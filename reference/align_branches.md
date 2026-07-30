# Align gene trees to the species-tree branch-coordinate system

Restrict the reference tree to each gene's retained taxa, classify every
primitive coordinate by graph-first semantics, and then query the
empirical gene-tree splits. Structural state is kept separate from
finite numeric evidence: a recovered split with a software failure
marker remains `mapped` while its numeric value is unavailable.

## Usage

``` r
align_branches(
  species_tree,
  gene_trees,
  mode = c("free", "fixed"),
  gene_ids = NULL,
  ...
)
```

## Arguments

- species_tree:

  Reference species tree: one
  [`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html), a Newick
  string, or a file path. Reference lengths, internal labels/support,
  and annotation blocks are ignored with diagnostics.

- gene_trees:

  One or more empirical gene trees supplied as Newick text, a
  SplitAligner line-based file, one
  [`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html), an
  `ape::multiPhylo`, or a list of `phylo` objects. A line-based record
  may be `gene_id(tree);` or a plain Newick tree.

- mode:

  Character; `"free"` for free-topology trees or `"fixed"` for
  topology-constrained trees. Both modes use the same state semantics;
  fixed-mode topology mismatches are additionally diagnosed.

- gene_ids:

  Optional character vector overriding inferred/file IDs. Explicit IDs
  must be non-missing, nonempty, unique, free of control characters, and
  have no leading or trailing whitespace. Unicode IDs are supported.
  Existing names on character vectors, `multiPhylo` objects, and lists
  follow the same content rules; only missing or empty object names
  receive deterministic automatic IDs.

- ...:

  Reserved; additional arguments currently signal an error.

## Value

A `splitaligner_result` list containing the primitive `state_matrix`,
primitive-plus-composite `numeric_matrix`, long state and composite
ledgers, coordinate provenance, structured diagnostics, validated
species tree, and versioned metadata.

## Details

The single-tree state alphabet is exactly `mapped`, `NA_struct`,
`NA_fuse`, and `NA_topo`. Legacy paired-workflow `residual_NA` is not a
fifth state. Failure markers are never converted to zero.

## See also

[`validate_species_tree()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_species_tree.md),
[`validate_branch_length_tokens()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_branch_length_tokens.md)

## Examples

``` r
species <- "((A:1,B:1):1,(C:1,D:1):1);"
genes <- c(g1 = "((A:1,B:1):1,(C:1,D:1):1);")
aligned <- align_branches(species, genes)
aligned$state_matrix
#>    B1       B2       B3       B4       B5      
#> g1 "mapped" "mapped" "mapped" "mapped" "mapped"
```
