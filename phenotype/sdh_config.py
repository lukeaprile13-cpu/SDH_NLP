"""
Settings for the SDH phenotype cohort. Change things here, not in the scripts.

Anything marked VERIFY is a best guess that has to be checked against the
GEMINI data dictionary or the aggregate check tables the scripts write
(output/aggregate/check_*.csv) before the cohort is used for analysis.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------
# The login is read from the project's R connection file (the same one the
# audit script used); it is never printed or written out. Environment
# variables override it: SDH_DB_NAME, SDH_DB_HOST, SDH_DB_USER,
# SDH_DB_PASSWORD, SDH_DB_PORT.
CREDENTIALS_R_FILE = os.environ.get("SDH_CREDENTIALS_FILE", "Test/emil.R")
DB_PORT = int(os.environ.get("SDH_DB_PORT", "5432"))
SCHEMA = os.environ.get("SDH_SCHEMA", "subdural_hematoma_v1_0_0")
TABLE_SUFFIX = "_subset"          # GEMINI tables are <name>_subset
STATEMENT_TIMEOUT = "600s"

# ---------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------
# patient_level/ holds one row per patient and report text: it stays on the
# GEMINI server and is never committed. aggregate/ holds cell-suppressed
# counts only, which are safe to share.
OUTPUT_DIR = Path(os.environ.get("SDH_OUTPUT_DIR", "output"))
PATIENT_DIR = OUTPUT_DIR / "patient_level"
AGGREGATE_DIR = OUTPUT_DIR / "aggregate"
SMALL_CELL = 6                    # counts 1-5 are shown as "<6"

# ---------------------------------------------------------------------
# Cohort definition
# ---------------------------------------------------------------------
SDH_CODE_PATTERNS = ("I620%", "S065%")       # SQL LIKE; I620% keeps any subcodes
TRAUMATIC_PREFIX = "S065"
NONTRAUMATIC_PREFIX = "I620"

# DAD diagnosis types that mean the SDH was there on arrival.
# "2" = post-admit comorbidity (developed in hospital): not a presentation.
# "9" = external cause, "0" = newborn, "4" = morphology: never an SDH.
SDH_TYPES_PRESENT_ON_ARRIVAL = {"M", "1", "3", "5", "6", "W", "X", "Y"}

MIN_AGE = 18
# 2013-2014 hold only a handful of SDH encounters and 2024 ends in June.
# check_hospital_year.csv shows when each hospital starts contributing.
STUDY_START = "2015-01-01"
STUDY_END = "2024-06-30 23:59:59"

# Encounters of the same patient are one episode of care (a transfer
# between hospitals) when the next admission starts within this many hours
# of the previous discharge (or overlaps it).
TRANSFER_GAP_HOURS = 12

# Elective admissions (admit_category "L") are planned, e.g. a scheduled
# burr hole for a chronic SDH seen in clinic: not an emergency presentation.
# They are flagged in every run; set True to remove them from the cohort.
EXCLUDE_ELECTIVE = False
ELECTIVE_CATEGORIES = {"L"}

# Index head CT: the first non-contrast head CT with a report, from this
# long before the episode's first admission time to this long after (the
# ER CT is usually before the admission time).
CT_WINDOW_BEFORE_H = 48
CT_WINDOW_AFTER_H = 72
CT_NAME_INCLUDE = r"head|brain"
CT_NAME_EXCLUDE = (r"angio|\bcta\b|perfusion|venogra|spine|neck|facial|sinus|orbit|"
                   r"temporal bone|stereotac|navigation")

# ---------------------------------------------------------------------
# Baseline windows (hours relative to time zero = arrival)
# ---------------------------------------------------------------------
# Baseline = what was known at presentation. Labs and vitals: the first
# value in this window. Anything later can be affected by treatment.
LAB_WINDOW_H = (-24, 12)
VITAL_WINDOW_H = (-6, 6)
# Comorbidities may also come from earlier admissions in this lookback
PRIOR_LOOKBACK_DAYS = 730

# ---------------------------------------------------------------------
# Pathway definitions
# ---------------------------------------------------------------------
EARLY_SURGERY_H = 24              # first cranial surgery < 24 h after arrival
FOLLOW_UP_DAYS = 30               # hospital-free days, readmission
RECURRENCE_DAYS = 90              # SDH readmission / repeat surgery

# hospitals with at least this many cranial SDH operations in the cohort
# are treated as neurosurgical centres (data-driven; replace with a known
# list in HOSPITAL_TYPE if you have one)
NEUROSURGICAL_MIN_OPERATIONS = 20
# e.g. {"101": "academic_neurosurgical", "205": "community"}; VERIFY with GEMINI
HOSPITAL_TYPE = {}
