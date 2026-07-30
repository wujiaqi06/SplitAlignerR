# Apply the frozen paired finalized-matrix bookkeeping layer

Pair fixed-topology and free-topology single-tree results without
modifying either graph-state ledger. The finalized matrix is computed
separately from graph/fiber provenance. Literal `"NA"` is an intentional
finalized token; `residual_NA` is only its descriptive summary name, not
a graph state.

## Usage

``` r
pair_alignment_results(fixed, free)
```

## Arguments

- fixed:

  A `splitaligner_result` generated with `mode = "fixed"`.

- free:

  A `splitaligner_result` generated with `mode = "free"`.

## Value

A `splitaligner_paired_result` containing graph states, fixed and free
pre-promotion matrices, the finalized free matrix, a per-cell ledger,
literal-`NA` summary rows, conventions, and versioned metadata. The
input single-tree results are not modified.

## Details

The free pre-promotion layer contains a numeric token only for a mapped
primitive with finite evidence, `NA_fuse` only for a fused state with
finite composite evidence, and literal `NA` otherwise. Paired
finalization then promotes graph-state `NA_struct` to `NA_struct`, and
promotes graph-state `NA_topo` to `NA_topo` only when the fixed
primitive is mapped with finite evidence. Finite evidence on a fixed
fused coordinate never satisfies that primitive gate. A literal
finalized `NA` remains `NA` on serialization and is summarized as
`residual_NA`.

## Examples

``` r
species <- "(((A,B),C),((D,E),F));"
fixed <- align_branches(
  species, c(g = "((A:1,B:1):1,(D:1,E:1):1);"), mode = "fixed"
)
free <- align_branches(
  species, c(g = "((A:1,D:1):1,(B:1,E:1):1);"), mode = "free"
)
paired <- pair_alignment_results(fixed, free)
paired$residual_NA
#>   gene_id coordinate_id branch_type fixed_primitive_state free_primitive_state
#> 7       g            B7    internal               NA_fuse              NA_fuse
#> 8       g            B8    internal               NA_fuse              NA_fuse
#> 9       g            B9    internal               NA_fuse              NA_fuse
#>   fixed_fiber_member_set free_fiber_member_set
#> 7               B7|B8|B9              B7|B8|B9
#> 8               B7|B8|B9              B7|B8|B9
#> 9               B7|B8|B9              B7|B8|B9
#>   fixed_primitive_numeric_available free_primitive_numeric_available
#> 7                             FALSE                            FALSE
#> 8                             FALSE                            FALSE
#> 9                             FALSE                            FALSE
#>   fixed_fused_numeric_available free_fused_numeric_available
#> 7                          TRUE                        FALSE
#> 8                          TRUE                        FALSE
#> 9                          TRUE                        FALSE
#>   fixed_composite_coordinate free_composite_coordinate
#> 7                F[B7|B8|B9]               F[B7|B8|B9]
#> 8                F[B7|B8|B9]               F[B7|B8|B9]
#> 9                F[B7|B8|B9]               F[B7|B8|B9]
#>   fixed_composite_recovery_status free_composite_recovery_status
#> 7               recovered_numeric                    unrecovered
#> 8               recovered_numeric                    unrecovered
#> 9               recovered_numeric                    unrecovered
#>   free_pre_promotion_token final_matrix_token summary_class residual_NA
#> 7                       NA                 NA   residual_NA        TRUE
#> 8                       NA                 NA   residual_NA        TRUE
#> 9                       NA                 NA   residual_NA        TRUE
```
