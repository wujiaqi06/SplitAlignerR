#!/usr/bin/env Rscript

all_args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", all_args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
repo_root <- normalizePath(file.path(script_dir, "..", "..", ".."), mustWork = TRUE)
setwd(repo_root)
source("dev/ARCH000A/prototype/load_arch000a.R")
suppressPackageStartupMessages(library(SplitAlignerR))

result_dir <- Sys.getenv("ARCH000A_BSTAR_RESULT_DIR", "")
if (!nzchar(result_dir)) stop("ARCH000A_BSTAR_RESULT_DIR is required.", call. = FALSE)
dir.create(result_dir, recursive = TRUE, showWarnings = FALSE)
measured_patterns <- as.integer(Sys.getenv("ARCH000A_BSTAR_MEASURED_PATTERNS", "250"))
target_loci <- as.integer(Sys.getenv("ARCH000A_BSTAR_TARGET_LOCI", "100000"))
threshold <- as.numeric(Sys.getenv("ARCH000A_BSTAR_BUFFER_BYTES", "65536"))
a_assert(measured_patterns >= 10L && target_loci >= measured_patterns,
         "B* stress scale is invalid.")

set.seed(20260731L)
tree <- ape::rtree(1000L, rooted = TRUE)
tree$tip.label <- sprintf("T%04d", seq_len(1000L))
species <- ape::write.tree(tree, digits = 10L)
timed <- a_elapsed(arch_species_authority(species))
authority <- timed$value
authority_seconds <- timed$seconds

seen <- new.env(hash = TRUE, parent = emptyenv())
patterns <- vector("list", measured_patterns)
set.seed(20260731L)
generated <- 0L
attempts <- 0L
timed <- a_elapsed({
  while (generated < measured_patterns) {
    attempts <- attempts + 1L
    missing <- 250L + ((attempts - 1L) %% 101L)
    retained <- setdiff(seq_len(1000L), sample.int(1000L, missing))
    bits <- a_pack_ids(retained, 1000L)
    key <- a_pattern_exact_key(bits)
    if (!exists(key, seen, inherits = FALSE)) {
      generated <- generated + 1L
      patterns[[generated]] <- retained
      assign(key, TRUE, seen)
    }
  }
})
pattern_generation_seconds <- timed$seconds

buffer <- a_new_bstar_churn_buffer(threshold)
member_sets <- list()
truth_seconds <- 0
emission_seconds <- 0
started_total <- proc.time()[["elapsed"]]
for (retained in patterns) {
  timed <- a_elapsed(arch_build_truth_plan(authority, retained))
  plan <- timed$value
  truth_seconds <- truth_seconds + timed$seconds
  if (length(plan$composites)) {
    for (composite in plan$composites) {
      member_sets[[length(member_sets) + 1L]] <- composite$members
      timed <- a_elapsed(buffer$add(composite$members))
      emission_seconds <- emission_seconds + timed$seconds
    }
  }
}
buffer$finalize()
stress_seconds <- unname(proc.time()[["elapsed"]] - started_total)
stats <- buffer$stats()
a_assert(stats$records_seen > measured_patterns,
         "Large-tree stress did not produce high composite emission.")
a_assert(stats$flush_count >= 2L,
         "Large-tree stress did not exercise pending-buffer churn.")
a_assert(a_bstar_exact_collision_gate(member_sets),
         "Forced B* hash collision changed exact byte identity.")

compaction_seconds <- stats$local_sort_unique_seconds + stats$global_union_seconds
measured <- data.frame(
  evidence_class = "MEASURED_ENGINEERING_STRESS",
  taxa = 1000L,
  loci = measured_patterns,
  unique_patterns = measured_patterns,
  unique_pattern_fraction = 1,
  buffer_threshold_bytes = threshold,
  canonical_member_set_encoded_bytes = stats$canonical_member_set_encoded_bytes,
  composite_records_emitted = stats$records_seen,
  records_per_flush_min = min(stats$records_per_flush),
  records_per_flush_mean = mean(stats$records_per_flush),
  records_per_flush_max = max(stats$records_per_flush),
  flush_count = stats$flush_count,
  local_sort_unique_seconds = stats$local_sort_unique_seconds,
  global_union_seconds = stats$global_union_seconds,
  bstar_compaction_seconds = compaction_seconds,
  truth_construction_seconds = truth_seconds,
  bstar_emission_including_flush_seconds = emission_seconds,
  stress_total_seconds = stress_seconds,
  bstar_compaction_fraction = compaction_seconds / stress_seconds,
  peak_pending_buffer_bytes = stats$peak_pending_buffer_bytes,
  unique_bstar = stats$unique_bstar,
  peak_rss_bytes = NA_real_,
  projection_basis = "NOT_APPLICABLE",
  stringsAsFactors = FALSE
)

scale <- target_loci / measured_patterns
projected <- measured
projected$evidence_class <- "PROJECTED_FROM_MEASURED_SMALLER_RUN"
projected$loci <- target_loci
projected$unique_patterns <- target_loci
projected$canonical_member_set_encoded_bytes <-
  measured$canonical_member_set_encoded_bytes * scale
projected$composite_records_emitted <-
  measured$composite_records_emitted * scale
projected$records_per_flush_min <- NA_real_
projected$records_per_flush_mean <- measured$records_per_flush_mean
projected$records_per_flush_max <- NA_real_
projected$flush_count <- ceiling(
  projected$canonical_member_set_encoded_bytes / threshold
)
projected$local_sort_unique_seconds <-
  measured$local_sort_unique_seconds * scale
projected$global_union_seconds <- measured$global_union_seconds * scale
projected$bstar_compaction_seconds <- measured$bstar_compaction_seconds * scale
projected$truth_construction_seconds <-
  measured$truth_construction_seconds * scale
projected$bstar_emission_including_flush_seconds <-
  measured$bstar_emission_including_flush_seconds * scale
projected$stress_total_seconds <- measured$stress_total_seconds * scale
projected$bstar_compaction_fraction <- measured$bstar_compaction_fraction
projected$peak_pending_buffer_bytes <- NA_real_
projected$unique_bstar <- NA_real_
projected$peak_rss_bytes <- NA_real_
projected$projection_basis <- paste(
  "Simple per-pattern linear projection for bytes, flush count, and timing;",
  "peak RSS and unique-B* growth are not projected; global union may be",
  "superlinear, so projected timing is not a completion claim."
)

utils::write.csv(
  rbind(measured, projected),
  file.path(result_dir, "ARCH000A_BSTAR_CHURN_RESULTS.csv"),
  row.names = FALSE, na = "NOT_MEASURED", quote = TRUE
)
writeLines(c(
  "status=PASS",
  paste0("authority_build_seconds=", format(authority_seconds, digits = 12)),
  paste0("pattern_generation_seconds=", format(pattern_generation_seconds, digits = 12)),
  paste0("measured_patterns=", measured_patterns),
  paste0("target_projection_loci=", target_loci),
  paste0("records_per_flush=", paste(stats$records_per_flush, collapse = ",")),
  paste0("bytes_per_flush=", paste(stats$bytes_per_flush, collapse = ",")),
  paste0("unique_Bstar_growth=", paste(stats$unique_growth, collapse = ",")),
  "hash_collision_policy=forced constant hash resolved by identical exact canonical bytes",
  "synthetic_input=engineering stress only; not a biological dataset"
), file.path(result_dir, "BSTAR_CHURN_DETAILS.raw.txt"))
