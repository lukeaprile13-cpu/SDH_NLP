"""
Score the notebook against a human extraction sheet that uses the FINAL
variable names (the same columns as SDH_results.csv).

    python evaluation/compare_final.py --sheet path/to/SDH_Report_Extraction.xlsx \
        --out evaluation/output_final

Sheet: one row per report with the report number, the report text and one
column per final variable. Column names are matched after trimming spaces
and a few known spellings (see SHEET_ALIASES). Variables the sheet does not
have are skipped.

Writes <out>/field_scores.csv and <out>/differences.csv and prints a table.
The patient reports are NOT stored in the repo - pass their path in.
"""

import argparse
import contextlib
import io
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compare_to_human import load_notebook  # noqa: E402

REPORT_NUMBER_COLUMNS = ["report_num", "report #", "report_number"]
REPORT_TEXT_COLUMNS = ["report_whole", "report", "full _report", "full_report"]

# final column  ->  other names a sheet has used for it
SHEET_ALIASES = {
    "L_internal_appearance": ["L_internal_appearence"],
    "R_internal_appearance": ["R_internal_appearence"],
    "L_holohemispheric_hematoma": ["L_holohemispheric _ hematoma"],
    "R_holohemispheric_hematoma": ["R_holohemispheric _ hematoma"],
    "effacement_lateral_ventricle_laterality": ["l_ventricle_laterality"],
    "ventricular_prominence": ["l_ventricular_prominence"],
    "territorial_infarct": ["territorial_ infarct"],
    "unspecified_infarct": ["unspecified__infarct"],
    "calvarial_fracture_type": ["fracture_type_ordinal"],
    "paranasal_sinus": ["paranal_sinuses", "paranasal_sinuses"],
}

# measurements are compared once, in mm
SKIP_COLUMNS = {"L_thickness_cm", "R_thickness_cm", "parafalcine_thickness_cm",
                "tentorium_thickness_cm", "midline_shift_cm"}

NUMERIC_COLUMNS = {"L_thickness_mm", "R_thickness_mm", "parafalcine_thickness_mm",
                   "tentorium_thickness_mm", "midline_shift_mm"}

# wording that means the same thing
SAME = {
    "yes": "yes ns",              # graded columns: plain Yes = Yes NS
    "muscal thickening ns": "mucosal thickening ns",
    "dependent": "dependant",
    "unremarkable": "well aerated",
}


def norm(column, value):

    if value is None:
        return "nr"

    value = re.sub(r"\s+", " ", str(value).strip().lower())

    if value in ("", "nr", "nan", "<blank>"):
        return "nr"

    if column in NUMERIC_COLUMNS:
        try:
            return f"{float(value):g}"
        except ValueError:
            return value

    return SAME.get(value, value)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook", default=os.path.join(HERE, "..", "NLP_v5.ipynb"))
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--out", default=os.path.join(HERE, "output_final"))
    args = parser.parse_args()

    g = load_notebook(args.notebook)

    if args.sheet.endswith((".xlsx", ".xls")):
        sheet = pd.read_excel(args.sheet, dtype=str)
    else:
        sheet = pd.read_csv(args.sheet, dtype=str)

    sheet.columns = [c.strip() for c in sheet.columns]
    text_column = next(c for c in REPORT_TEXT_COLUMNS if c in sheet.columns)
    number_column = next(c for c in REPORT_NUMBER_COLUMNS if c in sheet.columns)
    sheet = sheet[sheet[text_column].notna()]

    final_columns = [name for name, _ in g["FINAL_COLUMNS"]]

    columns = {}
    for column in final_columns:
        if column in SKIP_COLUMNS:
            continue
        for name in [column] + SHEET_ALIASES.get(column, []):
            if name in sheet.columns:
                columns[column] = name
                break

    stats = {column: dict(ok=0, wrong=0, missed=0, extra=0) for column in columns}
    differences = []

    for _, report in sheet.iterrows():

        with contextlib.redirect_stdout(io.StringIO()):
            code = g["final_output"](g["run_report"](str(report[text_column])))

        for column, sheet_column in columns.items():

            h, c = norm(column, report.get(sheet_column)), norm(column, code.get(column))

            if h == "nr" and c == "nr":
                continue

            s = stats[column]

            if h == c:
                s["ok"] += 1
                continue

            if c == "nr":
                s["missed"] += 1
            elif h == "nr":
                s["extra"] += 1
            else:
                s["wrong"] += 1

            differences.append((str(report[number_column]).strip(), column,
                                report.get(sheet_column), code.get(column)))

    rows = []
    for column, s in stats.items():
        labelled = s["ok"] + s["wrong"] + s["missed"]
        emitted = s["ok"] + s["wrong"] + s["extra"]
        rows.append(dict(
            field=column, human_values=labelled, **s,
            recall=round(s["ok"] / labelled, 3) if labelled else None,
            precision=round(s["ok"] / emitted, 3) if emitted else None,
        ))

    scores = pd.DataFrame(rows)
    total = scores[["human_values", "ok", "wrong", "missed", "extra"]].sum()

    os.makedirs(args.out, exist_ok=True)
    scores.to_csv(os.path.join(args.out, "field_scores.csv"), index=False)
    pd.DataFrame(differences, columns=["report", "field", "human", "code"]).to_csv(
        os.path.join(args.out, "differences.csv"), index=False
    )

    print(scores.to_string(index=False))
    print(
        f"\nTOTAL  human values {total['human_values']}  ok {total['ok']}  "
        f"recall {total['ok'] / total['human_values']:.0%}  "
        f"precision {total['ok'] / (total['ok'] + total['wrong'] + total['extra']):.0%}"
    )


if __name__ == "__main__":
    main()
