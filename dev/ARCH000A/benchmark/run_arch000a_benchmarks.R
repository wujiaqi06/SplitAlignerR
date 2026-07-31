#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (!length(args)) stop("benchmark mode is required", call. = FALSE)
mode <- args[[1L]]
label <- if (length(args) >= 2L) args[[2L]] else mode

all_args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", all_args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
repo_root <- normalizePath(file.path(script_dir, "..", "..", ".."), mustWork = TRUE)
setwd(repo_root)
source("dev/ARCH000A/prototype/load_arch000a.R")
suppressPackageStartupMessages(library(SplitAlignerR))
`%||%` <- function(left, right) if (is.null(left)) right else left

result_dir <- Sys.getenv("ARCH000A_BENCH_RESULT_DIR", tempfile("arch000a-results-"))
work_dir <- Sys.getenv("ARCH000A_BENCH_WORK_DIR", tempfile("arch000a-work-"))
dir.create(result_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)
dir302 <- Sys.getenv("ARCH000A_302_DIR", "")
full_dir <- Sys.getenv("ARCH000A_2275_DIR", "")
if (!dir.exists(dir302) || !dir.exists(full_dir)) {
  stop("ARCH000A authority paths are unavailable.", call. = FALSE)
}
species_path <- file.path(dir302, "input", "speciesTree302.nwk")
fixed_path <- file.path(full_dir, "fix.2275genes.nwk")
free_path <- file.path(full_dir, "free.2275genes.nwk")
metadata_path <- file.path(work_dir, "authority_catalog_metadata.rds")
store_path <- file.path(work_dir, "authority_truth_store.bin")

a_save_case <- function(row, extra = list()) {
  row$label <- label
  row$recorded_jst <- format(Sys.time(), tz = "Asia/Tokyo", usetz = TRUE)
  saveRDS(
    list(row = row, extra = extra),
    file.path(result_dir, paste0("case_", label, ".rds")),
    version = 3
  )
}

a_pattern_order <- function(mapping, ordering) {
  ids <- mapping$pattern_id
  index <- seq_along(ids)
  if (ordering == "original") return(index)
  if (ordering == "reversed") return(rev(index))
  if (ordering == "grouped") return(order(ids, method = "radix"))
  if (ordering == "interleaved") {
    occurrence <- ave(index, ids, FUN = seq_along)
    return(order(occurrence, ids, method = "radix"))
  }
  if (ordering == "random") {
    set.seed(20260731L)
    return(sample(index, length(index), replace = FALSE))
  }
  stop("Unknown benchmark ordering.", call. = FALSE)
}

a_normalized_walk_checksum <- function(gene_ids, checksums) {
  index <- order(gene_ids, method = "radix")
  a_adler32(charToRaw(paste0(
    gene_ids[index], ":", checksums[index], collapse = "\n"
  )))
}

a_walk_plan_store <- function(store, pattern_ids, authority, gene_ids) {
  checksum <- character(length(pattern_ids))
  started <- proc.time()[["elapsed"]]
  for (i in seq_along(pattern_ids)) {
    plan <- store$get(pattern_ids[[i]])
    checksum[[i]] <- a_adler32(a_pack_truth_plan(plan, authority))
  }
  seconds <- unname(proc.time()[["elapsed"]] - started)
  list(
    seconds = seconds,
    checksum = a_normalized_walk_checksum(gene_ids, checksum),
    stats = store$stats()
  )
}

a_walk_packed_store <- function(store, pattern_ids, gene_ids) {
  checksum <- character(length(pattern_ids))
  started <- proc.time()[["elapsed"]]
  for (i in seq_along(pattern_ids)) {
    body <- store$get_body(pattern_ids[[i]])
    checksum[[i]] <- a_adler32(body)
  }
  seconds <- unname(proc.time()[["elapsed"]] - started)
  list(
    seconds = seconds,
    checksum = a_normalized_walk_checksum(gene_ids, checksum),
    stats = store$stats()
  )
}

if (mode == "prepare_authority") {
  authority <- arch_species_authority(species_path)
  started <- proc.time()[["elapsed"]]
  fixed_scan <- a_scan_gene_patterns(fixed_path, authority)
  fixed_scan_seconds <- unname(proc.time()[["elapsed"]] - started)
  started <- proc.time()[["elapsed"]]
  free_scan <- a_scan_gene_patterns(free_path, authority)
  free_scan_seconds <- unname(proc.time()[["elapsed"]] - started)
  registry <- a_make_pattern_registry(list(fixed_scan, free_scan), authority)
  started <- proc.time()[["elapsed"]]
  catalog <- a_make_catalog(registry, authority, store_path)
  catalog_seconds <- unname(proc.time()[["elapsed"]] - started)
  saveRDS(
    list(
      authority = authority,
      registry = registry,
      catalog = catalog,
      fixed_path = fixed_path,
      free_path = free_path
    ),
    metadata_path, version = 3
  )
  row <- list(
    benchmark_type = "authority_prepare",
    workload = "authority_2275_fixed_free_shared_patterns",
    strategy = "packed_disk_build",
    output_mode = "store_isolation",
    loci = 4550L,
    unique_patterns = length(registry$pattern_ids),
    unique_pattern_fraction = length(registry$pattern_ids) / 2275,
    ordering = "canonical_pattern_id",
    cache_budget_bytes = 0,
    truth_store_memory_bytes = 0,
    pattern_registry_bytes = registry$total_bytes,
    bstar_registry_bytes = as.numeric(object.size(catalog$bstar_keys)),
    matrix_or_sink_bytes = 0,
    temporary_disk_bytes = catalog$write_result$file_bytes,
    first_pass_seconds = fixed_scan_seconds + free_scan_seconds +
      catalog$write_result$build_seconds + catalog$write_result$pack_seconds +
      catalog$write_result$write_seconds,
    second_pass_seconds = 0,
    total_seconds = fixed_scan_seconds + free_scan_seconds + catalog_seconds,
    truth_plan_builds = length(registry$pattern_ids),
    truth_plan_reloads = 0L,
    cache_hits = 0L,
    cache_misses = 0L,
    evictions = 0L,
    terminal_na_topo_count = 0L,
    checksum = a_adler32(charToRaw(paste0(
      registry$exact_pattern_keys, collapse = ""
    ))),
    measured_or_projected = "MEASURED"
  )
  a_save_case(row, list(
    fixed_scan_seconds = fixed_scan_seconds,
    free_scan_seconds = free_scan_seconds,
    catalog_seconds = catalog_seconds,
    write_result = catalog$write_result
  ))
} else if (mode == "strategy_walk") {
  meta <- readRDS(metadata_path)
  strategy <- args[[3L]]
  ordering <- args[[4L]]
  budget <- as.numeric(args[[5L]])
  mapping <- meta$registry$mappings[[1L]]
  index <- a_pattern_order(mapping, ordering)
  pattern_ids <- mapping$pattern_id[index]
  gene_ids <- mapping$gene_id[index]
  strategy_started <- proc.time()[["elapsed"]]
  disk <- a_open_packed_store(
    store_path, meta$registry, meta$authority, verify_all_records = FALSE
  )
  if (strategy == "retain_all") {
    store <- a_new_retain_all_store(meta$registry, meta$authority)
  } else if (strategy == "recompute") {
    store <- a_new_recompute_store(meta$registry, meta$authority)
  } else if (strategy == "lru_recompute") {
    store <- a_new_lru_truth_store(
      meta$registry, meta$authority, budget
    )
  } else if (strategy == "lru_disk_decoded") {
    store <- a_new_lru_truth_store(
      meta$registry, meta$authority, budget, loader = disk$get,
      strategy_name = "bounded_lru_disk_decoded"
    )
  } else if (strategy == "disk") {
    store <- disk
  } else if (strategy == "packed_disk_lru") {
    store <- a_new_packed_body_lru(disk, budget)
  } else stop("Unknown strategy.", call. = FALSE)
  initialization_seconds <- unname(
    proc.time()[["elapsed"]] - strategy_started
  )
  if (strategy == "packed_disk_lru") {
    walked <- a_walk_packed_store(store, pattern_ids, gene_ids)
  } else {
    walked <- a_walk_plan_store(store, pattern_ids, meta$authority, gene_ids)
  }
  stats <- walked$stats
  disk_stats <- disk$stats()
  row <- list(
    benchmark_type = "strategy_walk",
    workload = "authority_2275_fixed_pattern_order",
    strategy = strategy,
    output_mode = "store_isolation",
    loci = length(pattern_ids),
    unique_patterns = length(meta$registry$pattern_ids),
    unique_pattern_fraction = length(meta$registry$pattern_ids) / length(pattern_ids),
    ordering = ordering,
    cache_budget_bytes = budget,
    truth_store_memory_bytes = stats$cache_peak_accounted_bytes %||% 0,
    pattern_registry_bytes = meta$registry$total_bytes,
    bstar_registry_bytes = as.numeric(object.size(meta$catalog$bstar_keys)),
    matrix_or_sink_bytes = as.numeric(object.size(walked$checksum)),
    temporary_disk_bytes = meta$catalog$write_result$file_bytes,
    first_pass_seconds = initialization_seconds,
    second_pass_seconds = walked$seconds,
    total_seconds = initialization_seconds + walked$seconds,
    truth_plan_builds = stats$builds %||% 0L,
    truth_plan_reloads = stats$reloads %||% disk_stats$record_reads,
    cache_hits = stats$hits %||% 0L,
    cache_misses = stats$misses %||% disk_stats$record_reads,
    evictions = stats$evictions %||% 0L,
    terminal_na_topo_count = 0L,
    checksum = walked$checksum,
    measured_or_projected = "MEASURED"
  )
  a_save_case(row, list(
    initialization_seconds = initialization_seconds,
    walk_seconds = walked$seconds,
    store_stats = stats,
    disk_stats = disk_stats
  ))
  store$close()
  if (!identical(store, disk)) disk$close()
} else if (mode == "end_to_end") {
  meta <- readRDS(metadata_path)
  budget <- as.numeric(args[[3L]])
  disk <- a_open_packed_store(
    store_path, meta$registry, meta$authority, verify_all_records = FALSE
  )
  store <- a_new_packed_body_lru(disk, budget)
  result <- a_process_with_store(
    fixed_path, meta$registry$mappings[[1L]], meta$catalog, store,
    "compact", "authority-fixed"
  )
  stats <- store$stats()
  matrix_bytes <- sum(vapply(
    result[c("state_matrix", "numeric_matrix", "fused_numeric_by_primitive")],
    function(x) as.numeric(object.size(x)), numeric(1)
  ))
  row <- list(
    benchmark_type = "end_to_end",
    workload = "authority_2275_fixed",
    strategy = "packed_disk_plus_lru",
    output_mode = "compact_matrix",
    loci = nrow(result$state_matrix),
    unique_patterns = length(meta$registry$pattern_ids),
    unique_pattern_fraction = length(meta$registry$pattern_ids) /
      nrow(result$state_matrix),
    ordering = "original",
    cache_budget_bytes = budget,
    truth_store_memory_bytes = stats$cache_peak_accounted_bytes,
    pattern_registry_bytes = meta$registry$total_bytes,
    bstar_registry_bytes = as.numeric(object.size(meta$catalog$bstar_keys)),
    matrix_or_sink_bytes = matrix_bytes,
    temporary_disk_bytes = meta$catalog$write_result$file_bytes,
    first_pass_seconds = 0,
    second_pass_seconds = result$total_processing_seconds,
    total_seconds = result$total_processing_seconds,
    truth_plan_builds = 0L,
    truth_plan_reloads = stats$reloads,
    cache_hits = stats$hits,
    cache_misses = stats$misses,
    evictions = stats$evictions,
    terminal_na_topo_count = result$terminal_na_topo_count,
    checksum = result$normalized_scientific_checksum,
    measured_or_projected = "MEASURED"
  )
  a_save_case(row, list(
    phase_seconds = result$phase_seconds,
    store_stats = stats,
    result_object_bytes = result$result_object_bytes
  ))
  store$close()
  disk$close()
} else if (mode == "phase_decomposition") {
  authority <- arch_species_authority(species_path)
  result <- a_first_pass_cost_decomposition(fixed_path, authority)
  row <- list(
    benchmark_type = "phase_decomposition",
    workload = "authority_2275_fixed",
    strategy = "isolated_first_pass_components",
    output_mode = "store_isolation",
    loci = result$locus_count,
    unique_patterns = result$unique_patterns,
    unique_pattern_fraction = result$unique_patterns / result$locus_count,
    ordering = "original",
    cache_budget_bytes = 0,
    truth_store_memory_bytes = 0,
    pattern_registry_bytes = 0,
    bstar_registry_bytes = 0,
    matrix_or_sink_bytes = 0,
    temporary_disk_bytes = 0,
    first_pass_seconds = sum(result$phase_seconds),
    second_pass_seconds = 0,
    total_seconds = sum(result$phase_seconds),
    truth_plan_builds = result$unique_patterns,
    truth_plan_reloads = 0L,
    cache_hits = 0L,
    cache_misses = 0L,
    evictions = 0L,
    terminal_na_topo_count = 0L,
    checksum = "",
    measured_or_projected = "MEASURED"
  )
  a_save_case(row, list(phase_seconds = result$phase_seconds))
} else if (mode == "stress_actual") {
  locus_count <- as.integer(args[[3L]])
  fraction <- as.numeric(args[[4L]])
  unique_count <- max(1L, as.integer(round(locus_count * fraction)))
  authority <- arch_species_authority(species_path)
  generated <- a_generate_unique_pattern_bits(
    unique_count, universe_size = length(authority$taxa),
    seed = 20260731L + unique_count
  )
  registry <- a_stress_registry(generated, locus_count)
  path <- file.path(work_dir, paste0("stress-", label, ".bin"))
  started <- proc.time()[["elapsed"]]
  catalog <- a_make_catalog(registry, authority, path)
  total <- unname(proc.time()[["elapsed"]] - started)
  row <- list(
    benchmark_type = "pattern_uniqueness_stress",
    workload = paste0("synthetic_302like_", locus_count),
    strategy = "packed_disk_build_exact_S9_plans",
    output_mode = "store_isolation",
    loci = locus_count,
    unique_patterns = unique_count,
    unique_pattern_fraction = unique_count / locus_count,
    ordering = "canonical_pattern_id",
    cache_budget_bytes = 0,
    truth_store_memory_bytes = 0,
    pattern_registry_bytes = registry$total_bytes,
    bstar_registry_bytes = as.numeric(object.size(catalog$bstar_keys)),
    matrix_or_sink_bytes = 0,
    temporary_disk_bytes = catalog$write_result$file_bytes,
    first_pass_seconds = total,
    second_pass_seconds = 0,
    total_seconds = total,
    truth_plan_builds = unique_count,
    truth_plan_reloads = 0L,
    cache_hits = 0L,
    cache_misses = 0L,
    evictions = 0L,
    terminal_na_topo_count = 0L,
    checksum = a_adler32(charToRaw(paste0(
      registry$exact_pattern_keys, collapse = ""
    ))),
    measured_or_projected = "MEASURED"
  )
  a_save_case(row, list(
    generator_seed = generated$seed,
    missing_range = generated$missing_range,
    write_result = catalog$write_result,
    engineering_stress_only = TRUE,
    exact_S9_truth_plans = TRUE
  ))
  unlink(path)
} else if (mode == "stress_substrate") {
  locus_count <- as.integer(args[[3L]])
  fraction <- as.numeric(args[[4L]])
  budget <- as.numeric(args[[5L]])
  ordering <- args[[6L]]
  unique_count <- max(1L, as.integer(round(locus_count * fraction)))
  meta <- readRDS(metadata_path)
  generated <- a_generate_unique_pattern_bits(
    unique_count, universe_size = length(meta$authority$taxa),
    seed = 20260731L + unique_count
  )
  registry <- a_stress_registry(generated, locus_count)
  template_disk <- a_open_packed_store(
    store_path, meta$registry, meta$authority, verify_all_records = FALSE
  )
  template_body <- template_disk$get_body(meta$registry$pattern_ids[[1L]])
  template_disk$close()
  path <- file.path(work_dir, paste0("substrate-", label, ".bin"))
  started <- proc.time()[["elapsed"]]
  write_result <- a_write_packed_store(
    path, registry, meta$authority,
    body_provider = a_synthetic_body_provider(template_body)
  )
  write_total <- unname(proc.time()[["elapsed"]] - started)
  disk <- a_open_packed_store(
    path, registry, meta$authority, verify_all_records = FALSE
  )
  store <- a_new_packed_body_lru(disk, budget)
  sequence <- a_stress_pattern_sequence(
    locus_count, fraction, ordering = ordering, seed = 20260731L
  )
  pattern_ids <- registry$pattern_ids[sequence$pattern_index]
  walked <- a_walk_packed_store(
    store, pattern_ids, sprintf("stress_%08d", seq_along(pattern_ids))
  )
  stats <- walked$stats
  row <- list(
    benchmark_type = "packed_storage_substrate_stress",
    workload = paste0("synthetic_302dimension_", locus_count),
    strategy = "packed_disk_plus_lru",
    output_mode = "store_isolation_checksum_sink",
    loci = locus_count,
    unique_patterns = unique_count,
    unique_pattern_fraction = unique_count / locus_count,
    ordering = ordering,
    cache_budget_bytes = budget,
    truth_store_memory_bytes = stats$cache_peak_accounted_bytes,
    pattern_registry_bytes = registry$total_bytes,
    bstar_registry_bytes = 0,
    matrix_or_sink_bytes = as.numeric(object.size(walked$checksum)),
    temporary_disk_bytes = write_result$file_bytes,
    first_pass_seconds = write_total,
    second_pass_seconds = walked$seconds,
    total_seconds = write_total + walked$seconds,
    truth_plan_builds = 0L,
    truth_plan_reloads = stats$reloads,
    cache_hits = stats$hits,
    cache_misses = stats$misses,
    evictions = stats$evictions,
    terminal_na_topo_count = 0L,
    checksum = walked$checksum,
    measured_or_projected = "MEASURED_STORAGE_SUBSTRATE"
  )
  a_save_case(row, list(
    generator_seed = generated$seed,
    missing_range = generated$missing_range,
    write_result = write_result,
    store_stats = stats,
    engineering_stress_only = TRUE,
    scientific_truth_claim = FALSE,
    purpose = "packed store and hard-budget LRU systems stress"
  ))
  store$close()
  disk$close()
  unlink(path)
} else {
  stop(sprintf("Unknown benchmark mode: %s", mode), call. = FALSE)
}
