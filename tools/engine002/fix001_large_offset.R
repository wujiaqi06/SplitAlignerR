#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5L) {
  stop(
    "usage: fix001_large_offset.R <library> <directory> <count> <run-id> <output>",
    call. = FALSE
  )
}
.libPaths(c(args[[1L]], .libPaths()))
library(SplitAlignerR)

directory <- normalizePath(args[[2L]], mustWork = TRUE)
pattern_count <- as.double(args[[3L]])
run_id <- args[[4L]]
output <- args[[5L]]
MiB <- 1024^2
index_budget <- max(64 * MiB, pattern_count * 320)
started <- proc.time()
result <- SplitAlignerR:::cpp_engine002_build_authority_scale_store(
  directory, run_id, pattern_count,
  0, MiB, index_budget, MiB, index_budget + 2 * MiB
)
elapsed <- proc.time() - started

component <- sub("[.]manifest$", ".bin", result$manifest)
connection <- file(component, open = "rb")
on.exit(close(connection), add = TRUE)
header <- readBin(connection, raw(), n = 256L)
u64 <- function(bytes, at) {
  values <- as.double(as.integer(bytes[(at + 1L):(at + 8L)]))
  sum(values * 256^(0:7))
}
index_offset <- u64(header, 56L)
footer_offset <- u64(header, 64L)
exact_file_bytes <- u64(header, 72L)
seek(connection, where = index_offset, origin = "start")
first_index <- readBin(connection, raw(), n = 64L)
seek(
  connection,
  where = index_offset + (pattern_count - 1) * 64,
  origin = "start"
)
last_index <- readBin(connection, raw(), n = 64L)
seek(connection, where = footer_offset, origin = "start")
footer <- readBin(connection, raw(), n = 128L)

lines <- c(
  "status=PASS",
  paste0("manifest=", result$manifest),
  paste0("component=", component),
  paste0("pattern_count=", format(pattern_count, scientific = FALSE)),
  paste0("mean_record_bytes=", result$mean_record_bytes),
  paste0("minimum_record_bytes=", result$minimum_record_bytes),
  paste0("maximum_record_bytes=", result$maximum_record_bytes),
  paste0("total_record_bytes=", result$total_record_bytes),
  paste0("fixture_seconds=", result$fixture_seconds),
  paste0("record_generation_seconds=", result$record_generation_seconds),
  paste0("streaming_write_seconds=", result$streaming_write_seconds),
  paste0("finalize_validate_publish_seconds=",
         result$finalize_validate_publish_seconds),
  paste0("final_store_bytes=", result$final_store_bytes),
  paste0("header_index_offset=", index_offset),
  paste0("header_footer_offset=", footer_offset),
  paste0("header_exact_file_bytes=", exact_file_bytes),
  paste0("actual_file_bytes=", file.info(component)$size),
  paste0("first_index_pattern_id=", u64(first_index, 0L)),
  paste0("last_index_pattern_id=", u64(last_index, 0L)),
  paste0("footer_record_count=", u64(footer, 16L)),
  paste0("builder_charged_high_water=", result$builder_charged_high_water),
  paste0("current_record_high_water=", result$current_record_high_water),
  paste0("write_buffer_high_water=", result$write_buffer_high_water),
  paste0("temporary_disk_high_water=", result$temporary_disk_high_water),
  paste0("index_charged_bytes=", result$index_charged_bytes),
  paste0("finalize_io_seconds=", result$finalize_io_seconds),
  paste0("temporary_validation_seconds=",
         result$temporary_validation_seconds),
  paste0("manifest_prepare_seconds=", result$manifest_prepare_seconds),
  paste0("atomic_publication_seconds=",
         result$atomic_publication_seconds),
  paste0("published_validation_seconds=",
         result$published_validation_seconds),
  paste0("elapsed_seconds=", unname(elapsed[["elapsed"]])),
  paste0("user_seconds=", unname(elapsed[["user.self"]])),
  paste0("system_seconds=", unname(elapsed[["sys.self"]]))
)
writeLines(lines, output)
cat(paste(lines, collapse = "\n"), "\n")
