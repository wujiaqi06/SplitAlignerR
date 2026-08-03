# ENGINE001 future user workflow draft

This document freezes workflow shape, not exported names. Exact public names
remain subject to compatibility evidence and ENGINE007 authorization.

## Ordinary single-dataset workflow

Target concept:

```r
result <- align_trees(
  species_tree,
  gene_trees
)
```

Ordinary users do not select mapper mode, truth-store backend, matrix layout,
cache algorithm, tile size, or C++ pointer. The same unified mapper processes
every gene tree.

Accepted input concepts:

```text
species_tree:
  ape::phylo
  one Newick string or file under existing input rules

gene_trees:
  multiPhylo
  validated phylo list
  line-oriented Newick file
  supported connection
  future package file-backed tree source
```

File-backed input is scanned incrementally and is not first converted to one
large `multiPhylo`. ENGINE001 does not implement a new parser.

## Optional control

One optional control object groups advanced resource policy:

```r
control <- splitaligner_control(
  memory_limit = NULL,
  temporary_directory = NULL,
  materialization_limit = NULL,
  keep_files = NULL,
  progress = NULL
)
```

Backend names and layout mechanics are diagnostic/internal in the first
production stages. Defaults are planner-selected and recorded in the manifest.
Top-level parameter proliferation is prohibited.

## Result authority

The logical result makes available:

```text
primitive state matrix
branch-length matrix over B plus B-star
validity information for numeric matrices
primitive/composite coordinate registry
sparse composite provenance
pattern registry and gene-to-pattern mapping
branch counters and Support(b) table
species tree with internal Support(b) in node.label
run summary and validated manifest
```

For a safe in-memory run these may be ordinary compact R matrices. For a large
run, the result is an ordinary R descriptor whose accessors read validated
blocks from files. Both expose the same logical schema.

The result never requires an active external pointer after completion.

## Access and export concepts

```r
state_matrix(result)                 # materialize only when planner-safe
branch_length_matrix(result)
read_alignment_block(result, rows, columns)
coordinate_registry(result)
composite_provenance(result)
branch_support(result)
species_tree_with_support(result)
summary(result)
export_alignment(result, path, format = "tsv")
```

These names are illustrative, not frozen exports. Block access and export are
the preferred large-run paths. A request to materialize beyond the recorded
limit fails with required/projected bytes and suggests block/export access.

## Summary and print

Default output prioritizes:

```text
Genes analyzed
Primitive coordinates
Composite coordinates
Mapped cells
NA_struct cells
NA_fuse cells
NA_topo cells
Truth-store backend
Matrix backend
Completion/validation status
```

Support(b) is branch-level and appears as a table/tree summary, never as a
per-gene statistic. Zero/near-zero branch lengths remain optional numeric
diagnostics rather than mandatory headlines.

## Paired fixed/free workflow

Target concept:

```r
paired <- align_paired_trees(
  species_tree,
  fixed_trees,
  free_trees
)
```

`fixed_trees` and `free_trees` are directional dataset roles for paired
finalization. They are not mapper modes.

The orchestration shares:

```text
SpeciesAuthority
exact retained-pattern identities
TruthPlanStore records for identical patterns
CoordinateRegistry
```

It preserves distinct:

```text
fixed state/numeric matrix products
free state/numeric matrix products
input fingerprints and warnings
dataset-level QC
```

When the second dataset requests an already finalized exact pattern, it reuses
the same packed plan. Pattern IDs are global to the paired run after canonical
finalization; each gene-to-pattern table remains dataset-specific.

Paired finalization derives primitive fusion evidence from the packed fiber
plan, composite numeric column, and gene pattern ID. It does not allocate a
second expanded fusion-provenance matrix.

## Support(b) output

After all genes in one dataset complete, internal primitive counters yield:

```r
support <- mapped_count / (mapped_count + NA_topo_count)
support[denominator == 0] <- NA_real_
```

The result contains a table keyed by internal primitive ID. A copy of the
validated species `phylo` receives the values in the precomputed internal-edge
to `node.label` mapping. Terminal edges have no Support value.

## Errors and recovery

User errors name the explicit stage and preserve the original diagnostic.
Backend planning failures occur before expensive work. Interrupted/failed runs
do not appear completed; schema v1 restarts under a new run ID rather than
resuming partial output.

## Backward-compatible behavior

The certified reference functions remain unchanged during ENGINE002-ENGINE006.
The future workflow first appears as internal/shadow or explicit opt-in. It
cannot become default until cross-platform RECERT and ENGINE007 authorization.
