#' Inspect fusion groups on a free gene tree
#'
#' Taxon restriction determines the primitive members that share each projected
#' split. Every member has structural state `NA_fuse`. At the group coordinate,
#' the free tree either displays the exact split or lacks it (`NA_fuse_topo`).
#' Absence includes an unresolved tree that does not display the split.
#'
#' @param free A `splitaligner_result` from [align_branches()] in free mode.
#' @return A data frame with one row per gene and composite, including its
#'   primitive member IDs, projected split, numeric evidence and recovery status.
#'   `graph_class` is `Mapped` or `NA_fuse_topo`. The character `final_token`
#'   holds the recovered group length, literal `"NA"` when the displayed edge
#'   lacks a finite length, or `"NA_fuse_topo"` when the split is absent.
#'   Each composite is counted once, separately from its primitive members.
#' @seealso [pair_alignment_results()]
#' @export
free_fusion_groups <- function(free) {
  validate_free_result(free)
  classify_free_groups(free)
}

validate_free_result <- function(free) {
  validate_splitaligner_result_object(free)
  if (!identical(free$metadata$mode, "free")) {
    stop("Supply a free-mode alignment result.", call. = FALSE)
  }
  invisible(TRUE)
}

validated_free_composites <- function(free) {
  primitive <- free$state_ledger
  fused <- which(primitive$state == "NA_fuse")
  composites <- free$composite_ledger
  definitions <- free$composite_coordinates
  group <- match(composites$composite_id, definitions$coordinate_id)
  if (length(fused)) {
    group_key <- function(gene, composite) paste(gene, composite, sep = "\r")
    row <- match(
      group_key(primitive$gene_id[fused], primitive$composite_id[fused]),
      group_key(composites$gene_id, composites$composite_id)
    )
    # Every observed group must contain each declared member exactly once.
    # The result validator already guarantees a unique gene/primitive axis.
    member_key <- function(group, member) paste(group, member, sep = "\r")
    allowed <- member_key(
      rep(definitions$coordinate_id, definitions$member_count),
      unlist(definitions$primitive_members, use.names = FALSE)
    )
    if (anyNA(row) ||
        any(tabulate(row, nrow(composites)) != definitions$member_count[group]) ||
        !all(member_key(primitive$composite_id[fused],
                        primitive$coordinate_id[fused]) %in% allowed) ||
        anyNA(composites$projected_split) ||
        !identical(primitive$projected_split[fused],
                   composites$projected_split[row])) {
      stop("Free projected split or composite membership is inconsistent.",
           call. = FALSE)
    }
    status <- composites$recovery_status
    if (!all(status %in% c("recovered_numeric", "recovered_numeric_unavailable",
                           "unrecovered")) ||
        !identical(status == "recovered_numeric", composites$numeric_available) ||
        !identical(status == "unrecovered", composites$numeric_status == "not_recovered")) {
      stop("Free composite recovery evidence is missing or inconsistent.",
           call. = FALSE)
    }
  }
  composites$primitive_members <- definitions$primitive_members[group]
  composites
}

classify_free_groups <- function(free) {
  composites <- validated_free_composites(free)
  absent <- composites$recovery_status == "unrecovered"
  composites$graph_class <- rep("Mapped", nrow(composites))
  composites$graph_class[absent] <- "NA_fuse_topo"
  composites$final_token <- legacy_numeric_text(composites$numeric_value)
  composites$final_token[absent] <- "NA_fuse_topo"
  composites
}

#' Count the five free-tree topology outcomes using an explicit counting unit
#'
#' @param free A `splitaligner_result` from [align_branches()] in free mode.
#' @param unit Either `"primitive"` or `"coordinate"`. Primitive accounting
#'   weights each shared projection by its number of primitive members.
#'   Coordinate accounting counts each shared projection once. Both count each
#'   singleton once and retain one structural-absence entry per lost primitive.
#' @return A data frame with one row per gene and the selected unit. The
#'   five mutually exclusive counts sum to `Total`. `Mapped` and `NA_topo`
#'   count displayed and absent singletons. `NA_fuse` and `NA_fuse_topo`
#'   count displayed and absent shared projections in the selected unit.
#'   `NA_struct` counts lost primitives. Topological presence is independent
#'   of branch lengths. Member cells retain their structural `NA_fuse` label.
#' @examples
#' free <- align_branches("((A,B),C,(D,(E,F)));", "((A,D),B,(E,F));")
#' count_free_topology(free, "primitive")
#' count_free_topology(free, "coordinate")
#' @seealso [free_fusion_groups()]
#' @export
count_free_topology <- function(free, unit) {
  if (missing(unit) || !is.character(unit) || length(unit) != 1L ||
      !unit %in% c("primitive", "coordinate")) {
    stop('Choose unit = "primitive" or unit = "coordinate".', call. = FALSE)
  }
  validate_free_result(free)
  groups <- validated_free_composites(free)
  states <- free$state_matrix
  genes <- rownames(states)
  displayed <- absent <- numeric(length(genes))
  if (nrow(groups)) {
    weight <- if (unit == "primitive") lengths(groups$primitive_members) else
      rep.int(1L, nrow(groups))
    recovered <- groups$recovery_status != "unrecovered"
    group_gene <- match(groups$gene_id, genes)
    grouped <- rowsum(cbind(weight * recovered, weight * !recovered), group_gene,
                      reorder = FALSE)
    present_genes <- unique(group_gene)
    displayed[present_genes] <- grouped[, 1L]
    absent[present_genes] <- grouped[, 2L]
  }
  mapped <- rowSums(states == "mapped")
  structural <- rowSums(states == "NA_struct")
  topo <- rowSums(states == "NA_topo")
  data.frame(
    gene_id = genes, unit = rep(unit, length(genes)),
    Total = mapped + structural + displayed + topo + absent,
    Mapped = mapped, NA_struct = structural, NA_fuse = displayed,
    NA_topo = topo, NA_fuse_topo = absent,
    row.names = NULL, stringsAsFactors = FALSE
  )
}
