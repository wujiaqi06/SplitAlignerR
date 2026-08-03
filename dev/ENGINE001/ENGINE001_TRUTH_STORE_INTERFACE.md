# ENGINE001 truth-store interface freeze

## Backend-neutral contract

The mapper depends on one logical interface and never branches on storage
backend for scientific behavior:

```text
open(species_authority, pattern_registry, control) -> store
insert(pattern_id, exact_pattern_bits, packed_plan)
lookup(pattern_id, exact_pattern_bits) -> scoped read-only TruthPlanView
release(view)
validate(level)
finalize()
close()
stats()
```

`insert()` is allowed only during construction. `lookup()` is allowed during
construction only for records already committed to the temporary store and
after their record checksum passes. Finalization is one-way and makes the store
immutable. `close()` is idempotent.

## Scientific invariance

All backends return the same canonical plan bytes for one finalized pattern ID.
The mapper receives only a validated view and cannot observe:

- whether bytes came from memory, disk, cache, or recomputation;
- cache encounter order;
- eviction history;
- physical record order;
- fixed/free dataset role.

Every lookup verifies the pattern ID against the exact retained-taxa bitset or
its SHA-256 plus exact bytes. A hash match alone is never identity.

## Backends

### `PackedMemoryStore`

One contiguous immutable byte arena plus a fixed index. Selected only when:

```text
exact complete packed bytes <= 0.80 * configured truth-cache budget
```

The arena owns bytes; views are offsets into the arena and remain valid until
store close. No per-plan R objects are retained.

### `PackedDiskStore`

One validated sequential record file and sorted fixed-width index. Records are
written once in finalized pattern order. Reads use checked u64 offsets and
lengths. The open handle owns no scientific identity; the completed file and
manifest do.

### `PackedDiskLruStore`

The disk store plus a contiguous packed-body cache with a hard charged-byte
budget. Each entry charge is:

```text
record bytes
+ cache-key bytes
+ fixed entry metadata
+ allocator slab reservation attributable to the cache
```

The implementation preallocates slabs within the budget; it does not infer a
hard bound from `object.size()`. An entry larger than the entire cache budget is
served through a single bounded streaming/read buffer or rejected before
mapping if it exceeds the separately configured single-plan limit.

Lookups pin entries for the lifetime of a `TruthPlanView`. Pinned entries are
not evictable. With one single-thread gene buffer, at most one plan is pinned.
Future workers receive a declared pin allowance included in the cache budget.

LRU recency uses request sequence only. Tie-breaking uses finalized pattern ID.
Eviction never changes record bytes or output order.

### `RecomputeStore`

Fallback when validated local storage is unavailable. It retains only exact
pattern bits and optionally a byte-budgeted plan cache. Construction uses the
same frozen truth kernel and encoded-record validator as other backends.
Recomputation is a performance decision, not a different truth path.

## Adaptive selection

Inputs recorded in the run manifest:

```text
pattern count and observed uniqueness
measured/sample plan bytes
exact projected complete packed bytes
truth construction seconds per plan
validated sequential read/write throughput
configured truth-cache bytes
available writable storage and free bytes
single-plan maximum bytes
```

Decision order:

1. choose `PackedMemoryStore` when complete exact packed bytes are at most 80%
   of the truth-cache budget;
2. otherwise choose `PackedDiskLruStore` when a same-filesystem validated
   temporary directory has at least 110% of projected store bytes free;
3. otherwise choose `RecomputeStore` with a bounded cache when projected
   reconstruction time is accepted by control;
4. otherwise fail preflight with a storage/memory planning error.

The selector emits its inputs, selected backend, rejected alternatives, and
rationale. No silent fallback is allowed after a disk-full or corruption error.

## Index and lookup validation

The disk index is sorted by pattern ID and contains exact fingerprint, offset,
length, and record hash. Opening validates the global header/footer, exact file
length, index order, range non-overlap, index checksum, ordered-record checksum,
and manifest SHA-256.

Lookup then validates:

```text
requested pattern ID
requested exact retained bitset
index fingerprint
record header fingerprint
species-authority fingerprint
record length
record/header xxHash64
structural schema invariants
```

Full validation scans every record once. Lazy validation is permitted only
after the global store has passed publication validation; it still validates
each record before first use.

## Ownership and lifecycle

The active C++ run context owns store handles, packed arenas, cache slabs, pins,
and temporary paths. R owns the control object and durable manifest descriptor.
`close()` releases handles and memory but never deletes a validated published
store. Finalizers call `close()` defensively and are idempotent.

Temporary stores use an unpredictable run ID and remain `INCOMPLETE`. Successful
publication validates, closes, hashes, atomically renames components, and
publishes the `VALIDATED` manifest last.

On interrupt, exception, disk full, or process termination, no valid manifest is
published. A later run may remove only recognized incomplete files for the same
run ID after explicit cleanup policy checks. It cannot reuse a partial record.

## Optional reuse

Reuse is off by default during shadow/RECERT execution. When enabled later, it
requires exact equality of:

```text
truth-store schema major/minor compatibility
kernel semantic version
species-authority SHA-256
pattern-registry SHA-256
complete pattern count and ordered IDs
validated manifest and component SHA-256
```

Matrix output, input gene topology, and fixed/free provenance do not enter a
truth-store's scientific identity, but the run manifest records their separate
fingerprints.

## Error behavior

The interface emits typed internal categories for schema mismatch, authority
mismatch, corruption, incomplete store, disk full, allocation failure,
interruption, and invariant violation. Raw C++ exceptions never cross to an
ordinary user. The R orchestration layer attaches stage and safe path context
and preserves the original diagnostic message.
