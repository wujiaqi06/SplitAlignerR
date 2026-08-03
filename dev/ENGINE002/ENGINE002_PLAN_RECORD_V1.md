# TruthPlanRecord-v1.0 wire contract

## Scope and meaning

`TruthPlanRecord-v1.0` stores pre-empirical truth only. Its logical state codes
are:

```text
0 = eligible primitive coordinate
1 = NA_struct
2 = NA_fuse
3 = invalid/reserved
```

State 0 does not mean `Mapped`. `NA_topo` is not representable. Code 3 is
rejected by every encoder, decoder, and view.

## Durable rules

All multibyte integers are unsigned little-endian fixed-width values. The
format contains no implicit alignment or padding. Native structure layout,
`sizeof`, packing pragmas, `size_t`, `long`, and native enums never define wire
bytes. Reserved bytes and unused final-byte bits are zero. Schema v1.0 accepts
only major 1, minor 0, header size 144, flags 0, byte-order marker 1, state
encoding 1, and reference width 4. Unknown values fail closed. Trailing bytes
are rejected.

Pattern IDs and primitive IDs are zero-based. Finalized pattern IDs are
contiguous and deterministic after unsigned lexicographic sorting of the exact
full-species-universe retained bitsets. Primitive IDs use the immutable
`SpeciesAuthority` order. Taxon ID 0 is the least-significant bit of retained
byte 0. Primitive ID 0 occupies bits 0-1 of state byte 0.

## Header: exactly 144 bytes

| offset | width | encoding | field | v1.0 requirement |
|---:|---:|---|---|---|
| 0 | 4 | ASCII | magic | `TPLN` |
| 4 | 2 | u16 | schema_major | 1 |
| 6 | 2 | u16 | schema_minor | 0 |
| 8 | 2 | u16 | header_bytes | 144 |
| 10 | 2 | u16 | flags | 0 |
| 12 | 8 | u64 | pattern_id | zero-based finalized ID |
| 20 | 4 | u32 | global_taxon_count | exact authority count |
| 24 | 4 | u32 | primitive_count | exact authority count |
| 28 | 4 | u32 | retained_bytes | `ceil(global_taxon_count/8)` |
| 32 | 4 | u32 | state_bytes | `ceil(primitive_count/4)` |
| 36 | 4 | u32 | active_count | number of state-0 plus state-2 primitives |
| 40 | 4 | u32 | query_count | unique canonical queries |
| 44 | 1 | u8 | state_encoding | 1 (`two_bit_v1`) |
| 45 | 1 | u8 | query_ref_width | 4 |
| 46 | 1 | u8 | byte_order | 1 (`little`) |
| 47 | 1 | u8 | reserved | 0 |
| 48 | 8 | u64 | payload_bytes | exact payload length; `< 2^32` |
| 56 | 32 | bytes | retained_pattern_sha256 | identity formula in registry contract |
| 88 | 32 | bytes | species_authority_sha256 | exact open authority |
| 120 | 8 | u64 | payload_xxh64 | XXH64 seed 0 over exact payload |
| 128 | 8 | u64 | header_xxh64 | XXH64 seed 0 over bytes 0-127 |
| 136 | 8 | bytes | reserved | all zero |

The widths total exactly 144 bytes. The checksum at 128 deliberately preserves
the accepted ENGINE001 scope of bytes 0-127; whole-record XXH64 covers the full
144-byte header and payload. Reserved bytes 136-143 are also validated directly.

## Payload sections

The payload immediately follows the header and consists of exactly:

| order | width | section |
|---:|---:|---|
| 1 | `retained_bytes` | retained-taxa bitset |
| 2 | `state_bytes` | two-bit primitive states |
| 3 | `4 * active_count` | query references, u32 |
| 4 | `4 * (query_count + 1)` | query offsets, u32 |
| 5 | `query_offset[query_count]` | query-pool bytes |

Checked arithmetic precedes every addition, multiplication, offset, allocation,
seek, and cast. The exact payload length must be smaller than `2^32`. Counts
must fit their declared widths and the host/API allocation and seek limits.

Active primitives are the state-0 and state-2 primitives enumerated in frozen
primitive order. There is exactly one reference for each. State-1 primitives
have no reference. References are zero-based and in range.

Offsets begin at zero, are monotone, identify exact entry boundaries, and the
last offset equals the pool byte length. When `active_count = query_count = 0`,
the sole offset is u32 zero and the pool is empty. This is the only zero-query
representation and is valid only when the truth object has no active query.

## Query-pool entry

Each entry has a 12-byte prefix followed by its payload:

| relative offset | width | encoding | field |
|---:|---:|---|---|
| 0 | 1 | u8 | encoding: 1 dense, 2 sparse |
| 1 | 3 | bytes | reserved zero |
| 4 | 4 | u32 | selected_count |
| 8 | 4 | u32 | query_payload_bytes |
| 12 | variable | bytes | encoded selected side |

The scientific canonical value of every entry is the dense
`ceil(global_taxon_count/8)` selected-side bitset. The query pool is strictly
sorted by these dense bytes using unsigned lexicographic comparison and has no
duplicates. Physical dense/sparse encoding never changes this order.

Dense encoding uses exactly `ceil(global_taxon_count/8)` bytes. Selected bits
are a subset of retained taxa, unused final-byte bits are zero, and popcount
equals `selected_count`. Sparse encoding uses exactly `4 * selected_count`
bytes containing zero-based u32 taxon IDs that strictly increase, are in range,
and are retained. Sparse is selected only when its payload is strictly smaller
than the dense payload; ties use dense.

The selected side must be nonempty and its retained complement must be
nonempty. It is the smaller-popcount side. Equal-size sides use the unsigned
lexicographically smaller of the selected dense bytes and the retained-set
complement dense bytes.

Every query is referenced. Every reference group is one of:

* exactly one state-0 primitive; or
* at least two state-2 primitives.

Mixed state-0/state-2 groups, repeated state-0 groups, singleton state-2 groups,
or unreferenced entries are invalid. A state-2 group is one exact fiber; its
sorted primitive IDs are the composite identity and its common query is the
composite projected query. No orientation or path order is inferred.

## Authority-bound validation

A scientifically usable view requires an exact open `SpeciesAuthority` before
any state or query access. Validation checks authority fingerprint, global taxon
count, primitive count, schema, and generation. Terminal/internal type comes
only from the authority. A retained terminal primitive is state 0 or 2, never
state 1; a missing terminal taxon is state 1. A bare record is not a complete
scientific object.

## Checksum scopes

All XXH64 operations use the exact XXH64 algorithm, seed 0, and little-endian
u64 storage.

```text
payload_xxh64 = XXH64(payload, seed=0)
header_xxh64  = XXH64(header bytes 0..127, seed=0)
record_xxh64  = XXH64(all 144 header bytes || payload, seed=0)
```

`record_xxh64` is returned by the standalone codec and stored in the store
index. It is corruption detection, not scientific identity.

