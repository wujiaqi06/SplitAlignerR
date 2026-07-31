#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
source(file.path(script_dir, "arch000_common.R"))
suppressPackageStartupMessages(library(SplitAlignerR))

input_dir <- Sys.getenv("ARCH000_2275_DIR", "")
output <- Sys.getenv("ARCH000_SCANNER_RESULT", "")
if (!nzchar(input_dir) || !dir.exists(input_dir)) {
  arch_stop("Set ARCH000_2275_DIR to the frozen 2,275-gene input directory.")
}
if (!nzchar(output)) arch_stop("Set ARCH000_SCANNER_RESULT.")

lines <- c("input\trecords\tmismatches\tstatus")
for (name in c("fix.2275genes.nwk", "free.2275genes.nwk")) {
  path <- file.path(input_dir, name)
  mismatch <- 0L
  records <- arch_iterate_records(path, function(record, index) {
    candidate <- arch_scan_tips(record$newick)
    baseline <- arch_complete_parse_tips(record$newick)
    if (!identical(candidate, baseline)) mismatch <<- mismatch + 1L
  })
  lines <- c(lines, paste(
    name, records, mismatch, if (mismatch == 0L) "PASS" else "FAIL", sep = "\t"
  ))
}
writeLines(lines, output, useBytes = TRUE)
if (any(grepl("\tFAIL$", lines))) quit(status = 1L)
