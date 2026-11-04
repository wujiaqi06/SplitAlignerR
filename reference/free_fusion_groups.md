# Inspect fusion groups on a free gene tree

Taxon restriction determines the primitive members that share each
projected split. Every member has structural state `NA_fuse`. At the
group coordinate, the free tree either displays the exact split or lacks
it (`NA_fuse_topo`). Absence includes an unresolved tree that does not
display the split.

## Usage

``` r
free_fusion_groups(free)
```

## Arguments

- free:

  A `splitaligner_result` from
  [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
  in free mode.

## Value

A data frame with one row per gene and composite, including its
primitive member IDs, projected split, numeric evidence and recovery
status. `graph_class` is `Mapped` or `NA_fuse_topo`. The character
`final_token` holds the recovered group length, literal `"NA"` when the
displayed edge lacks a finite length, or `"NA_fuse_topo"` when the split
is absent. Each composite is counted once, separately from its primitive
members.

## See also

[`pair_alignment_results()`](https://wujiaqi06.github.io/SplitAlignerR/reference/pair_alignment_results.md)
