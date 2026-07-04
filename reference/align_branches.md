# Map gene trees onto the species-tree branch-coordinate system

Project the species-tree splits onto each gene's taxon set and classify
every gene-by-branch cell as mapped or as one of the explicit
missingness categories (`NA_struct`, `NA_fuse`, `NA_topo`, residual
`NA`), yielding a standardized gene-by-branch matrix on the frozen
primitive branch-coordinate axis.

## Usage

``` r
align_branches(species_tree, gene_trees, mode = c("free", "fixed"), ...)
```

## Arguments

- species_tree:

  Reference species tree: an `ape::phylo` object, or a Newick string /
  file path.

- gene_trees:

  Gene trees: an `ape::multiPhylo`, a list of `phylo` objects, or a path
  to a SplitAligner line-based Newick file.

- mode:

  Character; `"free"` for free-topology gene trees (which enables the
  `NA_topo` category) or `"fixed"` for topology-constrained gene trees.

- ...:

  Reserved for future arguments.

## Value

(Planned) a gene-by-branch matrix / object in which each
`(gene, branch)` cell holds either a numeric branch value or one of the
explicit missingness labels. Nothing is returned yet: the stub signals a
not-implemented error.

## Status

**Not implemented yet.** This is an interface preview in the public seed
release; calling it raises a clear not-implemented error. The
split-projection engine is under active development.

## See also

[`catnip10_expected()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_expected.md)
for the bundled benchmark expected output.

## Examples

``` r
if (FALSE) { # \dontrun{
# Interface preview (not implemented in the public seed release):
m <- align_branches(species_tree, gene_trees, mode = "free")
} # }
```
