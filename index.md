# SplitAlignerR

SplitAlignerR aligns gene-tree branches to species-tree coordinates. The
C++17 SplitAlignerFast backend maps exact taxon bitsets through C ABI 2.
A separate pure R implementation independently recomputes the Catnip10
graph-oracle benchmark. The package checks branch-length tokens before
using them as numeric evidence.

**For everyday use, start with
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).**
It uses the split-based Fast backend for both free and fixed inputs.
Setting `mode = "fixed"` does not switch algorithms. Choose
[`align_fixed_topology()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_fixed_topology.md)
explicitly if you want the independent graph path for fixed-topology
data. The Catnip10 oracle is a separate validation tool; you do not need
to select an algorithm to run it.

In the manuscript’s current numbering, reference truth is Algorithm S1,
the Perl workflow is S2, the Fast mapper used by
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
is S3, and
[`align_fixed_topology()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_fixed_topology.md)
is S4. Older software records and filenames retain their original
identifiers: S3 for reference truth and S2 for the Fast-backed R result.
Those identifiers do not select a different algorithm.

`v0.1.0` is the immutable Pro-RECERT-certified release. The default
branch is the post-release development line. The Fast-backed prerelease
has package version `0.1.0.9015` and is not covered by the `v0.1.0`
RECERT decision. The frozen `v0.1.0-rc1`, `v0.1.0-rc2`, and `v0.1.0-rc3`
tags are retained as historical release candidates.

Documentation site: <https://wujiaqi06.github.io/SplitAlignerR/>

## Installation

``` r

# install.packages("remotes")

# Stable, Pro-RECERT-certified release:
remotes::install_github("wujiaqi06/SplitAlignerR@v0.1.0")

# Fast-backed prerelease
remotes::install_github("wujiaqi06/SplitAlignerR@v0.1.0.9015")
```

## Minimal Example

``` r

library(SplitAlignerR)

catnip10_expected()
catnip10_summary_counts()
validate_catnip10_oracle()

# Independently rebuild all Catnip10 graph states in pure R.
rebuilt <- recompute_catnip10_oracle("global")
identical(rebuilt$matrix, catnip10_matrix("global"))

# Inspect the compiled core and its numeric input policy.
splitaligner_core_info()
validate_branch_length_tokens(c("0", "1e-8", "NaN", "1e9999"))

# Parse and canonicalize a reference tree in the C++ core.
validate_species_tree("((A:1,B:1),(C:1,D:1));")

# Align empirical trees. State and finite numeric evidence stay separate.
species <- "((A:1,B:1):1,(C:1,D:1):1);"
genes <- c(
  concordant = "((A:1,B:1):1,(C:1,D:1):1);",
  discordant = "((A:1,C:1):1,(B:1,D:1):1);",
  marker = "((A:NaN,B:1):1,(C:1,D:1):1);"
)
aligned <- align_branches(species, genes, mode = "free")
aligned$state_matrix
aligned$numeric_matrix
```

## Fast-backed development package

Build the prerelease with a C++17 compiler and the Rcpp, ape and digest
packages. Install this prerelease using
`R CMD INSTALL SplitAlignerR_0.1.0.9015.tar.gz`. Use
[`splitaligner_core_info()`](https://wujiaqi06.github.io/SplitAlignerR/reference/splitaligner_core_info.md)
to inspect the active backend and source version.

The mapper uses exact taxon bitsets. It caches coverage projections
within an alignment while preserving the R result’s branch order, source
indices and fusion memberships. The fixed and free outputs retain
separate graph states and numeric evidence. Pair them with
[`pair_alignment_results()`](https://wujiaqi06.github.io/SplitAlignerR/reference/pair_alignment_results.md)
to produce the finalized matrix. Full result objects include per-cell
provenance ledgers.

Projected split text in these ledgers is stored compactly and rendered
on request. It remains a character column: selecting a few records does
not expand every split in the panel. Use the package’s result writer or
`saveRDS(result, file, version = 3)` to retain compact storage. Reading
such a file requires SplitAlignerR 0.1.0.9014 or later. To save ordinary
character columns for older installations, use
`saveRDS(result, file, version = 2)`; expanding the strings can increase
memory use and file size. Operations that request a full character
buffer or edit the text column can also expand it. For panels larger
than available memory, use the batched disk interface below.

The result includes its per-branch Support table and the labeled
reference tree in `aligned$support_table` and `aligned$support_newick`.
To export the pair into a new directory, call
`write_branch_support(aligned, "support")`.

### Fixed-topology alignment with Algorithm S4

For an explicit alternative to the default split mapper, when each gene
tree has the topology of the reference restricted to that gene’s taxa,
use:

``` r

fixed <- align_fixed_topology(
  "((A,B),C);",
  c(full = "(C:4,(B:2,A:1):3);", reduced = "(B:5,C:4);"),
  reference_semantics = "unrooted",
  gene_semantics = "unrooted"
)
fixed$reference_state_matrix # S3 states for every input gene's retained taxa
fixed$numeric_matrix         # Successful genes: original and fusion columns
fixed$observation_ledger     # Actual measurements and their input-edge sources
fixed$component_observations # Includes components absent from the input
fixed$fusion_ledger          # Construction and sources of each fusion-column value
fixed$gene_outcomes          # Successes and skipped genes, with reasons
```

S4 carries original branch members through graph pruning and
contraction, then matches labeled tree structures before reading gene
lengths. It does not call the Fast split mapper. A topology mismatch
skips that gene and records its ID and reason; it does not become
`NA_topo`. Other invalid inputs still raise errors. Check
`fixed$metadata$n_input`, `n_success` and `n_skipped_topology` before
using a result. If every gene is skipped, the result contains the full
log and zero-row numeric matrices.

Reference identity and input measurements are separate. With
`reference_semantics = "rooted"`, S4 preserves the original reference
root and ancestral stem exactly as S3 does. Gene trees still default to
`gene_semantics = "unrooted"`. If forgetting the root combines two
reference components into one observed edge, its length is recorded once
as a joint observation; it is never copied or divided into two
original-branch values. An ancestral stem absent from the gene input
remains in reference truth but has no measurement. This is distinct from
an input edge whose length is missing. Use
`gene_semantics = "reference_rooted"` only for inputs explicitly
declared to preserve the reference root and its structure; a root-length
annotation does not create a missing edge. The declaration does not
establish that a model can estimate each root-adjacent length
independently.

`reference_state_matrix` has all input rows and only `observed`,
`NA_struct` and `NA_fuse`; `observed` describes reference identity, not
empirical recovery. `primitive_matrix`, `fusion_matrix` and their
combined `numeric_matrix` have successful genes only, in input order.
Reference components and deletion-fusion columns keep their S3
definitions. Joint observations caused by input normalization are kept
separately and do not create deletion fusions or change Support.
`primitive_observation_matrix` reports individual, joint or
unrepresented correspondence, alongside `NA_struct` for deleted
originals.

The default `fusion_view = "whole"` constructs values only from complete
reference components and complete available observation units.
`"direct"` retains a value only when the complete target corresponds to
one normalized observation unit, even when its reference state is
decomposable. Such a unit can itself sum multiple input edges when an
unrooted display root is suppressed; its provenance records
`single_input_edge` or `input_edge_sum`. Sources are counted once per
target value. Different target columns can share sources and are not
independent measurements. Input-edge IDs and hashes are provenance, not
portable identities.

This candidate introduces result schema `s4-observation-v1`, without the
old ambiguous `state_matrix` and `component_ledger` aliases. The old
`tree_semantics = "unrooted"` argument is a deprecated alias and cannot
be mixed with the new arguments. The old rooted spelling raises a
migration error: choose the two new semantics explicitly, since the
former rooted/MRCA result used a different reference definition.
Historical results are unchanged.

This entry returns a separate `splitaligner_fixed_result`; read its
matrices and ledgers directly. Existing support, paired, exchange and
disk-panel accessors accept the S2 result type, not this type. S4
retains ordinary per-cell source tables and assembles the full result in
memory. Reduced temporary assembly allocations do not make it
disk-backed; large provenance-rich results can still require substantial
memory. The batched disk interface applies to
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md),
not
[`align_fixed_topology()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_fixed_topology.md).
Version 0.1.0.9015 is a development prerelease.

### Reference truth tables, including rooted trees

To ask what happens to the original branches when taxa are removed,
supply only the reference tree and retained taxa. No empirical gene tree
is needed:

``` r

truth <- reference_truth(
  "((A:1,B:2):3,C:4);",
  list(full = c("A", "B", "C"), without_C = c("A", "B"),
       only_A = "A", empty = character(0)),
  tree_semantics = "rooted"
)
truth$state_matrix       # observed / NA_struct / NA_fuse on original branches
truth$original_matrix    # Separately retained original-branch lengths
truth$fusion_matrix      # Expected lengths in shared fusion coordinates
truth$component_ledger   # Complete original members and reference-edge sources
```

This S3 entry preserves the **original root and the path to the retained
taxa**. The original root is exempt from degree-two contraction. Its
convention matches the historical rooted benchmark, including the
root-to-MRCA stem. S4 uses the same reference identity and separately
records which components its gene input can measure. Missing input
representation does not change S3 truth.

In a truth table, `observed` means that an original reference branch
remains separately represented; it does not assert recovery in a gene
tree. Expected lengths come only from the reference. If a required
reference length is missing, the expected total stays missing. States
and complete fusion membership still remain available.
`fusion_view = "whole"` and `"direct"` follow the same complete-
component rule as the mapping outputs, with reference sources clearly
labeled.

An empty retained set has no edges. A single retained taxon keeps its
original root-to-tip path in rooted mode; zero or one retained taxon has
no edges in unrooted mode. The existing
[`recompute_catnip10_oracle()`](https://wujiaqi06.github.io/SplitAlignerR/reference/recompute_catnip10_oracle.md)
entry and frozen Catnip10 data are unchanged. These truth tools are
optional; ordinary mapping still starts with
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
and the split-based Fast default.

### Working with large gene collections (0.1.0.9006)

Start with a reference tree and two files containing one named gene tree
per line. In paired mode, use the same gene IDs in the same order in
both files. Choose a new directory on a disk with space for the results.

``` r

panel <- align_panel_to_disk("speciesTree302.nwk", "free.2275genes.nwk",
                            "mammal-panel", mode = "paired",
                            fixed_file = "fix.2275genes.nwk", batch_size = 32L)
read_panel_matrix(panel, "paired_free", genes = c("AASDH", "ABCA1"),
                  branches = c("B1", "B2"))
patterns <- panel_fusion_patterns(panel)
read_panel_groups(panel, genes = "ABCA12")
```

The first pass records each fusion pattern by its original reference
branches and writes per-gene evidence to disk. The second pass reads the
batches for the genes you request. A pattern discovered in the last
batch is available in the same column for any selection. To see whether
a pattern formed and was recovered, pass composite IDs to
[`read_panel_fusions()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_panel_to_disk.md)
and request `field = "recovery_status"`. For a temporary run, pass
`tempfile("mammal-")` as the output directory and keep the returned path
until you finish reading.

The default fusion view uses complete current components. A group formed
in a later batch can receive a sum in an earlier gene. Use
`read_panel_fusion_cells(panel, genes, patterns)` for the source edges
of each selected value, or `fusion_view = "direct"` when creating a
panel for single-edge measurements. Older panels keep their recorded
direct values.

To export a whole matrix, stream the second pass to a new TSV file. Each
row contains one gene, with the same reference and fusion columns
throughout.

``` r

export_panel_matrix(panel, "free-lengths.tsv", "free_length", include_fusions = TRUE)
```

Each new panel also writes `support.tsv` and `support.nwk` under `free/`
or `fixed/`. In paired mode, open `free/support.nwk` for the free-tree
Support percentages and `fixed/support.nwk` for the fixed-tree ones. The
writer sums each branch’s eligible and recovered gene counts across all
batches before computing its label.

The panel stores primitive lengths and states, paired tokens where
requested, and per-gene fusion records. For full per-cell provenance,
use
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
on the genes of interest. Reduce `batch_size` for wider reference trees.
The reference, one batch, the gene and fusion indexes, and the slice you
request need to fit in memory.

### Fusion members and their shared split

For each gene, missing taxa can cause two or more reference branches to
project onto one split. Each primitive member keeps `NA_fuse` in its own
cell. Inspect the group once to find its length or see why the length is
unavailable:

``` r

species <- "((A,B),C,(D,(E,F)));"
genes <- c(g1 = "((A,B):0.31,D,(E,F):0.17);",
           g2 = "((A,B):0.26,E,(D,F));",
           g3 = "((A,D),B,(E,F):0.23);")
free <- align_branches(species, genes, mode = "free")
groups <- free_fusion_groups(free)
groups[, c("gene_id", "primitive_members", "projected_split", "recovery_status",
           "graph_class", "final_token")]
```

For these three genes, the same two reference branches form a fusion
group. The shared split is present at length 0.31 in g1 and 0.26 in g2.
The g3 tree lacks the split, so its group token is `NA_fuse_topo`. Both
members still carry `NA_fuse` in all three genes. A displayed group with
no finite length has graph class `Mapped` and a literal `NA` value. An
unresolved free tree can also lack the split.

Choose the counting unit when tabulating the five outcomes.

``` r

count_free_topology(free, unit = "primitive")
count_free_topology(free, unit = "coordinate")
```

Each row satisfies
`Total = Mapped + NA_struct + NA_fuse + NA_topo + NA_fuse_topo`. For g3,
the absent shared split contributes two to `NA_fuse_topo` in primitive
accounting (Total = 9) and one in coordinate accounting (Total = 8).
`Mapped` counts displayed singletons, including those with missing
lengths. Both units count each structurally lost primitive once. The
accounting weights leave the two primitive cells for the absent split
labeled `NA_fuse`.

Primitive branch recovery uses only eligible reference branches. In g3,
each member of the absent group is already `NA_fuse` in the reference
layer and has no independent observation in the free tree. Each
therefore contributes zero to both the recovery numerator and its
denominator. The group still appears once in the group table.

The default `pair_alignment_results(fixed, free)` exposes the same group
table as `$free_fusion_groups`. Use `rule = "legacy"` for frozen paired
schema 1.0.0 matrices, including their historical residual `NA` tokens.

Use
[`export_splitaligner_exchange()`](https://wujiaqi06.github.io/SplitAlignerR/reference/splitaligner_exchange.md)
for fixed-mode exchange and
[`validate_splitaligner_exchange()`](https://wujiaqi06.github.io/SplitAlignerR/reference/splitaligner_exchange.md)
to verify an exchange object’s structure and seals. See
`?splitaligner_exchange` for its reference-tree requirements.

## V1 Scope

The certified V1 release combines the production mapper with the
independent Catnip10 benchmark track. It includes:

- [`catnip10_expected()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_expected.md)
  /
  [`catnip10_matrix()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_matrix.md)
  for the wide primitive-coordinate oracle matrix;
- [`catnip10_summary_counts()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_summary_counts.md)
  for per-regime status accounting;
- [`catnip10_fusion_groups()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_fusion_groups.md)
  for graph-oracle fused-coordinate membership;
- [`validate_catnip10_oracle()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_catnip10_oracle.md)
  for deterministic benchmark sanity checks;
- [`recompute_catnip10_oracle()`](https://wujiaqi06.github.io/SplitAlignerR/reference/recompute_catnip10_oracle.md)
  for an independent pure R reconstruction of every Catnip10 primitive
  state and fusion group;
- [`validate_branch_length_tokens()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_branch_length_tokens.md)
  for C++ whole-token and finite-range numeric validation;
- [`validate_species_tree()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_species_tree.md)
  for C++ Newick parsing, diagnostics, and canonical unrooted primitive
  coordinates;
- [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md)
  for C++ graph-first primitive classification, empirical split
  recovery, composite provenance, and finite numeric evidence;
- [`coordinate_provenance()`](https://wujiaqi06.github.io/SplitAlignerR/reference/coordinate_provenance.md)
  and [`summary()`](https://rdrr.io/r/base/summary.html) for member-set
  and run-level inspection;
- [`save_splitaligner_result()`](https://wujiaqi06.github.io/SplitAlignerR/reference/save_splitaligner_result.md)
  /
  [`read_splitaligner_result()`](https://wujiaqi06.github.io/SplitAlignerR/reference/read_splitaligner_result.md)
  for checked, lossless result persistence;
- [`pair_alignment_results()`](https://wujiaqi06.github.io/SplitAlignerR/reference/pair_alignment_results.md)
  for a separate fixed/free finalized-output layer that preserves
  literal `NA`, summarizes it as `residual_NA`, and never changes the
  single-tree graph ledger;
- [`splitaligner_core_info()`](https://wujiaqi06.github.io/SplitAlignerR/reference/splitaligner_core_info.md)
  for core, schema, and numeric-policy metadata;
- `catnip10_oracle`, the bundled data object containing the frozen
  species tree, branch-label crosswalk, per-cell oracle states, and
  fusion groups.

The Catnip10 benchmark is discordance-free by design. It exercises the
graph-defined `observed`, `NA_fuse`, and `NA_struct` ledger states under
taxon pruning. `NA_topo` is not expected in this benchmark because
empirical gene-tree discordance is outside the Catnip10 oracle fixture.

## Release and audit boundary

The production mapper lives in the C++ core. R converts inputs and wraps
the result; the Catnip10 Oracle remains a separate pure R node-edge
implementation that never calls the core or uses projected splits for
structural states.

The legacy contract field `finalized_perl_matrices_are_authoritative` is
intentionally named. Here, Perl refers to the frozen SplitAligner
reference implementation; SplitAlignerR does not require Perl at
runtime.

The V1 tests reproduce all 272 frozen Catnip10 primitive cells and all
19 fusion events, and include explicit discordance and unavailable
numeric-evidence toys. The immutable `v0.1.0` source passed independent
Pro RECERT; changes on the default development branch do not inherit
that certification. The scientific, numeric, provenance, and
paired-bookkeeping boundaries are recorded in
`inst/spec/V1_SCIENTIFIC_CONTRACT.md`.

See
[`vignette("quick-start", package = "SplitAlignerR")`](https://wujiaqi06.github.io/SplitAlignerR/articles/quick-start.md)
for the layered result model, batch input forms, diagnostics, provenance
lookup, and save/reload flow.

## Citation

If you use SplitAlignerR, please cite the SplitAligner preprint. A
software DOI has not yet been assigned.

> Wu J. (2026). *SplitAligner: A Gene-Species Tree Reconciliation
> Framework Using Split-Based Branch Mapping.* bioRxiv.
> <https://doi.org/10.64898/2026.02.24.707838>

See
[`CITATION.cff`](https://wujiaqi06.github.io/SplitAlignerR/CITATION.cff)
and `citation("SplitAlignerR")`.

## License

SplitAlignerR uses GPL-3. See
[LICENSE.md](https://wujiaqi06.github.io/SplitAlignerR/LICENSE.md). The
four vendored SplitAlignerFast core files are distributed under the [MIT
License](https://wujiaqi06.github.io/SplitAlignerR/inst/fast-backend/LICENSE).

## Acknowledgments

We are especially grateful to Chao Zhang (张超;
[@chaoszhang](https://github.com/chaoszhang)) of the School of Life
Sciences, Peking University, for his generous technical help and for
sharing his `fastSplitAligner.py` implementation. His implementation
provided an important reference for efficient split-based branch mapping
and a comparison baseline during the development and validation of
SplitAlignerFast.

SplitAlignerR also benefits from this contribution through its shared
SplitAlignerFast core.
