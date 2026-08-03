#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3L) {
  stop(
    "usage: fix001_interrupt_probe.R <library> <directory> <output>",
    call. = FALSE
  )
}
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

directory <- normalizePath(args[[2L]], mustWork = TRUE)
run_id <- "abababababababababababababababab"
message <- NULL
tryCatch(
  SplitAlignerR:::cpp_engine002_build_authority_scale_store(
    directory, run_id, 10000,
    0, 1024^2, 64 * 1024^2, 1024^2, 66 * 1024^2
  ),
  error = function(error) {
    message <<- conditionMessage(error)
  }
)
manifest <- file.path(directory, paste0(run_id, ".truthstore.manifest"))
component <- file.path(directory, paste0(run_id, ".truthstore.bin"))
temporary <- list.files(directory, pattern = "engine002-tmp-", full.names = TRUE)
status <- !is.null(message) &&
  grepl("ENGINE_INTERRUPTED", message, fixed = TRUE) &&
  !file.exists(manifest) && !file.exists(component) &&
  length(temporary) == 0L
lines <- c(
  paste0("status=", if (status) "PASS" else "FAIL"),
  paste0("condition=", if (is.null(message)) "<none>" else message),
  paste0("manifest_exists=", file.exists(manifest)),
  paste0("component_exists=", file.exists(component)),
  paste0("temporary_count=", length(temporary))
)
writeLines(lines, args[[3L]])
cat(paste(lines, collapse = "\n"), "\n")
if (!status) quit(status = 1L)
