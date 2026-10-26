# SDH NLP - frozen version 1.2

Frozen on 2026-10-22 for the validation study (v1.2: mixed density only when the report says mixed or heterogeneous; a falx-only SDH takes the falx side as laterality; two grades keep the worst). No changes to the code after this point.

- Code version: commit cb30bc1 (branch claude/peaceful-lovelace-5czfzi)
- Constructed test cases: PASS 353/353

| File | What it is | SHA-256 |
| --- | --- | --- |
| NLP_v5.ipynb | NLP; runs a CSV of reports and validates against human values | 3ff718b3e55c84c071b1b54580f68ab6925ba6431d8c497cb3984e65b86016b1 |
| NLP_v5_single_report.ipynb | Same NLP; runs one report and prints it | 11afe58ff1cda8914397faecc7108621fa4a42fe3c12989de6bd678b7bf25594 |
| cohort/build_cohort.R | Builds the validation cohort (GEMINI) | f0e8e7fb9bbbfa6044bb5fa4834c08fa1c8a3f926d92203b6131de1fde22464a |
| cohort/sdh_extraction_app.R | Screening and extraction app | bf8748692d1ee48ad16f5d8b2f74413c2c8ab7d9fcccc458d8a665d489abf689 |
| cohort/sdh_development_app.R | Development (training) set extraction app | 432619656ca5016dd516fa18763ed1ba0313e719f834e0de870ed5a32a5bbe0b |
| evaluation/ | Test suite and scoring scripts | |

To check a copy is the frozen one, compare its SHA-256 with the table
(R: digest::digest(file = "NLP_v5.ipynb", algo = "sha256"); Python: hashlib.sha256).
