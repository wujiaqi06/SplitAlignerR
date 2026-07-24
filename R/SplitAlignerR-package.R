#' @keywords internal
#' @useDynLib SplitAlignerR, .registration = TRUE
#' @importFrom Rcpp evalCpp
"_PACKAGE"

# The Catnip10 oracle data set is lazy-loaded from the package namespace and
# referenced by name inside package functions; declare it so R CMD check does
# not flag it as an undefined global variable.
utils::globalVariables("catnip10_oracle")
