# =====================================================================
# Adds transfer and comparison-to-prior flags to the frozen cohort file,
# without changing its rows, their order or row_id.
#
#   transferred_in      the ER record names an institution the patient came from
#   institution_from    that institution
#   triage_level, admit_via_ambulance, triage_date_time   ER context
#   flag_comparison     the report compares with a prior study ("again noted",
#                       "unchanged", "previously", "interval", "Comparison: ...")
#
# These are the automatic signals for a follow-up-style report. Screening
# records a person's judgment of the same thing (comparison_prior in
# sdh_screening.csv), so the flags' accuracy can be measured.
#
# Run in the GEMINI session (needs db and datacut).
# =====================================================================

library(DBI)
library(dplyr)

COHORT_FILE <- "sdh_validation_cohort.csv"

cohort_saved <- read.csv(COHORT_FILE, stringsAsFactors = FALSE, check.names = FALSE)
n_before <- nrow(cohort_saved)
ids_before <- cohort_saved$row_id


# ---------------------------------------------------------------------
# ER details for the cohort encounters
# ---------------------------------------------------------------------

dbGetQuery(db, paste0("SET search_path TO '", datacut, "', public;"))

tryCatch({ rs <- dbSendQuery(db, "DROP TABLE IF EXISTS temp_cohort"); dbClearResult(rs) }, error = function(e) NULL)
DBI::dbWriteTable(db, c("pg_temp", "temp_cohort"), data.frame(genc_id = unique(cohort_saved$genc_id)),
                  row.names = FALSE, overwrite = TRUE)

er_ctx <- dbGetQuery(db, "
  SELECT e.genc_id, e.institution_from, e.triage_level, e.admit_via_ambulance, e.triage_date_time
  FROM er_subset e
  INNER JOIN temp_cohort t ON e.genc_id = t.genc_id
") %>%
  arrange(genc_id, triage_date_time) %>%
  group_by(genc_id) %>%
  slice_head(n = 1) %>%            # one ER record per encounter, so no row is duplicated
  ungroup() %>%
  mutate(transferred_in = !is.na(institution_from) & trimws(as.character(institution_from)) != "")


# ---------------------------------------------------------------------
# Comparison wording in the report
# ---------------------------------------------------------------------

COMPARISON_WORDS <- paste(
  "again (noted|seen|demonstrated|identified)", "re-?demonstrat", "unchanged", "\\bstable\\b",
  "previously", "\\bprior (study|exam|ct|scan|imaging)", "interval (increase|decrease|change|development|resolution|enlargement)",
  "compared (to|with)", "in comparison", "no (significant )?change", "since the (prior|previous|last)",
  "comparison:\\s*(ct|mri|outside|head|\\d)", "outside (ct|study|hospital|imaging)",
  sep = "|"
)


# ---------------------------------------------------------------------
# Add the columns (same rows, same order) and save
# ---------------------------------------------------------------------

cohort_saved <- cohort_saved %>%
  select(-any_of(c("institution_from", "triage_level", "admit_via_ambulance", "triage_date_time",
                   "transferred_in", "flag_comparison"))) %>%
  left_join(er_ctx, by = "genc_id") %>%
  mutate(transferred_in = coalesce(transferred_in, FALSE),
         flag_comparison = grepl(COMPARISON_WORDS, tolower(imaging_result))) %>%
  arrange(row_id) %>%
  relocate(imaging_result, .after = last_col())

stopifnot(nrow(cohort_saved) == n_before, identical(sort(cohort_saved$row_id), sort(ids_before)))
write.csv(cohort_saved, COHORT_FILE, row.names = FALSE, na = "")

cat("Rows unchanged:", n_before, "\n\n")
print(cohort_saved %>% group_by(stratum) %>%
        summarise(transferred_in = round(mean(transferred_in), 2),
                  comparison_wording = round(mean(flag_comparison), 2),
                  either = round(mean(transferred_in | flag_comparison), 2)))
