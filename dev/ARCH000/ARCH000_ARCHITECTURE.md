# ARCH000 unified shared-truth streaming architecture

## Status and boundary

ARCH000 is a development-only feasibility design. It starts from
`main@e847dd0cc4bc8026cd75a34d2ca75be1b4fe0771` and changes only
`dev/ARCH000/`. It does not change the certified mapper, its schemas, or any
public API. The certified `v0.1.0` object remains the release authority.

A post-release enriched API prototype exposed a representation bottleneck. The
certified v0.1.0 mapper and release authority remain unchanged. That earlier
audit stopped before the final 407-key comparison, so ARCH000 does not describe
API000A as a complete authority PASS and does not invent a peak-RSS value for
it.

## Frozen scientific invariants

For one species tree and one exact retained-taxa set, restriction, deleted
primitive edges, degree-two suppression, fibers, structural/fused/eligible
primitive states, composite member sets, and projected query splits are truth.
They are independent of empirical gene topology. Empirical topology can only
refine an eligible coordinate to `mapped` or `NA_topo` and provide finite
numeric evidence.

The architecture therefore separates:

1. immutable pattern-specific truth plans;
2. one temporary empirical split index per gene;
3. compact state/numeric output arrays.

`fixed` and `free` are input provenance or paired-analysis roles. They are not
mapper modes in the proposed engine.

## Species-tree authority

The species tree is validated once. UTF-8 taxon labels receive canonical IDs
in bytewise label order. Primitive coordinates retain the frozen species-tree
axis and record their terminal/internal type and exact unrooted split. Unrooted
identity is independent of the textual representation root. Duplicate root
aliases resolve to the same primitive coordinate according to the existing
validated axis.

The prototype deliberately consumes `validate_species_tree()` output rather
than creating a second species-tree policy.

## Pass 1: pattern and coordinate discovery

For line-based Newick files, the preferred pass scans one record at a time and
extracts only terminal labels. It maps the exact labels to canonical taxon IDs
and forms a reversible exact pattern key. A hash table may locate a candidate
plan, but exact pattern-key equality establishes identity.

When a pattern appears for the first time, its truth plan is built once. Each
non-singleton projected-edge group emits an exact primitive-member set to the
bounded B* accumulator. Gene ID and temporary pattern key are the only
per-gene discoveries retained.

After the scan, exact pattern keys are canonically sorted and temporary IDs are
remapped to final `P00000001...` IDs. Pattern IDs therefore do not depend on
encounter order, thread scheduling, hash iteration, or operating system.

The experimental taxa-only scanner is accepted only after differential
comparison with the complete package parser. The current package's file
contract is one complete non-comment Newick record per line. Line-wrapped
records are not silently accepted by ARCH000 because the production reader does
not currently accept them.

For an in-memory `multiPhylo`, a future implementation should derive retained
tip sets from the existing objects and reuse those objects in pass 2. It should
not serialize and reread them merely to mimic a file workflow. This interface
is convenient, but it is not the bounded-memory route for hundreds of thousands
of loci because the caller has already materialized all trees.

## Exact and bounded B* discovery

Primitive B coordinates are declared before scanning loci. Only non-singleton
fibers create dynamic B* coordinates. Global B* identity is the exact ordered
set of primitive member IDs, never the pattern-local projected split.

The prototype holds `pending_Bstar` and a sorted exact
`global_unique_Bstar`. When the actual `object.size(pending_Bstar)` reaches the
configured threshold, it performs local sort/unique and a two-way exact merge
with the global set, then clears the pending buffer. Deliberate constant and
truncated hash tests confirm that hashes cannot manufacture identity.

If the global unique set itself exceeds its memory budget, production design
uses sorted run files followed by external merge-unique. Each run contains the
reversible member-set key and a checksum; the final merge compares exact keys.
ARCH000 did not activate disk spill because observed global B* growth remained
small.

Final coordinate order is:

```text
primitive B in frozen species-tree order
+ B* in lexicographic exact primitive-member-vector order
```

Overlapping and nested B* sets remain distinct and are not treated as an
additive or orthogonal basis.

## Pass 2: empirical recovery

After final coordinate discovery, state and numeric matrices are preallocated.
For each record, pass 2:

1. retrieves the immutable truth plan by final pattern ID;
2. fully parses only that empirical tree;
3. builds a temporary exact unrooted split index;
4. queries eligible primitives and applicable composites;
5. fills one row and internal-branch counters;
6. releases the tree and split index before reading the next record.

No per-gene long ledger is retained. The prototype rejects a terminal
`NA_topo` as an invariant violation.

## Compact authority and derived views

The prototype authority contains a raw-byte state matrix (`0 mapped`,
`1 NA_struct`, `2 NA_fuse`, `3 NA_topo`), a double numeric matrix, coordinate
and pattern registries, gene-to-pattern IDs, sparse composite provenance, truth
plans, and internal mapped/topology counters. Human-readable long tables are
derived views or chunked exports, not the primary result.

The R prototype intentionally keeps verbose list-based truth plans so their
semantics can be inspected. Measurements show that this R cache, not the
compact matrices, is the largest remaining component. The production kernel
should replace it with packed bitsets and typed arrays.

## Support(b)

After the last locus, each internal primitive branch receives:

```text
mapped_count / (mapped_count + NA_topo_count)
```

`NA_struct` and `NA_fuse` are excluded. Support is not computed for terminal
branches and is not a per-gene quantity. A future R wrapper can copy internal
support values to the matching standard `ape::phylo$node.label` positions and
return a conventional support-labelled tree. ARCH000 does not modify the
production output path.

## Adaptive execution planner

A production planner can sample an initial record block and report taxa-scan
throughput, full-parse throughput, pattern saturation, B* growth, projected
matrix bytes, and available memory. Its decision is explicit, for example:

```text
Execution plan: two-pass bounded-memory mode
Reason: projected one-pass working set exceeds configured memory budget
Estimated first-pass overhead: 0.27
Observed input throughput: 8.1 MB/s
```

If the storage probe indicates remote or slow media, the diagnostic recommends
staging immutable input to checksummed local scratch. ARCH000 does not add a
public adaptive API.

## Implementability verdict

The architecture preserves the frozen state semantics, exact B* identity,
deterministic registries, and paired residual boundary. The complete 2,275-gene
prototype recovered all 407 frozen residual keys while using compact authority
structures. Remaining work is production engineering and optimization, not an
unresolved conceptual or scientific blocker.
