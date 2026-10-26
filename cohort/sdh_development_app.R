# =====================================================================
# SDH development (training) set: extraction app
#
# The development reports are the cohort reports that were used to build
# the NLP (build_cohort.R removes them from the validation cohort and writes
# them to sdh_development_reports.csv). Extracting them here with the same
# variables and coding guide gives one training set for both the NLP and
# the LLMs. No screening: every development report is extracted; one that
# turns out not to be usable is marked "Not usable" with a reason.
#
# Files written to the working folder:
#   sdh_dev_extraction_<extractor>.csv  one file per extractor; the same
#                                       columns as the NLP validation sheet
#                                       (+ usable / not_usable_reason)
#
# Kept apart from the validation files (sdh_extraction_*.csv): different
# row_ids, different file names.
#
# Run: source("sdh_development_app.R")   (or open it and click Run App)
# =====================================================================

library(shiny)
library(dplyr)


# ---------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------

EXTRACTORS <- c("Student 1", "Student 2", "Student 3", "Student 4", "Student 5",
                "Radiologist 1", "Radiologist 2")

# the folder that holds the development file and every saved file
DATA_DIR <- getwd()

DEVELOPMENT_FILE <- file.path(DATA_DIR, "sdh_development_reports.csv")
extraction_file <- function(who) file.path(DATA_DIR, paste0("sdh_dev_extraction_", gsub("[^A-Za-z0-9]", "_", who), ".csv"))

NOT_USABLE_REASONS <- c(
  "Post-operative report",
  "No SDH described in the report",
  "Not a head CT / report incomplete",
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
              "Opacification NS", "Retention cyst", "Fluid", "Hemorrhage")

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
    v("parafalcine_location", "Falx", c("NR", "Anterior", "Medial", "Posterior", "Anterior/medial", "Medial/posterior", "Anterior/posterior"), "Location"),
    v("parafalcine_thickness_mm", "Falx", label = "Thickness (mm)", numeric = TRUE),
    v("parafalcine_density", "Falx", CDENS, "Density"),
    v("parafalcine_acuity", "Falx", ACUITY, "Acuity"),

    v("tentorium_hematoma", "Tentorium", COMPART, "Tentorium SDH"),
    v("tentorium_description", "Tentorium", DESC, "Description"),
    v("tentorium_thickness_mm", "Tentorium", label = "Thickness (mm)", numeric = TRUE),
    v("tentorium_density", "Tentorium", CDENS, "Density"),
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

if (!file.exists(DEVELOPMENT_FILE)) stop("Development file not found: ", DEVELOPMENT_FILE,
                                         " (run build_cohort.R first)")
dat <- read.csv(DEVELOPMENT_FILE, stringsAsFactors = FALSE, check.names = FALSE) %>%
  arrange(stratum, dev_order)
cat("Development reports:", nrow(dat), " | saving to", DATA_DIR, "\n")

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
    .ctx { background:#fff4e5; padding:10px 14px; border-radius:6px; border:1px solid #f0cf9c; margin-bottom:10px; }
    .well { padding:10px 14px; margin-bottom:10px; }
    .well h4 { margin-top:0; color:#1B3A5C; }
    .form-group { margin-bottom:6px; }
  "))),
  titlePanel("SDH development (training) set: extraction"),
  fluidRow(column(4, selectInput("who", "Extractor (choose before you start; saved with every report)",
                                 choices = c("Choose..." = "", EXTRACTORS)))),
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
          checkboxInput("e_not_usable", "Not usable for the training set"),
          selectInput("e_nu_reason", "Reason (if not usable)", choices = NOT_USABLE_REASONS, width = "100%"),
          textInput("e_nu_other", "Other reason (if Other)", width = "100%"),
          fluidRow(
            column(6, actionButton("e_save_stay", "Save and stay", class = "btn-primary", width = "100%")),
            column(6, actionButton("e_save", "Save and next", class = "btn-primary", width = "100%"))
          ),
          br(), br(),
          actionButton("e_reset", "Reset all to NR", width = "100%")
        )
      )
    )
  )
)


# ---------------------------------------------------------------------
# SERVER
# ---------------------------------------------------------------------

server <- function(input, output, session) {

  # bumped AFTER an extraction is written, so saved answers are re-read
  # only once the file holds them
  saved_version <- reactiveVal(0)

  idx <- reactiveVal(1)
  queue <- reactive({
    if (input$e_stratum == "both") dat else filter(dat, stratum == input$e_stratum)
  })
  observeEvent(input$e_stratum, idx(1))

  my_extractions <- reactive({
    saved_version()
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
    updateCheckboxInput(session, "e_not_usable", value = have && isTRUE(saved$usable[1] == "FALSE"))
    updateTextInput(session, "e_nu_other", value = "")
  })

  output$e_context <- renderUI({
    q <- queue()
    if (!nrow(q)) return(p("No development reports in this stratum."))
    row <- current()
    mine <- my_extractions()
    done <- if (is.null(mine)) 0 else sum(mine$row_id %in% as.character(q$row_id))
    is_done <- !is.null(mine) && as.character(row$row_id) %in% mine$row_id
    tagList(
      p(strong("DEVELOPMENT SET"), strong(" | report "), min(idx(), nrow(q)), " of ", nrow(q),
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

  # save this report; "Save and next" then moves on, "Save and stay" does not
  save_current <- function(advance) {
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
    out$set <- "development"
    out$stratum <- row$stratum
    out$hospital_num <- row$hospital_num
    out$extractor <- input$who
    out$completed_at <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
    out$flag <- isTRUE(input$e_flag)
    out$notes <- input$e_notes
    out$usable <- !isTRUE(input$e_not_usable)
    out$not_usable_reason <- if (isTRUE(input$e_not_usable)) {
      if (input$e_nu_reason == "Other") paste("Other:", input$e_nu_other) else input$e_nu_reason
    } else ""

    upsert(extraction_file(input$who), out)
    # check it is really in the file before moving on
    check <- read_or_empty(extraction_file(input$who))
    if (is.null(check) || !(as.character(row$row_id) %in% check$row_id)) {
      showNotification(paste("NOT saved - could not write", extraction_file(input$who)), type = "error", duration = NULL)
      return()
    }
    saved_version(saved_version() + 1)
    showNotification(paste("Saved row", row$row_id, "for", input$who, "to", basename(extraction_file(input$who))),
                     type = "message", duration = 3)
    if (advance) go(idx() + 1)
  }

  observeEvent(input$e_save, save_current(advance = TRUE))
  observeEvent(input$e_save_stay, save_current(advance = FALSE))
}

shinyApp(ui, server)
