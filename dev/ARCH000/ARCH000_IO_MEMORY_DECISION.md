# ARCH000 I/O and memory decision

## Decision

The two-pass shared-truth architecture is operationally feasible. On the full
2,275-locus authority, the preferred taxa-only first pass plus full recovery
completed in 333.826 seconds with 500,269,056 bytes peak RSS. Its persistent
compact object was 258,732,048 bytes, versus the earlier post-release enriched
prototype's 15,506,882,152-byte `object.size()`.

The architecture is not automatically fastest at every scale. On a replicated
10-tip/10,000-locus workload, the existing production in-memory mapper was
faster (6.066 seconds) than the transparent R streaming prototype (9.256
seconds), a bounded-memory slowdown of 1.526. The streaming result was much
smaller, however: 4,961,536 versus 30,368,680 bytes. An adaptive planner should
therefore retain a small-workload in-memory path and choose bounded replay when
the projected working set exceeds budget.

## Measurement environment

- Apple M3 Pro (`Mac15,6`), 38,654,705,664 physical bytes;
- macOS 14.4, arm64;
- R 4.4.2;
- internal fixed solid-state Apple Fabric storage, APFS;
- 32 MiB configured B* pending-buffer threshold;
- peak RSS from a fresh-process BSD `/usr/bin/time -l` high-water mark;
- explicit comparison memory budget: 1 GiB.

Only the available local APFS SSD was measured. No HDD, SATA, or network
filesystem result is fabricated.

## Principal measurements

| Workload / mode | Pass 1 s | Pass 2 s | Total s | First-pass fraction | Peak RSS | Compact/result size |
|---|---:|---:|---:|---:|---:|---:|
| 2,275 authority, taxa scan + full recovery | 174.415 | 159.411 | 333.826 | 0.522 | 500,269,056 B | 258,732,048 B |
| 2,275 authority, full parse twice | 515.714 | 160.720 | 676.434 | 0.762 | 496,844,800 B | 258,732,048 B |
| 2,275 authority, all text resident + full parse | 518.592 | 158.793 | 677.524 | 0.765 | 560,201,728 B | 258,732,048 B |
| 10,000 Catnip-derived, taxa + full | 2.364 | 6.892 | 9.256 | 0.255 | 304,807,936 B | 4,961,536 B |
| 10,000 Catnip-derived, current production | n/a | 5.622 | 6.066 | n/a | 185,368,576 B | 30,368,680 B |
| 100,000 Catnip-derived, taxa + full | 21.893 | 62.896 | 84.789 | 0.258 | 350,732,288 B | 48,251,536 B |
| 500,000 Catnip-derived | 109.465 | 314.480 | 423.945 | 0.258 | **not measured** | 241,257,680 B projected |

The 500,000 row is a projection from measured 100,000-locus throughput and
observed registry saturation. It is not labelled or used as a measured peak-RSS
result.

All measured modes fit the explicit 1 GiB budget. The complete fixed+free
2,275-gene conformance run retained both compact results and paired comparison
work in one process and peaked at 1,013,055,488 bytes; this combined audit also
fit 1 GiB but is not substituted for single-dataset benchmark values. A
strengthened final validation also replayed production mapping in bounded
chunks while retaining both compact results; that validation process peaked at
1,399,799,808 bytes. Its extra comparison overhead is recorded as conformance
evidence, not as the architecture's execution-mode peak.

## Authority growth and component attribution

The 2,275 authority had 283–302 retained taxa per gene, 1,974 unique patterns,
and 485 unique B*. The R truth-plan cache used 191,880,880 bytes and was the
largest top-level component (192,039,008 bytes including list structure). The
B* pending buffer peaked at only 124,040 bytes and produced one final flush;
disk spill was not triggered.

This is a scientifically useful result: almost every authority gene has a
distinct missing-taxa pattern, so caching cannot assume high pattern reuse.
Even in this adversarial pattern-count regime, memory scales with 1,974 plans
and compact matrices rather than 1,367,275 expanded long-ledger rows. The next
implementation should pack those plans in C++ bitsets/typed arrays.

The Catnip-derived replicated workloads saturated at 15 patterns and 13 B*.
At 100,000 loci the numeric matrix became the largest component, demonstrating
the desired transition from registry-dominated to irreducible output-matrix
growth.

## Plain versus gzip and phase isolation

The 10,000-locus temporary workload occupied 1,975,000 bytes plain and 47,079
bytes gzip because it intentionally repeats a small tree corpus. The repetition
makes its compression ratio nonrepresentative of natural authority files, but
the decompression timing remains measured:

| Phase | Plain s | gzip s | gzip increment |
|---|---:|---:|---:|
| sequential record read only | 0.621 | 0.663 | 0.042 |
| taxa scan only | 2.344 | 2.381 | 0.037 |
| complete parse only | 6.799 | 6.904 | 0.105 |
| full taxa-scan + recovery | 9.256 | 9.536 | 0.280 |

Gzip did not improve wall time on the local SSD. Its decompression cost was
small but positive. `storage_MB_per_second` in the CSV uses stored bytes; it is
therefore not compared directly between compressed and uncompressed rows.

## Two-pass tradeoff

For the authority workload, lightweight discovery reduced first-pass time by
341.299 seconds and cut total time to 0.493 of the all-text-resident/full-parse
baseline. Holding all Newick text increased peak RSS by about 60 MB and offered
no speed benefit. The extra sequential scan is therefore favorable on the
measured local SSD.

For small trees, the existing one-call production path remains faster. Its
expanded representation is acceptable only while the projected result fits the
budget. The prior API000A measurements show why it cannot be the default for
the 302-taxon full authority: a single fixed result was about 7.46 GB and the
combined enriched representation about 15.51 GB, with serialization incomplete
inside the audit window.

## Slow or remote storage

No second storage class was available. A future planner should measure a small
sequential block before execution. If observed throughput is below a configured
threshold or the source is remote, it should recommend copying the immutable
file to local scratch, verify its SHA-256, execute both passes against that
copy, and remove scratch only after evidence is committed. The cost model is:

```text
stage_once + two local sequential reads
versus
two remote reads
```

The choice must report measured staging/read throughput and must not call a
projection a storage benchmark.

## Returned-object interpretation

`object.size()` counts referenced R components recursively and is not live heap
or peak RSS. Serialization size is neither live heap nor a cross-platform byte
contract. ARCH000 therefore reports OS peak RSS separately and compares objects
through schema-aware semantics. The critical persistent cost is the returned
compact authority; expanded long tables remain explicit materializations or
chunked exports.
