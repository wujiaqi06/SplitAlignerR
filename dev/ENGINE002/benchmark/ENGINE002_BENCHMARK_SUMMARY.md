# ENGINE002 benchmark summary

Classification: storage and codec primitive measurements only. The 100,000
records are deterministic storage-only patterns under a synthetic 40-taxon
authority; they are not scientific truth-construction evidence.

All accepted cases have three independent repetitions. Median [minimum,
maximum] wall seconds:

| operation | count | wall seconds | throughput |
|---|---:|---:|---:|
| encode | 100,000 | 0.430 [0.427, 0.470] | 232,558 records/s |
| full decode | 10,000 | 0.050 [0.049, 0.062] | 200,000 records/s |
| validated direct view | 10,000 | 0.044 [0.040, 0.101] | 227,273 views/s |
| direct primitive query | 100,000 | 0.015 [0.015, 0.015] | 6,666,667 queries/s |
| memory build | 10,000 | 0.024 [0.023, 0.025] | 416,667 records/s |
| memory finalize | 10,000 | 0.004 [0.004, 0.005] | 2,500,000 records/s |
| disk build | 100,000 | 0.250 [0.247, 0.251] | 400,000 records/s |
| disk validate and publish | 100,000 | 4.513 [4.498, 4.513] | 22,158 records/s |
| fresh-process-style reopen/full validation | 100,000 | 2.426 [2.419, 2.535] | 41,220 records/s |
| original-order lookup | 100,000 | 3.032 [2.964, 3.053] | 32,982 lookups/s |
| reversed-order lookup | 100,000 | 1.038 [1.022, 1.052] | 96,339 lookups/s |
| grouped reuse | 20,000 | 0.143 [0.138, 0.151] | 139,860 lookups/s |
| maximally interleaved reuse | 20,000 | 0.149 [0.136, 0.158] | 134,228 lookups/s |
| fixed-seed random lookup | 100,000 | 1.827 [1.814, 1.847] | 54,735 lookups/s |

The one-operation cold/warm probes completed below the `proc.time()`
resolution and are recorded as zero wall time with throughput `NA`, rather
than an infinite speed claim.

Every 100,000-record repetition produced 24,200,384 measured final bytes, a
48,400,768-byte derived temporary upper bound (final plus equal-size
unpublished temporary component), 25,600,000 charged index bytes, 33,554,304 charged cache
high-water, 151,464 misses, 188,538 hits, and 64,083 evictions.
The counters conserve exactly: hits + misses = 340,002 requested snapshots,
insertions = misses, and insertions - evictions = 87,381 resident entries;
87,381 multiplied by the 384-byte deterministic charge equals the reported
33,554,304-byte high-water.

External peak RSS was 417,759,232 bytes. This includes the R harness, its list
of 100,000 input raw vectors, builder storage, store validation, and lookup
workloads. It is not the C++ cache charge.

ENGINE001 comparisons must retain this label:

```text
PURE-R PROTOTYPE BASELINE — NOT A PRODUCTION C++ SPEED CLAIM
```
