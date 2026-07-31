# ARCH000A bounded truth-plan architecture

## Scope

ARCH000A is a non-production supplement to ARCH000. It starts from commit
50054bd43abc3fbc840a750f50a3e6ac7f357183, changes only dev/ARCH000A/,
and does not alter package source, tests, public APIs, authorities, tags, or
releases.

The question is deliberately narrower than general streaming: how to prevent
verbose pattern-specific truth plans from growing without bound when retained-
taxa pattern uniqueness approaches one plan per locus.

## Frozen semantic boundary

A truth plan is a function of only the validated species-tree authority and an
exact retained-taxa bitset. It contains primitive structural/fused/eligible
states, original-edge fibers, exact composite primitive-member sets, and
pattern-local projected query splits. Gene-tree topology is absent from
construction. Empirical recovery may only map an eligible query or refine it
to NA_topo.

The global identity of a composite coordinate remains its exact canonical
primitive-member set. Pattern-local projected splits are query objects and
never global coordinate identifiers. Terminal NA_topo remains a hard failure.
Support(b) remains an internal-primitive post-scan statistic.

If an internal primitive is structurally unevaluable in every locus, its
mapped-plus-NA_topo denominator is zero and Support(b) is `NA_real_`. This is a
missing estimand, not numerical zero; any later phylo label adapter must retain
the missing value.

## Two bounded layers

The proposed architecture separates two meanings of cache:

1. A deterministic packed store owns the complete reconstructible truth record
   for every exact pattern. Its size grows on disk, not in working memory.
2. A byte-budgeted LRU owns only hot packed records. Its accounted bytes cannot
   exceed the configured budget. One decoded truth plan is an ephemeral query
   view and is released after the gene row.

This differs from retaining verbose R plans in an LRU. The latter is
implemented as Strategy B for comparison, but its entries are larger and
allocator accounting is less portable.

## Compact exact pattern registry

For 302 taxa, exact membership uses 38 bytes. The experimental registry stores
canonical pattern ID, exact membership bitset, exact bitset-derived key, and
gene-to-pattern mapping.

Final pattern IDs are assigned after bytewise sorting of exact membership keys.
A hash may select a candidate bucket, but equality is always rechecked against
the exact key/bitset. Constant-hash and truncated-hash tests exercise this
boundary. Reversing gene order leaves final IDs and bitsets unchanged.

## Deterministic packed record

The experimental SARATP01 record contains:

    38-byte retained-taxa bitset
    2-bit primitive truth-state vector
    one 302-taxon query bitset per primitive coordinate
    8-byte ASCII Adler-32 record checksum

For 302 taxa and 601 primitives, the fixed body is 23,027 bytes. This layout is
intentionally simple and inspectable; it is an engineering prototype, not a
promised permanent file format.

The file header locks version, taxa, primitive, pattern and record dimensions.
The SARADONE footer records the expected record count and a checksum over the
ordered record-checksum sequence. Opening a store requires exact expected file
length, valid footer, and matching registry metadata. Scientific opening also
verifies every record body.

## Pass 1

Pass 1 scans exact taxa patterns and freezes canonical IDs. Each unique pattern
is then constructed once from the species authority. Its packed body is written
sequentially, and its exact composite member sets enter the independently
bounded ARCH000 B-star accumulator.

Only the compact pattern registry, gene mapping, exact B-star registry,
packed-file metadata, and checksum sequence remain in memory. The verbose plan
used to encode one record is released before the next pattern.

## Pass 2

For each gene:

1. read and fully parse one Newick record;
2. build one empirical split index;
3. request its packed truth record through the hard-budget LRU;
4. verify and decode one ephemeral truth plan;
5. execute deterministic split queries;
6. write one compact matrix row or checksum-sink row;
7. update internal mapped/NA_topo counters;
8. release the decoded plan and empirical index.

The packed LRU changes I/O locality only. Cache hit, miss, or eviction cannot
change the decoded record or scientific output.

## Store-isolation and end-to-end modes

Store-isolation mode writes normalized per-gene checksums and counters rather
than full matrices. It measures registry/store/cache scaling without charging
irreducible result payload to the truth store.

End-to-end mode allocates raw categorical, double numeric, and fused-provenance
matrices at authority scales where they fit. Matrix bytes are reported
separately from truth-store, pattern-registry, and B-star bytes.

## Interruption boundary

A partial file has no valid completion footer and cannot be opened. A complete
file with one modified body byte fails its record checksum. Failed tests retain
small textual evidence; disposable partial stores are removed only after the
failure has been detected and recorded. Restart policy is rebuild-to-new-path,
verify, then publish; an incomplete path is never resumed or silently reused.

## B-star pending churn

The bounded B-star accumulator is separately stressed from truth-plan storage.
Its authoritative key is a deterministic exact byte encoding of the sorted
primitive-member IDs. A hash may choose a bucket only; forced-collision tests
recompare exact bytes. Pending encoded bytes, records per flush, local
sort/unique time, global merge time, unique-coordinate growth, and peak pending
bytes are recorded independently of the truth-plan cache.

## Production boundary

ARCH000A does not production-implement the packed layout, C++ kernels, file
lifecycle, planner, or public interface. Production implementation remains
unauthorized pending main-console review of the completed evidence.
