# Catnip10 benchmark oracle expected outputs

Deterministic expected outputs of the Catnip10 10-tip coordinate-audit
benchmark, evaluated on the unrooted primitive branch-coordinate axis.
The benchmark freezes a random 10-tip tree (R/APE, seed 42) with fixed
branch lengths and introduces no rate shift, gene-tree discordance, or
estimation error, so every coordinate under taxon pruning is classified
by an independent graph-theoretic oracle as observed (numeric),
`NA_fuse`, or `NA_struct`. `NA_topo` does not arise in this benchmark by
construction.

## Usage

``` r
catnip10_oracle
```

## Format

A named list with components:

- species_tree:

  character(1); the unrooted 10-tip benchmark species tree in Newick
  format.

- branch_map:

  data.frame; crosswalk between SplitAligner `B`-labels and the
  benchmark unrooted/rooted internal-node labels.

- global:

  list for the global regime with elements `matrix` (8 x 18 data.frame;
  `gene_id` plus 17 coordinates), `status_long` (long-format per-cell
  status), `fusion_groups` (composite fused coordinates), and
  `deletion_order` (character vector).

- local:

  list for the local regime, same structure as `global`.

## Source

Wu J. (2026) SplitAligner preprint,
[doi:10.64898/2026.02.24.707838](https://doi.org/10.64898/2026.02.24.707838)
; Catnip10 10-tip coordinate-audit benchmark, unrooted oracle outputs
(`oracle_gene_by_original_branch_matrix.tsv`,
`oracle_cell_status_long.tsv`, `oracle_fusion_groups.tsv`,
`branch_label_map.tsv`).

## Details

Two cumulative deletion regimes are provided: `global` (outgroup-first,
deleting t10, t1, t8, t7, t4, t9, t5) and `local` (locally confined,
deleting t8, t7, t4, t9, t5, t2, t3).

## Examples

``` r
str(catnip10_oracle, max.level = 2)
#> List of 4
#>  $ species_tree: chr "(t10:1.464364133,(t1:0.9888917289,(t8:0.0824375581,((t7:0.9057381309,t4:0.4469696281)N_15:0.3902034671,t9:0.836"| __truncated__
#>  $ branch_map  :'data.frame':    18 obs. of  5 variables:
#>   ..$ splitaligner_branch      : chr [1:18] "B11" "B12" "B13" "B14" ...
#>   ..$ benchmark_unrooted_branch: chr [1:18] "N_15" "N_14" "N_13" "N_12" ...
#>   ..$ benchmark_rooted_branch  : chr [1:18] "N_16" "N_15" "N_14" "N_13" ...
#>   ..$ split                    : chr [1:18] "" "" "" "" ...
#>   ..$ note                     : chr [1:18] "internal branch" "internal branch" "internal branch" "internal branch" ...
#>  $ global      :List of 4
#>   ..$ matrix        :'data.frame':   8 obs. of  18 variables:
#>   ..$ status_long   :'data.frame':   136 obs. of  6 variables:
#>   ..$ fusion_groups :'data.frame':   8 obs. of  6 variables:
#>   ..$ deletion_order: chr [1:7] "t10" "t1" "t8" "t7" ...
#>  $ local       :List of 4
#>   ..$ matrix        :'data.frame':   8 obs. of  18 variables:
#>   ..$ status_long   :'data.frame':   136 obs. of  6 variables:
#>   ..$ fusion_groups :'data.frame':   11 obs. of  6 variables:
#>   ..$ deletion_order: chr [1:7] "t8" "t7" "t4" "t9" ...
catnip10_oracle$global$deletion_order
#> [1] "t10" "t1"  "t8"  "t7"  "t4"  "t9"  "t5" 
```
