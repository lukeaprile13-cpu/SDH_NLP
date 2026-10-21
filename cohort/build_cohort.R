# =====================================================================
# SDH validation cohort
#
# Builds the sampling frame for the NLP / LLM validation: one row per
# patient = the first head CT of their first SDH encounter, with the
# report, hospital, age, sex, diagnoses and ER presenting complaint.
# Two strata, each in a fixed random screening order:
#
#   traumatic       S065   (an encounter with any S065 code)
#   nontraumatic    I620   (I620 and no S065)
#
# Uses the same tables and connection as the SDH viewer code (db, datacut).
# The output holds report text: keep it on the GEMINI server.
# =====================================================================

library(DBI)
library(dplyr)
library(stringr)
library(lubridate)


# ---------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------

MIN_AGE <- 18            # set to 60 if the study population is 60+

# DAD diagnosis types that count as an SDH present on arrival.
# "2" (post-admit comorbidity) = an SDH that developed in hospital: left out.
# c("M") = SDH must be the most responsible diagnosis (narrower; see notes).
SDH_TYPES_KEEP <- c("M", "1", "3", "W", "X", "Y", "6")

# the index CT: performed from this long before admission to this long after
# (the ER CT is usually before the admit time)
CT_WINDOW_BEFORE_H <- 48
CT_WINDOW_AFTER_H  <- 72

# not the index non-contrast head CT
CT_NAME_EXCLUDE <- "angio|cta\\b|perfusion|venogra|spine|neck|facial|sinus|orbit|temporal bone|stereotac|navigation"

# reports used to build the NLP can never be sampled. Either list their
# encounters (a csv with a genc_id column) or give the files that hold
# their text (csv or xlsx; the report column is found automatically) -
# a cohort report whose text matches one of them is removed
DEVELOPMENT_IDS_FILE <- "development_genc_ids.csv"
# fingerprints of every report used in development (column "key": three
# 120-letter stretches per report, letters only) - made from all the
# reports shared while building the NLP
DEVELOPMENT_FINGERPRINTS_FILE <- "development_fingerprints.csv"
DEVELOPMENT_REPORT_FILES <- c(
  # "Reports.CSV.xlsx",                    # first 50
  # "report_final_5.csv",                  # batch 9
  # "new13_reports.csv",
  # "FINAL_BLANK_SHEET - Copy.csv",        # DEV15
  # "val.csv",                             # VAL20
  # "more_reports_1.xlsx", "more_reports_2.xlsx", "more_reports_3.xlsx",
  # "Claude_test_before_validation.xlsx",  # the latest version (holds all 27)
  # "LLM_Comparison.xlsx"
)

SEED <- 20261021
OUTPUT_FILE <- "sdh_validation_cohort.csv"


# ---------------------------------------------------------------------
# 1. SDH encounters
# ---------------------------------------------------------------------

dbGetQuery(db, paste0("SET search_path TO '", datacut, "', public;"))

sdh_ids <- dbGetQuery(db, "
  SELECT DISTINCT genc_id
  FROM ipdiagnosis_subset
  WHERE diagnosis_code LIKE 'I620%' OR diagnosis_code LIKE 'S065%'
")
cat("SDH encounters (any diagnosis type):", nrow(sdh_ids), "\n")

tryCatch({ rs <- dbSendQuery(db, "DROP TABLE IF EXISTS temp_sdh"); dbClearResult(rs) }, error = function(e) NULL)
DBI::dbWriteTable(db, c("pg_temp", "temp_sdh"), sdh_ids, row.names = FALSE, overwrite = TRUE)

admdad <- dbGetQuery(db, "SELECT a.* FROM admdad_subset a INNER JOIN temp_sdh t ON a.genc_id = t.genc_id")
ipdiag <- dbGetQuery(db, "SELECT d.genc_id, d.diagnosis_code, d.diagnosis_type FROM ipdiagnosis_subset d INNER JOIN temp_sdh t ON d.genc_id = t.genc_id")
ct_reports <- dbGetQuery(db, "
  SELECT r.genc_id, r.imaging_result, r.test_name_raw, r.performed_date_time
  FROM radiology_subset r
  INNER JOIN temp_sdh t ON r.genc_id = t.genc_id
  WHERE r.modality_mapped = 'CT'
    AND (LOWER(r.test_name_raw) LIKE '%head%' OR LOWER(r.test_name_raw) LIKE '%brain%')
")

# ER presenting complaint and ER diagnoses, when the tables exist
# (column names are found by pattern, so they do not need to be exact)
er <- tryCatch(
  dbGetQuery(db, "SELECT e.* FROM er_subset e INNER JOIN temp_sdh t ON e.genc_id = t.genc_id"),
  error = function(e) NULL
)
erdiag <- tryCatch(
  dbGetQuery(db, "SELECT e.* FROM erdiagnosis_subset e INNER JOIN temp_sdh t ON e.genc_id = t.genc_id"),
  error = function(e) NULL
)
cat("admdad:", nrow(admdad), " ipdiagnosis:", nrow(ipdiag), " head CTs:", nrow(ct_reports),
    " er:", if (is.null(er)) "not found" else nrow(er),
    " erdiagnosis:", if (is.null(erdiag)) "not found" else nrow(erdiag), "\n")


# ---------------------------------------------------------------------
# 2. Diagnoses per encounter: stratum, SDH coding, main and other codes
# ---------------------------------------------------------------------

is_sdh <- function(code) grepl("^I620|^S065", code)

sdh_info <- ipdiag %>%
  filter(is_sdh(diagnosis_code)) %>%
  group_by(genc_id) %>%
  summarise(
    sdh_codes = paste(unique(diagnosis_code), collapse = "; "),
    sdh_types = paste(unique(diagnosis_type), collapse = "; "),
    sdh_present_on_arrival = any(diagnosis_type %in% SDH_TYPES_KEEP),
    sdh_is_primary = any(diagnosis_type == "M"),
    has_traumatic = any(grepl("^S065", diagnosis_code)),
    has_nontraumatic = any(grepl("^I620", diagnosis_code)),
    .groups = "drop"
  ) %>%
  mutate(stratum = if_else(has_traumatic, "traumatic", "nontraumatic"))

main_diag <- ipdiag %>%
  filter(diagnosis_type == "M") %>%
  group_by(genc_id) %>%
  summarise(main_diagnosis = paste(diagnosis_code, collapse = "; "), .groups = "drop")

other_dx <- ipdiag %>%
  filter(!is_sdh(diagnosis_code)) %>%
  group_by(genc_id) %>%
  summarise(other_codes = paste(paste0(diagnosis_code, "(", diagnosis_type, ")"), collapse = "; "),
            .groups = "drop")

er_info <- NULL
if (!is.null(er)) {
  complaint_cols <- grep("complaint", names(er), value = TRUE)
  er_info <- er %>%
    select(genc_id, any_of(complaint_cols)) %>%
    group_by(genc_id) %>%
    summarise(across(everything(), ~ paste(unique(na.omit(as.character(.x))), collapse = "; ")),
              .groups = "drop")
}

er_dx_info <- NULL
if (!is.null(erdiag)) {
  code_col <- grep("diagnosis_code", names(erdiag), value = TRUE)[1]
  er_dx_info <- erdiag %>%
    group_by(genc_id) %>%
    summarise(er_diagnosis_codes = paste(unique(.data[[code_col]]), collapse = "; "), .groups = "drop")
}


# ---------------------------------------------------------------------
# 3. Encounters that qualify, and their first head CT
# ---------------------------------------------------------------------

# date-times may arrive as text or already as date-times
as_dt <- function(x) if (inherits(x, "POSIXt")) x else ymd_hms(as.character(x), truncated = 3, quiet = TRUE)

# the admission / discharge time columns go by different names between
# data cuts (admission_date_time, admit_date_time, ...): take what is there
pick_col <- function(pattern) grep(pattern, names(admdad), value = TRUE)[1]
admit_col <- pick_col("^admi(t|ssion).*date.*time$|^admi(t|ssion)_date")
discharge_col <- pick_col("^discharge.*date.*time$|^discharge_date")
cat("admission time column:", admit_col, " discharge time column:", discharge_col, "\n")
if (is.na(admit_col)) stop("No admission time column in admdad: ", paste(names(admdad), collapse = ", "))

enc <- admdad %>%
  mutate(admit_date_time = as_dt(.data[[admit_col]]),
         discharge_date_time = if (is.na(discharge_col)) NA else as_dt(.data[[discharge_col]])) %>%
  select(any_of(c("genc_id", "patient_id_hashed", "age", "gender", "hospital_num",
                  "admit_date_time", "discharge_date_time", "admit_category",
                  "discharge_disposition"))) %>%
  inner_join(sdh_info, by = "genc_id") %>%
  filter(sdh_present_on_arrival, age >= MIN_AGE)

ct_index <- ct_reports %>%
  filter(!is.na(imaging_result), trimws(imaging_result) != "",
         !grepl(CT_NAME_EXCLUDE, tolower(test_name_raw))) %>%
  mutate(performed_date_time = as_dt(performed_date_time)) %>%
  inner_join(select(enc, genc_id, admit_date_time), by = "genc_id") %>%
  mutate(hours_from_admit = as.numeric(difftime(performed_date_time, admit_date_time, units = "hours"))) %>%
  group_by(genc_id) %>%
  mutate(head_cts_in_encounter = n()) %>%
  filter(hours_from_admit >= -CT_WINDOW_BEFORE_H, hours_from_admit <= CT_WINDOW_AFTER_H) %>%
  slice_min(performed_date_time, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  select(-admit_date_time)

cohort <- enc %>%
  inner_join(ct_index, by = "genc_id") %>%
  left_join(main_diag, by = "genc_id") %>%
  left_join(other_dx, by = "genc_id")
if (!is.null(er_info))    cohort <- left_join(cohort, er_info, by = "genc_id")
if (!is.null(er_dx_info)) cohort <- left_join(cohort, er_dx_info, by = "genc_id")


# ---------------------------------------------------------------------
# 4. One encounter per patient (the first), development reports removed
# ---------------------------------------------------------------------

cohort <- cohort %>%
  group_by(patient_id_hashed) %>%
  slice_min(performed_date_time, n = 1, with_ties = FALSE) %>%
  ungroup()

excluded_dev <- 0

if (file.exists(DEVELOPMENT_IDS_FILE)) {
  dev_ids <- read.csv(DEVELOPMENT_IDS_FILE, colClasses = "character")$genc_id
  before <- nrow(cohort)
  cohort <- filter(cohort, !(as.character(genc_id) %in% dev_ids))
  excluded_dev <- excluded_dev + before - nrow(cohort)
}

# match by text: letters only, lower case, so spacing, line breaks and the
# "|" of the exports do not matter; two reports match when they share a
# 120-letter stretch
fingerprint <- function(x) gsub("[^a-z]", "", tolower(as.character(x)))

read_reports <- function(path) {
  d <- if (grepl("\\.xlsx?$", path, ignore.case = TRUE)) {
    as.data.frame(readxl::read_excel(path, col_types = "text"))
  } else {
    read.csv(path, colClasses = "character", check.names = FALSE)
  }
  # the report column = the one with the longest text on average
  lens <- sapply(d, function(col) mean(nchar(as.character(col)), na.rm = TRUE))
  col <- names(which.max(lens))
  out <- as.character(d[[col]])
  out[!is.na(out) & nchar(out) > 100]
}

dev_files <- DEVELOPMENT_REPORT_FILES[file.exists(DEVELOPMENT_REPORT_FILES)]
missing_files <- setdiff(DEVELOPMENT_REPORT_FILES, dev_files)
if (length(missing_files)) warning("Development files not found: ", paste(missing_files, collapse = ", "))

# one row per fingerprint: which development report it comes from + the key
dev_keys <- data.frame(dev_report = character(0), key = character(0))

if (length(dev_files)) {
  dev_text <- unlist(lapply(dev_files, read_reports))
  dev_keys <- bind_rows(dev_keys, bind_rows(lapply(seq_along(dev_text), function(i) {
    # three stretches from each development report: start, middle, end
    f <- fingerprint(dev_text[i])
    n <- nchar(f)
    if (n < 120) return(NULL)
    starts <- unique(c(1, floor((n - 120) / 2) + 1, n - 119))
    data.frame(dev_report = paste0("file_", i), key = substring(f, starts, starts + 119))
  })))
  cat("Development reports read from files:", length(dev_text), "\n")
}

if (file.exists(DEVELOPMENT_FINGERPRINTS_FILE)) {
  fp_file <- read.csv(DEVELOPMENT_FINGERPRINTS_FILE, colClasses = "character")
  cat("Development reports in the fingerprint file:", length(unique(fp_file$dev_report)), "\n")
  dev_keys <- bind_rows(dev_keys, mutate(fp_file, dev_report = paste0("fp_", dev_report)))
}

if (nrow(dev_keys)) {
  # a cohort report is a development report when it holds one of that
  # report's stretches. A stretch found in more than 3 cohort reports is a
  # stock sentence ("images for surgical navigation are available ..."),
  # not one report, and is ignored. Removing an extra report costs nothing;
  # missing a development report would bias the validation.
  cohort_fp <- fingerprint(cohort$imaging_result)
  hits <- vapply(dev_keys$key, function(k) grepl(k, cohort_fp, fixed = TRUE), logical(length(cohort_fp)))
  hits <- matrix(hits, nrow = length(cohort_fp))
  stock <- colSums(hits) > 3
  cat("Stock sentences ignored:", sum(stock), "of", ncol(hits), "fingerprints\n")
  is_dev <- rowSums(hits[, !stock, drop = FALSE]) > 0
  cat("Development reports matched in the cohort:",
      length(unique(dev_keys$dev_report[!stock & colSums(hits) > 0])),
      " cohort reports removed:", sum(is_dev), "\n")
  excluded_dev <- excluded_dev + sum(is_dev)
  cohort <- cohort[!is_dev, ]
}

if (!file.exists(DEVELOPMENT_IDS_FILE) && !nrow(dev_keys)) {
  warning("No development ids or files: reports used to build the NLP are not excluded yet.")
}
cat("Development reports removed:", excluded_dev, "\n")


# ---------------------------------------------------------------------
# 5. Keyword hints for screening (a person makes every decision)
# ---------------------------------------------------------------------

txt <- tolower(cohort$imaging_result)
cohort <- cohort %>%
  mutate(
    hint_sdh_in_report  = grepl("subdural|\\bsdh\\b|extra-?\\s?axial (hematoma|haematoma|hemorrhage|collection)", txt),
    hint_postop         = grepl("post-?\\s?op|craniotomy|craniectomy|burr hole|evacuation|status post|s/p", txt),
    hint_fracture       = grepl("fractur", txt),
    hint_falx_tentorium = grepl("falx|falcine|interhemispheric|tentori", txt),
    hint_herniation     = grepl("herniat", txt)
  )


# ---------------------------------------------------------------------
# 6. Random screening order within each stratum
# ---------------------------------------------------------------------

set.seed(SEED)
cohort <- cohort %>%
  group_by(stratum) %>%
  mutate(screening_order = sample(n())) %>%
  ungroup() %>%
  arrange(stratum, screening_order) %>%
  mutate(row_id = row_number()) %>%
  relocate(row_id, stratum, screening_order, genc_id, patient_id_hashed, hospital_num,
           age, gender, sdh_codes, sdh_is_primary, test_name_raw, performed_date_time,
           hours_from_admit) %>%
  relocate(imaging_result, .after = last_col())

write.csv(cohort, OUTPUT_FILE, row.names = FALSE, na = "")


# ---------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------

cat("\nPatients per stratum\n");               print(count(cohort, stratum))
cat("\nSDH is the most responsible diagnosis\n"); print(count(cohort, stratum, sdh_is_primary))
cat("\nAge\n")
print(cohort %>% group_by(stratum) %>% summarise(median = median(age), q1 = quantile(age, .25), q3 = quantile(age, .75)))
cat("\nLargest hospitals (cap: 22 of 150, 11 per stratum)\n")
print(cohort %>% count(stratum, hospital_num, sort = TRUE) %>% group_by(stratum) %>% slice_head(n = 5))
cat("\nKeyword hints (share of reports)\n")
print(cohort %>% group_by(stratum) %>% summarise(across(starts_with("hint_"), ~ round(mean(.x), 2))))
