"""Builds phenotype/notebooks/*.ipynb (one per pipeline step).

    python phenotype/notebooks/_make_notebooks.py phenotype/notebooks
"""
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

SETUP = '''import os, sys
from pathlib import Path
import pandas as pd
from IPython.display import display, Markdown

# To write the output somewhere else, uncomment and edit BEFORE importing sdh_config:
# os.environ["SDH_OUTPUT_DIR"] = str(Path.home() / "sdh_phenotype_output")

PHENO = Path.cwd().parent              # the phenotype/ folder (this notebook is in phenotype/notebooks/)
sys.path.insert(0, str(PHENO))
import sdh_config as cfg
import sdh_io as io
pd.set_option("display.max_rows", 200, "display.max_columns", 60, "display.width", 220)
AGG = cfg.AGGREGATE_DIR


def show(name, rows=None, note=None):
    """Display one aggregate (cell-suppressed) table from the output folder."""
    path = AGG / name
    if not path.exists():
        print(f"{name}: not there yet (run the step above first)")
        return None
    df = pd.read_csv(path)
    display(Markdown(f"**{name}**" + (f" - {note}" if note else "")))
    display(df.head(rows) if rows else df)
    return df


def share(names, rows=80):
    """Print aggregate tables as text to paste to Claude / your team (counts only, small cells suppressed)."""
    for name in names:
        path = AGG / name
        if path.exists():
            df = pd.read_csv(path)
            print(f"===== {name} ({len(df)} rows{', first ' + str(rows) if len(df) > rows else ''}) =====")
            print(df.head(rows).to_csv(index=False))
        else:
            print(f"===== {name}: not found =====")
'''

PRIVACY = ("> **Privacy:** everything this notebook *displays* comes from `aggregate/` "
           "(counts with cells under 6 suppressed). Files in `patient_level/` stay on GEMINI: "
           "don't print their rows, and never paste them outside GEMINI.")


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")}


def code(text):
    text = text.strip("\n")
    if text.startswith("show(") and "\n" not in text:
        text += ";"          # show() displays the table itself; don't echo it twice
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}


def notebook(name, cells):
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python (sdh-gemini)", "language": "python",
                                                      "name": "sdh-gemini"},
                                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    for i, c in enumerate(nb["cells"]):
        c["id"] = f"{name[:2]}-{i:02d}"
    (OUT / name).write_text(json.dumps(nb, indent=1) + "\n")


# ---------------------------------------------------------------------
notebook("00_setup_check.ipynb", [
    md("""
# 0. Setup check

**What it does:** checks that everything the pipeline needs is in place before you run anything:
the Python packages, the SDH extraction folder, and the output folder. It reads nothing but file
names and row counts.

**Run:** once, whenever you start on a new machine or environment.
**Time:** seconds.
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Packages"),
    code('''import importlib
for pkg in ["pandas", "pyarrow", "spacy"]:
    try:
        m = importlib.import_module(pkg)
        print(f"{pkg:8s} OK  {getattr(m, '__version__', '')}")
    except ImportError:
        print(f"{pkg:8s} MISSING -> in a terminal: pip install {pkg}")
print("python  ", sys.version.split()[0], "|", sys.executable)'''),
    md("## Input: the GEMINI SDH extraction"),
    code('''import pyarrow.parquet as pq
print("Data folder:", cfg.DATA_DIR, "| exists:", cfg.DATA_DIR.exists())
for f in ["cohort.parquet", "encounters.parquet", "sdh_surgery_codes.csv"]:
    print(f"  {f:28s}", "found" if (cfg.DATA_DIR / f).exists() else "MISSING")
need = ["radiology", "ipdiagnosis", "erdiagnosis", "ipintervention", "erintervention", "lab", "vitals",
        "pharmacy", "ipscu", "erconsults", "derived_variables", "lookup_cci", "lookup_cihi_codes",
        "lookup_lab_concept", "lookup_vitals_concept"]
for t in need:
    p = cfg.DATA_DIR / "raw" / f"{t}.parquet"
    print(f"  raw/{t:24s}", f"{pq.ParquetFile(p).metadata.num_rows:>12,} rows" if p.exists() else "MISSING")'''),
    md("## Output folder"),
    code('''cfg.PATIENT_DIR.mkdir(parents=True, exist_ok=True)
cfg.AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)
print("Patient-level output (stays on GEMINI):", cfg.PATIENT_DIR)
print("Aggregate output (safe to share):      ", cfg.AGGREGATE_DIR)'''),
    md("**Look for:** every line says OK / found. If `spacy` is missing, install it before notebook 2."),
])

# ---------------------------------------------------------------------
notebook("01_episodes_and_ct_reports.ipynb", [
    md("""
# 1. Episodes of care, flags, and CT reports for the NLP

**What it does**
1. Takes every encounter in the extraction (adults with an SDH code in the ER or inpatient record).
2. Joins encounters of the same patient into one **episode of care** when GEMINI's `epicare` links them
   or the next admission starts within 12 h of the last discharge (a transfer).
3. **Flags** each episode instead of excluding it: SDH coded only in the ER, SDH that developed in
   hospital, elective admission, transferred in from outside GEMINI, no CT report, outside 2015-2024.
4. Collects **every head CT report** of every episode (not just the first: the NLP has to find the
   first CT that actually shows the SDH).

**Output** (`patient_level/`): `episodes.csv`, `episode_encounters.csv`, `ct_reports_for_nlp.csv`,
`ct_reports_index.csv`. Aggregate: `step1_counts.csv` and four check tables.

**Time:** a few minutes (reads the radiology table).
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Run"),
    code("%run ../01_episodes_and_ct_reports.py"),
    md("## Results"),
    code('show("step1_counts.csv", note="patients and episodes carrying each flag; the last row is how many reports the NLP will read")'),
    md("""
**Look for:** episodes vs patients (how many patients have more than one SDH episode); how many are
in-hospital onset and ER-only; the share with **no CT report** (about 28% expected).
"""),
    code('show("check_transfer_linking.csv", note="how transfers were joined")'),
    md("**Look for:** most joins found by *both* epicare and the 12 h rule. Many 'epicare only' joins would mean the 12 h window is too short; many 'time gap only' that it is too long."),
    code('show("check_arrival_source.csv", note="where patients came from (first encounter of the episode)")'),
    md("**Look for:** `from_acute_care_derived` = True is the transfer flag. `institution_from_filled` is also set for long-term care / rehab, so it is not used for the flag."),
    code('''cov = show("check_ct_coverage_by_hospital_year.csv", note="episodes with a CT report, per hospital and year")
if cov is not None:
    display(Markdown("**% of episodes with a CT report** (blank = small cell)"))
    display(cov.pivot_table(index=["hospital_num", "hospital_type"], columns="year", values="pct_with_ct_report"))
show("check_data_coverage_tables.csv", note="which data types GEMINI's coverage table lists")
show("check_ct_report_by_transfer.csv", note="CT report availability: transferred in vs not")'''),
    md("**Look for:** hospitals or years with low or no CT reports. `radiology_not_collected` counts episodes where GEMINI did not collect radiology at that hospital and date (a data gap, not a missing scan). Patients transferred in often had their first CT at the sending hospital."),
    code('show("check_ct_names.csv", rows=40, note="CT names counted as head CTs (excluded_name = True were left out)")'),
    md("**Look for:** head CTs wrongly excluded, or non-head scans (CTA, spine) wrongly included."),
    md("## Share"),
    code('share(["step1_counts.csv", "check_transfer_linking.csv", "check_arrival_source.csv", "check_data_coverage_tables.csv", "check_ct_report_by_transfer.csv", "check_ct_coverage_by_hospital_year.csv", "check_ct_names.csv"], rows=400)'),
])

# ---------------------------------------------------------------------
notebook("02_run_nlp.ipynb", [
    md("""
# 2. Run the NLP on every head CT report

**What it does:** runs a fixed snapshot of the SDH NLP (`phenotype/nlp/NLP_v5_snapshot.ipynb`, see
`nlp/SNAPSHOT.md`) on every report from notebook 1, exactly as `NLP_v5.ipynb` processes a report
(tokenize, bleed tree, variable mapping). It is the pre-validation version, used to set up the
pipeline; when the validated NLP is ready, swap the snapshot and rerun from here.

A CT counts as **showing an SDH** when the NLP gives a laterality of Left / Right / Bilateral,
or any falx (parafalcine) or tentorium hematoma.

**Output:** `patient_level/ct_reports_nlp_results.csv` (report id, episode, every NLP variable,
error; no report text).

**Time:** test run about a minute; full run (~46,000 reports) roughly 30-60 minutes. Progress is
saved as it goes: if it stops, run the same cell again and it continues where it left off.
For the full run you can also use a terminal inside `tmux` (see the last cell).
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Test run (first 200 reports)"),
    code('''TEST_OUT = cfg.PATIENT_DIR / "nlp_test_200.csv"
!{sys.executable} ../nlp/run_nlp.py --limit 200 --workers 2 --output "{TEST_OUT}"'''),
    code('''def nlp_summary(path):
    r = pd.read_csv(path, dtype=str, keep_default_na=False)
    lat = r.laterality.str.strip()
    comp = pd.Series(False, index=r.index)
    for c in cfg.NLP_SDH_COMPARTMENTS:
        comp |= ~r[c].str.strip().isin(cfg.NLP_ABSENT_VALUES)
    sdh = lat.isin(cfg.NLP_SDH_LATERALITY) | comp
    print(f"reports: {len(r)} | errors: {(r.error != '').sum()} | show an SDH: {sdh.sum()} ({100 * sdh.mean():.1f}%)")
    print(f"  SDH found only through a falx / tentorium hematoma: {(sdh & ~lat.isin(cfg.NLP_SDH_LATERALITY)).sum()}")
    display(lat.value_counts().rename("reports").to_frame().map(io.suppress))
    return r

test = nlp_summary(TEST_OUT)'''),
    md("""
**Look for:** errors close to 0; a sensible share showing an SDH (follow-up and unrelated head CTs
will often be negative). If something looks off, stop here and send me the summary.
"""),
    md("## Full run"),
    code("!{sys.executable} ../nlp/run_nlp.py --workers 4"),
    code('''full = nlp_summary(cfg.NLP_RESULTS_FILE)
for c in ["L_acuity", "R_acuity", "midline_shift_present", "mass_effect_present"]:
    if c in full:
        display(full[c].value_counts().rename(f"{c}: reports").to_frame().map(io.suppress))'''),
    md("""
## Share
The cells above print counts only. Paste their output (not the CSV) to Claude.

**Terminal alternative for the full run** (keeps going if the browser closes):
```bash
tmux new -s nlp
srun -p cpu --qos=depri --mem=32G --cpus-per-task=4 --pty bash -i
source ~/.venvs/sdh-gemini/bin/activate && cd ~/SDH_NLP
python phenotype/nlp/run_nlp.py --workers 4
```
"""),
])

# ---------------------------------------------------------------------
notebook("03_cohort_key.ipynb", [
    md("""
# 3. Cohort key: confirm the SDH, set time zero, pick the index episode

**What it does**
- **Confirms the SDH on imaging:** an episode is confirmed when any of its CTs shows an SDH (NLP).
- **Index CT:** the first CT showing the SDH (its NLP features become the CT variables in the baseline).
- **Time zero:** ER triage at the first hospital (or admission) for patients who came in with the SDH;
  the first CT showing it for SDH that **developed in hospital**.
- **Index episode:** each patient's first confirmed episode (or their first episode, flagged, if none is).
- Gives every patient a study ID, `row_id` (SDH00001 ...), the key that links all later files.

If the NLP has not been run, it still works (every CT counts as showing the SDH) and says so.

**Output:** `patient_level/cohort_key.csv` (one row per patient); aggregate `step2_counts.csv`.
**Time:** under a minute.
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Run"),
    code("%run ../02_cohort_key.py"),
    md("## Results"),
    code('show("step2_counts.csv")'),
    md("""
**Look for:**
- `index episode: first confirmed episode` should be most patients; the *none confirmed* group is
  mostly patients with no CT report or whose CTs never showed an SDH.
- `time zero from`: mostly `er_triage`; `diagnosis_ct` = in-hospital onset; `missing (no CT)` =
  in-hospital onset without a CT report (they cannot get a time zero).
"""),
    code('''# timing summaries (aggregate only)
k = io.read_patient_level("cohort_key.csv")
def q(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return pd.Series({"patients": io.suppress(len(s)), "median": round(s.median(), 1),
                      "IQR": f"{s.quantile(.25):.1f} to {s.quantile(.75):.1f}"}) if len(s) >= cfg.SMALL_CELL else None
display(pd.DataFrame({
    "hours: time zero -> index CT": q(k.hours_t0_to_index_ct),
    "hours: admission -> SDH diagnosis (in-hospital onset)": q(k.hours_admission_to_sdh_diagnosis),
}).T)'''),
    md("**Look for:** index CT usually within a few hours of arrival; in-hospital onset typically days after admission."),
    md("## Share"),
    code('share(["step2_counts.csv"])'),
])

# ---------------------------------------------------------------------
notebook("04_baseline.ipynb", [
    md("""
# 4. Baseline dataset: what was known at time zero

**What it does:** builds one row per patient with everything known at presentation, in three groups
(`baseline_dictionary.csv` lists every variable and its group):

| Group | Contents | Used for |
|---|---|---|
| **A clustering inputs** | CT features from the NLP, vitals, labs, age, sex, comorbidities and Charlson, anticoagulation evidence, mechanism, other injuries, presenting symptoms, CTAS, mLAPS | defining phenotypes |
| **B equity** | neighbourhood marginalization (Ontario Marginalization Index), rurality | does the same phenotype get the same care? |
| **C care context** | hospital, teaching / non-teaching, year, flags, when each value was measured | adjustment |

Labs and vitals are the **value closest to time zero** (labs 24 h before to 12 h after; vitals
6 h either side), taken from the raw lab / vitals tables using GEMINI's standard concepts first.
Comorbidities ignore type-2 (in-hospital) diagnoses. Medications: orders from the start of the
episode to 24 h after time zero.

**Output:** `patient_level/baseline.csv`; aggregate `baseline_dictionary.csv` and three check tables.
**Time:** several minutes (reads the 11-million-row lab table and the vitals table in batches).
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Run"),
    code("%run ../03_baseline.py"),
    md("## Results"),
    code('''d = show("baseline_dictionary.csv", rows=10, note="every baseline variable with its group")
if d is not None:
    display(d.group.value_counts().rename("variables").to_frame())'''),
    code('show("check_lab_vital_timing.csv", note="coverage of each lab and vital")'),
    md("""
**Look for:** `pct_patients` = share of patients who have that value. **GCS** decides whether GCS can
be a clustering input. A large `outside_window` count means values exist but were measured too long
after arrival; many `implausible` values usually mean a unit problem.
"""),
    code('''names = show("check_lab_vital_names.csv", rows=0)
if names is not None:
    for v, g in names.groupby("variable"):
        display(Markdown(f"**{v}**")); display(g.head(8))'''),
    md("**Look for:** each variable built from the right test (e.g. platelets not 'mean platelet volume') and consistent units."),
    code('show("check_med_names.csv", rows=60, note="drug names matched to each medication group")'),
    md("**Look for:** wrong drugs in a group (e.g. heparin flush under anticoagulants)."),
    md("## Share"),
    code('share(["baseline_dictionary.csv", "check_lab_vital_timing.csv", "check_lab_vital_names.csv", "check_med_names.csv"])'),
])

# ---------------------------------------------------------------------
notebook("05_outcomes.ipynb", [
    md("""
# 5. Outcome dataset: what happened after time zero

**What it does:** one row per patient with treatment, care process and outcomes, all timed from
time zero (never used for clustering):

- **Surgery:** first SDH operation (burr hole, craniotomy, twist drill, membrane excision ...), its
  code, hours from time zero, hospital; repeat operation. Operations *before* time zero (e.g. the
  brain surgery an in-hospital SDH followed) are ignored.
- **Other procedures:** MMA embolization, embolization that is probably aneurysm treatment, EVD,
  ventilation, craniectomy.
- **Care process:** ICU (hours from time zero), ER neurosurgery consult, palliative care code.
- **Pathway:** surgery < 24 h, surgery >= 24 h, MMA embolization only, no surgery with palliative care, no surgery.
- **Outcomes:** in-hospital death, death within 48 h, length of stay (from time zero; survivors only
  as well), discharge category, favourable discharge, 30-day readmission, SDH readmission within
  90 days, days alive and out of hospital to day 30.

**Output:** `patient_level/outcomes.csv`; aggregate check tables.
**Time:** a few minutes.
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Run"),
    code("%run ../04_outcomes.py"),
    md("## Results"),
    code('show("check_intervention_codes.csv", rows=60, note="every CCI code in the surgery families and the group it was given")'),
    md("""
**Look for (ideally with a neurosurgeon):** each code in the right group; `1JW51` embolizations with
an aneurysm code are labelled *probable aneurysm*; codes with no group that should have one.
`with_time` = how many have a real time (not 00:00).
"""),
    code('show("check_discharge_disposition.csv", note="CIHI discharge codes and the category given")'),
    md("**Look for:** every code mapped to a sensible category (home, long-term care, died ...)."),
    code('show("check_surgery_hospitals.csv", note="SDH operations per hospital; >= 20 = neurosurgical centre")'),
    code('''o = io.read_patient_level("outcomes.csv")
summary = {}
for c in ["pathway", "first_surgery_type", "discharge_category"]:
    summary[c] = o[c].fillna("(none)").value_counts()
for c, s in summary.items():
    display(s.rename(f"{c}: patients").to_frame().map(io.suppress))
flags = ["cranial_surgery", "mma_embolization", "icu_admission", "er_neurosurgery_consult",
         "palliative_care_coded", "died_in_hospital", "died_within_48h", "favourable_discharge"]
tf = pd.DataFrame({c: [io.suppress(int(o[c].astype(str).str.lower().eq("true").sum()))] for c in flags if c in o},
                  index=["patients"]).T
display(tf)'''),
    md("## Share"),
    code('share(["check_intervention_codes.csv", "check_discharge_disposition.csv", "check_surgery_hospitals.csv"])'),
])

# ---------------------------------------------------------------------
notebook("06_tables_and_checks.ipynb", [
    md("""
# 6. Descriptive tables and data coverage

**What it does:** joins the cohort key, baseline and outcomes on `row_id` into one file
(`patient_level/analysis_dataset.csv`) and makes the shareable tables:

- **Table 1** by SDH type (overall / traumatic / non-traumatic code)
- **Table 2** by treatment pathway
- **Coverage** of key variables per hospital and per year

Counts under 6 are shown as `<6`, and percentages that would reveal them are blanked.

**Time:** under a minute.
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Run"),
    code("%run ../05_tables_and_checks.py"),
    md("## Results"),
    code('show("table1_by_stratum.csv")'),
    md("**Look for:** plausible distributions (age, sex, mortality, surgery rates) and anything unexpected between traumatic and non-traumatic."),
    code('show("table2_by_pathway.csv")'),
    code('show("coverage_by_hospital.csv", note="% of patients with each key variable, per hospital")'),
    code('show("coverage_by_year.csv", note="% of patients with each key variable, per year")'),
    md("**Look for:** hospitals or years where a variable is (nearly) absent - a data gap rather than a clinical difference."),
    md("## Share"),
    code('share(["table1_by_stratum.csv", "table2_by_pathway.csv", "coverage_by_hospital.csv", "coverage_by_year.csv"], rows=400)'),
])

# ---------------------------------------------------------------------
notebook("07_clustering_dataset.ipynb", [
    md("""
# 7. The clustering dataset, with every patient accounted for

**What it does**
1. Applies the inclusion rules in `CLUSTER_RULES` (in `sdh_config.py`) one at a time and counts who
   each one removes: has a CT report, SDH confirmed on CT, in the study period (+ optional: no
   elective, no ER-only code, no in-hospital onset).
2. Keeps the clustering inputs (group A).
3. Reports **missing data** per variable (overall and in-hospital onset separately), per hospital and
   per patient. **Nobody is dropped for missing labs or vitals:** a variable missing in more than
   40% of patients is set aside, and patients missing more than 50% are flagged (both thresholds
   are settings).

**Output:** `patient_level/clustering_dataset.csv` (join `outcomes.csv` on `row_id` for the outcome
analyses); aggregate flowchart and missing-data tables.
**Time:** seconds.
"""),
    md(PRIVACY),
    code(SETUP),
    md("## Settings in use"),
    code('''print("Inclusion rules:", cfg.CLUSTER_RULES)
print("Set aside variables missing in more than", cfg.MAX_VARIABLE_MISSING_PCT, "%")
print("Flag patients missing more than", cfg.MAX_PATIENT_MISSING_PCT, "% | drop them:", cfg.DROP_HIGH_MISSING_PATIENTS)'''),
    md("To change a rule, edit `sdh_config.py`, then restart the kernel (Kernel -> Restart) and rerun."),
    md("## Run"),
    code("%run ../06_clustering_dataset.py"),
    md("## Results"),
    code('show("clustering_flowchart.csv", note="the flowchart for the paper")'),
    code('show("clustering_missingness_by_variable.csv", note="sorted from most to least missing")'),
    md("""
**Look for:** which variables are set aside (`used_for_clustering = False`); CTAS / mLAPS are blank for
in-hospital onset by design (see the split columns).
"""),
    code('show("clustering_patient_missingness.csv")'),
    code('show("clustering_missingness_by_hospital.csv")'),
    md("**Look for:** a hospital missing a whole variable (data not sent) rather than scattered gaps."),
    md("## Share"),
    code('share(["clustering_flowchart.csv", "clustering_missingness_by_variable.csv", "clustering_patient_missingness.csv", "clustering_missingness_by_hospital.csv"])'),
])
print("notebooks written to", OUT)
