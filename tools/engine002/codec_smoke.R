#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: codec_smoke.R <installed-library>")
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

raw_byte <- function(x) as.raw(x)
authority <- SplitAlignerR:::cpp_engine002_authority_create(
  c("A", "B", "C", "D"),
  c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), raw_byte)
)

hashes <- SplitAlignerR:::cpp_engine002_hash_reference_vectors()
stopifnot(
  identical(hashes$xxhash64_seed0,
            c("ef46db3751d8e999", "d24ec4f1a98c6e5b", "44bc2cf5ad770999")),
  identical(hashes$sha256,
            c("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
              "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")),
  identical(hashes$truth_semantics_sha256,
            "8323c706880b2e95628e803a408a459113b0ac3edeb4d69e9e0626a77fc57935")
)

states <- c(0L, 2L, 2L, 0L, 0L)
queries <- lapply(c(1L, 3L, 3L, 8L, 5L), raw_byte)
record <- SplitAlignerR:::cpp_engine002_plan_encode(
  authority, 0, raw_byte(15L), states, queries
)
stopifnot(length(record) >= 144L, rawToChar(record[1:4]) == "TPLN")

decoded <- SplitAlignerR:::cpp_engine002_plan_decode(authority, record)
view <- SplitAlignerR:::cpp_engine002_plan_view_snapshot(authority, record)
stopifnot(
  identical(decoded, view),
  identical(decoded$states, states),
  identical(decoded$retained, raw_byte(15L)),
  identical(decoded$eligible_primitives, c(0L, 3L, 4L)),
  length(decoded$fibers) == 1L,
  identical(decoded$fibers[[1L]], c(1L, 2L))
)

reencoded <- SplitAlignerR:::cpp_engine002_plan_encode(
  authority, decoded$pattern_id, decoded$retained, decoded$states,
  decoded$primitive_queries
)
stopifnot(identical(record, reencoded))

corrupt <- record
corrupt[[length(corrupt)]] <- as.raw(bitwXor(as.integer(corrupt[[length(corrupt)]]), 1L))
corrupt_error <- tryCatch(
  SplitAlignerR:::cpp_engine002_plan_decode(authority, corrupt),
  error = conditionMessage
)
stopifnot(grepl("ENGINE_STORE_CORRUPT", corrupt_error, fixed = TRUE))

stopifnot(isTRUE(SplitAlignerR:::cpp_engine002_authority_close(authority)))
closed_error <- tryCatch(
  SplitAlignerR:::cpp_engine002_authority_info(authority),
  error = conditionMessage
)
stopifnot(grepl("ENGINE_CONTEXT_CLOSED", closed_error, fixed = TRUE))

cat("ENGINE002_CODEC_SMOKE_PASS\n")
cat("record_bytes=", length(record), "\n", sep = "")
cat("record_xxh64=", decoded$record_xxh64, "\n", sep = "")

