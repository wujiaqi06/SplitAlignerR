## ARCH000A development-only byte-budgeted LRU stores.

a_lru_entry_accounted_bytes <- function(pattern_id, value,
                                         allocator_reserve_bytes = 2048) {
  as.numeric(object.size(list(pattern_id = pattern_id, value = value))) +
    as.numeric(allocator_reserve_bytes)
}

a_new_lru_truth_store <- function(registry, authority, budget_bytes,
                                  loader = NULL,
                                  strategy_name = "bounded_lru_recompute",
                                  allocator_reserve_bytes = 2048) {
  a_assert(length(budget_bytes) == 1L && is.finite(budget_bytes) &&
             budget_bytes > 0, "LRU budget must be one positive finite byte count.")
  if (is.null(loader)) {
    loader <- function(pattern_id) a_plan_for_pattern(registry, authority, pattern_id)
  }
  e <- new.env(parent = emptyenv())
  e$registry <- registry
  e$authority <- authority
  e$budget <- as.numeric(budget_bytes)
  e$reserve <- as.numeric(allocator_reserve_bytes)
  e$loader <- loader
  e$cache <- new.env(hash = TRUE, parent = emptyenv())
  e$sizes <- new.env(hash = TRUE, parent = emptyenv())
  e$order <- character()
  e$current <- 0
  e$peak <- 0
  e$requests <- 0L
  e$hits <- 0L
  e$misses <- 0L
  e$insertions <- 0L
  e$evictions <- 0L
  e$builds <- 0L
  e$load_seconds <- 0
  e$max_entry <- 0
  e$uncached_oversize <- 0L

  touch <- function(pattern_id) {
    e$order <- c(e$order[e$order != pattern_id], pattern_id)
  }
  evict_one <- function() {
    victim <- e$order[[1L]]
    bytes <- get(victim, e$sizes, inherits = FALSE)
    rm(list = victim, envir = e$cache)
    rm(list = victim, envir = e$sizes)
    e$order <- e$order[-1L]
    e$current <- e$current - bytes
    e$evictions <- e$evictions + 1L
  }
  e$get <- function(pattern_id) {
    e$requests <- e$requests + 1L
    if (exists(pattern_id, e$cache, inherits = FALSE)) {
      e$hits <- e$hits + 1L
      touch(pattern_id)
      return(get(pattern_id, e$cache, inherits = FALSE))
    }
    e$misses <- e$misses + 1L
    timed <- a_elapsed(e$loader(pattern_id))
    value <- timed$value
    e$load_seconds <- e$load_seconds + timed$seconds
    e$builds <- e$builds + 1L
    entry_bytes <- a_lru_entry_accounted_bytes(pattern_id, value, e$reserve)
    e$max_entry <- max(e$max_entry, entry_bytes)
    if (entry_bytes > e$budget) {
      e$uncached_oversize <- e$uncached_oversize + 1L
      return(value)
    }
    while (length(e$order) && e$current + entry_bytes > e$budget) evict_one()
    assign(pattern_id, value, e$cache)
    assign(pattern_id, entry_bytes, e$sizes)
    e$order <- c(e$order, pattern_id)
    e$current <- e$current + entry_bytes
    e$peak <- max(e$peak, e$current)
    e$insertions <- e$insertions + 1L
    a_assert(e$current <= e$budget, "LRU accounted bytes exceeded hard budget.")
    value
  }
  e$stats <- function() {
    actual <- as.numeric(object.size(as.list(e$cache, all.names = TRUE)))
    list(
      strategy = strategy_name,
      requests = e$requests,
      builds = e$builds,
      hits = e$hits,
      misses = e$misses,
      evictions = e$evictions,
      insertions = e$insertions,
      reloads = 0L,
      build_seconds = e$load_seconds,
      cache_budget_bytes = e$budget,
      cache_accounted_bytes = e$current,
      cache_peak_accounted_bytes = e$peak,
      cache_actual_bytes = actual,
      max_plan_bytes = e$max_entry,
      allocator_reserve_per_entry = e$reserve,
      uncached_oversize = e$uncached_oversize,
      hard_bound_bytes = e$budget + e$max_entry,
      budget_respected = e$peak <= e$budget
    )
  }
  e$close <- function() invisible(TRUE)
  class(e) <- c("arch000a_lru_truth_store", "environment")
  e
}

a_new_packed_body_lru <- function(disk_store, budget_bytes,
                                  allocator_reserve_bytes = 256) {
  a_assert(length(budget_bytes) == 1L && is.finite(budget_bytes) &&
             budget_bytes > 0, "Packed LRU budget must be positive.")
  e <- new.env(parent = emptyenv())
  e$disk <- disk_store
  e$budget <- as.numeric(budget_bytes)
  e$reserve <- as.numeric(allocator_reserve_bytes)
  e$cache <- new.env(hash = TRUE, parent = emptyenv())
  e$sizes <- new.env(hash = TRUE, parent = emptyenv())
  e$order <- character()
  e$current <- e$peak <- 0
  e$requests <- e$hits <- e$misses <- e$insertions <- e$evictions <- 0L
  e$decode_seconds <- 0
  e$max_decoded_plan_bytes <- 0

  touch <- function(pattern_id) {
    e$order <- c(e$order[e$order != pattern_id], pattern_id)
  }
  evict_one <- function() {
    victim <- e$order[[1L]]
    bytes <- get(victim, e$sizes, inherits = FALSE)
    rm(list = victim, envir = e$cache)
    rm(list = victim, envir = e$sizes)
    e$order <- e$order[-1L]
    e$current <- e$current - bytes
    e$evictions <- e$evictions + 1L
  }
  e$get_body <- function(pattern_id) {
    e$requests <- e$requests + 1L
    if (exists(pattern_id, e$cache, inherits = FALSE)) {
      e$hits <- e$hits + 1L
      touch(pattern_id)
      return(get(pattern_id, e$cache, inherits = FALSE))
    }
    e$misses <- e$misses + 1L
    body <- e$disk$get_body(pattern_id)
    entry_bytes <- a_lru_entry_accounted_bytes(pattern_id, body, e$reserve)
    if (entry_bytes <= e$budget) {
      while (length(e$order) && e$current + entry_bytes > e$budget) evict_one()
      assign(pattern_id, body, e$cache)
      assign(pattern_id, entry_bytes, e$sizes)
      e$order <- c(e$order, pattern_id)
      e$current <- e$current + entry_bytes
      e$peak <- max(e$peak, e$current)
      e$insertions <- e$insertions + 1L
    }
    a_assert(e$peak <= e$budget, "Packed LRU exceeded its hard byte budget.")
    body
  }
  e$get <- function(pattern_id) {
    body <- e$get_body(pattern_id)
    timed <- a_elapsed(e$disk$decode_body(body))
    e$decode_seconds <- e$decode_seconds + timed$seconds
    e$max_decoded_plan_bytes <- max(
      e$max_decoded_plan_bytes, as.numeric(object.size(timed$value))
    )
    timed$value
  }
  e$stats <- function() {
    disk_stats <- e$disk$stats()
    list(
      strategy = "packed_disk_plus_lru",
      requests = e$requests,
      builds = 0L,
      hits = e$hits,
      misses = e$misses,
      evictions = e$evictions,
      insertions = e$insertions,
      reloads = disk_stats$record_reads,
      build_seconds = 0,
      decode_seconds = e$decode_seconds,
      cache_budget_bytes = e$budget,
      cache_accounted_bytes = e$current,
      cache_peak_accounted_bytes = e$peak,
      cache_actual_bytes = as.numeric(object.size(as.list(e$cache, all.names = TRUE))),
      max_plan_bytes = e$max_decoded_plan_bytes,
      allocator_reserve_per_entry = e$reserve,
      hard_bound_bytes = e$budget + e$max_decoded_plan_bytes,
      budget_respected = e$peak <= e$budget,
      disk = disk_stats
    )
  }
  e$close <- function() invisible(TRUE)
  class(e) <- c("arch000a_packed_lru_store", "environment")
  e
}
