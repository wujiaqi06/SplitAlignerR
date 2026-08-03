# ENGINE002-FIX001 streaming builder

## Required inputs

Construction requires one exact SpeciesAuthority, one finalized and sorted
PatternRegistry, an existing non-symlink directory, a 32-lowercase-hex run
identifier, and explicit cache/scratch/index/metadata/combined budgets. The
registry binds the expected count, canonical IDs, exact retained bytes, species
authority fingerprint, registry fingerprint, and truth-semantics fingerprint.

## State machine

BUILDING starts by exclusively creating a recognized temporary component and
writing a 256-byte placeholder header. For expected ID i, insert(record):

1. checks cancellation and lifecycle;
2. decodes and validates the complete record against the authority;
3. requires record.pattern_id == i;
4. requires exact retained bytes and retained SHA-256 equal registry entry i;
5. writes record bytes immediately;
6. updates streaming records SHA-256 and canonical payload SHA-256;
7. appends exactly one 64-byte index entry;
8. advances i and releases the caller-owned record.

The contract returns stable typed errors for out-of-order/skipped IDs,
duplicates, too many records, premature finalize, insertion after finalize,
and insertion after close.

## Finalization and publication

After exactly N inserts, finalization:

1. appends the canonical N * 64 byte index;
2. patches the header and writes the footer;
3. flushes, computes the normalized complete-file SHA-256, patches it, flushes,
   and closes;
4. completely validates the temporary component;
5. writes and re-parses an INCOMPLETE candidate manifest;
6. writes and re-parses a VALIDATED temporary manifest;
7. atomically publishes the component without replacement;
8. completely validates the published component against the final manifest;
9. atomically publishes VALIDATED manifest last and syncs the directory.

The accepted store reopens from component/index bytes alone. It owns no
reference to builder record memory.

## Failure invariant

Every write/cancellation/publication exception transitions the builder to
closed, closes resources, removes recognized temporary files, and prevents a
VALIDATED manifest. If a current-run component or manifest was already
published before a later injected failure, that current-run output is removed.
No replacement path exists, so a prior completed run cannot be overwritten.
