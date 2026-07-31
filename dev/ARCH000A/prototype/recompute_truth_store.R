## ARCH000A development-only recompute-on-demand truth-plan store.

a_plan_for_pattern <- function(registry, authority, pattern_id) {
  retained <- a_registry_retained_ids(registry, pattern_id)
  plan <- arch_build_truth_plan(authority, retained)
  plan$bytes <- as.numeric(object.size(plan))
  plan
}

a_plan_scientific_equal <- function(observed, expected, authority) {
  same_composites <- function(left, right) {
    left_keys <- names(left)
    right_keys <- names(right)
    if (is.null(left_keys)) left_keys <- character()
    if (is.null(right_keys)) right_keys <- character()
    left_keys <- sort(left_keys, method = "radix")
    right_keys <- sort(right_keys, method = "radix")
    if (!identical(left_keys, right_keys)) return(FALSE)
    all(vapply(left_keys, function(key) {
      identical(left[[key]]$members, right[[key]]$members) &&
        identical(left[[key]]$projected_split, right[[key]]$projected_split)
    }, logical(1)))
  }
    identical(observed$retained_ids, expected$retained_ids) &&
    identical(observed$state_template, expected$state_template) &&
    identical(observed$projected_split, expected$projected_split) &&
    identical(observed$eligible, expected$eligible) &&
    same_composites(observed$composites, expected$composites)
}

a_new_recompute_store <- function(registry, authority) {
  e <- new.env(parent = emptyenv())
  e$registry <- registry
  e$authority <- authority
  e$builds <- 0L
  e$requests <- 0L
  e$build_seconds <- 0
  e$max_plan_bytes <- 0
  e$get <- function(pattern_id) {
    e$requests <- e$requests + 1L
    timed <- a_elapsed(a_plan_for_pattern(e$registry, e$authority, pattern_id))
    e$builds <- e$builds + 1L
    e$build_seconds <- e$build_seconds + timed$seconds
    e$max_plan_bytes <- max(e$max_plan_bytes, as.numeric(object.size(timed$value)))
    timed$value
  }
  e$stats <- function() list(
    strategy = "recompute",
    requests = e$requests,
    builds = e$builds,
    hits = 0L,
    misses = e$requests,
    evictions = 0L,
    reloads = 0L,
    build_seconds = e$build_seconds,
    cache_budget_bytes = 0,
    cache_accounted_bytes = 0,
    cache_peak_accounted_bytes = 0,
    cache_actual_bytes = 0,
    max_plan_bytes = e$max_plan_bytes,
    hard_bound_bytes = e$max_plan_bytes
  )
  e$close <- function() invisible(TRUE)
  class(e) <- c("arch000a_recompute_store", "environment")
  e
}

a_new_retain_all_store <- function(registry, authority, loader = NULL) {
  if (is.null(loader)) {
    loader <- function(pattern_id) a_plan_for_pattern(registry, authority, pattern_id)
  }
  timed <- a_elapsed({
    plans <- lapply(registry$pattern_ids, loader)
    names(plans) <- registry$pattern_ids
    plans
  })
  plans <- timed$value
  plan_bytes <- vapply(plans, function(x) as.numeric(object.size(x)), numeric(1))
  e <- new.env(parent = emptyenv())
  e$plans <- plans
  e$requests <- 0L
  e$build_seconds <- timed$seconds
  e$get <- function(pattern_id) {
    e$requests <- e$requests + 1L
    plan <- e$plans[[pattern_id]]
    if (is.null(plan)) a_stop(sprintf("Unknown retain-all pattern: %s", pattern_id))
    plan
  }
  e$stats <- function() list(
    strategy = "retain_all",
    requests = e$requests,
    builds = length(e$plans),
    hits = e$requests,
    misses = 0L,
    evictions = 0L,
    reloads = 0L,
    build_seconds = e$build_seconds,
    cache_budget_bytes = Inf,
    cache_accounted_bytes = sum(plan_bytes),
    cache_peak_accounted_bytes = sum(plan_bytes),
    cache_actual_bytes = as.numeric(object.size(e$plans)),
    max_plan_bytes = if (length(plan_bytes)) max(plan_bytes) else 0,
    hard_bound_bytes = NA_real_
  )
  e$close <- function() invisible(TRUE)
  class(e) <- c("arch000a_retain_all_store", "environment")
  e
}
