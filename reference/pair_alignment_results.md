# Finalize paired fixed and free branch alignments

Pair fixed-topology and free-topology single-tree results without
modifying either graph-state ledger. The finalized matrix is computed
separately from graph/fiber provenance. Literal `"NA"` is an intentional
finalized token; `residual_NA` is only its descriptive summary name, not
a graph state.

## Usage

``` r
pair_alignment_results(fixed, free, rule = c("layered", "legacy"))
```

## Arguments

- fixed:

  A `splitaligner_result` generated with `mode = "fixed"`.

- free:

  A `splitaligner_result` generated with `mode = "free"`.

- rule:

  Use the default `"layered"` rule (paired schema 2.0.0) or `"legacy"`
  to reproduce the frozen schema 1.0.0 final matrix.

## Value

A `splitaligner_paired_result` containing graph states, fixed and free
pre-promotion matrices, the finalized free matrix, a per-cell ledger,
literal-`NA` summary rows, conventions, and versioned metadata. The
input single-tree results are not modified. In layered mode,
`free_fusion_groups` reports free-tree recovery once per gene and
composite.

## Details

The free pre-promotion layer contains a numeric token only for a mapped
primitive with finite evidence, `NA_fuse` only for a fused state with
finite composite evidence, and literal `NA` otherwise. Paired
finalization then promotes graph-state `NA_struct` to `NA_struct`, and
promotes graph-state `NA_topo` to `NA_topo` only when the fixed
primitive is mapped with finite evidence. Finite evidence on a fixed
fused coordinate never satisfies that primitive gate. In layered mode,
every fused primitive remains `NA_fuse`. The group carries the recovered
length or, when the projected split is absent, `NA_fuse_topo`. A literal
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
paired$free_fusion_groups
#>   gene_id composite_id projected_split recovery_status numeric_available
#> 1       g  F[B7|B8|B9]      A..B||D..E     unrecovered             FALSE
#>   numeric_value numeric_status primitive_members  graph_class  final_token
#> 1            NA  not_recovered        B7, B8, B9 NA_fuse_topo NA_fuse_topo
```
