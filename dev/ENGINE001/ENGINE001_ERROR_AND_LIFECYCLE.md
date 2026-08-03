# ENGINE001 error, cancellation and lifecycle freeze

## Internal error categories

Low-level C++ code returns a typed category and diagnostic payload. R converts
it to a package condition with stage, safe context, and original message. Raw
C++ exception text is never the ordinary user contract.

| category | meaning | default user prefix |
|---|---|---|
| `ENGINE_INVALID_SPECIES_TREE` | malformed or unsupported species authority | `[SA_SPECIES_TREE]` |
| `ENGINE_DUPLICATE_TAXON` | duplicate canonical label | `[SA_SPECIES_TREE]` |
| `ENGINE_UNKNOWN_TAXON` | gene label absent from authority | mapper stage prefix |
| `ENGINE_MALFORMED_GENE_TREE` | empirical parse/shape error | alignment stage prefix |
| `ENGINE_INSUFFICIENT_TAXA` | fewer than contract minimum retained taxa | alignment stage prefix |
| `ENGINE_SCHEMA_MISMATCH` | incompatible packed/store/matrix schema | `[SA_RESULT_INVARIANT]` |
| `ENGINE_AUTHORITY_MISMATCH` | species/coordinate fingerprint differs | `[SA_RESULT_INVARIANT]` |
| `ENGINE_STORE_CORRUPT` | checksum or structural validation failed | `[SA_RESULT_INVARIANT]` |
| `ENGINE_INCOMPLETE_RUN` | completion footer/manifest absent | `[SA_RESULT_INVARIANT]` |
| `ENGINE_ALLOCATION_FAILURE` | checked allocation cannot be satisfied | alignment stage prefix |
| `ENGINE_DISK_FULL` | projected or actual storage unavailable | alignment stage prefix |
| `ENGINE_INTERRUPTED` | user/process cancellation at safe point | alignment stage prefix |
| `ENGINE_CONTEXT_CLOSED` | stale/closed external pointer | `[SA_RESULT_INVARIANT]` |
| `ENGINE_TERMINAL_NA_TOPO` | scientific terminal invariant violated | `[SA_RESULT_INVARIANT]` |
| `ENGINE_AUTHORITY_FAILURE` | shadow/RECERT comparison failed | `[SA_RESULT_INVARIANT]` |

The mapper stage prefix is chosen by the explicit orchestration call
(`SA_FIXED_ALIGNMENT` or `SA_FREE_ALIGNMENT` when paired), never by regex over
the low-level message. Original diagnostic text is retained as condition data.

## Run-state machine

```text
CREATED
  -> PREFLIGHTED
  -> PASS1_ACTIVE
  -> REGISTRIES_FINALIZED
  -> PASS2_ACTIVE
  -> COMPONENTS_FINALIZED
  -> VALIDATING
  -> VALIDATED
  -> PUBLISHED

any pre-publication state
  -> FAILED | INTERRUPTED
  -> CLOSED
```

Transitions are monotonic. `PUBLISHED` is possible only from `VALIDATED`.
`close()` is valid from every state and is idempotent. A failed context cannot
resume execution in schema v1.

## Preflight

Before truth construction, preflight validates:

- species and input containers;
- path non-aliasing and destination writability;
- input fingerprints or stream limitations;
- dimensions and every checked byte calculation;
- truth/matrix memory budgets;
- at least 110% of projected temporary disk bytes;
- schema/kernel compatibility;
- run-ID uniqueness and same-filesystem atomic publication;
- absence of collision with a prior completed run.

Failure leaves no output other than an optional human-readable preflight log.

## User interrupt and R error

At a safe check point, the kernel marks active components incomplete, flushes
only diagnostic state needed for truthful cleanup, releases plan pins and file
handles, and returns `ENGINE_INTERRUPTED` or the typed original failure. It does
not write a completion footer or validated manifest.

R uses `on.exit()` to call idempotent close. It may offer cleanup of the current
run's recognizable temporary files, but cannot delete inputs, prior completed
runs, or unrelated paths.

## C++ exception

Public C++ entry points catch standard and unknown exceptions after RAII has
released locks/pins. Known typed errors preserve category. `std::bad_alloc`
becomes `ENGINE_ALLOCATION_FAILURE`. Unknown exceptions become an internal
failure with stage context; no raw exception crosses the public R boundary.

## Disk full

Disk full is not a signal to switch backend mid-run. The current component is
left incomplete, handles are closed, and R reports required/projected/free bytes
when known. A new run may select another backend after fresh preflight.

## Corrupt input tree

The current gene row is never published. The default run fails atomically;
skipping malformed genes is not part of ENGINE001 and would require a future
explicit scientific/API policy. The error records the stable gene ID and input
record number without echoing unbounded Newick text.

## Process termination

Abrupt termination may leave run-ID temporary files. They lack a validated
manifest and cannot be opened as completed output. The next run may inventory
them but does not delete automatically unless they match the package's exact
temporary naming/ownership record and user cleanup policy.

## Incomplete stores

Validation requires exact header, dimensions, component length, tile/record
index, footer, hashes, and validated manifest. Missing footer, truncated file,
wrong species fingerprint, wrong schema, trailing data, or missing component is
rejected.

The isolated manifest prototype covers complete, missing-footer, truncation,
authority-mismatch and schema-mismatch cases.

## Publication protocol

For every component:

1. create an unpredictable run-ID temporary file in the destination directory;
2. write header, payload and index with checked offsets;
3. flush and request `fsync` where supported;
4. write completion footer;
5. close and reopen read-only;
6. validate exact structure and hashes;
7. compute SHA-256;
8. write an `INCOMPLETE` manifest describing all components;
9. atomically rename components to final run-ID names;
10. validate them again by final names;
11. atomically publish the `VALIDATED` manifest last.

If directory durability is supported, the containing directory is synced after
renames. Cross-device rename is rejected.

## Cleanup and resume

Successful temporary stores are removed only after their durable successor and
manifest validate. Failure evidence explicitly requested by a diagnostic run is
preserved under an evidence path; normal cache payloads are not.

Resume support is deferred for schema v1. A partial truth or matrix store is
never resumed or reused. Restart means a new run ID and complete rebuild. This
keeps the initial production state machine auditable.

## Authority failure

During shadow or RECERT execution, any normalized state, numeric, coordinate,
provenance, counter, terminal-invariant, or 407-ledger difference produces
`ENGINE_AUTHORITY_FAILURE`. The new result remains an unpublished diagnostic;
the reference engine and default behavior remain unchanged.
