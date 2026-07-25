#' SplitAlignerR release-candidate status
#'
#' Report the current V1 release-candidate status of the package.
#'
#' @return A length-one character string describing the release-candidate
#'   status.
#' @examples
#' splitalignerR_scaffold()
#' @export
splitalignerR_scaffold <- function() {
  paste0(
    "SplitAlignerR ", utils::packageVersion("SplitAlignerR"),
    " V1 release candidate: the C++ graph-first mapper and independent Catnip10 ",
    "R Oracle are frozen for audit; independent RECERT is pending and this is ",
    "not a final release certificate."
  )
}

#' Catnip10 benchmark expected oracle output
#'
#' Return the deterministic expected gene-by-branch coordinate matrix of the
#' Catnip10 10-tip coordinate-audit benchmark for one taxon-deletion regime.
#' Values are kept as character strings so that numeric branch lengths and the
#' explicit missingness labels (`NA_struct`, `NA_fuse`) are preserved exactly as
#' emitted by the independent graph-theoretic oracle. Rows are the full tree
#' (`*_step0`) followed by seven cumulative deletion steps; columns are the 17
#' primitive branch coordinates on the unrooted axis (ten terminals `t1`--`t10`
#' and seven internals `N_12`--`N_18`), preceded by `gene_id`.
#'
#' @param regime Deletion regime: `"global"` (outgroup-first) or `"local"`
#'   (locally confined). Partial matching is allowed via [match.arg()].
#' @return A `data.frame` with 8 rows and 18 columns (`gene_id` plus the 17
#'   branch coordinates), all columns character.
#' @seealso [catnip10_oracle] for the full bundled benchmark object.
#' @examples
#' g <- catnip10_expected("global")
#' dim(g)
#' g[["gene_id"]]
#' @export
catnip10_expected <- function(regime = c("global", "local")) {
  catnip10_matrix(regime)
}
