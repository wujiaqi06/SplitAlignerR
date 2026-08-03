# ENGINE002 typed error contract

Low-level code throws or returns only stable internal categories plus bounded
diagnostics. Internal R wrappers translate them to conditions while preserving
the original message. No category is selected by regular-expression matching of
an exception message.

| category | contract meaning |
|---|---|
| `ENGINE_INVALID_ARGUMENT` | malformed internal input or descriptor |
| `ENGINE_SCHEMA_MISMATCH` | unsupported type/ABI/schema/flags/encoding |
| `ENGINE_AUTHORITY_MISMATCH` | authority count, axis, or digest mismatch |
| `ENGINE_PATTERN_MISMATCH` | retained bits/ID/registry mismatch |
| `ENGINE_STORE_CORRUPT` | structural/checksum/hash/canonical corruption |
| `ENGINE_INCOMPLETE_RUN` | missing or non-VALIDATED manifest/component |
| `ENGINE_DUPLICATE_RECORD` | duplicate pattern ID insertion |
| `ENGINE_DUPLICATE_PATTERN` | exact retained pattern under another ID |
| `ENGINE_INVALID_STATE` | operation prohibited in current lifecycle state |
| `ENGINE_STORE_BUSY` | close/eviction conflicts with an active pin |
| `ENGINE_CONTEXT_CLOSED` | closed or stale-generation context |
| `ENGINE_MEMORY_BUDGET` | cache/scratch/index/combined budget violation |
| `ENGINE_ALLOCATION_FAILURE` | checked allocation or `std::bad_alloc` failure |
| `ENGINE_IO_FAILURE` | open/read/write/seek/flush/sync/close failure |
| `ENGINE_DISK_FULL` | confirmed or injected no-space/short-write condition |
| `ENGINE_UNSUPPORTED_ATOMICITY` | safe same-filesystem no-replace unavailable |
| `ENGINE_INTERRUPTED` | R/user interruption at a safe cleanup point |
| `ENGINE_SCIENTIFIC_INVARIANT` | invalid truth state/fiber/terminal/query rule |
| `ENGINE_INTERNAL_FAILURE` | contained unknown exception |

Specific mappings required at every R/C++ entry point:

```text
std::bad_alloc                 -> ENGINE_ALLOCATION_FAILURE
closed/stale context           -> ENGINE_CONTEXT_CLOSED
corrupt bytes/store            -> ENGINE_STORE_CORRUPT
unsupported schema             -> ENGINE_SCHEMA_MISMATCH
wrong authority                -> ENGINE_AUTHORITY_MISMATCH
cache/scratch/index overflow   -> ENGINE_MEMORY_BUDGET
disk full or short write       -> ENGINE_DISK_FULL or ENGINE_IO_FAILURE
truth invariant failure        -> ENGINE_SCIENTIFIC_INVARIANT
unknown C++ exception          -> ENGINE_INTERNAL_FAILURE
```

R interrupts remain interrupts after RAII cleanup and never become unknown C++
errors. Diagnostics may include stage, safe basename, expected/observed widths,
and IDs, but never unbounded input or raw memory. Explicit close and finalizers
share an idempotent no-throw cleanup path.

