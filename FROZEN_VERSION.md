# SDH NLP - frozen version 1.1

Frozen on 2026-10-22 for the validation study (v1.1: two grades for one column keep the worst grade). No changes to the code after this point.

- Code version: commit 1445e94 (branch claude/peaceful-lovelace-5czfzi)
- Constructed test cases: PASS 348/348

| File | What it is | SHA-256 |
| --- | --- | --- |
| NLP_v5.ipynb | NLP; runs a CSV of reports and validates against human values | 76864a48f7fd29717b4f914bd082e97d9630d8a6843a0b03894fd943a959a6c0 |
| NLP_v5_single_report.ipynb | Same NLP; runs one report and prints it | e5c9f39f44862a9ea564ef4fdc1b8b2c50c0f36341759c704e6c3e7352813d9c |
| cohort/build_cohort.R | Builds the validation cohort (GEMINI) | 4ad357b0aa9e3edb2df5a27ea9b491b9178a7096d966872c4e1c27ad7b5aeb52 |
| cohort/sdh_extraction_app.R | Screening and extraction app | 31973970ece3f781ff11b12c1feabb7295a4467305d7d290bb3e2021e0a5921c |
| evaluation/ | Test suite and scoring scripts | |

To check a copy is the frozen one, compare its SHA-256 with the table
(R: digest::digest(file = "NLP_v5.ipynb", algo = "sha256"); Python: hashlib.sha256).
