#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: store_golden.R <installed-library>")
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

rb <- function(x) as.raw(x)
authority <- SplitAlignerR:::.engine002_authority(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)
records <- list(
  SplitAlignerR:::.engine002_plan_encode(
    authority, 0, rb(3L), c(2L, 2L, 1L, 1L, 1L),
    list(rb(1L), rb(1L), NULL, NULL, NULL)
  ),
  SplitAlignerR:::.engine002_plan_encode(
    authority, 1, rb(7L), c(0L, 0L, 2L, 1L, 2L),
    list(rb(1L), rb(2L), rb(4L), NULL, rb(4L))
  )
)
MiB <- 1024^2
destination <- tempfile("engine002-golden-", tmpdir = "/private/tmp")
dir.create(destination, mode = "0700")
on.exit(unlink(destination, recursive = TRUE), add = TRUE)
run_id <- "0123456789abcdef0123456789abcdef"
patterns <- lapply(records, function(record) {
  SplitAlignerR:::.engine002_plan_decode(authority, record)$retained
})
store <- SplitAlignerR:::.engine002_disk_store(
  authority, patterns, destination, run_id,
  0, MiB, MiB, MiB, 3 * MiB
)
lapply(records, function(record) {
  SplitAlignerR:::cpp_engine002_store_insert(store, record)
})
manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
  store, destination, run_id
)
component <- sub("[.]manifest$", ".bin", manifest)
bytes <- readBin(component, raw(), n = file.info(component)$size)
u64 <- function(at) {
  x <- as.double(as.integer(bytes[(at + 1L):(at + 8L)]))
  sum(x * 256^(0:7))
}
index_offset <- u64(56L)
footer_offset <- u64(64L)
hex <- function(x) paste(sprintf("%02x", as.integer(x)), collapse = "")
cat("store_header\t", hex(bytes[1:256]), "\n", sep = "")
cat("index\t", hex(bytes[(index_offset + 1L):footer_offset]), "\n", sep = "")
cat("footer\t", hex(bytes[(footer_offset + 1L):length(bytes)]), "\n", sep = "")
cat("manifest_hex\t", hex(readBin(manifest, raw(), n = file.info(manifest)$size)),
    "\n", sep = "")
cat("store_bytes\t", length(bytes), "\n", sep = "")
