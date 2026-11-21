# Each process exits after writing one shard. The parent receives only its axes
# and distinct pattern definitions, plus one support-count row per branch.
job <- readRDS(commandArgs(trailingOnly = TRUE)[[1L]])
.libPaths(job$libs)
suppressPackageStartupMessages(library(SplitAlignerR))

roles <- if (job$mode == "paired") c("free", "fixed") else job$mode
shard <- list()
alignments <- list()
patterns <- list()
support <- list()
branches <- NULL
for (role in roles) {
  trees <- if (role == "fixed" && job$mode == "paired") job$fixed else job$trees
  x <- align_branches(job$reference, trees, mode = role, gene_ids = job$ids, fusion_view = "direct")
  axis <- colnames(x$state_matrix)
  if (is.null(branches)) branches <- axis
  stopifnot(identical(axis, branches), identical(rownames(x$state_matrix), job$ids))
  shard[[paste0(role, "_state")]] <- x$state_matrix
  shard[[paste0(role, "_length")]] <- x$numeric_matrix[, axis, drop = FALSE]
  # The global catalog is not known yet. Store each current edge once in the
  # gene's own coordinate system so later batches can introduce new targets.
  evidence <- list(
    gene_ids = job$ids, primitive_ids = axis,
    state_ledger = x$state_ledger[c("gene_id", "coordinate_id", "state", "composite_id",
                                   "numeric_value", "numeric_status", "projected_split", "source_nodes")],
    composite_ledger = x$composite_ledger[c("gene_id", "composite_id", "recovery_status",
                                            "numeric_value", "numeric_status", "projected_split", "source_nodes")],
    composite_coordinates = x$composite_coordinates[c("coordinate_id", "primitive_members")]
  )
  shard[[paste0(role, "_fibers")]] <- evidence
  defs <- x$composite_coordinates[c("coordinate_id", "primitive_members")]
  patterns[[role]] <- defs
  support[[role]] <- x$support_table[c(
    "coordinate_id", "branch_type", "n_valid_topologies", "n_struct", "n_fused",
    "n_dec", "n_rec", "n_not_recovered"
  )]
  if (role == "free") {
    shard$groups <- free_fusion_groups(x)
  } else {
    groups <- x$composite_ledger
    idx <- match(groups$composite_id, defs$coordinate_id)
    stopifnot(!anyNA(idx))
    groups$primitive_members <- defs$primitive_members[idx]
    shard$fixed_groups <- groups
  }
  if (job$mode == "paired") alignments[[role]] <- x
}
if (job$mode == "paired") {
  paired <- pair_alignment_results(alignments$fixed, alignments$free)
  shard$paired_free <- paired$final_matrix
  shard$paired_fixed <- paired$fixed_final_matrix
}
components <- setdiff(names(shard), c("groups", "fixed_groups", "fixed_fibers", "free_fibers"))
for (nm in components) {
  stopifnot(identical(dimnames(shard[[nm]]), list(job$ids, branches)))
}
saveRDS(shard, job$shard, version = 3L)
saveRDS(list(branches = branches, components = components, patterns = patterns, support = support),
        job$result_file)
