args <- commandArgs(trailingOnly = TRUE)
if (length(args)) {
  if (length(args) != 3L || args[[1L]] != "--read") {
    stop("usage: compact_vector_smoke.R [--read RDS LIBRARY_PATHS]", call. = FALSE)
  }
  .libPaths(strsplit(args[[3L]], .Platform$path.sep, fixed = TRUE)[[1L]])
  stopifnot(!"SplitAlignerR" %in% loadedNamespaces())
  restored <- readRDS(args[[2L]])
  stopifnot("SplitAlignerR" %in% loadedNamespaces(),
            is.character(restored$projected),
            identical(restored$projected, restored$expected))
  cat("PASS: compact-vector RDS loaded in a fresh process.\n")
} else {
  stopifnot(!"package:SplitAlignerR" %in% search())
  tree <- "((A:1,B:2):3,(C:4,D:5):6);"
  aligned <- SplitAlignerR::align_branches(tree, c(g = tree), mode = "fixed")
  projected <- aligned$state_ledger$projected_split
  stopifnot(is.character(projected), length(projected) > 0L)
  expected <- vapply(seq_along(projected), function(i) projected[[i]], character(1))
  payload <- list(projected = projected, expected = expected)
  path <- tempfile(fileext = ".rds")
  saveRDS(payload, path, version = 3L)
  stopifnot(identical(readRDS(path), payload))
  script <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE))
  stopifnot(length(script) == 1L)
  status <- system2(file.path(R.home("bin"), "Rscript"),
                    c("--vanilla", shQuote(normalizePath(script)), "--read",
                      shQuote(path), shQuote(paste(.libPaths(), collapse = .Platform$path.sep))))
  unlink(path)
  stopifnot(status == 0L, !"package:SplitAlignerR" %in% search())
  cat("PASS: namespace-only alignment and compact-vector RDS round trip.\n")
}
