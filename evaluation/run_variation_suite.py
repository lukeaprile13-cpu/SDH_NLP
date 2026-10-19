"""
Run the variation suite: constructed sentences (not patient reports) with
the values the extraction conventions say they should produce.

    python evaluation/run_variation_suite.py [--notebook NLP_v5.ipynb]

Prints PASS n/N and every failing sentence with the wanted and produced
value. Run it after every rule change, together with the scored sheets.
"""

import argparse
import collections
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compare_to_human import load_notebook  # noqa: E402
from variation_suite import CASES  # noqa: E402


def norm(value):
    value = str(value).strip()
    try:
        return f"{float(value):g}"
    except ValueError:
        return value


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook", default=os.path.join(HERE, "..", "NLP_v5.ipynb"))
    args = parser.parse_args()

    g = load_notebook(args.notebook)

    failures = collections.defaultdict(list)
    totals = collections.Counter()

    for family, text, expected in CASES:
        with contextlib.redirect_stdout(io.StringIO()):
            row = g["final_output"](g["run_report"](text))
        totals[family] += 1
        wrong = {k: (v, row.get(k, "MISSING")) for k, v in expected.items() if norm(row.get(k, "NR")) != norm(v)}
        if wrong:
            failures[family].append((text, wrong))

    failed = sum(len(f) for f in failures.values())
    print(f"PASS {len(CASES) - failed}/{len(CASES)}")

    for family in totals:
        rows = failures.get(family, [])
        print(f"  {family:14} {totals[family] - len(rows)}/{totals[family]}")
        for text, wrong in rows:
            print(f"    - {text}")
            for column, (want, got) in wrong.items():
                print(f"        {column}: want {want!r}, got {got!r}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
