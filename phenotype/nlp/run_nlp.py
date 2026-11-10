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
"""
import argparse
import contextlib
import io
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import sdh_config as cfg

NOTEBOOK = HERE / "NLP_v5_snapshot.ipynb"
_ns = {}


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


def _init(notebook):
    global _ns
    _ns = load_nlp(notebook)


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
        row = {"report_id": report_id, "episode": episode}
        try:
            row.update(run_one(text))
            row["error"] = ""
        except Exception as error:          # this report gets NR everywhere, the error is kept
            row.update(_ns["final_output"]({}))
            row["error"] = f"{type(error).__name__}: {error}"
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
    a = ap.parse_args()

    reports = pd.read_csv(a.input, dtype=str, keep_default_na=False)
    reports = reports[reports.report.str.strip() != ""]
    if a.limit:
        reports = reports.head(a.limit)
    out_path, partial = Path(a.output), Path(a.output + ".partial")
    done = set()
    if partial.exists():
        done = set(pd.read_csv(partial, dtype=str, usecols=["report_id"]).report_id)
        print(f"Resuming: {len(done)} reports already done")
    todo = reports[~reports.report_id.isin(done)]
    rows = list(zip(todo.report_id, todo.episode, todo.report))
    chunks = [rows[i:i + a.chunk] for i in range(0, len(rows), a.chunk)]
    print(f"{len(rows)} reports to run in {len(chunks)} chunks with {a.workers} workers")

    start, n = time.time(), 0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.notebook,)) as pool:
        for res in pool.map(run_chunk, chunks):
            pd.DataFrame(res).to_csv(partial, mode="a", header=not partial.exists(), index=False)
            n += len(res)
            rate = n / max(time.time() - start, 1e-9)
            print(f"  {n + len(done)}/{len(reports)} reports  ({rate:.0f}/s, "
                  f"about {(len(rows) - n) / max(rate, 1e-9) / 60:.0f} min left)", flush=True)

    res = pd.read_csv(partial, dtype=str, keep_default_na=False).drop_duplicates("report_id", keep="last")
    res.to_csv(out_path, index=False)
    partial.unlink()
    errors = (res.error != "").sum()
    print(f"Done: {len(res)} reports -> {out_path} ({errors} with errors)")


if __name__ == "__main__":
    main()
