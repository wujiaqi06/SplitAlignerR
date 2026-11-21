# Construct reference-only branch truth by pruning and contraction

Algorithm S3 restricts a reference tree to retained-taxon sets by graph
pruning and contraction while carrying complete original-edge
memberships. It accepts no empirical gene trees and does not infer
recovery.
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
remains the default split-based mapping entry.

## Usage

``` r
reference_truth(species_tree, retained_taxa, gene_ids = NULL,
  tree_semantics = c("unrooted", "rooted"),
  fusion_view = c("whole", "direct"))
```

## Arguments

- species_tree:

  Reference Newick text/file or one
  [`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html) object. At
  least two distinct reference taxa are required. Every internal node in
  the original input, including its root, must have at least two
  children. Non-root branch lengths provide expected values; a
  display-root length is ignored.

- retained_taxa:

  One character vector, or a list of character vectors of retained
  reference labels. List names supply optional row identifiers. Each set
  must contain unique, nonmissing reference labels. Empty sets are
  allowed.

- gene_ids:

  Optional unique row identifiers, one per retained-taxon set.

- tree_semantics:

  `"unrooted"` (default) or `"rooted"`. Rooted truth preserves the
  original root and its path to the retained-tip MRCA. That root is
  never promoted or suppressed. With one retained taxon, the original
  root-to-tip path remains. Empty sets have no edges; unrooted sets of
  one taxon also have no surviving edges.

- fusion_view:

  `"whole"` constructs expected shared-column values from complete
  current reference components. `"direct"` retains only active fused
  edges.

## Value

A `splitaligner_truth_result` list with a primitive-only `state_matrix`
(`observed`, `NA_struct`, `NA_fuse`), numeric `original_matrix`,
separate `fusion_matrix`, coordinate tables, `component_ledger`,
`fusion_ledger`, `reference_provenance`, `metadata` and `input`.
Component `expected_value` and `expected_status` refer only to reference
lengths. `reference_source_nodes` are zero-based incoming-edge addresses
in the input reference Newick, used only for provenance. The fusion
ledger records reference representability, expected-value status,
construction mode and contributing reference components; it contains no
empirical recovery status.

## Details

The rooted S3 original-root convention also defines the reference layer
of
[`align_fixed_topology`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_fixed_topology.md).
S4 records only the measurements actually represented by its gene input,
without changing this reference truth.

`observed` denotes a separately represented original reference branch,
not an empirical observation. Expected component lengths require every
contributing reference length to be finite. Missing lengths never change
structural identity and are never skipped in a partial sum. Zero,
negative lengths and failure markers follow the package's existing
numeric policy. No `NA_topo` or `NA_fuse_topo` classification occurs in
this layer.

## Examples

``` r
truth <- reference_truth("((A:1,B:2):3,C:4);",
  list(full = c("A", "B", "C"), without_C = c("A", "B"), only_A = "A"),
  tree_semantics = "rooted")
truth$state_matrix
#>           B1         B2          B3          B4        
#> full      "observed" "observed"  "observed"  "observed"
#> without_C "observed" "observed"  "NA_struct" "observed"
#> only_A    "NA_fuse"  "NA_struct" "NA_struct" "NA_fuse" 
truth$original_matrix
#>           B1 B2 B3 B4
#> full       1  2  4  3
#> without_C  1  2 NA  3
#> only_A    NA NA NA NA
truth$fusion_matrix
#>           F[B1|B4]
#> full             4
#> without_C        4
#> only_A           4
```
