#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5L) {
  stop(
    paste(
      "usage: fix001a_platform_evidence.R <repo> <installed-library>",
      "<authority-examples> <output-dir> <platform-key>"
    ),
    call. = FALSE
  )
}

repo <- normalizePath(args[[1L]], mustWork = TRUE)
library_dir <- normalizePath(args[[2L]], mustWork = TRUE)
authority_root <- normalizePath(args[[3L]], mustWork = TRUE)
output_dir <- normalizePath(args[[4L]], mustWork = TRUE)
platform_key <- args[[5L]]
.libPaths(c(library_dir, .libPaths()))
library(SplitAlignerR)
if (!requireNamespace("digest", quietly = TRUE)) {
  stop("FIX001A evidence requires the CI-only digest package", call. = FALSE)
}

source(file.path(repo, "dev/ARCH000/prototype/arch000_common.R"))
source(file.path(repo, "dev/ARCH000A/prototype/compact_pattern_registry.R"))
source(file.path(repo, "tools/engine002/authority_helpers.R"))

MiB <- 1024^2
safe_tempdir <- normalizePath(tempdir(), mustWork = TRUE)
rb <- function(x) as.raw(x)
hash_file <- function(path) {
  digest::digest(path, algo = "sha256", serialize = FALSE, file = TRUE)
}
read_all_raw <- function(path) {
  readBin(path, raw(), n = file.info(path)$size)
}
write_all_raw <- function(value, path) {
  connection <- file(path, open = "wb")
  on.exit(close(connection))
  writeBin(value, connection, useBytes = TRUE)
}
capture_error <- function(expression, code) {
  message <- tryCatch({
    force(expression)
    NA_character_
  }, error = conditionMessage)
  if (is.na(message) || !grepl(code, message, fixed = TRUE)) {
    stop("expected ", code, "; observed: ", message, call. = FALSE)
  }
  invisible(message)
}
u64 <- function(bytes, zero_offset) {
  values <- as.double(as.integer(
    bytes[(zero_offset + 1L):(zero_offset + 8L)]
  ))
  sum(values * 256^(0:7))
}
hex_to_raw <- function(value) {
  starts <- seq.int(1L, nchar(value), by = 2L)
  as.raw(strtoi(substring(value, starts, starts + 1L), base = 16L))
}
raw_to_hex <- function(value) {
  paste(sprintf("%02x", as.integer(value)), collapse = "")
}

small_authority <- function(labels = c("A", "B", "C", "D")) {
  SplitAlignerR:::.engine002_authority(
    labels, c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), rb)
  )
}
small_records <- function(authority) {
  list(
    SplitAlignerR:::.engine002_plan_encode(
      authority, 0, rb(3L), c(2L, 2L, 1L, 1L, 1L),
      list(rb(1L), rb(1L), NULL, NULL, NULL)
    ),
    SplitAlignerR:::.engine002_plan_encode(
      authority, 1, rb(7L), c(0L, 0L, 2L, 1L, 2L),
      list(rb(1L), rb(2L), rb(4L), NULL, rb(4L))
    )
  )
}
build_small_store <- function(authority, records, root, run_id) {
  patterns <- lapply(records, function(record) {
    SplitAlignerR:::.engine002_plan_decode(authority, record)$retained
  })
  store <- SplitAlignerR:::.engine002_disk_store(
    authority, patterns, root, run_id,
    64 * 1024, MiB, MiB, MiB, 3 * MiB + 64 * 1024
  )
  for (record in records) {
    SplitAlignerR:::cpp_engine002_store_insert(store, record)
  }
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(store, root, run_id)
  list(store = store, manifest = manifest,
       component = sub("[.]manifest$", ".bin", manifest))
}

# Frozen golden plan: decode, validate, re-encode and preserve exact bytes.
authority <- small_authority()
records <- small_records(authority)
plan_fixture <- file.path(
  repo, "tests/testthat/fixtures/engine002/plan_three_taxon_dense_v1.hex"
)
expected_plan <- hex_to_raw(readLines(plan_fixture, warn = FALSE)[[1L]])
decoded_plan <- SplitAlignerR:::.engine002_plan_decode(authority, expected_plan)
direct_plan <- SplitAlignerR:::.engine002_plan_view_snapshot(
  authority, expected_plan
)
stopifnot(identical(decoded_plan, direct_plan))
reencoded_plan <- SplitAlignerR:::.engine002_plan_encode(
  authority, decoded_plan$pattern_id, decoded_plan$retained,
  decoded_plan$states, decoded_plan$primitive_queries
)
stopifnot(identical(expected_plan, reencoded_plan))
plan_output <- file.path(output_dir, "golden_plan.bin")
write_all_raw(reencoded_plan, plan_output)

# Frozen golden store: exact header/index/footer/manifest bytes.
store_root <- tempfile("fix001a-golden-store-", tmpdir = safe_tempdir)
dir.create(store_root, mode = "0700")
on.exit(unlink(store_root, recursive = TRUE, force = TRUE), add = TRUE)
run_id <- "0123456789abcdef0123456789abcdef"
built <- build_small_store(authority, records, store_root, run_id)
component_bytes <- read_all_raw(built$component)
manifest_bytes <- read_all_raw(built$manifest)
fixture <- utils::read.delim(
  file.path(repo, "tests/testthat/fixtures/engine002/store_two_pattern_v1.tsv"),
  header = FALSE, quote = "", stringsAsFactors = FALSE
)
expected <- stats::setNames(fixture[[2L]], fixture[[1L]])
index_offset <- u64(component_bytes, 56L)
footer_offset <- u64(component_bytes, 64L)
stopifnot(
  identical(raw_to_hex(component_bytes[1:256]), expected[["store_header"]]),
  identical(
    raw_to_hex(component_bytes[(index_offset + 1L):footer_offset]),
    expected[["index"]]
  ),
  identical(
    raw_to_hex(component_bytes[(footer_offset + 1L):length(component_bytes)]),
    expected[["footer"]]
  ),
  identical(raw_to_hex(manifest_bytes), expected[["manifest_hex"]]),
  identical(as.character(length(component_bytes)), expected[["store_bytes"]])
)
file.copy(built$component, file.path(output_dir, "golden_store.bin"),
          overwrite = TRUE)
file.copy(built$manifest, file.path(output_dir, "golden_store.manifest"),
          overwrite = TRUE)

# R/XPtr lifecycle and no-replace behavior on the actual platform.
pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(
  built$store, 0, rb(3L)
)
capture_error(
  SplitAlignerR:::cpp_engine002_store_close(built$store),
  "ENGINE_STORE_BUSY"
)
stopifnot(SplitAlignerR:::cpp_engine002_pin_release(pin))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(built$store))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(built$store))
capture_error(
  SplitAlignerR:::cpp_engine002_store_stats(built$store),
  "ENGINE_CONTEXT_CLOSED"
)

reopened <- SplitAlignerR:::cpp_engine002_disk_store_open(
  authority, built$manifest, 64 * 1024, MiB, MiB, MiB,
  3 * MiB + 64 * 1024
)
stopifnot(identical(
  SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    reopened, 1, rb(7L)
  )$states,
  c(0L, 0L, 2L, 1L, 2L)
))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(reopened))

duplicate <- SplitAlignerR:::.engine002_disk_store(
  authority, lapply(records, function(record) {
    SplitAlignerR:::.engine002_plan_decode(authority, record)$retained
  }), store_root, run_id, 0, MiB, MiB, MiB, 3 * MiB
)
for (record in records) {
  SplitAlignerR:::cpp_engine002_store_insert(duplicate, record)
}
before_no_replace <- read_all_raw(built$component)
capture_error(
  SplitAlignerR:::cpp_engine002_store_finalize(duplicate, store_root, run_id),
  "ENGINE_"
)
stopifnot(identical(before_no_replace, read_all_raw(built$component)))

wrong_authority <- small_authority(c("A", "B", "C", "X"))
capture_error(
  SplitAlignerR:::cpp_engine002_disk_store_open(
    wrong_authority, built$manifest, 0, MiB, MiB, MiB, 3 * MiB
  ),
  "ENGINE_AUTHORITY_MISMATCH"
)
capture_error(
  SplitAlignerR:::cpp_engine002_disk_store_open(
    authority, file.path(store_root, "missing.manifest"),
    0, MiB, MiB, MiB, 3 * MiB
  ),
  "ENGINE_"
)
invalid_manifest <- file.path(store_root, "invalid.truthstore.manifest")
invalid_text <- readLines(built$manifest, warn = FALSE)
invalid_text <- sub(
  "^completion_state=VALIDATED$", "completion_state=INCOMPLETE", invalid_text
)
writeLines(invalid_text, invalid_manifest, useBytes = TRUE)
capture_error(
  SplitAlignerR:::cpp_engine002_disk_store_open(
    authority, invalid_manifest, 0, MiB, MiB, MiB, 3 * MiB
  ),
  "ENGINE_"
)

# A separate R process must reopen a completed store.
session_root <- tempfile("fix001a-new-session-", tmpdir = safe_tempdir)
dir.create(session_root, mode = "0700")
on.exit(unlink(session_root, recursive = TRUE, force = TRUE), add = TRUE)
rscript <- file.path(R.home("bin"), paste0("Rscript", if (.Platform$OS.type == "windows") ".exe" else ""))
prepare_log <- file.path(output_dir, "new_session_prepare.log")
reopen_log <- file.path(output_dir, "new_session_reopen.log")
prepare_status <- system2(
  rscript,
  shQuote(c(
    file.path(repo, "tools/engine002/new_session_prepare.R"),
    library_dir, session_root
  )),
  stdout = prepare_log, stderr = prepare_log
)
reopen_status <- system2(
  rscript,
  shQuote(c(
    file.path(repo, "tools/engine002/new_session_reopen.R"),
    library_dir, session_root
  )),
  stdout = reopen_log, stderr = reopen_log
)
stopifnot(identical(prepare_status, 0L), identical(reopen_status, 0L))

# Corruption is rejected after all valid reopen/no-replace checks.
corrupted <- component_bytes
corrupted[[257L]] <- as.raw(bitwXor(as.integer(corrupted[[257L]]), 1L))
write_all_raw(corrupted, built$component)
capture_error(
  SplitAlignerR:::cpp_engine002_disk_store_open(
    authority, built$manifest, 0, MiB, MiB, MiB, 3 * MiB
  ),
  "ENGINE_"
)

# Finalizers are no-throw under repeated XPtr/active-pin GC.
for (i in seq_len(50L)) {
  local({
    memory <- SplitAlignerR:::.engine002_memory_store(authority, 1)
    SplitAlignerR:::cpp_engine002_store_insert(memory, records[[1L]])
    SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")
    pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(memory, 0, rb(3L))
    invisible(NULL)
  })
  if (i %% 5L == 0L) gc()
}
gc()

# Exact u64 arithmetic beyond 4 GiB; doubles remain exact below 2^53.
large <- SplitAlignerR:::.engine002_large_offset_arithmetic_probe(16000, 275000)
stopifnot(
  identical(large$records_bytes, 4400000000),
  identical(large$index_offset, 4400000256),
  isTRUE(large$crosses_2GiB),
  isTRUE(large$crosses_4GiB),
  large$footer_offset > 2^32,
  large$file_bytes > 2^32
)

# Full frozen 1,974-pattern authority through the installed R/C++ boundary.
species <- file.path(authority_root, "302mammal/input/speciesTree302.nwk")
fixed <- file.path(authority_root, "preprint_302mammal/input/fix.2275genes.nwk")
free <- file.path(authority_root, "preprint_302mammal/input/free.2275genes.nwk")
stopifnot(file.exists(species), file.exists(fixed), file.exists(free))

reference_authority <- arch_species_authority(species)
fixed_scan <- a_scan_gene_patterns(fixed, reference_authority)
free_scan <- a_scan_gene_patterns(free, reference_authority)
registry <- a_make_pattern_registry(
  list(fixed_scan, free_scan), reference_authority
)
stopifnot(length(registry$pattern_ids) == 1974L)
full_authority <- engine002_make_authority(reference_authority)
terminal <- which(reference_authority$branch_type == "terminal")

reference_started <- proc.time()[["elapsed"]]
retained_sets <- vector("list", length(registry$pattern_ids))
reference_plans <- vector("list", length(registry$pattern_ids))
reference_queries <- vector("list", length(registry$pattern_ids))
for (i in seq_along(registry$pattern_ids)) {
  retained_sets[[i]] <- a_unpack_ids(
    registry$exact_pattern_bits[[i]], registry$universe_size
  )
  reference_plans[[i]] <- arch_build_truth_plan(
    reference_authority, retained_sets[[i]]
  )
  reference_queries[[i]] <- engine002_plan_queries(
    reference_authority, retained_sets[[i]],
    reference_plans[[i]]$state_template
  )
}
reference_precompute_seconds <- unname(
  proc.time()[["elapsed"]] - reference_started
)

run_authority <- function(repetition, keep_records = FALSE) {
  record_path <- tempfile(
    sprintf("fix001a-authority-%s-%d-", platform_key, repetition),
    tmpdir = safe_tempdir
  )
  connection <- file(record_path, open = "wb")
  connection_open <- TRUE
  records_out <- if (keep_records) {
    vector("list", length(registry$pattern_ids))
  } else {
    NULL
  }
  phase <- c(encode = 0, decode = 0, direct_view = 0, reencode = 0)
  started <- proc.time()[["elapsed"]]
  on.exit({
    if (connection_open) close(connection)
    unlink(record_path, force = TRUE)
  }, add = TRUE)
  for (i in seq_along(registry$pattern_ids)) {
    retained <- retained_sets[[i]]
    reference <- reference_plans[[i]]
    queries <- reference_queries[[i]]

    phase_start <- proc.time()[["elapsed"]]
    record <- SplitAlignerR:::.engine002_plan_encode(
      full_authority, i - 1L, registry$exact_pattern_bits[[i]],
      reference$state_template, queries
    )
    phase[["encode"]] <- phase[["encode"]] +
      proc.time()[["elapsed"]] - phase_start
    phase_start <- proc.time()[["elapsed"]]
    decoded <- SplitAlignerR:::.engine002_plan_decode(full_authority, record)
    phase[["decode"]] <- phase[["decode"]] +
      proc.time()[["elapsed"]] - phase_start
    phase_start <- proc.time()[["elapsed"]]
    view <- SplitAlignerR:::.engine002_plan_view_snapshot(
      full_authority, record
    )
    phase[["direct_view"]] <- phase[["direct_view"]] +
      proc.time()[["elapsed"]] - phase_start

    equal <- engine002_plan_equal_reference(decoded, reference, queries)
    if (!isTRUE(equal) || !identical(decoded, view)) {
      stop("1,974 authority mismatch at pattern ", i - 1L, call. = FALSE)
    }
    decoded_keys <- vapply(decoded$fibers, function(members) {
      paste0(
        "BM1:",
        paste(sprintf("%08x", sort(as.integer(members) + 1L)), collapse = ".")
      )
    }, character(1))
    reference_keys <- vapply(reference$composites, `[[`, character(1), "key")
    if (!identical(
      unname(sort(decoded_keys, method = "radix")),
      unname(sort(reference_keys, method = "radix"))
    )) {
      stop("composite coordinate identity mismatch at pattern ", i - 1L,
           call. = FALSE)
    }
    if (length(reference_keys)) {
      decoded_query <- stats::setNames(decoded$fiber_queries, decoded_keys)
      reference_query <- stats::setNames(lapply(reference$composites, function(x) {
        queries[[x$members[[1L]]]]
      }), reference_keys)
      order_keys <- sort(reference_keys, method = "radix")
      if (!identical(decoded_query[order_keys], reference_query[order_keys])) {
        stop("composite query mismatch at pattern ", i - 1L, call. = FALSE)
      }
    }
    retained_terminal <- vapply(terminal, function(branch) {
      length(intersect(reference_authority$side_a[[branch]], retained)) > 0L &&
        length(intersect(reference_authority$side_b[[branch]], retained)) > 0L
    }, logical(1))
    if (any(decoded$states[terminal[retained_terminal]] == 1L)) {
      stop("terminal invariant mismatch at pattern ", i - 1L, call. = FALSE)
    }

    phase_start <- proc.time()[["elapsed"]]
    reencoded <- SplitAlignerR:::.engine002_plan_encode(
      full_authority, decoded$pattern_id, decoded$retained,
      decoded$states, decoded$primitive_queries
    )
    phase[["reencode"]] <- phase[["reencode"]] +
      proc.time()[["elapsed"]] - phase_start
    if (!identical(record, reencoded)) {
      stop("authority re-encode mismatch at pattern ", i - 1L, call. = FALSE)
    }
    writeBin(record, connection, useBytes = TRUE)
    if (keep_records) records_out[[i]] <- record
  }
  close(connection)
  connection_open <- FALSE
  elapsed <- unname(proc.time()[["elapsed"]] - started)
  list(
    hash = hash_file(record_path), elapsed = elapsed,
    phase = phase, records = records_out,
    record_bytes = file.info(record_path)$size
  )
}

authority_runs <- vector("list", 3L)
for (repetition in seq_len(3L)) {
  authority_runs[[repetition]] <- run_authority(
    repetition, keep_records = repetition == 1L
  )
}
authority_hashes <- vapply(authority_runs, `[[`, character(1), "hash")
stopifnot(length(unique(authority_hashes)) == 1L)

# Time the in-memory store separately from record encoding.  This is a
# diagnostic phase measurement, not a controlled cross-runner comparison.
memory_build_started <- proc.time()[["elapsed"]]
authority_memory <- SplitAlignerR:::.engine002_memory_store(
  full_authority, length(authority_runs[[1L]]$records)
)
for (record in authority_runs[[1L]]$records) {
  SplitAlignerR:::cpp_engine002_store_insert(authority_memory, record)
}
memory_build_seconds <- unname(
  proc.time()[["elapsed"]] - memory_build_started
)
memory_finalize_started <- proc.time()[["elapsed"]]
stopifnot(SplitAlignerR:::cpp_engine002_store_finalize(
  authority_memory, "", ""
))
memory_finalize_seconds <- unname(
  proc.time()[["elapsed"]] - memory_finalize_started
)
stopifnot(SplitAlignerR:::cpp_engine002_store_close(authority_memory))

authority_store_root <- tempfile(
  "fix001a-authority-store-", tmpdir = safe_tempdir
)
dir.create(authority_store_root, mode = "0700")
on.exit(unlink(authority_store_root, recursive = TRUE, force = TRUE), add = TRUE)
authority_run_id <- "dddddddddddddddddddddddddddddddd"
authority_disk <- SplitAlignerR:::.engine002_disk_store(
  full_authority, registry$exact_pattern_bits, authority_store_root,
  authority_run_id, 64 * MiB, MiB, MiB, MiB, 67 * MiB
)
disk_build_started <- proc.time()[["elapsed"]]
for (record in authority_runs[[1L]]$records) {
  SplitAlignerR:::cpp_engine002_store_insert(authority_disk, record)
}
disk_build_seconds <- unname(proc.time()[["elapsed"]] - disk_build_started)
disk_finalize_started <- proc.time()[["elapsed"]]
authority_manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
  authority_disk, authority_store_root, authority_run_id
)
disk_finalize_seconds <- unname(
  proc.time()[["elapsed"]] - disk_finalize_started
)
authority_component <- sub("[.]manifest$", ".bin", authority_manifest)
authority_store_stats <- SplitAlignerR:::cpp_engine002_store_stats(authority_disk)
set.seed(2002L)
random_ids <- unique(c(0L, 1L, 986L, 1973L, sample.int(1974L, 25L) - 1L))
lookup_started <- proc.time()[["elapsed"]]
for (id in random_ids) {
  got <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    authority_disk, id, registry$exact_pattern_bits[[id + 1L]]
  )
  stopifnot(identical(
    got$states,
    SplitAlignerR:::.engine002_plan_decode(
      full_authority, authority_runs[[1L]]$records[[id + 1L]]
    )$states
  ))
}
lookup_seconds <- unname(proc.time()[["elapsed"]] - lookup_started)
SplitAlignerR:::cpp_engine002_store_close(authority_disk)
disk_reopen_started <- proc.time()[["elapsed"]]
authority_reopened <- SplitAlignerR:::cpp_engine002_disk_store_open(
  full_authority, authority_manifest, 64 * MiB, MiB, MiB, MiB, 67 * MiB
)
disk_reopen_seconds <- unname(
  proc.time()[["elapsed"]] - disk_reopen_started
)
last <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
  authority_reopened, 1973, registry$exact_pattern_bits[[1974L]]
)
stopifnot(identical(last$pattern_id, 1973))
SplitAlignerR:::cpp_engine002_store_close(authority_reopened)

# Windows executes a real, bounded authority-shaped store plus no-truncation probe.
windows_physical <- list(status = "NOT_APPLICABLE", count = 0,
                         file_bytes = 0, last_lookup = FALSE)
if (identical(.Platform$OS.type, "windows")) {
  windows_root <- tempfile(
    "fix001a-windows-physical-", tmpdir = safe_tempdir
  )
  dir.create(windows_root, mode = "0700")
  on.exit(unlink(windows_root, recursive = TRUE, force = TRUE), add = TRUE)
  windows_count <- as.double(Sys.getenv(
    "SPLITALIGNERR_FIX001A_WINDOWS_PHYSICAL_COUNT", "10000"
  ))
  index_budget <- max(64 * MiB, windows_count * 320)
  physical <- SplitAlignerR:::cpp_engine002_build_authority_scale_store(
    windows_root, "feedfacefeedfacefeedfacefeedface", windows_count,
    0, MiB, index_budget, MiB, index_budget + 2 * MiB
  )
  reopened_physical <- SplitAlignerR:::cpp_engine002_reopen_authority_scale_store(
    physical$manifest, windows_count,
    0, MiB, index_budget, MiB, index_budget + 2 * MiB
  )
  stopifnot(
    identical(reopened_physical$last_pattern_id, windows_count - 1),
    identical(reopened_physical$file_bytes, physical$final_store_bytes)
  )
  windows_physical <- list(
    status = "PASS", count = windows_count,
    file_bytes = physical$final_store_bytes, last_lookup = TRUE
  )
}

rss <- if (requireNamespace("ps", quietly = TRUE)) {
  as.numeric(ps::ps_memory_info(ps::ps_handle())[["rss"]])
} else {
  NA_real_
}

deterministic <- c(
  paste0("platform_key=", platform_key),
  "status=PASS",
  paste0("golden_plan_sha256=", hash_file(plan_output)),
  paste0("golden_store_component_sha256=", hash_file(file.path(
    output_dir, "golden_store.bin"
  ))),
  paste0("golden_store_manifest_sha256=", hash_file(file.path(
    output_dir, "golden_store.manifest"
  ))),
  paste0("authority_records_sha256=", authority_hashes[[1L]]),
  paste0("authority_store_component_sha256=", hash_file(authority_component)),
  paste0("authority_store_manifest_sha256=", hash_file(authority_manifest))
)
writeLines(
  deterministic,
  file.path(output_dir, "deterministic_hashes.txt"),
  useBytes = TRUE
)

authority_elapsed <- vapply(authority_runs, `[[`, numeric(1), "elapsed")
runtime <- data.frame(
  platform = platform_key,
  operation = c(
    paste0("authority_1974_rep", 1:3),
    "authority_reference_precompute", "authority_encode", "authority_decode",
    "authority_direct_view", "authority_reencode", "memory_store_build",
    "memory_store_finalize", "disk_store_build", "disk_store_finalize",
    "disk_store_reopen", "random_lookup"
  ),
  seconds = c(
    authority_elapsed,
    reference_precompute_seconds, unname(authority_runs[[1L]]$phase),
    memory_build_seconds, memory_finalize_seconds, disk_build_seconds,
    disk_finalize_seconds, disk_reopen_seconds, lookup_seconds
  ),
  stringsAsFactors = FALSE
)
utils::write.csv(
  runtime, file.path(output_dir, "runtime_results.csv"),
  row.names = FALSE, quote = TRUE, na = "NA"
)

platform_lines <- c(
  "status=PASS",
  paste0("platform_key=", platform_key),
  "runtime_label=HOSTED-RUNNER DIAGNOSTIC - NOT A CONTROLLED CROSS-PLATFORM PERFORMANCE COMPARISON",
  paste0("R_version=", R.version.string),
  paste0("OS_type=", .Platform$OS.type),
  paste0("sysname=", Sys.info()[["sysname"]]),
  "golden_plan_decode_reencode=PASS",
  "golden_store_validate_reopen=PASS",
  "binary_no_crlf_exact_bytes=PASS",
  "R_lifecycle_active_pin_busy=PASS",
  "R_lifecycle_release_close_double_close=PASS",
  "R_lifecycle_read_after_close=PASS",
  "R_lifecycle_GC_XPtr=PASS",
  "new_R_process_reopen=PASS",
  "wrong_authority_rejection=PASS",
  "corruption_rejection=PASS",
  "missing_or_unvalidated_manifest_rejection=PASS",
  "atomic_no_replace_preexisting_rejection=PASS",
  "atomic_no_replace_original_bytes_preserved=PASS",
  "u64_offset_above_4GiB=PASS",
  "C_long_truncation_runtime_probe=PASS",
  "authority_1974=PASS",
  "authority_retained_taxa=1974/1974",
  "authority_primitive_truth_state=1974/1974",
  "authority_eligible_coordinate=1974/1974",
  "authority_projected_query=1974/1974",
  "authority_fiber=1974/1974",
  "authority_composite_member_set=1974/1974",
  "authority_composite_query=1974/1974",
  "authority_encode_decode_reencode=1974/1974",
  "authority_direct_view=1974/1974",
  "authority_terminal_invariant=1974/1974",
  paste0("authority_runtime_seconds=", paste(
    sprintf("%.6f", authority_elapsed), collapse = ","
  )),
  paste0("authority_runtime_median_seconds=", sprintf(
    "%.6f", stats::median(authority_elapsed)
  )),
  paste0("authority_runtime_range_seconds=", paste(
    sprintf("%.6f", range(authority_elapsed)), collapse = ","
  )),
  paste0("authority_reference_precompute_seconds=", sprintf(
    "%.6f", reference_precompute_seconds
  )),
  paste0("authority_record_bytes=", authority_runs[[1L]]$record_bytes),
  paste0("authority_store_bytes=", authority_store_stats$file_bytes),
  paste0("memory_store_build_seconds=", sprintf(
    "%.6f", memory_build_seconds
  )),
  paste0("memory_store_finalize_seconds=", sprintf(
    "%.6f", memory_finalize_seconds
  )),
  paste0("disk_store_build_seconds=", sprintf("%.6f", disk_build_seconds)),
  paste0("disk_store_finalize_seconds=", sprintf(
    "%.6f", disk_finalize_seconds
  )),
  paste0("disk_store_reopen_seconds=", sprintf(
    "%.6f", disk_reopen_seconds
  )),
  paste0("random_lookup_seconds=", sprintf("%.6f", lookup_seconds)),
  paste0("peak_RSS_bytes=", if (is.na(rss)) "NOT_MEASURED" else rss),
  paste0("windows_physical_store_status=", windows_physical$status),
  paste0("windows_physical_store_patterns=", windows_physical$count),
  paste0("windows_physical_store_bytes=", windows_physical$file_bytes),
  paste0("windows_physical_last_record_lookup=", windows_physical$last_lookup)
)
writeLines(
  platform_lines,
  file.path(output_dir, "platform_results.txt"),
  useBytes = TRUE
)
cat(paste(platform_lines, collapse = "\n"), "\n", sep = "")
