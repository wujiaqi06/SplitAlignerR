# ENGINE002 store and view lifecycle contract

## Store states

```text
BUILDING -> FINALIZED -> CLOSED
BUILDING -> CLOSED
OPEN_VALIDATED -> CLOSED
```

`OPEN_VALIDATED` is produced only by fully validating a published disk store and
its final manifest. `FINALIZED` is an immutable same-process store. State
transitions are monotone.

## BUILDING

Insertion is allowed and lookup is prohibited. No view can be returned. Input
order may be arbitrary. Each insertion copies canonical bytes into C++-owned
storage and validates the record and authority binding.

All duplicate cases are typed failures, including exact repeated ID/bytes:

```text
same ID, same bytes                  -> ENGINE_DUPLICATE_RECORD
same ID, different bytes             -> ENGINE_DUPLICATE_RECORD
different ID, same retained pattern  -> ENGINE_DUPLICATE_PATTERN
insertion after finalization/close    -> ENGINE_INVALID_STATE
```

## finalize()

Finalization requires complete IDs `0..pattern_count-1`, canonical retained-bit
order, and exact identities. It canonicalizes record/index order, freezes bytes,
validates the complete store, and atomically changes state to `FINALIZED`.

A second `finalize()` on an unchanged finalized store is idempotent success. It
does not mutate bytes, digests, generation, or counters. A failed finalize leaves
the object in `BUILDING` with no views and no published output.

## TruthPlanView

A view is C++ internal, noncopyable, scoped RAII, generation checked, authority
bound, and backed by an immutable arena owner, cache pin, or one scratch owner.
It never crosses into R. Every access validates the open state and generation
before byte dereference.

Explicit close while a view/pin is active returns `ENGINE_STORE_BUSY` and makes
no state or resource change. The no-throw finalizer may mark the shared control
block closing and defers destructive cleanup until the last guard releases.
Pinned cache entries cannot be evicted.

## close()

Explicit close and the finalizer share one idempotent no-throw cleanup path.
Successful close invalidates the generation before releasing handles or owned
bytes. Repeated close succeeds without mutation. After successful close:

```text
new lookup       -> ENGINE_CONTEXT_CLOSED
read-after-close -> ENGINE_CONTEXT_CLOSED
insert/finalize  -> ENGINE_CONTEXT_CLOSED
```

No view can dereference freed storage.

## Reopen meanings

`PackedMemoryStore` has no cross-session durability. A finalized memory store
may be reopened only as another same-process immutable handle sharing the exact
arena/control block.

`PackedDiskStore` reopens across explicit close, original-pointer garbage
collection, and a new R session using ordinary final filenames and manifest.
It becomes `OPEN_VALIDATED` only after complete component, manifest, authority,
registry, semantics, structure, and checksum validation.

## R external pointers

Internal XPtrs contain an exact type tag, ABI major 1, generation, open/closed
state, and shared control block. Every entry point checks all fields. Wrong type
or ABI is `ENGINE_SCHEMA_MISMATCH`; stale generation or closed state is
`ENGINE_CONTEXT_CLOSED`.

R never owns a native span and C++ never retains an unprotected pointer into a
movable R vector. Active calls hold strong local guards. No durable output
depends on an XPtr remaining alive.

