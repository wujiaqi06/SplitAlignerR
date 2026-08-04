#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: fix001a_testthat.R <installed-library> <output>", call. = FALSE)
}
.libPaths(c(args[[1L]], .libPaths()))
Sys.setenv(NOT_CRAN = "true")
library(testthat)
library(SplitAlignerR)

test_root <- system.file("tests", "testthat", package = "SplitAlignerR")
if (!nzchar(test_root) || !dir.exists(test_root)) {
  stop("installed testthat directory is missing", call. = FALSE)
}

started <- proc.time()[["elapsed"]]
result <- testthat::test_dir(
  test_root,
  reporter = testthat::SummaryReporter$new(),
  package = "SplitAlignerR",
  stop_on_failure = TRUE,
  stop_on_warning = TRUE,
  load_package = "installed"
)
elapsed <- unname(proc.time()[["elapsed"]] - started)

failed <- sum(vapply(result, function(item) {
  sum(vapply(item$results, inherits, logical(1), "expectation_failure"))
}, integer(1)))
errors <- sum(vapply(result, function(item) {
  sum(vapply(item$results, inherits, logical(1), "expectation_error"))
}, integer(1)))
skips <- sum(vapply(result, function(item) {
  sum(vapply(item$results, inherits, logical(1), "expectation_skip"))
}, integer(1)))
expectations <- sum(vapply(result, function(item) length(item$results), integer(1)))

lines <- c(
  "status=PASS",
  paste0("files=", length(result)),
  paste0("expectations=", expectations),
  paste0("failures=", failed),
  paste0("errors=", errors),
  paste0("skips=", skips),
  paste0("elapsed_seconds=", sprintf("%.6f", elapsed))
)
writeLines(lines, args[[2L]], useBytes = TRUE)
cat(paste(lines, collapse = "\n"), "\n", sep = "")
