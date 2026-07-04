#' Map gene trees onto the species-tree branch-coordinate system
#'
#' Project the species-tree splits onto each gene's taxon set and classify every
#' gene-by-branch cell as mapped or as one of the explicit missingness
#' categories (`NA_struct`, `NA_fuse`, `NA_topo`, residual `NA`), yielding a
#' standardized gene-by-branch matrix on the frozen primitive branch-coordinate
#' axis.
#'
#' @section Status:
#' **Not implemented yet.** This is a stub that fixes the intended interface for
#' the `v0.0.1` scaffold; calling it raises a clear not-implemented error. The
#' split-projection engine will be added in a later version.
#'
#' @param species_tree Reference species tree: an `ape::phylo` object, or a
#'   Newick string / file path.
#' @param gene_trees Gene trees: an `ape::multiPhylo`, a list of `phylo`
#'   objects, or a path to a SplitAligner line-based Newick file.
#' @param mode Character; `"free"` for free-topology gene trees (which enables
#'   the `NA_topo` category) or `"fixed"` for topology-constrained gene trees.
#' @param ... Reserved for future arguments.
#' @return (Planned) a gene-by-branch matrix / object in which each
#'   `(gene, branch)` cell holds either a numeric branch value or one of the
#'   explicit missingness labels. Nothing is returned yet: the stub signals a
#'   not-implemented error.
#' @seealso [catnip10_expected()] for the bundled benchmark expected output.
#' @examples
#' \dontrun{
#' # Interface preview (not implemented in v0.0.1):
#' m <- align_branches(species_tree, gene_trees, mode = "free")
#' }
#' @export
align_branches <- function(species_tree, gene_trees,
                           mode = c("free", "fixed"), ...) {
  mode <- match.arg(mode)
  stop(
    "align_branches() is not implemented in this scaffold (v0.0.1). ",
    "The split-projection engine is planned for a later release.",
    call. = FALSE
  )
}
