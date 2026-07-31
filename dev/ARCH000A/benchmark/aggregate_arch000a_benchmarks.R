#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("result directory is required", call. = FALSE)
result_dir <- normalizePath(args[[1L]], mustWork = TRUE)
files <- sort(list.files(
  result_dir, pattern = "^case_.*[.]rds$", full.names = TRUE
))
if (!length(files)) stop("No benchmark case files found.", call. = FALSE)

read_peak <- function(label) {
  path <- file.path(result_dir, paste0(label, ".rss.txt"))
  lines <- readLines(path, warn = FALSE)
  value <- sub("^peak_rss_bytes=", "", grep("^peak_rss_bytes=", lines, value = TRUE))
  if (length(value) != 1L || !grepl("^[0-9]+$", value)) return(NA_real_)
  as.numeric(value)
}

cases <- lapply(files, readRDS)
rows <- lapply(cases, function(case) {
  row <- case$row
  row$peak_rss_bytes <- read_peak(row$label)
  as.data.frame(row, stringsAsFactors = FALSE, check.names = FALSE)
})
columns <- unique(unlist(lapply(rows, names), use.names = FALSE))
normalize <- function(row) {
  missing <- setdiff(columns, names(row))
  for (name in missing) row[[name]] <- NA
  row[columns]
}
table <- do.call(rbind, lapply(rows, normalize))
table <- table[order(table$benchmark_type, table$label, method = "radix"), ]
utils::write.csv(
  table, file.path(result_dir, "ARCH000A_BENCHMARK_RESULTS.csv"),
  row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)

phase_rows <- list()
for (case in cases) {
  if (!is.null(case$extra$phase_seconds)) {
    phase_rows[[length(phase_rows) + 1L]] <- data.frame(
      label = case$row$label,
      pass = if (case$row$benchmark_type == "phase_decomposition") {
        "first"
      } else "second",
      phase = names(case$extra$phase_seconds),
      seconds = as.numeric(case$extra$phase_seconds),
      measurement = if (case$row$benchmark_type == "phase_decomposition") {
        "isolated_component"
      } else "instrumented_pipeline",
      stringsAsFactors = FALSE
    )
  }
}
phase <- if (length(phase_rows)) do.call(rbind, phase_rows) else data.frame()
utils::write.csv(
  phase, file.path(result_dir, "ARCH000A_PHASE_TIMINGS.csv"),
  row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)

cache <- subset(
  table,
  benchmark_type %in% c(
    "strategy_walk", "end_to_end", "packed_storage_substrate_stress"
  ),
  select = c(
    label, workload, strategy, loci, unique_patterns,
    unique_pattern_fraction, ordering, cache_budget_bytes,
    truth_plan_builds, truth_plan_reloads, cache_hits, cache_misses,
    evictions, total_seconds, peak_rss_bytes, checksum
  )
)
utils::write.csv(
  cache, file.path(result_dir, "ARCH000A_CACHE_RESULTS.csv"),
  row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)

memory <- table[c(
  "label", "workload", "strategy", "output_mode", "loci",
  "unique_patterns", "unique_pattern_fraction", "cache_budget_bytes",
  "truth_store_memory_bytes", "pattern_registry_bytes",
  "bstar_registry_bytes", "matrix_or_sink_bytes", "temporary_disk_bytes",
  "peak_rss_bytes", "measured_or_projected"
)]
utils::write.csv(
  memory, file.path(result_dir, "ARCH000A_MEMORY_RESULTS.csv"),
  row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)
