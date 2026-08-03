# ENGINE001 final handoff

## Classification

```text
ENGINE001_DESIGN_PASS
```

All required production contracts are frozen. Selected packed records pass
exact authority round trip, matrix layout has direct large-shape evidence,
ownership/lifecycle is explicit, memory responsibilities are separated,
incomplete runs are rejected, and the implementation/rollback sequence is
closed. Remaining work is implementation under new authorization.

## Selected production contracts

### Packed truth plan

```text
hybrid deduplicated canonical query pool
+ per-query min(dense bitset, sparse sorted u32 taxon IDs)
+ u32 active-primitive query references
+ u32 query offset table
+ 144-byte versioned record header
```

Truth codes are 0 eligible, 1 `NA_struct`, 2 `NA_fuse`, 3 invalid. `NA_topo`
is empirical and absent from truth records. Exact fibers and composite member
sets reconstruct from repeated query references among state-2 primitives.

### Integrity

```text
xxHash64 for fast header/record/tile/index corruption detection
+ strict structural validation
+ SHA-256 for authority, pattern, complete component and manifest identity
```

Hashes never replace exact bitset/member equality.

### Truth store

```text
complete packed bytes <= 80% cache budget:
  contiguous PackedMemoryStore

otherwise with validated local storage:
  PackedDiskStore + hard byte-budgeted packed LRU

otherwise when explicitly feasible:
  RecomputeStore + bounded cache
```

The mapper consumes a scoped immutable view and is backend-independent.

### Matrix

```text
in-memory compact backend when planner-safe
otherwise separate typed 256x256 tiled component files
```

State is u8 over primitive B. Numeric components are binary64 over their frozen
axis plus a one-bit validity component. Missing payload is canonical zero and
validity determines missingness. The manifest binds state, validity, numeric,
registries and fingerprints and is atomically published last.

### R/C++ ownership

R owns user inputs, validation, API, conditions, durable descriptors, summaries,
Support trees and exports. C++ owns immutable canonical authority, truth
construction/store views, empirical split index, one reusable gene buffer,
matrix row/tile writes and counters.

External pointers exist only for active authority/run contexts. They carry
type/ABI/generation/open checks, close idempotently and are never the sole
durable result. Completed files reopen without the original pointer.

### Ordinary workflow

Conceptually:

```r
result <- align_trees(species_tree, gene_trees)
```

Exact exported names remain deferred to ENGINE007. Ordinary users do not select
fixed/free mapper modes, truth backends, cache budgets, tiles or pointers. One
optional control groups advanced resource limits.

Paired fixed/free inputs are directional dataset roles. They share authority,
exact patterns, truth plans and coordinates but keep distinct matrix products.

## Packed-schema benchmark

All rows below use 1,974 actual authority retained-taxa patterns and include the
candidate 144-byte record header.

| candidate | mean bytes/plan | total bytes | encode s | decode s | exact plans |
|---|---:|---:|---:|---:|---:|
| dense fixed width | 23,171.0 | 45,739,554 | 32.919 | 127.045 | 1,974/1,974 |
| sparse per active primitive | 18,770.8 | 37,053,534 | 67.652 | 195.186 | 1,974/1,974 |
| selected hybrid query pool | 19,057.9 | 37,620,244 | 97.667 | 186.644 | 1,974/1,974 |

Truth construction took 161.691 s and the fresh-process sampled peak RSS was
531,234,816 bytes. These timings are pure-R prototype timings and are not C++
production predictions.

Sparse-only is about 1.5% smaller at 302 taxa, but repeats fiber queries, lacks
direct variable-record lookup without another index, and projects worse as
taxon width grows. Observed-302-shape projections for mean record bytes:

| taxa | dense | sparse-only | selected hybrid |
|---:|---:|---:|---:|
| 1,000 | 250,394 | 166,968 | 114,977 |
| 5,000 | 6,251,394 | 3,875,012 | 2,103,208 |

These two rows are derived projections, not executed larger-tree plans.

## Matrix-layout benchmark

The payload is deterministic synthetic state plus numeric data; it does not run
SplitAligner science. Every cell was written and scanned. The production total
adds the exact one-bit numeric validity component.

### 2,275 x 1,086

| layout | write s | column s | full scan s | peak RSS bytes |
|---|---:|---:|---:|---:|
| row-major | 0.070 | 0.011 | 0.018 | 266,862,592 |
| column-major | 0.162 | 0.001 | 0.017 | 218,021,888 |
| selected tiled 256x256 | 0.076 | 0.002 | 0.018 | 243,171,328 |

All three materialized to R and produced the same semantic checksum.

### 100,000 x 4,913

| layout | write s | column s | full scan s | peak RSS bytes |
|---|---:|---:|---:|---:|
| row-major | 14.257 | 2.852 | 2.246 | 387,547,136 |
| column-major | 24.827 | 0.001 | 3.165 | 2,368,995,328 |
| selected tiled 256x256 | 14.698 | 0.131 | 2.282 | 612,581,376 |

Measured state+numeric file length was 4,421,700,576 bytes. Adding the exact
derived validity component gives 4,483,113,364 bytes. Full R materialization was
correctly recorded `NOT_ATTEMPTED_PLANNER_LIMIT` because it exceeded the 1 GiB
prototype gate.

Tiled layout was selected because it remained close to row-major streaming
write speed, improved column extraction by more than an order of magnitude in
the large case, and avoided column-major's 2.37 GB sampled RSS.

## Lifecycle evidence

Manifest validation:

```text
complete matching run:             PASS / accepted
missing footer:                    PASS / rejected
truncated component:               PASS / rejected
wrong species fingerprint:         PASS / rejected
wrong schema:                      PASS / rejected
```

Ownership sketch:

```text
ordinary snapshot independent:     PASS
first close changes state:          PASS
second close idempotent:            PASS
closed context fails safely:        PASS
snapshot survives pointer GC:       PASS
```

Schema v1 does not resume partial output. Restart uses a new run ID. A validated
manifest is published only after component footer, exact length, structural
checks, hashes, close/reopen validation and atomic rename.

## Design gates

```text
scientific completeness:                  PASS
selected packed exact round trip:         PASS (1,974/1,974)
matrix complete typed representation:     PASS
canonical pattern/coordinate identity:    PASS
truth/gene/matrix/R budgets explicit:     PASS
incomplete run detection:                 PASS
reference/shadow compatibility path:      PASS
minimal ordinary workflow:                PASS
automated detailed design gates:          15/15 PASS
```

Unresolved blockers:

```text
NONE
```

Known implementation trade-offs are recorded as revisit conditions, not hidden
blockers: hybrid complexity, multi-file manifest-last publication, conservative
planner thresholds, initial single-thread execution and no schema-v1 resume.

## Production sequence and rollback

```text
ENGINE002: packed schema and truth-store primitives
ENGINE003: compact in-memory and tiled matrix backend
ENGINE004: single-thread C++ truth/empirical kernels
ENGINE005: internal shadow integration and full authority
ENGINE006: Linux/macOS/Windows independent RECERT
ENGINE007: separately authorized public API migration
```

Each stage has a reference-engine rollback point. No stage combines into one
mega-commit or moves the default before independent evidence.

## Recommended next task

```text
ENGINE002 — Core schema and storage primitives
```

It should implement only the frozen record/store schema, exact direct views,
integrity and atomic publication. It must not replace the empirical mapper or
change public defaults.

## Authorization boundary

Production implementation remains unauthorized by ENGINE001. No files under
`R/`, `src/`, tests, package metadata, data, inst, vignettes, public interfaces,
main, tags or releases are modified.
