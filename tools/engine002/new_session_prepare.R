#!/usr/bin/env Rscript
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("usage: new_session_prepare.R <library> <directory>")
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)
rb <- function(x) as.raw(x)
authority <- SplitAlignerR:::.engine002_authority(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)
record <- SplitAlignerR:::.engine002_plan_encode(
  authority, 0, rb(3L), c(2L, 2L, 1L, 1L, 1L),
  list(rb(1L), rb(1L), NULL, NULL, NULL)
)
MiB <- 1024^2
store <- SplitAlignerR:::.engine002_disk_store(
  authority, 1, 0, MiB, MiB, MiB, 3 * MiB
)
SplitAlignerR:::cpp_engine002_store_insert(store, record)
manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
  store, args[[2L]], "cccccccccccccccccccccccccccccccc"
)
SplitAlignerR:::cpp_engine002_store_close(store)
writeLines(manifest, file.path(args[[2L]], "manifest.path"))
