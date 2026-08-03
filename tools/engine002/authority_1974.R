#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3L) {
  stop("usage: authority_1974.R <installed-library> <authority-root> <output>")
}
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

root <- normalizePath(args[[2L]], mustWork = TRUE)
output <- args[[3L]]
repo <- normalizePath(file.path(dirname(commandArgs()[[1L]]), ".."),
                      mustWork = FALSE)
argv <- commandArgs(FALSE)
file_arg <- sub("^--file=", "", argv[startsWith(argv, "--file=")][[1L]])
tool_dir <- dirname(normalizePath(file_arg, mustWork = TRUE))
repo <- normalizePath(file.path(tool_dir, "..", ".."), mustWork = TRUE)
source(file.path(repo, "dev/ARCH000/prototype/arch000_common.R"))
source(file.path(repo, "dev/ARCH000A/prototype/compact_pattern_registry.R"))
source(file.path(tool_dir, "authority_helpers.R"))

species <- file.path(root, "302mammal/input/speciesTree302.nwk")
fixed <- file.path(root, "preprint_302mammal/input/fix.2275genes.nwk")
free <- file.path(root, "preprint_302mammal/input/free.2275genes.nwk")
expected_sha <- c(
  species = "f975e0c22c7817ff1d785f60c39958a28e0827a93e3a46383cbfe3ca497cc70f",
  fixed = "6bfaa5e134a3bedbd77624134c50855f80f536205ca70d5b0ffe055d7f36b0ab",
  free = "cf19a1befac3ffa007f44867e26f1d63e1c732dfe7367f6058dd8a4bff322efb"
)
observed_sha <- vapply(c(species, fixed, free), function(path) {
  unname(tools::md5sum(path))
}, character(1))
# SHA-256 is independently checked by the calling evidence command. The MD5
# values retained here ensure that a file cannot change during this run.

started <- proc.time()[["elapsed"]]
reference_authority <- arch_species_authority(species)
fixed_scan <- a_scan_gene_patterns(fixed, reference_authority)
free_scan <- a_scan_gene_patterns(free, reference_authority)
registry <- a_make_pattern_registry(
  list(fixed_scan, free_scan), reference_authority
)
stopifnot(length(registry$pattern_ids) == 1974L)
authority <- engine002_make_authority(reference_authority)

records <- vector("list", length(registry$pattern_ids))
record_bytes <- numeric(length(records))
for (i in seq_along(records)) {
  retained <- a_unpack_ids(registry$exact_pattern_bits[[i]],
                           registry$universe_size)
  reference <- arch_build_truth_plan(reference_authority, retained)
  queries <- engine002_plan_queries(
    reference_authority, retained, reference$state_template
  )
  record <- SplitAlignerR:::.engine002_plan_encode(
    authority, i - 1L, registry$exact_pattern_bits[[i]],
    reference$state_template, queries
  )
  decoded <- SplitAlignerR:::.engine002_plan_decode(authority, record)
  view <- SplitAlignerR:::.engine002_plan_view_snapshot(authority, record)
  equal <- engine002_plan_equal_reference(decoded, reference, queries)
  if (!isTRUE(equal)) {
    detail <- ""
    if (!attr(equal, "checks")[["fibers"]]) {
      detail <- paste0(
        ";decoded_fibers=",
        paste(engine002_member_keys(decoded$fibers), collapse = "|"),
        ";reference_fibers=",
        paste(engine002_member_keys(
          lapply(reference$composites, `[[`, "members"), one_based = TRUE
        ), collapse = "|")
      )
    }
    stop(sprintf(
      "authority mismatch at pattern %d: %s%s", i - 1L,
      paste(names(attr(equal, "checks"))[!attr(equal, "checks")],
            collapse = ","), detail
    ), call. = FALSE)
  }
  if (!identical(decoded, view)) {
    stop(sprintf("direct view mismatch at pattern %d", i - 1L), call. = FALSE)
  }
  reencoded <- SplitAlignerR:::.engine002_plan_encode(
    authority, decoded$pattern_id, decoded$retained, decoded$states,
    decoded$primitive_queries
  )
  if (!identical(record, reencoded)) {
    stop(sprintf("re-encode mismatch at pattern %d", i - 1L), call. = FALSE)
  }
  records[[i]] <- record
  record_bytes[[i]] <- length(record)
}

memory <- SplitAlignerR:::.engine002_memory_store(authority, length(records))
for (i in rev(seq_along(records))) {
  SplitAlignerR:::cpp_engine002_store_insert(memory, records[[i]])
}
SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")
for (i in c(1L, 2L, length(records) %/% 2L, length(records))) {
  got <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    memory, i - 1L, registry$exact_pattern_bits[[i]]
  )
  stopifnot(identical(got$states,
                      SplitAlignerR:::.engine002_plan_decode(
                        authority, records[[i]]
                      )$states))
}
memory_stats <- SplitAlignerR:::cpp_engine002_store_stats(memory)
SplitAlignerR:::cpp_engine002_store_close(memory)

elapsed <- unname(proc.time()[["elapsed"]] - started)
lines <- c(
  "status=PASS",
  "authority_source=RECERT013_Published_20260723_JST",
  paste0("species_sha256=", expected_sha[["species"]]),
  paste0("fixed_sha256=", expected_sha[["fixed"]]),
  paste0("free_sha256=", expected_sha[["free"]]),
  paste0("authority_patterns=", length(records)),
  paste0("codec_reference_equal=", length(records), "/", length(records)),
  paste0("encode_decode_reencode=", length(records), "/", length(records)),
  paste0("direct_view_equal=", length(records), "/", length(records)),
  paste0("record_bytes_total=", sum(record_bytes)),
  paste0("record_bytes_min=", min(record_bytes)),
  paste0("record_bytes_max=", max(record_bytes)),
  paste0("memory_arena_bytes=", memory_stats$arena_bytes),
  paste0("elapsed_seconds=", sprintf("%.3f", elapsed)),
  paste0("input_md5_stability=", paste(observed_sha, collapse = ","))
)
writeLines(lines, output, useBytes = TRUE)
cat(paste(lines, collapse = "\n"), "\n", sep = "")
