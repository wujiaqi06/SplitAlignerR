#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: store_smoke.R <installed-library>")
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

rb <- function(x) as.raw(x)
authority <- SplitAlignerR:::cpp_engine002_authority_create(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)

record0 <- SplitAlignerR:::cpp_engine002_plan_encode(
  authority, 0, rb(7L), c(0L, 2L, 2L, 1L, 0L),
  list(rb(1L), rb(2L), rb(2L), NULL, rb(4L))
)
record1 <- SplitAlignerR:::cpp_engine002_plan_encode(
  authority, 1, rb(15L), c(0L, 2L, 2L, 0L, 0L),
  lapply(c(1L, 3L, 3L, 8L, 5L), rb)
)

memory <- SplitAlignerR:::cpp_engine002_memory_store_create(authority, 2)
before_finalize <- tryCatch(
  SplitAlignerR:::cpp_engine002_store_lookup_snapshot(memory, 0, rb(7L)),
  error = conditionMessage
)
stopifnot(grepl("ENGINE_INVALID_STATE", before_finalize, fixed = TRUE))
stopifnot(SplitAlignerR:::cpp_engine002_store_insert(memory, record1))
stopifnot(SplitAlignerR:::cpp_engine002_store_insert(memory, record0))
stopifnot(isTRUE(SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")))
stopifnot(isTRUE(SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")))
mem0 <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(memory, 0, rb(7L))
stopifnot(identical(mem0$states, c(0L, 2L, 2L, 1L, 0L)))
pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(memory, 0, rb(7L))
busy <- tryCatch(SplitAlignerR:::cpp_engine002_store_close(memory),
                 error = conditionMessage)
stopifnot(grepl("ENGINE_STORE_BUSY", busy, fixed = TRUE))
stopifnot(SplitAlignerR:::cpp_engine002_pin_release(pin))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(memory))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(memory))

destination <- tempfile("engine002-store-", tmpdir = "/private/tmp")
dir.create(destination, mode = "0700")
run_id <- "0123456789abcdef0123456789abcdef"
MiB <- 1024^2
disk <- SplitAlignerR:::cpp_engine002_disk_store_create(
  authority, 2, 0, MiB, MiB, MiB, 3 * MiB
)
stopifnot(SplitAlignerR:::cpp_engine002_store_insert(disk, record1))
stopifnot(SplitAlignerR:::cpp_engine002_store_insert(disk, record0))
manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
  disk, destination, run_id
)
stopifnot(
  file.exists(manifest),
  file.exists(file.path(destination, paste0(run_id, ".truthstore.bin")))
)
disk0 <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(disk, 0, rb(7L))
disk1 <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(disk, 1, rb(15L))
stopifnot(identical(disk0, mem0), identical(disk1$states,
                                           c(0L, 2L, 2L, 0L, 0L)))
stats <- SplitAlignerR:::cpp_engine002_store_stats(disk)
stopifnot(stats$oversized_bypasses == 2, stats$charged_cache_bytes == 0,
          stats$scratch_high_water > 0, stats$scratch_high_water <= MiB)
stopifnot(SplitAlignerR:::cpp_engine002_store_close(disk))

reopened <- SplitAlignerR:::cpp_engine002_disk_store_open(
  authority, manifest, 64 * 1024, MiB, MiB, MiB, 3 * MiB + 64 * 1024
)
reopened0 <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
  reopened, 0, rb(7L)
)
stopifnot(identical(reopened0, mem0))
disk_pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(reopened, 0, rb(7L))
disk_busy <- tryCatch(SplitAlignerR:::cpp_engine002_store_close(reopened),
                      error = conditionMessage)
stopifnot(grepl("ENGINE_STORE_BUSY", disk_busy, fixed = TRUE))
stopifnot(SplitAlignerR:::cpp_engine002_pin_release(disk_pin))
stopifnot(SplitAlignerR:::cpp_engine002_store_close(reopened))

failed_destination <- tempfile("engine002-fail-", tmpdir = "/private/tmp")
dir.create(failed_destination, mode = "0700")
failed_id <- "fedcba9876543210fedcba9876543210"
failing <- SplitAlignerR:::cpp_engine002_disk_store_create(
  authority, 1, 0, MiB, MiB, MiB, 3 * MiB
)
one <- record0
one[13:20] <- writeBin(as.double(0), raw(), size = 8, endian = "little")
stopifnot(SplitAlignerR:::cpp_engine002_store_insert(failing, one))
stopifnot(SplitAlignerR:::cpp_engine002_set_publication_failpoint(7L))
injected <- tryCatch(
  SplitAlignerR:::cpp_engine002_store_finalize(
    failing, failed_destination, failed_id
  ), error = conditionMessage
)
stopifnot(grepl("ENGINE_IO_FAILURE", injected, fixed = TRUE))
stopifnot(!file.exists(file.path(
  failed_destination, paste0(failed_id, ".truthstore.manifest")
)))
stopifnot(SplitAlignerR:::cpp_engine002_set_publication_failpoint(0L))

cat("ENGINE002_STORE_SMOKE_PASS\n")
cat("store_bytes=", stats$file_bytes, "\n", sep = "")
cat("memory_arena_bytes=", length(record0) + length(record1), "\n", sep = "")
cat("validated_manifest=", manifest, "\n", sep = "")

