"""
STEP 3 - What happened after arrival: treatment pathway and outcomes.

These are never clustering inputs. Surgery timing is measured from time
zero, so later analyses can handle immortal time (landmark or
clone-censor-weight); palliative care is its own flag so a "no surgery"
group is not mostly patients whose care was withdrawn.

    python phenotype/03_pathways_outcomes.py

Writes output/patient_level/pathways_outcomes.csv and
check_intervention_codes.csv, check_discharge_disposition.csv,
check_neurosurgical_hospitals.csv in output/aggregate/.
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
for c in ("time_zero", "admission_date_time", "discharge_date_time"):
    cohort[c] = db.to_dt(cohort[c])
for c in ("admission_date_time", "discharge_date_time"):
    enc[c] = db.to_dt(enc[c])
enc["in_index_episode"] = enc["in_index_episode"].astype(str).str.lower().eq("true")
enc["sdh_coded"] = enc["sdh_codes"].notna()

c = cohort.set_index("patient_id_hashed")
t0, ep_end = c["time_zero"], c["discharge_date_time"]
out = cohort[["row_id", "patient_id_hashed"]].set_index("patient_id_hashed")

idx_enc = enc[enc.in_index_episode & enc.patient_id_hashed.isin(out.index)].copy()
# admissions after the index episode, up to RECURRENCE_DAYS after its discharge
later = enc[~enc.in_index_episode & enc.patient_id_hashed.isin(out.index)].copy()
later["ep_end"] = later.patient_id_hashed.map(ep_end)
later["days_after"] = (later.admission_date_time - later.ep_end).dt.total_seconds() / 86400
later = later[(later.days_after >= 0) & (later.days_after <= cfg.RECURRENCE_DAYS)]
gid_to_pid = pd.concat([idx_enc, later])[["genc_id", "patient_id_hashed"]].set_index("genc_id")["patient_id_hashed"]

# ---------------------------------------------------------------------
# 1. Interventions (CCI)
# ---------------------------------------------------------------------
def interventions(table):
    c_code = sc.col(table, [r"^intervention_code$", r"intervention_code", r"code"], required=True)
    c_dt = sc.col(table, [r"start.*date_time", r"intervention.*date_time"])
    c_date = sc.col(table, [r"start_date$", r"episode_start_date", r"date$"])
    c_time = sc.col(table, [r"start_time$", r"episode_start_time", r"time$"])
    sel = ["genc_id", f"{c_code} AS code"]
    sel += [f"{c_dt} AS dt"] if c_dt else [f"{c_date} AS d"] + ([f"{c_time}::text AS tm"] if c_time else [])
    x = db.query_ids(conn, f"SELECT {', '.join(sel)} FROM {table} WHERE genc_id = ANY(%(ids)s)", gid_to_pid.index)
    if c_dt:
        x["when"] = db.to_dt(x.dt)
        x["time_known"] = x["when"].notna() & (x["when"].dt.strftime("%H%M") != "0000")
    elif c_date:
        x["when"], x["time_known"] = db.combine_date_time(x.d, x.tm if c_time else None)
    else:
        x["when"], x["time_known"] = pd.NaT, False
    return x[["genc_id", "code", "when", "time_known"]]


tables = [sc.table("ipintervention")] + sc.find_tables(r"^erintervention")
iv = pd.concat([interventions(t) for t in tables if t], ignore_index=True)
iv["code"] = iv.code.map(codes.normalise_code)
iv["patient_id_hashed"] = iv.genc_id.map(gid_to_pid)
iv["in_index"] = iv.genc_id.isin(idx_enc.genc_id)
iv["h"] = db.hours_between(iv["when"], iv.patient_id_hashed.map(t0))
iv["group"] = None
for g, prefixes in codes.INTERVENTION_GROUPS.items():
    iv.loc[iv.group.isna() & iv.code.str.startswith(tuple(prefixes)), "group"] = g
iv["cranial_surgery"] = iv.group.isin(codes.CRANIAL_SURGERY_GROUPS)

chk = iv[iv["in_index"] & iv.code.str.startswith(tuple(codes.INTERVENTION_CHECK_FAMILIES))]
db.save_aggregate(chk.groupby(["code", "group"], dropna=False).agg(
    patients=("patient_id_hashed", "nunique"), with_time=("time_known", "sum")).reset_index()
    .sort_values("patients", ascending=False), "check_intervention_codes.csv", ["patients", "with_time"])

ix = iv[iv["in_index"]].sort_values("when")
cran = ix[ix.cranial_surgery]
first = cran.groupby("patient_id_hashed").first()
out["cranial_surgery"] = out.index.isin(first.index)
out["first_surgery_group"] = first.group.reindex(out.index)
out["first_surgery_code"] = first.code.reindex(out.index)
out["surgery_hours_from_t0"] = first.h.reindex(out.index).round(1)
out["surgery_time_known"] = first.time_known.reindex(out.index)
out["surgery_calendar_day"] = (first["when"].dt.normalize() -
                               t0.reindex(first.index).dt.normalize()).dt.days.reindex(out.index)
out["n_cranial_procedure_dates"] = cran.groupby("patient_id_hashed")["when"].apply(
    lambda s: s.dt.normalize().nunique()).reindex(out.index).fillna(0).astype(int)
for g in ("mma_embolization", "ventricular_drain", "mechanical_ventilation"):
    hit = ix[ix.group == g].groupby("patient_id_hashed").h.min()
    out[g] = out.index.isin(hit.index)
    out[f"{g}_hours_from_t0"] = hit.reindex(out.index).round(1)
out["surgery_hospital"] = cran.groupby("patient_id_hashed").genc_id.first() \
    .map(idx_enc.set_index("genc_id").hospital_num).reindex(out.index)

# repeat surgery: a second operation date in the episode, or an operation
# on a readmission within RECURRENCE_DAYS
re_op = iv[~iv["in_index"] & iv.cranial_surgery].patient_id_hashed.unique()
out["repeat_cranial_surgery_90d"] = (out.n_cranial_procedure_dates > 1) | out.index.isin(re_op)

# ---------------------------------------------------------------------
# 2. Palliative care, ICU
# ---------------------------------------------------------------------
DX = sc.table("ipdiagnosis")
dx = db.query_ids(conn, f"SELECT genc_id, diagnosis_code FROM {DX} WHERE genc_id = ANY(%(ids)s)",
                  idx_enc.genc_id)
dx["code"] = dx.diagnosis_code.map(codes.normalise_code)
pall = dx[dx.code.str.startswith(tuple(codes.PALLIATIVE_CODES))].genc_id.map(gid_to_pid).unique()
out["palliative_care_coded"] = out.index.isin(pall)

SCU = sc.table("ipscu", required=False)
if SCU:
    c_in = sc.col(SCU, [r"^scu_admit_date_time$", r"admit.*date.*time", r"date_time"])
    if c_in:
        scu = db.query_ids(conn, f"SELECT genc_id, {c_in} AS t FROM {SCU} WHERE genc_id = ANY(%(ids)s)",
                           idx_enc.genc_id)
        scu["patient_id_hashed"] = scu.genc_id.map(gid_to_pid)
        scu["h"] = db.hours_between(db.to_dt(scu.t), scu.patient_id_hashed.map(t0))
        first_icu = scu.groupby("patient_id_hashed").h.min()
        out["icu_hours_from_t0"] = first_icu.reindex(out.index).round(1)
        out["icu_within_24h"] = out.icu_hours_from_t0 < 24

# ---------------------------------------------------------------------
# 3. Pathway
# ---------------------------------------------------------------------
early = out.surgery_hours_from_t0 < cfg.EARLY_SURGERY_H
pathway = np.select(
    [out.cranial_surgery & early, out.cranial_surgery, out.mma_embolization, out.palliative_care_coded],
    ["surgery_early", "surgery_delayed", "mma_only", "no_surgery_palliative"], default="no_surgery")
out["pathway"] = pathway

# ---------------------------------------------------------------------
# 4. Outcomes
# ---------------------------------------------------------------------
DV = sc.table("derived_variables")
c_mort = sc.col(DV, [r"^in_hospital_mortality_derived$", r"mortality"])
c_icu = sc.col(DV, [r"^icu_entry_derived$", r"icu_entry"])
sel = ["genc_id"] + [f"{col} AS {a}" for col, a in [(c_mort, "died"), (c_icu, "icu_entry")] if col]
dv = db.query_ids(conn, f"SELECT {', '.join(sel)} FROM {DV} WHERE genc_id = ANY(%(ids)s)", gid_to_pid.index)
truthy = lambda s: s.astype("string").str.lower().isin(["true", "t", "1", "yes", "y"])
for col in ("died", "icu_entry"):
    if col in dv:
        dv[col] = truthy(dv[col])
dv["patient_id_hashed"] = dv.genc_id.map(gid_to_pid)
dv["in_index"] = dv.genc_id.isin(idx_enc.genc_id)
dvi = dv[dv["in_index"]]
out["died_in_hospital"] = out.index.isin(dvi[dvi.died].patient_id_hashed) if "died" in dvi else np.nan
if "icu_entry" in dvi:
    out["icu_entry"] = out.index.isin(dvi[dvi.icu_entry].patient_id_hashed)

out["episode_los_days"] = ((ep_end - t0).dt.total_seconds() / 86400).reindex(out.index).round(2)
out["days_to_death"] = out.episode_los_days.where(out.died_in_hospital == True)
out["survivor_los_days"] = out.episode_los_days.where(out.died_in_hospital == False)
out["alive_in_hospital_at_24h"] = (out.episode_los_days >= 1)

# discharge disposition of the last admission of the episode
last = idx_enc.sort_values("admission_date_time").groupby("patient_id_hashed").last()
raw = last.get("discharge_disposition", pd.Series(dtype="string")).astype("string").str.strip()
mapped = raw.map(codes.DISPOSITION_MAP)
mapped = mapped.where(raw.notna())
db.save_aggregate(pd.DataFrame({"raw_code": raw, "mapped": mapped.fillna("UNMAPPED")})
                  .groupby(["raw_code", "mapped"], dropna=False).size().reset_index(name="patients"),
                  "check_discharge_disposition.csv", ["patients"])
out["discharge_disposition_raw"] = raw.reindex(out.index)
out["discharge_category"] = mapped.reindex(out.index)
out.loc[out.died_in_hospital == True, "discharge_category"] = "died"
out["favourable_discharge"] = out.discharge_category.isin(codes.FAVOURABLE_DISPOSITIONS) \
    .where(out.discharge_category.notna())
out["discharged_to_new_facility"] = out.discharge_category.isin(["long_term_care", "other_facility"])

# readmissions (GEMINI hospitals only)
surv = out.index[out.died_in_hospital == False]
r30 = later[later.days_after <= cfg.FOLLOW_UP_DAYS]
survivor = pd.Series(out.index.isin(surv), index=out.index)
# among survivors of the index episode only (blank for those who died)
out["readmitted_30d"] = pd.Series(out.index.isin(r30.patient_id_hashed), index=out.index) \
    .astype("boolean").where(survivor)
sdh_r = later[later.sdh_coded]
out["sdh_readmission_90d"] = pd.Series(out.index.isin(sdh_r.patient_id_hashed), index=out.index) \
    .astype("boolean").where(survivor)
died_later = dv[~dv["in_index"] & dv.get("died", False)].patient_id_hashed.unique() if "died" in dv else []
out["died_on_readmission_90d"] = out.index.isin(died_later)

# hospital-free days to day 30 (0 if died in the index episode)
window_end = t0 + pd.Timedelta(days=cfg.FOLLOW_UP_DAYS)
days_in = ((ep_end.clip(upper=window_end) - t0).dt.total_seconds() / 86400).clip(lower=0)
r = later.copy()
r["t0"], r["wend"] = r.patient_id_hashed.map(t0), r.patient_id_hashed.map(window_end)
r = r[r.admission_date_time < r.wend]
r["d"] = ((r.discharge_date_time.clip(upper=r.wend) - r.admission_date_time).dt.total_seconds() / 86400).clip(lower=0)
days_in = days_in.add(r.groupby("patient_id_hashed").d.sum(), fill_value=0)
hfd = (cfg.FOLLOW_UP_DAYS - days_in).clip(lower=0).reindex(out.index)
died_30 = (out.died_in_hospital == True) | out.index.isin(
    later[(later.days_after <= cfg.FOLLOW_UP_DAYS) & later.genc_id.isin(dv[dv.get("died", False)].genc_id)]
    .patient_id_hashed) if "died" in dv else (out.died_in_hospital == True)
out["hospital_free_days_30"] = hfd.where(~died_30, 0).round(1)

# ---------------------------------------------------------------------
# 5. Hospital neurosurgical capability (data-driven)
# ---------------------------------------------------------------------
ops = out.groupby("surgery_hospital").size()
neuro = set(ops[ops >= cfg.NEUROSURGICAL_MIN_OPERATIONS].index.astype(str))
db.save_aggregate(ops.rename("cranial_operations").reset_index()
                  .assign(neurosurgical_centre=lambda d: d.surgery_hospital.astype(str).isin(neuro)),
                  "check_neurosurgical_hospitals.csv", ["cranial_operations"])
first_hosp = c["hospital_num"].astype(str)
hosps = c["hospitals_in_episode"].fillna("").astype(str).str.split("; ")
out["arrived_at_neurosurgical_centre"] = first_hosp.isin(neuro).reindex(out.index)
out["transferred_to_neurosurgical_centre"] = pd.Series(
    [(f not in neuro) and any(h in neuro for h in hs) for f, hs in zip(first_hosp, hosps)],
    index=c.index).reindex(out.index)
print(f"Neurosurgical centres (>= {cfg.NEUROSURGICAL_MIN_OPERATIONS} operations): {len(neuro)}")
print("Pathway:", out.pathway.value_counts().to_dict())

out = out.reset_index()
db.save_patient_level(out, "pathways_outcomes.csv")
print("Done. Next: python phenotype/04_data_checks.py")
