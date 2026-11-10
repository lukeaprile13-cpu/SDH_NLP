"""
STEP 2 - Baseline features: what was known when the patient arrived.

These are the candidate phenotype (clustering) inputs, plus the equity and
adjustment variables. Nothing that happens after arrival is used, except
where noted (reversal agents in the first 24 h are a proxy for being on an
anticoagulant at home).

    python phenotype/02_baseline_features.py

Reads cohort.csv and encounters.csv from step 1.
Writes output/patient_level/baseline_features.csv (one row per patient) and
check_lab_names.csv, check_vital_names.csv, check_med_names.csv,
check_locality_columns.csv in output/aggregate/.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_codes as codes
import sdh_config as cfg
import sdh_db as db

conn = db.connect()
sc = db.Schema(conn)

cohort = db.read_patient_level("cohort.csv")
enc = db.read_patient_level("encounters.csv")
for c in ("time_zero", "admission_date_time"):
    cohort[c] = db.to_dt(cohort[c])
for c in ("admission_date_time", "discharge_date_time"):
    enc[c] = db.to_dt(enc[c])
enc["in_index_episode"] = enc["in_index_episode"].astype(str).str.lower().eq("true")

t0 = cohort.set_index("patient_id_hashed")["time_zero"]
out = cohort[["row_id", "patient_id_hashed"]].copy().set_index("patient_id_hashed")

# encounters that belong to the index episode, and admissions in the lookback
idx_enc = enc[enc.in_index_episode & enc.patient_id_hashed.isin(out.index)][["genc_id", "patient_id_hashed"]]
pe = enc[~enc.in_index_episode & enc.patient_id_hashed.isin(out.index)].copy()
pe["t0"] = pe.patient_id_hashed.map(t0)
prior_enc = pe[(pe.admission_date_time < pe.t0) &
               (pe.admission_date_time >= pe.t0 - pd.Timedelta(days=cfg.PRIOR_LOOKBACK_DAYS))]
prior_1y = prior_enc[prior_enc.admission_date_time >= prior_enc.t0 - pd.Timedelta(days=365)]
out["prior_admissions_1y"] = prior_1y.groupby("patient_id_hashed").size().reindex(out.index).fillna(0).astype(int)
out["prior_admissions_2y"] = prior_enc.groupby("patient_id_hashed").size().reindex(out.index).fillna(0).astype(int)
gid_to_pid = pd.concat([idx_enc, prior_enc[["genc_id", "patient_id_hashed"]]]).drop_duplicates() \
    .set_index("genc_id")["patient_id_hashed"]
print(f"Index episode encounters: {len(idx_enc)}; lookback admissions: {len(prior_enc)}")


def flag_frame(frame, groups, prefix=""):
    """One boolean column per group: any code in `frame` (patient, code) matches."""
    res = pd.DataFrame(index=out.index)
    for name, prefixes in groups.items():
        hit = frame[frame.code.str.startswith(tuple(prefixes))].patient_id_hashed.unique()
        res[prefix + name] = res.index.isin(hit)
    return res


# ---------------------------------------------------------------------
# 1. Diagnoses: comorbidities, mechanism, injuries, presenting symptoms
# ---------------------------------------------------------------------
DX = sc.table("ipdiagnosis")
dx = db.query_ids(conn, f"SELECT genc_id, diagnosis_code, diagnosis_type FROM {DX} WHERE genc_id = ANY(%(ids)s)",
                  gid_to_pid.index)
dx["code"] = dx.diagnosis_code.map(codes.normalise_code)
dx["type"] = dx.diagnosis_type.astype("string").str.strip().str.upper()
dx["patient_id_hashed"] = dx.genc_id.map(gid_to_pid)
dx["in_index"] = dx.genc_id.isin(idx_enc.genc_id)
index_dx = dx[dx.in_index]
index_poa = index_dx[index_dx.type != "2"]          # not developed in hospital
prior_dx = dx[~dx.in_index]

# Comorbidities: the index episode (not type 2, not the SDH and its
# neighbours, hemiplegia only when pre-admit) plus the lookback admissions
como_index = index_poa[~index_poa.code.str.startswith(codes.CHARLSON_INDEX_EXCLUDE)]
hemi = tuple(codes.CHARLSON["hemiplegia"][1])
como_index = como_index[~(como_index.code.str.startswith(hemi) & (como_index.type != "1"))]
como = pd.concat([como_index, prior_dx])

charlson = flag_frame(como, {k: v[1] for k, v in codes.CHARLSON.items()}, "cci_")
out = out.join(charlson)
out["charlson_score"] = charlson.rename(columns=lambda c: c[4:]).apply(codes.charlson_score, axis=1)
out = out.join(flag_frame(como, codes.SDH_COMORBIDITIES, "hx_"))
out["comorbidity_from_prior_admission_available"] = out.prior_admissions_2y > 0

# Mechanism: external cause codes of the index episode, first match wins
mech = pd.Series("none_coded", index=out.index)
ext = index_dx[index_dx.code.str.match(r"^[VWXY]")]
for name, prefixes in reversed(list(codes.MECHANISM.items())):
    hit = ext[ext.code.str.startswith(tuple(prefixes))].patient_id_hashed.unique()
    mech[mech.index.isin(hit)] = name
out["mechanism"] = mech
out = out.join(flag_frame(index_poa, codes.CONCURRENT_INJURY, "inj_"))
out["polytrauma_proxy"] = index_poa[index_poa.code.str.match(r"^(S[1-9]|T0[0-7])")] \
    .groupby("patient_id_hashed").code.nunique().reindex(out.index).fillna(0) >= 2

symptoms = flag_frame(index_poa, codes.SYMPTOM_CODES, "sx_")
anticoag_codes = pd.concat([index_dx, prior_dx])
out["anticoagulant_code"] = flag_frame(anticoag_codes, {"x": codes.ANTICOAGULANT_CODES}).x
out["antiplatelet_code"] = flag_frame(anticoag_codes, {"x": codes.ANTIPLATELET_CODES}).x

# ---------------------------------------------------------------------
# 2. Emergency department
# ---------------------------------------------------------------------
start = cohort.set_index("start_genc_id")["patient_id_hashed"]
ER = sc.table("er", required=False)
if ER:
    c_triage = sc.col(ER, [r"^triage_level$", r"ctas", r"triage_level"])
    c_time = sc.col(ER, [r"^triage_date_time$", r"triage.*date.*time"])
    c_compl = sc.cols(ER, r"complaint")
    sel = ["genc_id"] + [f"{c} AS {a}" for c, a in [(c_triage, "triage_level"), (c_time, "triage_time")] if c]
    sel += [f"{c}::text AS complaint_{i}" for i, c in enumerate(c_compl)]
    er = db.query_ids(conn, f"SELECT {', '.join(sel)} FROM {ER} WHERE genc_id = ANY(%(ids)s)", start.index)
    er["patient_id_hashed"] = er.genc_id.map(start)
    if "triage_time" in er:
        er = er.sort_values("triage_time")
    er = er.groupby("patient_id_hashed").first()
    if "triage_level" in er:
        out["ctas"] = pd.to_numeric(er.triage_level.astype("string").str.extract(r"(\d)")[0],
                                    errors="coerce").reindex(out.index)
    ccols = [c for c in er.columns if c.startswith("complaint_")]
    if ccols:
        text = er[ccols[0]].fillna("").astype(str)
        for c in ccols[1:]:
            text = text + " " + er[c].fillna("").astype(str)
        text = text.str.lower().reindex(out.index).fillna("")
        out["er_complaint_recorded"] = text.str.strip().ne("")
        for name, pattern in codes.COMPLAINT_KEYWORDS.items():
            out[name] = text.str.contains(pattern, regex=True)
    else:
        print("er table has no complaint column")
ERDX = sc.table("erdiagnosis", required=False)
if ERDX:
    c_code = sc.col(ERDX, [r"^er_diagnosis_code$", r"diagnosis_code"])
    erdx = db.query_ids(conn, f"SELECT genc_id, {c_code} AS code FROM {ERDX} WHERE genc_id = ANY(%(ids)s)",
                        idx_enc.genc_id)
    erdx["code"] = erdx.code.map(codes.normalise_code)
    erdx["patient_id_hashed"] = erdx.genc_id.map(gid_to_pid)
    symptoms = symptoms | flag_frame(erdx, codes.SYMPTOM_CODES, "sx_")
out = out.join(symptoms)
out["arrived_by_ambulance"] = cohort.set_index("patient_id_hashed").get(
    "admit_via_ambulance", pd.Series(dtype="string")).reindex(out.index).astype("string") \
    .str.upper().str.strip().isin(["Y", "1", "TRUE", "A", "C", "G"])     # VERIFY codes
out["transferred_in"] = cohort.set_index("patient_id_hashed").get(
    "institution_from", pd.Series(dtype="string")).reindex(out.index).notna()


# ---------------------------------------------------------------------
# 3. Labs and vitals: first value in the baseline window
# ---------------------------------------------------------------------
def measurements(table, defs, window, check_name, name_patterns, value_patterns, time_patterns,
                 unit_patterns=(r"unit",), omop_patterns=(r"omop",)):
    if table is None:
        print(f"no {check_name} table: skipped")
        return pd.DataFrame(index=out.index)
    c_name = sc.col(table, name_patterns, required=True)
    c_val = sc.col(table, value_patterns, required=True)
    c_time = sc.col(table, time_patterns, required=True)
    c_unit = sc.col(table, list(unit_patterns))
    c_omop = sc.col(table, list(omop_patterns))
    pattern = "|".join(f"({d[0]})" for d in defs.values())
    sel = [f"genc_id", f"{c_name}::text AS name", f"{c_val}::text AS value", f"{c_time} AS t"]
    sel += [f"{c_unit}::text AS unit"] if c_unit else []
    sel += [f"{c_omop}::text AS omop"] if c_omop else []
    m = db.query_ids(conn, f"SELECT {', '.join(sel)} FROM {table} "
                           f"WHERE genc_id = ANY(%(ids)s) AND LOWER({c_name}::text) ~ %(pat)s",
                     idx_enc.genc_id, params={"pat": db.pg_regex(pattern)})
    m["patient_id_hashed"] = m.genc_id.map(gid_to_pid)
    m["h"] = db.hours_between(db.to_dt(m.t), m.patient_id_hashed.map(t0))
    m["lname"] = m.name.str.lower()
    m["num"] = db.to_number(m.value)
    res, checks = pd.DataFrame(index=out.index), []
    for var, (inc, exc, lo, hi) in defs.items():
        hit = m.lname.str.contains(inc, regex=True)
        if var == "dbp":                              # also '150/90' recorded as blood pressure
            hit |= m.lname.str.contains(r"blood pressure|\bbp\b|nibp", regex=True) & m.value.str.contains("/", na=False)
        r = m[hit]
        if exc:
            r = r[~r.lname.str.contains(exc, regex=True)]
        r = r.copy()
        if var == "hemoglobin":                       # g/dL -> g/L
            r.loc[r.num < 25, "num"] *= 10
        if var == "creatinine":                       # mg/dL -> umol/L
            r.loc[r.num < 15, "num"] *= 88.4
        if var == "dbp":                              # '150/90' -> 90
            r["num"] = db.to_number(r.value.str.split("/").str[-1])
        r["plausible"] = r.num.between(lo, hi)
        keys = ["name"] + [k for k in ("unit", "omop") if k in r]
        checks.append(r.groupby(keys, dropna=False).agg(rows=("num", "size"), plausible=("plausible", "sum"),
                                                        median=("num", "median")).reset_index()
                      .assign(variable=var))
        w = r[r.plausible & r.h.between(*window)].sort_values("h")
        first = w.groupby("patient_id_hashed").first()
        res[var] = first.num.reindex(res.index)
        res[f"{var}_hours_from_t0"] = first.h.reindex(res.index).round(1)
    if checks:
        chk = pd.concat(checks, ignore_index=True)
        chk["median"] = chk["median"].round(2)
        db.save_aggregate(chk[["variable"] + [c for c in chk if c != "variable"]],
                          f"check_{check_name}_names.csv", ["rows", "plausible"])
    return res


LAB = sc.table("lab", required=False)
out = out.join(measurements(LAB, codes.LABS, cfg.LAB_WINDOW_H, "lab",
                            [r"^test_name_raw$", r"test.*name", r"name"],
                            [r"^result_value$", r"result.*value", r"value"],
                            [r"^collection_date_time$", r"collect.*date.*time", r"date_time"]))
VIT = sc.table("vitals", required=False) or next(iter(sc.find_tables(r"vital")), None)
out = out.join(measurements(VIT, codes.VITALS, cfg.VITAL_WINDOW_H, "vital",
                            [r"measure.*name", r"name_raw", r"name"],
                            [r"measurement_value", r"value"],
                            [r"measure.*date.*time", r"collect.*date.*time", r"date_time"]))
for v in ("inr", "platelets"):
    if v not in out:
        out[v] = np.nan
out["inr_ge_1_5"] = (out.inr >= 1.5).where(out.inr.notna())
out["platelets_lt_100"] = (out.platelets < 100).where(out.platelets.notna())


# ---------------------------------------------------------------------
# 4. Medications and blood products
# ---------------------------------------------------------------------
def orders(table, groups, name_pattern, time_patterns, check_name, enc_ids):
    if table is None:
        print(f"no {check_name} table: skipped")
        return None
    names = sc.cols(table, name_pattern)
    c_time = sc.col(table, time_patterns)
    if not names or not c_time:
        print(f"{table}: no name or time column found; skipped")
        return None
    text = " || ' ' || ".join(f"COALESCE({c}::text, '')" for c in names)
    pattern = "|".join(f"({p})" for p in groups.values())
    m = db.query_ids(conn, f"SELECT genc_id, LOWER({text}) AS name, {c_time} AS t FROM {table} "
                           f"WHERE genc_id = ANY(%(ids)s) AND LOWER({text}) ~ %(pat)s",
                     enc_ids, params={"pat": db.pg_regex(pattern)})
    m["patient_id_hashed"] = m.genc_id.map(gid_to_pid)
    m["h"] = db.hours_between(db.to_dt(m.t), m.patient_id_hashed.map(t0))
    m["in_index"] = m.genc_id.isin(idx_enc.genc_id)
    chk = []
    for g, p in groups.items():
        m[g] = m.name.str.contains(p, regex=True)
        chk.append(m[m[g]].groupby("name").size().reset_index(name="orders").assign(group=g))
    if chk:
        db.save_aggregate(pd.concat(chk)[["group", "name", "orders"]], f"check_{check_name}_names.csv", ["orders"])
    return m


PH = sc.table("pharmacy", required=False)
meds = orders(PH, codes.MEDS, r"generic|brand|med_name|drug|name_raw",
              [r"start.*date.*time", r"order.*date.*time", r"date_time"], "med",
              gid_to_pid.index)
TR = sc.table("transfusion", required=False)
blood = orders(TR, codes.BLOOD_PRODUCTS, r"product|component|blood|name",
               [r"issue.*date.*time", r"date_time", r"time"], "transfusion", idx_enc.genc_id)

for g in codes.MEDS:
    out[f"rx_{g}_first_24h"] = False
if meds is not None:
    first24 = meds[meds["in_index"] & meds.h.between(-24, 24)]
    for g in codes.MEDS:
        out[f"rx_{g}_first_24h"] = out.index.isin(first24[first24[g]].patient_id_hashed)
    prior = meds[~meds["in_index"]]
    for g in ("anticoagulant_doac", "anticoagulant_warfarin", "antiplatelet"):
        out[f"rx_{g}_prior_admission"] = out.index.isin(prior[prior[g]].patient_id_hashed)
for g in codes.BLOOD_PRODUCTS:
    out[f"bb_{g}_first_24h"] = False
if blood is not None:
    b24 = blood[blood.h.between(-24, 24)]
    for g in codes.BLOOD_PRODUCTS:
        out[f"bb_{g}_first_24h"] = out.index.isin(b24[b24[g]].patient_id_hashed)

# best available evidence of an anticoagulant / antiplatelet at home
get = lambda c: out[c] if c in out else False
out["anticoagulated_evidence"] = (
    out.anticoagulant_code | get("rx_anticoagulant_doac_first_24h") | get("rx_anticoagulant_warfarin_first_24h")
    | get("rx_anticoagulant_doac_prior_admission") | get("rx_anticoagulant_warfarin_prior_admission")
    | get("rx_reversal_pcc_first_24h") | get("rx_reversal_idarucizumab_first_24h")
    | get("rx_reversal_andexanet_first_24h") | get("bb_pcc_blood_bank_first_24h")
    | out.inr_ge_1_5.fillna(False).astype(bool))
out["antiplatelet_evidence"] = (out.antiplatelet_code | get("rx_antiplatelet_first_24h")
                                | get("rx_antiplatelet_prior_admission"))

# ---------------------------------------------------------------------
# 5. Neighbourhood / equity variables (when the data cut has them)
# ---------------------------------------------------------------------
loc_tables = sc.find_tables(r"locality|neighbo|census|marg|ses")
found = []
for t in loc_tables:
    if "genc_id" not in sc.columns[t]:
        continue
    cols = [c for c in sc.columns[t] if c != "genc_id" and
            any(k in c.lower() for k in ("quintile", "income", "marg", "instab", "depriv", "dependen",
                                         "ethnic", "rural", "ses", "material", "residential"))]
    found += [{"table": t, "column": c} for c in cols]
    if cols:
        loc = db.query_ids(conn, f"SELECT genc_id, {', '.join(cols)} FROM {t} WHERE genc_id = ANY(%(ids)s)",
                           start.index)
        loc = loc.assign(patient_id_hashed=loc.genc_id.map(start)).groupby("patient_id_hashed").first()
        out = out.join(loc[cols].add_prefix("nbhd_"))
db.save_aggregate(pd.DataFrame(found or [{"table": "none found", "column": ""}]),
                  "check_locality_columns.csv")

# ---------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------
out = out.reset_index()
db.save_patient_level(out, "baseline_features.csv")
print("Done. Next: python phenotype/03_pathways_outcomes.py")
