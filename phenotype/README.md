# SDH phenotype datasets

Builds the analysis datasets for the SDH phenotype study from the GEMINI SDH
extraction (`gemini_sdh_cohort_v1`, made by `sdh_cohort_extraction.ipynb` in
the GEMINI GitLab repo).

**Aim:** phenotypes at presentation that predict what happens to patients,
to inform triage and treatment pathways, and to check that patients with the
same need get the same care (equity).

## What comes out

```
                 cohort_key.csv  (one row per patient)
                 row_id, episode, time zero, index CT, flags
                          |  joined on row_id
          +---------------+----------------+
          v                                v
   baseline.csv                      outcomes.csv
   known at time zero                what happened after
   A clustering inputs               surgery (type, timing), ICU, consult,
   B equity                          palliative care, pathway, death, LOS,
   C care context                    discharge, readmission
```

`baseline_dictionary.csv` says which group (A / B / C) each baseline variable
is in. Equity (B) and care-context (C) variables are kept out of the
clustering so the equity question is not circular: phenotypes describe the
patient, and B / C test whether the same phenotype gets the same care.

## Decisions

| Topic | Decision |
|---|---|
| Who | Adults 18+ with an SDH code (S06.5 or I62.0) in the ER or inpatient record |
| Exclusions | None at this stage: everything is **flagged** (ER-only SDH code, SDH developed in hospital, elective, transferred in from outside GEMINI, no CT report, outside 2015-01 to 2024-06, SDH not confirmed on CT) and decided at analysis |
| SDH confirmation | The NLP reads every head CT report; an episode is confirmed when any CT shows an SDH |
| Transfers | Encounters joined into one episode when GEMINI's `epicare` links them or the next admission starts within 12 h of the last discharge. If the first hospital is not in GEMINI, the episode starts at the GEMINI hospital (flagged) |
| Index episode | Each patient's first episode with the SDH confirmed on CT (else their first episode, flagged) |
| Time zero | Came in with the SDH: ER triage of the first hospital (else admission). SDH developed in hospital: the first CT showing it |
| Index CT | The first CT showing the SDH (its NLP features go into the baseline) |
| Baseline labs / vitals | The value closest to time zero: labs 24 h before to 12 h after, vitals 6 h before to 6 h after |
| Clustering inputs (A) | CT features (NLP), vitals, labs, age, **sex**, comorbidities, anticoagulation, mechanism, injuries, symptoms, CTAS, mLAPS |
| Equity (B) | Ontario Marginalization Index 2016 / 2021 quintiles, rurality |
| Care context (C) | Hospital, teaching / non-teaching, year, flags, when each value was measured |

## Running (on GEMINI)

Use the `sdh-gemini` environment from the GitLab repo. From this repo's root:

```bash
python phenotype/01_episodes_and_ct_reports.py   # episodes, flags, every head CT report
#   -> run NLP_v5.ipynb on patient_level/ct_reports_for_nlp.csv
#      (OUTPUT_CSV = "ct_reports_nlp_results.csv", RUN_VALIDATION = False)
#      and put the result in patient_level/
python phenotype/02_cohort_key.py                # confirm SDH, time zero, index episode
python phenotype/03_baseline.py                  # baseline.csv
python phenotype/04_outcomes.py                  # outcomes.csv
python phenotype/05_tables_and_checks.py         # Table 1, coverage
```

Steps 2-5 also run before the NLP (every CT then counts as showing the SDH,
and `nlp_available` is False), so the pipeline can be checked first.

Folders are set in `sdh_config.py` (or `SDH_DATA_DIR` / `SDH_OUTPUT_DIR`).
Output goes to `~/sdh_phenotype_output`:

- `patient_level/`: one row per patient or report. **Stays on GEMINI. Never commit it.**
- `aggregate/`: counts with cells under 6 suppressed. Safe to share.

## Check before analysis

| File | Question |
|---|---|
| `step1_counts.csv`, `step2_counts.csv` | How many patients carry each flag |
| `check_transfer_linking.csv` | Do epicare and the 12 h rule agree on transfers? |
| `check_ct_coverage_by_hospital_year.csv` | Where are CT reports missing? |
| `check_ct_names.csv` | Which CT names count as head CTs |
| `check_lab_vital_names.csv`, `check_lab_vital_timing.csv` | Which lab / vital names were used, units, coverage (GCS!) |
| `check_med_names.csv` | Drug names in each medication group |
| `check_intervention_codes.csv` | Surgery codes and groups: needs a neurosurgeon (embolization `1JW51` coils are usually aneurysm treatment; MMA is more likely `1JX51`) |
| `check_discharge_disposition.csv` | CIHI codes and the category given |
| `coverage_by_hospital.csv`, `coverage_by_year.csv` | Missing data by site and year |

Also check whether every hospital contributes neurosurgery-service
admissions (`lookup_hospital.other_inpatient_cohort_avail`, and the most
responsible service by hospital and year): where they don't, operated
patients are missing.

## Known limitations

- The NLP was built on reports that contain an SDH. Its handling of reports
  with **no** SDH (normal scans, "resolved") must be checked before it is used
  to confirm SDH.
- Only GEMINI hospitals: deaths after discharge and readmissions elsewhere are not seen.
- The extraction only holds SDH encounters, so earlier admissions can't add
  comorbidities, and days in hospital on readmission are unknown.
- Pharmacy orders in hospital are a proxy for home medication.
- Surgery times recorded as 00:00 are treated as date-only (`surgery_time_known`).
