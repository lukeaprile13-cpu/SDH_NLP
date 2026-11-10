"""
STEP 1 - Build the SDH phenotype cohort.

One row per patient: their first SDH episode of care (transfers between
GEMINI hospitals joined into one episode), with time zero (arrival) and the
index head CT whose report the NLP reads.

    python phenotype/01_build_cohort.py

Writes (output/patient_level/, stays on the server):
    cohort.csv                    one row per patient
    encounters.csv                every admission of every SDH patient, with
                                  episode ids (later steps use it for prior
                                  admissions and readmissions)
    index_ct_reports_for_nlp.csv  row_id, genc_id, report: the NLP input
Writes (output/aggregate/, cell-suppressed, safe to share):
    flowchart.csv, check_hospital_year.csv, check_ct_names.csv,
    check_transfer_gaps.csv, check_sdh_diagnosis_types.csv
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_config as cfg
import sdh_db as db
from sdh_codes import normalise_code

flow = []


def step(label, patients, episodes=None, encounters=None, note=""):
    flow.append({"step": len(flow) + 1, "description": label, "patients": patients,
                 "episodes": episodes, "encounters": encounters, "note": note})
    print(f"[{len(flow)}] {label}: {patients} patients"
          + (f", {episodes} episodes" if episodes is not None else "")
          + (f", {encounters} encounters" if encounters is not None else ""))


conn = db.connect()
sc = db.Schema(conn)
ADM, DX, RAD = sc.table("admdad"), sc.table("ipdiagnosis"), sc.table("radiology")
ER = sc.table("er", required=False)

admit_col = sc.col(ADM, [r"^admission_date_time$", r"^admit_date_time$",
                         r"^admi(t|ssion).*date.*time"], required=True)
disch_col = sc.col(ADM, [r"^discharge_date_time$", r"^discharge.*date.*time"], required=True)
optional = {name: sc.col(ADM, pattern) for name, pattern in {
    "age": r"^age$", "gender": r"^gender$|^sex$", "admit_category": r"^admit_category",
    "discharge_disposition": r"^discharge_disposition$",
    "institution_from": r"^institution_from$", "institution_from_type": r"^institution_from_type",
    "institution_to": r"^institution_to$", "institution_to_type": r"^institution_to_type",
    "admit_via_ambulance": r"ambulance",
}.items()}
missing = [k for k, v in optional.items() if v is None]
if missing:
    print("admdad columns not in this data cut (left blank):", ", ".join(missing))

# ---------------------------------------------------------------------
# 1. SDH diagnosis rows
# ---------------------------------------------------------------------
like = " OR ".join(["diagnosis_code LIKE %s"] * len(cfg.SDH_CODE_PATTERNS))
sdh_dx = db.query(conn, f"SELECT genc_id, diagnosis_code, diagnosis_type FROM {DX} WHERE {like}",
                  cfg.SDH_CODE_PATTERNS)
sdh_dx["diagnosis_code"] = sdh_dx["diagnosis_code"].map(normalise_code)
sdh_dx["diagnosis_type"] = sdh_dx["diagnosis_type"].astype("string").str.strip().str.upper()
sdh_dx["present_on_arrival"] = sdh_dx["diagnosis_type"].isin(cfg.SDH_TYPES_PRESENT_ON_ARRIVAL)
sdh_dx["traumatic"] = sdh_dx["diagnosis_code"].str.startswith(cfg.TRAUMATIC_PREFIX)

db.save_aggregate(
    sdh_dx.assign(code_group=lambda d: d["diagnosis_code"].str[:4])
          .groupby(["code_group", "diagnosis_code", "diagnosis_type"], dropna=False)
          .genc_id.nunique().reset_index(name="encounters"),
    "check_sdh_diagnosis_types.csv", ["encounters"])

sdh_enc = sdh_dx.groupby("genc_id").agg(
    sdh_codes=("diagnosis_code", lambda s: "; ".join(sorted(set(s)))),
    sdh_types=("diagnosis_type", lambda s: "; ".join(sorted(set(s.dropna())))),
    sdh_poa=("present_on_arrival", "any"),
    sdh_primary=("diagnosis_type", lambda s: (s == "M").any()),
).reset_index()
poa_codes = (sdh_dx[sdh_dx.present_on_arrival].groupby("genc_id")
             .agg(sdh_traumatic=("traumatic", "any"),
                  sdh_nontraumatic=("diagnosis_code", lambda s: s.str.startswith(cfg.NONTRAUMATIC_PREFIX).any()))
             .reset_index())
sdh_enc = sdh_enc.merge(poa_codes, on="genc_id", how="left")

# ---------------------------------------------------------------------
# 2. Every admission of every SDH patient
# ---------------------------------------------------------------------
select = [f"genc_id", "NULLIF(BTRIM(patient_id_hashed), '') AS patient_id_hashed", "hospital_num",
          f"{admit_col} AS admission_date_time", f"{disch_col} AS discharge_date_time"]
select += [f"{col} AS {name}" for name, col in optional.items() if col]
sdh_ids_sql = f"SELECT DISTINCT genc_id FROM {DX} WHERE {like}"
sdh_adm = db.query(conn, f"""
    SELECT {', '.join(select)} FROM {ADM}
    WHERE genc_id IN ({sdh_ids_sql})""", cfg.SDH_CODE_PATTERNS)
step("Encounters with an SDH code (I62.0, S06.5; any diagnosis type)",
     sdh_adm.patient_id_hashed.nunique(), encounters=len(sdh_adm),
     note=f"{sdh_adm.patient_id_hashed.isna().sum()} encounters have no patient id")

encounters = db.query(conn, f"""
    SELECT {', '.join(select)} FROM {ADM}
    WHERE NULLIF(BTRIM(patient_id_hashed), '') IN (
        SELECT NULLIF(BTRIM(patient_id_hashed), '') FROM {ADM} WHERE genc_id IN ({sdh_ids_sql}))
    """, cfg.SDH_CODE_PATTERNS)
for c in ("admission_date_time", "discharge_date_time"):
    encounters[c] = db.to_dt(encounters[c])
for c in ("admit_category", "gender", "discharge_disposition"):
    if c in encounters:
        encounters[c] = encounters[c].astype("string").str.strip()
encounters = encounters.merge(sdh_enc, on="genc_id", how="left")
encounters["sdh_coded"] = encounters["sdh_codes"].notna()
encounters["sdh_poa"] = encounters["sdh_poa"].fillna(False).astype(bool)
print(f"All admissions of SDH patients: {len(encounters)}")

missing_pid = sdh_adm.patient_id_hashed.isna().sum()
step("Remove encounters without a patient id (they cannot be linked or de-duplicated)",
     sdh_adm.patient_id_hashed.nunique(), encounters=int(len(sdh_adm) - missing_pid))

coded = encounters[encounters.sdh_coded]
poa = coded[coded.sdh_poa]
step("SDH present on arrival (diagnosis type is not 2 = developed in hospital)",
     poa.patient_id_hashed.nunique(), encounters=len(poa),
     note=f"{len(coded) - len(poa)} encounters had the SDH only as a type-2 (in-hospital) diagnosis")

# ---------------------------------------------------------------------
# 3. Episodes of care: admissions joined by transfers
# ---------------------------------------------------------------------
encounters = encounters.sort_values(["patient_id_hashed", "admission_date_time", "genc_id"]).reset_index(drop=True)
prev_end = (encounters.groupby("patient_id_hashed")["discharge_date_time"]
            .transform(lambda s: s.cummax().shift()))
gap_h = db.hours_between(encounters["admission_date_time"], prev_end)
encounters["hours_since_previous_discharge"] = gap_h
new_chain = gap_h.isna() | (gap_h > cfg.TRANSFER_GAP_HOURS)
encounters["chain_id"] = new_chain.cumsum()

gaps = gap_h.dropna()
bins = [-1e9, 0, 3, 6, 12, 24, 48, 168, 1e9]
labels = ["overlap", "0-3h", "3-6h", "6-12h", "12-24h", "24-48h", "2-7d", ">7d"]
db.save_aggregate(pd.cut(gaps, bins=bins, labels=labels).value_counts().sort_index()
                  .rename_axis("gap_between_admissions").reset_index(name="admissions"),
                  "check_transfer_gaps.csv", ["admissions"])

# Episode start: the first SDH (present on arrival) admission of the chain,
# moved back to an earlier admission of the same chain when that began
# within CT_WINDOW_AFTER_H of it (seen at hospital A, transferred to B).
anchor = (encounters[encounters.sdh_poa].groupby("chain_id")
          .agg(anchor_genc_id=("genc_id", "first"), anchor_admit=("admission_date_time", "first")))
encounters = encounters.merge(anchor, on="chain_id", how="left")
in_episode = (encounters.anchor_admit.notna() &
              (encounters.admission_date_time >=
               encounters.anchor_admit - pd.Timedelta(hours=cfg.CT_WINDOW_AFTER_H)))
encounters["in_sdh_episode"] = in_episode
encounters["episode_id"] = encounters["chain_id"].where(in_episode).astype("Int64")
preceded = encounters[~in_episode & encounters.anchor_admit.notna()].chain_id.unique()

episodes = (encounters[in_episode].groupby("episode_id").agg(
    patient_id_hashed=("patient_id_hashed", "first"),
    start_genc_id=("genc_id", "first"),
    anchor_genc_id=("anchor_genc_id", "first"),
    hospital_num=("hospital_num", "first"),
    hospitals_in_episode=("hospital_num", lambda s: "; ".join(pd.unique(s.dropna()))),
    n_hospitals=("hospital_num", "nunique"),
    n_encounters=("genc_id", "size"),
    episode_genc_ids=("genc_id", lambda s: "; ".join(s)),
    admission_date_time=("admission_date_time", "first"),
    discharge_date_time=("discharge_date_time", "max"),
    sdh_codes=("sdh_codes", lambda s: "; ".join(sorted({c for x in s.dropna() for c in x.split("; ")}))),
    sdh_types=("sdh_types", lambda s: "; ".join(sorted({c for x in s.dropna() for c in x.split("; ")}))),
    sdh_primary=("sdh_primary", lambda s: s.fillna(False).astype(bool).any()),
    sdh_traumatic=("sdh_traumatic", lambda s: s.fillna(False).astype(bool).any()),
    sdh_nontraumatic=("sdh_nontraumatic", lambda s: s.fillna(False).astype(bool).any()),
).reset_index())
first = encounters[in_episode].groupby("episode_id").first()
for c in ("age", "gender", "admit_category", "institution_from", "institution_from_type",
          "admit_via_ambulance"):
    if c in first:
        episodes[c] = episodes["episode_id"].map(first[c])
episodes["sdh_first_coded_in_later_encounter"] = episodes.start_genc_id != episodes.anchor_genc_id
episodes["preceded_by_other_stay"] = episodes.episode_id.isin(preceded)
episodes["stratum"] = episodes.sdh_traumatic.map({True: "traumatic", False: "nontraumatic"})
episodes["age"] = pd.to_numeric(episodes.get("age"), errors="coerce")

step("Episodes of care (transfers within "
     f"{cfg.TRANSFER_GAP_HOURS} h joined)", episodes.patient_id_hashed.nunique(), len(episodes),
     note=f"{(episodes.n_hospitals > 1).sum()} episodes span more than one GEMINI hospital")

# ---------------------------------------------------------------------
# 4. Age, study period, first episode per patient
# ---------------------------------------------------------------------
ep = episodes[episodes.age >= cfg.MIN_AGE]
step(f"Age {cfg.MIN_AGE} or older", ep.patient_id_hashed.nunique(), len(ep))

start, end = pd.Timestamp(cfg.STUDY_START), pd.Timestamp(cfg.STUDY_END)
ep = ep[(ep.admission_date_time >= start) & (ep.admission_date_time <= end)]
step(f"Episode starts {cfg.STUDY_START} to {cfg.STUDY_END[:10]}", ep.patient_id_hashed.nunique(), len(ep))

ep = ep.sort_values(["patient_id_hashed", "admission_date_time"])
earlier_sdh = (encounters[encounters.sdh_coded].groupby("patient_id_hashed").admission_date_time.min())
cohort = ep.groupby("patient_id_hashed").head(1).copy()
cohort["later_sdh_episodes"] = cohort.patient_id_hashed.map(ep.groupby("patient_id_hashed").size()) - 1
cohort["prior_sdh_admission_in_data"] = (cohort.patient_id_hashed.map(earlier_sdh)
                                         < cohort.admission_date_time)
step("First qualifying episode per patient (the index episode)", len(cohort), len(cohort),
     note=f"{int(cohort.prior_sdh_admission_in_data.sum())} had an SDH-coded admission before it "
          "(type 2 or before the study period)")

cohort["elective"] = cohort.get("admit_category", pd.Series(index=cohort.index, dtype="string")) \
    .isin(cfg.ELECTIVE_CATEGORIES)
if cfg.EXCLUDE_ELECTIVE:
    cohort = cohort[~cohort.elective]
    step("Remove elective (planned) admissions", len(cohort), len(cohort))
else:
    print(f"   elective admissions kept and flagged: {int(cohort.elective.sum())}")

# ---------------------------------------------------------------------
# 5. Time zero: ER triage of the first encounter, else admission time
# ---------------------------------------------------------------------
cohort["time_zero"] = cohort.admission_date_time
cohort["time_zero_source"] = "admission"
if ER:
    triage_col = sc.col(ER, [r"^triage_date_time$", r"triage.*date.*time", r"arrival.*date.*time"])
    if triage_col:
        er = db.query_ids(conn, f"SELECT genc_id, {triage_col} AS triage_date_time FROM {ER} "
                                f"WHERE genc_id = ANY(%(ids)s)", cohort.start_genc_id)
        er["triage_date_time"] = db.to_dt(er.triage_date_time)
        er = er.merge(cohort[["start_genc_id", "admission_date_time"]],
                      left_on="genc_id", right_on="start_genc_id")
        h = db.hours_between(er.triage_date_time, er.admission_date_time)
        er = er[(h >= -48) & (h <= 1)].groupby("genc_id").triage_date_time.min()
        has = cohort.start_genc_id.isin(er.index)
        cohort.loc[has, "time_zero"] = cohort.loc[has, "start_genc_id"].map(er)
        cohort.loc[has, "time_zero_source"] = "er_triage"
print("time zero source:", cohort.time_zero_source.value_counts().to_dict())

# ---------------------------------------------------------------------
# 6. Index head CT
# ---------------------------------------------------------------------
c_mod = sc.col(RAD, [r"^modality_mapped$", r"modality"], required=True)
c_name = sc.col(RAD, [r"^test_name_raw$", r"test_name", r"name"], required=True)
c_time = sc.col(RAD, [r"^performed_date_time$", r"performed.*time", r"(ordered|exam|study).*date.*time"],
                required=True)
c_text = sc.col(RAD, [r"^imaging_result$", r"result|report"], required=True)
episode_encs = encounters.loc[encounters.episode_id.isin(cohort.episode_id), ["genc_id", "episode_id"]]
ct = db.query_ids(conn, f"""
    SELECT genc_id, {c_name} AS test_name, {c_time} AS performed_date_time, {c_text} AS report
    FROM {RAD}
    WHERE genc_id = ANY(%(ids)s) AND {c_mod} = 'CT'
      AND LOWER({c_name}) ~ %(inc)s""", episode_encs.genc_id, params={"inc": db.pg_regex(cfg.CT_NAME_INCLUDE)})
ct["performed_date_time"] = db.to_dt(ct.performed_date_time)
ct["excluded_name"] = ct.test_name.str.lower().str.contains(cfg.CT_NAME_EXCLUDE, regex=True)
ct["has_report"] = ct.report.fillna("").str.strip().str.len() > 0

db.save_aggregate(ct.groupby(["test_name", "excluded_name"]).size().reset_index(name="scans")
                  .sort_values("scans", ascending=False), "check_ct_names.csv", ["scans"])

ct = ct.merge(episode_encs, on="genc_id").merge(
    cohort[["episode_id", "admission_date_time", "time_zero"]], on="episode_id")
ct = ct[~ct.excluded_name]
ct["hours_from_admit"] = db.hours_between(ct.performed_date_time, ct.admission_date_time)
ct["in_window"] = ct.hours_from_admit.between(-cfg.CT_WINDOW_BEFORE_H, cfg.CT_WINDOW_AFTER_H)
ct = ct.sort_values(["episode_id", "performed_date_time"])

per_ep = ct.groupby("episode_id").agg(
    head_cts_in_episode=("genc_id", "size"),
    head_cts_with_report=("has_report", "sum"),
    any_ct_in_window=("in_window", "any"))
index_ct = ct[ct.in_window & ct.has_report].groupby("episode_id").head(1)
first_ct = ct[ct.in_window].groupby("episode_id").head(1)

cohort = cohort.merge(per_ep, on="episode_id", how="left")
n_any = int(cohort.any_ct_in_window.fillna(False).astype(bool).sum())
step(f"A head CT within {cfg.CT_WINDOW_BEFORE_H} h before to {cfg.CT_WINDOW_AFTER_H} h after admission",
     n_any, n_any, note="CT names in check_ct_names.csv")

index_ct = index_ct.rename(columns={"genc_id": "index_ct_genc_id", "test_name": "index_ct_name",
                                    "performed_date_time": "index_ct_date_time"})
cohort = cohort.merge(index_ct[["episode_id", "index_ct_genc_id", "index_ct_name",
                                "index_ct_date_time", "report"]], on="episode_id", how="inner")
cohort["first_ct_in_window_lacked_report"] = ~cohort.episode_id.map(
    first_ct.set_index("episode_id").has_report).astype(bool)
cohort["hours_time_zero_to_index_ct"] = db.hours_between(cohort.index_ct_date_time, cohort.time_zero)
later = ct.merge(cohort[["episode_id", "index_ct_date_time"]], on="episode_id")
later = later[later.performed_date_time > later.index_ct_date_time].groupby("episode_id").performed_date_time.min()
cohort["hours_index_to_second_ct"] = db.hours_between(cohort.episode_id.map(later), cohort.index_ct_date_time)
step("The index head CT has report text (the NLP input)", len(cohort), len(cohort))

# ---------------------------------------------------------------------
# 7. Save
# ---------------------------------------------------------------------
cohort = cohort.sort_values("patient_id_hashed").reset_index(drop=True)
cohort["row_id"] = [f"SDH{i + 1:05d}" for i in range(len(cohort))]
cohort["admission_year"] = cohort.admission_date_time.dt.year
cohort["hospital_type"] = cohort.hospital_num.map(cfg.HOSPITAL_TYPE)

nlp = cohort[["row_id", "index_ct_genc_id", "report"]].rename(columns={"index_ct_genc_id": "genc_id"})
cols = ["row_id", "patient_id_hashed", "episode_id", "start_genc_id", "anchor_genc_id",
        "episode_genc_ids", "n_encounters", "n_hospitals", "hospital_num", "hospitals_in_episode",
        "hospital_type", "age", "gender", "admit_category", "elective", "institution_from",
        "institution_from_type", "admit_via_ambulance", "admission_date_time", "discharge_date_time",
        "admission_year", "time_zero", "time_zero_source", "stratum", "sdh_codes", "sdh_types",
        "sdh_primary", "sdh_traumatic", "sdh_nontraumatic", "sdh_first_coded_in_later_encounter",
        "preceded_by_other_stay", "prior_sdh_admission_in_data", "later_sdh_episodes",
        "index_ct_genc_id", "index_ct_name", "index_ct_date_time", "hours_time_zero_to_index_ct",
        "first_ct_in_window_lacked_report", "head_cts_in_episode", "head_cts_with_report",
        "hours_index_to_second_ct"]
db.save_patient_level(cohort[[c for c in cols if c in cohort]], "cohort.csv")
db.save_patient_level(nlp, "index_ct_reports_for_nlp.csv")
encounters["in_index_episode"] = encounters.episode_id.isin(cohort.episode_id).fillna(False)
enc_cols = ["patient_id_hashed", "genc_id", "hospital_num", "admission_date_time", "discharge_date_time",
            "admit_category", "discharge_disposition", "sdh_codes", "sdh_types", "sdh_poa",
            "chain_id", "episode_id", "in_index_episode", "hours_since_previous_discharge"]
db.save_patient_level(encounters[[c for c in enc_cols if c in encounters]], "encounters.csv")

flow_df = pd.DataFrame(flow)
db.save_aggregate(flow_df, "flowchart.csv", ["patients", "episodes", "encounters"])

hy = (encounters[encounters.sdh_coded].assign(year=lambda d: d.admission_date_time.dt.year)
      .groupby(["hospital_num", "year"]).genc_id.nunique().rename("sdh_encounters").reset_index())
hy_c = (cohort.rename(columns={"admission_year": "year"}).groupby(["hospital_num", "year"]).size()
        .rename("cohort_patients").reset_index())
hy = hy.merge(hy_c, on=["hospital_num", "year"], how="outer").fillna({"sdh_encounters": 0, "cohort_patients": 0})
db.save_aggregate(hy, "check_hospital_year.csv", ["sdh_encounters", "cohort_patients"])

print("\nStrata:", cohort.stratum.value_counts().to_dict())
print("Done. Next: python phenotype/02_baseline_features.py")
