#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("result and benchmark-work directories are required", call. = FALSE)
}
all_args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", all_args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
repo_root <- normalizePath(file.path(script_dir, "..", "..", ".."), mustWork = TRUE)
setwd(repo_root)
source("dev/ARCH000A/prototype/load_arch000a.R")
result_dir <- normalizePath(args[[1L]], mustWork = TRUE)
work_dir <- normalizePath(args[[2L]], mustWork = TRUE)
benchmark_path <- file.path(result_dir, "ARCH000A_BENCHMARK_RESULTS.csv")
table <- utils::read.csv(
  benchmark_path, stringsAsFactors = FALSE, check.names = FALSE,
  na.strings = "NOT_MEASURED"
)

table$fit_status <- "COMPLETED"
table$metric_note <- ""
table$checksum_scope <- "case_specific_identity_or_scientific_checksum"

meta <- readRDS(file.path(work_dir, "authority_catalog_metadata.rds"))
disk <- a_open_packed_store(
  file.path(work_dir, "authority_truth_store.bin"),
  meta$registry, meta$authority, verify_all_records = FALSE
)
mapping <- meta$registry$mappings[[1L]]
record_checksum <- stats::setNames(
  disk$expected_checksums, meta$registry$pattern_ids
)
gene_checksum <- unname(record_checksum[mapping$pattern_id])
index <- order(mapping$gene_id, method = "radix")
normalized_walk_checksum <- a_adler32(charToRaw(paste0(
  mapping$gene_id[index], ":", gene_checksum[index], collapse = "\n"
)))
disk$close()
strategy_walk <- table$benchmark_type == "strategy_walk"
table$checksum[strategy_walk] <- normalized_walk_checksum
table$checksum_scope[strategy_walk] <-
  "normalized_by_gene_id_over_exact_packed_truth_plan"

decoded_lru <- table$strategy == "lru_disk_decoded"
table$truth_plan_reloads[decoded_lru] <- table$cache_misses[decoded_lru]
table$truth_plan_builds[decoded_lru] <- 0
table$metric_note[decoded_lru] <- paste(
  "Loader calls materialize packed records from disk; counted as reloads,",
  "not S9 truth-plan reconstructions."
)

source <- table[table$label == "stress_100000_u100_interleaved_64m", ]
if (nrow(source) != 1L) {
  stop("Measured 100,000-locus substrate row is unavailable.", call. = FALSE)
}
projection <- source
scale <- 5
resident_records <- source$unique_patterns - source$evictions
projection$benchmark_type <- "packed_storage_substrate_projection"
projection$workload <- "synthetic_302dimension_500000"
projection$loci <- 500000
projection$unique_patterns <- 500000
projection$unique_pattern_fraction <- 1
projection$pattern_registry_bytes <- source$pattern_registry_bytes * scale
projection$temporary_disk_bytes <- 36 + 500000 * 23035 + 20
projection$first_pass_seconds <- source$first_pass_seconds * scale
projection$second_pass_seconds <- source$second_pass_seconds * scale
projection$total_seconds <- source$total_seconds * scale
projection$truth_plan_reloads <- 500000
projection$cache_hits <- 0
projection$cache_misses <- 500000
projection$evictions <- 500000 - resident_records
projection$peak_rss_bytes <- NA_real_
projection$checksum <- NA_character_
projection$measured_or_projected <- paste(
  "PROJECTED_FROM_MEASURED_100000_LINEAR_THROUGHPUT",
  "AND_EXACT_FIXED_RECORD_SLOPE",
  sep = "_"
)
projection$label <- "projected_500000_u100_interleaved_64m"
projection$recorded_jst <- format(Sys.time(), tz = "Asia/Tokyo", usetz = TRUE)
projection$fit_status <- "PROJECTED_NOT_EXECUTED"
projection$metric_note <- paste(
  "Engineering storage-substrate projection only; peak RSS is intentionally",
  "not projected and no scientific truth claim is made."
)
projection$checksum_scope <- "NOT_PROJECTED"
table <- rbind(table, projection)

utils::write.csv(
  table, benchmark_path, row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)

cache_path <- file.path(result_dir, "ARCH000A_CACHE_RESULTS.csv")
cache <- subset(
  table,
  benchmark_type %in% c(
    "strategy_walk", "end_to_end", "packed_storage_substrate_stress",
    "packed_storage_substrate_projection"
  ),
  select = c(
    label, workload, strategy, loci, unique_patterns,
    unique_pattern_fraction, ordering, cache_budget_bytes,
    truth_plan_builds, truth_plan_reloads, cache_hits, cache_misses,
    evictions, total_seconds, peak_rss_bytes, checksum,
    checksum_scope, measured_or_projected, fit_status, metric_note
  )
)
utils::write.csv(
  cache, cache_path, row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)

memory_path <- file.path(result_dir, "ARCH000A_MEMORY_RESULTS.csv")
memory <- table[c(
  "label", "workload", "strategy", "output_mode", "loci",
  "unique_patterns", "unique_pattern_fraction", "cache_budget_bytes",
  "truth_store_memory_bytes", "pattern_registry_bytes",
  "bstar_registry_bytes", "matrix_or_sink_bytes", "temporary_disk_bytes",
  "peak_rss_bytes", "measured_or_projected", "fit_status", "metric_note"
)]
utils::write.csv(
  memory, memory_path, row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)
