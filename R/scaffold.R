#' SplitAlignerR scaffold placeholder
#'
#' A temporary placeholder that reports the scaffold status of the package.
#' It exists so that the `v0.0.1` scaffold installs, documents, and passes
#' `R CMD check` while the split-based branch-mapping engine is still under
#' development. It will be removed once the mapping functions land.
#'
#' @return A length-one character string describing the scaffold status.
#' @examples
#' splitalignerR_scaffold()
#' @export
splitalignerR_scaffold <- function() {
  paste0(
    "SplitAlignerR ", utils::packageVersion("SplitAlignerR"),
    " scaffold: the split-based branch-mapping engine is not implemented yet. ",
    "Bundled Catnip10 benchmark oracle output is available via catnip10_expected()."
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
  regime <- match.arg(regime)
  catnip10_oracle[[regime]]$matrix
}
