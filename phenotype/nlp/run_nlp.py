"""
Run the SDH NLP (a fixed snapshot of NLP_v5.ipynb) on every CT report from
step 1, in batch.

    python phenotype/nlp/run_nlp.py                 # all reports, 4 workers
    python phenotype/nlp/run_nlp.py --workers 8
    python phenotype/nlp/run_nlp.py --limit 200     # a quick test on the first 200

Input:  patient_level/ct_reports_for_nlp.csv   (report_id, episode, report)
Output: patient_level/ct_reports_nlp_results.csv
        report_id, episode, every NLP variable, error  (no report text)

The notebook's definitions (everything before "RUN FUNCTIONS") are run once
per worker; each report then goes through the same calls as the notebook's
run_csv: tokenize_report -> orchestrator -> master_variable_mapping_function
-> final_output. Progress is saved every chunk, so a stopped run picks up
where it left off when started again.

If a worker process dies (usually out of memory), the unfinished reports
are retried in smaller batches with one worker fewer each time; a report
that crashes the NLP on its own, or runs longer than --timeout seconds, is
recorded with an error instead of stopping the run.
"""
import argparse
import contextlib
import io
import json
import signal
import sys
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import sdh_config as cfg
from sdh_io import report_hash

NOTEBOOK = HERE / "NLP_v5_snapshot.ipynb"
_ns = {}
_timeout = 60


class ReportTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise ReportTimeout()


def load_nlp(notebook=NOTEBOOK):
    """Run the notebook's definition cells (up to '# RUN FUNCTIONS') into a namespace."""
    cells = json.loads(Path(notebook).read_text())["cells"]
    ns = {"__name__": "sdh_nlp"}
    for cell in cells:
        src = "".join(cell["source"])
        if cell["cell_type"] == "markdown" and src.strip().startswith("# RUN FUNCTIONS"):
            break
        if cell["cell_type"] != "code":
            continue
        # notebook-only lines: shell / magic commands
        src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(("!", "%")))
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(src, f"{Path(notebook).name}", "exec"), ns)
    for f in ("tokenize_report", "orchestrator", "master_variable_mapping_function", "final_output"):
        if f not in ns:
            sys.exit(f"{f} not found in {notebook}: has the notebook changed shape?")
    return ns


def _init(notebook, timeout):
    global _ns, _timeout
    # workers started by fork (Linux) inherit the NLP already loaded by main();
    # loading it twice in one process makes spaCy refuse to re-register its components
    if not _ns:
        _ns = load_nlp(notebook)
    _timeout = timeout
    signal.signal(signal.SIGALRM, _alarm)


def run_one(text, ns=None):
    ns = ns or _ns
    with contextlib.redirect_stdout(io.StringIO()):
        sentence_lists = ns["tokenize_report"](text)
        trees = [ns["orchestrator"](sentence_lists)]
        variables = ns["master_variable_mapping_function"](trees)
    return dict(ns["final_output"](variables))


def run_chunk(rows):
    out = []
    for report_id, episode, text in rows:
        row = {"report_id": report_id, "report_hash": report_hash(text), "episode": episode}
        signal.alarm(_timeout)
        try:
            row.update(run_one(text))
            row["error"] = ""
        except ReportTimeout:
            row.update(_ns["final_output"]({}))
            row["error"] = f"timeout: still running after {_timeout} s"
        except Exception as error:          # this report gets NR everywhere, the error is kept
            row.update(_ns["final_output"]({}))
            row["error"] = f"{type(error).__name__}: {error}"
        finally:
            signal.alarm(0)
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(cfg.PATIENT_DIR / "ct_reports_for_nlp.csv"))
    ap.add_argument("--output", default=str(cfg.NLP_RESULTS_FILE))
    ap.add_argument("--notebook", default=str(NOTEBOOK))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=int, default=60, help="seconds before one report is given up")
    a = ap.parse_args()

    reports = pd.read_csv(a.input, dtype=str, keep_default_na=False)
    reports = reports[reports.report.str.strip() != ""]
    if a.limit:
        reports = reports.head(a.limit)
    out_path, partial = Path(a.output), Path(a.output + ".partial")
    # resume only reports whose id AND text fingerprint match (step 1 renumbers reports when rerun)
    reports["report_hash"] = reports.report.map(report_hash)
    key = reports.report_id + "|" + reports.report_hash
    done = set()
    if partial.exists():
        old = pd.read_csv(partial, dtype=str, keep_default_na=False)
        if "report_hash" not in old:
            old["report_hash"] = ""
        done = set(old.report_id + "|" + old.report_hash) & set(key)
        if len(done) < len(old):
            print(f"{len(old) - len(done)} saved results belong to an older set of reports: they are redone")
            old[(old.report_id + "|" + old.report_hash).isin(done)].to_csv(partial, index=False)
        print(f"Resuming: {len(done)} reports already done")
    todo = reports[~key.isin(done)]
    rows = list(zip(todo.report_id, todo.episode, todo.report))
    chunks = [rows[i:i + a.chunk] for i in range(0, len(rows), a.chunk)]
    print(f"{len(rows)} reports to run in {len(chunks)} chunks with {a.workers} workers")

    # load the NLP once here first, so a setup problem (e.g. a missing package) stops
    # the run with a clear message instead of looking like crashed workers
    global _ns
    try:
        main_ns = _ns = load_nlp(a.notebook)
    except Exception as error:
        sys.exit(f"The NLP could not be loaded from {a.notebook}: {type(error).__name__}: {error}")

    start, n, workers = time.time(), 0, max(1, a.workers)
    queue = deque(chunks)

    def write(res):
        nonlocal n
        pd.DataFrame(res).to_csv(partial, mode="a", header=not partial.exists(), index=False)
        n += len(res)
        rate = n / max(time.time() - start, 1e-9)
        print(f"  {n + len(done)}/{len(reports)} reports  ({rate:.0f}/s, "
              f"about {(len(rows) - n) / max(rate, 1e-9) / 60:.0f} min left)", flush=True)

    while queue:
        # with one worker, one batch at a time, so a crash points at that batch
        in_flight = workers * 2 if workers > 1 else 1
        pool = ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(a.notebook, a.timeout))
        running, lost = {}, []
        while (queue or running) and not lost:
            while queue and len(running) < in_flight:
                c = queue.popleft()
                running[pool.submit(run_chunk, c)] = c
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for f in finished:
                c = running.pop(f)
                try:
                    write(f.result())
                except BrokenProcessPool:
                    lost.append(c)
        pool.shutdown(wait=False, cancel_futures=True)
        if not lost:
            continue
        lost += list(running.values())
        if workers == 1 and len(lost) == 1 and len(lost[0]) == 1:
            # this one report crashes the NLP by itself: record it and move on
            report_id, episode, text = lost[0][0]
            print(f"  report {report_id} crashes the NLP: recorded as an error")
            write([{"report_id": report_id, "report_hash": report_hash(text), "episode": episode,
                    **main_ns["final_output"]({}), "error": "worker crashed on this report"}])
            continue
        n_lost = sum(len(c) for c in lost)
        workers = max(1, workers - 1)
        for c in reversed(lost):            # retry first, in halves
            half = max(1, len(c) // 2)
            for part in reversed([c[i:i + half] for i in range(0, len(c), half)]):
                queue.appendleft(part)
        print(f"  A worker stopped (usually out of memory, or one report crashed it). Retrying {n_lost} "
              f"reports in smaller batches with {workers} worker(s).", flush=True)

    res = pd.read_csv(partial, dtype=str, keep_default_na=False).drop_duplicates("report_id", keep="last")
    res.to_csv(out_path, index=False)
    partial.unlink()
    errors = (res.error != "").sum()
    print(f"Done: {len(res)} reports -> {out_path} ({errors} with errors)")


if __name__ == "__main__":
    main()
