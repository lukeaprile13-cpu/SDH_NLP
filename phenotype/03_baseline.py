"""
STEP 3 - Baseline dataset: what was known at time zero. One row per patient.

Time zero is ER arrival (or admission) for patients who came in with the SDH
and the diagnosing CT for SDH that developed in hospital (step 2). Labs and
vitals are the values closest to time zero (from the raw tables), so the
same rule works for both.

Variables are in three groups (baseline_dictionary.csv):
    A  clustering inputs  - the clinical presentation (incl. age, sex, CT/NLP)
    B  equity             - neighbourhood marginalization, rurality
    C  care context       - hospital, year, flags (adjustment, not clustering)

    python phenotype/03_baseline.py

Writes patient_level/baseline.csv and aggregate/baseline_dictionary.csv,
check_lab_vital_names.csv, check_lab_vital_timing.csv, check_med_names.csv.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_codes as codes
import sdh_config as cfg
import sdh_io as io

key = io.read_patient_level("cohort_key.csv")
key["time_zero"] = io.to_dt(key.time_zero)
key["admission_date_time"] = io.to_dt(key.admission_date_time)
for c in [c for c in key if c.startswith("flag_")]:
    key[c] = key[c].astype(str).str.lower().eq("true")
encs = io.read_patient_level("episode_encounters.csv")
encs = encs[encs.episode.isin(key.episode)]
pid = key.set_index("patient_id_hashed")
t0 = pid.time_zero
gid_pid = encs.set_index("genc_id").patient_id_hashed
out = pid[["row_id"]].copy()
groups = {}           # variable -> (group, description)


def add(col, values, group, desc):
    out[col] = values
    groups[col] = (group, desc)


def flags(frame, defs, prefix, group, what):
    for name, prefixes in defs.items():
        hit = frame[frame.code.str.startswith(tuple(prefixes))].patient_id_hashed
        add(prefix + name, out.index.isin(hit), group, f"{what}: {name.replace('_', ' ')}")


# ---------------------------------------------------------------------
# 1. Demographics, context, equity (first encounter of the episode)
# ---------------------------------------------------------------------
add("age", pd.to_numeric(pid.age, errors="coerce"), "A", "age at admission")
add("sex", pid.gender, "A", "sex (admdad gender)")
add("sdh_type_code", pid.sdh_type, "A", "traumatic (S06.5) or non-traumatic (I62.0) by ICD code")
for c, d in [("hospital_num", "hospital of arrival"), ("hospital_type", "teaching / non-teaching"),
             ("admission_year", "year of admission"), ("time_zero_source", "what time zero is"),
             ("n_hospitals", "hospitals in the episode")]:
    add(c, pid[c], "C", d)
for c in [c for c in key if c.startswith("flag_")]:
    add(c, pid[c], "C", c[5:].replace("_", " "))

e_cols = io.columns_of("encounters")
equity = [c for c in e_cols if c.startswith(("sc21_", "sc16_"))]
e = io.load("encounters", ["genc_id", "er_triage_level", "dv_mlaps_24hrs", "dv_admit_charlson_derived",
                           "transfer_institution_from_type_mns"] + equity)
first = e.merge(encs[encs.order_in_episode == 1][["genc_id", "patient_id_hashed"]], on="genc_id") \
    .set_index("patient_id_hashed").reindex(out.index)
onset = pid.flag_in_hospital_onset
# triage and the first-24 h mLAPS describe the original presentation, not an SDH found later in hospital
add("ctas", pd.to_numeric(first.er_triage_level.astype("string").str.extract(r"(\d)")[0], errors="coerce")
    .where(~onset), "A", "ER triage level (CTAS 1 = most urgent); blank for in-hospital onset")
add("mlaps_24h", pd.to_numeric(first.dv_mlaps_24hrs, errors="coerce").where(~onset), "A",
    "mLAPS lab acuity score, first 24 h of admission; blank for in-hospital onset")
add("charlson_admit_gemini", pd.to_numeric(first.dv_admit_charlson_derived, errors="coerce"), "A",
    "GEMINI-derived Charlson score at admission")
add("came_from_type", first.get("transfer_institution_from_type_mns"), "C", "where the patient came from")
for c in equity:
    add("nbhd_" + c, first[c], "B", f"neighbourhood (dissemination area): {c}")

# ---------------------------------------------------------------------
# 2. Labs and vitals: value closest to time zero
# ---------------------------------------------------------------------
def closest(frame, var, window, lo, hi, check):
    """frame: patient_id_hashed, t, val -> value closest to t0 in the window."""
    f = frame.copy()
    f["h"] = io.hours_between(io.to_dt(f.t), f.patient_id_hashed.map(t0))
    present = f.val.notna()
    ok = f.val.between(lo, hi)
    inwin = f.h.between(*window)
    k = f[present & ok & inwin].assign(a=lambda d: d.h.abs()).sort_values("a").groupby("patient_id_hashed").first()
    check.append({"variable": var, "rows_within_3_days": int(present.sum()), "implausible": int((present & ~ok).sum()),
                  "outside_window": int((present & ok & ~inwin).sum()), "patients_with_value": len(k),
                  "pct_patients": round(100 * len(k) / len(out), 1),
                  "median": round(k.val.median(), 2) if len(k) else None,
                  "median_hours_from_t0": round(k.h.median(), 1) if len(k) else None})
    return k


# The lab and vitals tables are large (11 and 6 million rows): while reading,
# keep only rows of interest measured near time zero (a wider window than the
# baseline windows, so the checks can still count values measured too late).
SCAN_WINDOW_H = (-48, 72)
gid_t0 = encs.assign(t0=encs.patient_id_hashed.map(t0)).set_index("genc_id").t0


def near_t0(b, time_col):
    h = io.hours_between(io.to_dt(b[time_col]), b.genc_id.map(gid_t0))
    return h.between(*SCAN_WINDOW_H)


timing, names = [], []
lk = io.load("lookup_lab_concept", ["concept_id", "concept_desc"])
lk_desc = dict(zip(lk.concept_id.astype(str), lk.concept_desc.astype(str).str.lower()))
inc_all = "|".join(f"({p[0]})" for p in list(codes.LAB_CONCEPTS.values()) + list(codes.LABS.values()))


def lab_text(b):
    concept = b.test_type_mapped_omop.astype("string").str.replace(r"\.0$", "", regex=True).map(lk_desc)
    return concept, b.test_name_raw.fillna("").astype(str).str.lower()


lab = io.load("lab", ["genc_id", "test_name_raw", "test_type_mapped_omop", "result_value", "result_unit",
                      "collection_date_time"], genc_ids=encs.genc_id,
              keep_rows=lambda b: near_t0(b, "collection_date_time") & (
                  lab_text(b)[0].fillna("").str.contains(inc_all, regex=True)
                  | lab_text(b)[1].str.contains(inc_all, regex=True)))
lab["concept"], lab["raw"] = lab_text(lab)
lab["patient_id_hashed"] = lab.genc_id.map(gid_pid)
lab["val"] = io.to_number(lab.result_value)
lab["t"] = lab.collection_date_time
for var, (inc, exc, lo, hi) in codes.LABS.items():
    c_inc, c_exc = codes.LAB_CONCEPTS.get(var, (None, None))
    by_concept = lab.concept.notna() & lab.concept.fillna("").str.contains(c_inc or "$^", regex=True)
    if c_exc:
        by_concept &= ~lab.concept.fillna("").str.contains(c_exc, regex=True)
    by_raw = lab.concept.isna() & lab.raw.str.contains(inc, regex=True)
    if exc:
        by_raw &= ~lab.raw.str.contains(exc, regex=True)
    f = lab[by_concept | by_raw].copy()
    if var == "hemoglobin":
        f.loc[f.val < 25, "val"] *= 10
    if var == "creatinine":
        f.loc[f.val < 15, "val"] *= 88.4
    if var == "glucose":
        f.loc[f.val > 60, "val"] /= 18
    names.append(f.groupby([f.concept.fillna("(no concept) " + f.raw), "result_unit"], dropna=False).val
                 .agg(["size", "median"]).reset_index().set_axis(["name", "unit", "rows", "median"], axis=1)
                 .assign(variable=var, table="lab"))
    k = closest(f, var, cfg.LAB_WINDOW_H, lo, hi, timing)
    add(var, k.val, "A", f"lab {var}, closest to time zero ({cfg.LAB_WINDOW_H[0]} to +{cfg.LAB_WINDOW_H[1]} h)")
    out[f"{var}_hours_from_t0"] = k.h.round(1)
    groups[f"{var}_hours_from_t0"] = ("C", f"when {var} was measured")
del lab

lv = io.load("lookup_vitals_concept", ["concept_id", "concept_desc"])
lv_desc = dict(zip(lv.concept_id.astype(str), lv.concept_desc.astype(str).str.lower()))
v_inc = "|".join(f"({p})" for p in codes.VITAL_CONCEPTS.values()) + "|" + \
        "|".join(f"({p[0]})" for p in codes.VITALS.values())


def vit_text(b):
    concept = b.measurement_mapped_omop.astype("string").str.replace(r"\.0$", "", regex=True).map(lv_desc)
    return concept, b.measurement_name.fillna("").astype(str).str.lower()


vit = io.load("vitals", ["genc_id", "measurement_name", "measurement_mapped_omop", "measurement_value",
                         "measurement_unit", "measure_date_time"], genc_ids=encs.genc_id,
              keep_rows=lambda b: near_t0(b, "measure_date_time") & (
                  vit_text(b)[0].fillna("").str.contains(v_inc, regex=True)
                  | vit_text(b)[1].str.contains(v_inc, regex=True)))
vit["concept"], vit["raw"] = vit_text(vit)
vit["patient_id_hashed"] = vit.genc_id.map(gid_pid)
vit["t"] = vit.measure_date_time
combined = vit.concept.fillna("").str.contains(codes.VITAL_CONCEPTS["bp_combined"], regex=True) | (
    vit.concept.isna() & vit.raw.str.contains(r"blood pressure|\bbp\b|nibp", regex=True)
    & vit.measurement_value.astype("string").str.contains("/", na=False))
for var, (inc, exc, lo, hi) in codes.VITALS.items():
    c_inc = codes.VITAL_CONCEPTS.get(var)
    by_concept = vit.concept.fillna("").str.contains(c_inc, regex=True) if c_inc else False
    by_raw = vit.concept.isna() & vit.raw.str.contains(inc, regex=True) & ~combined
    if exc:
        by_raw &= ~vit.raw.str.contains(exc, regex=True)
    f = vit[by_concept | by_raw].copy()
    f["val"] = io.to_number(f.measurement_value)
    if var in ("sbp", "dbp"):
        bp = vit[combined].copy()
        part = 0 if var == "sbp" else -1
        bp["val"] = io.to_number(bp.measurement_value.astype("string").str.split("/").str[part])
        f = pd.concat([f, bp])
    if var == "temperature":
        f.loc[f.val > 50, "val"] = (f.val - 32) / 1.8
    names.append(f.groupby([f.concept.fillna("(no concept) " + f.raw), "measurement_unit"], dropna=False).val
                 .agg(["size", "median"]).reset_index().set_axis(["name", "unit", "rows", "median"], axis=1)
                 .assign(variable=var, table="vitals"))
    k = closest(f, var, cfg.VITAL_WINDOW_H, lo, hi, timing)
    add(var, k.val, "A", f"vital {var}, closest to time zero ({cfg.VITAL_WINDOW_H[0]} to +{cfg.VITAL_WINDOW_H[1]} h)")
    out[f"{var}_hours_from_t0"] = k.h.round(1)
    groups[f"{var}_hours_from_t0"] = ("C", f"when {var} was measured")
del vit
nm = pd.concat(names, ignore_index=True)
io.save_aggregate(nm[["table", "variable", "name", "unit", "rows", "median"]].sort_values(["variable", "rows"],
                  ascending=[True, False]), "check_lab_vital_names.csv", ["rows"])
io.save_aggregate(pd.DataFrame(timing), "check_lab_vital_timing.csv",
                  ["rows_within_3_days", "implausible", "outside_window", "patients_with_value"])
for v in ("inr", "platelets", "gcs"):
    if v not in out:
        out[v] = np.nan
add("inr_ge_1_5", (out.inr >= 1.5).where(out.inr.notna()), "A", "INR 1.5 or higher")
add("platelets_lt_100", (out.platelets < 100).where(out.platelets.notna()), "A", "platelets below 100")
add("gcs_le_8", (out.gcs <= 8).where(out.gcs.notna()), "A", "GCS 8 or lower")

# ---------------------------------------------------------------------
# 3. Diagnoses: comorbidities, mechanism, injuries, symptoms
# ---------------------------------------------------------------------
dx = io.load("ipdiagnosis", ["genc_id", "diagnosis_code", "diagnosis_type"], genc_ids=encs.genc_id)
dx["code"] = dx.diagnosis_code.map(codes.normalise_code)
dx["type"] = dx.diagnosis_type.astype("string").str.strip().str.upper()
dx["patient_id_hashed"] = dx.genc_id.map(gid_pid)
poa = dx[dx.type != "2"]                             # not a complication of this stay
como = poa[~poa.code.str.startswith(codes.CHARLSON_INDEX_EXCLUDE)]
hemi = tuple(codes.CHARLSON["hemiplegia"][1])
como = como[~(como.code.str.startswith(hemi) & (como.type != "1"))]
flags(como, {k: v[1] for k, v in codes.CHARLSON.items()}, "cci_", "A", "Charlson comorbidity")
cci = out[[f"cci_{k}" for k in codes.CHARLSON]].rename(columns=lambda c: c[4:])
add("charlson_score", cci.apply(codes.charlson_score, axis=1), "A", "Charlson score from this episode's codes")
flags(como, codes.SDH_COMORBIDITIES, "hx_", "A", "comorbidity")

mech = pd.Series("none_coded", index=out.index)
ext = dx[dx.code.str.match(r"^[VWXY]")]
for name, prefixes in reversed(list(codes.MECHANISM.items())):
    mech[mech.index.isin(ext[ext.code.str.startswith(tuple(prefixes))].patient_id_hashed)] = name
add("mechanism", mech, "A", "mechanism of injury from external cause codes")
flags(poa, codes.CONCURRENT_INJURY, "inj_", "A", "concurrent injury")
add("polytrauma_proxy", poa[poa.code.str.match(r"^(S[1-9]|T0[0-7])")].groupby("patient_id_hashed")
    .code.nunique().reindex(out.index).fillna(0) >= 2, "A", "injuries in 2+ body regions outside the head")
erdx = io.load("erdiagnosis", ["genc_id", "er_diagnosis_code"], genc_ids=encs.genc_id)
erdx["code"] = erdx.er_diagnosis_code.map(codes.normalise_code)
erdx["patient_id_hashed"] = erdx.genc_id.map(gid_pid)
flags(pd.concat([poa[["patient_id_hashed", "code"]], erdx[["patient_id_hashed", "code"]]]),
      codes.SYMPTOM_CODES, "sx_", "A", "presenting symptom code")
add("anticoagulant_code", out.index.isin(dx[dx.code.str.startswith(tuple(codes.ANTICOAGULANT_CODES))]
    .patient_id_hashed), "A", "anticoagulant use / effect code")

# ---------------------------------------------------------------------
# 4. Medications: orders from the start of the episode to 24 h after time zero
# ---------------------------------------------------------------------
med_inc = "|".join(f"({p})" for p in codes.MEDS.values())
ph = io.load("pharmacy", ["genc_id", "med_id_generic_name_raw", "med_id_brand_name_raw", "med_start_date_time"],
             genc_ids=encs.genc_id,
             keep_rows=lambda b: (b.med_id_generic_name_raw.fillna("").astype(str) + " " +
                                  b.med_id_brand_name_raw.fillna("").astype(str)).str.lower()
             .str.contains(med_inc, regex=True))
ph["name"] = (ph.med_id_generic_name_raw.fillna("").astype(str) + " " +
              ph.med_id_brand_name_raw.fillna("").astype(str)).str.lower().str.strip()
ph["patient_id_hashed"] = ph.genc_id.map(gid_pid)
t = io.to_dt(ph.med_start_date_time)
start = ph.patient_id_hashed.map(pid.admission_date_time) - pd.Timedelta(hours=24)
ph["base"] = (t >= start) & (t <= ph.patient_id_hashed.map(t0) + pd.Timedelta(hours=cfg.MED_AFTER_T0_H))
chk = []
for g_, pattern in codes.MEDS.items():
    hit = ph.name.str.contains(pattern, regex=True)
    add(f"rx_{g_}", out.index.isin(ph[hit & ph.base].patient_id_hashed), "A",
        f"{g_.replace('_', ' ')} ordered from episode start to {cfg.MED_AFTER_T0_H} h after time zero")
    chk.append(ph[hit].groupby("name").size().reset_index(name="orders").assign(group=g_))
io.save_aggregate(pd.concat(chk)[["group", "name", "orders"]], "check_med_names.csv", ["orders"])
add("anticoagulated_evidence", out.anticoagulant_code | out.rx_anticoagulant_doac | out.rx_anticoagulant_warfarin
    | out.rx_reversal_pcc | out.rx_reversal_idarucizumab | out.rx_reversal_andexanet
    | out.inr_ge_1_5.fillna(False).astype(bool), "A", "any evidence of an anticoagulant at presentation")
add("antiplatelet_evidence", out.rx_antiplatelet, "A", "antiplatelet ordered around presentation")

# ---------------------------------------------------------------------
# 5. CT features from the NLP (index CT)
# ---------------------------------------------------------------------
if cfg.NLP_RESULTS_FILE.exists():
    nlp = pd.read_csv(cfg.NLP_RESULTS_FILE, dtype=str)
    nlp = nlp.rename(columns={nlp.columns[0]: "report_id"})
    drop = {"episode", "report", "report_hash", "tree", "review_flag", "error"}
    feats = [c for c in nlp.columns[1:] if c not in drop and not c.lower().endswith("_description")]
    m = pid[["index_ct_report_id"]].reset_index().merge(nlp[["report_id"] + feats], left_on="index_ct_report_id",
                                                        right_on="report_id", how="left").set_index("patient_id_hashed")
    for c in feats:
        add("ct_" + c, m[c], "A", f"index CT (NLP): {c}")
else:
    print("No NLP results yet: CT features not added (rerun this step after the NLP)")

out = out.reset_index()
io.save_patient_level(out, "baseline.csv")
dic = pd.DataFrame([{"variable": v, "group": g_, "description": d} for v, (g_, d) in groups.items()])
dic["group"] = dic.group.map({"A": "A clustering input", "B": "B equity", "C": "C care context"})
io.save_aggregate(dic, "baseline_dictionary.csv")   # names and descriptions only: safe to share
print(dic.group.value_counts().to_string())
print("Next: python phenotype/04_outcomes.py")
