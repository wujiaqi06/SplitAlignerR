# R 3.5/3.6 has no unlink(expand = FALSE). Cleanup paths belong to this
# operation and must reach the filesystem without wildcard interpretation.
.unlink_literal <- function(path, recursive = FALSE, force = FALSE) {
  if (!is.character(path) || anyNA(path) || any(!nzchar(path))) {
    stop("Cleanup paths must be nonempty strings.", call. = FALSE)
  }
  flag <- function(x) is.logical(x) && length(x) == 1L && !is.na(x)
  if (!flag(recursive) || !flag(force)) {
    stop("Cleanup flags must be TRUE or FALSE.", call. = FALSE)
  }
  path <- path.expand(path)
  status <- vapply(path, cpp_unlink_literal, integer(1), recursive = recursive, force = force)
  failed <- path[status != 0L]
  if (length(failed)) {
    condition <- structure(
      list(message = paste0("Cleanup failed; paths remain: ", paste(dQuote(failed), collapse = ", ")),
           call = NULL, paths = failed),
      class = c("splitaligner_cleanup_warning", "warning", "condition")
    )
    # Cleanup commonly runs in on.exit(). With warn = 2, preserve the original
    # operation's error and still report every path whose removal failed.
    if (getOption("warn", 0L) >= 2L) {
      message(conditionMessage(condition))
    } else {
      tryCatch(warning(condition), error = function(e) message(conditionMessage(condition)))
    }
  }
  invisible(as.integer(length(failed) > 0L))
}
