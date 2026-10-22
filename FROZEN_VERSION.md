# SDH NLP - frozen version 1.0

Frozen on 2026-10-22 for the validation study. No changes to the code after this point.

- Code version: commit 4930f9c (branch claude/peaceful-lovelace-5czfzi)
- Constructed test cases: PASS 346/346

| File | What it is | SHA-256 |
| --- | --- | --- |
| NLP_v5.ipynb | NLP; runs a CSV of reports and validates against human values | e1c621d39b4dda8c0af6f7ca2c847a064c093c326281e64d83310367ebd0ea21 |
| NLP_v5_single_report.ipynb | Same NLP; runs one report and prints it | 166f3d854ff5724d6fee911292a576e06b4479b7ef7e953fd26378c324338fa7 |
| cohort/build_cohort.R | Builds the validation cohort (GEMINI) | 4ad357b0aa9e3edb2df5a27ea9b491b9178a7096d966872c4e1c27ad7b5aeb52 |
| cohort/sdh_extraction_app.R | Screening and extraction app | 31973970ece3f781ff11b12c1feabb7295a4467305d7d290bb3e2021e0a5921c |
| evaluation/ | Test suite and scoring scripts | |

To check a copy is the frozen one, compare its SHA-256 with the table
(R: digest::digest(file = "NLP_v5.ipynb", algo = "sha256"); Python: hashlib.sha256).
