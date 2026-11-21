# Inspect the source of shared fusion-column values

Inspect whole current components, their empirical matches and their
lengths for selected shared fusion coordinates.

## Usage

``` r
fusion_cells(result, gene_ids = NULL, coordinate_ids = NULL)
```

## Arguments

- result:

  A result from
  [`align_branches`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).

- gene_ids:

  Optional gene IDs in the desired order.

- coordinate_ids:

  Optional shared fusion coordinate IDs.

## Value

One row per selected gene and fusion coordinate with its structural and
recovery states, value, numeric status, applicable construction mode and
a `components` list-column. Each component records its whole primitive
member set, projected split, recovery and numeric evidence.
`source_nodes` lists comma-separated, zero-based postorder node indices
in the input gene Newick. Each names the incoming edge at that node.
Multiple indices for one split identify degree-two aliases collapsed
into one measurement. For an unavailable target, the table shows
surviving touched components, including whole components crossing the
target boundary. For historical direct-only objects, rerun the alignment
to record source indices.

## Examples

``` r
r <- align_branches("((A,B),(C,D));", c(g1 = "(A:1,B:2);",
                                       g2 = "((A:1,B:2):3,(C:4,D:5):6);"))
fusion_cells(r, "g2")
#>   gene_id composite_id reference_state reference_reason recovery_status
#> 1      g2     F[B1|B2]    decomposable    representable       recovered
#>   numeric_status numeric_available numeric_value           construction_mode
#> 1      available              TRUE             3 selected_component_edge_sum
#>     components
#> 1 c("B1", ....
```
