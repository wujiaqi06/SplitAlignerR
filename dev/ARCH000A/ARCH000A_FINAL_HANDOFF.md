# ARCH000A final handoff

## Classification

```text
ARCH000A_PASS
```

At least one strategy has an asserted hard truth-store bound, every mandatory
scientific and oracle gate completed, full 2,275 fixed/free authority and the
407-key ledger passed, peak RSS was sampled at the OS process boundary, and
100%-unique high-locus storage stress completed. Remaining work is production
engineering. Production implementation remains unauthorized.

## Recommended truth-plan strategy

Use an adaptive exact packed architecture:

1. retain all **packed** records in bounded memory only when the measured or
   exact-formula complete packed cache is no more than 80% of the assigned
   cache budget;
2. otherwise use the deterministic packed disk store plus a hard byte-budgeted
   packed-body LRU;
3. if validated local storage is unavailable, fall back to recompute plus a
   bounded verbose-plan LRU rather than weaken semantics or the memory bound.

For the authority workload, all packed bodies consume 47,012,784 bytes, 70.05%
of the selected 64 MiB budget, so the adaptive decision is retain-all packed
memory after first load. For the directly measured 100,000-pattern stress,
complete packed memory would require about 2.38 GB, so the same 64 MiB policy
selects disk plus bounded LRU.

## Rejected default strategies

- ARCH000 verbose retain-all: scientifically correct but unbounded in unique
  pattern count; 191,880,880 bytes already at 1,974 authority patterns.
- pure recompute: hard-bounded and retained as the no-storage fallback, but it
  rebuilt 2,275 plans and required 204.566 s in the authority store walk.
- verbose R LRU: bounded by conservative accounting, but 32 MiB produced 2,054
  builds and 1,718 evictions; R object/allocator behavior is not the preferred
  production boundary.
- disk-only decoded R plans: bounded but required 171.960 s; only 0.134 s was
  physical record reading while 134.689 s was R decoding.
- packed disk without a hot cache: safe but wastes locality and fixed/free
  reuse. It remains the lower layer, not the complete policy.

## Measured authority facts

```text
loci per side:                    2,275
fixed + free mappings:            4,550
unique retained patterns:         1,974
unique-pattern fraction:          0.867692307692
singleton patterns:               1,895
repeated patterns:                79
maximum pattern frequency:        110
unique B*:                        485
verbose plan bytes, sum:          191,880,880
verbose plan bytes min/median/max: 93,896 / 96,904 / 104,736
packed store bytes:               45,471,146
packed body bytes per pattern:    23,027
packed LRU bytes, all patterns:   47,012,784
verbose/store reduction:          4.220x
```

Pattern, B-star, truth-store, and output-matrix memory are separate columns in
the benchmark files. No component sum is relabelled as peak RSS.

## Memory and peak RSS

All values below are measured fresh-process sampled OS RSS maxima except the
explicit 500,000 projection.

| case | truth-store bytes | sampled peak RSS bytes | temporary disk bytes |
|---|---:|---:|---:|
| verbose retain-all, authority | 191,880,880 | 291,520,512 | 45,471,146 |
| pure recompute, authority | 0 persistent | 281,837,568 | 45,471,146 |
| verbose recompute LRU 32 MiB | 33,554,432 | 275,922,944 | 45,471,146 |
| verbose recompute LRU 256 MiB | 196,871,152 | 323,764,224 | 45,471,146 |
| packed LRU 32 MiB, store walk | 33,532,928 | 326,057,984 | 45,471,146 |
| packed LRU 64 MiB, store walk | 47,012,784 | 331,694,080 | 45,471,146 |
| packed 64 MiB end-to-end compact authority | 47,012,784 | 525,074,432 | 45,471,146 |
| 10,000 exact S9 plan build | 0 persistent | 342,114,304 | 230,350,056 |
| 100,000 packed substrate, 100% unique | 67,089,672 | 672,350,208 | 2,303,500,056 |
| full fixed/free strengthened conformance | 47,012,784 | 1,838,825,472 | 45,471,146 |
| 500,000 packed substrate projection | 67,089,672 | NOT_MEASURED | 11,517,500,056 |

The complete conformance process is 85.63% of a 2 GiB whole-process budget,
but that peak includes both compact scientific results and repeated chunked
production-reference objects. The selected truth-store cache itself is 47.0 MB
on authority and remains below its 64 MiB cap at 100,000 loci. Operational
budgets evaluated are 2 GiB and 8 GiB; cache budgets measured are 32, 64, 128,
and 256 MiB.

## First-pass decomposition

The normal shared authority catalog took 336.782 s including fixed/free scans,
truth construction, packing, validation, and catalog work. The separate
repeated-phase decomposition is diagnostic and is not substituted for normal
wall time:

| phase | seconds |
|---|---:|
| raw sequential read | 0.136 |
| tree-boundary detection | 0.200 |
| tip-label tokenization | 18.301 |
| taxon name to integer ID | 0.030 |
| exact pattern-key construction | 0.084 |
| pattern-registry lookup | 0.013 |
| truth-plan construction | 144.993 |
| B-star emission | 0.001 |
| B-star local deduplication | 0.003 |
| B-star global union | 0.016 |

The authority catalog's 1,974 plan build, pack, and physical-write components
were 143.651 s, 32.031 s, and 0.109 s respectively. It is incorrect to call
the first-pass cost “I/O”; tokenization and truth construction dominate.

## Second-pass decomposition

The directly measured fixed authority end-to-end compact pass:

| phase | seconds |
|---|---:|
| raw read | 0.273 |
| full Newick parse | 2.155 |
| empirical split-index construction | 143.013 |
| packed load plus R decode | 142.286 |
| deterministic split queries | 0.181 |
| matrix/sink write | 0.337 |
| branch-counter update | 0.030 |

Physical authority record read throughput was 52,404,625 bytes / 0.134 s
(391.079 MB/s). Physical store write throughput was 45,471,146 bytes / 0.109 s
(417.166 MB/s). The R unpack/decode cost, not storage, is the measured reason
to recommend direct packed C++ query views.

## Cache behavior and order sensitivity

At 32 MiB in original authority order, verbose disk-decoded LRU recorded
226 hits, 2,049 misses, and 1,695 evictions. Packed LRU recorded 294 hits,
1,981 misses, and 573 evictions. At 64 MiB all 1,974 packed authority patterns
fit: 301 hits, 1,974 first loads, and zero evictions.

The full shared fixed/free run then reused the same cache: fixed recorded 301
hits and 1,974 loads; free recorded 2,275 hits, zero misses, zero reloads, and
zero evictions. Grouped, maximally interleaved, original, reversed, and fixed-
seed random orders changed cache statistics only. The gene-ID-normalized exact
plan checksum was 550dbb4f for every strategy and ordering.

## Stress boundary

Direct exact S9 plan construction completed at 2,275 loci for approximately
10%, 50%, 90%, and 100% unique patterns. The measured 100% row built 2,275
plans in 356.113 s. The largest direct exact-S9 stress built and round-tripped
10,000 unique plans in 1,686.636 s with a 230,350,056-byte store.

The largest measured locus scale is 100,000 at 100% uniqueness. It is explicitly
a packed storage/index/LRU engineering substrate and makes no scientific-truth
claim. It completed in 144.739 s, with zero hits, 100,000 misses, 97,183
evictions, a 67,089,672-byte cache high-water, and a 2,303,500,056-byte store.

The 500,000 row is projected linearly from that measured substrate using the
exact fixed record slope. Peak RSS is not projected and the row is not a
completion claim.

## External-review addendum

Degenerate, endpoint-collapse, terminal-fusion, Support(b), and exact-collision
gates all passed. Zero input and one-tip gene trees are stably rejected by the
current contract; accepted two- and three-tip patterns match production and
packed round trips. A full-clade deletion created three denominator-zero
internal coordinates, all with `NA_real_` support preserved as missing in an
ape node-label slot.

The directly measured 1,000-taxon B-star churn run used 250 unique patterns,
emitted 55,830 exact member records, flushed 11 times, peaked at 65,548 pending
bytes, and produced 2,916 unique B-star coordinates. Local plus global
compaction was 0.042 s of 103.982 s measured stress time. The 100,000-locus
B-star extension is a labelled projection; peak RSS and unique-B-star growth
remain NOT_MEASURED.

## Completed oracle and safety gates

```text
compact exact pattern identity and forced collisions: PASS
degenerate and endpoint/fusion patterns:              PASS
Support(b) denominator-zero rule:                     PASS
Catnip10 272 primitive cells plus composites:         PASS
302-mammal fixed/free 5 x 601:                        PASS
cross-strategy toy and 302 outputs:                    PASS
all 1,974 authority packed round trips:               PASS
full fixed primitive cells:                           1,367,275 / PASS
full free primitive cells:                            1,367,275 / PASS
full primitive/composite numeric comparison:          PASS
paired inputs and residual literal-NA keys:            407 / 407 / PASS
terminal NA_topo:                                     0 / PASS
three repeats and five orderings:                     PASS
incomplete store rejection:                           PASS
single-byte corruption rejection:                    PASS
```

Incomplete mandatory oracle gates: none.

## Determinism and interruption verdicts

Determinism: PASS. Canonical pattern IDs, B-star IDs, and gene-ID-normalized
scientific outputs are invariant to repeats, order, cache budget, and strategy.

Interruption safety: PASS. Exact file size, metadata, record checksums, ordered
footer checksum, and SARADONE record count are required before opening. A
partial file cannot be reused. Restart means rebuild to a new path, verify,
then publish.

## Recommended production sequence

1. Freeze typed bitset, byte order, record, and checksum schemas.
2. Add cross-language retained-set, fiber, projected-split, and record golden
   vectors, including every addendum boundary.
3. Implement one-pattern truth construction and exact packed round trip in C++.
4. Query packed state/split views directly; do not rebuild verbose R plans.
5. Implement exact byte-accounted packed memory and disk-backed LRU layers.
6. Implement atomic store publication, footer verification, cleanup, and
   interruption recovery.
7. Connect bounded one-gene empirical indexing, deterministic queries, compact
   row fill, and Support(b) counters.
8. Keep planning, provenance, temporary-path policy, result classes, and paired
   semantics in R.
9. Re-run current authorities and multi-platform RECERT before exposure.

## Authorization boundary

ARCH000A is architecture evidence only. It does not authorize changes under
`R/`, `src/`, `tests/`, metadata, public APIs, authorities, tags, releases, or
the certified v0.1.0 implementation. Production implementation remains
unauthorized pending an explicit later task.
