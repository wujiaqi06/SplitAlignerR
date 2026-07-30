# Validate and canonicalize a reference species tree

Parse a reference tree with the C++17 production core, strip reference
branch lengths, internal support/labels, and annotation blocks with
structured diagnostics, and construct the deterministic primitive
coordinate table from canonical unrooted splits. Multifurcations are
retained and never silently refined.

## Usage

``` r
validate_species_tree(species_tree)
```

## Arguments

- species_tree:

  One [`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html) object,
  one Newick string, or a path to a file containing exactly one Newick
  tree.

## Value

A list with `valid`, `tip_labels`, `coordinates`, `diagnostics`,
`metadata`, and `source`. Coordinate rows retain primitive B aliases and
exact split-side taxon lists.

## Examples

``` r
validated <- validate_species_tree("((A:1,B:1),(C:1,D:1));")
validated$coordinates
#>   coordinate_id canonical_split branch_type primitive_alias_text side_a_size
#> 1            B1      A||B..C..D    terminal                   B1           1
#> 2            B2      A..C..D||B    terminal                   B2           3
#> 3            B3      A..B..D||C    terminal                   B3           3
#> 4            B4      A..B..C||D    terminal                   B4           3
#> 5            B5      A..B||C..D    internal                B5|B6           2
#>   side_b_size side_a_taxa side_b_taxa primitive_aliases
#> 1           3           A     B, C, D                B1
#> 2           1     A, C, D           B                B2
#> 3           1     A, B, D           C                B3
#> 4           1     A, B, C           D                B4
#> 5           2        A, B        C, D            B5, B6
#>                                                   note
#> 1                                                     
#> 2                                                     
#> 3                                                     
#> 4                                                     
#> 5 lowest B alias retained for duplicate unrooted split
```
