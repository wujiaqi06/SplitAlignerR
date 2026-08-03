# ENGINE001 production kernel design freeze

## Classification

```text
ENGINE001_DESIGN_PASS
```

All mandatory production contracts are specified and the remaining work is
staged implementation. This classification authorizes no production change.

## Frozen architecture

```text
R input/API layer
  -> validated SpeciesAuthority
  -> incremental retained-taxa scan
  -> canonical PatternRegistry
  -> one truth plan per exact pattern
  -> hybrid PackedTruthPlan records
  -> bounded TruthPlanStore
  -> canonical B-star CoordinateRegistry
  -> one reusable GeneWorkBuffer
  -> unified empirical split recovery
  -> in-memory or 256x256 tiled MatrixBackend
  -> BranchCounters and post-scan Support(b)
  -> validated RunManifest published last
```

Fixed/free roles exist only in paired R orchestration. They share authority,
truth and coordinate objects but retain distinct matrix products.

## Major decisions

- Packed truth plan: deduplicated canonical query pool; each query independently
  chooses dense taxon bitset or sparse u32 taxon IDs; active primitives hold u32
  references through an offset table.
- Integrity: xxHash64 for fast record/tile checks plus strict structural
  validation; SHA-256 for scientific identity, complete files and manifests.
- Truth store: packed memory at no more than 80% of cache budget; otherwise
  packed disk plus hard byte-budgeted LRU; bounded recomputation fallback.
- Matrix layout: separate typed component files, 256x256 row-major tiles, tile
  index, validity bitmaps for numeric missingness, validated manifest last.
- Ownership: R owns public and durable objects; an opaque C++ run context owns
  active handles/caches/buffers; external pointers are never durable results.
- Planner: automatically selects memory/file backend from conservative bytes,
  available memory, truth/gene-buffer reserves and validated storage.
- Parallelism: deferred until single-thread authority equivalence; future unit is
  immutable-authority, non-overlapping gene blocks with deterministic reduction.
- Resume: not supported by schema v1; interrupted output is incomplete and a
  restart uses a new run ID.

## Scientific completeness

The object and file schemas preserve:

```text
exact retained taxa
primitive truth states
eligible primitive coordinates
projected primitive queries
restriction fibers
composite member identities and queries
empirical Mapped/NA_topo recovery
finite numeric values and explicit validity
pattern and coordinate registries
sparse composite provenance
branch counters and denominator-zero Support(b)
run provenance and completion identity
```

`NA_topo` is never a truth-plan state. Retained terminal coordinates can only be
Mapped or NA_fuse; a terminal NA_topo remains a hard failure.

## Evidence summary

Actual 302-taxon authority schema comparison rebuilt 1,974 unique plans. Dense,
sparse and hybrid candidates each reconstructed all 1,974 exactly. The selected
hybrid mean was approximately 19.1 KB per record including its frozen 144-byte
record header. It was slightly larger than the scan-only sparse candidate at
302 taxa but supports direct offset-indexed queries and has lower observed-shape
projections at 1,000 and 5,000 taxa.

The isolated matrix benchmark completed every layout at 2,275 x 1,086 and
100,000 x 4,913 cells. The large logical state-plus-numeric files totaled about
4.42 GB. Tiled layout retained near-row-major write throughput while providing
much faster column extraction and substantially lower RSS than column-major.

Manifest prototypes accepted only a complete matching run and rejected missing
footer, truncation, wrong species fingerprint and wrong schema. The ownership
prototype proved ordinary output survives pointer GC, close is idempotent and a
closed context fails safely.

These are isolated R/C++ layout prototypes. They do not claim production kernel
speed and do not rerun the SplitAligner algorithm for synthetic matrices.

## Bounded-memory responsibilities

Four independent budgets are mandatory:

```text
truth-store/cache budget:
  exact packed bytes including cache metadata and pinned-view allowance

GeneWorkBuffer budget:
  one parsed gene, split index, plan view and output row per worker

matrix backend budget:
  in-memory complete arrays or bounded tile buffers plus file bytes

R materialization budget:
  separate explicit limit; no automatic large conversion
```

The planner records estimates and decisions before expensive work. Output
matrix bytes are not attributed to the truth cache.

## Durable completion

Component headers, indices, footers, exact length, structural validation,
xxHash64 checks and SHA-256 all bind a run. Components are written under a
temporary run ID and validated before rename. The `VALIDATED` manifest is
published last. No incomplete file is reused in schema v1.

## Compatibility and API boundary

Ordinary workflow remains conceptually:

```r
result <- align_trees(species_tree, gene_trees)
```

Advanced resource settings are grouped in one optional control. Users do not
select fixed/free mapper modes, caches, matrix layouts, pointers or C++ objects.

The reference engine remains default through ENGINE006. The new engine moves
through internal shadow, compact comparison, explicit opt-in and independent
cross-platform RECERT. Only ENGINE007 may propose a public default change.

## Gates

```text
scientific completeness:                 PASS
selected packed schema exact round trip: PASS (1,974/1,974)
matrix completeness/layout evidence:     PASS
deterministic identity contracts:        PASS
explicit bounded-memory responsibilities:PASS
durable completion/incomplete rejection: PASS
reference compatibility path:            PASS
minimal ordinary API:                    PASS
```

## Non-authorization statement

ENGINE001 changes only `dev/ENGINE001/`. It does not authorize edits under
`R/`, `src/`, tests, metadata, data, inst, vignettes, public interfaces, main,
tags or releases. The next permitted step, if separately ordered, is ENGINE002
core schema and storage primitives.
