"""
Code lists. ICD-10-CA codes are written without the dot (I620, S0650) and
match by prefix: "I50" matches I500, I501, I509 ...

CCI intervention groups and the discharge disposition map are marked
VERIFY: check them against check_intervention_codes.csv and
check_discharge_disposition.csv before analysis.
"""
import re


def rng(letter, start, end):
    """rng("C", 0, 26) -> C00 ... C26 (prefixes)."""
    return [f"{letter}{i:02d}" for i in range(start, end + 1)]


def sub(code, start, end):
    """sub("I42", 5, 9) -> I425 ... I429."""
    return [f"{code}{i}" for i in range(start, end + 1)]


def has_prefix(codes, prefixes):
    """True if any code in `codes` starts with any prefix."""
    prefixes = tuple(prefixes)
    return any(str(c).startswith(prefixes) for c in codes if c is not None)


# ---------------------------------------------------------------------
# Charlson comorbidity (Quan et al. 2005 ICD-10 coding, Charlson weights)
# ---------------------------------------------------------------------
_DM = ["E10", "E11", "E12", "E13", "E14"]
CHARLSON = {
    # name: (weight, prefixes)
    "mi": (1, ["I21", "I22", "I252"]),
    "chf": (1, ["I099", "I110", "I130", "I132", "I255", "I420", *sub("I42", 5, 9), "I43",
                "I50", "P290"]),
    "pvd": (1, ["I70", "I71", "I731", "I738", "I739", "I771", "I790", "I792", "K551",
                "K558", "K559", "Z958", "Z959"]),
    # I60-I62 are left out at the index episode (they are the SDH and its
    # neighbours); see CHARLSON_INDEX_EXCLUDE
    "cvd": (1, ["G45", "G46", "H340", *rng("I", 60, 69)]),
    "dementia": (1, ["F00", "F01", "F02", "F03", "F051", "G30", "G311"]),
    "copd": (1, ["I278", "I279", *rng("J", 40, 47), *rng("J", 60, 67), "J684", "J701",
                 "J703"]),
    "rheum": (1, ["M05", "M06", "M315", "M32", "M33", "M34", "M351", "M353", "M360"]),
    "pud": (1, ["K25", "K26", "K27", "K28"]),
    "liver_mild": (1, ["B18", *sub("K70", 0, 3), "K709", *sub("K71", 3, 5), "K717", "K73",
                       "K74", "K760", *sub("K76", 2, 4), "K768", "K769", "Z944"]),
    "dm_uncomplicated": (1, [f"{d}{s}" for d in _DM for s in ("0", "1", "6", "8", "9")]),
    "dm_complicated": (2, [f"{d}{s}" for d in _DM for s in ("2", "3", "4", "5", "7")]),
    # at the index episode only pre-admit (type 1) hemiplegia counts: a new
    # hemiparesis is a symptom of the SDH, not a comorbidity
    "hemiplegia": (2, ["G041", "G114", "G801", "G802", "G81", "G82", *sub("G83", 0, 4),
                       "G839"]),
    "renal": (2, ["I120", "I131", *sub("N03", 2, 7), *sub("N05", 2, 7), "N18", "N19",
                  "N250", *sub("Z49", 0, 2), "Z940", "Z992"]),
    "cancer": (2, [*rng("C", 0, 26), *rng("C", 30, 34), *rng("C", 37, 41), "C43",
                   *rng("C", 45, 58), *rng("C", 60, 76), *rng("C", 81, 85), "C88",
                   *rng("C", 90, 97)]),
    "liver_severe": (3, ["I850", "I859", "I864", "I982", "K704", "K711", "K721", "K729",
                         "K765", "K766", "K767"]),
    "metastatic": (6, ["C77", "C78", "C79", "C80"]),
    "hiv": (6, ["B20", "B21", "B22", "B24"]),
}
# when both are present only the more severe one is scored
CHARLSON_HIERARCHY = [("liver_mild", "liver_severe"), ("dm_uncomplicated", "dm_complicated"),
                      ("cancer", "metastatic")]
CHARLSON_INDEX_EXCLUDE = ("I60", "I61", "I62", "S06")

# ---------------------------------------------------------------------
# Comorbidities that matter for SDH beyond Charlson
# ---------------------------------------------------------------------
SDH_COMORBIDITIES = {
    "atrial_fibrillation": ["I48"],
    "hypertension": rng("I", 10, 15),
    "vte_history": ["I26", "I80", "I81", "I82", "Z867"],
    "mechanical_valve": ["Z952", "Z953", "Z954"],
    "alcohol_use": ["F10", "E244", "G312", "G621", "G721", "I426", "K292", "K70", "K860",
                    "Z502", "Z714", "T51"],
    "epilepsy": ["G40", "G41"],
    "parkinsonism": ["G20", "G21", "G22"],
    "coagulopathy": ["D65", "D66", "D67", "D68", "D69"],
    "thrombocytopenia": ["D695", "D696"],
    "csf_shunt": ["Z982"],
    "falls_history": ["Z9181"],          # VERIFY: may not exist in ICD-10-CA
    "homelessness": ["Z590"],
}

# Evidence the patient was on an anticoagulant (codes; see also labs/meds)
ANTICOAGULANT_CODES = ["Z921", "D683", "Y442"]   # VERIFY D683x subcodes in ICD-10-CA
ANTIPLATELET_CODES = ["Z9282"]                    # VERIFY: may not exist in ICD-10-CA

# ---------------------------------------------------------------------
# Presentation: mechanism, concurrent injuries, symptoms
# ---------------------------------------------------------------------
MECHANISM = {   # checked in this order; the first match wins
    "transport": rng("V", 1, 99),
    "assault": [*rng("X", 85, 99), *rng("Y", 0, 9)],
    "fall_same_level": ["W01", "W03", "W18"],
    "fall_from_height": rng("W", 4, 17),
    "fall_unspecified": ["W00", "W02", "W19"],
    "struck_by": ["W20", "W21", "W22", "W50", "W51"],
    "other_external_cause": ["W", "X", "Y"],
}

CONCURRENT_INJURY = {
    "other_intracranial_injury": ["S060", "S061", "S062", "S063", "S064", "S066", "S067",
                                  "S068", "S069"],
    "traumatic_sah": ["S066"],
    "epidural_hematoma": ["S064"],
    "contusion_ich": ["S063"],
    "skull_fracture": ["S020", "S021", "S027"],
    "facial_fracture": ["S022", "S023", "S024", "S025", "S026", "S028", "S029"],
    "cervical_spine_injury": ["S12", "S13", "S14"],
    "hip_fracture": ["S72"],
    "rib_fracture": ["S222", "S223", "S224"],
    "nontraumatic_sah": ["I60"],
    "nontraumatic_ich": ["I61"],
}

SYMPTOM_CODES = {
    "decreased_consciousness": ["R40"],
    "seizure": ["R56", "G40", "G41"],
    "headache": ["R51", "G44"],
    "confusion_delirium": ["R410", "F05"],
    "speech_disturbance": ["R47"],
    "hemiparesis": ["G81", "G83"],
    "syncope": ["R55"],
    "gait_abnormality": ["R26", "R2681"],
    "nausea_vomiting": ["R11"],
    "dizziness": ["R42"],
}

# ER chief complaint text (lower case regex)
COMPLAINT_KEYWORDS = {
    "complaint_fall": r"\bfall|\bfell\b|found down",
    "complaint_head_injury": r"head (inj|trauma)|hit (his|her|their)? ?head|\bhi\b",
    "complaint_headache": r"headache|\bh/?a\b",
    "complaint_confusion": r"confus|altered|deliri|disorient|\bloc\b|decreased level|"
                           r"unresponsive|letharg|drows",
    "complaint_weakness": r"weak|hemipar|numb|stroke|facial droop|\bcva\b",
    "complaint_seizure": r"seiz|convuls",
    "complaint_speech": r"speech|aphasi|dysphasi|slurr",
    "complaint_mvc": r"\bmvc\b|\bmva\b|motor vehicle|collision|pedestrian|cyclist|bike",
}

PALLIATIVE_CODES = ["Z515"]

# ---------------------------------------------------------------------
# Interventions (CCI). The extraction's sdh_surgery_codes.csv gives
# burr_hole / craniotomy / twist_drill / embolization; these add families it
# leaves out. VERIFY every group with check_intervention_codes.csv.
# ---------------------------------------------------------------------
NOT_SDH_SURGERY = {"1AA52MESJ"}      # subdural-peritoneal shunt, not a craniotomy
EXTRA_INTERVENTION_GROUPS = {
    "membrane_excision": ["1AA87"],          # excision, meninges / dura (membranectomy)
    "brain_hematoma_drainage": ["1AN52"],    # drainage, brain (intracerebral hematoma)
    "decompressive_craniectomy": ["1EA80", "1EA87"],   # VERIFY
    "other_meningeal_drainage": ["1AA52"],   # 1AA52 codes not in the extraction's list
    "ventricular_drain": ["1AJ52"],          # EVD; VERIFY
    "mechanical_ventilation": ["1GZ31"],
}
CRANIAL_SURGERY_GROUPS = ["burr_hole", "craniotomy", "twist_drill", "membrane_excision",
                          "brain_hematoma_drainage", "decompressive_craniectomy", "other_meningeal_drainage"]
INTERVENTION_CHECK_FAMILIES = ["1AA", "1AN", "1AJ", "1EA", "1JW", "1JX", "1JE"]
# an embolization in an episode with one of these is probably aneurysm treatment
ANEURYSM_CODES = ["I60", "I671", "Q282", "Q283"]

# ---------------------------------------------------------------------
# Labs and vitals (matched on the raw test / measurement name, lower case)
# ---------------------------------------------------------------------
# name: (include regex, exclude regex, plausible min, plausible max)
LABS = {
    "inr": (r"\binr\b|international normali", r"", 0.5, 15),
    "ptt": (r"\bptt\b|aptt|partial thromboplastin", r"ratio", 10, 200),
    "platelets": (r"platelet|\bplt\b", r"function|antibod|mean|volume|\bmpv\b|aggreg", 1, 2000),
    "hemoglobin": (r"h(a)?emoglobin|\bhgb\b|\bhb\b", r"a1c|glyc|urine|plasma free|carboxy|"
                   r"met|fetal|electro|\bmch", 30, 250),
    "wbc": (r"\bwbc\b|white blood|leukocyte", r"urine|esterase|csf|fluid", 0.1, 200),
    "sodium": (r"\bsodium\b|^na\b|\bna\+", r"urine|fluid|excret", 100, 180),
    "creatinine": (r"creatinine", r"urine|clearance|ratio|fluid|kinase", 10, 2500),
    "glucose": (r"glucose", r"urine|csf|fluid|tolerance|meter|poc", 0.5, 60),
    "fibrinogen": (r"fibrinogen", r"", 0.1, 15),
    "lactate": (r"lactate|lactic", r"dehydrog|\bldh\b|csf", 0.1, 30),
}

VITALS = {
    "sbp": (r"systolic|\bsbp\b|blood pressure|\bbp\b|\bnibp\b|\babp\b", r"diastolic|mean|\bmap\b", 40, 300),
    "dbp": (r"diastolic|\bdbp\b", r"", 20, 200),
    "heart_rate": (r"heart rate|pulse|\bhr\b", r"oximetry|ox\b|spo2", 20, 250),
    "resp_rate": (r"resp", r"", 4, 70),
    "temperature": (r"temp", r"", 30, 44),
    "spo2": (r"spo2|o2 sat|oxygen sat|oximetry", r"", 50, 100),
    "gcs": (r"glasgow|\bgcs\b", r"eye|verbal|motor", 3, 15),
}

# GEMINI's standard concepts (lookup_lab_concept / lookup_vitals_concept
# descriptions) are matched first; LABS / VITALS above are the fallback for
# rows without a concept. name: (include, exclude) on the lower-case description
LAB_CONCEPTS = {
    "inr": (r"\binr\b|international normali", r""),
    "pt": (r"prothrombin time", r"inr|ratio|international"),
    "ptt": (r"aptt|partial thromboplastin", r"ratio"),
    "platelets": (r"^platelets?\b", r"mean|aggreg|antibod|function|distribution|large|immature"),
    "hemoglobin": (r"^h(a)?emoglobin \[mass/volume\]", r"a1c|plasma|urine|carboxy|met|fetal|fraction"),
    "wbc": (r"^leukocytes \[#/volume\]", r"urine|fluid|csf"),
    "sodium": (r"^sodium", r"urine|fluid"),
    "creatinine": (r"^creatinine \[", r"urine|clearance|ratio|fluid"),
    "glucose": (r"^glucose", r"urine|csf|fluid|tolerance|post|challenge"),
    "fibrinogen": (r"fibrinogen", r"degradation|antigen"),
    "lactate": (r"^lactate", r"dehydrog|csf"),
}
LABS["pt"] = (r"\bpt\b|prothrombin time", r"inr|ratio|ptt", 5, 150)
VITAL_CONCEPTS = {
    "sbp": r"^systolic blood pressure",
    "dbp": r"^diastolic blood pressure",
    "bp_combined": r"^blood pressure$|^blood pressure panel",   # '150/90' -> sbp and dbp
    "heart_rate": r"^heart rate",
    "resp_rate": r"^respiratory rate",
    "spo2": r"^oxygen saturation",
    "temperature": r"^body temperature",
}

# ---------------------------------------------------------------------
# Medications and blood products (matched on drug / product name)
# ---------------------------------------------------------------------
MEDS = {
    "anticoagulant_doac": r"apixaban|eliquis|rivaroxaban|xarelto|dabigatran|pradaxa|edoxaban|lixiana|savaysa",
    "anticoagulant_warfarin": r"warfarin|coumadin",
    "antiplatelet": r"clopidogrel|plavix|ticagrelor|brilinta|prasugrel|effient|\basa\b|"
                    r"aspirin|acetylsalicylic|dipyridamole|aggrenox",
    "reversal_pcc": r"octaplex|beriplex|prothrombin complex|\bpcc\b|kcentra",
    "reversal_vitamin_k": r"phytonadione|phytomenadione|vitamin k\b",
    "reversal_idarucizumab": r"idarucizumab|praxbind",
    "reversal_andexanet": r"andexanet|andexxa|ondexxya",
    "desmopressin": r"desmopressin|ddavp",
    "tranexamic_acid": r"tranexamic|cyklokapron",
    "antiseizure": r"levetiracetam|keppra|phenytoin|dilantin|lacosamide|vimpat|valpro|"
                   r"brivaracetam|fosphenytoin",
    "hyperosmolar": r"mannitol|hypertonic|sodium chloride 3%|nacl 3|23\.4%",
    "dexamethasone": r"dexamethasone|decadron",
}
BLOOD_PRODUCTS = {
    "platelet_transfusion": r"platelet|\bplt\b",
    "plasma_transfusion": r"plasma|\bfp\b|\bffp\b",
    "pcc_blood_bank": r"octaplex|beriplex|prothrombin complex|\bpcc\b",
    "rbc_transfusion": r"red (blood )?cell|\brbc\b|prbc|packed",
}

# ---------------------------------------------------------------------
# Discharge disposition: mapped from lookup_cihi_codes descriptions
# (checked in check_discharge_disposition.csv)
# ---------------------------------------------------------------------
FAVOURABLE_DISPOSITIONS = {"home", "home_with_support"}
_DISPOSITION_RULES = [   # first match wins (lower-case description)
    ("died", r"died|death|expired|deceased|maid|medical assistance in dying|suicide|cadaver"),
    ("left_against_advice", r"against|did not return|left|absent|elop"),
    ("home_with_support", r"home.*support|support.*home|home care|homecare"),
    ("home", r"home|residence|private"),
    ("rehabilitation", r"rehab"),
    ("long_term_care", r"long.?term|residential|nursing|continuing|chronic|group|supportive living"),
    ("transfer_acute", r"acute|inpatient|emergency|ambulatory|hospital"),
    ("other_facility", r"."),
]


def disposition_category(description):
    d = str(description or "").lower()
    if not d:
        return None
    return next(cat for cat, pattern in _DISPOSITION_RULES if re.search(pattern, d))


def charlson_score(flags):
    """Charlson score from a dict of booleans keyed like CHARLSON."""
    flags = dict(flags)
    for mild, severe in CHARLSON_HIERARCHY:
        if flags.get(severe):
            flags[mild] = False
    return sum(w for name, (w, _) in CHARLSON.items() if flags.get(name))


def normalise_code(code):
    """'I62.0 ' -> 'I620'."""
    return re.sub(r"[^A-Z0-9]", "", str(code).upper()) if code is not None else None
