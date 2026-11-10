"""
STEP 3 - What happened after arrival: treatment pathway and outcomes.

Never clustering inputs. Surgery is taken from the whole episode (after a
transfer the operation is usually at the receiving hospital) and timed from
time zero, so later analyses can deal with immortal time. Palliative care
is its own flag, so "no surgery" is not mostly patients whose care was
withdrawn.

    python phenotype/03_pathways_outcomes.py

Writes patient_level/pathways_outcomes.parquet and aggregate/
check_intervention_codes.csv, check_discharge_disposition.csv,
check_surgery_hospitals.csv.
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
t0, ep_end = co.time_zero, co.discharge_date_time
gid_pid = ep.set_index("genc_id").patient_id_hashed
out = co[["row_id"]].copy()

# ---------------------------------------------------------------------
# 1. Interventions of the episode
# ---------------------------------------------------------------------
cols = ["genc_id", "intervention_code", "intervention_episode_start_date_time"]
iv = pd.concat([io.load("ipintervention", cols), io.load("erintervention", cols)], ignore_index=True)
iv = iv[iv.genc_id.isin(ep.genc_id)].copy()
iv["code"] = iv.intervention_code.map(codes.normalise_code)
iv["when"] = io.to_dt(iv.intervention_episode_start_date_time)
iv["time_known"] = iv["when"].notna() & (iv["when"].dt.strftime("%H:%M") != "00:00")
iv["patient_id_hashed"] = iv.genc_id.map(gid_pid)
iv["h"] = io.hours_between(iv["when"], iv.patient_id_hashed.map(t0))

# the extraction's reviewed list first, then the extra families for review
sdh_list = pd.read_csv(cfg.DATA_DIR / "sdh_surgery_codes.csv", dtype=str)
sdh_type = dict(zip(sdh_list.code.map(codes.normalise_code), sdh_list.sdh_surgery_type))
sdh_type = {c: t for c, t in sdh_type.items() if c not in codes.NOT_SDH_SURGERY}
iv["group"] = iv.code.map(sdh_type)
for g, prefixes in codes.EXTRA_INTERVENTION_GROUPS.items():
    iv.loc[iv.group.isna() & iv.code.str.startswith(tuple(prefixes)), "group"] = g

# embolization with an aneurysm / non-traumatic SAH code in the episode is
# most likely aneurysm treatment, not middle meningeal artery embolization
dx = io.load("ipdiagnosis", ["genc_id", "diagnosis_code", "diagnosis_type"])
dx = dx[dx.genc_id.isin(ep.genc_id)].copy()
dx["code"] = dx.diagnosis_code.map(codes.normalise_code)
dx["patient_id_hashed"] = dx.genc_id.map(gid_pid)
aneurysm = set(dx[dx.code.str.startswith(tuple(codes.ANEURYSM_CODES))].patient_id_hashed)
emb = iv.group.eq("embolization")
iv.loc[emb & iv.patient_id_hashed.isin(aneurysm), "group"] = "embolization_probable_aneurysm"
iv.loc[emb & ~iv.patient_id_hashed.isin(aneurysm), "group"] = "mma_embolization"

fam = iv[iv.code.str.startswith(tuple(codes.INTERVENTION_CHECK_FAMILIES)) | iv.group.notna()]
lk = io.load("lookup_cci", ["intervention_code", "cci_short_title"])
lk["code"] = lk.intervention_code.map(codes.normalise_code)
io.save_aggregate(fam.groupby(["code", "group"], dropna=False)
                  .agg(patients=("patient_id_hashed", "nunique"), rows=("code", "size"),
                       with_time=("time_known", "sum")).reset_index()
                  .merge(lk[["code", "cci_short_title"]].drop_duplicates("code"), on="code", how="left")
                  .sort_values("patients", ascending=False),
                  "check_intervention_codes.csv", ["patients", "rows", "with_time"])

iv = iv.sort_values("when")
cran = iv[iv.group.isin(codes.CRANIAL_SURGERY_GROUPS)]
first = cran.groupby("patient_id_hashed").first()
out["cranial_surgery"] = out.index.isin(first.index)
out["first_surgery_type"] = first.group
out["first_surgery_code"] = first.code
out["surgery_hours_from_t0"] = first.h.round(1)
out["surgery_time_known"] = first.time_known
out["surgery_calendar_day"] = (first["when"].dt.normalize() - t0.reindex(first.index).dt.normalize()).dt.days
out["surgery_hospital"] = first.genc_id.map(ep.set_index("genc_id").hospital_num).astype("string")
out["n_cranial_procedure_dates"] = cran.groupby("patient_id_hashed")["when"].agg(
    lambda s: s.dt.normalize().nunique()).reindex(out.index).fillna(0).astype(int)
out["repeat_cranial_surgery_in_episode"] = out.n_cranial_procedure_dates > 1
for g in ("mma_embolization", "embolization_probable_aneurysm", "ventricular_drain", "mechanical_ventilation",
          "decompressive_craniectomy"):
    hit = iv[iv.group == g].groupby("patient_id_hashed").h.min()
    out[g] = out.index.isin(hit.index)
    out[f"{g}_hours_from_t0"] = hit.round(1)

# ---------------------------------------------------------------------
# 2. Palliative care, ICU, neurosurgery consult
# ---------------------------------------------------------------------
out["palliative_care_coded"] = out.index.isin(dx[dx.code.str.startswith(tuple(codes.PALLIATIVE_CODES))].patient_id_hashed)

scu = io.load("ipscu", ["genc_id", "scu_admit_date_time", "icu_flag"])
scu = scu[scu.genc_id.isin(ep.genc_id)].copy()
scu = scu[io.truthy(scu.icu_flag)] if "icu_flag" in scu else scu
scu["patient_id_hashed"] = scu.genc_id.map(gid_pid)
scu["h"] = io.hours_between(io.to_dt(scu.scu_admit_date_time), scu.patient_id_hashed.map(t0))
icu = scu.groupby("patient_id_hashed").h.min()
out["icu_admission"] = out.index.isin(icu.index)
out["icu_hours_from_t0"] = icu.round(1)
out["icu_within_24h"] = out.icu_hours_from_t0 < 24

cons = io.load("erconsults", ["genc_id", "consult_service_description", "consult_request_date_time"])
cons = cons[cons.genc_id.isin(ep.genc_id) &
            cons.consult_service_description.fillna("").str.lower().str.contains("neuro.?surg|neurosx|nsx")].copy()
cons["patient_id_hashed"] = cons.genc_id.map(gid_pid)
cons["h"] = io.hours_between(io.to_dt(cons.consult_request_date_time), cons.patient_id_hashed.map(t0))
nc = cons.groupby("patient_id_hashed").h.min()
out["er_neurosurgery_consult"] = out.index.isin(nc.index)
out["neurosurgery_consult_hours_from_t0"] = nc.round(1)

# ---------------------------------------------------------------------
# 3. Pathway
# ---------------------------------------------------------------------
early = out.surgery_hours_from_t0 < cfg.EARLY_SURGERY_H
out["pathway"] = np.select(
    [out.cranial_surgery & early, out.cranial_surgery, out.mma_embolization, out.palliative_care_coded],
    ["surgery_early", "surgery_delayed", "mma_embolization_only", "no_surgery_palliative"], default="no_surgery")

# ---------------------------------------------------------------------
# 4. Outcomes
# ---------------------------------------------------------------------
e = io.load("encounters", ["genc_id", "discharge_disposition", "dv_in_hospital_mortality_derived",
                           "dv_readmission_30d_derived", "discharge_ts"])
e = e[e.genc_id.isin(ep.genc_id)].merge(ep[["genc_id", "patient_id_hashed", "order_in_episode"]], on="genc_id")
e["died"] = io.truthy(e.dv_in_hospital_mortality_derived)
last = e.sort_values("order_in_episode").groupby("patient_id_hashed").last()

out["died_in_hospital"] = out.index.isin(e[e.died].patient_id_hashed)
out["episode_los_days"] = ((ep_end - t0).dt.total_seconds() / 86400).round(2)
out["days_to_death"] = out.episode_los_days.where(out.died_in_hospital)
out["survivor_los_days"] = out.episode_los_days.where(~out.died_in_hospital)
out["died_within_48h"] = out.died_in_hospital & (out.episode_los_days < 2)

# discharge disposition of the last encounter, mapped from CIHI's descriptions
lk = io.load("lookup_cihi_codes")
lk = lk[lk.column_name.astype(str).str.lower().eq("discharge_disposition")]
desc = dict(zip(lk.value.astype(str).str.strip(), lk.description))
raw = last.discharge_disposition.astype("string").str.strip()
cat = raw.map(lambda v: codes.disposition_category(desc.get(v, desc.get(str(v).lstrip("0"), ""))))
io.save_aggregate(pd.DataFrame({"raw_code": raw, "description": raw.map(desc), "category": cat})
                  .groupby(["raw_code", "description", "category"], dropna=False).size().reset_index(name="patients"),
                  "check_discharge_disposition.csv", ["patients"])
out["discharge_disposition_raw"] = raw
out["discharge_category"] = cat.where(~out.died_in_hospital.reindex(cat.index), "died")
out["favourable_discharge"] = out.discharge_category.isin(codes.FAVOURABLE_DISPOSITIONS)
out["discharged_to_new_facility"] = out.discharge_category.isin(["long_term_care", "rehabilitation", "other_facility"])

# readmission (GEMINI-derived: any GEMINI hospital) among survivors; SDH
# readmission from the patient's later cohort encounters
surv = ~out.died_in_hospital
out["readmitted_30d"] = io.truthy(last.dv_readmission_30d_derived).reindex(out.index).astype("boolean").where(surv)
allc = io.load("cohort", ["genc_id", "patient_id_hashed", "admission_date_time"])
allc = allc[allc.patient_id_hashed.isin(out.index) & ~allc.genc_id.isin(ep.genc_id)].copy()
allc["days"] = (io.to_dt(allc.admission_date_time) - allc.patient_id_hashed.map(ep_end)).dt.total_seconds() / 86400
re_sdh = allc[allc.days.between(0, cfg.RECURRENCE_DAYS)].patient_id_hashed
out["sdh_readmission_90d"] = pd.Series(out.index.isin(re_sdh), index=out.index).astype("boolean").where(surv)

# days alive and out of hospital to day 30 (readmission days are not in the
# extraction, so survivors are counted from the index episode only)
out["days_alive_out_of_hospital_30"] = (cfg.FOLLOW_UP_DAYS - out.episode_los_days.clip(upper=cfg.FOLLOW_UP_DAYS)) \
    .where(~out.died_in_hospital, 0).round(1)

# ---------------------------------------------------------------------
# 5. Where patients were treated
# ---------------------------------------------------------------------
ops = out.groupby("surgery_hospital").size()
neuro = set(ops[ops >= cfg.NEUROSURGICAL_MIN_OPERATIONS].index.astype(str))
io.save_aggregate(ops.rename("sdh_operations").reset_index()
                  .assign(neurosurgical_centre=lambda d: d.surgery_hospital.astype(str).isin(neuro)),
                  "check_surgery_hospitals.csv", ["sdh_operations"])
hosps = co.hospitals_in_episode.fillna("").astype(str).str.split("; ")
first_h = co.hospital_num.astype(str)
out["arrived_at_neurosurgical_centre"] = first_h.isin(neuro)
out["transferred_to_neurosurgical_centre"] = pd.Series(
    [(f not in neuro) and any(h in neuro for h in hs) for f, hs in zip(first_h, hosps)], index=co.index)
print(f"Neurosurgical centres (>= {cfg.NEUROSURGICAL_MIN_OPERATIONS} SDH operations): {len(neuro)}")
print("Pathway:", out.pathway.value_counts().to_dict())

out = out.reset_index()
io.save_patient_level(out, "pathways_outcomes.parquet")
print("Next: python phenotype/04_tables_and_checks.py")
