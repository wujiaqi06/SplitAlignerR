#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("result directory is required", call. = FALSE)
result_dir <- normalizePath(args[[1L]], mustWork = TRUE)
rss_lines <- readLines(
  file.path(result_dir, "BSTAR_CHURN_RSS.raw.txt"), warn = FALSE
)
peak <- sub(
  "^peak_rss_bytes=", "",
  grep("^peak_rss_bytes=", rss_lines, value = TRUE)
)
if (length(peak) != 1L || !grepl("^[0-9]+$", peak)) {
  stop("Measured B* peak RSS is unavailable.", call. = FALSE)
}
path <- file.path(result_dir, "ARCH000A_BSTAR_CHURN_RESULTS.csv")
table <- utils::read.csv(
  path, stringsAsFactors = FALSE, check.names = FALSE,
  na.strings = "NOT_MEASURED"
)
table$peak_rss_bytes[table$evidence_class == "MEASURED_ENGINEERING_STRESS"] <-
  as.numeric(peak)
utils::write.csv(
  table, path, row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)
