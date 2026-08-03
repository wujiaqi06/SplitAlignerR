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
  64 * 1024, MiB, index_budget, MiB,
  index_budget + MiB + 64 * 1024 + MiB
)
elapsed <- proc.time() - started
component <- sub("[.]manifest$", ".bin", args[[2L]])
sha_started <- proc.time()[["elapsed"]]
sha_line <- system2(
  "shasum", c("-a", "256", shQuote(component)),
  stdout = TRUE, stderr = TRUE
)
sha_seconds <- proc.time()[["elapsed"]] - sha_started
sha_line <- sha_line[
  grepl("^[0-9a-f]{64}[[:space:]]", sha_line)
]
if (length(sha_line) != 1L) {
  stop("complete-file SHA-256 probe failed", call. = FALSE)
}
component_sha256 <- sub("[[:space:]].*$", "", sha_line)
lines <- c(
  "status=PASS",
  paste0("manifest=", args[[2L]]),
  paste0("pattern_count=", format(pattern_count, scientific = FALSE)),
  paste0("lookup_count=", result$lookup_count),
  paste0("first_pattern_id=", result$first_pattern_id),
  paste0("middle_pattern_id=", result$middle_pattern_id),
  paste0("last_pattern_id=", result$last_pattern_id),
  paste0("file_bytes=", result$file_bytes),
  paste0("open_full_validation_seconds=",
         result$open_full_validation_seconds),
  paste0("boundary_lookup_seconds=", result$boundary_lookup_seconds),
  paste0("sequential_lookup_seconds=", result$sequential_lookup_seconds),
  paste0("random_lookup_seconds=", result$random_lookup_seconds),
  paste0("lru_warm_lookup_seconds=", result$lru_warm_lookup_seconds),
  paste0("functional_probe_count=", result$functional_probe_count),
  paste0("lru_hits=", result$lru_hits),
  paste0("lru_misses=", result$lru_misses),
  paste0("lru_evictions=", result$lru_evictions),
  paste0("lru_insertions=", result$lru_insertions),
  paste0("lru_cache_high_water=", result$lru_cache_high_water),
  paste0("complete_file_sha256_seconds=", sha_seconds),
  paste0("component_sha256=", component_sha256),
  paste0("elapsed_seconds=", unname(elapsed[["elapsed"]]))
)
writeLines(lines, args[[4L]])
cat(paste(lines, collapse = "\n"), "\n")
