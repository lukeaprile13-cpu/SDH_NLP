# SDH phenotype dataset

Builds the analysis dataset for the SDH phenotype study from the GEMINI SDH
extraction (`gemini_sdh_cohort_v1`, made by `sdh_cohort_extraction.ipynb` in
the GEMINI GitLab repo). One row per patient: their first SDH episode of care.

**Study aim:** phenotypes at presentation that predict what happens to the
patient, to inform triage and treatment pathways, and to check that patients
with the same need get the same care (equity).

## Running (on GEMINI)

Use the `sdh-gemini` environment from the GitLab repo (`scripts/setup_env.sh`).
From this repo's root, run the steps in order:

```bash
python phenotype/01_build_cohort.py
python phenotype/02_baseline_features.py
python phenotype/03_pathways_outcomes.py
python phenotype/04_tables_and_checks.py
```

The input folder and output folder are set in `sdh_config.py` (or with the
`SDH_DATA_DIR` / `SDH_OUTPUT_DIR` environment variables). Output goes to
`~/sdh_phenotype_output` by default:

- `patient_level/`: one row per patient. **Stays on GEMINI.** Never commit it.
- `aggregate/`: counts with cells under 6 suppressed. Safe to share.

## Cohort definition (step 1)

| Step | Rule |
|---|---|
| Start | Every encounter in the extraction: age 18+, an SDH code (S06.5 or I62.0) in the ER or the inpatient abstract |
| Study period | Admitted 2015-01-01 to 2024-06-30 (2013-14 and 2024 are partial) |
| SDH on the inpatient abstract | ER-only SDH codes are provisional: removed (`INCLUDE_ER_ONLY_SDH` for a sensitivity analysis) |
| Present on arrival | At least one SDH diagnosis type other than 2 (type 2 = developed in hospital) |
| Episode of care | Encounters joined by GEMINI's `epicare` (transfers between hospitals) |
| Index episode | The patient's first qualifying episode |
| Time zero | ER triage of the first encounter (if 72 h before to 1 h after admission), else admission |
| Index head CT | First non-contrast head CT with a report, 48 h before to 72 h after admission (the NLP input) |

Elective admissions are flagged (`elective`), not removed (`EXCLUDE_ELECTIVE`).

## Variables

**Baseline (step 2): candidate phenotype inputs, known at arrival**

| Domain | Variables | Source |
|---|---|---|
| Demographics | age, sex, hospital, teaching / non-teaching | admdad, lookup_hospital |
| Severity | CTAS, mLAPS (first 24 h), GCS, SBP, HR | er, derived_variables, vitals |
| Labs | INR, PT, PTT, platelets, haemoglobin, sodium, creatinine, glucose, fibrinogen | lab (first value from 24 h before to 12 h after arrival) |
| Comorbidity | Charlson components and score (diagnosis type respected), GEMINI admission Charlson, AF, VTE, valve, alcohol, epilepsy, coagulopathy ... | ipdiagnosis, derived_variables |
| Anticoagulation | DOAC / warfarin / antiplatelet orders and reversal agents in the first 24 h, anticoagulant codes, INR >= 1.5 | pharmacy, ipdiagnosis, lab |
| Mechanism | transport, assault, fall (same level / height), other, none coded | external cause codes |
| Concurrent injury | other intracranial injury, skull / facial / spine / hip / rib fracture, polytrauma | ipdiagnosis |
| Presentation | decreased consciousness, seizure, headache, confusion, speech, hemiparesis ... | ipdiagnosis (not type 2), erdiagnosis |
| Equity | Ontario Marginalization Index 2016 / 2021 quintiles, rurality | locality_variables + StatCan lookups |
| NLP (added later) | SDH thickness, midline shift, density, laterality, herniation, atrophy ... | index CT report via `index_ct_reports_for_nlp.csv`, joined on `row_id` |

**Pathway and outcomes (step 3): never clustering inputs**

| Domain | Variables |
|---|---|
| Surgery | first cranial operation type and code, hours from arrival, calendar day, hospital; repeat operation |
| Other procedures | MMA embolization, embolization probably for an aneurysm, EVD, ventilation, craniectomy |
| Care process | ER neurosurgery consult (hours), ICU admission (hours, within 24 h), palliative care code |
| Pathway | surgery < 24 h, surgery >= 24 h, MMA embolization only, no surgery with palliative care, no surgery |
| Where | arrived at / transferred to a neurosurgical centre (>= 20 SDH operations in the cohort) |
| Outcomes | in-hospital death, death within 48 h, LOS, LOS in survivors, discharge category (home, home with support, long-term care, rehab ...), favourable discharge, 30-day readmission, SDH readmission within 90 days, days alive and out of hospital to day 30 |

## Check before analysis

The aggregate `check_*.csv` files exist so these can be verified:

1. **`check_ct_coverage_by_hospital_year.csv`**: 28% of patients have no CT report. If it clusters by hospital or year, the NLP cohort under-represents those sites.
2. **`check_intervention_codes.csv`**: every CCI code in the surgery families with its group. A neurosurgeon should confirm the groups, especially embolization (`1JW51` coils are usually aneurysm treatment; MMA is more likely `1JX51`) and the extra families (`1AA87`, `1AN52`, `1EA`).
3. **`check_discharge_disposition.csv`**: CIHI code, description and the category given.
4. **`check_lab_vital_timing.csv`**: how many values were dropped for being measured too late after arrival. GCS coverage decides whether GCS can be a clustering input.
5. **`check_med_names.csv`**: drug names matched to each group.
6. **`coverage_by_hospital.csv` / `coverage_by_year.csv`**: missing data by site and year.

## Known limitations

- Only GEMINI hospitals: deaths after discharge and readmissions elsewhere are not seen.
- The extraction only holds SDH encounters, so earlier admissions can't add comorbidities, and days in hospital on readmission are unknown (days alive and out of hospital counts the index episode only).
- Pharmacy orders in hospital are a proxy for home medication.
- Surgery times recorded as 00:00 are treated as date-only (`surgery_time_known`).
