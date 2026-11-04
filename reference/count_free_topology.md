# Count the five free-tree topology outcomes using an explicit counting unit

Count the five free-tree topology outcomes using an explicit counting
unit

## Usage

``` r
count_free_topology(free, unit)
```

## Arguments

- free:

  A `splitaligner_result` from
  [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
  in free mode.

- unit:

  Either `"primitive"` or `"coordinate"`. Primitive accounting weights
  each shared projection by its number of primitive members. Coordinate
  accounting counts each shared projection once. Both count each
  singleton once and retain one structural-absence entry per lost
  primitive.

## Value

A data frame with one row per gene and the selected unit. The five
mutually exclusive counts sum to `Total`. `Mapped` and `NA_topo` count
displayed and absent singletons. `NA_fuse` and `NA_fuse_topo` count
displayed and absent shared projections in the selected unit.
`NA_struct` counts lost primitives. Topological presence is independent
of branch lengths. Member cells retain their structural `NA_fuse` label.

## See also

[`free_fusion_groups()`](https://wujiaqi06.github.io/SplitAlignerR/reference/free_fusion_groups.md)

## Examples

``` r
free <- align_branches("((A,B),C,(D,(E,F)));", "((A,D),B,(E,F));")
count_free_topology(free, "primitive")
#>       gene_id      unit Total Mapped NA_struct NA_fuse NA_topo NA_fuse_topo
#> 1 gene_000001 primitive     9      6         1       0       0            2
count_free_topology(free, "coordinate")
#>       gene_id       unit Total Mapped NA_struct NA_fuse NA_topo NA_fuse_topo
#> 1 gene_000001 coordinate     8      6         1       0       0            1
```
