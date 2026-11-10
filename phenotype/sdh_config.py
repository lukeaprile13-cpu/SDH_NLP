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
# A CT shows an SDH when the NLP gives a laterality of Left / Right / Bilateral,
# OR a falx (parafalcine) or tentorium hematoma (any value but NR / No).
NLP_SDH_LATERALITY = {"Left", "Right", "Bilateral"}
NLP_SDH_COMPARTMENTS = ["parafalcine_hematoma", "tentorium_hematoma"]
NLP_ABSENT_VALUES = {"NR", "No", ""}

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
# A head CT: the name says head / brain / cranial, or the body part is mapped
# to head. Combined scans (head + C-spine, head + face, trauma panels) are
# KEPT: they include a full non-contrast head CT and are often the first scan
# in major trauma. Purely vascular studies (CTA, venogram, perfusion) are left
# out unless the name also has a non-contrast head part.
CT_NAME_INCLUDE = r"head|brain|cranial"
CT_BODY_PART_INCLUDE = r"head|brain"
CT_VASCULAR = r"angio|\bcta\b|\bctv\b|venogra|perfusion|\bcow\b"
CT_NONCONTRAST = r"unenhanced|\bwo\b|w/o|without|no contrast|non.?con|\bnc\b|- ?cont|-/|plain"
CT_ALWAYS_EXCLUDE = r"brain death"
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

# ---------------------------------------------------------------------
# Step 6 - the clustering dataset
# ---------------------------------------------------------------------
# Inclusion rules, applied in this order (False = not applied); each one is
# a row of clustering_flowchart.csv
CLUSTER_RULES = {
    "radiology_collected": True,      # GEMINI collected radiology at that hospital on that date
    "has_ct_report": True,            # the index episode has a head CT report to read
    "sdh_confirmed_on_ct": True,      # the NLP found an SDH on a CT of the index episode
    "in_study_period": True,          # admitted 2015-01-01 to 2024-06-30
    "exclude_elective": False,        # planned admissions (no triage moment)
    "exclude_er_only_sdh": False,     # SDH code only in the ER (kept: the CT confirms it)
    "exclude_in_hospital_onset": False,
}
# Missing labs / vitals never remove a patient by default. Instead:
#  - a clustering variable missing in more than this share of patients is
#    set aside (listed in clustering_missingness_by_variable.csv, not used)
MAX_VARIABLE_MISSING_PCT = 40
#  - patients missing more than this share of the kept clustering variables
#    are flagged; set DROP_HIGH_MISSING_PATIENTS = True to remove them
MAX_PATIENT_MISSING_PCT = 50
DROP_HIGH_MISSING_PATIENTS = False
