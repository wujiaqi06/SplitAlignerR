# Align fixed-topology trees with separate reference and observation records

Independent implementation of Supplementary Algorithm S4. A reference
record is restricted by graph pruning and contraction with complete
original-member tracking. A separate matching view represents only the
structure observable under the declared gene semantics. Labeled tree
structure determines the match; no split mapper or branch length
participates in it.
[`align_branches`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
remains the default split-based entry, including for `mode = "fixed"`.

## Usage

``` r
align_fixed_topology(
  species_tree,
  gene_trees,
  gene_ids = NULL,
  tree_semantics = NULL,
  fusion_view = c("whole", "direct"),
  reference_semantics = c("unrooted", "rooted"),
  gene_semantics = c("unrooted", "reference_rooted")
)
```

## Arguments

- species_tree:

  Reference Newick text/file or one
  [`ape::phylo`](https://rdrr.io/pkg/ape/man/read.tree.html) object.
  Every internal node in the original reference, including its root,
  must have at least two children. Unary roots created by reference
  restriction remain valid.

- gene_trees:

  Gene Newick text/file, `phylo`, `multiPhylo`, or list of trees. The
  graph path permits explicit unary stem structure in gene inputs.

- gene_ids:

  Optional unique gene identifiers, one per input tree.

- tree_semantics:

  Deprecated compatibility argument. Explicit `"unrooted"` warns and
  selects unrooted reference and gene semantics when neither new
  semantics argument is supplied. Explicit `"rooted"` raises a migration
  error because the old MRCA restriction changed reference identity. Do
  not mix this argument with the new semantics arguments. Historical
  result objects are not reinterpreted.

- fusion_view:

  `"whole"` constructs shared fusion-column values only from complete
  reference components and complete available observation units.
  `"direct"` retains a value only when the complete target corresponds
  to one normalized observation unit, even when its reference state is
  decomposable. That unit may itself sum multiple input edges when a
  degree-two display root is suppressed.

- reference_semantics:

  `"unrooted"` (default) or `"rooted"`. Rooted reference identity
  preserves the original root and its ancestral stem exactly as
  [`reference_truth`](https://wujiaqi06.github.io/SplitAlignerR/reference/reference_truth.md)
  does. Unrooted display roots do not determine branch identity.

- gene_semantics:

  `"unrooted"` (default), or `"reference_rooted"` for inputs explicitly
  declared to preserve the reference root and its structure. The latter
  requires a rooted reference and the declared original-root structure
  in the input; a root-length annotation does not create a missing edge.
  This declaration does not guarantee statistical identifiability of
  separate root-adjacent lengths.

## Value

A `splitaligner_fixed_result` list using result schema
`s4-observation-v1`. `reference_state_matrix` contains all input rows
and S3 states `observed`, `NA_struct`, and `NA_fuse` on original
coordinates. Here `observed` describes a separately represented
reference branch, not empirical recovery. `reference_components` records
the full memberships and reference-edge sources for every input.

`primitive_matrix` and `fusion_matrix` contain successful genes only, in
input order; `numeric_matrix` combines them. Coordinate tables retain
reference-defined original and deletion-fusion coordinates, including
fusion patterns in the reference restrictions of topology-skipped genes.
The result has no old `state_matrix` or `component_ledger` aliases.

`observation_ledger` records actual normalized observation units for
successful genes, with `individual` or `joint` correspondence, reference
component IDs, full primitive members, input-edge IDs, source lengths
and statuses, `normalization_mode`, numeric status and value.
`individual` means one current reference component, which can itself
contain fused originals; `joint` means multiple reference components.
Normalization mode distinguishes `single_input_edge` from
`input_edge_sum`. Each source occurs once within a target value;
different output columns can legitimately reuse sources. IDs and hashes
are provenance addresses, not portable semantic identities.

`component_observations` also records unrepresented reference
components, with a missing observation ID and a representation reason.
An unrepresented stem is not an observation unit and is not reclassified
as `NA_struct`. The reason `ancestral_stem_outside_unrooted_view`
describes the normalized observation view, not the absence of a stem in
the input. Unrooted normalization removes ancestral stems even when
explicitly present in a gene Newick; `input$gene_newicks` retains the
input Newick representations. An existing input edge without a length
remains an observation and carries its numeric missingness status.
`primitive_observation_matrix` contains `individual`, `joint`,
`unrepresented`, or `NA_struct` for successful genes.
`primitive_numeric_status_matrix` and `primitive_observation_id_matrix`
give the numeric status and provenance link of each original-branch
cell. Joint measurements are never copied or divided into individual
original-branch lengths and do not create deletion-fusion events.

`fusion_ledger` separates reference representability, observation
availability, numeric status and value, construction mode, observation
IDs and contributing sources. Whole-component sums must respect complete
observation units and cannot cut through a joint measurement.

`gene_outcomes` contains every input gene's success or skip outcome,
code and reason. Metadata includes `n_input`, `n_success`,
`n_skipped_topology`, both semantics, root policy and result schema.
All-skipped results retain reference records and a complete skip log,
with typed zero-row numeric matrices and observation ledgers.

## Details

Fixed-topology mismatches are skipped per gene and recorded with
`FIXED_TOPOLOGY_MISMATCH`, gene ID and reason. They are not successes or
`NA_topo` events. Other malformed inputs still raise errors. After input
conversion, per-gene parsing, preparation and matching errors name the
gene ID while preserving the original condition class, code and other
diagnostic fields; `gene_id` is also available on the condition. There
is no fallback to the split mapper. At least two distinct taxa are
required, and gene taxa must be a subset of reference taxa. Gene lengths
follow the package's strict numeric policy; reference lengths do not
supply measurements.

The separate result class is not accepted by existing S2-only support,
paired, exchange or disk-panel accessors. Use the explicit matrices and
ledgers. S4 currently assembles these results in memory.

## Examples

``` r
x <- align_fixed_topology("((A,B),C);",
  c(full = "(C:4,(B:2,A:1):3);", reduced = "(B:5,C:4);"))
x$reference_state_matrix
#>         B1          B2         B3        
#> full    "observed"  "observed" "observed"
#> reduced "NA_struct" "NA_fuse"  "NA_fuse" 
x$numeric_matrix
#>         B1 B2 B3 F[B2|B3]
#> full     1  2  7        9
#> reduced NA NA NA        9
x$observation_ledger
#>   gene_id observation_id   relation reference_component_ids primitive_members
#> 1    full          O[B1] individual                      B1                B1
#> 2    full          O[B2] individual                      B2                B2
#> 3    full          O[B3] individual                      B3                B3
#> 4 reduced       O[B2|B3] individual                F[B2|B3]            B2, B3
#>   input_edge_ids source_lengths source_status normalization_mode numeric_status
#> 1              2              1  finite_n....  single_input_edge finite_numeric
#> 2              1              2  finite_n....  single_input_edge finite_numeric
#> 3           0, 3           4, 3  finite_n....     input_edge_sum finite_numeric
#> 4           0, 1           5, 4  finite_n....     input_edge_sum finite_numeric
#>   numeric_value
#> 1             1
#> 2             2
#> 3             7
#> 4             9
x$gene_outcomes
#>   input_index gene_id outcome code reason
#> 1           1    full success <NA>   <NA>
#> 2           2 reduced success <NA>   <NA>

rooted <- align_fixed_topology("((A:1,B:2):3,(C:4,D:5):6);",
  "((A:1,B:2):3,(C:4,D:5):6);", reference_semantics = "rooted")
rooted$reference_state_matrix
#>             B1         B2         B3         B4         B5         B6        
#> gene_000001 "observed" "observed" "observed" "observed" "observed" "observed"
rooted$observation_ledger
#>       gene_id observation_id   relation reference_component_ids
#> 1 gene_000001          O[B1] individual                      B1
#> 2 gene_000001          O[B2] individual                      B2
#> 3 gene_000001          O[B3] individual                      B3
#> 4 gene_000001          O[B4] individual                      B4
#> 5 gene_000001       O[B5|B6]      joint                  B5, B6
#>   primitive_members input_edge_ids source_lengths source_status
#> 1                B1              0              1  finite_n....
#> 2                B2              1              2  finite_n....
#> 3                B3              3              4  finite_n....
#> 4                B4              4              5  finite_n....
#> 5            B5, B6           2, 5           3, 6  finite_n....
#>   normalization_mode numeric_status numeric_value
#> 1  single_input_edge finite_numeric             1
#> 2  single_input_edge finite_numeric             2
#> 3  single_input_edge finite_numeric             4
#> 4  single_input_edge finite_numeric             5
#> 5     input_edge_sum finite_numeric             9
```
