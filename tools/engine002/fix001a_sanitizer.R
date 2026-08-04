#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: fix001a_sanitizer.R <installed-library> <output>", call. = FALSE)
}
.libPaths(c(args[[1L]], .libPaths()))
Sys.setenv(NOT_CRAN = "true")
library(SplitAlignerR)
library(testthat)

test_root <- system.file("tests", "testthat", package = "SplitAlignerR")
files <- file.path(test_root, c(
  "test-engine002-codec.R",
  "test-engine002-stores.R",
  "test-engine002-fix001.R",
  "test-engine002-fix001a.R",
  "test-engine002-fix001b.R"
))
if (any(!file.exists(files))) {
  stop("installed ENGINE002 sanitizer tests are incomplete", call. = FALSE)
}

started <- proc.time()[["elapsed"]]
for (path in files) {
  testthat::test_file(
    path,
    reporter = testthat::SummaryReporter$new(),
    package = "SplitAlignerR",
    stop_on_failure = TRUE,
    stop_on_warning = TRUE,
    load_package = "installed"
  )
}

# Additional finalizer churn while ASan/UBSan instruments the package DSO.
rb <- function(x) as.raw(x)
authority <- SplitAlignerR:::.engine002_authority(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)
record <- SplitAlignerR:::.engine002_plan_encode(
  authority, 0, rb(3L), c(2L, 2L, 1L, 1L, 1L),
  list(rb(1L), rb(1L), NULL, NULL, NULL)
)
for (i in seq_len(250L)) {
  local({
    store <- SplitAlignerR:::.engine002_memory_store(authority, 1)
    SplitAlignerR:::cpp_engine002_store_insert(store, record)
    SplitAlignerR:::cpp_engine002_store_finalize(store, "", "")
    pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(store, 0, rb(3L))
    invisible(NULL)
  })
  if (i %% 10L == 0L) gc()
}
gc()
elapsed <- unname(proc.time()[["elapsed"]] - started)

lines <- c(
  "status=PASS",
  "classification=PASS",
  "boundary=Rcpp package shared library under ASan+UBSan",
  "detect_leaks=disabled because the host R runtime is not sanitizer-built",
  "codec=PASS",
  "direct_view=PASS",
  "memory_store=PASS",
  "streaming_disk_builder=PASS",
  "disk_reopen=PASS",
  "LRU_and_oversized_scratch=PASS",
  "fault_cleanup=PASS",
  "incremental_sha_and_targeted_aggregate=PASS",
  "constant_hash=PASS",
  "XPtr_finalizer_GC=PASS",
  "close_and_read_after_close=PASS",
  paste0("elapsed_seconds=", sprintf("%.6f", elapsed))
)
writeLines(lines, args[[2L]], useBytes = TRUE)
cat(paste(lines, collapse = "\n"), "\n", sep = "")
