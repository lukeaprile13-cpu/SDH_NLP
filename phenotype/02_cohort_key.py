"""
STEP 2 - Cohort key: one row per patient, with time zero and the index CT.

Uses the NLP results on every head CT report (step 1) to
  - confirm the SDH on imaging (any CT of the episode shows one),
  - find the index CT: the first CT showing the SDH,
  - set time zero: ER arrival (or admission) for patients who came in with
    the SDH; the index CT for SDH that developed in hospital,
  - pick each patient's index episode: their first episode with the SDH
    confirmed on CT (or their first episode, flagged, when none is).
Before the NLP has been run it falls back to "first CT with a report" and
says so (nlp_available = False); run it again once the NLP results exist.

    python phenotype/02_cohort_key.py

Writes patient_level/cohort_key.csv (one row per patient) and
aggregate/step2_counts.csv.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_io as io

ep = io.read_patient_level("episodes.csv")
cti = io.read_patient_level("ct_reports_index.csv")
for c in ("admission_date_time", "er_triage_date_time"):
    ep[c] = io.to_dt(ep[c])
for c in [c for c in ep if c.startswith("flag_")]:
    ep[c] = ep[c].astype(str).str.lower().eq("true")

# ---------------------------------------------------------------------
# 1. SDH on each CT (NLP)
# ---------------------------------------------------------------------
nlp = None
if cfg.NLP_RESULTS_FILE.exists():
    nlp = pd.read_csv(cfg.NLP_RESULTS_FILE, dtype=str)
    nlp = nlp.rename(columns={nlp.columns[0]: "report_id"})
    col = lambda c: nlp[c].fillna("").str.strip() if c in nlp else pd.Series("", index=nlp.index)
    nlp["sdh_on_ct"] = col("laterality").isin(cfg.NLP_SDH_LATERALITY)
    for c in cfg.NLP_SDH_COMPARTMENTS:
        nlp["sdh_on_ct"] |= ~col(c).isin(cfg.NLP_ABSENT_VALUES)
    if "error" in nlp:
        print(f"  {(nlp.error.fillna('') != '').sum()} reports had an NLP error (counted as no SDH)")
    # the NLP results must come from these exact reports (step 1 renumbers them when rerun)
    if "report_hash" not in nlp or "report_hash" not in cti:
        sys.exit("The NLP results or ct_reports_index.csv have no report fingerprint (made with an older "
                 "version): rerun notebook 01, delete ct_reports_nlp_results.csv and rerun the NLP.")
    chk = cti[["report_id", "report_hash"]].merge(nlp[["report_id", "report_hash"]], on="report_id", how="inner")
    bad = (chk.report_hash_x != chk.report_hash_y).sum()
    if bad:
        sys.exit(f"{bad} NLP results do not match the current reports (step 1 was rerun after the NLP). "
                 "Delete ct_reports_nlp_results.csv and rerun the NLP.")
    cti = cti.merge(nlp[["report_id", "sdh_on_ct"]], on="report_id", how="left")
    print(f"NLP results: {len(nlp)} reports, {int(nlp.sdh_on_ct.sum())} show an SDH")
    missing = cti.sdh_on_ct.isna().sum()
    if missing:
        print(f"  {missing} reports have no NLP result (treated as not showing an SDH)")
    cti["sdh_on_ct"] = cti.sdh_on_ct.fillna(False).astype(bool)
else:
    print(f"No NLP results at {cfg.NLP_RESULTS_FILE}: FALLBACK - every CT report counts as showing the SDH.")
    cti["sdh_on_ct"] = True
nlp_available = nlp is not None

# ---------------------------------------------------------------------
# 2. Index CT, confirmation and time zero per episode
# ---------------------------------------------------------------------
cti = cti.merge(ep[["episode", "flag_in_hospital_onset"]], on="episode", how="left")
cti["h"] = pd.to_numeric(cti.hours_from_episode_admission, errors="coerce")
in_window = cti.h.between(-cfg.CT_WINDOW_BEFORE_H, cfg.CT_WINDOW_AFTER_H)
after_admit = cti.h >= 0
# came in with it: first positive CT in the window around arrival (else any later one)
# developed in hospital: first positive CT after admission
cti["rank"] = (~cti.sdh_on_ct) * 4 + (~cti.flag_in_hospital_onset & ~in_window) * 2 \
    + (cti.flag_in_hospital_onset & ~after_admit) * 2
cti = cti.sort_values(["episode", "rank", "performed_date_time"])
pos = cti[cti.sdh_on_ct]
idx = pos.groupby("episode").head(1).set_index("episode")

e = ep.set_index("episode")
e["sdh_confirmed_on_ct"] = pd.Series(e.index.isin(pos.episode), index=e.index).astype("boolean") \
    .where(e.n_head_ct_reports > 0)                      # unknown when there is no report
if not nlp_available:
    e["sdh_confirmed_on_ct"] = pd.NA
e["index_ct_report_id"] = idx.report_id
e["index_ct_genc_id"] = idx.genc_id
e["index_ct_name"] = idx.test_name_raw
e["index_ct_date_time"] = idx.performed_date_time
e["index_ct_hours_from_admission"] = idx.h
e["index_ct_outside_window"] = (idx["rank"] % 4 > 0).reindex(e.index)

tri_h = io.hours_between(e.er_triage_date_time, e.admission_date_time)
arrival = e.er_triage_date_time.where(tri_h.between(*cfg.TRIAGE_WINDOW_H), e.admission_date_time)
e["time_zero"] = arrival.where(~e.flag_in_hospital_onset, e.index_ct_date_time)
e["time_zero_source"] = "admission"
e.loc[tri_h.between(*cfg.TRIAGE_WINDOW_H), "time_zero_source"] = "er_triage"
e.loc[e.flag_in_hospital_onset, "time_zero_source"] = "diagnosis_ct"
e.loc[e.flag_in_hospital_onset & e.time_zero.isna(), "time_zero_source"] = "missing (no CT)"
e["hours_t0_to_index_ct"] = io.hours_between(e.index_ct_date_time, e.time_zero).round(1)
e["hours_admission_to_sdh_diagnosis"] = e.index_ct_hours_from_admission.where(e.flag_in_hospital_onset)
ep = e.reset_index()

# ---------------------------------------------------------------------
# 3. Index episode per patient
# ---------------------------------------------------------------------
ep["confirmed"] = ep.sdh_confirmed_on_ct.fillna(False).astype(bool)
if nlp_available:
    ep = ep.sort_values(["patient_id_hashed", "confirmed", "admission_date_time"], ascending=[True, False, True])
    key = ep.groupby("patient_id_hashed").head(1).copy()
    key["index_episode_rule"] = key.confirmed.map({True: "first confirmed episode",
                                                   False: "first episode (none confirmed)"})
else:
    key = ep.sort_values(["patient_id_hashed", "admission_date_time"]).groupby("patient_id_hashed").head(1).copy()
    key["index_episode_rule"] = "first episode (NLP not run yet)"
key["flag_sdh_not_confirmed_on_ct"] = key.sdh_confirmed_on_ct.eq(False).fillna(False).astype(bool)
key["n_episodes_for_patient"] = key.patient_id_hashed.map(ep.groupby("patient_id_hashed").size())
key["later_episodes"] = key.n_episodes_for_patient - key.episode_number_for_patient
key["nlp_available"] = nlp_available
key["admission_year"] = key.admission_date_time.dt.year
key = key.sort_values("patient_id_hashed").reset_index(drop=True)
key["row_id"] = ["SDH%05d" % (i + 1) for i in range(len(key))]
key = key.drop(columns=["confirmed"])
key = key[["row_id"] + [c for c in key if c != "row_id"]]
io.save_patient_level(key, "cohort_key.csv")

flags = [c for c in key if c.startswith("flag_")]
rows = [("Patients (index episode each)", len(key))]
rows += [(f"  {c[5:]}", int(key[c].sum())) for c in flags]
rows += [(f"  index episode: {r}", n) for r, n in key.index_episode_rule.value_counts().items()]
rows += [(f"  time zero from {r}", n) for r, n in key.time_zero_source.value_counts().items()]
rows += [(f"  {t}", n) for t, n in key.sdh_type.value_counts().items()]
io.save_aggregate(pd.DataFrame(rows, columns=["description", "patients"]), "step2_counts.csv", ["patients"])
for r in rows:
    print(f"{r[0]}: {r[1]}")
print("Next: python phenotype/03_baseline.py")
