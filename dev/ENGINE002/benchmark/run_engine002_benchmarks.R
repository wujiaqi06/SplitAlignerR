#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3L) {
  stop("usage: run_engine002_benchmarks.R <installed-library> <output-dir> <record-count>")
}
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)
output_dir <- args[[2L]]
record_count <- as.integer(args[[3L]])
if (is.na(record_count) || record_count < 10000L || record_count > 100000L) {
  stop("record-count must be 10,000..100,000")
}
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

timed <- function(code) {
  before <- proc.time()
  value <- force(code)
  after <- proc.time() - before
  list(
    value = value,
    elapsed = unname(after[["elapsed"]]),
    user = unname(after[["user.self"]]),
    system = unname(after[["sys.self"]])
  )
}

result_rows <- list()
add_result <- function(workload, operation, repetition, count, timing,
                       bytes = NA_real_, status = "MEASURED",
                       notes = "") {
  result_rows[[length(result_rows) + 1L]] <<- data.frame(
    workload = workload,
    operation = operation,
    repetition = repetition,
    count = count,
    wall_seconds = timing$elapsed,
    user_seconds = timing$user,
    system_seconds = timing$system,
    operations_per_second = if (timing$elapsed > 0) {
      count / timing$elapsed
    } else {
      NA_real_
    },
    bytes = bytes,
    MB_per_second = if (is.na(bytes)) NA_real_ else
      if (timing$elapsed > 0) bytes / 1024^2 / timing$elapsed else NA_real_,
    status = status,
    notes = notes,
    stringsAsFactors = FALSE
  )
}

taxon_count <- 40L
labels <- sprintf("T%03d", 0:(taxon_count - 1L))
singleton <- c(as.raw(1L), raw(4L))
authority <- SplitAlignerR:::.engine002_authority(
  labels, 0L, list(singleton)
)
pattern_from_integer <- function(value) {
  bits <- raw(5L)
  bits[[1L]] <- as.raw(1L)
  x <- as.double(value)
  for (bit in 0:30) {
    if (x %% 2 >= 1) {
      taxon <- bit + 1L
      byte <- (taxon %/% 8L) + 1L
      offset <- taxon %% 8L
      bits[[byte]] <- as.raw(bitwOr(
        as.integer(bits[[byte]]), bitwShiftL(1L, offset)
      ))
    }
    x <- floor(x / 2)
  }
  bits
}
patterns <- lapply(seq_len(record_count), pattern_from_integer)
keys <- vapply(patterns, function(x) {
  paste(sprintf("%02x", as.integer(x)), collapse = "")
}, character(1))
patterns <- patterns[order(keys, method = "radix")]
raw_less <- function(left, right) {
  different <- which(as.integer(left) != as.integer(right))
  if (!length(different)) return(FALSE)
  at <- different[[1L]]
  as.integer(left[[at]]) < as.integer(right[[at]])
}
queries <- lapply(patterns, function(retained) {
  complement <- as.raw(bitwXor(as.integer(retained), as.integer(singleton)))
  if (sum(as.integer(intToBits(
        sum(as.integer(retained) * 256^(0:4))
      )[1:40])) == 2L &&
      raw_less(complement, singleton)) {
    complement
  } else {
    singleton
  }
})

encoded <- timed({
  lapply(seq_along(patterns), function(i) {
    SplitAlignerR:::.engine002_plan_encode(
      authority, i - 1L, patterns[[i]], 0L, list(queries[[i]])
    )
  })
})
records <- encoded$value
record_bytes <- sum(vapply(records, length, integer(1)))
add_result(
  "synthetic_storage_only", "encode", 1L, record_count, encoded,
  record_bytes, notes = "non-scientific deterministic unique retained patterns"
)
for (repetition in 2:3) {
  one <- timed({
    for (i in seq_along(patterns)) {
      SplitAlignerR:::.engine002_plan_encode(
        authority, i - 1L, patterns[[i]], 0L, list(queries[[i]])
      )
    }
  })
  add_result("synthetic_storage_only", "encode", repetition, record_count,
             one, record_bytes)
}

decode_count <- min(10000L, record_count)
for (repetition in 1:3) {
  one <- timed(lapply(records[seq_len(decode_count)], function(record) {
    SplitAlignerR:::.engine002_plan_decode(authority, record)
  }))
  add_result("synthetic_10000", "full_decode", repetition, decode_count, one,
             sum(vapply(records[seq_len(decode_count)], length, integer(1))))
  one <- timed(lapply(records[seq_len(decode_count)], function(record) {
    SplitAlignerR:::.engine002_plan_view_probe(
      authority, record, 0L, repeats = 1L
    )
  }))
  add_result("synthetic_10000", "validated_direct_view", repetition,
             decode_count, one)
}
for (repetition in 1:3) {
  one <- timed(SplitAlignerR:::.engine002_plan_view_probe(
    authority, records[[1L]], 0L, repeats = 100000L
  ))
  add_result("single_validated_view", "direct_primitive_query", repetition,
             100000L, one)
}

memory_rows <- list()
for (repetition in 1:3) {
  memory <- SplitAlignerR:::.engine002_memory_store(authority, decode_count)
  build <- timed(for (i in seq_len(decode_count)) {
    SplitAlignerR:::cpp_engine002_store_insert(memory, records[[i]])
  })
  add_result("synthetic_10000", "memory_build", repetition, decode_count, build)
  finalize <- timed(
    SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")
  )
  stats <- SplitAlignerR:::cpp_engine002_store_stats(memory)
  add_result("synthetic_10000", "memory_finalize", repetition, decode_count,
             finalize, stats$arena_bytes)
  lookup <- timed(for (i in seq_len(decode_count)) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      memory, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_10000", "memory_sequential_lookup", repetition,
             decode_count, lookup)
  memory_rows[[length(memory_rows) + 1L]] <- data.frame(
    workload = "synthetic_10000", repetition = repetition,
    arena_bytes = stats$arena_bytes, active_pins = stats$active_pins,
    stringsAsFactors = FALSE
  )
  SplitAlignerR:::cpp_engine002_store_close(memory)
}

MiB <- 1024^2
disk_rows <- list()
lru_rows <- list()
set.seed(20260803)
random_ids <- sample.int(record_count, record_count)
for (repetition in 1:3) {
  destination <- tempfile(
    sprintf("engine002-bench-r%d-", repetition), tmpdir = "/private/tmp"
  )
  dir.create(destination, mode = "0700")
  on.exit(unlink(destination, recursive = TRUE), add = TRUE)
  disk <- SplitAlignerR:::.engine002_disk_store(
    authority, record_count, 32 * MiB, MiB, 64 * MiB, MiB, 98 * MiB
  )
  build <- timed(for (i in seq_len(record_count)) {
    SplitAlignerR:::cpp_engine002_store_insert(disk, records[[i]])
  })
  add_result("synthetic_storage_only", "disk_build", repetition, record_count,
             build, record_bytes)
  run_id <- sprintf("%032x", repetition)
  publication <- timed(
    SplitAlignerR:::cpp_engine002_store_finalize(
      disk, destination, run_id
    )
  )
  manifest <- publication$value
  stats <- SplitAlignerR:::cpp_engine002_store_stats(disk)
  add_result("synthetic_storage_only", "disk_finalize_validate_publish",
             repetition, record_count, publication, stats$file_bytes)
  SplitAlignerR:::cpp_engine002_store_close(disk)

  reopened_time <- timed(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      authority, manifest, 32 * MiB, MiB, 64 * MiB, MiB, 98 * MiB
    )
  )
  reopened <- reopened_time$value
  add_result("synthetic_storage_only", "process_cold_reopen_full_validation",
             repetition, record_count, reopened_time, stats$file_bytes)
  cold <- timed(SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    reopened, 0, patterns[[1L]]
  ))
  add_result("synthetic_storage_only", "process_cold_first_lookup",
             repetition, 1L, cold)
  warm <- timed(SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    reopened, 0, patterns[[1L]]
  ))
  add_result("synthetic_storage_only", "warm_second_lookup",
             repetition, 1L, warm)
  sequential_ids <- seq_len(record_count)
  original <- timed(for (i in sequential_ids) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_storage_only", "original_order_lookup",
             repetition, length(sequential_ids), original)
  reversed <- timed(for (i in rev(sequential_ids)) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_storage_only", "reversed_order_lookup",
             repetition, length(sequential_ids), reversed)
  hot_ids <- seq_len(min(10000L, record_count))
  grouped_ids <- rep(hot_ids, each = 2L)
  grouped <- timed(for (i in grouped_ids) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_storage_only", "grouped_reuse_lookup",
             repetition, length(grouped_ids), grouped)
  interleaved_ids <- rep(hot_ids, 2L)
  interleaved <- timed(for (i in interleaved_ids) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_storage_only", "maximally_interleaved_reuse_lookup",
             repetition, length(interleaved_ids), interleaved)
  random <- timed(for (i in random_ids) {
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, i - 1L, patterns[[i]]
    )
  })
  add_result("synthetic_storage_only", "fixed_seed_random_lookup",
             repetition, length(random_ids), random)
  final_stats <- SplitAlignerR:::cpp_engine002_store_stats(reopened)
  lru_rows[[length(lru_rows) + 1L]] <- data.frame(
    workload = "synthetic_storage_only", repetition = repetition,
    cache_budget = 32 * MiB, scratch_budget = MiB,
    hits = final_stats$hits, misses = final_stats$misses,
    insertions = final_stats$insertions, evictions = final_stats$evictions,
    oversized_bypasses = final_stats$oversized_bypasses,
    pin_failures = final_stats$pin_failures,
    cache_high_water = final_stats$cache_high_water,
    scratch_high_water = final_stats$scratch_high_water,
    stringsAsFactors = FALSE
  )
  disk_rows[[length(disk_rows) + 1L]] <- data.frame(
    workload = "synthetic_storage_only", repetition = repetition,
    record_count = record_count, final_disk_bytes = final_stats$file_bytes,
    index_charged_bytes = final_stats$index_charged_bytes,
    metadata_charged_bytes = final_stats$metadata_charged_bytes,
    temporary_disk_high_water = final_stats$file_bytes * 2,
    temporary_disk_high_water_basis =
      "DERIVED: final component plus equal-size unpublished temporary",
    stringsAsFactors = FALSE
  )
  SplitAlignerR:::cpp_engine002_store_close(reopened)
  unlink(destination, recursive = TRUE)
}

utils::write.csv(
  do.call(rbind, result_rows),
  file.path(output_dir, "ENGINE002_RUNTIME_RESULTS.csv"), row.names = FALSE
)
utils::write.csv(
  do.call(rbind, memory_rows),
  file.path(output_dir, "ENGINE002_MEMORY_RESULTS.csv"), row.names = FALSE
)
utils::write.csv(
  do.call(rbind, lru_rows),
  file.path(output_dir, "ENGINE002_LRU_RESULTS.csv"), row.names = FALSE
)
utils::write.csv(
  do.call(rbind, disk_rows),
  file.path(output_dir, "ENGINE002_STORE_RESULTS.csv"), row.names = FALSE
)
writeLines(c(
  paste0("R=", R.version.string),
  paste0("platform=", R.version$platform),
  paste0("machine=", Sys.info()[["machine"]]),
  paste0("os=", Sys.info()[["sysname"]], " ", Sys.info()[["release"]]),
  paste0("record_count=", record_count),
  "seed=20260803",
  "authority=synthetic 40-taxon/one-terminal storage-only authority",
  "timing=proc.time; external peak RSS captured by wrapper"
), file.path(output_dir, "ENGINE002_BENCHMARK_ENVIRONMENT.txt"))
cat("ENGINE002_BENCHMARK_PASS\n")
cat("record_count=", record_count, "\n", sep = "")
cat("record_bytes=", record_bytes, "\n", sep = "")
