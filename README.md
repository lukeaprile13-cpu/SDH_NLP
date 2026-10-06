# SDH NLP

`NLP_v5.ipynb` reads CT head reports and extracts subdural hematoma variables.

## Running a batch of reports

1. Put `SDH_reports.csv` in the same folder as the notebook. It needs 3 columns, in this order:
   1. the randomised report number
   2. a number from 1 to n
   3. the report text

   A header row is optional; the columns are read by position.
2. In Jupyter, choose **Run All**.
3. The results are written to `SDH_results.csv`, one row per report, with these columns:
   - `report_num`, `report_index`, `report`
   - `tree`: the parsed tree, before variable mapping
   - every study variable, in the order set by `FINAL_COLUMNS` (FINAL OUTPUT VARIABLES cell)
   - `review_flag`: why a person should read this report, empty when there is no reason. The code codes what the report says rather than guessing; for now it flags an epidural reported on the same side as a subdural, or an epidural with no side given (e.g. a report calling the same collection "extradural" in the findings and "subdural" in the conclusion)
   - `error`: empty unless that report crashed. A crashed report gets NR everywhere and the run continues.

The example report cells at the end of the notebook still show the step-by-step debug output for one report.

## Checking against human extraction

- Sheets with the final variable names (one row per report, same columns as `SDH_results.csv`): `python evaluation/compare_final.py --sheet your_sheet.xlsx`
- Older sheets: `evaluation/compare_to_human.py`

Results and the rules added are in `evaluation/RESULTS.md`.
