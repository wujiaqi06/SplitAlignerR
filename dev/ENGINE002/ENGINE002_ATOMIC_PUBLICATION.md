# ENGINE002 atomic no-clobber publication contract

## Final names

`run_store_id` is exactly 32 lowercase hexadecimal characters. Component names
are basename-only ASCII and match `[A-Za-z0-9][A-Za-z0-9._-]{0,126}`. Path
separators, `.`/`..`, control bytes, symlinks, and alternate data-stream syntax
are rejected.

```text
<run_store_id>.truthstore.bin
<run_store_id>.truthstore.manifest
```

Temporary names add an unpredictable 128-bit lowercase-hex nonce and remain in
the destination directory. Publication never follows a symlink.

## Exact manifest v1.0

The manifest is canonical UTF-8/ASCII text with LF endings, no BOM, and exactly
these keys in this order, one `key=value` per line and a final LF:

```text
magic=SplitAlignerR-TruthPlanStore-Manifest
manifest_schema_major=1
manifest_schema_minor=0
completion_state=INCOMPLETE|VALIDATED
run_store_id=<32 lowercase hex>
store_component=<validated basename>
store_bytes=<canonical unsigned decimal u64>
store_sha256=<64 lowercase hex>
store_schema=1.0
plan_schema=1.0
species_authority_sha256=<64 lowercase hex>
pattern_registry_sha256=<64 lowercase hex>
truth_semantics_sha256=<64 lowercase hex>
pattern_count=<canonical unsigned decimal u64>
publication_timestamp_policy=OMITTED_V1
```

Canonical decimal has no sign or leading zero except the single character `0`.
No whitespace, unknown key, duplicate key, alternate order, CRLF, or trailing
byte is accepted. Timestamps are deterministically omitted in schema v1.

The candidate and final manifests are separately created immutable files; an
INCOMPLETE manifest is never mutated into VALIDATED.

## Publication protocol

1. Reject symlink destination components and create exclusive temporary files
   in the final destination directory.
2. Write header, records, and index with checked binary writes.
3. Patch final header fields and header hash.
4. Write the complete footer.
5. Flush and request platform durability after all final bytes exist.
6. Close the writer.
7. Reopen read-only and run full canonical, structural, and checksum validation.
8. Compute ordinary SHA-256 over every actual component byte.
9. Create, flush, close, and validate a separate temporary candidate manifest
   marked `INCOMPLETE`.
10. Create, flush, close, and validate a separate temporary final manifest
    marked `VALIDATED`; do not publish it yet.
11. Publish every component with a same-filesystem atomic no-replace operation.
12. Reopen and revalidate each component under its final name.
13. Publish the final `VALIDATED` manifest last with atomic no-replace.
14. Sync the destination directory where the platform supports it.
15. Remove only recognized temporary files belonging to this run after success.

The final validated manifest is the commit record. A component with a footer but
without that manifest is incomplete.

## No-clobber and portability

Existence prechecks are diagnostic only and never provide the safety guarantee.
POSIX publication uses an atomic same-directory no-replace primitive (for
example `renameat2(RENAME_NOREPLACE)` where available or an exact same-filesystem
link-then-unlink protocol for regular files). Windows uses an atomic move that
does not request replacement. If the platform/filesystem cannot provide safe
no-replace publication, return `ENGINE_UNSUPPORTED_ATOMICITY`.

Pre-existing final files remain byte-identical. Cross-device rename, copy
fallback, in-place final-file patching, in-place manifest mutation, and symlink
redirection are prohibited. Every short write, flush, durability, close, reopen,
validation, rename/link, directory-sync, and cleanup failure is typed.

## Failpoints

An internal test seam can fail after every numbered stage and inject short
writes and disk-full errors. No failpoint may leave an accepted store. Component
without manifest, manifest without component, stale candidate manifest,
contradictory identity, and pre-existing destination are all rejected.

