canonical_ape_write_tree <- function(tree) {
  if (inherits(tree, "multiPhylo")) {
    # [[.multiPhylo restores the shared tip labels of compressed tree sets.
    return(vapply(seq_along(tree), function(i) canonical_ape_write_tree(tree[[i]]),
                  character(1)))
  }

  # Let ape write the topology using integer node IDs. Substituting each
  # ID once keeps ape's label sanitizer away from the actual Newick labels.
  tips <- tree$tip.label
  if (anyNA(tips) || any(!nzchar(tips))) {
    stop("Every phylo tip must have a nonempty label.", call. = FALSE)
  }
  nodes <- tree$node.label
  if (is.null(nodes)) nodes <- rep("", tree$Nnode)
  if (length(nodes) != tree$Nnode) {
    stop("The phylo node labels must match the internal nodes.", call. = FALSE)
  }
  nodes[is.na(nodes)] <- ""
  labels <- enc2utf8(c(tips, nodes))
  # Quote only labels that need it so ordinary tip names round-trip through ape.
  quoted <- grepl("[][(),:;'\"[:space:]]", labels)
  labels[quoted] <- paste0("'", gsub("'", "''", labels[quoted], fixed = TRUE), "'")

  if (!is.null(tree$edge.length) && length(tree$edge.length) != nrow(tree$edge)) {
    stop("The phylo edge lengths must match the edges.", call. = FALSE)
  }
  lengths <- rep(NA_real_, length(labels))
  if (!is.null(tree$edge.length)) lengths[tree$edge[, 2L]] <- tree$edge.length
  if (!is.null(tree$root.edge)) lengths[length(tips) + 1L] <- tree$root.edge
  has_length <- !is.na(lengths) | is.nan(lengths)
  if (any(has_length)) {
    values <- .dot_decimal(sprintf("%.17g", lengths[has_length]))
    labels[has_length] <- paste0(labels[has_length], ":", values)
  }

  tree$tip.label <- as.character(seq_along(tips))
  tree$node.label <- as.character(length(tips) + seq_len(tree$Nnode))
  tree$edge.length <- tree$root.edge <- NULL
  skeleton <- ape::write.tree(tree, digits = 0L)
  indices <- gregexpr("[0-9]+", skeleton)
  regmatches(skeleton, indices) <- list(labels[as.integer(regmatches(skeleton, indices)[[1L]])])
  enc2utf8(skeleton)
}

check_missing_tree_path <- function(text) {
  if (is.na(text)) return(invisible(NULL))
  value <- trimws(text)
  if (!startsWith(value, "(") && !startsWith(value, "[") && !endsWith(value, ";") &&
      (grepl("[/\\\\]", value) ||
       grepl("\\.(nwk|newick|tree|trees|tre|treefile|txt)$", value, ignore.case = TRUE))) {
    stop(sprintf("Tree file does not exist: %s", text), call. = FALSE)
  }
}

as_species_newick <- function(species_tree) {
  if (inherits(species_tree, "multiPhylo")) {
    stop("`species_tree` must contain exactly one tree.", call. = FALSE)
  }
  if (inherits(species_tree, "phylo")) {
    return(list(
      text = canonical_ape_write_tree(species_tree),
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
  check_missing_tree_path(species_tree)
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
