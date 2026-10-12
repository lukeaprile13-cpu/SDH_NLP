# SDH NLP

`NLP_v5.ipynb` reads CT head reports and extracts subdural hematoma variables.

## Running a batch of reports (and validating)

1. Put your CSV in the same folder as the notebook. Column A and B: report numbers, column C: the report text, columns D onwards (optional): the human-extracted values, with a header row naming the variables.
2. In the **SETTINGS** cell (section "RUN ALL REPORTS AND VALIDATE") write the CSV's file name in `INPUT_CSV`.
3. Menu **Kernel → Restart & Run All**.

Outputs, in the same folder:
- `SDH_results.csv`: the report numbers, the report, `tree` (before variable mapping), every variable, `review_flag`, `error`.
- `SDH_validation_summary.csv`: overall accuracy, sensitivity, PPV, F1, specificity and kappa, with 95% CIs.
- `SDH_validation_by_variable.csv`: the same metrics for each variable.
- `SDH_validation_mismatches.csv`: every report / variable where the NLP and the human differ.
- `SDH_validation_confusion.csv`: human value × NLP value counts for each variable.

Set `RUN_VALIDATION = False` to only extract (for a CSV with no human values). Rows without report text are skipped.

## Checking against human extraction

- Sheets with the final variable names (one row per report, same columns as `SDH_results.csv`): `python evaluation/compare_final.py --sheet your_sheet.xlsx`
- Older sheets: `evaluation/compare_to_human.py`

Results and the rules added are in `evaluation/RESULTS.md`.
