# Shared table construction for independent reference truth and S4 alignment.
# The provider supplies current components; it never determines graph identity.
.assemble_reference_components <- function(reference, aligned_genes, ids, fusion_view) {
  primitive <- reference$primitives
  primitive$coordinate_id <- primitive$branch_id
  primitive$primitive_aliases <- primitive$aliases
  primitive$primitive_alias_text <- vapply(primitive$aliases, paste,
                                         character(1), collapse = "|")
  primitive$branch_id <- primitive$aliases <- NULL
  axis <- primitive$coordinate_id
  states <- matrix("NA_struct", length(ids), length(axis), dimnames = list(ids, axis))
  numeric <- matrix(NA_real_, length(ids), length(axis), dimnames = list(ids, axis))
  ledgers <- vector("list", length(ids))
  owners <- vector("list", length(ids))
  component_sizes <- vector("list", length(ids))
  retained <- vector("list", length(ids))
  promoted <- logical(length(ids))
  discarded_stems <- vector("list", length(ids))
  for (i in seq_along(ids)) {
    aligned <- if (is.function(aligned_genes)) aligned_genes(i) else aligned_genes[[i]]
    retained[[i]] <- aligned$retained_taxa
    promoted[[i]] <- aligned$root_promoted
    discarded_stems[[i]] <- aligned$removed_root_members
    components <- aligned$components
    members <- lapply(components, `[[`, "primitive_members")
    sizes <- lengths(members)
    positions <- match(unlist(members, use.names = FALSE), axis)
    if (any(sizes == 0L) || anyNA(positions) || anyDuplicated(positions))
      stop("Internal component membership is invalid.", call. = FALSE)
    # The graph kernel returns each component's members in primitive-axis
    # order. Preserve that contract without re-scanning the full axis per edge.
    positions_by_component <- split(positions, rep.int(seq_along(components), sizes))
    if (any(vapply(positions_by_component, is.unsorted, logical(1), strictly = TRUE)))
      stop("Internal component members are out of order.", call. = FALSE)
    owner <- integer(length(axis))
    owner[positions] <- rep.int(seq_along(components), sizes)
    values <- vapply(components, `[[`, numeric(1), "numeric_value")
    states[i, positions] <- rep.int(ifelse(sizes == 1L, "mapped", "NA_fuse"), sizes)
    singletons <- which(sizes == 1L)
    singleton_positions <- match(vapply(members[singletons], `[[`, character(1), 1L), axis)
    numeric[i, singleton_positions] <- values[singletons]
    # Construct columns once per gene instead of one data.frame per edge.
    ledgers[[i]] <- data.frame(
      gene_id = rep.int(ids[[i]], length(components)),
      coordinate_id = vapply(members, .s4_component_id, character(1)),
      numeric_value = values,
      numeric_status = vapply(components, `[[`, character(1), "numeric_status"),
      primitive_members = I(members),
      source_nodes = I(lapply(components, `[[`, "source_nodes")),
      reference_source_nodes = I(lapply(components, `[[`, "reference_source_nodes")),
      stringsAsFactors = FALSE)
    owners[[i]] <- owner
    component_sizes[[i]] <- sizes
  }
  ledger <- do.call(rbind, ledgers)
  rownames(ledger) <- NULL
  fused <- ledger[lengths(ledger$primitive_members) > 1L, , drop = FALSE]
  fused <- fused[!duplicated(fused$coordinate_id), , drop = FALSE]
  # Lexicographic primitive-index order, consistent with the shared F[...] schema.
  if (nrow(fused)) {
    width <- nchar(as.character(length(axis)))
    keys <- vapply(fused$primitive_members, function(m)
      paste(sprintf(paste0("%0", width, "d"), match(m, axis)), collapse = ":"), character(1))
    fused <- fused[order(keys, method = "radix"), , drop = FALSE]
  }
  definitions <- data.frame(coordinate_id = fused$coordinate_id,
    coordinate_type = rep("composite", nrow(fused)),
    member_count = lengths(fused$primitive_members),
    member_text = vapply(fused$primitive_members, paste, character(1), collapse = "|"),
    primitive_members = I(as.list(fused$primitive_members)), stringsAsFactors = FALSE)
  rownames(definitions) <- NULL
  extra <- matrix(NA_real_, length(ids), nrow(definitions),
                  dimnames = list(ids, definitions$coordinate_id))
  cell_count <- length(ids) * nrow(definitions)
  cell_reference <- cell_reason <- cell_recovery <- cell_status <-
    cell_construction <- character(cell_count)
  cell_values <- rep(NA_real_, cell_count)
  cell_sources <- vector("list", cell_count)
  targets <- lapply(definitions$primitive_members, match, table = axis)
  cell_row <- 0L
  for (j in seq_len(nrow(definitions))) for (i in seq_along(ids)) {
    cell <- .s4_fusion_cell(targets[[j]], ledgers[[i]], fusion_view,
                            owners[[i]], component_sizes[[i]])
    extra[i, j] <- cell$numeric_value
    cell_row <- cell_row + 1L
    cell_reference[[cell_row]] <- cell$reference_state
    cell_reason[[cell_row]] <- cell$reference_reason
    cell_recovery[[cell_row]] <- cell$recovery_status
    cell_status[[cell_row]] <- cell$numeric_status
    cell_values[[cell_row]] <- cell$numeric_value
    cell_construction[[cell_row]] <- cell$construction_mode
    cell_sources[[cell_row]] <- cell$components
  }
  fusion_ledger <- data.frame(
    gene_id = rep(ids, times = nrow(definitions)),
    composite_id = rep(definitions$coordinate_id, each = length(ids)),
    reference_state = cell_reference, reference_reason = cell_reason,
    recovery_status = cell_recovery, numeric_status = cell_status,
    numeric_available = is.finite(cell_values), numeric_value = cell_values,
    construction_mode = cell_construction, components = I(cell_sources),
    stringsAsFactors = FALSE)
  out <- list(state_matrix = states, numeric_matrix = cbind(numeric, extra),
    primitive_coordinates = primitive, composite_coordinates = definitions,
    component_ledger = ledger, fusion_ledger = fusion_ledger,
    gene_provenance = data.frame(gene_id = ids, retained_taxa = I(retained),
                                root_promoted = promoted,
                                discarded_root_members = I(discarded_stems),
                                stringsAsFactors = FALSE)
  )
  out
}

# S4 assembly is deliberately separate from the split-mapper result class.
# Input-local B labels and the numeric policy are shared, never the mapping.

.s4_empty_components <- function() {
  data.frame(gene_id = character(), coordinate_id = character(),
    numeric_value = numeric(), numeric_status = character(),
    primitive_members = I(list()), source_nodes = I(list()),
    reference_source_nodes = I(list()),
    stringsAsFactors = FALSE)
}

.s4_component_id <- function(members) {
  if (length(members) == 1L) members else
    paste0("F[", paste(members, collapse = "|"), "]")
}

.s4_fusion_cell <- function(target, components, view, owners, sizes) {
  # Each primitive has exactly one current component, or zero if deleted.
  # Inspect only the target's owners instead of scanning all current edges.
  selected <- owners[target]
  touched <- sort(unique(selected[selected > 0L]))
  sources <- components[touched, , drop = FALSE]
  deleted <- any(selected == 0L)
  # The target and current components contain unique primitive members. Thus
  # equality of these counts is equivalent to whole-component coverage.
  partial <- sum(sizes[touched]) > sum(selected > 0L)
  available <- !deleted && !partial
  state <- if (!available) "unavailable" else
    if (nrow(sources) == 1L) "active" else "decomposable"
  reason <- if (deleted && partial) "deleted_member_and_partial_component" else
    if (deleted) "deleted_member" else if (partial) "partial_component" else "representable"
  status <- "not_applicable"
  value <- NA_real_
  construction <- if (!available) "none" else if (state == "active")
    "single_edge_lookup" else "selected_component_edge_sum"
  if (available) {
    if (state == "decomposable" && view == "direct") {
      status <- "direct_only"
    } else if (any(!is.finite(sources$numeric_value))) {
      status <- "missing_length"
    } else {
      # Each current component appears once. Never sum overlapping global columns.
      value <- sum(sources$numeric_value)
      status <- if (is.finite(value)) "available" else "nonfinite_sum"
      if (!is.finite(value)) value <- NA_real_
    }
  }
  list(reference_state = state, reference_reason = reason,
    recovery_status = if (available) "recovered" else "not_applicable",
    numeric_status = status, numeric_value = value,
    construction_mode = construction, components = sources)
}

.s4_with_gene_context <- function(gene_id, expr) {
  tryCatch(expr, error = function(e) {
    message <- conditionMessage(e)
    context <- paste0("Gene tree `", gene_id, "`")
    # The graph matcher already names its gene with single quotes. Preserve
    # that diagnostic rather than adding a second copy of the same context.
    if (!startsWith(message, context) &&
        !startsWith(message, paste0("Gene tree '", gene_id, "'"))) {
      e$message <- paste0(context, ": ", message)
    }
    if (is.null(e$gene_id)) e$gene_id <- gene_id
    # Rethrow the condition itself: rebuilding a simpleError would lose the
    # native/S4 classes, code, call and any other diagnostic fields.
    stop(e)
  })
}

#' Align fixed-topology trees with separate reference and observation records
#'
#' Supplementary Algorithm S4 uses graph restriction and labeled-tree
#' isomorphism, without a split-mapping backend. Rooted reference identity
#' preserves the original root, as in [reference_truth()]. A separate view
#' matches only the structure represented by the declared gene inputs.
#'
#' @param species_tree Reference Newick text/file or one `ape::phylo` object.
#'   Every internal node of the input reference, including the root, must have
#'   at least two children. Restriction may subsequently leave a unary root.
#' @param gene_trees Gene Newick text/file, `phylo`, `multiPhylo`, or list of trees.
#'   Gene inputs may explicitly retain a unary ancestral stem. This does not
#'   relax the input-reference requirement or the S2 parser.
#' @param gene_ids Optional unique gene identifiers, one per input tree.
#' @param tree_semantics Deprecated compatibility argument. Explicit
#'   `"unrooted"` warns and sets both new semantics to unrooted. The former
#'   `"rooted"` MRCA convention is rejected with migration guidance. Do not
#'   combine this argument with the new semantics arguments.
#' @param fusion_view `"direct"` uses one complete normalized observation
#'   unit; normalization can sum multiple input edges separated by a display
#'   root. `"whole"` also permits sums of multiple complete observation units.
#'   Both views require complete reference-component and observation coverage.
#' @param reference_semantics `"unrooted"` (default) or `"rooted"`. Rooted
#'   identity preserves the original root and its retained ancestral stem.
#' @param gene_semantics `"unrooted"` (default) or `"reference_rooted"`.
#'   The latter requires a rooted reference and an input that actually retains
#'   the declared original-root structure; root length annotations do not
#'   create missing edges. The input declaration is not a statistical claim
#'   about separate identifiability of root-adjacent lengths.
#' @return A `splitaligner_fixed_result` with result schema
#'   `"s4-observation-v1"`. `reference_state_matrix` contains S3 `observed`
#'   (reference eligible), `NA_struct`, and `NA_fuse` for every input gene;
#'   these are not empirical recovery labels. `reference_components` records
#'   their complete memberships. `observation_ledger` contains only actual
#'   normalized input units, with `individual` or `joint` correspondence,
#'   raw input edge IDs/lengths/statuses, normalization mode, and value.
#'   `component_observations` separately records components not represented
#'   in the normalized observation view; those rows are not observations.
#'   Under unrooted gene semantics, ancestral stems lie outside that view even
#'   when explicitly present in the input. Their reason is
#'   `ancestral_stem_outside_unrooted_view`; `input$gene_newicks` retains the
#'   input Newick representations. Primitive observation relation, ID, and
#'   numeric-status matrices make these distinctions visible.
#'
#'   `primitive_matrix`, `fusion_matrix`, and their column concatenation
#'   `numeric_matrix` contain only successfully matched genes. Shared fusion
#'   columns come from the reference restrictions of all input genes, including
#'   skipped genes; joint observations do not create new fusion columns.
#'   `fusion_ledger` records both coverage checks, selected observation units,
#'   numerical availability and construction. A source can contribute once per
#'   target value, and may legitimately be reused by different overlapping
#'   target columns. The old `state_matrix`/`component_ledger` fields are not
#'   aliases for this new schema. No mixed-root Support denominator is defined.
#'
#'   A typed `FIXED_TOPOLOGY_MISMATCH` records and skips that gene; the remaining
#'   genes continue. `gene_outcomes` covers all inputs and metadata reports
#'   input/success/skip counts. All-skipped results retain typed zero-row
#'   empirical tables and reference axes. Other errors remain fatal. After
#'   input conversion, per-gene parsing, preparation and matching errors name
#'   the gene ID and preserve their original condition class and code.
#'   Matching success does not require usable lengths. Source edge
#'   IDs are zero-based postorder incoming-edge indices local to each input Newick; equivalent
#'   rewritten trees may have different raw IDs but the same normalized values.
#'   At least two taxa are required. Reference lengths do not enter S4 values.
#' @examples
#' x <- align_fixed_topology("((A,B),(C,D));",
#'   "(A:1,B:2,(C:3,D:4):7);", reference_semantics = "rooted")
#' x$reference_state_matrix
#' x$primitive_observation_matrix
#' x$observation_ledger
#' @export
align_fixed_topology <- function(species_tree, gene_trees, gene_ids = NULL,
                                tree_semantics = NULL,
                                fusion_view = c("whole", "direct"),
                                reference_semantics = c("unrooted", "rooted"),
                                gene_semantics = c("unrooted", "reference_rooted")) {
  if (!is.null(tree_semantics)) {
    if (!missing(reference_semantics) || !missing(gene_semantics))
      stop("Do not combine deprecated `tree_semantics` with the new semantics arguments.", call. = FALSE)
    legacy <- match.arg(tree_semantics, c("unrooted", "rooted"))
    if (legacy == "rooted")
      stop(paste0("The former `tree_semantics = \"rooted\"` MRCA convention is not retained. ",
        "Migrate explicitly to `reference_semantics = \"rooted\"` and choose ",
        "`gene_semantics = \"unrooted\"` or `\"reference_rooted\"`; ",
        "the new reference identity preserves the original root."), call. = FALSE)
    warning("`tree_semantics` is deprecated; use `reference_semantics` and `gene_semantics`.", call. = FALSE)
    reference_semantics <- gene_semantics <- "unrooted"
  }
  reference_semantics <- match.arg(reference_semantics)
  gene_semantics <- match.arg(gene_semantics)
  fusion_view <- match.arg(fusion_view)
  if (gene_semantics == "reference_rooted" && reference_semantics != "rooted")
    stop("`gene_semantics = \"reference_rooted\"` requires `reference_semantics = \"rooted\"`.", call. = FALSE)
  species <- as_species_newick(species_tree)
  genes <- as_gene_newicks(gene_trees, gene_ids)
  reference <- .s4_reference(cpp_s4_parse_tree(species$text, TRUE), reference_semantics)
  ids <- enc2utf8(as.vector(genes$ids))
  prepared <- observed <- vector("list", length(ids))
  outcomes <- data.frame(input_index = seq_along(ids), gene_id = ids,
    outcome = rep("success", length(ids)), code = rep(NA_character_, length(ids)),
    reason = rep(NA_character_, length(ids)), stringsAsFactors = FALSE)
  for (i in seq_along(ids)) {
    parsed <- .s4_with_gene_context(ids[[i]],
      cpp_s4_parse_tree(genes$newicks[[i]], FALSE))
    prepared[[i]] <- .s4_with_gene_context(ids[[i]],
      .s4_prepare_observation(reference, parsed, ids[[i]]))
    matched <- tryCatch(.s4_with_gene_context(ids[[i]],
      .s4_match_observation(reference, prepared[[i]], gene_semantics)),
      splitaligner_topology_mismatch = function(e) e)
    if (inherits(matched, "splitaligner_topology_mismatch")) {
      if (!identical(matched$code, "FIXED_TOPOLOGY_MISMATCH")) stop(matched)
      outcomes$outcome[[i]] <- "skipped"
      outcomes$code[[i]] <- matched$code
      outcomes$reason[[i]] <- conditionMessage(matched)
    } else {
      observed[[i]] <- matched
    }
    # Retain only the reference component record after matching. Graph
    # snapshots are per-gene scratch space, not a second in-memory tree panel.
    prepared[[i]]$reference_graph <- NULL
    prepared[[i]]$gene_graph <- NULL
  }
  out <- .s4_assemble_observations(reference, prepared, observed, ids, outcomes, fusion_view)
  successful <- sum(outcomes$outcome == "success")
  out$metadata <- list(algorithm = "S4", backend = "graph_restriction_tree_isomorphism",
    result_schema = "s4-observation-v1", observation_schema = "normalized-observation-v1",
    reference_semantics = reference_semantics, gene_semantics = gene_semantics,
    root_policy = if (reference_semantics == "rooted") "original_root_preserved" else "representation_only",
    branch_identity = if (reference_semantics == "rooted") "rooted_reference_edge" else "unrooted_reference_edge",
    fusion_view = fusion_view, fusion_schema = "whole-reference-observation-v1",
    composite_scope = "all_input_reference_restrictions",
    support_status = "not_defined_for_observation_schema",
    n_input = length(ids), n_success = successful,
    n_skipped_topology = length(ids) - successful,
    topology_status = if (successful == length(ids)) "all_matched" else
      if (successful == 0L) "all_skipped" else "partially_matched",
    package_version = as.character(utils::packageVersion("SplitAlignerR")))
  out$input <- list(reference_newick = species$text, species_source = species$source,
    gene_source = genes$source, gene_ids = ids,
    gene_newicks = stats::setNames(genes$newicks, ids))
  class(out) <- c("splitaligner_fixed_result", "list")
  out
}

#' @export
print.splitaligner_fixed_result <- function(x, ...) {
  if (identical(x$metadata$result_schema, "s4-observation-v1")) {
    cat("SplitAlignerR S4 fixed-topology alignment (s4-observation-v1)\n",
      "  Reference: ", x$metadata$reference_semantics, "; gene observations: ",
      x$metadata$gene_semantics, "\n  Genes: ", x$metadata$n_input, "; successful: ",
      x$metadata$n_success, "; topology-skipped: ", x$metadata$n_skipped_topology,
      "\n  Primitive coordinates: ", nrow(x$primitive_coordinates),
      "; shared deletion-fusion coordinates: ", nrow(x$composite_coordinates),
      "\n  Normalized observations: ", nrow(x$observation_ledger), "\n", sep = "")
  } else {
    # Printing historical saved objects does not reinterpret or migrate them.
    cat("SplitAlignerR S4 historical fixed-topology alignment\n",
      "  Semantics: ", x$metadata$tree_semantics, "; root policy: ", x$metadata$root_policy,
      "\n  Genes: ", nrow(x$state_matrix), "; primitive coordinates: ", ncol(x$state_matrix),
      "; shared fusion coordinates: ", nrow(x$composite_coordinates), "\n", sep = "")
  }
  invisible(x)
}
