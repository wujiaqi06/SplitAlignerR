#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (!length(args)) stop("ENGINE001 benchmark mode is required.", call. = FALSE)
mode <- args[[1L]]

if (mode == "packed") {
  if (length(args) != 6L) stop("packed mode requires five arguments.", call. = FALSE)
  source("dev/ENGINE001/prototype/packed_schema_comparison.R")
  e1_run_schema_comparison(args[[2L]], args[[3L]], args[[4L]],
                           args[[5L]], args[[6L]])
} else if (mode == "matrix") {
  if (length(args) != 6L) stop("matrix mode requires five arguments.", call. = FALSE)
  source("dev/ENGINE001/prototype/matrix_layout_benchmark.R")
  e1_run_matrix_case(args[[2L]], as.integer(args[[3L]]),
                     as.integer(args[[4L]]), args[[5L]], args[[6L]])
} else if (mode == "manifest") {
  if (length(args) != 2L) stop("manifest mode requires output.", call. = FALSE)
  source("dev/ENGINE001/prototype/manifest_validation.R")
  e1_run_manifest_validation(args[[2L]])
} else if (mode == "ownership") {
  if (length(args) != 2L) stop("ownership mode requires output.", call. = FALSE)
  source("dev/ENGINE001/prototype/ownership_lifecycle_sketch.R")
  e1_run_ownership_sketch(args[[2L]])
} else if (mode == "aggregate") {
  if (length(args) != 4L) stop("aggregate mode requires result, RSS and output dirs.",
                               call. = FALSE)
  result_dir <- args[[2L]]
  rss_dir <- args[[3L]]
  output_dir <- args[[4L]]
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  packed <- read.csv(file.path(result_dir, "packed_schema.csv"),
                     check.names = FALSE)
  packed_rss <- readLines(file.path(rss_dir, "packed_schema.rss.txt"))
  packed$peak_rss_bytes <- as.numeric(sub(
    "^peak_rss_bytes=", "", packed_rss[startsWith(packed_rss, "peak_rss_bytes=")]
  ))
  write.csv(packed, file.path(output_dir, "PACKED_SCHEMA_RESULTS.csv"),
            row.names = FALSE, quote = TRUE)
  matrix_files <- list.files(result_dir, pattern = "^matrix_.*[.]csv$",
                             full.names = TRUE)
  matrix_rows <- lapply(matrix_files, function(path) {
    row <- read.csv(path, check.names = FALSE)
    label <- sub("[.]csv$", "", basename(path))
    rss <- readLines(file.path(rss_dir, paste0(label, ".rss.txt")))
    row$peak_rss_bytes <- as.numeric(sub(
      "^peak_rss_bytes=", "", rss[startsWith(rss, "peak_rss_bytes=")]
    ))
    row
  })
  matrix <- do.call(rbind, matrix_rows)
  matrix <- matrix[order(matrix$rows, matrix$layout), , drop = FALSE]
  write.csv(matrix, file.path(output_dir, "MATRIX_LAYOUT_RESULTS.csv"),
            row.names = FALSE, quote = TRUE)
} else {
  stop(sprintf("Unknown ENGINE001 benchmark mode: %s", mode), call. = FALSE)
}
