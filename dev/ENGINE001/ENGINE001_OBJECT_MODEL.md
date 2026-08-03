# ENGINE001 production object model

## Ownership rule

The durable authority of a completed run is ordinary R metadata plus validated
files. An external pointer may own an active C++ context, cache, or open file,
but it is never the sole durable representation of a completed result.

All run-level scientific axes are immutable after Pass 1 finalization. Mutable
objects are restricted to the truth-store cache, one reusable gene workspace,
non-overlapping matrix rows, branch counters, and lifecycle state.

## `SpeciesAuthority`

Purpose: immutable run-level definition of taxa and primitive coordinates.

Construction input:

- one validated `ape::phylo` or species-tree Newick source;
- UTF-8 taxon labels after the package's existing normalization rules;
- the frozen primitive coordinate ledger produced by canonical unrooted splits.

Fields:

```text
taxon_count:                 u32
canonical_taxon_labels:      length-prefixed UTF-8, canonical byte order
taxon_id:                    u32, 0-based on disk / 1-based only in R views
species_topology:            validated unrooted edge representation
primitive_count:             u32
primitive_edge_id:           u32, frozen order
primitive_canonical_split:   exact taxon bitset
primitive_type:              terminal/internal
ape_node_label_index:        nullable u32 for internal primitives
species_fingerprint:         SHA-256
coordinate_fingerprint:      SHA-256
```

Validation requires at least two unique taxa, exact UTF-8 labels, no unknown or
duplicate taxa, exactly one primitive row per frozen species edge, a complete
terminal/internal classification, and a one-to-one mapping between internal
primitive edges and eligible `ape::phylo$node.label` positions.

Canonicalization sorts taxa by unsigned UTF-8 byte sequence. Every unrooted
split stores the smaller side; equal-size sides use canonical taxon-bitset byte
order. Primitive order is the frozen canonical split order, not traversal or
root order.

The species fingerprint is:

```text
SHA-256(
  "SplitAlignerR-SpeciesAuthority-v1\0" ||
  u32le(taxon_count) ||
  repeated[u32le(label_bytes) || label_utf8] ||
  u32le(primitive_count) ||
  repeated[primitive_type_u8 || canonical_split_bitset]
)
```

The coordinate fingerprint additionally binds primitive order and finalized
canonical B-star member sets.

R constructs and owns the user-visible description. C++ receives an immutable
validated copy owned by an opaque run context. It lives until context close.
Its canonical byte encoding is serializable; the pointer is not.

## `PatternRegistry`

Purpose: exact retained-taxa identity and gene-to-pattern mapping.

Fields:

```text
pattern_id:                 u64
retained_taxa_bitset:       ceil(taxon_count / 8) bytes
pattern_fingerprint:        SHA-256
pattern_frequency:          u64
gene_to_pattern:            u64 per gene
optional_store_locator:     backend-owned, not scientific identity
```

Pass 1 may assign temporary encounter IDs. Final IDs are assigned only after
sorting exact retained bitsets lexicographically as unsigned bytes. Gene rows
are remapped before truth-store or matrix publication. Hashes accelerate bucket
lookup only; exact bitset equality resolves every collision.

The pattern fingerprint is:

```text
SHA-256(
  "SplitAlignerR-Pattern-v1\0" ||
  species_fingerprint ||
  u32le(taxon_count) ||
  retained_taxa_bitset
)
```

`pattern_id` and counts are u64 on disk. Implementations reject values that
overflow addressable storage, `R_xlen_t`, file offsets, or the selected backend;
they must not truncate to R integer. R may expose IDs as decimal strings when
they exceed exactly representable numeric range.

R owns labels and the durable mapping table. C++ owns compact bitsets and the
active lookup index. The finalized registry is immutable and serializable.

## `PackedTruthPlan`

Purpose: one immutable, versioned truth object for one exact pattern.

It must reconstruct exactly:

- retained taxa;
- primitive `eligible`, `NA_struct`, and `NA_fuse` truth states;
- projected primitive query splits;
- restriction fibers;
- composite primitive-member sets;
- composite projected queries;
- eligible primitive coordinates.

`NA_topo` is absent because it is an empirical result. The selected hybrid
query-pool schema is frozen in `ENGINE001_PACKED_SCHEMA.md`.

C++ constructs, encodes, validates, and exposes a read-only view. R may request
a diagnostic decoded copy, but ordinary mapping queries the packed view
directly. A plan is durable only inside a validated store or as ordinary bytes.

## `TruthPlanStore`

Purpose: one backend-neutral scientific interface.

Backends:

```text
PackedMemoryStore
PackedDiskStore
PackedDiskLruStore
RecomputeStore
```

The store owns packed records and any cache. The mapper receives a scoped
read-only `TruthPlanView`; a view cannot outlive the cache pin or lookup call.
Eviction changes performance only. Finalization makes the store immutable.

The disk index binds pattern ID, exact fingerprint, offset, length, and record
checksum. Store reuse requires exact schema major, species fingerprint,
coordinate-independent pattern fingerprint, complete footer, whole-store
SHA-256, and successful structural validation.

## `CoordinateRegistry`

Purpose: the complete matrix-column axis.

Fields:

```text
coordinate_index:           u64
coordinate_type:            primitive/composite
primitive_id:               nullable u32
canonical_member_set:       sorted u32 primitive IDs
member_set_fingerprint:     SHA-256
matrix_column_index:        u64
```

Primitive B occupies the frozen species-axis order. B-star is finalized after
Pass 1 by exact canonical primitive-member bytes and sorted lexicographically.
Projected splits remain pattern-local query values and are never coordinate
identity. Hash-table or encounter order cannot enter final indices.

The coordinate fingerprint is SHA-256 over a domain prefix, the species
fingerprint, primitive count/order/type/canonical split bytes, followed by the
final B-star count and each length-prefixed canonical member-set byte string.

R owns the durable human-readable table and sparse provenance. C++ owns the
compact finalized member arrays and lookup index used during matrix writes.

## `GeneWorkBuffer`

Purpose: one reusable, bounded per-gene workspace.

It contains only:

```text
parsed empirical topology
canonical empirical split index
temporary empirical numeric values
one pinned PackedTruthPlanView
one primitive state row
one numeric coordinate row
temporary fusion values and QC counters
```

For `Tg` retained taxa, `Eg` empirical edges, `B` primitives, `K` composites,
and `W = ceil(T / 64)` taxon words, the conservative logical payload is:

```text
O(Tg + Eg) topology words
+ O(Eg * W) canonical split-index words
+ 8 * Eg numeric bytes
+ B state bytes
+ 8 * (B + K) numeric-row bytes
+ O(B) temporary query/fusion metadata
```

It depends on one gene and finalized coordinate counts, never on the number of
genes. Production must report the configured maximum row-buffer and split-index
bytes. The buffer is cleared or reused after every gene.

## `MatrixBackend`

Purpose: one interface for state and numeric products independent of storage.

Backends:

```text
InMemoryCompactMatrix
TiledFileMatrix
```

R owns the backend descriptor and completed result handle. The C++ run context
owns open handles and tile buffers while active. Finalized file-backed results
remain readable after pointer destruction through the manifest and component
files. Exact operations and layout are frozen in `ENGINE001_MATRIX_BACKEND.md`.

## `BranchCounters`

One compact row per internal primitive branch contains u64 `mapped_count` and
u64 `NA_topo_count`; optional structural/fusion counts are diagnostics only.
Counters reject overflow. Future workers use thread-local arrays followed by a
fixed worker-ID then primitive-ID reduction.

After all genes finish:

```text
denominator = mapped_count + NA_topo_count
Support(b) = mapped_count / denominator, if denominator > 0
Support(b) = NA_real_, otherwise
```

Only internal values map to `ape::phylo$node.label`. Terminal branches receive
no Support value.

## `RunManifest`

Purpose: durable authority and lifecycle root.

Required fields include schema/package/kernel versions, authority and input
fingerprints, gene/primitive/B-star/pattern counts, truth and matrix backends,
budgets, component paths and SHA-256 values, warnings, authority status, and
one lifecycle state:

```text
INCOMPLETE
FINALIZED
VALIDATED
```

Only a `VALIDATED` manifest is published at the final path. JSON is the
human-readable envelope; canonical binary headers and file hashes remain the
machine validation authority. The manifest is an ordinary durable R-readable
file and never depends on an external pointer.
