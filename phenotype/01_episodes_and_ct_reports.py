"""
STEP 1 - Episodes of care, flags, and every head CT report for the NLP.

Takes every encounter in the GEMINI SDH extraction (adults with an SDH code
in the ER or inpatient record), joins transfers into episodes of care, and
flags each episode. Nobody is excluded here. Then it writes every head CT
report of every episode for the NLP, which later confirms the SDH and finds
the CT that diagnosed it.

    python phenotype/01_episodes_and_ct_reports.py

Patient level (patient_level/, stays on GEMINI):
    episodes.csv               one row per episode of care (all episodes)
    episode_encounters.csv     which encounters make up each episode
    ct_reports_for_nlp.csv     report_id, episode, report  -> run NLP_v5.ipynb on this
    ct_reports_index.csv       report_id, episode, genc_id, CT time and name (no text)
Aggregate (aggregate/, cell-suppressed):
    step1_counts.csv, check_transfer_linking.csv, check_arrival_source.csv, check_ct_names.csv,
    check_ct_coverage_by_hospital_year.csv, check_ct_report_by_transfer.csv,
    check_data_coverage_tables.csv
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_io as io

# ---------------------------------------------------------------------
# 1. Encounters
# ---------------------------------------------------------------------
enc = io.load("cohort")
enc = enc.merge(io.load("encounters", [
    "genc_id", "admission_ts", "discharge_ts", "er_triage_ts", "admit_category", "institution_from",
    "admit_via_ambulance", "gender", "hospital_hospital_type", "dv_epicare",
    "dv_from_acute_care_institution_derived", "transfer_institution_from_type_mns"]), on="genc_id", how="left")
enc["admit"] = io.to_dt(enc.admission_ts).fillna(io.to_dt(enc.admission_date_time))
enc["discharge"] = io.to_dt(enc.discharge_ts)
enc["triage"] = io.to_dt(enc.er_triage_ts)
b = lambda c: enc[c].fillna(False).astype(bool)
enc["sdh_inpatient"] = b("sdh_traumatic_inpatient") | b("sdh_nontraumatic_inpatient")
types = enc.sdh_ip_dx_types.fillna("").astype(str).str.upper()
enc["sdh_poa"] = types.str.replace("2", "", regex=False).str.contains(r"[A-Z0-9]")
enc["hospital_num"] = enc.hospital_num.astype("string")

# ---------------------------------------------------------------------
# 2. Episodes of care: same GEMINI epicare as the previous encounter, or
#    admitted within TRANSFER_GAP_HOURS of its discharge
# ---------------------------------------------------------------------
enc = enc.sort_values(["patient_id_hashed", "admit", "genc_id"]).reset_index(drop=True)
same_pt = enc.patient_id_hashed.eq(enc.patient_id_hashed.shift())
prev_end = enc.groupby("patient_id_hashed").discharge.transform(lambda s: s.cummax().shift())
gap = io.hours_between(enc.admit, prev_end)
epicare = enc.dv_epicare.astype("string")
as_bool = lambda x: pd.Series(x, index=enc.index).fillna(False).astype(bool)
same_pt = as_bool(same_pt)
by_epicare = same_pt & as_bool(epicare.notna() & epicare.eq(epicare.shift()))
by_gap = same_pt & as_bool(gap <= cfg.TRANSFER_GAP_HOURS)
enc["hours_since_previous_discharge"] = gap.where(same_pt).round(1)
enc["episode"] = ["EP%06d" % n for n in (~(by_epicare | by_gap)).cumsum()]
enc["order_in_episode"] = enc.groupby("episode").cumcount() + 1
io.save_aggregate(pd.DataFrame({
    "link": ["epicare and time gap", "epicare only", f"time gap <= {cfg.TRANSFER_GAP_HOURS} h only"],
    "encounters_joined_to_previous": [int((by_epicare & by_gap).sum()), int((by_epicare & ~by_gap).sum()),
                                      int((by_gap & ~by_epicare).sum())]}),
    "check_transfer_linking.csv", ["encounters_joined_to_previous"])

g = enc.groupby("episode", sort=False)
first = g.first()          # first non-missing per column; the identity columns come from row 1 below
row1 = enc[enc.order_in_episode == 1].set_index("episode")
ep = pd.DataFrame({
    "patient_id_hashed": row1.patient_id_hashed,
    "first_genc_id": row1.genc_id,
    "episode_genc_ids": g.genc_id.agg("; ".join),
    "n_encounters": g.size(),
    "hospital_num": row1.hospital_num,
    "hospital_type": row1.hospital_hospital_type,
    "hospitals_in_episode": g.hospital_num.agg(lambda s: "; ".join(pd.unique(s.dropna()))),
    "n_hospitals": g.hospital_num.nunique(),
    "age": row1.age, "gender": first.gender,
    "admit_category": row1.admit_category, "admit_via_ambulance": row1.admit_via_ambulance,
    "institution_from": row1.institution_from,
    "admission_date_time": row1.admit, "discharge_date_time": g.discharge.max(),
    "er_triage_date_time": row1.triage,
    "sdh_traumatic": g.sdh_traumatic.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_nontraumatic": g.sdh_nontraumatic.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_most_responsible": g.sdh_most_responsible_dx.agg(lambda s: s.fillna(False).astype(bool).any()),
    "sdh_ip_dx_types": g.sdh_ip_dx_types.agg(
        lambda s: ",".join(sorted({t.strip() for x in s.dropna() for t in str(x).split(",")}))),
    "any_inpatient_sdh_code": g.sdh_inpatient.any(),
    "any_sdh_present_on_arrival": g.sdh_poa.any(),
}).reset_index()

# flags (nobody is excluded in this step)
ep["flag_er_only_sdh"] = ~ep.any_inpatient_sdh_code
ep["flag_in_hospital_onset"] = ep.any_inpatient_sdh_code & ~ep.any_sdh_present_on_arrival
ep["flag_elective"] = ep.admit_category.astype("string").str.strip().isin(cfg.ELECTIVE_CATEGORIES)
# arrived from an acute-care hospital (GEMINI-derived). institution_from alone
# is also filled in for long-term care, rehab etc., so it is only reported.
from_acute = io.truthy(row1.dv_from_acute_care_institution_derived).reindex(ep.episode)
ep["flag_transferred_in_from_outside_gemini"] = from_acute.values
blank = lambda s: s.astype("string").str.strip().fillna("").isin(["", "nan", "None", "0", "00", "000", "0000"])
src = pd.DataFrame({
    "institution_from_filled": (~blank(row1.institution_from)).reindex(ep.episode).values,
    "from_acute_care_derived": from_acute.values,
    "from_type_mns": row1.get("transfer_institution_from_type_mns", pd.Series(dtype="string"))
                         .astype("string").reindex(ep.episode).fillna("(blank)").values})
io.save_aggregate(src.value_counts().reset_index(name="episodes"), "check_arrival_source.csv", ["episodes"])
ep["flag_in_study_period"] = (ep.admission_date_time >= cfg.STUDY_START) & (ep.admission_date_time < cfg.STUDY_END)
ep["sdh_type"] = ep.sdh_traumatic.map({True: "traumatic", False: "nontraumatic"})
ep = ep.sort_values(["patient_id_hashed", "admission_date_time"])
ep["episode_number_for_patient"] = ep.groupby("patient_id_hashed").cumcount() + 1

# ---------------------------------------------------------------------
# 3. Every head CT report of every episode
# ---------------------------------------------------------------------
rad = io.load("radiology", ["genc_id", "modality_mapped", "body_part_mapped", "test_name_raw",
                            "performed_date_time", "imaging_result"])
gid_ep = enc.set_index("genc_id").episode
rad = rad[rad.genc_id.isin(gid_ep.index) & rad.modality_mapped.eq("CT")].copy()
name = rad.test_name_raw.fillna("").str.lower()
part = rad.body_part_mapped.fillna("").astype(str).str.lower()
rad["is_head"] = name.str.contains(cfg.CT_NAME_INCLUDE, regex=True) | part.str.contains(cfg.CT_BODY_PART_INCLUDE, regex=True)
rad["excluded_name"] = name.str.contains(cfg.CT_ALWAYS_EXCLUDE, regex=True) | (
    name.str.contains(cfg.CT_VASCULAR, regex=True) & ~name.str.contains(cfg.CT_NONCONTRAST, regex=True))
io.save_aggregate(rad[rad.is_head].groupby(["test_name_raw", "body_part_mapped", "excluded_name"], dropna=False)
                  .size().reset_index(name="scans").sort_values("scans", ascending=False),
                  "check_ct_names.csv", ["scans"])

ct = rad[rad.is_head & ~rad.excluded_name].copy()
ct["has_report"] = ct.imaging_result.fillna("").str.strip().str.len() > 0
ct["episode"] = ct.genc_id.map(gid_ep)
ct["performed_date_time"] = io.to_dt(ct.performed_date_time)
ct = ct.sort_values(["episode", "performed_date_time"]).reset_index(drop=True)
ep_i = ep.set_index("episode")
ep_i["n_head_cts"] = ct.groupby("episode").size().reindex(ep_i.index).fillna(0).astype(int)
ep_i["n_head_ct_reports"] = ct.groupby("episode").has_report.sum().reindex(ep_i.index).fillna(0).astype(int)
ep_i["flag_no_ct_report"] = ep_i.n_head_ct_reports == 0

# was radiology collected at this hospital on this date? (GEMINI lookup_data_coverage)
cov_lk = io.load("lookup_data_coverage")
io.save_aggregate(cov_lk.groupby("data").hospital_num.nunique().reset_index(name="hospitals"),
                  "check_data_coverage_tables.csv")
rad_cov = cov_lk[cov_lk.data.astype(str).str.contains("radiol|imaging", case=False, regex=True)].copy()
if len(rad_cov):
    rad_cov["hospital_num"] = rad_cov.hospital_num.astype("string")
    rad_cov["lo"], rad_cov["hi"] = io.to_dt(rad_cov.min_date), io.to_dt(rad_cov.max_date)
    m = ep_i[["hospital_num", "admission_date_time"]].reset_index().merge(rad_cov[["hospital_num", "lo", "hi"]],
                                                                          on="hospital_num", how="left")
    m["in"] = (m.admission_date_time >= m.lo) & (m.admission_date_time <= m.hi + pd.Timedelta(days=1))
    # an episode with a CT report clearly had radiology collected, whatever the table says
    ep_i["flag_radiology_not_collected"] = ~m.groupby("episode")["in"].any().reindex(ep_i.index).fillna(False) \
        & ep_i.flag_no_ct_report
else:
    print("lookup_data_coverage has no radiology rows; data values:", sorted(cov_lk.data.astype(str).unique()))
    ep_i["flag_radiology_not_collected"] = False
ep = ep_i.reset_index()

rep = ct[ct.has_report].copy()
rep["report_id"] = ["CT%07d" % (i + 1) for i in range(len(rep))]
rep["hours_from_episode_admission"] = io.hours_between(
    rep.performed_date_time, rep.episode.map(ep_i.admission_date_time)).round(1)
# columns A and B = report numbers, column C = report text (what NLP_v5.ipynb reads)
io.save_patient_level(rep[["report_id", "episode", "imaging_result"]].rename(columns={"imaging_result": "report"}),
                      "ct_reports_for_nlp.csv")
io.save_patient_level(rep[["report_id", "episode", "genc_id", "performed_date_time", "test_name_raw",
                           "hours_from_episode_admission"]], "ct_reports_index.csv")

# ---------------------------------------------------------------------
# 4. Save and count
# ---------------------------------------------------------------------
io.save_patient_level(ep, "episodes.csv")
io.save_patient_level(enc[["episode", "patient_id_hashed", "genc_id", "order_in_episode", "hospital_num", "admit",
                           "discharge", "triage", "hours_since_previous_discharge"]], "episode_encounters.csv")

cov = ep.assign(year=ep.admission_date_time.dt.year).groupby(["hospital_num", "hospital_type", "year"]).agg(
    episodes=("episode", "size"), with_ct_report=("flag_no_ct_report", lambda s: int((~s).sum())),
    radiology_not_collected=("flag_radiology_not_collected", "sum")).reset_index()
cov["pct_with_ct_report"] = [io.safe_pct(k, n) for k, n in zip(cov.with_ct_report, cov.episodes)]
io.save_aggregate(cov, "check_ct_coverage_by_hospital_year.csv", ["episodes", "with_ct_report", "radiology_not_collected"])
tr = ep.groupby("flag_transferred_in_from_outside_gemini").agg(
    episodes=("episode", "size"), with_ct_report=("flag_no_ct_report", lambda s: int((~s).sum()))).reset_index()
tr["pct_with_ct_report"] = [io.safe_pct(k, n) for k, n in zip(tr.with_ct_report, tr.episodes)]
io.save_aggregate(tr, "check_ct_report_by_transfer.csv", ["episodes", "with_ct_report"])

firsts = ep[ep.episode_number_for_patient == 1]
rows = [("All encounters in the extraction", enc.patient_id_hashed.nunique(), len(enc))]
rows.append(("Episodes of care (transfers joined)", ep.patient_id_hashed.nunique(), len(ep)))
for f in ["flag_er_only_sdh", "flag_in_hospital_onset", "flag_elective", "flag_transferred_in_from_outside_gemini",
          "flag_no_ct_report", "flag_radiology_not_collected"]:
    rows.append((f"  episodes flagged {f[5:]}", ep[ep[f]].patient_id_hashed.nunique(), int(ep[f].sum())))
rows.append(("  episodes outside the study period", ep[~ep.flag_in_study_period].patient_id_hashed.nunique(),
             int((~ep.flag_in_study_period).sum())))
rows.append(("Head CT reports sent to the NLP", rep.episode.map(ep_i.patient_id_hashed).nunique(), len(rep)))
io.save_aggregate(pd.DataFrame(rows, columns=["description", "patients", "episodes_or_rows"]),
                  "step1_counts.csv", ["patients", "episodes_or_rows"])
for r in rows:
    print(f"{r[0]}: {r[1]} patients, {r[2]}")
print(f"\nNext: run NLP_v5.ipynb on patient_level/ct_reports_for_nlp.csv (OUTPUT_CSV = "
      f"'{cfg.NLP_RESULTS_FILE.name}', RUN_VALIDATION = False), put the result in patient_level/,\n"
      "then: python phenotype/02_cohort_key.py  (it also runs before the NLP, with a fallback)")
