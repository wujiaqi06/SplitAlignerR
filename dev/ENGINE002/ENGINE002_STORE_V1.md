# TruthPlanStore-v1.0 wire contract

## File layout

One store component is an exact concatenation with no unregistered gap,
alignment byte, padding, or trailing byte:

```text
256-byte store header
TruthPlanRecord-v1.0 records in pattern-ID order
64-byte index entries in pattern-ID order
128-byte completion footer
```

Every store offset is an absolute unsigned u64 offset from file byte zero.
Finalized IDs are zero-based and contiguous. The record and index order is
canonical regardless of insertion order.

## Store header: exactly 256 bytes

| offset | width | encoding | field | v1.0 requirement |
|---:|---:|---|---|---|
| 0 | 8 | ASCII | magic | `SATRST01` |
| 8 | 2 | u16 | store_schema_major | 1 |
| 10 | 2 | u16 | store_schema_minor | 0 |
| 12 | 2 | u16 | header_bytes | 256 |
| 14 | 2 | u16 | flags | 0 |
| 16 | 1 | u8 | byte_order | 1 (`little`) |
| 17 | 1 | u8 | completion_state | 1 (`FINALIZED`) |
| 18 | 2 | u16 | plan_schema_major | 1 |
| 20 | 2 | u16 | plan_schema_minor | 0 |
| 22 | 2 | u16 | plan_header_bytes | 144 |
| 24 | 2 | u16 | index_entry_bytes | 64 |
| 26 | 2 | u16 | footer_bytes | 128 |
| 28 | 4 | bytes | reserved | zero |
| 32 | 4 | u32 | global_taxon_count | authority count |
| 36 | 4 | u32 | primitive_count | authority count |
| 40 | 8 | u64 | pattern_count | finalized record count |
| 48 | 8 | u64 | records_start | 256 |
| 56 | 8 | u64 | index_offset | first index byte |
| 64 | 8 | u64 | footer_offset | first footer byte |
| 72 | 8 | u64 | exact_file_bytes | footer offset + 128 |
| 80 | 8 | u64 | records_bytes | index offset - 256 |
| 88 | 8 | u64 | index_bytes | `64 * pattern_count` |
| 96 | 32 | bytes | species_authority_sha256 | exact authority |
| 128 | 32 | bytes | pattern_registry_sha256 | exact finalized registry |
| 160 | 32 | bytes | truth_semantics_sha256 | frozen semantics |
| 192 | 32 | bytes | store_identity_sha256 | identity-registry formula |
| 224 | 8 | u64 | header_xxh64 | XXH64 seed 0 over bytes 0-223 |
| 232 | 24 | bytes | reserved | zero |

## Index entry: exactly 64 bytes

| offset | width | encoding | field |
|---:|---:|---|---|
| 0 | 8 | u64 | pattern_id |
| 8 | 8 | u64 | record_offset |
| 16 | 8 | u64 | record_bytes |
| 24 | 32 | bytes | retained_pattern_sha256 |
| 56 | 8 | u64 | record_xxh64 |

The first record offset is 256. Each later record begins exactly at the prior
record end. The final record ends at `index_offset`. Index entries themselves
are contiguous. The index ends exactly at `footer_offset`.

## Completion footer: exactly 128 bytes

| offset | width | encoding | field | v1.0 requirement |
|---:|---:|---|---|---|
| 0 | 8 | ASCII | completion_magic | `SATDONE1` |
| 8 | 2 | u16 | store_schema_major | 1 |
| 10 | 2 | u16 | store_schema_minor | 0 |
| 12 | 2 | u16 | footer_bytes | 128 |
| 14 | 2 | u16 | flags | 0 |
| 16 | 8 | u64 | record_count | equals pattern count |
| 24 | 8 | u64 | exact_file_bytes | equals header value |
| 32 | 8 | u64 | ordered_records_xxh64 | exact records region |
| 40 | 8 | u64 | index_xxh64 | exact index region |
| 48 | 32 | bytes | payload_aggregate_sha256 | domain-separated aggregate |
| 80 | 32 | bytes | complete_file_sha256 | normalized self-field rule below |
| 112 | 8 | u64 | footer_xxh64 | normalized footer rule below |
| 120 | 8 | bytes | reserved | zero |

## Empty and single-record stores

An empty store is valid and authority-bound. Its exact geometry is:

```text
pattern_count = 0
records_start = 256
records_bytes = 0
index_offset  = 256
index_bytes   = 0
footer_offset = 256
file_bytes    = 384
```

Its pattern-registry fingerprint uses the zero-count registry formula and its
ordered-record/index XXH64 values are the reference XXH64 empty-input digest.
A single-record store has ID 0 and one index entry.

## Canonical validation

The validator checks exact magic, versions, widths, byte order, flags,
completion state, identities, count-derived sizes, and all checked arithmetic.
It rejects duplicate, missing, or out-of-order IDs; the same ID with different
bytes; the same exact retained pattern under another ID; nonmonotone,
overlapping, gapped, or overflowing ranges; mismatched record headers and index
entries; unsupported schema; nonzero reserved bytes; and trailing bytes.

The header, every record, index, and footer are parsed through explicit byte
loads. No file/API/`size_t`/`streamoff` cast occurs before range checking.

## Integrity scopes

All fixed integers used in identity inputs are little-endian. Domains and
length prefixes are frozen in `ENGINE002_IDENTITY_REGISTRY.md`.

```text
header_xxh64 = XXH64(header bytes 0..223, seed=0)
ordered_records_xxh64 = XXH64(exact records region, seed=0)
index_xxh64 = XXH64(exact index region, seed=0)
```

`payload_aggregate_sha256` is SHA-256 over its domain, record count, and for
each canonical record: pattern ID u64, payload length u64, and exact payload
bytes, each variable byte sequence length-prefixed as specified by the identity
registry.

The footer self-hash is calculated over all 128 footer bytes after normalizing
bytes 80-119 (the complete-file SHA and footer hash fields) to zero. The footer
hash is then stored at 112.

The complete-file SHA-256 is calculated over the exact final file after
normalizing only footer-relative bytes 80-111 (its own field) to zero. The
stored footer hash is included. The digest is then stored at footer offset 80.
This rule has no circular coverage. The separately published manifest SHA-256
covers every actual file byte, including the stored complete-file digest.

## Publication acceptance

A structurally valid component, even with a valid footer, is not an accepted
store. Acceptance additionally requires the exact final `VALIDATED` manifest,
component size and actual-byte SHA-256, authority/registry/semantics identity,
and final-name revalidation defined by `ENGINE002_ATOMIC_PUBLICATION.md`.

