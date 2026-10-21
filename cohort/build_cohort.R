# =====================================================================
# SDH validation cohort
#
# Builds the sampling frame for the NLP / LLM validation:
#   one row per patient = their first eligible encounter with an SDH code,
#   with the first head CT of that encounter, its report, and the
#   variables needed for screening (hospital, age, presenting complaint).
#   Two strata by ICD-10-CA code, each in a fixed random screening order.
#
#   traumatic       S065  (S06.5 traumatic subdural haemorrhage)
#   non-traumatic   I620  (I62.0 non-traumatic subdural haemorrhage)
#
# Run it where the data lives. The output contains report text: keep it
# on the approved server, never in git or email.
# =====================================================================

library(DBI)
library(dplyr)
library(stringr)
library(lubridate)
library(readr)


# ---------------------------------------------------------------------
# SETTINGS - match these to your database before running
# ---------------------------------------------------------------------

# con <- DBI::dbConnect(...)            # your existing connection

TABLES <- list(
  admdad      = "admdad",               # one row per encounter
  ipdiagnosis = "ipdiagnosis",          # inpatient diagnoses
  erdiagnosis = "erdiagnosis",          # emergency diagnoses
  er          = "er",                   # ER visit (presenting complaint, triage time)
  radiology   = "radiology"             # imaging tests and reports
)

COLS <- list(
  encounter        = "genc_id",
  patient          = "patient_id_hashed",     # set to NA if there is no patient id
  hospital         = "hospital_num",
  age              = "age",
  admit_time       = "admission_date_time",
  ip_code          = "diagnosis_code",
  ip_type          = "diagnosis_type",
  er_code          = "er_diagnosis_code",
  er_type          = "er_diagnosis_type",
  complaint        = "presenting_complaint",  # in the er table
  triage_time      = "triage_date_time",      # in the er table
  test_name        = "test_name_raw",         # CT name, e.g. "CT HEAD W/O CONTRAST"
  modality         = "modality_mapped",       # set to NA if there is no modality column
  ordered_time     = "ordered_date_time",
  performed_time   = "performed_date_time",
  report_text      = "result_text"            # the radiology report
)

SDH_CODES <- c(traumatic = "S065", nontraumatic = "I620")

# DAD diagnosis types that count. "2" (post-admit comorbidity) is an SDH
# that developed after admission - left out so the CT is the presenting
# one. Use c("M") for "SDH must be the most responsible diagnosis".
IP_TYPES_KEEP <- c("M", "1", "3", "W", "X", "Y", "6")

MIN_AGE <- 18
STUDY_START <- as.Date("2015-04-01")
STUDY_END   <- as.Date("2023-03-31")

# first head CT from this long before arrival to this long after
CT_WINDOW_BEFORE_H <- 24
CT_WINDOW_AFTER_H  <- 72

# reports already used to build the NLP (one report id or encounter id
# per line, column "genc_id"); they can never be sampled
DEVELOPMENT_IDS_FILE <- "development_report_ids.csv"

SEED <- 20261021
OUTPUT_FILE <- "sdh_validation_cohort.csv"


# ---------------------------------------------------------------------
# 1. Encounters with an SDH code (inpatient or emergency)
# ---------------------------------------------------------------------

codes <- unname(SDH_CODES)

ip_sdh <- tbl(con, TABLES$ipdiagnosis) |>
  transmute(genc_id = .data[[COLS$encounter]],
            code = .data[[COLS$ip_code]],
            dx_type = .data[[COLS$ip_type]]) |>
  filter(substr(code, 1, 4) %in% codes) |>
  collect() |>
  filter(dx_type %in% IP_TYPES_KEEP) |>
  mutate(source = "ip")

er_sdh <- tbl(con, TABLES$erdiagnosis) |>
  transmute(genc_id = .data[[COLS$encounter]],
            code = .data[[COLS$er_code]],
            dx_type = .data[[COLS$er_type]]) |>
  filter(substr(code, 1, 4) %in% codes) |>
  collect() |>
  mutate(source = "er")

sdh_dx <- bind_rows(ip_sdh, er_sdh) |>
  mutate(code4 = substr(code, 1, 4))

# one row per encounter; an encounter with both codes is traumatic
sdh_enc <- sdh_dx |>
  group_by(genc_id) |>
  summarise(
    stratum = if_else(any(code4 == SDH_CODES[["traumatic"]]), "traumatic", "nontraumatic"),
    both_codes = n_distinct(code4) > 1,
    sdh_codes = paste(sort(unique(code)), collapse = ";"),
    sdh_most_responsible = any(source == "ip" & dx_type == "M"),
    sdh_dx_sources = paste(sort(unique(source)), collapse = ";"),
    .groups = "drop"
  )


# ---------------------------------------------------------------------
# 2. Encounter details: hospital, age, arrival, presenting complaint
# ---------------------------------------------------------------------

adm <- tbl(con, TABLES$admdad) |>
  filter(.data[[COLS$encounter]] %in% !!sdh_enc$genc_id) |>
  collect() |>
  transmute(genc_id = .data[[COLS$encounter]],
            patient_id = if (is.na(COLS$patient)) .data[[COLS$encounter]] else .data[[COLS$patient]],
            hospital_num = .data[[COLS$hospital]],
            age = .data[[COLS$age]],
            admit_time = ymd_hms(.data[[COLS$admit_time]], truncated = 3))

er_visit <- tbl(con, TABLES$er) |>
  filter(.data[[COLS$encounter]] %in% !!sdh_enc$genc_id) |>
  collect() |>
  transmute(genc_id = .data[[COLS$encounter]],
            presenting_complaint = .data[[COLS$complaint]],
            triage_time = ymd_hms(.data[[COLS$triage_time]], truncated = 3)) |>
  group_by(genc_id) |>
  slice_min(triage_time, n = 1, with_ties = FALSE) |>
  ungroup()

enc <- sdh_enc |>
  inner_join(adm, by = "genc_id") |>
  left_join(er_visit, by = "genc_id") |>
  mutate(arrival_time = coalesce(triage_time, admit_time)) |>
  filter(age >= MIN_AGE,
         as.Date(arrival_time) >= STUDY_START,
         as.Date(arrival_time) <= STUDY_END)


# ---------------------------------------------------------------------
# 3. The first head CT of each encounter, with its report
# ---------------------------------------------------------------------

rad <- tbl(con, TABLES$radiology) |>
  filter(.data[[COLS$encounter]] %in% !!enc$genc_id) |>
  collect() |>
  transmute(genc_id = .data[[COLS$encounter]],
            ct_name = .data[[COLS$test_name]],
            modality = if (is.na(COLS$modality)) NA_character_ else .data[[COLS$modality]],
            ct_ordered_time = ymd_hms(.data[[COLS$ordered_time]], truncated = 3),
            ct_performed_time = ymd_hms(.data[[COLS$performed_time]], truncated = 3),
            report_text = .data[[COLS$report_text]])

head_ct <- rad |>
  filter(
    is.na(modality) | str_detect(str_to_upper(modality), "CT"),
    str_detect(str_to_upper(ct_name), "\\bCT\\b|COMPUTED TOMOGRAPHY"),
    str_detect(str_to_upper(ct_name), "HEAD|BRAIN|CRANI"),
    # angiograms, perfusion, spine-only and face-only studies are not the index head CT
    !str_detect(str_to_upper(ct_name), "ANGIO|CTA\\b|PERFUSION|VENOGRAM|SPINE ONLY|FACIAL BONES ONLY"),
    !is.na(report_text), str_length(report_text) > 50
  ) |>
  inner_join(select(enc, genc_id, arrival_time), by = "genc_id") |>
  mutate(hours_from_arrival = as.numeric(difftime(ct_performed_time, arrival_time, units = "hours"))) |>
  filter(hours_from_arrival >= -CT_WINDOW_BEFORE_H,
         hours_from_arrival <= CT_WINDOW_AFTER_H) |>
  group_by(genc_id) |>
  slice_min(ct_performed_time, n = 1, with_ties = FALSE) |>
  ungroup()


# ---------------------------------------------------------------------
# 4. One encounter per patient, development reports removed
# ---------------------------------------------------------------------

cohort <- enc |>
  inner_join(head_ct, by = c("genc_id", "arrival_time")) |>
  group_by(patient_id) |>
  slice_min(arrival_time, n = 1, with_ties = FALSE) |>
  ungroup()

if (file.exists(DEVELOPMENT_IDS_FILE)) {
  dev_ids <- read_csv(DEVELOPMENT_IDS_FILE, col_types = cols(.default = "c"))$genc_id
  cohort <- filter(cohort, !(as.character(genc_id) %in% dev_ids))
} else {
  warning("No development id file: reports used to build the NLP are not excluded yet.")
}


# ---------------------------------------------------------------------
# 5. Screening helpers (flags only - a person makes every decision)
# ---------------------------------------------------------------------

txt <- str_to_lower(cohort$report_text)

cohort <- cohort |>
  mutate(
    flag_sdh_in_report  = str_detect(txt, "subdural|\\bsdh\\b|extra-?\\s?axial (hematoma|haematoma|hemorrhage|collection)"),
    flag_postop         = str_detect(txt, "post-?\\s?op|craniotomy|craniectomy|burr hole|evacuation|status post|s/p"),
    flag_fracture_word  = str_detect(txt, "fractur"),
    flag_falx_tentorium = str_detect(txt, "falx|falcine|interhemispheric|tentori"),
    flag_herniation     = str_detect(txt, "herniat")
  )


# ---------------------------------------------------------------------
# 6. Random screening order within each stratum
# ---------------------------------------------------------------------

set.seed(SEED)

cohort <- cohort |>
  group_by(stratum) |>
  mutate(screening_order = sample(n())) |>
  ungroup() |>
  arrange(stratum, screening_order) |>
  mutate(row_id = row_number()) |>
  select(row_id, stratum, screening_order, genc_id, patient_id, hospital_num, age,
         presenting_complaint, sdh_codes, both_codes, sdh_most_responsible, sdh_dx_sources,
         arrival_time, ct_name, ct_ordered_time, ct_performed_time, hours_from_arrival,
         starts_with("flag_"), report_text)

write_csv(cohort, OUTPUT_FILE)


# ---------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------

cat("\nPatients per stratum\n")
print(count(cohort, stratum))

cat("\nSDH as most responsible diagnosis\n")
print(count(cohort, stratum, sdh_most_responsible))

cat("\nLargest hospitals (15% cap = 22 of 150, 11 per stratum)\n")
print(cohort |> count(stratum, hospital_num, sort = TRUE) |> group_by(stratum) |> slice_head(n = 5))

cat("\nScreening flags (keyword hits, not findings)\n")
print(cohort |> group_by(stratum) |>
        summarise(across(starts_with("flag_"), ~ round(mean(.x), 2)), .groups = "drop"))
