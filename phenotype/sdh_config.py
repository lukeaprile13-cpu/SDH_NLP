"""
Settings for the SDH phenotype datasets. Change things here, not in the scripts.

Input: the GEMINI SDH extraction (gemini_sdh_cohort_v1, from
sdh_cohort_extraction.ipynb). Output: a folder of your own on GEMINI.
Anything marked VERIFY needs checking against the aggregate check tables
(aggregate/check_*.csv) before analysis.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------
# Folders (both on GEMINI; patient-level files never leave it)
# ---------------------------------------------------------------------
DATA_DIR = Path(os.environ.get(
    "SDH_DATA_DIR", "/mnt/nfs/project/subdural_hematoma_endotypes/gemini_sdh_cohort_v1"))
OUTPUT_DIR = Path(os.environ.get("SDH_OUTPUT_DIR", Path.home() / "sdh_phenotype_output"))
PATIENT_DIR = OUTPUT_DIR / "patient_level"   # stays on GEMINI
AGGREGATE_DIR = OUTPUT_DIR / "aggregate"     # cell-suppressed counts: safe to share
SMALL_CELL = 6                               # counts 1-5 are shown as "<6"

# The NLP results for ct_reports_for_nlp.csv (NLP_v5.ipynb's OUTPUT_CSV).
# Until it exists, step 2 falls back to "first CT with a report".
NLP_RESULTS_FILE = PATIENT_DIR / "ct_reports_nlp_results.csv"
# NLP laterality values that mean an SDH is on the scan ("NR" = none reported)
NLP_SDH_LATERALITY = {"Left", "Right", "Bilateral", "Falx"}

# ---------------------------------------------------------------------
# Cohort: everyone is kept and flagged; exclusions happen at analysis
# ---------------------------------------------------------------------
STUDY_START = "2015-01-01"                   # flag in_study_period
STUDY_END = "2024-07-01"                     # exclusive
ELECTIVE_CATEGORIES = {"L"}                  # flag elective

# Encounters of one patient are one episode of care when GEMINI's epicare
# links them OR the next admission starts within this many hours of the
# previous discharge (or overlaps it).
TRANSFER_GAP_HOURS = 12

# Time zero for patients who came in with the SDH: ER triage of the first
# encounter when within this window around its admission; else admission.
# For SDH that developed in hospital: the CT that showed it.
TRIAGE_WINDOW_H = (-72, 1)

# Head CTs (all with a report go to the NLP)
CT_NAME_INCLUDE = r"head|brain"
CT_NAME_EXCLUDE = (r"angio|\bcta\b|perfusion|venogra|spine|neck|facial|sinus|orbit|"
                   r"temporal bone|stereotac|navigation")
# The index CT of a patient who came in with the SDH is looked for from this
# long before the episode's first admission to this long after it
CT_WINDOW_BEFORE_H = 48
CT_WINDOW_AFTER_H = 72

# ---------------------------------------------------------------------
# Baseline: the value closest to time zero within these windows (hours)
# ---------------------------------------------------------------------
LAB_WINDOW_H = (-24, 12)
VITAL_WINDOW_H = (-6, 6)
MED_AFTER_T0_H = 24          # medication orders from episode start to this long after time zero

# ---------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------
EARLY_SURGERY_H = 24
FOLLOW_UP_DAYS = 30
RECURRENCE_DAYS = 90
NEUROSURGICAL_MIN_OPERATIONS = 20            # hospitals with this many SDH operations
