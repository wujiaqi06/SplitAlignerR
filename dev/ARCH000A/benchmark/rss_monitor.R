#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("PID and output path are required", call. = FALSE)
pid <- as.integer(args[[1L]])
output <- args[[2L]]
interval <- 0.02
peak <- 0
samples <- 0L
started <- Sys.time()

suppressPackageStartupMessages(library(ps))
handle <- try(ps::ps_handle(pid), silent = TRUE)
if (!inherits(handle, "try-error")) {
  repeat {
    running <- try(ps::ps_is_running(handle), silent = TRUE)
    if (inherits(running, "try-error") || !isTRUE(running)) break
    memory <- try(ps::ps_memory_info(handle), silent = TRUE)
    if (!inherits(memory, "try-error")) {
      peak <- max(peak, as.numeric(memory[["rss"]]), na.rm = TRUE)
      samples <- samples + 1L
    }
    Sys.sleep(interval)
  }
}

writeLines(c(
  "method=ps_rss_polling",
  sprintf("target_pid=%d", pid),
  sprintf("poll_interval_seconds=%.3f", interval),
  sprintf("samples=%d", samples),
  sprintf("peak_rss_bytes=%.0f", peak),
  sprintf("monitor_wall_seconds=%.6f",
          as.numeric(difftime(Sys.time(), started, units = "secs"))),
  "interpretation=sampled OS RSS maximum; not a kernel high-water mark"
), output)
