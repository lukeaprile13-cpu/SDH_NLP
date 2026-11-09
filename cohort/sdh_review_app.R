# ============================================================================
# SDH NLP - review the disagreements (development set)
#
# Shows every report x variable where the NLP and the extractor disagree, one
# at a time, with the whole report and the relevant sentences highlighted.
# For each one you decide whose error it is:
#
#   NLP wrong        - the extractor is right; the NLP needs a rule
#   Human wrong      - the NLP is right; the extraction was a mistake
#   Both wrong       - neither has the right value (write it in "Should be")
#   Both defensible  - the coding rules allow either; a rule decision is needed
#   Unsure           - ask the radiologist
#
# For the NLP-wrong ones, type the sentence with anything identifying removed
# into "De-identified sentence": the export file holds only those sentences
# (no report numbers, no report text), so it can be sent out.
#
# Reads  (searched for under the home folder, "backups" folders skipped)
#   <PREFIX>_sentences_to_check.csv   from NLP_v5.ipynb
#   sdh_dev_extraction_<who>.csv      for the whole report text
# Writes (in the same folder as the sentences file)
#   <PREFIX>_review.csv               your decisions, saved after every one
#   <PREFIX>_to_send.csv              the export (button): de-identified only
#   <PREFIX>_review_summary.csv       verdict counts per variable (button)
#
# Run: shiny::runApp("sdh_review_app.R")
# ============================================================================

library(shiny)

PREFIX <- "SDH_dev_Student_1"
EXTRACTION_NAME <- "sdh_dev_extraction_Student_1.csv"
SEARCH_FOLDER <- "~"

VERDICTS <- c("NLP wrong", "Human wrong", "Both wrong", "Both defensible", "Unsure")

find_file <- function(name) {
  if (file.exists(name)) return(normalizePath(name))
  found <- list.files(path.expand(SEARCH_FOLDER), pattern = paste0("^", gsub("\\.", "\\\\.", name), "$"),
                      recursive = TRUE, full.names = TRUE)
  found <- found[!grepl("/backups/", found)]
  if (!length(found)) stop(name, " was not found under ", SEARCH_FOLDER)
  found[order(file.mtime(found), decreasing = TRUE)][1]
}

read_chr <- function(path) {
  read.csv(path, stringsAsFactors = FALSE, check.names = FALSE, colClasses = "character",
           na.strings = character(0), encoding = "UTF-8", fileEncoding = "UTF-8-BOM")
}

SENTENCES_FILE <- find_file(paste0(PREFIX, "_sentences_to_check.csv"))
OUT_DIR <- dirname(SENTENCES_FILE)
REVIEW_FILE <- file.path(OUT_DIR, paste0(PREFIX, "_review.csv"))
SEND_FILE <- file.path(OUT_DIR, paste0(PREFIX, "_to_send.csv"))
SUMMARY_FILE <- file.path(OUT_DIR, paste0(PREFIX, "_review_summary.csv"))

items <- read_chr(SENTENCES_FILE)
ID1 <- names(items)[1]
ID2 <- names(items)[2]
items$key <- paste(items[[ID1]], items[[ID2]], items$variable, sep = "|")

# which kind of disagreement: the NLP's errors are mostly where the NLP has
# NR or a different value; where the human has NR it is mostly a human miss
is_nr <- function(x) toupper(trimws(x)) %in% c("", "NR", "NA", "NAN", "NONE")
items$kind <- ifelse(is_nr(items$nlp), "NLP has NR",
                     ifelse(is_nr(items$human), "Human has NR", "Different values"))
KINDS <- c("NLP has NR (check first)" = "NLP has NR",
           "Different values" = "Different values",
           "Human has NR (mostly human misses)" = "Human has NR")

# whole report text, by the two report numbers
reports <- tryCatch({
  ex <- read_chr(find_file(EXTRACTION_NAME))
  setNames(ex$report_whole, paste(ex[[1]], ex[[2]], sep = "|"))
}, error = function(e) {
  message("No extraction file: only the sentences are shown (", conditionMessage(e), ")")
  character(0)
})

cat(nrow(items), "disagreements from", SENTENCES_FILE, "\nSaving decisions to", REVIEW_FILE, "\n")

REVIEW_COLUMNS <- c("key", ID1, ID2, "variable", "human", "nlp", "verdict", "should_be",
                    "deid_sentence", "comment", "reviewed_at")

read_review <- function() {
  if (!file.exists(REVIEW_FILE)) {
    return(setNames(data.frame(matrix(character(0), 0, length(REVIEW_COLUMNS)), stringsAsFactors = FALSE),
                    REVIEW_COLUMNS))
  }
  read_chr(REVIEW_FILE)
}

# --- highlighting ------------------------------------------------------------

esc <- function(x) {
  x <- gsub("&", "&amp;", x, fixed = TRUE)
  x <- gsub("<", "&lt;", x, fixed = TRUE)
  gsub(">", "&gt;", x, fixed = TRUE)
}

# the whole report with the relevant sentences marked
report_html <- function(report, sentences) {
  text <- esc(gsub("\\s+", " ", report))
  for (s in unique(strsplit(sentences, "\n", fixed = TRUE)[[1]])) {
    s <- esc(trimws(s))
    if (nchar(s) < 4 || startsWith(s, "(no sentence")) next
    text <- sub(s, paste0("<mark>", s, "</mark>"), text, fixed = TRUE)
  }
  HTML(text)
}

pretty_variable <- function(v) gsub("_+", " ", trimws(v))

# --- UI ----------------------------------------------------------------------

ui <- fluidPage(
  tags$head(tags$style(HTML("
    .report-box { background:#fafafa; border:1px solid #ddd; border-radius:6px; padding:12px;
                  max-height:420px; overflow-y:auto; line-height:1.55; font-size:14px; white-space:normal; }
    mark { background:#ffe58a; padding:1px 0; }
    .values td { padding:4px 14px 4px 0; font-size:16px; }
    .big { font-size:20px; font-weight:600; }
    .sent { background:#fff8dc; border-left:4px solid #e0b000; padding:6px 10px; margin-bottom:6px; }
    .done { color:#2e7d32; font-weight:600; }
    .todo { color:#b26a00; font-weight:600; }
  ")),
  tags$script(HTML("
    // keys 1-5 pick a verdict, Enter saves and goes to the next (not while typing)
    document.addEventListener('keydown', function (e) {
      var t = e.target.tagName;
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') return;
      if (e.key >= '1' && e.key <= '5') {
        var radios = document.querySelectorAll('input[name=verdict]');
        var r = radios[parseInt(e.key) - 1];
        if (r) { r.click(); }
      }
      if (e.key === 'Enter') { document.getElementById('save_next').click(); }
      if (e.key === 'ArrowRight') { document.getElementById('next').click(); }
      if (e.key === 'ArrowLeft') { document.getElementById('prev').click(); }
    });
  "))),
  titlePanel("SDH NLP - review the disagreements"),
  sidebarLayout(
    sidebarPanel(width = 3,
      selectInput("var_filter", "Variable", choices = NULL),
      checkboxGroupInput("kinds", "Kind of disagreement", choices = KINDS, selected = KINDS),
      radioButtons("show", "Show", c("Not reviewed yet", "All", "Reviewed"), selected = "Not reviewed yet"),
      htmlOutput("progress"),
      hr(),
      actionButton("export", "Export de-identified sentences", class = "btn-primary", width = "100%"),
      br(), br(),
      actionButton("summary", "Write verdict summary", width = "100%"),
      br(), br(),
      helpText("Keys: 1-5 pick the verdict, Enter = save and next, arrows = previous / next."),
      helpText("To change a decision: Show 'Reviewed' or 'All', find it, and save again."),
      helpText("Decisions are saved to the review file after every save, so you can stop and come back.")
    ),
    mainPanel(width = 9,
      fluidRow(
        column(8, htmlOutput("header")),
        column(4, style = "text-align:right; padding-top:10px;",
               actionButton("prev", "< Previous"), actionButton("next", "Next >"))
      ),
      hr(),
      fluidRow(
        column(7,
          h4("Report"),
          htmlOutput("report"),
          h4("Sentences that mention it"),
          htmlOutput("sentences")
        ),
        column(5,
          radioButtons("verdict", "Whose error?", choices = VERDICTS, selected = character(0)),
          textInput("should_be", "Should be (the right value)", width = "100%"),
          textAreaInput("deid", "De-identified sentence (for NLP wrong / defensible / unsure)",
                        rows = 4, width = "100%",
                        placeholder = "Copy the failing sentence here and remove names, dates, places, numbers that identify"),
          actionButton("copy_sent", "Copy the highlighted sentences in", class = "btn-xs"),
          br(), br(),
          textAreaInput("comment", "Comment", rows = 2, width = "100%"),
          actionButton("save_next", "Save and next", class = "btn-success"),
          htmlOutput("saved_note")
        )
      )
    )
  )
)

# --- server ------------------------------------------------------------------

server <- function(input, output, session) {

  review <- reactiveVal(read_review())
  pos <- reactiveVal(1)

  observe({
    counts <- table(items$variable)
    counts <- counts[order(-counts, names(counts))]
    choices <- c(setNames("(all)", paste0("All variables (", nrow(items), ")")),
                 setNames(names(counts), paste0(pretty_variable(names(counts)), " (", counts, ")")))
    updateSelectInput(session, "var_filter", choices = choices)
  })

  # the items in the current filter, in file order
  shown <- reactive({
    req(input$var_filter)
    x <- items
    if (input$var_filter != "(all)") x <- x[x$variable == input$var_filter, , drop = FALSE]
    x <- x[x$kind %in% input$kinds, , drop = FALSE]
    done <- x$key %in% review()$key
    if (input$show == "Not reviewed yet") x <- x[!done, , drop = FALSE]
    if (input$show == "Reviewed") x <- x[done, , drop = FALSE]
    x
  })

  # back to the first one when the filter changes
  observeEvent(list(input$var_filter, input$show, input$kinds), pos(1), ignoreInit = TRUE)

  current <- reactive({
    x <- shown()
    if (!nrow(x)) return(NULL)
    x[min(pos(), nrow(x)), , drop = FALSE]
  })

  # fill the form with what was saved for this one (or empty)
  observeEvent(current(), {
    it <- current()
    saved <- if (is.null(it)) NULL else review()[review()$key == it$key, , drop = FALSE]
    have <- !is.null(saved) && nrow(saved) > 0
    updateRadioButtons(session, "verdict", selected = if (have && nzchar(saved$verdict[1])) saved$verdict[1] else character(0))
    updateTextInput(session, "should_be", value = if (have) saved$should_be[1] else "")
    updateTextAreaInput(session, "deid", value = if (have) saved$deid_sentence[1] else "")
    updateTextAreaInput(session, "comment", value = if (have) saved$comment[1] else "")
    output$saved_note <- renderUI(if (have) span(class = "done", paste("Saved", saved$reviewed_at[1])) else NULL)
  }, ignoreNULL = FALSE)

  output$progress <- renderUI({
    done <- sum(items$key %in% review()$key)
    x <- if (is.null(input$var_filter) || input$var_filter == "(all)") items else items[items$variable == input$var_filter, ]
    done_here <- sum(x$key %in% review()$key)
    HTML(paste0("<p><b>All:</b> ", done, " / ", nrow(items), " reviewed</p>",
                "<p><b>This variable:</b> ", done_here, " / ", nrow(x), "</p>",
                "<p><b>Showing:</b> ", if (nrow(shown())) paste(min(pos(), nrow(shown())), "of", nrow(shown())) else "none", "</p>"))
  })

  output$header <- renderUI({
    it <- current()
    if (is.null(it)) return(h3(class = "done", "Nothing left here - pick another variable or show 'All'."))
    done <- it$key %in% review()$key
    tagList(
      div(class = "big", pretty_variable(it$variable)),
      tags$table(class = "values", tags$tr(
        tags$td(HTML(paste0("Report <b>", esc(it[[ID1]]), "</b>"))),
        tags$td(HTML(paste0("Human: <b>", esc(it$human), "</b>"))),
        tags$td(HTML(paste0("NLP: <b>", esc(it$nlp), "</b>"))),
        tags$td(em(it$kind)),
        tags$td(span(class = if (done) "done" else "todo", if (done) "reviewed" else "not reviewed"))
      ))
    )
  })

  output$report <- renderUI({
    it <- current()
    if (is.null(it)) return(NULL)
    text <- reports[paste(it[[ID1]], it[[ID2]], sep = "|")]
    if (is.na(text)) return(div(class = "report-box", em("(report text not found - see the sentences below)")))
    div(class = "report-box", report_html(text, it$sentences))
  })

  output$sentences <- renderUI({
    it <- current()
    if (is.null(it)) return(NULL)
    lapply(strsplit(it$sentences, "\n", fixed = TRUE)[[1]], function(s) div(class = "sent", s))
  })

  observeEvent(input$copy_sent, {
    it <- current()
    if (!is.null(it)) updateTextAreaInput(session, "deid", value = it$sentences)
  })

  save_current <- function() {
    it <- current()
    if (is.null(it)) return()
    if (is.null(input$verdict) || !nzchar(input$verdict)) {
      showNotification("Pick whose error it is first.", type = "warning")
      return()
    }
    row <- data.frame(key = it$key, a = it[[ID1]], b = it[[ID2]], variable = it$variable,
                      human = it$human, nlp = it$nlp, verdict = input$verdict,
                      should_be = input$should_be, deid_sentence = input$deid,
                      comment = input$comment, reviewed_at = format(Sys.time(), "%Y-%m-%d %H:%M:%S"),
                      stringsAsFactors = FALSE)
    names(row) <- REVIEW_COLUMNS
    old <- review()
    new <- rbind(old[old$key != it$key, REVIEW_COLUMNS, drop = FALSE], row)
    write.csv(new, REVIEW_FILE, row.names = FALSE, na = "", fileEncoding = "UTF-8")
    check <- read_review()
    if (!(it$key %in% check$key)) {
      showNotification(paste("NOT saved - could not write", REVIEW_FILE), type = "error", duration = NULL)
      return()
    }
    key <- it$key
    review(check)
    showNotification("Saved", duration = 1.5)
    # in "Not reviewed yet" the saved one drops out, so the same position is
    # already the next one; otherwise move one on
    x <- shown()
    if (input$show == "Not reviewed yet") {
      pos(min(pos(), max(1, nrow(x))))
    } else {
      pos(min(match(key, x$key) + 1, nrow(x)))
    }
  }

  observeEvent(input$save_next, save_current())
  observeEvent(input$`next`, pos(min(pos() + 1, max(1, nrow(shown())))))
  observeEvent(input$prev, pos(max(pos() - 1, 1)))

  observeEvent(input$export, {
    r <- review()
    r <- r[r$verdict %in% c("NLP wrong", "Both wrong", "Both defensible", "Unsure"), , drop = FALSE]
    if (!nrow(r)) {
      showNotification("No NLP-wrong / defensible / unsure decisions yet.", type = "warning")
      return()
    }
    missing <- sum(!nzchar(trimws(r$deid_sentence)))
    out <- r[order(r$variable), c("variable", "human", "nlp", "verdict", "should_be", "deid_sentence", "comment")]
    out <- out[nzchar(trimws(out$deid_sentence)), , drop = FALSE]
    write.csv(out, SEND_FILE, row.names = FALSE, na = "", fileEncoding = "UTF-8")
    showModal(modalDialog(
      title = "Exported",
      p(nrow(out), "rows written to", code(SEND_FILE)),
      if (missing) p(class = "todo", missing, "decision(s) left out because they have no de-identified sentence yet.") else NULL,
      p("It has no report numbers and no report text - only the sentences you typed. Read it once more before sending."),
      easyClose = TRUE
    ))
  })

  observeEvent(input$summary, {
    r <- review()
    if (!nrow(r)) {
      showNotification("Nothing reviewed yet.", type = "warning")
      return()
    }
    tab <- as.data.frame.matrix(table(r$variable, factor(r$verdict, levels = VERDICTS)))
    tab <- cbind(variable = rownames(tab), tab, reviewed = rowSums(tab),
                 disagreements = as.integer(table(items$variable)[rownames(tab)]))
    all <- data.frame(variable = "ALL", t(colSums(tab[, -1])), check.names = FALSE)
    all$disagreements <- nrow(items)
    tab <- rbind(tab, all)
    write.csv(tab, SUMMARY_FILE, row.names = FALSE)
    showModal(modalDialog(title = paste("Summary written to", SUMMARY_FILE),
                          renderTable(tab[tab$variable == "ALL", , drop = FALSE]), easyClose = TRUE))
  })
}

shinyApp(ui, server)
