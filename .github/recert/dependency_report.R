args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L || !nzchar(args[[1L]])) {
  stop("usage: dependency_report.R OUTPUT_TSV", call. = FALSE)
}

required <- data.frame(
  package = c(
    "ape", "Rcpp", "testthat", "knitr", "markdown",
    "xfun", "litedown", "commonmark", "pkgload", "rcmdcheck", "processx"
  ),
  reason = c(
    "DESCRIPTION Imports",
    "DESCRIPTION Imports/LinkingTo",
    "DESCRIPTION Suggests",
    "DESCRIPTION Suggests/VignetteBuilder support",
    "DESCRIPTION Suggests",
    "markdown/litedown build chain",
    "markdown direct dependency",
    "litedown direct dependency",
    "source-root test runner",
    "CI check runner",
    "independent subprocess deep-tree probe"
  ),
  stringsAsFactors = FALSE
)

installed <- utils::installed.packages()
index <- match(required$package, rownames(installed))
required$installed <- !is.na(index)
required$version <- NA_character_
required$library <- NA_character_
present <- required$installed
required$version[present] <- installed[index[present], "Version"]
required$library[present] <- installed[index[present], "LibPath"]

utils::write.table(
  required,
  file = args[[1L]],
  sep = "\t",
  quote = FALSE,
  row.names = FALSE,
  na = "NOT_INSTALLED"
)

if (any(!required$installed)) {
  stop(
    sprintf(
      "missing required replay dependencies: %s",
      paste(required$package[!required$installed], collapse = ", ")
    ),
    call. = FALSE
  )
}
