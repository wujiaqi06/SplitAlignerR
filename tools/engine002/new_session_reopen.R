#!/usr/bin/env Rscript
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("usage: new_session_reopen.R <library> <directory>")
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)
rb <- function(x) as.raw(x)
authority <- SplitAlignerR:::.engine002_authority(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)
manifest <- readLines(file.path(args[[2L]], "manifest.path"), warn = FALSE)
MiB <- 1024^2
store <- SplitAlignerR:::cpp_engine002_disk_store_open(
  authority, manifest, 0, MiB, MiB, MiB, 3 * MiB
)
snapshot <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
  store, 0, rb(3L)
)
stopifnot(
  identical(snapshot$retained, rb(3L)),
  identical(snapshot$states, c(2L, 2L, 1L, 1L, 1L))
)
SplitAlignerR:::cpp_engine002_store_close(store)
cat("ENGINE002_NEW_SESSION_REOPEN_PASS\n")
