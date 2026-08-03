## Compile and verify the isolated ENGINE001 external-pointer ownership sketch.

e1_run_ownership_sketch <- function(output_path) {
  cache <- tempfile("engine001-rcpp-cache-")
  dir.create(cache)
  on.exit(unlink(cache, recursive = TRUE, force = TRUE), add = TRUE)
  Rcpp::sourceCpp(
    "dev/ENGINE001/prototype/ownership_lifecycle_sketch.cpp",
    cacheDir = cache, rebuild = TRUE, showOutput = FALSE, verbose = FALSE
  )
  pointer <- engine001_context_create("authority-sha256", c(1, 2, 3))
  snapshot <- engine001_context_snapshot(pointer)
  first_close <- engine001_context_close(pointer)
  second_close <- engine001_context_close(pointer)
  closed_error <- tryCatch({
    engine001_context_snapshot(pointer)
    NA_character_
  }, error = conditionMessage)
  rm(pointer)
  invisible(gc())
  results <- data.frame(
    gate = c(
      "ordinary_snapshot_is_independent",
      "first_close_changes_state",
      "second_close_is_idempotent",
      "closed_context_fails_safely",
      "snapshot_survives_pointer_gc"
    ),
    status = c(
      identical(snapshot$values, c(1, 2, 3)) && isTRUE(snapshot$durable),
      isTRUE(first_close),
      identical(second_close, FALSE),
      startsWith(closed_error, "[ENGINE_CONTEXT_CLOSED]"),
      identical(snapshot$values, c(1, 2, 3))
    ),
    stringsAsFactors = FALSE
  )
  results$status <- ifelse(results$status, "PASS", "FAIL")
  write.table(results, output_path, sep = "\t", quote = FALSE, row.names = FALSE)
  if (any(results$status != "PASS")) {
    stop("ENGINE001 ownership sketch failed.", call. = FALSE)
  }
  invisible(results)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 1L) {
    stop("Usage: ownership_lifecycle_sketch.R output.txt", call. = FALSE)
  }
  e1_run_ownership_sketch(args[[1L]])
}
