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
  validate_splitaligner_result_object(free)
  if (!identical(free$metadata$mode, "free")) {
    stop("Supply a free-mode alignment result.", call. = FALSE)
  }
  classify_free_groups(free)
}

classify_free_groups <- function(free) {
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
  absent <- composites$recovery_status == "unrecovered"
  composites$primitive_members <- definitions$primitive_members[group]
  composites$graph_class <- rep("Mapped", nrow(composites))
  composites$graph_class[absent] <- "NA_fuse_topo"
  composites$final_token <- legacy_numeric_text(composites$numeric_value)
  composites$final_token[absent] <- "NA_fuse_topo"
  composites
}
