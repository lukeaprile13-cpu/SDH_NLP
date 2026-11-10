"""
STEP 1 - Phenotype cohort: one row per patient = their first SDH episode.

Starts from the GEMINI SDH extraction (every adult encounter with an SDH
code) and applies the phenotype study rules: study period, SDH on the
inpatient abstract and present on arrival, transfers joined into one
episode of care (GEMINI's epicare), first episode per patient, time zero
(arrival) and the index head CT whose report the NLP reads.

    python phenotype/01_build_cohort.py

Patient level (OUTPUT_DIR/patient_level, stays on GEMINI):
    cohort.parquet                one row per patient
    episode_encounters.parquet    the encounters in each index episode
    index_ct_reports_for_nlp.csv  row_id, genc_id, report: the NLP input
Aggregate (OUTPUT_DIR/aggregate, cell-suppressed):
    flowchart.csv, check_ct_names.csv, check_ct_coverage_by_hospital_year.csv
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_io as io

flow = []


def step(label, d, note=""):
    flow.append({"step": len(flow) + 1, "description": label, "patients": d.patient_id_hashed.nunique(),
                 "encounters": d.genc_id.nunique(), "note": note})
    print(f"[{len(flow)}] {label}: {flow[-1]['patients']} patients, {flow[-1]['encounters']} encounters")


# ---------------------------------------------------------------------
# 1. Cohort encounters with what the rules need
# ---------------------------------------------------------------------
enc = io.load("cohort")
extra = io.load("encounters", ["genc_id", "admission_ts", "discharge_ts", "er_triage_ts", "admit_category",
                               "institution_from", "admit_via_ambulance", "gender", "hospital_hospital_type",
                               "dv_epicare"])
enc = enc.merge(extra, on="genc_id", how="left")
enc["admit"] = io.to_dt(enc["admission_ts"]).fillna(io.to_dt(enc["admission_date_time"]))
enc["discharge"] = io.to_dt(enc["discharge_ts"])
enc["triage"] = io.to_dt(enc["er_triage_ts"])

b = lambda c: enc[c].fillna(False).astype(bool)
enc["sdh_inpatient"] = b("sdh_traumatic_inpatient") | b("sdh_nontraumatic_inpatient")
types = enc["sdh_ip_dx_types"].fillna("").astype(str).str.upper()
# present on arrival = at least one SDH diagnosis type other than 2
enc["sdh_poa"] = types.str.replace("2", "", regex=False).str.contains(r"[A-Z0-9]")
enc["episode"] = enc["dv_epicare"].astype("string").fillna("g" + enc["genc_id"])

step("Cohort encounters (ER or inpatient SDH code, age 18+)", enc)
d = enc[(enc.admit >= cfg.STUDY_START) & (enc.admit < cfg.STUDY_END)]
step(f"Admitted {cfg.STUDY_START} to before {cfg.STUDY_END}", d)

er_only = d[~d.sdh_inpatient]
type2 = d[d.sdh_inpatient & ~d.sdh_poa]
keep = (d.sdh_inpatient & d.sdh_poa) | (cfg.INCLUDE_ER_ONLY_SDH & ~d.sdh_inpatient)
d = d[keep]
step("SDH on the inpatient abstract and present on arrival" +
     (" (or ER-only, kept by setting)" if cfg.INCLUDE_ER_ONLY_SDH else ""), d,
     note=f"removed: SDH coded only in the ER ({er_only.patient_id_hashed.nunique()} patients); "
          f"inpatient SDH only as type 2 = developed in hospital ({type2.patient_id_hashed.nunique()} patients)")

# ---------------------------------------------------------------------
# 2. First episode per patient (episode = every cohort encounter in the
#    same GEMINI episode of care, qualifying or not)
# ---------------------------------------------------------------------
ep_start = enc.groupby("episode").admit.min()
d = d.assign(ep_start=d.episode.map(ep_start))
first_ep = d.sort_values(["ep_start", "admit"]).groupby("patient_id_hashed").episode.first()
ep_enc = enc[enc.episode.isin(first_ep.values)].sort_values(["episode", "admit"]).copy()
ep_enc["order_in_episode"] = ep_enc.groupby("episode").cumcount() + 1
step("First qualifying episode per patient (transfers joined)", ep_enc,
     note=f"{(ep_enc.groupby('episode').size() > 1).sum()} episodes have more than one encounter")

first = ep_enc[ep_enc.order_in_episode == 1].set_index("episode")
g = ep_enc.groupby("episode")
co = pd.DataFrame({
    "patient_id_hashed": first.patient_id_hashed,
    "first_genc_id": first.genc_id,
    "episode_genc_ids": g.genc_id.agg("; ".join),
    "n_encounters": g.size(),
    "hospital_num": first.hospital_num.astype("string"),
    "hospital_type": first.hospital_hospital_type,
    "hospitals_in_episode": g.hospital_num.agg(lambda s: "; ".join(pd.unique(s.astype(str)))),
    "n_hospitals": g.hospital_num.nunique(),
    "age": first.age, "gender": first.gender, "admit_category": first.admit_category,
    "institution_from": first.institution_from, "admit_via_ambulance": first.admit_via_ambulance,
    "admission_date_time": first.admit, "discharge_date_time": g.discharge.max(),
    "sdh_traumatic": g.sdh_traumatic_inpatient.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_nontraumatic": g.sdh_nontraumatic_inpatient.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_most_responsible": g.sdh_most_responsible_dx.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_ip_dx_types": g.sdh_ip_dx_types.agg(lambda s: ",".join(sorted({t for x in s.dropna() for t in str(x).split(",")}))),
    "sdh_er_only_in_episode": g.sdh_inpatient.agg(lambda s: not s.any()),
}).reset_index()
co["stratum"] = co.sdh_traumatic.map({True: "traumatic", False: "nontraumatic"})
co["elective"] = co.admit_category.astype("string").str.strip().isin(cfg.ELECTIVE_CATEGORIES)
co["later_sdh_encounters"] = co.patient_id_hashed.map(
    enc.groupby("patient_id_hashed").size()) - co.n_encounters
if cfg.EXCLUDE_ELECTIVE:
    co = co[~co.elective]
    step("Remove elective admissions", ep_enc[ep_enc.episode.isin(co.episode)])

# time zero: ER triage of the first encounter, else admission
tri = first.triage.reindex(co.episode).values
h = (pd.Series(tri) - co.admission_date_time).dt.total_seconds() / 3600
ok = h.between(*cfg.TRIAGE_WINDOW_H)
co["time_zero"] = pd.Series(tri).where(ok, co.admission_date_time)
co["time_zero_source"] = ok.map({True: "er_triage", False: "admission"})
co["hours_triage_to_admission"] = (-h).where(ok).round(1)
print("time zero:", co.time_zero_source.value_counts().to_dict())

# ---------------------------------------------------------------------
# 3. Index head CT
# ---------------------------------------------------------------------
rad = io.load("radiology", ["genc_id", "modality_mapped", "body_part_mapped", "test_name_raw",
                            "performed_date_time", "imaging_result"])
gid_ep = ep_enc.set_index("genc_id").episode
rad = rad[rad.genc_id.isin(gid_ep.index) & rad.modality_mapped.eq("CT")].copy()
name = rad.test_name_raw.fillna("").str.lower()
rad["is_head"] = name.str.contains(cfg.CT_NAME_INCLUDE, regex=True)
rad["excluded_name"] = name.str.contains(cfg.CT_NAME_EXCLUDE, regex=True)
io.save_aggregate(rad[rad.is_head].groupby(["test_name_raw", "body_part_mapped", "excluded_name"], dropna=False)
                  .size().reset_index(name="scans").sort_values("scans", ascending=False),
                  "check_ct_names.csv", ["scans"])
ct = rad[rad.is_head & ~rad.excluded_name].copy()
ct["has_report"] = ct.imaging_result.fillna("").str.strip().str.len() > 0
ct["episode"] = ct.genc_id.map(gid_ep)
ct["when"] = io.to_dt(ct.performed_date_time)
ct["h_admit"] = io.hours_between(ct["when"], ct.episode.map(co.set_index("episode").admission_date_time))
ct = ct.sort_values(["episode", "when"])
win = ct[ct.h_admit.between(-cfg.CT_WINDOW_BEFORE_H, cfg.CT_WINDOW_AFTER_H)]
idx = win[win.has_report].groupby("episode").head(1).set_index("episode")

ce = co.set_index("episode")
ce["head_ct_in_window"] = ce.index.isin(win.episode)
ce["head_cts_in_episode"] = ct.groupby("episode").size().reindex(ce.index).fillna(0).astype(int)
ce["index_ct_genc_id"] = idx.genc_id
ce["index_ct_name"] = idx.test_name_raw
ce["index_ct_date_time"] = idx["when"]
ce["has_index_ct_report"] = ce.index_ct_genc_id.notna()
ce["first_ct_lacked_report"] = ~win.groupby("episode").has_report.first().reindex(ce.index).fillna(True).astype(bool)
ce["hours_t0_to_index_ct"] = io.hours_between(ce.index_ct_date_time, ce.time_zero).round(1)
second = ct.merge(idx[["when"]].rename(columns={"when": "t_idx"}), left_on="episode", right_index=True)
second = second[second["when"] > second.t_idx].groupby("episode")["when"].min()
ce["hours_index_ct_to_next_ct"] = io.hours_between(second.reindex(ce.index), ce.index_ct_date_time).round(1)
co = ce.reset_index()

cov = co.assign(year=co.admission_date_time.dt.year).groupby(["hospital_num", "hospital_type", "year"]) \
    .agg(patients=("patient_id_hashed", "size"), with_ct_report=("has_index_ct_report", "sum")).reset_index()
# a percentage is shown only when neither its count nor the remainder is a small cell
safe = lambda n: (n == 0) | (n >= cfg.SMALL_CELL)
cov["pct_with_report"] = (100 * cov.with_ct_report / cov.patients).round(1).where(
    safe(cov.with_ct_report) & safe(cov.patients - cov.with_ct_report))
io.save_aggregate(cov, "check_ct_coverage_by_hospital_year.csv", ["patients", "with_ct_report"])

eps = co.loc[co.head_ct_in_window, "episode"]
step(f"Head CT from {cfg.CT_WINDOW_BEFORE_H} h before to {cfg.CT_WINDOW_AFTER_H} h after admission",
     ep_enc[ep_enc.episode.isin(eps)])
if cfg.REQUIRE_CT_REPORT:
    co = co[co.has_index_ct_report]
    step("Index head CT has report text (NLP input)", ep_enc[ep_enc.episode.isin(co.episode)],
         note="see check_ct_coverage_by_hospital_year.csv for where reports are missing")

# ---------------------------------------------------------------------
# 4. Save
# ---------------------------------------------------------------------
co = co.sort_values("patient_id_hashed").reset_index(drop=True)
co["row_id"] = [f"SDH{i + 1:05d}" for i in range(len(co))]
co["admission_year"] = co.admission_date_time.dt.year
co = co[["row_id"] + [c for c in co if c != "row_id"]]
io.save_patient_level(co, "cohort.parquet")
io.save_patient_level(ep_enc[ep_enc.episode.isin(co.episode)][
    ["episode", "patient_id_hashed", "genc_id", "order_in_episode", "hospital_num", "admit", "discharge"]],
    "episode_encounters.parquet")
if cfg.REQUIRE_CT_REPORT:
    nlp = pd.DataFrame({"row_id": co.row_id, "genc_id": co.index_ct_genc_id,
                        "report": co.episode.map(idx.imaging_result)})
    io.save_patient_level(nlp, "index_ct_reports_for_nlp.csv")
io.save_aggregate(pd.DataFrame(flow), "flowchart.csv", ["patients", "encounters"])
print("Strata:", co.stratum.value_counts().to_dict())
print("Next: python phenotype/02_baseline_features.py")
