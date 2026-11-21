# S3 is a reference-only operation. It performs no comparison against an
# empirical gene tree and makes no recovery or topology-agreement claim.

.s3_retained_sets <- function(retained_taxa, gene_ids, taxa) {
  if (is.character(retained_taxa) && is.null(dim(retained_taxa))) {
    sets <- list(retained_taxa)
  } else if (is.list(retained_taxa) && !is.object(retained_taxa)) {
    sets <- retained_taxa
  } else {
    stop("`retained_taxa` must be a character vector or a list of character vectors.",
         call. = FALSE)
  }
  if (!length(sets)) {
    stop("`retained_taxa` must contain at least one retained-taxon set; use character(0) for an empty set.",
         call. = FALSE)
  }
  ids <- complete_gene_ids(if (is.null(gene_ids)) names(sets) else gene_ids,
                           length(sets), user_supplied = !is.null(gene_ids))
  ids <- enc2utf8(as.vector(ids))
  for (i in seq_along(sets)) {
    retained <- sets[[i]]
    if (!is.character(retained) || !is.null(dim(retained))) {
      stop(sprintf("Retained-taxon set `%s` must be a character vector.", ids[[i]]),
           call. = FALSE)
    }
    retained <- enc2utf8(as.vector(retained))
    if (anyNA(retained) || any(!nzchar(retained))) {
      stop(sprintf("Retained-taxon set `%s` must not contain missing or empty labels.", ids[[i]]),
           call. = FALSE)
    }
    if (anyDuplicated(retained)) {
      stop(sprintf("Retained-taxon set `%s` contains duplicate taxon labels.", ids[[i]]),
           call. = FALSE)
    }
    unknown <- setdiff(retained, enc2utf8(taxa))
    if (length(unknown)) {
      stop(sprintf("Retained-taxon set `%s` contains taxa absent from the reference: %s.",
                   ids[[i]], paste(unknown, collapse = ", ")), call. = FALSE)
    }
    sets[[i]] <- retained[order(vapply(retained, .s4_byte_key, character(1)),
                                method = "radix")]
  }
  names(sets) <- ids
  list(sets = sets, ids = ids)
}

.s3_restrict_reference <- function(reference, retained, gene_id) {
  graph <- list2env(reference$graph, parent = emptyenv())
  graph$gene_id <- gene_id
  # Protect the original root even when it becomes unary. Contracting other
  # degree-two nodes therefore carries the full root-to-MRCA stem forward.
  .s4_prune(graph, retained, reference$semantics, root_policy = "preserve")
  edges <- which(graph$active)
  axis <- reference$primitives$branch_id
  components <- lapply(edges, function(edge) {
    members <- graph$members[[edge]]
    members <- members[order(match(members, axis))]
    sources <- sort(graph$sources[[edge]])
    # Decide numerical availability only after the complete structural
    # component is known. A finite prefix may overflow even though the final
    # component includes a missing edge and has no available expected total.
    source_status <- reference$numeric_status[sources + 1L]
    value <- NA_real_
    if (any(source_status == "software_failure_marker")) {
      status <- "software_failure_marker"
    } else if (any(source_status == "missing_branch_length")) {
      status <- "missing_branch_length"
    } else {
      value <- sum(reference$lengths[sources + 1L])
      if (!is.finite(value)) {
        .s4_stop("Complete reference-component length sum exceeds the finite numeric range.",
                 gene_id, code = "NUMERIC_RANGE_ERROR")
      }
      status <- "finite_numeric"
    }
    list(primitive_members = members, source_nodes = sources,
         reference_source_nodes = sources, numeric_value = value,
         numeric_status = status)
  })
  positions <- vapply(components, function(component)
    min(match(component$primitive_members, axis)), integer(1))
  list(retained_taxa = retained, components = components[order(positions)],
       root_promoted = FALSE, removed_root_members = character())
}

.s3_expected_components <- function(components) {
  # The shared assembly has both empirical and reference source columns. This
  # layer exposes only the latter because every source here is a reference edge.
  components$source_nodes <- NULL
  names(components)[names(components) == "numeric_value"] <- "expected_value"
  names(components)[names(components) == "numeric_status"] <- "expected_status"
  components
}

#' Construct reference-only branch truth by pruning and contraction
#'
#' Supplementary Algorithm S3 restricts a reference tree to specified taxon
#' sets while carrying complete original-edge memberships through contraction.
#' It accepts no empirical gene trees and does not infer branch recovery.
#' [align_branches()] remains the default split-based mapping entry.
#'
#' @param species_tree Reference Newick text/file or one `ape::phylo` object.
#'   At least two distinct reference taxa are required. Every internal node in
#'   the original input, including its root, must have at least two children.
#'   Non-root reference branch lengths provide expected values; a display-root
#'   length is ignored.
#' @param retained_taxa One character vector of retained labels, or a list of
#'   character vectors. List names supply optional row identifiers. Each set
#'   must contain unique reference labels. An empty character vector is allowed.
#' @param gene_ids Optional unique row identifiers, one per retained-taxon set.
#' @param tree_semantics `"unrooted"` (default) or `"rooted"`. Rooted truth
#'   preserves the original root, including its path to the retained-tip MRCA;
#'   that root is never promoted or suppressed. [align_fixed_topology()] uses
#'   the same reference identity and records empirical observations separately.
#'   With one retained taxon, its full path from the original root remains. An empty set
#'   has no edges. Unrooted sets of zero or one taxon have no surviving edges.
#' @param fusion_view `"whole"` allows expected shared-column sums from complete
#'   current reference components. `"direct"` retains only active fused edges.
#' @return A `splitaligner_truth_result` list. `state_matrix` contains only
#'   `observed`, `NA_struct`, and `NA_fuse` on original primitive coordinates.
#'   `original_matrix` contains numeric values only for observed singletons;
#'   `fusion_matrix` contains shared fusion-coordinate values. Coordinate tables
#'   and `component_ledger` preserve complete primitive memberships.
#'
#'   Component `expected_value` and `expected_status` describe reference lengths,
#'   never empirical observations. A component's value is available only when
#'   every contributing reference length is finite. Missing lengths and software
#'   failure markers never change its structural identity. Negative and zero
#'   lengths follow the package's existing numeric policy. `reference_source_nodes`
#'   are zero-based incoming-edge addresses in the supplied reference Newick;
#'   they are provenance, not portable branch identities.
#'
#'   `fusion_ledger` records reference representability, expected-value status,
#'   construction mode, and the exact current reference components. It contains
#'   no empirical recovery status. `reference_provenance`, `metadata`, and `input`
#'   identify the retained sets and root convention. No `NA_topo` or
#'   `NA_fuse_topo` classification is made by a reference-only truth operation.
#' @examples
#' truth <- reference_truth("((A:1,B:2):3,C:4);",
#'   list(full = c("A", "B", "C"), without_B = c("A", "C")),
#'   tree_semantics = "rooted")
#' truth$state_matrix
#' truth$original_matrix
#' truth$fusion_matrix
#' @export
reference_truth <- function(species_tree, retained_taxa, gene_ids = NULL,
                            tree_semantics = c("unrooted", "rooted"),
                            fusion_view = c("whole", "direct")) {
  tree_semantics <- match.arg(tree_semantics)
  fusion_view <- match.arg(fusion_view)
  species <- as_species_newick(species_tree)
  # The shared parser always assigns reference-compatible legacy B labels.
  # FALSE enables the strict branch-length policy instead of discarding lengths;
  # the incoming length on the representation root remains ignored by the parser.
  parsed <- cpp_s4_parse_tree(species$text, FALSE)
  reference <- .s4_reference(parsed, tree_semantics)
  # Keep measurements separate from the graph: identity surgery transports
  # provenance only, then each final component reads its complete source set.
  reference$lengths <- parsed$lengths
  reference$numeric_status <- parsed$numeric_status
  retained <- .s3_retained_sets(retained_taxa, gene_ids, reference$taxa)
  ids <- retained$ids
  assembled <- .assemble_reference_components(reference, function(i)
    .s3_restrict_reference(reference, retained$sets[[i]], ids[[i]]), ids, fusion_view)
  states <- assembled$state_matrix
  states[states == "mapped"] <- "observed"
  primitive <- assembled$primitive_coordinates
  # Source addresses are all reference-local in S3, including the primitive table.
  names(primitive)[names(primitive) == "source_nodes"] <- "reference_source_nodes"
  definitions <- assembled$composite_coordinates
  ledger <- .s3_expected_components(assembled$component_ledger)
  fusion <- assembled$fusion_ledger
  fusion$recovery_status <- NULL
  names(fusion)[names(fusion) == "numeric_value"] <- "expected_value"
  names(fusion)[names(fusion) == "numeric_status"] <- "expected_status"
  names(fusion)[names(fusion) == "numeric_available"] <- "expected_available"
  fusion$construction_mode <- ifelse(fusion$reference_state == "active",
    "reference_path_sum", ifelse(fusion$reference_state == "decomposable",
      "selected_reference_component_sum", "none"))
  fusion$components <- I(lapply(fusion$components, .s3_expected_components))
  root_policy <- if (tree_semantics == "rooted") "original_root_preserved" else
    "representation_only"
  output <- list(
    state_matrix = states,
    original_matrix = assembled$numeric_matrix[, primitive$coordinate_id, drop = FALSE],
    fusion_matrix = assembled$numeric_matrix[, definitions$coordinate_id, drop = FALSE],
    primitive_coordinates = primitive, composite_coordinates = definitions,
    component_ledger = ledger, fusion_ledger = fusion,
    reference_provenance = data.frame(gene_id = ids, retained_taxa = I(retained$sets),
      root_policy = rep(root_policy, length(ids)), stringsAsFactors = FALSE),
    metadata = list(algorithm = "S3", backend = "reference_graph_pruning_contraction",
      tree_semantics = tree_semantics, root_policy = root_policy,
      branch_identity = if (tree_semantics == "rooted") "rooted_reference_edge" else
        "unrooted_reference_edge", fusion_view = fusion_view,
      fusion_schema = "whole-component-v1", numeric_source = "reference_branch_lengths",
      package_version = as.character(utils::packageVersion("SplitAlignerR"))),
    input = list(reference_newick = species$text, species_source = species$source,
                 retained_taxa = retained$sets, gene_ids = ids))
  class(output) <- c("splitaligner_truth_result", "list")
  output
}

#' @export
print.splitaligner_truth_result <- function(x, ...) {
  cat("SplitAlignerR S3 reference truth\n",
      "  Semantics: ", x$metadata$tree_semantics, "; root policy: ", x$metadata$root_policy,
      "\n  Retained-taxon sets: ", nrow(x$state_matrix),
      "; primitive coordinates: ", ncol(x$state_matrix),
      "; shared fusion coordinates: ", ncol(x$fusion_matrix), "\n", sep = "")
  invisible(x)
}
