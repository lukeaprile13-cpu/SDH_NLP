"""
STEP 4 - One analysis dataset, plus shareable descriptive tables.

    python phenotype/04_tables_and_checks.py

Patient level:  patient_level/analysis_dataset.parquet (one row per patient;
                NLP output is added later, joined on row_id)
Aggregate (cell-suppressed, safe to share outside GEMINI):
    table1_by_stratum.csv      descriptives: overall, traumatic, non-traumatic
    table2_by_pathway.csv      the same by treatment pathway
    coverage_by_hospital.csv   % of patients with each key variable, per hospital
    coverage_by_year.csv       the same per admission year
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_io as io

co = io.read_patient_level("cohort.parquet")
base = io.read_patient_level("baseline_features.parquet").drop(columns="row_id")
path = io.read_patient_level("pathways_outcomes.parquet").drop(columns="row_id")
df = co.merge(base, on="patient_id_hashed", how="left").merge(path, on="patient_id_hashed", how="left")
io.save_patient_level(df, "analysis_dataset.parquet")

SKIP = ("row_id", "episode", "patient_id_hashed", "genc", "date_time", "time_zero", "index_ct_name",
        "hospitals_in_episode", "hospital_num", "surgery_hospital", "first_surgery_code", "sdh_ip_dx_types",
        "discharge_disposition_raw", "institution_from", "_hours_from_t0", "nbhd_sc16_c16_popdw")


def describe(d, groups):
    """Rows: variable / level; columns: n (%) or median [IQR] per group; small cells suppressed."""
    rows = []
    n_by = {g: len(x) for g, x in groups.items()}
    rows.append({"variable": "Patients", "level": "", **{g: io.suppress(n) for g, n in n_by.items()}})
    for col in d.columns:
        if any(s in col for s in SKIP):
            continue
        s = d[col]
        num = pd.to_numeric(s, errors="coerce") if s.dtype != bool else None
        is_bool = str(s.dtype) in ("bool", "boolean") or (
            s.dtype == object and s.notna().any() and s.dropna().map(lambda v: isinstance(v, bool)).all())
        if is_bool:
            cell = {}
            for g, x in groups.items():
                v = x[col].dropna().astype(bool)
                k, n = int(v.sum()), len(v)
                cell[g] = (f"{io.suppress(k)} ({100 * k / n:.1f}%)" if n and (k == 0 or k >= cfg.SMALL_CELL)
                           and (n - k == 0 or n - k >= cfg.SMALL_CELL) else io.suppress(k) if n else "")
            rows.append({"variable": col, "level": "yes", **cell})
        elif num is not None and num.notna().mean() > 0.5 * s.notna().mean() and num.nunique() > 7:
            cell = {}
            for g, x in groups.items():
                v = pd.to_numeric(x[col], errors="coerce").dropna()
                cell[g] = (f"{v.median():.1f} [{v.quantile(.25):.1f}-{v.quantile(.75):.1f}]"
                           if len(v) >= cfg.SMALL_CELL else "")
            rows.append({"variable": col, "level": "median [IQR]", **cell})
            miss = {g: io.suppress(int(x[col].isna().sum())) for g, x in groups.items()}
            rows.append({"variable": col, "level": "missing (n)", **miss})
        elif s.astype("string").nunique() <= 12:
            for lev in sorted(s.dropna().astype(str).unique()) + ["(missing)"]:
                cell = {}
                for g, x in groups.items():
                    v = x[col].astype("string")
                    k = int(v.isna().sum()) if lev == "(missing)" else int((v == lev).sum())
                    cell[g] = f"{io.suppress(k)} ({100 * k / len(x):.1f}%)" if k == 0 or k >= cfg.SMALL_CELL \
                        else io.suppress(k)
                rows.append({"variable": col, "level": lev, **cell})
    return pd.DataFrame(rows)


strata = {"overall": df, "traumatic": df[df.stratum == "traumatic"],
          "nontraumatic": df[df.stratum == "nontraumatic"]}
io.save_aggregate(describe(df, strata), "table1_by_stratum.csv")
paths = {"overall": df, **{p: df[df.pathway == p] for p in sorted(df.pathway.dropna().unique())}}
io.save_aggregate(describe(df, paths), "table2_by_pathway.csv")

KEY = ["ctas", "mlaps_24h", "gcs", "sbp", "heart_rate", "inr", "platelets", "hemoglobin", "creatinine",
       "sodium", "glucose", "nbhd_sc21_material_resources_q_DA21", "hours_triage_to_admission"]
KEY = [k for k in KEY if k in df]
for by, name in (("hospital_num", "coverage_by_hospital.csv"), ("admission_year", "coverage_by_year.csv")):
    g = df.groupby(by)
    cov = g.size().rename("patients").to_frame()
    for k in KEY:
        cov[f"pct_{k}"] = (100 * g[k].apply(lambda s: s.notna().mean())).round(1)
    cov = cov.reset_index()
    cov.loc[cov.patients < cfg.SMALL_CELL, [c for c in cov if c.startswith("pct_")]] = None
    if by == "hospital_num":
        cov = cov.merge(df.groupby("hospital_num").hospital_type.first().reset_index(), on="hospital_num")
    io.save_aggregate(cov, name, ["patients"])
print("Done. Share only the files in", cfg.AGGREGATE_DIR)
