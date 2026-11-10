"""
Settings for the SDH phenotype dataset. Change things here, not in the scripts.

Input: the GEMINI SDH extraction (gemini_sdh_cohort_v1, built by
sdh_cohort_extraction.ipynb). Output: a folder of your own on GEMINI.
Anything marked VERIFY needs checking against the aggregate check tables
(output/aggregate/check_*.csv) before analysis.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------
# Folders (both on GEMINI; patient-level data never leaves it)
# ---------------------------------------------------------------------
DATA_DIR = Path(os.environ.get(
    "SDH_DATA_DIR", "/mnt/nfs/project/subdural_hematoma_endotypes/gemini_sdh_cohort_v1"))
OUTPUT_DIR = Path(os.environ.get("SDH_OUTPUT_DIR", Path.home() / "sdh_phenotype_output"))
PATIENT_DIR = OUTPUT_DIR / "patient_level"   # one row per patient: stays on GEMINI
AGGREGATE_DIR = OUTPUT_DIR / "aggregate"     # cell-suppressed counts: safe to share
SMALL_CELL = 6                               # counts 1-5 are shown as "<6"

# ---------------------------------------------------------------------
# Cohort
# ---------------------------------------------------------------------
STUDY_START = "2015-01-01"
STUDY_END = "2024-07-01"                     # exclusive: admissions to 2024-06-30
# An SDH coded only in the ER (never on the inpatient abstract) is a
# provisional diagnosis; left out by default, kept as a sensitivity analysis.
INCLUDE_ER_ONLY_SDH = False
# Elective admissions (admit_category "L"), e.g. a planned burr hole, are
# not emergency presentations. Always flagged; True removes them.
EXCLUDE_ELECTIVE = False
ELECTIVE_CATEGORIES = {"L"}

# Time zero = ER triage of the episode's first encounter when it falls in
# this window around the admission time; otherwise the admission time.
TRIAGE_WINDOW_H = (-72, 1)

# Index head CT: first non-contrast head CT with a report, from this long
# before the episode's first admission to this long after.
CT_WINDOW_BEFORE_H = 48
CT_WINDOW_AFTER_H = 72
CT_NAME_INCLUDE = r"head|brain"
CT_NAME_EXCLUDE = (r"angio|\bcta\b|perfusion|venogra|spine|neck|facial|sinus|orbit|"
                   r"temporal bone|stereotac|navigation")
REQUIRE_CT_REPORT = True                     # the NLP needs the report text

# ---------------------------------------------------------------------
# Baseline (hours relative to time zero)
# ---------------------------------------------------------------------
# Lab / vital values measured later than this after arrival are blanked:
# by then treatment (reversal, transfusion, surgery) can have changed them.
LAB_MAX_HOURS_AFTER_T0 = 12
VITAL_MAX_HOURS_AFTER_T0 = 6
MED_BASELINE_WINDOW_H = (-24, 24)            # orders that reflect home medication

# ---------------------------------------------------------------------
# Pathways and outcomes
# ---------------------------------------------------------------------
EARLY_SURGERY_H = 24
FOLLOW_UP_DAYS = 30
RECURRENCE_DAYS = 90
NEUROSURGICAL_MIN_OPERATIONS = 20            # hospitals with this many SDH operations
