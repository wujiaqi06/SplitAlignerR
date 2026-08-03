# ENGINE001 packed truth-plan schema freeze

## Decision

Select a deduplicated query pool with a per-query dense/sparse payload choice
and u32 references from active primitive coordinates. The record is called:

```text
SplitAlignerR-PackedTruthPlan-v1
```

The choice is hybrid in representation, not in scientific meaning. Every query
has one canonical split and every primitive has one frozen truth state.

Dense fixed-width and per-primitive sparse candidates remain benchmark
comparators. Measured evidence is in `benchmark/PACKED_SCHEMA_RESULTS.csv`.

## Byte-order and serialization rules

- all integers and IEEE-754 doubles are little-endian;
- all widths below are exact;
- no C++ structure dump, compiler padding, `size_t`, `long`, or native enum is
  serialized;
- reserved bytes are zero and validators reject nonzero reserved bytes;
- offsets are relative to the start declared for that section;
- checked arithmetic precedes every allocation, multiplication, and seek;
- record payloads must be smaller than `2^32` bytes in schema v1 because query
  offsets are u32; larger plans require a future schema major version;
- counts may be u64 at the store level, but one plan's taxa, primitives,
  active references, and query count are u32.

## Truth-state encoding

Two bits per primitive, least-significant pair first within each byte:

```text
0 = Mapped-eligible truth coordinate
1 = NA_struct
2 = NA_fuse
3 = reserved/invalid in a truth plan
```

Padding bits in the final byte are zero. Code 3 is rejected during plan
validation. `NA_topo` is produced only after an eligible empirical query fails;
it is not stored in a pre-empirical truth plan.

## Record header

Every plan record has a 144-byte header:

| byte offset | width | field |
|---:|---:|---|
| 0 | 4 | ASCII `TPLN` |
| 4 | 2 | schema major, u16 = 1 |
| 6 | 2 | schema minor, u16 = 0 |
| 8 | 2 | header bytes, u16 = 144 |
| 10 | 2 | flags, u16 |
| 12 | 8 | finalized pattern ID, u64 |
| 20 | 4 | taxon count, u32 |
| 24 | 4 | primitive count, u32 |
| 28 | 4 | retained-bitset bytes, u32 |
| 32 | 4 | state bytes, u32 |
| 36 | 4 | active query-reference count, u32 |
| 40 | 4 | unique query count, u32 |
| 44 | 1 | state encoding, u8 = 1 (`two_bit_v1`) |
| 45 | 1 | query-reference width, u8 = 4 |
| 46 | 1 | byte-order marker, u8 = 1 (`little`) |
| 47 | 1 | reserved zero |
| 48 | 8 | payload bytes, u64 |
| 56 | 32 | pattern SHA-256 |
| 88 | 32 | species-authority SHA-256 |
| 120 | 8 | payload xxHash64, stored little-endian |
| 128 | 8 | xxHash64 of bytes 0..127, stored little-endian |
| 136 | 8 | reserved zero |

Header validation checks all exact count-derived widths, schema, byte order,
authority identity, pattern identity, reserved bytes, payload length and both
hashes before a query view is returned.

## Payload sections

Sections occur once in this order:

```text
retained_taxa_bitset[ceil(taxon_count / 8)]
truth_states[ceil(primitive_count / 4)]
query_ref[active_query_count]                 u32
query_offset[unique_query_count + 1]          u32
query_pool[query_offset[last]]                bytes
```

Active primitives are exactly those with state 0 or 2, enumerated in frozen
primitive order. Therefore primitive IDs need not be repeated. Each `query_ref`
is a zero-based index into the query pool. State 1 has no query reference.

Offsets are monotonic, begin at zero, end at the exact pool length, and point to
entry boundaries. This gives O(1) entry location without decoding preceding
entries.

## Query-pool entries

Queries are sorted by canonical split bytes and deduplicated before references
are written. Each entry contains:

| relative offset | width | field |
|---:|---:|---|
| 0 | 1 | encoding: 1 dense bitset, 2 sparse u32 IDs |
| 1 | 3 | reserved zero |
| 4 | 4 | selected-side taxon count, u32 |
| 8 | 4 | payload bytes, u32 |
| 12 | variable | query payload |

For encoding 1, payload width is `ceil(taxon_count / 8)`. For encoding 2,
payload width is exactly `4 * selected_count`, and strictly increasing taxon
IDs are stored as u32. The encoder chooses sparse only when its payload is
strictly smaller than the dense bitset; ties choose dense. Both encodings store
the canonical smaller split side, with byte-order tie-breaking for equal sides.

## Exact reconstruction

The record reconstructs fibers without an extra provenance table:

1. decode retained taxa and truth states;
2. associate query references with state-0/state-2 primitives in frozen order;
3. group primitives by identical canonical query entry;
4. a repeated group whose members are all state 2 is one restriction fiber;
5. the sorted primitive-member set is the exact global composite identity;
6. a state-0 primitive is eligible and has its direct projected query;
7. state-1 primitives are structural and have no query.

Mixed state-0/state-2 groups, singleton state-2 groups, duplicate sparse IDs,
out-of-range references, terminal invariant violations, or unreferenced query
pool entries are structural corruption.

## Candidate comparison

The benchmark compares:

```text
dense fixed width:
  one full taxon bitset for every primitive

eligible/active sparse records:
  primitive ID plus selected-side taxon IDs per active primitive

selected hybrid pool:
  deduplicated queries, min(dense bitset, sparse u32 IDs), u32 references
```

The selected pool enables direct C++ query views and exact fiber reconstruction.
The sparse-per-primitive candidate repeats fused queries and needs a secondary
index or variable scan. Dense fixed width remains a useful fast fallback when
the planner proves it smaller for a future topology.

## Store container

`TruthPlanStore-v1` contains:

```text
256-byte fixed store header
packed plan records in finalized pattern-ID order
64-byte index entry per pattern
128-byte completion footer
```

Each index entry is:

```text
pattern_id u64
record_offset u64
record_bytes u64
pattern_sha256[32]
record_xxhash64[8]
```

The store header binds schema, byte order, taxon/primitive/pattern counts,
species fingerprint, index/footer offsets, and header checksum. The footer binds
record count, exact final length, index xxHash64, ordered-record xxHash64, and
whole payload SHA-256.

## Integrity strategy

Selected strategy:

```text
xxHash64 per header/record/index for fast corruption detection
+ strict structural validation
+ SHA-256 for species/pattern/store identity and manifest publication
```

xxHash64 is not treated as collision-proof scientific identity. Exact bitsets
and member bytes decide equality. SHA-256 sidecars and manifest fingerprints
bind durable artifacts.

Validators reject:

- truncated headers, records, index, or footer;
- incorrect schema major or byte order;
- wrong species authority;
- pattern fingerprint mismatch;
- noncanonical retained/query/member encoding;
- checksum mismatch;
- unexpected trailing bytes;
- duplicate or missing finalized pattern IDs.

## Atomic publication

The writer creates a run-ID-specific temporary store in the destination
directory, writes records and index, flushes, writes and validates the footer,
flushes and requests `fsync` where supported, closes handles, computes SHA-256,
writes an incomplete manifest, and atomically renames components. The validated
manifest is renamed last. Cross-device publication is rejected rather than
silently copied non-atomically.

No file lacking the exact completion footer and published validated manifest is
reusable. Cleanup may remove only temporary files carrying the current run ID.
