#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: finalize_evidence.R <repository-root>")
repo <- normalizePath(args[[1L]], mustWork = TRUE)
evidence <- file.path(repo, "dev", "ENGINE002", "evidence")

git <- function(arguments) {
  system2("git", c("-C", repo, arguments), stdout = TRUE, stderr = TRUE)
}
changed <- c(
  "committed_and_tracked_diff_from_ENGINE001_base:",
  git(c("diff", "--name-status",
        "93e8bf79ff6fb6b6419d794b7ef70bac702b8665")),
  "",
  "current_porcelain_before_BENCH_commit:",
  git(c("status", "--short"))
)
writeLines(changed, file.path(evidence, "CHANGED_FILES.txt"), useBytes = TRUE)

state <- c(
  "captured_before_required_ENGINE002-BENCH_commit=TRUE",
  git(c("status", "--short", "--branch")),
  paste0("current_HEAD=", git(c("rev-parse", "HEAD"))),
  paste0("current_tree=", git(c("rev-parse", "HEAD^{tree}")))
)
writeLines(state, file.path(evidence, "REPO_STATE_AFTER.txt"), useBytes = TRUE)

checksum_path <- file.path(evidence, "SHA256SUMS")
files <- sort(list.files(
  file.path(repo, "dev", "ENGINE002"), recursive = TRUE,
  full.names = TRUE, all.files = FALSE
), method = "radix")
files <- files[normalizePath(files, mustWork = FALSE) !=
                 normalizePath(checksum_path, mustWork = FALSE)]
lines <- vapply(files, function(path) {
  result <- system2("/usr/bin/shasum", c("-a", "256", path), stdout = TRUE)
  digest <- substr(result[[1L]], 1L, 64L)
  relative <- substring(path, nchar(repo, type = "bytes") + 2L)
  paste0(digest, "  ", relative)
}, character(1))
writeLines(lines, checksum_path, useBytes = TRUE)
cat("ENGINE002_EVIDENCE_FINALIZED\n")
cat("checksummed_files=", length(lines), "\n", sep = "")
