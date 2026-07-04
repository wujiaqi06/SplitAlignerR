#' Catnip10 benchmark oracle expected outputs
#'
#' Deterministic expected outputs of the Catnip10 10-tip coordinate-audit
#' benchmark, evaluated on the unrooted primitive branch-coordinate axis. The
#' benchmark freezes a random 10-tip tree (R/APE, seed 42) with fixed branch
#' lengths and introduces no rate shift, gene-tree discordance, or estimation
#' error, so every coordinate under taxon pruning is classified by an
#' independent graph-theoretic oracle as observed (numeric), `NA_fuse`, or
#' `NA_struct`. `NA_topo` does not arise in this benchmark by construction.
#'
#' Two cumulative deletion regimes are provided: `global` (outgroup-first,
#' deleting t10, t1, t8, t7, t4, t9, t5) and `local` (locally confined,
#' deleting t8, t7, t4, t9, t5, t2, t3).
#'
#' @format A named list with components:
#' \describe{
#'   \item{species_tree}{character(1); the unrooted 10-tip benchmark species
#'     tree in Newick format.}
#'   \item{branch_map}{data.frame; crosswalk between SplitAligner `B`-labels and
#'     the benchmark unrooted/rooted internal-node labels.}
#'   \item{global}{list for the global regime with elements `matrix`
#'     (8 x 18 data.frame; `gene_id` plus 17 coordinates), `status_long`
#'     (long-format per-cell status), `fusion_groups` (composite fused
#'     coordinates), and `deletion_order` (character vector).}
#'   \item{local}{list for the local regime, same structure as `global`.}
#' }
#' @source Wu J. (2026) SplitAligner preprint,
#'   \doi{10.64898/2026.02.24.707838}; Catnip10 10-tip coordinate-audit
#'   benchmark, unrooted oracle outputs
#'   (`oracle_gene_by_original_branch_matrix.tsv`, `oracle_cell_status_long.tsv`,
#'   `oracle_fusion_groups.tsv`, `branch_label_map.tsv`).
#' @examples
#' str(catnip10_oracle, max.level = 2)
#' catnip10_oracle$global$deletion_order
"catnip10_oracle"
