# =====================================================================
# Which development-set reports are really development reports?
#
# build_cohort.R removes a cohort report from the validation pool when it
# shares one 60-letter stretch with a report used to build the NLP. That
# is deliberately generous: template wording ("effacement of cerebral sulci
# greater on the right, compression of the ...") also matches unrelated
# reports. This check uses longer fingerprints (three 120-letter stretches
# per development report: start, middle, end) to label each report in
# sdh_development_reports.csv:
#
#   confirmed   2 or 3 of one development report's stretches are in it
#   likely      1 stretch (often a report cut short in one of the files)
#   template    none: it only shared a short piece of common wording
#
# Nothing is changed or removed: the training set stays the same. The
# output has no report text.
#
# Run: paste dev_fingerprints_full_paste.R into the session (it makes
# dev_fp_full), then source("check_development_matches.R").
# =====================================================================

library(dplyr)

DATA_DIR <- getwd()
DEVELOPMENT_FILE <- file.path(DATA_DIR, "sdh_development_reports.csv")
OUTPUT_FILE <- file.path(DATA_DIR, "sdh_development_match_check.csv")

if (!exists("dev_fp_full")) stop("Paste dev_fingerprints_full_paste.R into this session first.")
if (!file.exists(DEVELOPMENT_FILE)) stop("Not found: ", DEVELOPMENT_FILE)

dev <- read.csv(DEVELOPMENT_FILE, stringsAsFactors = FALSE, check.names = FALSE)
fingerprint <- function(x) gsub("[^a-z]", "", tolower(as.character(x)))
dev_fp <- fingerprint(dev$imaging_result)

# for each report: how many stretches of its best-matching development report it holds
best <- t(vapply(dev_fp, function(f) {
  hit <- vapply(dev_fp_full$key, function(k) grepl(k, f, fixed = TRUE), logical(1))
  if (!any(hit)) return(c(keys = 0, dev_report = NA))
  per_report <- table(dev_fp_full$dev_report[hit])
  c(keys = max(per_report), dev_report = as.numeric(names(per_report)[which.max(per_report)]))
}, numeric(2)))

check <- dev %>%
  select(row_id, stratum) %>%
  mutate(keys_matched = as.integer(best[, "keys"]),
         dev_report = best[, "dev_report"],
         dev_match = case_when(keys_matched >= 2 ~ "confirmed",
                               keys_matched == 1 ~ "likely",
                               TRUE ~ "template"))

write.csv(check, OUTPUT_FILE, row.names = FALSE, na = "")

cat("\nDevelopment set:", nrow(check), "reports\n")
print(count(check, dev_match))
cat("\nBy stratum\n")
print(count(check, stratum, dev_match))
cat("\nDistinct development reports found (confirmed or likely):",
    length(unique(na.omit(check$dev_report[check$dev_match != "template"]))), "\n")
cat("Saved (no report text):", OUTPUT_FILE, "\n")
