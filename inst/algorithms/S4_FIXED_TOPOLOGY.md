# Algorithm S4: fixed-topology graph alignment

This is the package interface contract for development prerelease 0.1.0.9015,
result schema `s4-observation-v1`. It does not change the manuscript or
reinterpret historical result objects.

The everyday default remains `align_branches()` using S2/Fast, for both free
and fixed inputs. S4 is explicitly selected with `align_fixed_topology()`.
S3 `reference_truth()` accepts retained-taxon sets without empirical trees.
There is no automatic algorithm switching or fallback.

## Input semantics and migration

```r
align_fixed_topology(
  species_tree, gene_trees, gene_ids = NULL,
  tree_semantics = NULL, fusion_view = c("whole", "direct"),
  reference_semantics = c("unrooted", "rooted"),
  gene_semantics = c("unrooted", "reference_rooted")
)
```

- The reference defaults to unrooted. Rooted reference identity preserves the
  original root and its complete retained ancestral stem, exactly as S3 does.
- Gene observations default to unrooted, independently of reference semantics.
- `reference_rooted` requires a rooted reference and an input actually retaining
  the declared original-root structure. A root-length annotation is not an
  edge and cannot substitute for a missing stem. The declaration does not
  establish statistical identifiability of separate root-adjacent lengths.
- The old positional slots remain available. Explicit
  `tree_semantics = "unrooted"` is a warning-producing compatibility alias,
  allowed only when neither new semantics argument was supplied.
- Explicit `tree_semantics = "rooted"` raises a migration error. The historical
  0.1.0.9007--0.1.0.9009 rooted path discarded members above the retained MRCA;
  silently interpreting those calls as original-root preservation would change
  reference identity. Historical saved objects and helper tests remain intact.

## Reference restriction and observation matching

1. Parse the reference and freeze its input-local B aliases. Unrooted
   degree-two display-root aliases describe one primitive edge; rooted
   root-child edges remain distinct. Aliases identify the chosen reference
   coordinates, not cross-tree node identities.
2. For each gene's taxa, construct the S3 reference restriction with complete
   primitive memberships. In rooted mode protect the original root and retain
   its ancestral stem. Classify originals as `observed`, `NA_struct` or
   `NA_fuse`. Here `observed` means a separately represented reference branch,
   not empirical recovery. Reference lengths do not enter S4 measurements.
3. Make a separate matching view. For unrooted inputs, remove ancestral stems
   that connect no retained-taxon pair and suppress degree-two vertices while
   carrying every represented member. For `reference_rooted`, retain the
   declared root and match that rooted structure. Never write matching-view
   removals or contractions back into S3 reference states.
4. Match complete labeled structures by exact tree isomorphism. Orient
   unrooted trees at the same deterministic retained leaf; orient explicitly
   rooted trees at their roots. Intern exact node/child-structure tuples and
   pair matching children. No split mapper, probabilistic fingerprint, input
   node number, branch length or internal support label determines identity.
5. A `FIXED_TOPOLOGY_MISMATCH` skips that gene and records its ID and reason;
   subsequent genes continue. Other input/numeric errors remain fatal. After
   input conversion, per-gene parsing, preparation and matching errors name
   the gene ID and preserve their original condition class, code and diagnostic
   fields. A skipped gene is neither a successful
   alignment nor an `NA_topo` event.
6. For successfully matched genes, record each normalized observation exactly
   once with complete reference-component membership, primitive members, raw
   input-edge IDs, source lengths and source statuses. Only then derive its
   length. Missing length never changes the structural correspondence.

A reference component can have an individual, joint or unrepresented
correspondence. **Individual** means one complete current reference component,
which may already contain multiple deleted-tip fusion members. **Joint** means
that one input observation covers multiple reference components. Joint
correspondence caused by forgetting a root is not a deletion-fusion event.

For rooted reference `((A,B),(C,D));`, two root-adjacent reference branches may
correspond jointly to one unrooted edge. Record that length once, without
copying or dividing it into original-branch measurements. For
`((A,B),C);` restricted to A,B, the original ancestral stem remains in S3;
unrooted `(A:2,B:5);` supplies only the A--B observation of length 7, not the
stem. By contrast, explicitly rooted `((A:2,B:5):7);` represents the retained
stem as an actual edge. The outer display-root annotation supplies no edge.

If that same explicit stem is instead supplied under `gene_semantics = "unrooted"`,
normalization removes it from the observation view. In either the absent-stem
or explicitly supplied-stem case, the reference component's reason is
`ancestral_stem_outside_unrooted_view`. This reason describes the selected
observation view; it does not assert that the input lacked a stem.
`input$gene_newicks` retains the input Newick representations for inspection.

## Numerical construction and provenance

Two coverage conditions apply to every target set C:

1. C must be an exact union of complete S3 current reference components.
   Deleted members and partial reference-component overlaps cannot be filled.
2. C must also be an exact union of complete available observation units.
   A target cannot cut through a joint measurement or use a partially
   represented subset. Every required source must have a usable length.

`fusion_view = "direct"` fills a target only when it corresponds to one
complete normalized observation unit. It does **not** require S3
`reference_state = "active"`: a decomposable target may be measured jointly
as one unit. `fusion_view = "whole"` additionally permits sums of multiple
complete observation units. Neither view creates new shared coordinates from
an arbitrary numerical sum.

Observation normalization records `single_input_edge` or `input_edge_sum`.
Suppressing an unrooted degree-two display root can sum two raw input edges
into one observation even in direct view. Target construction separately
records `single_observation_lookup` or `selected_observation_unit_sum`.
These are different levels of provenance.

Each input edge contributes once to a given target. Overlapping global
columns may reuse the same source, so the columns are not independent
measurements. Never construct a target by summing arbitrary previously filled
composite columns. Input-edge IDs are zero-based incoming-edge addresses
local to their parsed input; rewritten equivalent Newicks can have different
raw IDs and hashes. Compare normalized membership and values semantically under an explicit
reference-coordinate correspondence, without claiming the underlying source
bytes were identical. A reordered reference may require a coordinate crosswalk.

Finite zero and signed lengths follow the existing numeric policy. Missing
lengths or software-failure markers prevent a complete value; no partial sum
is emitted. A complete normalized observation whose finite sources overflow
is an error. Overflow in a sum across distinct observation units leaves that
target unavailable with `nonfinite_sum`.

## Output schema and gene accounting

- `reference_state_matrix` and `reference_components` cover **all input genes**.
  They retain S3 reference states and complete members independently of
  empirical topology agreement.
- `primitive_coordinates` and `composite_coordinates` define reference
  originals and deletion-fusion groups. The shared fusion axis comes from
  reference restrictions of all inputs, including skipped genes. Normalization
  joint groups do not create new deletion-fusion columns.
- `primitive_matrix`, `fusion_matrix`, and their concatenation
  `numeric_matrix` contain **successful genes only**, in input order.
- `observation_ledger` contains actual observations for successful genes,
  with `individual`/`joint` relation and the source records above.
- `component_observations` records each successful gene's reference-component
  correspondence. An unrepresented component has a missing observation ID
  and the reason `ancestral_stem_outside_unrooted_view`; it is not a fake
  observation unit. An existing represented edge lacking
  length remains an observation, with numeric missingness recorded separately.
- `primitive_observation_matrix`, `primitive_observation_id_matrix` and
  `primitive_numeric_status_matrix` expose each successful original cell's
  correspondence, provenance link and numeric status. Deleted originals carry
  `NA_struct` correspondence. A joint observation never fills individual
  original-branch values.
- `fusion_ledger` records reference state/reason, observation status/reason,
  numeric status/value, construction mode, observation IDs and selected sources.
- `gene_outcomes` has one row per input with `input_index`, `gene_id`, outcome,
  code and reason. Metadata has `n_input`, `n_success`, `n_skipped_topology` and
  `topology_status` (`all_matched`, `partially_matched`, `all_skipped`).
  Matching success does not imply usable lengths.

When all genes are skipped, return the reference axes/records and complete
skip log, with typed zero-row numeric matrices and empirical ledgers. Do not
leave skipped rows looking like all-`NA_struct` empirical results. Check gene
counts before downstream analysis. A completed call satisfies
`n_input = n_success + n_skipped_topology`; other errors abort the call.

The schema deliberately has no ambiguous old `state_matrix` or
`component_ledger` aliases. `splitaligner_fixed_result` remains separate from
S2 results. Existing S2 support, paired, exchange and disk-panel accessors do
not accept it. No mixed-root Support denominator is defined; neither joint
observations nor skipped genes silently enter existing Support counts.

## Implementation and scope

The public entry and historical helpers are in `R/fixed-topology.R`.
`R/fixed-observation-graph.R` builds separate reference and matching views;
`R/fixed-observation.R` assembles the new schema. S3 retains its independent
reference-only behavior. Parsing and graph primitives are shared, but S4
never invokes Fast reference projection or split mapping.

At least two distinct taxa are required per input tree, and gene taxa must be
in the reference. Multifurcations must match exactly. Original reference
inputs retain the 0.1.0.9009 contract: every internal node, including the
root, must have at least two children. A unary root created by S3 restriction
is still preserved. Only the graph path's gene-input allowance is broadened:
gene trees may explicitly represent unary stem structure. This does not
broaden original reference inputs or change the S2 parser's contract.
Malformed numeric tokens remain errors.

S4 currently assembles results in memory. This prerelease makes no
large-panel, Linux or publication acceptance claim. The implementation mapping
is: S2/Fast for default mapping, S3 for general rooted/unrooted reference truth,
and S4 for optional fixed-topology graph alignment.
