## ARCH000A development-only exact-byte B* pending-buffer stress helpers.

a_member_bytes <- function(member_ids) {
  member_ids <- sort(unique(as.integer(member_ids)), method = "radix")
  a_assert(length(member_ids) > 1L, "B* member set must be non-singleton.")
  writeBin(
    as.integer(c(length(member_ids), member_ids)), raw(),
    size = 4L, endian = "little"
  )
}

a_raw_hex <- function(value) {
  paste0(sprintf("%02x", as.integer(value)), collapse = "")
}

a_new_bstar_churn_buffer <- function(threshold_bytes = 64 * 1024) {
  a_assert(length(threshold_bytes) == 1L && is.finite(threshold_bytes) &&
             threshold_bytes > 0, "B* churn threshold must be positive.")
  e <- new.env(parent = emptyenv())
  e$threshold <- as.numeric(threshold_bytes)
  e$pending <- character()
  e$pending_bytes <- 0
  e$peak_pending_bytes <- 0
  e$global <- character()
  e$flushes <- 0L
  e$records_seen <- 0L
  e$encoded_bytes_seen <- 0
  e$records_per_flush <- integer()
  e$bytes_per_flush <- numeric()
  e$unique_growth <- integer()
  e$local_sort_seconds <- 0
  e$global_union_seconds <- 0

  e$flush <- function() {
    if (!length(e$pending)) return(invisible(TRUE))
    record_count <- length(e$pending)
    encoded_bytes <- e$pending_bytes
    timed <- a_elapsed(sort(unique(e$pending), method = "radix"))
    local <- timed$value
    e$local_sort_seconds <- e$local_sort_seconds + timed$seconds
    timed <- a_elapsed(arch_merge_sorted_unique(e$global, local))
    e$global <- timed$value
    e$global_union_seconds <- e$global_union_seconds + timed$seconds
    e$flushes <- e$flushes + 1L
    e$records_per_flush <- c(e$records_per_flush, record_count)
    e$bytes_per_flush <- c(e$bytes_per_flush, encoded_bytes)
    e$unique_growth <- c(e$unique_growth, length(e$global))
    e$pending <- character()
    e$pending_bytes <- 0
    invisible(TRUE)
  }

  e$add <- function(member_ids) {
    bytes <- a_member_bytes(member_ids)
    key <- a_raw_hex(bytes)
    e$pending <- c(e$pending, key)
    e$pending_bytes <- e$pending_bytes + length(bytes)
    e$peak_pending_bytes <- max(e$peak_pending_bytes, e$pending_bytes)
    e$records_seen <- e$records_seen + 1L
    e$encoded_bytes_seen <- e$encoded_bytes_seen + length(bytes)
    if (e$pending_bytes >= e$threshold) e$flush()
    invisible(key)
  }

  e$finalize <- function() {
    e$flush()
    e$global
  }

  e$stats <- function() list(
    threshold_bytes = e$threshold,
    records_seen = e$records_seen,
    canonical_member_set_encoded_bytes = e$encoded_bytes_seen,
    flush_count = e$flushes,
    records_per_flush = e$records_per_flush,
    bytes_per_flush = e$bytes_per_flush,
    local_sort_unique_seconds = e$local_sort_seconds,
    global_union_seconds = e$global_union_seconds,
    peak_pending_buffer_bytes = e$peak_pending_bytes,
    unique_bstar = length(e$global),
    unique_growth = e$unique_growth
  )
  e
}

a_bstar_exact_collision_gate <- function(member_sets) {
  exact_raw <- lapply(member_sets, a_member_bytes)
  exact_hex <- sort(unique(vapply(exact_raw, a_raw_hex, character(1))),
                    method = "radix")
  forced_hash <- rep.int("forced-collision", length(exact_raw))
  buckets <- split(seq_along(exact_raw), forced_hash, drop = TRUE)
  collision_resolved <- sort(unique(unlist(lapply(buckets, function(index) {
    exact_bucket <- new.env(hash = TRUE, parent = emptyenv())
    for (candidate in exact_raw[index]) {
      exact_key <- a_raw_hex(candidate)
      if (exists(exact_key, exact_bucket, inherits = FALSE)) {
        a_assert(
          identical(get(exact_key, exact_bucket, inherits = FALSE), candidate),
          "Exact B* byte key resolved to non-identical member bytes."
        )
      } else {
        assign(exact_key, candidate, exact_bucket)
      }
    }
    ls(exact_bucket, all.names = TRUE)
  }), use.names = FALSE)), method = "radix")
  identical(collision_resolved, exact_hex)
}
