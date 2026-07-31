#!/usr/bin/env Rscript

args_all <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", args_all, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
arch_root <- normalizePath(file.path(script_dir, ".."), mustWork = TRUE)
prototype_dir <- file.path(arch_root, "prototype")
source(file.path(prototype_dir, "arch000_common.R"))
suppressPackageStartupMessages(library(SplitAlignerR))

args <- commandArgs(trailingOnly = TRUE)
if (!length(args)) arch_stop("Expected action: generate, case, aggregate, or environment.")
action <- args[[1L]]

arg_map <- function(values) {
  out <- list()
  for (value in values) {
    at <- regexpr("=", value, fixed = TRUE)[[1L]]
    if (at < 2L) arch_stop(sprintf("Invalid key=value argument: %s", value))
    out[[substr(value, 1L, at - 1L)]] <- substr(value, at + 1L, nchar(value))
  }
  out
}

write_catnip_workload <- function(path, count, compressed = FALSE) {
  data("catnip10_oracle", package = "SplitAlignerR")
  species <- ape::read.tree(text = catnip10_oracle$species_tree)
  trees <- list()
  for (regime in c("global", "local")) {
    deletion <- catnip10_oracle[[regime]]$deletion_order
    trees <- c(trees, lapply(0:length(deletion), function(step) {
      if (!step) species else ape::drop.tip(species, deletion[seq_len(step)])
    }))
  }
  newicks <- vapply(trees, ape::write.tree, character(1))
  con <- if (compressed) gzfile(path, open = "wt", compression = 6L) else
    file(path, open = "wt", encoding = "UTF-8")
  on.exit(close(con), add = TRUE)
  block_size <- 10000L
  for (start in seq.int(1L, count, by = block_size)) {
    index <- start:min(count, start + block_size - 1L)
    lines <- paste0(
      sprintf("rep_%06d", index),
      newicks[((index - 1L) %% length(newicks)) + 1L]
    )
    writeLines(lines, con, useBytes = TRUE)
  }
  invisible(path)
}

if (action == "generate") {
  opt <- arg_map(args[-1L])
  work <- normalizePath(opt$work, mustWork = FALSE)
  dir.create(work, recursive = TRUE, showWarnings = FALSE)
  data("catnip10_oracle", package = "SplitAlignerR")
  species_path <- file.path(work, "catnip10_species.nwk")
  writeLines(catnip10_oracle$species_tree, species_path, useBytes = TRUE)
  for (n in c(10000L, 100000L)) {
    plain <- file.path(work, sprintf("catnip10_rep_%d.nwk", n))
    write_catnip_workload(plain, n, FALSE)
    if (n == 10000L) {
      write_catnip_workload(paste0(plain, ".gz"), n, TRUE)
    }
  }
  files <- list.files(work, full.names = TRUE)
  sha256_file <- function(path) {
    output <- system2("shasum", c("-a", "256", path), stdout = TRUE)
    strsplit(output[[1L]], " ", fixed = TRUE)[[1L]][[1L]]
  }
  manifest <- data.frame(
    file = basename(files),
    bytes = as.numeric(file.info(files)$size),
    sha256 = vapply(files, sha256_file, character(1)),
    note = "reproducible temporary workload; excluded from handoff archive",
    stringsAsFactors = FALSE
  )
  utils::write.csv(manifest, file.path(work, "WORKLOAD_MANIFEST.csv"), row.names = FALSE)
  quit(status = 0L)
}

if (action == "case") {
  opt <- arg_map(args[-1L])
  variant <- opt$variant
  input <- normalizePath(opt$input, mustWork = TRUE)
  species <- normalizePath(opt$species, mustWork = TRUE)
  result_file <- opt$result
  storage_bytes <- as.numeric(file.info(input)$size)

  if (variant %in% c("read_only", "taxa_scan_only", "full_parse_only")) {
    authority <- if (variant == "read_only") NULL else arch_species_authority(species)
    taxa_counts <- integer()
    pattern_keys <- character()
    started <- proc.time()[["elapsed"]]
    count <- arch_iterate_records(input, function(record, index) {
      if (variant == "read_only") return(invisible(NULL))
      taxa <- if (variant == "taxa_scan_only") {
        arch_scan_tips(record$newick)
      } else {
        arch_complete_parse_tips(record$newick)
      }
      ids <- arch_taxa_to_ids(taxa, authority)
      taxa_counts[[index]] <<- length(ids)
      pattern_keys[[index]] <<- arch_pattern_key(ids)
    })
    elapsed <- proc.time()[["elapsed"]] - started
    row <- data.frame(
      workload = opt$label, variant = variant,
      representation = if (grepl("[.]gz$", input, ignore.case = TRUE)) "gzip_newick" else "plain_newick",
      measured_or_projected = "MEASURED", storage_type = opt$storage_type,
      input_bytes = storage_bytes, loci = count,
      taxa_min = if (length(taxa_counts)) min(taxa_counts) else NA_real_,
      taxa_median = if (length(taxa_counts)) stats::median(taxa_counts) else NA_real_,
      taxa_max = if (length(taxa_counts)) max(taxa_counts) else NA_real_,
      unique_patterns = if (length(pattern_keys)) length(unique(pattern_keys)) else NA_real_,
      unique_bstar = NA_real_, pattern_cache_bytes = NA_real_,
      bstar_buffer_peak_bytes = NA_real_,
      bstar_threshold_bytes = as.numeric(opt$threshold_bytes),
      bstar_flush_count = NA_real_, preparation_seconds = 0,
      first_pass_seconds = unname(elapsed), second_pass_seconds = 0,
      total_seconds = unname(elapsed), first_pass_overhead_fraction = 1,
      trees_per_second = count / unname(elapsed),
      storage_MB_per_second = storage_bytes / 1e6 / unname(elapsed),
      peak_rss_bytes = NA_real_, final_compact_object_bytes = NA_real_,
      largest_top_level_component = "not_applicable",
      largest_top_level_component_bytes = NA_real_, temporary_disk_bytes = 0,
      bounded_memory_slowdown = NA_real_,
      notes = "I/O phase-isolation microbenchmark; no recovery result retained.",
      stringsAsFactors = FALSE
    )
    saveRDS(row, result_file, version = 3)
    quit(status = 0L)
  }

  if (variant == "production_in_memory") {
    prepare_started <- proc.time()[["elapsed"]]
    con <- if (grepl("[.]gz$", input, ignore.case = TRUE)) gzfile(input) else input
    lines <- readLines(con, warn = FALSE, encoding = "UTF-8")
    if (inherits(con, "connection")) close(con)
    records <- SplitAlignerR:::gene_records_from_lines(lines)
    ids <- SplitAlignerR:::complete_gene_ids(records$ids, length(records$newicks))
    preparation_seconds <- proc.time()[["elapsed"]] - prepare_started
    started <- proc.time()[["elapsed"]]
    result <- SplitAlignerR::align_branches(
      species, records$newicks, mode = "free", gene_ids = ids
    )
    engine_seconds <- proc.time()[["elapsed"]] - started
    component_bytes <- vapply(result, function(x) as.numeric(object.size(x)), numeric(1))
    largest <- names(component_bytes)[which.max(component_bytes)]
    row <- data.frame(
      workload = opt$label, variant = variant,
      representation = if (grepl("[.]gz$", input, ignore.case = TRUE)) "gzip_newick" else "plain_newick",
      measured_or_projected = "MEASURED", storage_type = opt$storage_type,
      input_bytes = storage_bytes, loci = nrow(result$state_matrix),
      taxa_min = min(result$gene_provenance$retained_taxon_count),
      taxa_median = stats::median(result$gene_provenance$retained_taxon_count),
      taxa_max = max(result$gene_provenance$retained_taxon_count),
      unique_patterns = length(unique(result$gene_provenance$retained_taxa_key)),
      unique_bstar = nrow(result$composite_coordinates),
      pattern_cache_bytes = NA_real_, bstar_buffer_peak_bytes = NA_real_,
      bstar_threshold_bytes = NA_real_, bstar_flush_count = NA_real_,
      preparation_seconds = unname(preparation_seconds),
      first_pass_seconds = NA_real_, second_pass_seconds = unname(engine_seconds),
      total_seconds = unname(preparation_seconds + engine_seconds),
      first_pass_overhead_fraction = NA_real_,
      trees_per_second = nrow(result$state_matrix) /
        unname(preparation_seconds + engine_seconds),
      storage_MB_per_second = storage_bytes / 1e6 /
        unname(preparation_seconds + engine_seconds),
      peak_rss_bytes = NA_real_,
      final_compact_object_bytes = as.numeric(object.size(result)),
      largest_top_level_component = largest,
      largest_top_level_component_bytes = unname(component_bytes[[largest]]),
      temporary_disk_bytes = 0, bounded_memory_slowdown = NA_real_,
      notes = "Existing production in-memory mapper baseline; expanded ledgers retained.",
      stringsAsFactors = FALSE
    )
    saveRDS(row, result_file, version = 3)
    quit(status = 0L)
  }

  prepare_started <- proc.time()[["elapsed"]]
  engine_input <- input
  method <- if (variant == "full_full") "full_parse" else "taxa_scan"
  if (variant == "in_memory_text") {
    engine_input <- readLines(
      if (grepl("[.]gz$", input, ignore.case = TRUE)) gzfile(input) else input,
      warn = FALSE, encoding = "UTF-8"
    )
    method <- "full_parse"
  } else if (!variant %in% c("taxa_full", "full_full")) {
    arch_stop(sprintf("Unknown benchmark variant: %s", variant))
  }
  preparation_seconds <- proc.time()[["elapsed"]] - prepare_started
  result <- arch_stream_compact(
    species, engine_input, first_method = method,
    bstar_threshold_bytes = as.numeric(opt$threshold_bytes)
  )
  row <- data.frame(
    workload = opt$label,
    variant = variant,
    representation = if (grepl("[.]gz$", input, ignore.case = TRUE)) "gzip_newick" else "plain_newick",
    measured_or_projected = "MEASURED",
    storage_type = opt$storage_type,
    input_bytes = storage_bytes,
    loci = nrow(result$state_matrix),
    taxa_min = result$metrics$taxa_min,
    taxa_median = result$metrics$taxa_median,
    taxa_max = result$metrics$taxa_max,
    unique_patterns = result$metrics$unique_patterns,
    unique_bstar = result$metrics$unique_bstar,
    pattern_cache_bytes = result$metrics$pattern_cache_bytes,
    bstar_buffer_peak_bytes = result$metrics$bstar_peak_pending_bytes,
    bstar_threshold_bytes = result$metrics$bstar_threshold_bytes,
    bstar_flush_count = result$metrics$bstar_flush_count,
    preparation_seconds = unname(preparation_seconds),
    first_pass_seconds = result$metrics$first_pass_seconds,
    second_pass_seconds = result$metrics$second_pass_seconds,
    total_seconds = unname(preparation_seconds) + result$metrics$total_seconds,
    first_pass_overhead_fraction = result$metrics$first_pass_seconds /
      (unname(preparation_seconds) + result$metrics$total_seconds),
    trees_per_second = nrow(result$state_matrix) /
      (unname(preparation_seconds) + result$metrics$total_seconds),
    storage_MB_per_second = storage_bytes / 1e6 /
      (unname(preparation_seconds) + result$metrics$total_seconds),
    peak_rss_bytes = NA_real_,
    final_compact_object_bytes = result$metrics$compact_object_bytes,
    largest_top_level_component = result$metrics$largest_top_level_component,
    largest_top_level_component_bytes = result$metrics$largest_top_level_component_bytes,
    temporary_disk_bytes = 0,
    bounded_memory_slowdown = NA_real_,
    notes = "Peak RSS is injected from the matching BSD time -l process log during aggregation.",
    stringsAsFactors = FALSE
  )
  saveRDS(row, result_file, version = 3)
  quit(status = 0L)
}

parse_peak_rss <- function(path) {
  lines <- readLines(path, warn = FALSE)
  hit <- grep("maximum resident set size", lines, value = TRUE)
  if (length(hit) != 1L) return(NA_real_)
  as.numeric(sub("^\\s*([0-9]+).*$", "\\1", hit))
}

if (action == "aggregate") {
  opt <- arg_map(args[-1L])
  result_dir <- normalizePath(opt$result_dir, mustWork = TRUE)
  output <- opt$output
  rds <- list.files(result_dir, pattern = "[.]rds$", full.names = TRUE)
  rows <- lapply(rds, function(path) {
    row <- readRDS(path)
    time_path <- sub("[.]rds$", ".time.txt", path)
    row$peak_rss_bytes <- parse_peak_rss(time_path)
    row
  })
  table <- do.call(rbind, rows)
  rownames(table) <- NULL
  for (workload in unique(table$workload)) {
    subset_index <- which(table$workload == workload)
    preferred <- match("production_in_memory", table$variant[subset_index])
    if (is.na(preferred)) preferred <- match("in_memory_text", table$variant[subset_index])
    baseline <- table$total_seconds[subset_index[preferred]]
    if (length(baseline) && !is.na(baseline)) {
      two_pass <- subset_index[table$variant[subset_index] == "taxa_full"]
      table$bounded_memory_slowdown[two_pass] <- table$total_seconds[two_pass] / baseline
    }
  }
  table$memory_budget_bytes <- 1024^3
  table$fits_1GiB_budget <- ifelse(
    table$measured_or_projected == "MEASURED" & is.finite(table$peak_rss_bytes),
    table$peak_rss_bytes <= table$memory_budget_bytes,
    NA
  )
  if (any(table$loci == 100000L & table$variant == "taxa_full")) {
    source_row <- table[which(table$loci == 100000L & table$variant == "taxa_full")[[1L]], ]
    projection <- source_row
    projection$workload <- "catnip10_rep_500000_projection"
    projection$measured_or_projected <- "PROJECTED_FROM_100000"
    projection$input_bytes <- source_row$input_bytes * 5
    projection$loci <- 500000L
    projection$preparation_seconds <- source_row$preparation_seconds * 5
    projection$first_pass_seconds <- source_row$first_pass_seconds * 5
    projection$second_pass_seconds <- source_row$second_pass_seconds * 5
    projection$total_seconds <- source_row$total_seconds * 5
    projection$peak_rss_bytes <- NA_real_
    projection$final_compact_object_bytes <- source_row$final_compact_object_bytes * 5
    projection$largest_top_level_component_bytes <-
      source_row$largest_top_level_component_bytes * 5
    projection$fits_1GiB_budget <- NA
    projection$notes <- paste0(
      "Projection only: linear time/matrix growth from measured 100,000-locus run; ",
      "pattern and B* registries held at observed saturation; peak RSS not projected."
    )
    table <- rbind(table, projection)
  }
  table <- table[order(table$loci, table$workload, table$variant, method = "radix"), ]
  utils::write.csv(table, output, row.names = FALSE, na = "NOT_MEASURED")
  quit(status = 0L)
}

if (action == "environment") {
  opt <- arg_map(args[-1L])
  capture <- function(command, command_args = character()) {
    tryCatch(system2(command, command_args, stdout = TRUE, stderr = TRUE),
             error = function(e) paste("UNAVAILABLE:", conditionMessage(e)))
  }
  packages <- c("SplitAlignerR", "ape", "phangorn", "ps")
  storage <- capture("diskutil", c("info", "/"))
  storage <- storage[grepl(paste0(
    "^\\s*(File System Personality|Protocol|Device Location|",
    "Removable Media|Solid State|Disk Size|Container Free Space):"
  ), storage)]
  lines <- c(
    paste("captured_utc:", format(Sys.time(), tz = "UTC", usetz = TRUE)),
    paste("R:", R.version.string),
    paste("platform:", R.version$platform),
    vapply(packages, function(package) {
      paste0(package, ": ", if (requireNamespace(package, quietly = TRUE)) {
        as.character(utils::packageVersion(package))
      } else "NOT INSTALLED")
    }, character(1)),
    "",
    "sw_vers:", capture("sw_vers"),
    "",
    "kernel_without_hostname:", capture("uname", c("-srvmp")),
    "",
    "hardware_model:", capture("sysctl", c("-n", "hw.model")),
    "physical_memory_bytes:", capture("sysctl", c("-n", "hw.memsize")),
    "cpu_brand:", capture("sysctl", c("-n", "machdep.cpu.brand_string")),
    "",
    "filesystem:", capture("df", c("-h", arch_root)),
    "",
    "storage_probe_selected_fields:", storage
  )
  writeLines(lines, opt$output, useBytes = TRUE)
  quit(status = 0L)
}

arch_stop(sprintf("Unknown action: %s", action))
