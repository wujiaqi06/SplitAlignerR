## ARCH000A experimental, non-public adaptive selector.

a_select_truth_strategy <- function(
    locus_count,
    unique_patterns,
    estimated_verbose_cache_bytes,
    estimated_packed_cache_bytes,
    cache_budget_bytes,
    mean_reconstruction_seconds,
    packed_store_bytes,
    disk_write_bytes_per_second,
    disk_read_bytes_per_second,
    expected_lru_hit_rate,
    storage_available = TRUE) {
  inputs <- list(
    locus_count = as.integer(locus_count),
    unique_patterns = as.integer(unique_patterns),
    unique_pattern_fraction = unique_patterns / locus_count,
    estimated_verbose_cache_bytes = as.numeric(estimated_verbose_cache_bytes),
    estimated_packed_cache_bytes = as.numeric(estimated_packed_cache_bytes),
    cache_budget_bytes = as.numeric(cache_budget_bytes),
    mean_reconstruction_seconds = as.numeric(mean_reconstruction_seconds),
    packed_store_bytes = as.numeric(packed_store_bytes),
    disk_write_bytes_per_second = as.numeric(disk_write_bytes_per_second),
    disk_read_bytes_per_second = as.numeric(disk_read_bytes_per_second),
    expected_lru_hit_rate = as.numeric(expected_lru_hit_rate),
    storage_available = isTRUE(storage_available)
  )
  if (estimated_packed_cache_bytes <= 0.80 * cache_budget_bytes) {
    strategy <- "retain_all_packed_memory"
    reason <- paste(
      "Measured packed full-cache estimate is at most 80% of the budget;",
      "disk lifecycle and recomputation are unnecessary."
    )
  } else if (isTRUE(storage_available) &&
             is.finite(disk_read_bytes_per_second) &&
             disk_read_bytes_per_second > 0) {
    strategy <- "packed_disk_plus_bounded_lru"
    reason <- paste(
      "Packed full-cache estimate exceeds budget; deterministic records provide",
      "reuse without S9 reconstruction, while the byte LRU bounds hot storage."
    )
  } else {
    strategy <- "recompute_plus_bounded_lru"
    reason <- paste(
      "Packed full-cache estimate exceeds budget and no validated store is available;",
      "recompute is slower but preserves a defensible memory bound."
    )
  }
  list(
    strategy = strategy,
    budget_bytes = as.numeric(cache_budget_bytes),
    inputs = inputs,
    reason = reason,
    estimated_recompute_seconds = unique_patterns * mean_reconstruction_seconds,
    estimated_packed_initialization_seconds = if (
      is.finite(disk_write_bytes_per_second) && disk_write_bytes_per_second > 0
    ) packed_store_bytes / disk_write_bytes_per_second else NA_real_,
    estimated_cold_reload_seconds = if (
      is.finite(disk_read_bytes_per_second) && disk_read_bytes_per_second > 0
    ) packed_store_bytes / disk_read_bytes_per_second else NA_real_,
    classification = "engineering_judgment_from_measured_inputs"
  )
}

a_selector_text <- function(decision) {
  paste(
    sprintf("Truth-plan strategy: %s", decision$strategy),
    sprintf("Budget: %.0f bytes", decision$budget_bytes),
    sprintf(
      "Observed pattern uniqueness: %.3f",
      decision$inputs$unique_pattern_fraction
    ),
    sprintf(
      "Estimated verbose full-cache size: %.0f bytes",
      decision$inputs$estimated_verbose_cache_bytes
    ),
    sprintf(
      "Estimated packed full-cache size: %.0f bytes",
      decision$inputs$estimated_packed_cache_bytes
    ),
    sprintf(
      "Expected LRU hit rate: %.3f",
      decision$inputs$expected_lru_hit_rate
    ),
    sprintf(
      "Disk write throughput: %.3f MB/s",
      decision$inputs$disk_write_bytes_per_second / 1e6
    ),
    sprintf(
      "Disk read throughput: %.3f MB/s",
      decision$inputs$disk_read_bytes_per_second / 1e6
    ),
    sprintf(
      "Truth reconstruction time: %.6f s/plan",
      decision$inputs$mean_reconstruction_seconds
    ),
    sprintf("Reason: %s", decision$reason),
    sep = "\n"
  )
}
