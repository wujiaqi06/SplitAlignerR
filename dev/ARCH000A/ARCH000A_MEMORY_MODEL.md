# ARCH000A memory model

## Separate quantities

ARCH000A reports four independent components:

1. compact retained-taxa pattern registry;
2. truth-plan store/cache working memory;
3. exact global B-star registry;
4. final matrix or checksum-sink memory.

Peak process RSS is reported separately and is never inferred by adding
object.size values.

## Exact registry

For T species taxa, one exact bitset uses:

    ceil(T / 8) bytes

At T = 302 this is 38 payload bytes per unique pattern. R list/string overhead
is measured in the prototype. A production C++ registry would instead use
contiguous fixed-width bitsets, integer pattern IDs, and an exact equality
check after any hash lookup.

## Verbose-plan retain-all model

The ARCH000 authority measured 191,880,880 bytes across 1,974 verbose truth
plans. Retain-all therefore grows approximately with unique-pattern count:

    verbose_store_bytes = sum(measured plan object sizes)

This is a measured R representation cost, not a language-independent lower
bound.

## Recompute bound

Recompute retains no full-plan cache. Its conservative working bound is:

    compact registry
    + exact B-star registry
    + one largest decoded/reconstructed plan
    + one empirical split index
    + sink or matrix payload

Locus count does not enter the truth-plan working-memory term, although it does
enter gene mapping and output size.

## Verbose LRU bound

Each cached entry is charged:

    object.size(list(pattern_id, plan))
    + 2,048 bytes conservative allocator reserve

Insertion evicts until charged bytes plus the new entry do not exceed the
configured cache budget. The budget assertion is executed after every
insertion. One newly built oversize plan may exist outside the cache, so the
reported conservative bound is:

    cache budget + largest measured in-flight plan

Actual R cache object size is measured at observation points and reported
beside the conservative accounting.

## Packed store and packed LRU

For T taxa and B primitives:

    key bytes       = ceil(T / 8)
    state bytes     = ceil(B / 4)
    query bytes     = B * ceil(T / 8)
    packed body     = key + state + query
    packed record   = body + 8 checksum bytes

At T = 302 and B = 601:

    key bytes       = 38
    state bytes     = 151
    query bytes     = 22,838
    packed body     = 23,027
    packed record   = 23,035

File size is exactly header plus record count times fixed record bytes plus
footer. This provides a deterministic target-scale storage bound.

Packed-LRU entries are charged as the raw body wrapper plus a 256-byte
allocator reserve. The conservative working bound is:

    packed cache budget + largest decoded plan

The decoded plan is ephemeral and not counted as a cache resident.

## Matrix and sink

Store-isolation mode retains only per-gene checksums, gene IDs, counters and
registry metadata. End-to-end compact mode additionally retains:

    raw state matrix:       loci * B bytes
    double numeric matrix:  loci * (B + B-star) * 8 bytes
    fused lookup matrix:    loci * B * 8 bytes

The fused matrix is a validation convenience in the R prototype, not a required
production authority component. It may be reconstructed in chunks.

## B-star pending buffer

The B-star pending-buffer bound is distinct from both the global B-star
registry and truth-plan cache. The large-tree stress charges the exact encoded
member-set record bytes and flushes after a configurable threshold. Peak
pending bytes may exceed the threshold by at most the last inserted record;
flush count, encoded bytes, and global-registry growth are reported separately.

## Operational budgets

Evidence is evaluated against 2 GiB and 8 GiB whole-process operational
budgets. Truth-store cache cases additionally use 32, 64, 128 and 256 MiB hard
cache budgets. The actual machine has substantially more memory, but a strategy
passes only when its bounded truth-store term remains valid under the smaller
configured target.

## Peak-RSS method

The sandbox denied kernel high-water collection through BSD time. Each final
fresh R process is therefore monitored by a separate read-only ps process at
20 ms intervals. The evidence reports the largest sampled OS RSS, sample count,
and interval as sampled peak RSS. It is not labelled as a kernel high-water
mark. This method is independent of object.size and observes package loading,
construction, storage, parsing, matrices and cleanup while the target PID is
alive.

## Projections

Any 500,000-locus row is derived from measured 100,000-locus throughput and
fixed record/mapping slopes. Projected peak RSS is not reported. A projection
cannot satisfy a measured-memory gate.
