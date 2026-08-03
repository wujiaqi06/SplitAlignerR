# ENGINE002 identity registry v1

## Common encoding

Every formula below is SHA-256 over the exact concatenation shown. ASCII domain
strings include the displayed terminal NUL byte. Unsigned integers are fixed
width little-endian. A `bytes` value is encoded as `u64 length || value` unless
the formula explicitly fixes its width. UTF-8 labels are length-prefixed and
must already be in the package's canonical authority form.

SHA-256 establishes durable identity. XXH64 is used only for buckets and fast
corruption detection and never decides scientific equality.

## SpeciesAuthority-v1

Domain:

```text
SplitAlignerR/SpeciesAuthority/v1\0
```

Canonical stream:

```text
domain
global_taxon_count:u32
primitive_count:u32
for taxon_id = 0..global_taxon_count-1:
  taxon_id:u32
  canonical_label:bytes
for primitive_id = 0..primitive_count-1:
  primitive_id:u32
  terminal_flag:u8
  reserved_zero[3]
  terminal_taxon_id:u32       # 0xffffffff for an internal primitive
  canonical_full_split:bytes  # global-axis canonical selected-side bitset
```

The split bitset width is exactly `ceil(global_taxon_count/8)` with zero padding
bits. Terminal entries have `terminal_flag=1`, an in-range taxon ID, and the
singleton split for that taxon. Internal entries have flag 0 and sentinel
`0xffffffff`. Primitive order is part of the identity.

ENGINE002 accepts an expected authority digest only after recomputing this
canonical descriptor. A digest supplied without the descriptor cannot create a
scientifically usable authority.

## Retained-pattern fingerprint

Domain:

```text
SplitAlignerR/RetainedPattern/v1\0
```

Canonical stream:

```text
domain
global_taxon_count:u32
retained_bitset:bytes
```

Pattern ID is intentionally absent: exact retained bits are scientific pattern
identity. The registry separately binds those bits to one deterministic ID.

## Pattern-registry fingerprint

Domain:

```text
SplitAlignerR/PatternRegistry/v1\0
```

Canonical stream:

```text
domain
global_taxon_count:u32
pattern_count:u64
for pattern_id = 0..pattern_count-1:
  pattern_id:u64
  retained_bitset:bytes
```

Each bitset has exact global-axis width and zero padding. Final order is
unsigned lexicographic retained-bitset order. Duplicate exact bitsets, missing
IDs, and noncontiguous IDs are rejected before hashing.

## Truth-semantics contract fingerprint

Domain:

```text
SplitAlignerR/TruthSemantics/v1\0
```

The domain is followed by `clause_count:u32 = 8`, then each exact ASCII clause
as `u32 byte_length || clause_bytes`, in this order:

```text
state:0=eligible;1=NA_struct;2=NA_fuse;3=invalid
state0:eligible-not-mapped;NA_topo=absent
primitive_axis:SpeciesAuthority-v1
fiber:same-query;all-state2;size>=2;members=u32le-sorted
query:canonical-dense-selected-side;unsigned-byte-lex
bstar:exact-canonical-primitive-member-set
terminal:retained-terminal!=NA_struct;missing-terminal=NA_struct
schema:TruthPlanRecord-v1.0
```

The resulting digest is a protocol constant generated and checked by the
independent specification validator. It is not derived from compiler output,
timestamps, or source-file metadata.

```text
8323c706880b2e95628e803a408a459113b0ac3edeb4d69e9e0626a77fc57935
```

## Store identity

Domain:

```text
SplitAlignerR/TruthPlanStoreIdentity/v1\0
```

Canonical stream:

```text
domain
species_authority_sha256[32]
pattern_registry_sha256[32]
truth_semantics_sha256[32]
plan_schema_major:u16
plan_schema_minor:u16
store_schema_major:u16
store_schema_minor:u16
```

## Payload aggregate identity

Domain:

```text
SplitAlignerR/TruthPlanPayloadAggregate/v1\0
```

Canonical stream:

```text
domain
record_count:u64
for pattern_id = 0..record_count-1:
  pattern_id:u64
  payload:bytes
```

## Complete component and manifest SHA-256

The footer's internal complete-file digest follows the normalized self-field
rule in the store contract. The manifest component digest is ordinary SHA-256
over every actual component byte without normalization.

## Fast hash registry

The fast hash is exactly XXH64 from xxHash, seed 0, stored as little-endian u64.
The implementation includes independent reference vectors and an internal-only
test seam that can return a constant value for retained-pattern, query-pool,
composite-member-set, record-index, and LRU-key buckets. Exact bytes are compared
inside every bucket, so injected collisions cannot merge identities.
