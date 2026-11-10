"""
STEP 2 - Baseline features: what was known when the patient arrived.

Candidate phenotype (clustering) inputs plus equity and adjustment
variables. Lab and vital values come from the extraction's encounter-level
columns, re-checked against time zero (arrival): values measured too long
after arrival are blanked, because treatment may already have changed them.
Comorbidities, injuries and symptoms come from the raw diagnosis tables with
the diagnosis type respected (type 2 = developed in hospital is left out).

    python phenotype/02_baseline_features.py

Writes patient_level/baseline_features.parquet and aggregate/
check_lab_vital_timing.csv, check_med_names.csv.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdh_codes as codes
import sdh_config as cfg
import sdh_io as io

co = io.read_patient_level("cohort.parquet").set_index("patient_id_hashed")
ep = io.read_patient_level("episode_encounters.parquet")
t0 = co.time_zero
gid_pid = ep.set_index("genc_id").patient_id_hashed
out = co[["row_id"]].copy()


def flags(frame, groups, prefix):
    """frame: patient_id_hashed, code. One boolean column per group."""
    res = pd.DataFrame(index=out.index)
    for name, prefixes in groups.items():
        res[prefix + name] = res.index.isin(frame[frame.code.str.startswith(tuple(prefixes))].patient_id_hashed)
    return res


# ---------------------------------------------------------------------
# 1. Encounter-level variables (first encounter of the episode)
# ---------------------------------------------------------------------
LAB_VARS = ["inr", "pt", "ptt", "platelets", "hemoglobin", "sodium", "creatinine", "glucose", "fibrinogen"]
VITAL_VARS = ["gcs", "sbp", "dbp", "heart_rate", "resp_rate", "spo2", "temperature"]
first_cols = ["er_triage_level", "dv_mlaps_24hrs", "dv_admit_charlson_derived", "ext_fall", "ext_transport",
              "ext_assault", "transfer_institution_from_type_mns", "residence_code"]
lv_cols = [f"lab_{v}{s}" for v in LAB_VARS for s in ("", "_ts", "_unit")] + \
          [f"vital_{v}{s}" for v in VITAL_VARS for s in ("", "_ts")]
import pyarrow.parquet as pq
names = pq.ParquetFile(cfg.DATA_DIR / "encounters.parquet").schema_arrow.names
equity_cols = [c for c in names if c.startswith(("sc21_", "sc16_"))]
e = io.load("encounters", ["genc_id"] + first_cols + lv_cols + equity_cols)
e = e[e.genc_id.isin(ep.genc_id)].merge(ep[["genc_id", "patient_id_hashed", "order_in_episode"]], on="genc_id")
f1 = e[e.order_in_episode == 1].set_index("patient_id_hashed")

out["ctas"] = pd.to_numeric(f1.er_triage_level.astype("string").str.extract(r"(\d)")[0], errors="coerce")
out["mlaps_24h"] = pd.to_numeric(f1.dv_mlaps_24hrs, errors="coerce")
out["charlson_admit_gemini"] = pd.to_numeric(f1.dv_admit_charlson_derived, errors="coerce")
for c in ("ext_fall", "ext_transport", "ext_assault"):
    if c in f1:
        out[c] = io.truthy(f1[c])
out["came_from_type"] = f1.get("transfer_institution_from_type_mns")
for c in equity_cols:
    out["nbhd_" + c] = f1[c]

# Labs / vitals: the earliest value across the episode's encounters that was
# measured from 24 h before to LAB_MAX (VITAL_MAX) hours after time zero
checks = []
for kind, vars_, max_after, defs in (("lab", LAB_VARS, cfg.LAB_MAX_HOURS_AFTER_T0, codes.LABS),
                                     ("vital", VITAL_VARS, cfg.VITAL_MAX_HOURS_AFTER_T0, codes.VITALS)):
    for v in vars_:
        col, ts = f"{kind}_{v}", f"{kind}_{v}_ts"
        if col not in e:
            continue
        x = e[["patient_id_hashed", col, ts]].copy()
        x["val"] = io.to_number(x[col])
        x["h"] = io.hours_between(io.to_dt(x[ts]), x.patient_id_hashed.map(t0))
        if v == "hemoglobin":
            x.loc[x.val < 25, "val"] *= 10          # g/dL -> g/L
        if v == "creatinine":
            x.loc[x.val < 15, "val"] *= 88.4        # mg/dL -> umol/L
        if v == "glucose":
            x.loc[x.val > 60, "val"] /= 18          # mg/dL -> mmol/L
        lo, hi = defs[v][2:] if v in defs else (5, 150)
        present = x.val.notna()
        plausible = x.val.between(lo, hi)
        timely = x.h.between(-24, max_after)
        keep = x[present & plausible & timely].sort_values("h").groupby("patient_id_hashed").first()
        out[v] = keep.val
        out[f"{v}_hours_from_t0"] = keep.h.round(1)
        checks.append({"variable": v, "encounters_with_value": int(present.sum()),
                       "implausible": int((present & ~plausible).sum()),
                       "blanked_too_late": int((present & plausible & (x.h > max_after)).sum()),
                       "blanked_too_early": int((present & plausible & (x.h < -24)).sum()),
                       "no_timestamp": int((present & x.h.isna()).sum()),
                       "patients_kept": int(keep.shape[0]),
                       "pct_patients_kept": round(100 * keep.shape[0] / len(out), 1),
                       "median_kept": round(keep.val.median(), 2) if len(keep) else None,
                       "median_hours_from_t0": round(keep.h.median(), 1) if len(keep) else None})
io.save_aggregate(pd.DataFrame(checks), "check_lab_vital_timing.csv",
                  ["encounters_with_value", "implausible", "blanked_too_late", "blanked_too_early",
                   "no_timestamp", "patients_kept"])
for v in ("inr", "platelets", "gcs"):
    if v not in out:
        out[v] = np.nan
out["inr_ge_1_5"] = (out.inr >= 1.5).where(out.inr.notna())
out["platelets_lt_100"] = (out.platelets < 100).where(out.platelets.notna())
out["gcs_le_8"] = (out.gcs <= 8).where(out.gcs.notna())

# ---------------------------------------------------------------------
# 2. Diagnoses of the episode: comorbidities, mechanism, injuries, symptoms
# ---------------------------------------------------------------------
dx = io.load("ipdiagnosis", ["genc_id", "diagnosis_code", "diagnosis_type"])
dx = dx[dx.genc_id.isin(ep.genc_id)].copy()
dx["code"] = dx.diagnosis_code.map(codes.normalise_code)
dx["type"] = dx.diagnosis_type.astype("string").str.strip().str.upper()
dx["patient_id_hashed"] = dx.genc_id.map(gid_pid)
poa = dx[dx.type != "2"]

como = poa[~poa.code.str.startswith(codes.CHARLSON_INDEX_EXCLUDE)]
hemi = tuple(codes.CHARLSON["hemiplegia"][1])
como = como[~(como.code.str.startswith(hemi) & (como.type != "1"))]
cci = flags(como, {k: v[1] for k, v in codes.CHARLSON.items()}, "cci_")
out = out.join(cci)
out["charlson_score"] = cci.rename(columns=lambda c: c[4:]).apply(codes.charlson_score, axis=1)
out = out.join(flags(como, codes.SDH_COMORBIDITIES, "hx_"))

mech = pd.Series("none_coded", index=out.index)
ext = dx[dx.code.str.match(r"^[VWXY]")]
for name, prefixes in reversed(list(codes.MECHANISM.items())):
    mech[mech.index.isin(ext[ext.code.str.startswith(tuple(prefixes))].patient_id_hashed)] = name
out["mechanism"] = mech
out = out.join(flags(poa, codes.CONCURRENT_INJURY, "inj_"))
out["polytrauma_proxy"] = poa[poa.code.str.match(r"^(S[1-9]|T0[0-7])")].groupby("patient_id_hashed") \
    .code.nunique().reindex(out.index).fillna(0) >= 2

erdx = io.load("erdiagnosis", ["genc_id", "er_diagnosis_code"])
erdx = erdx[erdx.genc_id.isin(ep.genc_id)].copy()
erdx["code"] = erdx.er_diagnosis_code.map(codes.normalise_code)
erdx["patient_id_hashed"] = erdx.genc_id.map(gid_pid)
out = out.join(flags(pd.concat([poa[["patient_id_hashed", "code"]], erdx[["patient_id_hashed", "code"]]]),
                     codes.SYMPTOM_CODES, "sx_"))
out["anticoagulant_code"] = out.index.isin(dx[dx.code.str.startswith(tuple(codes.ANTICOAGULANT_CODES))].patient_id_hashed)

# ---------------------------------------------------------------------
# 3. Medications around arrival (raw pharmacy)
# ---------------------------------------------------------------------
ph = io.load("pharmacy", ["genc_id", "med_id_generic_name_raw", "med_id_brand_name_raw", "med_start_date_time"])
ph = ph[ph.genc_id.isin(ep.genc_id)].copy()
ph["name"] = (ph.med_id_generic_name_raw.fillna("").astype(str) + " " +
              ph.med_id_brand_name_raw.fillna("").astype(str)).str.lower().str.strip()
ph["patient_id_hashed"] = ph.genc_id.map(gid_pid)
ph["h"] = io.hours_between(io.to_dt(ph.med_start_date_time), ph.patient_id_hashed.map(t0))
base = ph[ph.h.between(*cfg.MED_BASELINE_WINDOW_H)]
chk = []
for g, pattern in codes.MEDS.items():
    hit = ph.name.str.contains(pattern, regex=True)
    out[f"rx_{g}_first_24h"] = out.index.isin(base[hit.loc[base.index]].patient_id_hashed)
    chk.append(ph[hit].groupby("name").size().reset_index(name="orders").assign(group=g))
io.save_aggregate(pd.concat(chk)[["group", "name", "orders"]], "check_med_names.csv", ["orders"])

out["anticoagulated_evidence"] = (out.anticoagulant_code | out.rx_anticoagulant_doac_first_24h
                                  | out.rx_anticoagulant_warfarin_first_24h | out.rx_reversal_pcc_first_24h
                                  | out.rx_reversal_idarucizumab_first_24h | out.rx_reversal_andexanet_first_24h
                                  | out.inr_ge_1_5.fillna(False).astype(bool))
out["antiplatelet_evidence"] = out.rx_antiplatelet_first_24h

out = out.reset_index()
io.save_patient_level(out, "baseline_features.parquet")
print("Next: python phenotype/03_pathways_outcomes.py")
