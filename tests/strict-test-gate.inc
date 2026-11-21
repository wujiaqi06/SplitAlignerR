# Sourced by tests/testthat.R. The .inc suffix prevents R CMD check from also
# executing this definition-only file as a separate R test script.
# Uses raw events and the reporter's complete diagnostic stacks, not the
# lossy as.data.frame(testthat_results) error column. No new package dependency.
splitaligner_assert_raw_test_events <- function(results, reporter_problems = list(),
                                                reporter_warnings = list(),
                                                escaped_warnings = list()) {
  if (!is.list(results) || !length(results)) {
    stop("STRICT_RAW_EVENTS FAIL: no test results were returned.", call. = FALSE)
  }
  events <- list()
  for (test in results) {
    if (!is.list(test) || !is.list(test$results)) {
      stop("STRICT_RAW_EVENTS FAIL: malformed raw test results.", call. = FALSE)
    }
    events <- c(events, test$results)
  }
  if (!length(events)) {
    stop("STRICT_RAW_EVENTS FAIL: no expectation events were returned.", call. = FALSE)
  }
  event_is_bad <- function(event) {
    if (inherits(event, "expectation_skip")) return(FALSE)
    inherits(event, c("expectation_failure", "expectation_error",
                      "expectation_warning", "error", "warning"))
  }
  bad <- vapply(events, event_is_bad, logical(1))
  known <- vapply(events, function(event)
    inherits(event, c("expectation_success", "expectation_skip")) ||
      event_is_bad(event), logical(1))
  skips <- sum(vapply(events, inherits, logical(1), what = "expectation_skip"))
  # Reporter stacks also retain diagnostics emitted outside test_that(),
  # which a version-specific per-test ListReporter may omit from results.
  counts <- c(raw_bad = sum(bad), unknown = sum(!known),
              reporter_problems = length(reporter_problems),
              reporter_warnings = length(reporter_warnings),
              escaped_warnings = length(escaped_warnings))
  if (any(counts > 0L)) {
    stop(paste0("STRICT_RAW_EVENTS FAIL: ",
      paste(paste(names(counts), counts, sep = "="), collapse = ", "),
      "; allowed skip events=", skips, "."), call. = FALSE)
  }
  cat("STRICT_RAW_EVENTS PASS: ", length(events), " raw events; ", skips,
      " skip events retained; no failures, errors, or unexpected warnings.\n", sep = "")
  invisible(TRUE)
}
