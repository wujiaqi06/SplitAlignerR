library(testthat)
library(SplitAlignerR)

# Keep the ordinary check report, but do not trust its summarizer as the final
# acceptance gate. Some testthat versions count an error only when it is the
# last event in a test, so a later warning can conceal it from all_passed().
source("strict-test-gate.inc", local = TRUE)
strict_reporter <- testthat::CheckReporter$new()
strict_escaped_warnings <- list()
strict_results <- withCallingHandlers(
  test_check("SplitAlignerR", reporter = strict_reporter,
             stop_on_failure = FALSE, stop_on_warning = FALSE),
  warning = function(w) {
    strict_escaped_warnings[[length(strict_escaped_warnings) + 1L]] <<- w
    # Do not suppress the original warning.
  }
)
splitaligner_assert_raw_test_events(
  strict_results,
  reporter_problems = strict_reporter$problems$as_list(),
  reporter_warnings = strict_reporter$warnings$as_list(),
  escaped_warnings = strict_escaped_warnings
)
