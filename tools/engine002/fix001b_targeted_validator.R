#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3L) {
  stop(
    "usage: fix001b_targeted_validator.R <repo> <library> <output>",
    call. = FALSE
  )
}
repo <- normalizePath(args[[1L]], mustWork = TRUE)
.libPaths(c(normalizePath(args[[2L]], mustWork = TRUE), .libPaths()))
library(SplitAlignerR)

MiB <- 1024^2
run_id <- "0123456789abcdef0123456789abcdef"
rb <- function(value) as.raw(value)
authority <- SplitAlignerR:::.engine002_authority(
  c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
  lapply(c(1L, 2L, 4L, 8L, 3L), rb)
)
fixture_root <- file.path(repo, "tests", "testthat", "fixtures", "engine002")
scratch <- tempfile(
  "fix001b-targeted-", tmpdir = normalizePath(tempdir(), mustWork = TRUE)
)
dir.create(scratch, mode = "0700")
on.exit(unlink(scratch, recursive = TRUE, force = TRUE), add = TRUE)

copy_case <- function(source_root, stem) {
  destination <- file.path(scratch, stem)
  dir.create(destination, mode = "0700")
  component <- file.path(destination, paste0(run_id, ".truthstore.bin"))
  manifest <- file.path(destination, paste0(run_id, ".truthstore.manifest"))
  if (!file.copy(
    file.path(source_root, paste0(stem, ".bin")), component
  ) || !file.copy(
    file.path(source_root, paste0(stem, ".manifest")), manifest
  )) {
    stop("cannot stage targeted validator fixture: ", stem, call. = FALSE)
  }
  list(component = component, manifest = manifest)
}

capture <- function(manifest) {
  tryCatch({
    SplitAlignerR:::cpp_engine002_disk_store_open(
      authority, manifest, 0, MiB, MiB, MiB, 3 * MiB
    )
    NA_character_
  }, error = conditionMessage)
}

old <- copy_case(file.path(fixture_root, "history"), "fix1a_bad_aggregate")
old_message <- capture(old$manifest)
if (is.na(old_message) ||
    !grepl("payload aggregate SHA-256 mismatch", old_message, fixed = TRUE)) {
  stop("old nonconforming store did not reach aggregate rejection")
}

aggregate <- copy_case(file.path(fixture_root, "fix001b"), "aggregate_tamper")
aggregate_message <- capture(aggregate$manifest)
if (is.na(aggregate_message) ||
    !grepl("payload aggregate SHA-256 mismatch", aggregate_message,
           fixed = TRUE)) {
  stop("aggregate-only tamper did not reach aggregate rejection")
}

payload <- copy_case(file.path(fixture_root, "fix001b"), "payload_tamper")
payload_message <- capture(payload$manifest)
if (is.na(payload_message) ||
    !grepl("payload aggregate SHA-256 mismatch", payload_message,
           fixed = TRUE)) {
  stop("payload mutation did not reach aggregate rejection")
}

footer <- copy_case(file.path(fixture_root, "fix001b"), "golden")
bytes <- readBin(footer$component, raw(), n = file.info(footer$component)$size)
u64 <- function(value, zero_offset) {
  observed <- as.double(as.integer(
    value[(zero_offset + 1L):(zero_offset + 8L)]
  ))
  sum(observed * 256^(0:7))
}
footer_offset <- u64(bytes, 64L)
position <- footer_offset + 48L + 1L
bytes[[position]] <- as.raw(bitwXor(as.integer(bytes[[position]]), 1L))
connection <- file(footer$component, open = "wb")
writeBin(bytes, connection, useBytes = TRUE)
close(connection)
footer_message <- capture(footer$manifest)
if (is.na(footer_message) ||
    !grepl("footer checksum mismatch", footer_message, fixed = TRUE)) {
  stop("footer-only tamper did not fail at the footer checksum")
}

lines <- c(
  "status=PASS",
  paste0("old_defective_store_rejection=", old_message),
  paste0("aggregate_only_rejection=", aggregate_message),
  paste0("payload_mutation_rejection=", payload_message),
  paste0("footer_only_first_integrity_layer=", footer_message)
)
writeLines(lines, args[[3L]], useBytes = TRUE)
cat(paste(lines, collapse = "\n"), "\n", sep = "")
