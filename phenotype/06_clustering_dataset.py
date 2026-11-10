"""
STEP 6 - The clustering dataset, with every patient accounted for.

Applies the inclusion rules in CLUSTER_RULES (sdh_config.py) one at a time,
counting who is removed by each, keeps the clustering inputs (group A in
baseline_dictionary.csv), and reports missing data:
  - per variable: how many patients lack it (overall, by hospital, and for
    in-hospital onset, where triage variables are blank by design)
  - per patient: what share of the clustering variables they lack
Nobody is dropped for missing labs / vitals unless DROP_HIGH_MISSING_PATIENTS.

    python phenotype/06_clustering_dataset.py

Patient level: clustering_dataset.csv (row_id + kept clustering variables +
               patient_missing_pct); join outcomes.csv on row_id
Aggregate:     clustering_flowchart.csv, clustering_missingness_by_variable.csv,
               clustering_missingness_by_hospital.csv, clustering_patient_missingness.csv
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_io as io

key = io.read_patient_level("cohort_key.csv")
base = io.read_patient_level("baseline.csv")
dic = pd.read_csv(cfg.AGGREGATE_DIR / "baseline_dictionary.csv")
for c in [c for c in key if c.startswith("flag_")]:
    key[c] = key[c].astype(str).str.lower().eq("true")
key["confirmed"] = key.sdh_confirmed_on_ct.astype(str).str.lower().eq("true")
key["flag_no_ct_report"] = pd.to_numeric(key.n_head_ct_reports, errors="coerce").fillna(0) == 0

# ---------------------------------------------------------------------
# 1. Inclusion rules, one row per rule
# ---------------------------------------------------------------------
rules = {
    "radiology_collected": ("Radiology collected at that hospital and date (data coverage)",
                            lambda d: ~d.get("flag_radiology_not_collected", pd.Series(False, index=d.index))),
    "has_ct_report": ("Index episode has a head CT report", lambda d: ~d.flag_no_ct_report),
    "sdh_confirmed_on_ct": ("SDH confirmed on CT by the NLP", lambda d: d.confirmed),
    "in_study_period": (f"Admitted {cfg.STUDY_START} to before {cfg.STUDY_END}", lambda d: d.flag_in_study_period),
    "exclude_elective": ("Not an elective admission", lambda d: ~d.flag_elective),
    "exclude_er_only_sdh": ("SDH coded on the inpatient record", lambda d: ~d.flag_er_only_sdh),
    "exclude_in_hospital_onset": ("SDH present on arrival", lambda d: ~d.flag_in_hospital_onset),
}
d = key
flow = [{"step": "Patients in the cohort key (one index episode each)", "patients": len(d), "removed": 0}]
if not key.nlp_available.astype(str).str.lower().eq("true").all():
    print("WARNING: the cohort key was built before the NLP ran; 'SDH confirmed on CT' is skipped")
    rules.pop("sdh_confirmed_on_ct")
for name, on in cfg.CLUSTER_RULES.items():
    if not on or name not in rules:
        continue
    label, keep = rules[name]
    before = len(d)
    d = d[keep(d)]
    flow.append({"step": label, "patients": len(d), "removed": before - len(d)})

# ---------------------------------------------------------------------
# 2. Clustering variables and their missing data
# ---------------------------------------------------------------------
A = [v for v in dic.loc[dic.group.str.startswith("A"), "variable"] if v in base]
x = base[base.row_id.isin(d.row_id)].set_index("row_id")[A]
onset = d.set_index("row_id").flag_in_hospital_onset.reindex(x.index)
hosp = d.set_index("row_id").hospital_num.reindex(x.index)

# yes/no code flags (comorbidities, symptoms, meds) are never missing: no code = no
miss = []
for v in A:
    m = x[v].isna()
    k = int(m.sum())
    miss.append({"variable": v, "missing": k, "pct_missing": io.safe_pct(k, len(x)),
                 "pct_missing_came_in_with_sdh": io.safe_pct(int(m[~onset].sum()), int((~onset).sum())),
                 "pct_missing_in_hospital_onset": io.safe_pct(int(m[onset].sum()), int(onset.sum())),
                 "raw_pct": 100 * k / max(len(x), 1)})
miss = pd.DataFrame(miss)
miss["used_for_clustering"] = miss.raw_pct <= cfg.MAX_VARIABLE_MISSING_PCT
io.save_aggregate(miss.drop(columns="raw_pct").sort_values("missing", ascending=False),
                  "clustering_missingness_by_variable.csv", ["missing"])
kept = list(miss.loc[miss.used_for_clustering, "variable"])
set_aside = list(miss.loc[~miss.used_for_clustering, "variable"])
print(f"Clustering variables: {len(kept)} kept, {len(set_aside)} set aside "
      f"(missing in more than {cfg.MAX_VARIABLE_MISSING_PCT}%): {', '.join(set_aside) or 'none'}")

numeric_or_missable = [v for v in kept if x[v].isna().any()]
bh = x[numeric_or_missable].isna().groupby(hosp).mean().mul(100).round(1)
bh.insert(0, "patients", x.groupby(hosp).size())
bh.loc[bh.patients < cfg.SMALL_CELL, numeric_or_missable] = None
io.save_aggregate(bh.reset_index().rename(columns={"hospital_num": "hospital_num"}),
                  "clustering_missingness_by_hospital.csv", ["patients"])

# per patient: share of the kept clustering variables that are blank
x["patient_missing_pct"] = (100 * x[kept].isna().mean(axis=1)).round(1)
bins = pd.cut(x.patient_missing_pct, [-0.1, 0, 10, 25, 50, 100], labels=["none", "up to 10%", "10-25%", "25-50%", "over 50%"])
io.save_aggregate(bins.value_counts().sort_index().rename_axis("share_of_clustering_variables_missing")
                  .reset_index(name="patients"), "clustering_patient_missingness.csv", ["patients"])
high = x.patient_missing_pct > cfg.MAX_PATIENT_MISSING_PCT
x["flag_high_missing"] = high
if cfg.DROP_HIGH_MISSING_PATIENTS:
    flow.append({"step": f"Missing at most {cfg.MAX_PATIENT_MISSING_PCT}% of the clustering variables",
                 "patients": int((~high).sum()), "removed": int(high.sum())})
    x = x[~high]
else:
    print(f"{int(high.sum())} patients miss more than {cfg.MAX_PATIENT_MISSING_PCT}% of the clustering "
          "variables (flagged, kept)")

io.save_aggregate(pd.DataFrame(flow), "clustering_flowchart.csv", ["patients", "removed"])
for f in flow:
    print(f"{f['step']}: {f['patients']} (removed {f['removed']})")
io.save_patient_level(x[kept + ["patient_missing_pct", "flag_high_missing"]].reset_index(), "clustering_dataset.csv")
print("Outcomes for the same patients: outcomes.csv, joined on row_id")
