# =====================================================================
# SDH validation: screening + extraction app
#
#   Screening tab   one person works down each stratum in screening order:
#                   include, or exclude with a reason. Stops a stratum at
#                   75; enforces the hospital cap (11 per stratum, 22 total).
#   Extraction tab  each extractor codes every included report with
#                   dropdowns that only allow the coding guide's values.
#
# Data: the cohort from build_cohort.R (the `cohort` object in this R
# session, or sdh_validation_cohort.csv in the working folder).
#
# Files written to the working folder (they hold no report text except
# report_whole in the extraction files, which the NLP scoring needs):
#   sdh_screening.csv                   one row per screened report
#   sdh_extraction_<extractor>.csv      one file per extractor; the same
#                                       columns as the NLP validation sheet
#
# Run: source("sdh_extraction_app.R")   (or open it and click Run App)
# =====================================================================

library(shiny)
library(dplyr)


# ---------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------

EXTRACTORS <- c("Student 1", "Student 2", "Radiologist 1", "Radiologist 2")

TARGET_PER_STRATUM <- 75
HOSPITAL_CAP_STRATUM <- 11      # 15% of 75
HOSPITAL_CAP_TOTAL <- 22        # 15% of 150
FINDING_MINIMUM <- 20           # fracture, falx / tentorium, herniation

# the folder that holds the cohort and every saved file; keep it the same
# every time (the app reads what is already saved there when it starts)
DATA_DIR <- getwd()

COHORT_FILE <- file.path(DATA_DIR, "sdh_validation_cohort.csv")
SCREENING_FILE <- file.path(DATA_DIR, "sdh_screening.csv")
extraction_file <- function(who) file.path(DATA_DIR, paste0("sdh_extraction_", gsub("[^A-Za-z0-9]", "_", who), ".csv"))

# A report that compares with an earlier (outside) study is NOT excluded: it
# is the first CT in the data for the encounter. Tick "compares with a prior
# study" instead. Post-operative reports are excluded.
EXCLUSION_REASONS <- c(
  "Post-operative report",
  "Earlier head CT in the data for this encounter",
  "No SDH described in the report",
  "Not a head CT / report incomplete",
  "Hospital cap reached",
  "Development report",
  "Other"
)


# ---------------------------------------------------------------------
# VARIABLES - names exactly as in the validation sheet, values from the
# coding guide (NR first = the default)
# ---------------------------------------------------------------------

YN       <- c("NR", "Yes", "No")
GRADE    <- c("NR", "No", "Yes NS", "Mild", "Moderate", "Severe")
SIDE     <- c("NR", "Left", "Right", "Bilateral")
DESC     <- c("NR", "Small", "Medium", "Large")
ACUITY   <- c("NR", "Acute", "Subacute", "Chronic", "Acute on chronic",
              "Subacute on chronic", "Acute on Subacute")
DOMINANT <- c("NR", "Hyperdense", "Hypodense", "Isodense")
INTERNAL <- c("NR", "Septations", "Dependant", "Layering")
COMPART  <- c("NR", "Yes NS", "Left", "Right", "Bilateral", "No")
CDENS    <- c("NR", "Hyperdense", "Hypodense", "Isodense", "Mixed")
INFARCT  <- c("NR", "Yes Acute", "Yes Chronic", "Yes NS", "No Acute", "No NS")
FX_LOC   <- c("NR", "No", "Calvarial", "Facial", "Skull base", "Calvarial & Facial",
              "Calvarial & Skull base", "Facial & Skull base", "Calvarial & Facial & Skull base")
FX_TYPE  <- c("NR", "Linear", "Non-displaced", "Displaced", "Depressed", "Comminuted")
SINUS    <- c("NR", "Clear", "Mild mucosal thickening", "Moderate mucosal thickening",
              "Mucosal thickening NS", "Mild opacification", "Severe opacification",
              "Opacification NS", "Retention cyst", "Fluid")

v <- function(name, group, choices = NULL, label = NULL, numeric = FALSE) {
  list(name = name, group = group, choices = choices,
       label = if (is.null(label)) trimws(name) else label, numeric = numeric)
}

side_vars <- function(s) {
  g <- if (s == "L") "Left SDH" else "Right SDH"
  list(
    v(paste0(s, "_description"), g, DESC, "Description"),
    v(paste0(s, "_acuity"), g, ACUITY, "Acuity"),
    v(paste0(s, "_mixed_density"), g, YN, "Mixed density"),
    v(paste0(s, "_hyperdense"), g, YN, "Hyperdense"),
    v(paste0(s, "_hypodense"), g, YN, "Hypodense"),
    v(paste0(s, "_isodense"), g, YN, "Isodense"),
    v(paste0(s, "_density_dominance"), g, DOMINANT, "Density dominance"),
    v(paste0(s, "_internal_appearence"), g, INTERNAL, "Internal appearance"),
    v(paste0(s, "_thickness_mm"), g, label = "Thickness (mm)", numeric = TRUE),
    v(paste0(s, "_convexity_hematoma"), g, YN, "Convexity"),
    v(paste0(s, "_holohemispheric _ hematoma"), g, YN, "Holohemispheric"),
    v(paste0(s, "_vertex"), g, YN, "Vertex"),
    v(paste0(s, "_frontal_lobe "), g, YN, "Frontal"),
    v(paste0(s, "_parietal_lobe "), g, YN, "Parietal"),
    v(paste0(s, "_temporal_lobe "), g, YN, "Temporal"),
    v(paste0(s, "_occipital_lobe "), g, YN, "Occipital"),
    v(paste0(s, "_middle_fossa "), g, YN, "Middle fossa")
  )
}

VARIABLES <- c(
  list(v("laterality ", "SDH", c("NR", "Left", "Right", "Bilateral", "Falx"), "Laterality")),
  side_vars("L"),
  side_vars("R"),
  list(
    v("parafalcine_hematoma", "Falx", COMPART, "Falx SDH"),
    v("parafalcine_description", "Falx", DESC, "Description"),
    v("parafalcine_location", "Falx", c("NR", "Anterior", "Posterior", "Anterior/posterior"), "Location"),
    v("parafalcine_thickness_mm", "Falx", label = "Thickness (mm)", numeric = TRUE),
    v("parafalcine_density", "Falx", CDENS, "Density"),
    v("parafalcine_acuity", "Falx", ACUITY, "Acuity"),

    v("tentorium_hematoma", "Tentorium", COMPART, "Tentorium SDH"),
    v("tentorium_description", "Tentorium", DESC, "Description"),
    v("tentorium_thickness_mm", "Tentorium", label = "Thickness (mm)", numeric = TRUE),
    v("tentorium_acuity", "Tentorium", ACUITY, "Acuity"),

    v("mass_effect_present", "Mass effect and shift", GRADE, "Mass effect"),
    v("midline_shift_present", "Mass effect and shift", GRADE, "Midline shift"),
    v("midline_shift_mm", "Mass effect and shift", label = "Midline shift (mm)", numeric = TRUE),
    v("midline_shift_direction", "Mass effect and shift", c("NR", "Left", "Right"), "Shift direction"),

    v("effacement_sulci", "Effacement and ventricles", GRADE, "Sulcal effacement"),
    v("effacement_sulci_laterality", "Effacement and ventricles", SIDE, "Sulcal side"),
    v("effacement_lateral_ventricle", "Effacement and ventricles", GRADE, "Lateral ventricle effacement"),
    v("l_ventricle_laterality", "Effacement and ventricles", SIDE, "Lateral ventricle side"),
    v("effacement_third_ventricle", "Effacement and ventricles", GRADE, "Third ventricle effacement"),
    v("effacement_ventricular_system", "Effacement and ventricles", GRADE, "Ventricular system effacement"),
    v("l_ventricular_prominence", "Effacement and ventricles", GRADE, "Ventricular prominence"),
    v("l_v_prominence_laterality", "Effacement and ventricles", SIDE, "Prominence side"),
    v("ex_vacuo_ventriculomegaly", "Effacement and ventricles", GRADE, "Ex vacuo ventriculomegaly"),
    v("hydrocephalus", "Effacement and ventricles", GRADE, "Hydrocephalus"),

    v("herniation_subfalcine", "Herniation", GRADE, "Subfalcine"),
    v("herniation_uncal", "Herniation", GRADE, "Uncal"),
    v("herniation_transtentorial", "Herniation", GRADE, "Transtentorial"),
    v("herniation_tonsillar ", "Herniation", GRADE, "Tonsillar"),

    v("microangiopathy ", "Other brain findings", GRADE, "Microangiopathy"),
    v("cerebral_atrophy", "Other brain findings", c(GRADE, "Age appropriate"), "Cerebral atrophy"),
    v("encephalomalacia ", "Other brain findings", GRADE, "Encephalomalacia"),
    v("white_dark_differentiation", "Other brain findings", YN, "Gray-white differentiation"),
    v("mass", "Other brain findings", YN, "Mass"),
    v("territorial_ infarct", "Other brain findings", INFARCT, "Territorial infarct"),
    v("lacune_infarct", "Other brain findings", INFARCT, "Lacunar infarct"),
    v("unspecified__infarct", "Other brain findings", INFARCT, "Unspecified infarct"),
    v("parenchymal_edema", "Other brain findings", YN, "Edema"),

    v("parenchymal_contusion", "Other bleeds", YN, "Contusion"),
    v("parenchymal_hemorrhage", "Other bleeds", YN, "Intraparenchymal hemorrhage"),
    v("subarachnoid_hemorrhage", "Other bleeds", YN, "Subarachnoid hemorrhage"),
    v("intraventricular_hemorrhage", "Other bleeds", YN, "Intraventricular hemorrhage"),
    v("epidural_hemorrhage", "Other bleeds", YN, "Epidural hemorrhage"),

    v("bony_lesion", "Bone, scalp, orbit", YN, "Fracture (bony lesion)"),
    v("fracture_location", "Bone, scalp, orbit", FX_LOC, "Fracture location"),
    v("fracture_type_ordinal", "Bone, scalp, orbit", FX_TYPE, "Fracture type"),
    v("scalp_hematoma", "Bone, scalp, orbit", YN, "Scalp hematoma"),
    v("soft_tissue_lesion", "Bone, scalp, orbit", YN, "Soft tissue lesion"),
    v("orbital_lesion", "Bone, scalp, orbit", YN, "Orbital lesion"),

    v("paranal_sinuses", "Sinuses and mastoids", SINUS, "Paranasal sinuses"),
    v("mastoid_air_cells", "Sinuses and mastoids", SINUS, "Mastoid air cells"),
    v("sphenoid_sinus", "Sinuses and mastoids", SINUS, "Sphenoid sinus"),
    v("ethmoid_sinus", "Sinuses and mastoids", SINUS, "Ethmoid sinus"),
    v("maxillary_sinus", "Sinuses and mastoids", SINUS, "Maxillary sinus")
  )
)

VAR_NAMES <- vapply(VARIABLES, `[[`, "", "name")
input_id <- function(name) paste0("v_", gsub("[^A-Za-z0-9]", "_", trimws(name)))

# the sheet's column order: every mm column is followed by its cm column
SHEET_COLUMNS <- unlist(lapply(VARIABLES, function(x) {
  if (x$numeric) c(x$name, sub("_mm$", "_cm", x$name)) else x$name
}))


# ---------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------

# the frozen cohort file (row_id is what links every saved decision to its
# report, so the app always reads the saved file, not a rebuilt cohort)
if (!file.exists(COHORT_FILE)) stop("Cohort file not found: ", COHORT_FILE)
dat <- read.csv(COHORT_FILE, stringsAsFactors = FALSE, check.names = FALSE) %>%
  arrange(stratum, screening_order)
cat("Cohort:", nrow(dat), "reports  | saving to", DATA_DIR, "\n")

read_or_empty <- function(path) {
  if (file.exists(path)) read.csv(path, stringsAsFactors = FALSE, check.names = FALSE,
                                  colClasses = "character")
  else NULL
}

# replace one report's row in a CSV (or add it)
upsert <- function(path, row) {
  old <- read_or_empty(path)
  if (!is.null(old)) {
    old <- old[old$row_id != as.character(row$row_id[1]), , drop = FALSE]
    row <- bind_rows(mutate(old, across(everything(), as.character)),
                     mutate(row, across(everything(), as.character)))
  }
  write.csv(row, path, row.names = FALSE, na = "")
}


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

report_style <- "background:white; padding:16px; border:1px solid #ddd; border-radius:6px;
                 white-space:pre-wrap; font-size:14px; line-height:1.7; max-height:75vh;
                 overflow-y:auto; user-select:text;"

group_panel <- function(group) {
  vars <- Filter(function(x) x$group == group, VARIABLES)
  inputs <- lapply(vars, function(x) {
    if (x$numeric) {
      numericInput(input_id(x$name), x$label, value = NA, min = 0, step = 0.1, width = "100%")
    } else {
      selectInput(input_id(x$name), x$label, choices = x$choices, selected = "NR",
                  selectize = FALSE, width = "100%")
    }
  })
  rows <- split(inputs, ceiling(seq_along(inputs) / 3))
  wellPanel(h4(group), lapply(rows, function(r) fluidRow(lapply(r, function(i) column(4, i)))))
}

GROUPS <- unique(vapply(VARIABLES, `[[`, "", "group"))

ui <- fluidPage(
  tags$head(tags$style(HTML("
    body { font-family: 'Segoe UI', Arial, sans-serif; background:#f5f5f5; }
    .ctx { background:#eef4ff; padding:10px 14px; border-radius:6px; border:1px solid #c5d5ea; margin-bottom:10px; }
    .well { padding:10px 14px; margin-bottom:10px; }
    .well h4 { margin-top:0; color:#1B3A5C; }
    .form-group { margin-bottom:6px; }
    .count { font-size:15px; }
  "))),
  titlePanel("SDH validation: screening and extraction"),
  fluidRow(column(4, selectInput("who", "Extractor (choose before you start; saved with every report)",
                                 choices = c("Choose..." = "", EXTRACTORS)))),
  tabsetPanel(
    id = "tabs",

    # ---------------- screening
    tabPanel("Screening",
      br(),
      fluidRow(
        column(3,
          radioButtons("s_stratum", "Stratum", choices = c("traumatic", "nontraumatic")),
          uiOutput("s_counts"),
          hr(),
          checkboxInput("s_comparison", "Report compares with a prior study (again noted, unchanged, previously ...)"),
          actionButton("s_include", "Include", class = "btn-success", width = "100%"),
          br(), br(),
          selectInput("s_reason", "Exclusion reason", choices = EXCLUSION_REASONS, width = "100%"),
          textInput("s_other", "Other reason (if Other)", width = "100%"),
          actionButton("s_exclude", "Exclude", class = "btn-danger", width = "100%"),
          br(), br(),
          checkboxInput("s_supplement", "Supplementary sample (stratum full: include only reports with a finding still under the minimum)"),
          actionButton("s_undo", "Undo last decision", width = "100%")
        ),
        column(9, div(class = "ctx", uiOutput("s_context")), div(style = report_style, uiOutput("s_report")))
      )
    ),

    # ---------------- extraction
    tabPanel("Extraction",
      br(),
      fluidRow(
        column(5,
          radioButtons("e_stratum", NULL, inline = TRUE,
                       choices = c("Traumatic" = "traumatic", "Non-traumatic" = "nontraumatic", "Both" = "both")),
          div(class = "ctx", uiOutput("e_context")),
          fluidRow(
            column(3, actionButton("e_prev", "< Prev", width = "100%")),
            column(3, actionButton("e_next", "Next >", width = "100%")),
            column(3, numericInput("e_goto", NULL, value = 1, min = 1, width = "100%")),
            column(3, actionButton("e_jump", "Go", width = "100%"))
          ),
          div(style = report_style, uiOutput("e_report"))
        ),
        column(7,
          div(style = "max-height:80vh; overflow-y:auto; padding-right:6px;",
            lapply(GROUPS, group_panel),
            wellPanel(
              h4("Finish"),
              checkboxInput("e_flag", "Flag this report for discussion"),
              textAreaInput("e_notes", "Notes", width = "100%", height = "70px"),
              actionButton("e_save", "Save and next", class = "btn-primary", width = "100%"),
              br(), br(),
              actionButton("e_reset", "Reset all to NR", width = "100%")
            ),
            wellPanel(
              h4("Not eligible after all?"),
              p("Takes the report out of the sample and records why; screening then adds the next report in its place."),
              selectInput("e_ex_reason", "Reason", choices = setdiff(EXCLUSION_REASONS, "Hospital cap reached"), width = "100%"),
              textInput("e_ex_other", "Other reason (if Other)", width = "100%"),
              actionButton("e_exclude", "Exclude and send back to screening", class = "btn-danger", width = "100%")
            )
          )
        )
      )
    )
  )
)


# ---------------------------------------------------------------------
# SERVER
# ---------------------------------------------------------------------

server <- function(input, output, session) {

  screening <- reactiveVal(read_or_empty(SCREENING_FILE))

  # ---------------- screening
  included <- reactive({
    s <- screening()
    if (is.null(s)) return(dat[0, ])
    ids <- s$row_id[s$decision %in% c("Included", "Included (supplementary)")]
    dat %>% filter(row_id %in% as.integer(ids))
  })

  main_included <- reactive({
    s <- screening()
    if (is.null(s)) return(dat[0, ])
    dat %>% filter(row_id %in% as.integer(s$row_id[s$decision == "Included"]))
  })

  next_candidate <- reactive({
    done <- if (is.null(screening())) integer(0) else as.integer(screening()$row_id)
    dat %>% filter(stratum == input$s_stratum, !(row_id %in% done)) %>% slice_head(n = 1)
  })

  # findings in the included reports, from the screener's own extraction
  finding_counts <- reactive({
    if (!nzchar(input$who)) return(NULL)
    ex <- read_or_empty(extraction_file(input$who))
    input$e_save
    if (is.null(ex)) return(c(fracture = 0, falx_tentorium = 0, herniation = 0))
    ex <- ex %>% filter(as.integer(row_id) %in% included()$row_id)
    pos <- function(col) !(ex[[col]] %in% c("", "NR", "No"))
    c(fracture = sum(ex$bony_lesion == "Yes"),
      falx_tentorium = sum(pos("parafalcine_hematoma") | pos("tentorium_hematoma")),
      herniation = sum(pos("herniation_subfalcine") | pos("herniation_uncal") |
                       pos("herniation_transtentorial") | pos("herniation_tonsillar ")))
  })

  output$s_counts <- renderUI({
    inc <- main_included()
    per <- count(inc, stratum)
    n_of <- function(s) { x <- per$n[per$stratum == s]; if (length(x)) x else 0 }
    hosp <- inc %>% count(hospital_num, sort = TRUE) %>% slice_head(n = 3)
    fc <- finding_counts()
    tagList(
      div(class = "count",
        p(strong("Included (main sample)")),
        p("Traumatic: ", n_of("traumatic"), " / ", TARGET_PER_STRATUM),
        p("Non-traumatic: ", n_of("nontraumatic"), " / ", TARGET_PER_STRATUM),
        p(strong("Largest hospitals"), br(),
          if (nrow(hosp)) paste0(hosp$hospital_num, ": ", hosp$n, collapse = " | ") else "none yet",
          br(), em("cap ", HOSPITAL_CAP_STRATUM, " per stratum, ", HOSPITAL_CAP_TOTAL, " total")),
        if (!is.null(fc)) p(strong("Findings so far"), em(" (from your extractions)"), br(),
          "Fracture: ", fc[["fracture"]], " | Falx/tentorium: ", fc[["falx_tentorium"]],
          " | Herniation: ", fc[["herniation"]], br(), em("minimum ", FINDING_MINIMUM, " each"))
      )
    )
  })

  cap_reached <- reactive({
    row <- next_candidate()
    if (!nrow(row)) return(FALSE)
    inc <- main_included()
    sum(inc$hospital_num == row$hospital_num & inc$stratum == row$stratum) >= HOSPITAL_CAP_STRATUM ||
      sum(inc$hospital_num == row$hospital_num) >= HOSPITAL_CAP_TOTAL
  })

  stratum_full <- reactive(sum(main_included()$stratum == input$s_stratum) >= TARGET_PER_STRATUM)

  output$s_context <- renderUI({
    row <- next_candidate()
    if (!nrow(row)) return(h4("No reports left in this stratum."))
    hints <- c(Fracture = row$hint_fracture, `Falx/tentorium` = row$hint_falx_tentorium,
               Herniation = row$hint_herniation, `Post-op words` = row$hint_postop,
               `SDH word` = row$hint_sdh_in_report)
    hints <- names(hints)[as.logical(hints) %in% TRUE]
    tagList(
      if (stratum_full() && !isTRUE(input$s_supplement))
        h4(style = "color:#2e7d32;", "This stratum has ", TARGET_PER_STRATUM, " reports: screening is complete."),
      if (cap_reached())
        h4(style = "color:#c62828;", "Hospital ", row$hospital_num, " is at its cap: exclude with \"Hospital cap reached\"."),
      p(strong("Row "), row$row_id, strong(" | screening order "), row$screening_order,
        strong(" | hospital "), row$hospital_num, strong(" | age "), row$age,
        strong(" | sex "), row$gender),
      p(strong("CT: "), row$test_name_raw, strong(" | performed "), as.character(row$performed_date_time),
        strong(" | hours from admission "), round(as.numeric(row$hours_from_admit), 1)),
      p(strong("SDH codes: "), row$sdh_codes, strong(" | SDH most responsible: "), row$sdh_is_primary,
        strong(" | head CTs this encounter: "), row$head_cts_in_encounter),
      p(strong("Keyword hints: "), if (length(hints)) paste(hints, collapse = ", ") else "none",
        em(" (words only; read the report)"))
    )
  })

  output$s_report <- renderUI({
    row <- next_candidate()
    if (!nrow(row)) return(NULL)
    row$imaging_result
  })

  record_screening <- function(decision, reason = "", row = next_candidate()) {
    if (!nzchar(input$who)) { showNotification("Choose the extractor first.", type = "error"); return() }
    if (!nrow(row)) return()
    upsert(SCREENING_FILE, data.frame(
      row_id = row$row_id, stratum = row$stratum, screening_order = row$screening_order,
      genc_id = row$genc_id, hospital_num = row$hospital_num, decision = decision,
      comparison_prior = isTRUE(input$s_comparison),
      reason = reason, screened_by = input$who, screened_at = format(Sys.time(), "%Y-%m-%d %H:%M:%S")
    ))
    screening(read_or_empty(SCREENING_FILE))
    updateCheckboxInput(session, "s_comparison", value = FALSE)
  }

  observeEvent(input$s_include, {
    if (cap_reached()) {
      showNotification("This hospital is at its cap: exclude it.", type = "error"); return()
    }
    if (stratum_full() && !isTRUE(input$s_supplement)) {
      showNotification("This stratum is full. Tick 'Supplementary sample' to add enrichment reports.", type = "error"); return()
    }
    record_screening(if (stratum_full()) "Included (supplementary)" else "Included")
  })

  observeEvent(input$s_exclude, {
    reason <- if (input$s_reason == "Other") paste("Other:", input$s_other) else input$s_reason
    record_screening("Excluded", reason)
  })

  observeEvent(input$s_undo, {
    s <- screening()
    if (is.null(s) || !nrow(s)) return()
    s <- s[order(s$screened_at), ]
    s <- s[-nrow(s), , drop = FALSE]
    write.csv(s, SCREENING_FILE, row.names = FALSE, na = "")
    screening(read_or_empty(SCREENING_FILE))
  })


  # ---------------- extraction
  idx <- reactiveVal(1)
  queue <- reactive({
    q <- included() %>% arrange(stratum, screening_order)
    if (input$e_stratum != "both") q <- filter(q, stratum == input$e_stratum)
    q
  })
  observeEvent(input$e_stratum, idx(1))

  observeEvent(input$e_exclude, {
    row <- current()
    if (is.null(row)) return()
    reason <- if (input$e_ex_reason == "Other") paste("Other:", input$e_ex_other) else input$e_ex_reason
    record_screening("Excluded", paste("During extraction:", reason), row = row)
    showNotification(paste("Row", row$row_id, "excluded; screen the next report to replace it."),
                     type = "warning", duration = 5)
  })

  my_extractions <- reactive({
    input$e_save
    if (!nzchar(input$who)) return(NULL)
    read_or_empty(extraction_file(input$who))
  })

  current <- reactive({
    q <- queue()
    if (!nrow(q)) return(NULL)
    q[min(idx(), nrow(q)), ]
  })

  # fill the form with this extractor's saved values (or NR)
  observe({
    row <- current()
    if (is.null(row)) return()
    saved <- my_extractions()
    saved <- if (!is.null(saved)) saved[saved$row_id == as.character(row$row_id), , drop = FALSE] else NULL
    have <- !is.null(saved) && nrow(saved) == 1
    for (x in VARIABLES) {
      val <- if (have && x$name %in% names(saved)) saved[[x$name]][1] else NA
      if (x$numeric) {
        updateNumericInput(session, input_id(x$name), value = suppressWarnings(as.numeric(val)))
      } else {
        updateSelectInput(session, input_id(x$name), selected = if (is.na(val) || val == "") "NR" else val)
      }
    }
    updateCheckboxInput(session, "e_flag", value = have && isTRUE(saved$flag[1] == "TRUE"))
    updateTextAreaInput(session, "e_notes", value = if (have) saved$notes[1] else "")
  })

  output$e_context <- renderUI({
    q <- queue()
    if (!nrow(q)) return(p("No included reports yet: screen first."))
    row <- current()
    done <- if (is.null(my_extractions())) 0 else sum(my_extractions()$row_id %in% as.character(q$row_id))
    is_done <- !is.null(my_extractions()) && as.character(row$row_id) %in% my_extractions()$row_id
    tagList(
      p(strong("Report "), min(idx(), nrow(q)), " of ", nrow(q),
        strong(" | row "), row$row_id, strong(" | "), row$stratum,
        if (is_done) span(style = "color:#2e7d32;", " | saved") else span(style = "color:#c62828;", " | not saved")),
      p(strong("Done by "), if (nzchar(input$who)) input$who else "(choose extractor)", ": ", done, " of ", nrow(q))
    )
  })

  output$e_report <- renderUI({
    row <- current()
    if (is.null(row)) return(NULL)
    row$imaging_result
  })

  go <- function(i) { q <- queue(); if (nrow(q)) idx(max(1, min(i, nrow(q)))) }
  observeEvent(input$e_prev, go(idx() - 1))
  observeEvent(input$e_next, go(idx() + 1))
  observeEvent(input$e_jump, go(input$e_goto))

  observeEvent(input$e_reset, {
    for (x in VARIABLES) {
      if (x$numeric) updateNumericInput(session, input_id(x$name), value = NA)
      else updateSelectInput(session, input_id(x$name), selected = "NR")
    }
  })

  observeEvent(input$e_save, {
    if (!nzchar(input$who)) { showNotification("Choose the extractor first.", type = "error"); return() }
    row <- current()
    if (is.null(row)) return()

    values <- list()
    for (x in VARIABLES) {
      val <- input[[input_id(x$name)]]
      if (x$numeric) {
        mm <- suppressWarnings(as.numeric(val))
        values[[x$name]] <- if (is.na(mm)) "NR" else format(mm)
        values[[sub("_mm$", "_cm", x$name)]] <- if (is.na(mm)) "NR" else format(mm / 10)
      } else {
        values[[x$name]] <- val
      }
    }

    out <- data.frame(`#` = row$row_id, report_num = row$genc_id, report_whole = row$imaging_result,
                      check.names = FALSE, stringsAsFactors = FALSE)
    for (col in SHEET_COLUMNS) out[[col]] <- values[[col]]
    out$row_id <- row$row_id
    out$stratum <- row$stratum
    out$hospital_num <- row$hospital_num
    out$extractor <- input$who
    out$completed_at <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
    out$flag <- isTRUE(input$e_flag)
    out$notes <- input$e_notes

    upsert(extraction_file(input$who), out)
    showNotification(paste("Saved row", row$row_id, "for", input$who), type = "message", duration = 2)
    go(idx() + 1)
  })
}

shinyApp(ui, server)
