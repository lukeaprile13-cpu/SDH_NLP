# SDH NLP - frozen version 1.2

Frozen on 2026-10-22 for the validation study (v1.2: mixed density only when the report says mixed or heterogeneous; a falx-only SDH takes the falx side as laterality; two grades keep the worst). No changes to the code after this point.

- Code version: commit cb30bc1 (branch claude/peaceful-lovelace-5czfzi)
- Constructed test cases: PASS 353/353

**v1.3 in progress (not frozen).** The notebooks have changed since v1.2 (see
V1.3_CHANGES.md), so their hashes below are the v1.2 ones and will not match the
current files. To get the exact v1.2 code, check out commit cb30bc1. v1.3 gets
its own hashes here when it is frozen, before the validation run.

| File | What it is | SHA-256 |
| --- | --- | --- |
| NLP_v5.ipynb | NLP; runs a CSV of reports and validates against human values | 3ff718b3e55c84c071b1b54580f68ab6925ba6431d8c497cb3984e65b86016b1 |
| NLP_v5_single_report.ipynb | Same NLP; runs one report and prints it | 11afe58ff1cda8914397faecc7108621fa4a42fe3c12989de6bd678b7bf25594 |
| cohort/build_cohort.R | Builds the validation cohort (GEMINI) | f0e8e7fb9bbbfa6044bb5fa4834c08fa1c8a3f926d92203b6131de1fde22464a |
| cohort/sdh_extraction_app.R | Screening and extraction app | 858c5c7532f0942ea5d4123a79727003bfbd8184e8073775d9535dae4ea0f3fd |
| cohort/sdh_development_app.R | Development (training) set extraction app | 6a90186904b462b6645a96552e6d9d1c121e6b5ef87682aff608371a65d1ddc0 |
| evaluation/ | Test suite and scoring scripts | |

To check a copy is the frozen one, compare its SHA-256 with the table
(R: digest::digest(file = "NLP_v5.ipynb", algo = "sha256"); Python: hashlib.sha256).
