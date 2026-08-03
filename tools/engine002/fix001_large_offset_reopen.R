#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4L) {
  stop(
    "usage: fix001_large_offset_reopen.R <library> <manifest> <count> <output>",
    call. = FALSE
  )
}
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

MiB <- 1024^2
pattern_count <- as.double(args[[3L]])
index_budget <- max(64 * MiB, pattern_count * 320)
started <- proc.time()
result <- SplitAlignerR:::cpp_engine002_reopen_authority_scale_store(
  args[[2L]], pattern_count,
  0, MiB, index_budget, MiB, index_budget + 2 * MiB
)
elapsed <- proc.time() - started
lines <- c(
  "status=PASS",
  paste0("manifest=", args[[2L]]),
  paste0("pattern_count=", format(pattern_count, scientific = FALSE)),
  paste0("lookup_count=", result$lookup_count),
  paste0("first_pattern_id=", result$first_pattern_id),
  paste0("middle_pattern_id=", result$middle_pattern_id),
  paste0("last_pattern_id=", result$last_pattern_id),
  paste0("file_bytes=", result$file_bytes),
  paste0("elapsed_seconds=", unname(elapsed[["elapsed"]]))
)
writeLines(lines, args[[4L]])
cat(paste(lines, collapse = "\n"), "\n")
