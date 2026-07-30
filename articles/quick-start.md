# SplitAlignerR Quick Start

SplitAlignerR aligns empirical gene trees to the primitive
branch-coordinate axis of one reference tree. The production state logic
is implemented once in C++17. R converts inputs, calls that core, and
wraps the result. The bundled Catnip10 Oracle is deliberately separate
pure R node-edge graph surgery; it is benchmark evidence, not a second
production implementation.

## The three result layers

Keep these questions separate:

1.  `state_matrix`: what happened to each primitive reference coordinate
    after taxon restriction and empirical split recovery?
2.  `numeric_matrix`: which primitive or composite coordinates have
    accepted finite branch-length evidence?
3.  provenance: which frozen primitive members define each composite
    coordinate?

The single-tree states are `mapped`, `NA_struct`, `NA_fuse`, and
`NA_topo`. Paired `residual_NA` is the summary name for finalized
literal `NA`; it is not a fifth graph state and it is never written into
a finalized matrix.

## Align one or more gene trees

``` r

library(SplitAlignerR)

species <- "((A:1,B:1):1,(C:1,D:1):1);"
genes <- c(
  concordant = "((A:1,B:1):1,(C:1,D:1):1);",
  discordant = "((A:1,C:1):1,(B:1,D:1):1);",
  marker = "((A:NaN,B:1):1,(C:1,D:1):1);"
)

result <- align_branches(species, genes, mode = "free")
result
#> <splitaligner_result> 3 genes x 5 primitive coordinates; 0 composite coordinates
#>   mapped=14  NA_struct=0  NA_fuse=0  NA_topo=1
#>   core=0.1.0  schema=1.0.0  mode=free
result$state_matrix
#>            B1       B2       B3       B4       B5       
#> concordant "mapped" "mapped" "mapped" "mapped" "mapped" 
#> discordant "mapped" "mapped" "mapped" "mapped" "NA_topo"
#> marker     "mapped" "mapped" "mapped" "mapped" "mapped"
result$numeric_matrix
#>            B1 B2 B3 B4 B5
#> concordant  1  1  1  1  2
#> discordant  1  1  1  1 NA
#> marker     NA  1  1  1  2
```

The discordant tree lacks the reference internal split, so that
primitive cell is `NA_topo`. The `marker` tree still recovers the
terminal split for `A`, so its state is `mapped`; only its numeric value
is unavailable. Software failure markers are never converted to zero and
never manufacture topological absence.

`species_tree` may also be one
[`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html) object or a
file containing one Newick tree. `gene_trees` may be a character vector,
one `phylo`, a named list of `phylo` objects, an `ape::multiPhylo`, or a
line-based file. File records may be plain Newick or use the bounded
`gene_id(tree);` form.

## Optional paired bookkeeping

Fixed and free single-tree results remain independent objects. Pair them
only when their ordered gene and coordinate axes and conventions agree.

``` r

fixed <- align_branches(species, genes["concordant"], mode = "fixed",
                         gene_ids = "g1")
free <- align_branches(species, genes["discordant"], mode = "free",
                        gene_ids = "g1")
paired <- pair_alignment_results(fixed, free)
paired$semantic_state_matrix
#>    B1       B2       B3       B4       B5       
#> g1 "mapped" "mapped" "mapped" "mapped" "NA_topo"
paired$free_pre_promotion_matrix
#>    B1  B2  B3  B4  B5  
#> g1 "1" "1" "1" "1" "NA"
paired$final_matrix
#>    B1  B2  B3  B4  B5       
#> g1 "1" "1" "1" "1" "NA_topo"
paired$residual_NA
#>  [1] gene_id                           coordinate_id                    
#>  [3] branch_type                       fixed_primitive_state            
#>  [5] free_primitive_state              fixed_fiber_member_set           
#>  [7] free_fiber_member_set             fixed_primitive_numeric_available
#>  [9] free_primitive_numeric_available  fixed_fused_numeric_available    
#> [11] free_fused_numeric_available      fixed_composite_coordinate       
#> [13] free_composite_coordinate         fixed_composite_recovery_status  
#> [15] free_composite_recovery_status    free_pre_promotion_token         
#> [17] final_matrix_token                summary_class                    
#> [19] residual_NA                      
#> <0 rows> (or 0-length row.names)
```

The semantic state matrix is the unchanged free single-tree ledger.
Before paired promotion, both `NA_struct` and `NA_topo` graph states are
represented by literal `NA`; only mapped finite evidence becomes numeric
and only a fused state with finite composite evidence becomes `NA_fuse`.
The paired gate then uses the graph state to assign `NA_struct`, or
assigns `NA_topo` only when the fixed primitive is mapped with finite
evidence. A finite fixed fused coordinate cannot satisfy that gate.
Final literal `NA` is retained as `NA` and summarized as `residual_NA`.
Empirical split conflict or adjacent side-clade loss may explain a
frozen data set, but neither is a classification predicate.

## Structural restriction and composite provenance

With only `A` and `B` retained, their primitive terminal coordinates
form one composite path while coordinates on the lost side become
structural absence.

``` r

pruned <- align_branches(species, c(two_taxa = "(A:4,B:5);"))
pruned$state_matrix
#>          B1        B2        B3          B4          B5         
#> two_taxa "NA_fuse" "NA_fuse" "NA_struct" "NA_struct" "NA_struct"
pruned$composite_ledger
#>    gene_id composite_id projected_split   recovery_status numeric_available
#> 1 two_taxa     F[B1|B2]            A||B recovered_numeric              TRUE
#>   numeric_value numeric_status
#> 1             9 finite_numeric
coordinate_provenance(pruned, "F[B1|B2]")
#>   coordinate_id coordinate_type branch_type canonical_reference_split
#> 1      F[B1|B2]       composite   composite                      <NA>
#>   member_count member_text representation_alias_text primitive_members
#> 1            2       B1|B2                      <NA>            B1, B2
```

Numeric evidence for a fused path lives on the composite column in
`numeric_matrix`. It is not copied back into its primitive `NA_fuse`
cells. Composite coordinates are provenance-bearing member sets; this
package does not claim that they form an orthogonal, additive, or
independent basis.

## Summaries and diagnostics

``` r

summary(result)
#> SplitAlignerR summary: 3 genes, 5 primitive, 0 composite coordinates
#>      state count
#>     mapped    14
#>  NA_struct     0
#>    NA_fuse     0
#>    NA_topo     1
#> Finite numeric values: 13
#> Active diagnostic rows: 4
subset(result$diagnostics, count > 0L)
#>       gene_id                       code severity count
#> 8  concordant DUPLICATE_GENE_SPLIT_ALIAS     INFO     1
#> 17 discordant DUPLICATE_GENE_SPLIT_ALIAS     INFO     1
#> 24     marker    SOFTWARE_FAILURE_MARKER     INFO     1
#> 26     marker DUPLICATE_GENE_SPLIT_ALIAS     INFO     1
#>                                                                          message
#> 8       Equivalent root-representation edges were combined as one unrooted split
#> 17      Equivalent root-representation edges were combined as one unrooted split
#> 24 Recognized software failure markers were kept as unavailable numeric evidence
#> 26      Equivalent root-representation edges were combined as one unrooted split
```

Species-tree branch lengths, internal support/labels, annotation blocks,
and a representation-root length are parsed and ignored with structured
diagnostics. Gene-tree internal support/labels and annotation blocks are
also ignored. Gene tip labels, topology, and branch-length evidence are
retained. Duplicate taxa, unexpected taxa, invalid numeric tokens, parse
failures, and incompatible result schemas fail loudly.

Finite negative values are retained with a diagnostic because the
nonnegative theorem scope does not cover them. Decimal overflow and
underflow to zero are rejected. Conventional textual spellings such as
`NaN` and `Inf` are recognized before numeric conversion and classified
as unavailable software evidence.

``` r

validate_branch_length_tokens(c("0", "-0.1", "NaN", "Inf", "1e9999"))
#>    token          classification accepted value is_zero is_negative
#> 1      0          finite_numeric     TRUE   0.0    TRUE       FALSE
#> 2   -0.1          finite_numeric     TRUE  -0.1   FALSE        TRUE
#> 3    NaN software_failure_marker    FALSE    NA      NA          NA
#> 4    Inf software_failure_marker    FALSE    NA      NA          NA
#> 5 1e9999            out_of_range    FALSE    NA      NA          NA
#>                                                                        diagnostic
#> 1                                                          accepted finite double
#> 2 accepted finite double; negative value is outside the nonnegative theorem scope
#> 3                          recognized unavailable marker; never converted to zero
#> 4                          recognized unavailable marker; never converted to zero
#> 5                                 numeric value is not finite in double precision
```

## Save and reload without flattening layers

``` r

path <- tempfile(fileext = ".rds")
save_splitaligner_result(result, path)
restored <- read_splitaligner_result(path)
identical(result, restored)
#> [1] TRUE
```

Reload checks the stored core and result-schema versions by default.
Existing files are not overwritten unless `overwrite = TRUE` is
explicit.

## Benchmark track

``` r

validate_catnip10_oracle()
#>                                                 check status
#> 1                                  package_data_loads   PASS
#> 2 no_unexpected_NA_topo_in_discordance_free_benchmark   PASS
#> 3                             status_counts_available   PASS
#> 4                 matrix_dimensions_match_seed_oracle   PASS
#> 5                    pure_R_graph_oracle_exact_global   PASS
#> 6                     pure_R_graph_oracle_exact_local   PASS
#>                                                                                                                         details
#> 1                                                                             catnip10_oracle contains global and local regimes
#> 2                                                                                                     NA_topo cells observed: 0
#> 3 global total=136 observed=72 NA_fuse=25 NA_struct=39 NA_topo=0; local total=136 observed=69 NA_fuse=24 NA_struct=43 NA_topo=0
#> 4                                                                         Expected each regime matrix to be 8 rows x 18 columns
#> 5                                                         136/136 primitive cells and all fusion groups match the frozen oracle
#> 6                                                         136/136 primitive cells and all fusion groups match the frozen oracle
rebuilt <- recompute_catnip10_oracle("global")
identical(rebuilt$matrix, catnip10_matrix("global"))
#> [1] TRUE
```

The Catnip10 benchmark is discordance-free. Its two cumulative deletion
regimes contain 272 frozen primitive cells in total. The pure R Oracle
recomputes their graph states independently of the C++ mapper.
Development tests additionally cross-check the mapper against every cell
and frozen fusion member set. These are implementation gates, not final
release certification.
