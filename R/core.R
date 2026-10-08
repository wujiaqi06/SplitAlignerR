#' SplitAligner C++ core metadata
#'
#' Return versioned metadata for the compiled production-core boundary. The
#' graph oracle is intentionally reported separately because it is implemented
#' in pure R and must remain independent of the production C++ engine.
#'
#' @return A named list containing core, schema, language, and numeric-policy
#'   identifiers.
#' @examples
#' splitaligner_core_info()
#' @export
splitaligner_core_info <- function() {
  cpp_splitaligner_core_info()
}

#' Validate branch-length tokens
#'
#' Parse branch-length tokens using the SplitAlignerR V1 numeric policy. Parsing
#' consumes the entire token, accepts explicit zero and every representable
#' finite decimal value, rejects non-finite values and values that overflow or
#' underflow to zero, and never converts software failure markers to zero.
#'
#' Finite negative values are retained for compatibility with phylogenetic
#' software output but receive a diagnostic because the nonnegative numerical
#' theorem does not cover them.
#'
#' @param tokens A character vector of branch-length tokens. R missing values,
#'   empty strings, and recognized software failure markers are treated as
#'   unavailable numeric evidence.
#' @return A data frame with the original token, classification, acceptance
#'   flag, parsed value, zero/negative flags, and diagnostic.
#' @examples
#' validate_branch_length_tokens(c("0", "1e-8", "NaN", "1e9999"))
#' @export
validate_branch_length_tokens <- function(tokens) {
  if (is.factor(tokens)) {
    tokens <- as.character(tokens)
  }
  if (!is.character(tokens)) {
    stop("`tokens` must be a character vector.", call. = FALSE)
  }
  cpp_validate_branch_length_tokens(tokens)
}
