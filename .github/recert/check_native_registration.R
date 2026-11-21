args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 1L) {
  stop("usage: check_native_registration.R [SOURCE_ROOT]", call. = FALSE)
}
source_root <- normalizePath(if (length(args)) args[[1L]] else ".",
                             mustWork = TRUE)
generated <- file.path(source_root, c("src/RcppExports.cpp", "R/RcppExports.R"))
read_bytes <- function(path) readBin(path, "raw", n = file.info(path)$size)

# Different supported Rcpp versions may format generated files differently.
# Require determinism within this version and preserve the initialization hook.
Rcpp::compileAttributes(source_root)
first <- lapply(generated, read_bytes)
cpp <- rawToChar(first[[1L]])
pattern <- paste0(
  "(?s)RcppExport\\s+void\\s+R_init_SplitAlignerR\\s*",
  "\\([^)]*\\)\\s*\\{([^}]*)\\}"
)
init <- regmatches(cpp, regexec(pattern, cpp, perl = TRUE))[[1L]]
if (length(init) != 2L) {
  stop("Generated package initialization routine was not found.", call. = FALSE)
}
calls <- gregexpr("\\bsplitaligner_init\\s*\\(\\s*dll\\s*\\)\\s*;",
                  init[[2L]], perl = TRUE)[[1L]]
if (length(calls) != 1L || calls[[1L]] < 0L) {
  stop("Generated package initialization must call splitaligner_init once.",
       call. = FALSE)
}
Rcpp::compileAttributes(source_root)
if (!identical(first, lapply(generated, read_bytes))) {
  stop("Repeated attribute generation changed the generated files.", call. = FALSE)
}
cat("PASS: Rcpp", as.character(utils::packageVersion("Rcpp")),
    "retains one native initialization call and generates stable files.\n")
