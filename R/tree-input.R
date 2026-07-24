as_species_newick <- function(species_tree) {
  if (inherits(species_tree, "multiPhylo")) {
    stop("`species_tree` must contain exactly one tree.", call. = FALSE)
  }
  if (inherits(species_tree, "phylo")) {
    return(list(
      text = enc2utf8(ape::write.tree(species_tree)),
      source = "ape::phylo"
    ))
  }
  if (!is.character(species_tree) || length(species_tree) != 1L ||
      is.na(species_tree) || !nzchar(species_tree)) {
    stop(
      "`species_tree` must be one `ape::phylo`, Newick string, or file path.",
      call. = FALSE
    )
  }

  if (file.exists(species_tree)) {
    lines <- readLines(species_tree, warn = FALSE, encoding = "UTF-8")
    return(list(
      text = enc2utf8(paste(lines, collapse = "\n")),
      source = normalizePath(species_tree, winslash = "/", mustWork = TRUE)
    ))
  }
  list(text = enc2utf8(species_tree), source = "Newick string")
}

#' Validate and canonicalize a reference species tree
#'
#' Parse a reference tree with the C++17 production core, strip reference branch
#' lengths, internal support/labels, and annotation blocks with structured
#' diagnostics, and construct the deterministic primitive coordinate table from
#' canonical unrooted splits. Multifurcations are retained and never silently
#' refined.
#'
#' @param species_tree One `ape::phylo` object, one Newick string, or a path to a
#'   file containing exactly one Newick tree.
#' @return A list with `valid`, `tip_labels`, `coordinates`, `diagnostics`,
#'   `metadata`, and `source`. Coordinate rows retain primitive B aliases and
#'   exact split-side taxon lists.
#' @examples
#' validated <- validate_species_tree("((A:1,B:1),(C:1,D:1));")
#' validated$coordinates
#' @export
validate_species_tree <- function(species_tree) {
  input <- as_species_newick(species_tree)
  result <- cpp_validate_species_tree(input$text)
  result$source <- input$source
  class(result) <- c("splitaligner_tree_validation", "list")
  result
}
