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
   - `error`: empty unless that report crashed. A crashed report gets NR everywhere and the run continues.

The example report cells at the end of the notebook still show the step-by-step debug output for one report.

## Checking against human extraction

See `evaluation/compare_to_human.py` and `evaluation/RESULTS.md`.
