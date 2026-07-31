# ARCH000A truth-store options

## Strategy A: recompute on demand

Persistent full-plan memory is zero. The exact bitset registry reconstructs a
truth plan whenever a gene requests it. The bound is compact registry plus one
ephemeral verbose plan.

Advantages:

- simplest hard working-memory bound;
- no file lifecycle or corruption surface;
- exact semantics reuse the same constructor.

Costs:

- repeated patterns pay construction repeatedly;
- fixed/free analyses cannot reuse construction work;
- high uniqueness makes every request a relatively expensive build.

It is the safe no-storage fallback, not the default recommendation.

## Strategy B: bounded verbose-plan LRU

The prototype accounts each entry as the measured R object plus pattern-ID
wrapper and a conservative 2,048-byte allocator reserve. It evicts least
recently used exact IDs before insertion and asserts:

    accounted cache bytes <= configured cache budget

An entry larger than the budget is returned uncached. The conservative working
bound is cache budget plus the largest in-flight entry.

Advantages:

- hits avoid truth reconstruction;
- no separate packed decoding step;
- scientifically independent of eviction.

Costs:

- verbose entries waste memory;
- misses still rebuild truth;
- allocator and object-graph behavior are R-specific;
- poor locality at 86.8% unique patterns sharply limits hits.

It is useful as a comparison and transitional prototype, but not preferred for
the R/C++ production boundary.

## Strategy C: packed disk store

Every canonical pattern is constructed once, encoded deterministically, and
written sequentially. The in-memory index retains registry identity and record
checksums; fixed-width offsets are calculated rather than stored as R objects.

Advantages:

- exact round-trip reconstruction;
- fixed/free and repeated analyses reuse one construction;
- working memory is independent of global plan count;
- completion/footer and per-record checksums reject partial/corrupt stores;
- packed size is directly predictable.

Costs:

- temporary disk grows with unique patterns;
- cold access adds read and decode cost;
- production lifecycle needs atomic publication, cleanup and portability work.

Disk alone is bounded but can perform unnecessary repeated reads.

## Strategy D: packed disk plus packed-byte LRU

The hybrid LRU caches verified packed bodies, not verbose R plans. Exact pattern
IDs address entries; decoded plans remain ephemeral. Entry accounting includes
the raw record, key/wrapper and a conservative 256-byte reserve.

Advantages:

- hard configurable cache bound;
- compact hot set;
- disk avoids repeated S9 construction;
- cache locality improves reads without affecting semantics;
- one store can serve fixed and free inputs sharing exact patterns;
- clean C++ path to packed bitsets and typed spans.

Costs:

- more components than recompute;
- low locality may produce few hits;
- requires validated local scratch for best performance.

## Adaptive policy

The selector may retain all packed records only if packed full-cache bytes are
at most 80% of the allocated truth-store budget. The verbose R-plan estimate
is reported separately. Otherwise it prefers packed disk plus LRU
when validated local storage is available; recompute plus LRU is the explicit
fallback when storage is unavailable or untrusted.

The selector records locus count, pattern uniqueness, estimated cache/store
bytes, reconstruction time, disk throughput, expected hit rate, budget and
rationale. It never silently infers a policy from topology or fixed/free role.

## Recommendation criterion

The recommendation is not fastest-case-wins. A candidate must first preserve
all frozen science, exact identity, determinism, terminal safety and a
defensible hard bound. Wall time, storage sensitivity, locality, complexity and
failure recovery are comparative properties considered only after those gates.
