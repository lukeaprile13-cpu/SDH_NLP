"""
Run the NLP notebook over a set of reports and compare every variable with
the human-extracted sheet.

    python evaluation/compare_to_human.py \
        --reports path/to/Reports.CSV.xlsx \
        --gold path/to/vaiables_final.csv \
        --out evaluation/output

Reports file: columns  report_num, full _report   (.xlsx or .csv)
Gold file:    columns  report_num, <one column per variable>

Writes <out>/field_scores.csv and <out>/differences.csv and prints a table.
The patient reports are NOT stored in the repo - pass their paths in.
"""

import argparse
import contextlib
import io
import json
import os
import re

import pandas as pd


HERE = os.path.dirname(os.path.abspath(__file__))

# cells that run the example report / install packages, not definitions
# (matched at the start of a line, so calls inside functions do not count)
RUN_CELL_MARKERS = re.compile(
    r'^(!\{sys\.executable\}|print\(sys\.executable\)|report = """|'
    r"sentence_lists = tokenize_report\(report\)|main_tree = orchestrator\(|"
    r"final_variables = master_variable_mapping_function\()",
    re.MULTILINE,
)

# array key  ->  column on the human sheet
FIELDS = {
    "laterality": "laterality",
    "L_description": "L_description", "L_acuity": "L_acuity", "L_mixed_density": "L_mixed_density",
    "L_morphology": "L_internal_appearence", "L_hyper_dense": "L_hyperdense", "L_hypo_dense": "L_hypodense",
    "L_iso_dense": "L_isodense", "L_thickness_max": "L_thickness_max", "L_thickness": "L_thickness",
    "L_convexity_hematoma": "L_convexity_hematoma", "L_holohemispheric_hematoma": "L_holohemispheric _ hematoma",
    "L_vertex": "L_vertex", "L_frontal_lobe": "L_frontal_lobe", "L_parietal_lobe": "L_parietal_lobe",
    "L_temporal_lobe": "L_temporal_lobe", "L_occipital_lobe": "L_occipital_lobe",
    "R_description": "R_description", "R_acuity": "R_acuity", "R_mixed_density": "R_density_uniformity",
    "R_morphology": "R_internal_appearence", "R_hyper_dense": "R_hyperdense", "R_hypo_dense": "R_hypodense",
    "R_iso_dense": "R_isodense", "R_thickness_max": "R_thickness_max", "R_thickness": "R_thickness",
    "R_convexity_hematoma": "R_convexity_hematoma", "R_holohemispheric_hematoma": "R_holohemispheric _ hematoma",
    "R_vertex": "R_vertex", "R_frontal_lobe": "R_frontal_lobe", "R_parietal_lobe": "R_parietal_lobe",
    "R_temporal_lobe": "R_temporal_lobe", "R_occipital_lobe": "R_occipital_lobe",
    "parafalcine_hematoma": "parafalcine_hematoma", "tentorium_hematoma": "tentorium_hematoma",
    "mass_effect_present": "mass_effect_present", "midline_shift_present": "midline_shift_present",
    "midline_shift": "midline_shift", "midline_shift_direction": "midline_shift_direction",
    "effacement_sulci": "effacement_sulci", "effacement_sulci_laterality": "effacement_sulci_laterality",
    "effacement_ventricular_system": "effacement_ventricular_system",
    "effacement_lateral_ventricle": "effacement_lateral_ventricle", "l_ventricle_laterality": "l_ventricle_laterality",
    "ventricular_prominence": "l_ventricular_prominence", "ex_vacuo_dilatation": "ex_vacuo_ventriculomegaly",
    "effacement_cisterns": "effacement_basal_cistern",
    "herniation_subfalcine": "herniation_subfalcine", "herniation_uncal": "herniation_uncal",
    "herniation_transtentorial": "herniation_transtentorial", "herniation_tonsillar": "herniation_tonsillar",
    "hydrocephalus": "hydrocephalus", "microangiopathy": "microangiopathy", "cerebral_atrophy": "cerebral_atrophy",
    "white_dark_differentiation": "white_dark_differentiation", "mass": "mass",
    "territorial_infarct": "territorial_ infarct", "lacunar_infarct": "lacune_infarct",
    "unspecified_infarct": "unspecified__infarct",
    "bony_lesion": "bony_lesion", "skull_fracture": "skull_fracture", "scalp_hematoma": "scalp_hematoma",
    "soft_tissue_lesion": "soft_tissue_lesion", "orbital_lesion": "orbital_lesion",
    "subarachnoid_hemorrhage": "subarachnoid_hemorrhage", "intraparenchymal_hemorrhage": "intraparenchymal_hemorrhage",
    "intraventricular_hemorrhage": "intraventricular_hemorrhage",
    "paranasal_sinuses": "paranal_sinuses", "mastoid_air_cells": "mastoid_air_cells",
}

# other names the human sheet has used for the same column
COLUMN_ALIASES = {
    "R_density_uniformity": ["R_mixed_density"],
    "intraparenchymal_hemorrhage": ["parenchymal_hemorrhage"],
    "skull_fracture": ["calvarial_fracture_present"],
}

REPORT_NUMBER_COLUMNS = ["report_num", "report #", "report_number"]
REPORT_TEXT_COLUMNS = ["full _report", "full_report", "report"]

# wording differences that are not extraction errors
EQUIV = {"dependent": "dependant", "mixed": "yes ns", "yes": "yes ns", "preserved": "yes ns",
         "acute and subacute": "acute/subacute"}


def load_notebook(path):

    nb = json.load(open(path))
    namespace = {}

    for cell in nb["cells"]:

        if cell["cell_type"] != "code":
            continue

        source = "".join(cell["source"])

        if RUN_CELL_MARKERS.search(source):
            continue

        exec(compile(source, path, "exec"), namespace)

    return namespace


def norm(field, value):

    if value is None:
        return "nr"

    value = str(value).strip()

    if value == "" or value.lower() in ("nr", "nan"):
        return "nr"

    value = re.sub(r"\s+", " ", value.lower())

    if field in ("L_description", "R_description"):
        return "medium" if value in ("moderate", "medium") else value

    if field in ("soft_tissue_lesion", "orbital_lesion"):
        return "no" if value in ("normal", "unremarkable", "no") else value

    if field in ("paranasal_sinuses", "mastoid_air_cells"):
        return "clear" if value in ("well aerated", "unremarkable", "clear", "normal") else value

    return EQUIV.get(value, value)


def to_mm(row, mm_key, cm_key):

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    mm, cm = num(row.get(mm_key)), num(row.get(cm_key))

    if mm is not None:
        return round(mm, 2)

    if cm is not None:
        return round(cm * 10, 2)

    return None


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook", default=os.path.join(HERE, "..", "NLP_v5.ipynb"))
    parser.add_argument("--reports", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--out", default=os.path.join(HERE, "output"))
    args = parser.parse_args()

    g = load_notebook(args.notebook)

    if args.reports.endswith((".xlsx", ".xls")):
        reports = pd.read_excel(args.reports, dtype=str)
    else:
        reports = pd.read_csv(args.reports, dtype=str)

    reports.columns = [c.strip() for c in reports.columns]
    number_column = next(c for c in REPORT_NUMBER_COLUMNS if c in reports.columns)
    text_column = next(c for c in REPORT_TEXT_COLUMNS if c in reports.columns)

    gold = pd.read_csv(args.gold, dtype=str).dropna(how="all")
    gold.columns = [c.strip() for c in gold.columns]
    gold["report_num"] = gold["report_num"].str.strip()

    # the same report number can appear twice for different reports;
    # when both files have the "#" column, match on that instead
    key_column = "report_num"
    if "#" in gold.columns and "#" in reports.columns and gold["report_num"].duplicated().any():
        key_column = "#"
        number_column = "#"
        gold["#"] = gold["#"].str.strip()

    gold = gold.set_index(key_column)

    # use whichever name this sheet has; fields the sheet does not have are skipped
    columns = {}
    for field, column in FIELDS.items():
        for name in [column] + COLUMN_ALIASES.get(column, []):
            if name in gold.columns or name in ("L_thickness", "R_thickness", "midline_shift"):
                columns[field] = name
                break

    stats = {field: dict(ok=0, wrong=0, missed=0, extra=0) for field in FIELDS}
    differences = []

    for _, report in reports.iterrows():

        number = str(report[number_column]).strip()

        if number not in gold.index:
            continue

        human = gold.loc[number].to_dict()

        with contextlib.redirect_stdout(io.StringIO()):
            code = dict(g["run_report"](str(report[text_column])))

        for row in (human, code):
            row["L_thickness"] = to_mm(row, "L_thickness_mm", "L_thickness_cm")
            row["R_thickness"] = to_mm(row, "R_thickness_mm", "R_thickness_cm")
            row["midline_shift"] = to_mm(row, "midline_shift_mm", "midline_shift_cm")

        for field, column in columns.items():

            h, c = norm(field, human.get(column)), norm(field, code.get(field))

            if h == "nr" and c == "nr":
                continue

            s = stats[field]

            if h == c:
                s["ok"] += 1
                continue

            if c == "nr":
                s["missed"] += 1
            elif h == "nr":
                s["extra"] += 1
            else:
                s["wrong"] += 1

            differences.append((number, field, human.get(column), code.get(field)))

    rows = []
    for field, s in stats.items():
        if field not in columns:
            continue
        labelled = s["ok"] + s["wrong"] + s["missed"]
        emitted = s["ok"] + s["wrong"] + s["extra"]
        rows.append(dict(
            field=field, human_values=labelled, **s,
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
