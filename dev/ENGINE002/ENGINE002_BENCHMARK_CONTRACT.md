# ENGINE002 benchmark and acceptance contract

## Workloads

1. All 1,974 exact ARCH000A authority plans.
2. 10,000 deterministic exact plans encoded with the production hybrid schema.
3. 100,000 canonical production store records, labelled synthetic storage-only
   and non-scientific.
4. Validated sparse/large-offset fixtures whose final record, index, and footer
   cross 2 GiB and 4 GiB.

ARCH000A fixed-width experiments do not substitute for these measurements.
ENGINE001 timings are labelled exactly:

```text
PURE-R PROTOTYPE BASELINE — NOT A PRODUCTION C++ SPEED CLAIM
```

## Operations

Measure encode, full decode, validated view creation, direct primitive query,
fiber/composite enumeration, memory build/finalize/validation/reopen, disk
write/finalize/close/cross-session reopen/full validation, sequential/random
lookup, LRU hit/miss/insert/pin/eviction/oversized bypass, record checksum,
whole-store validation, complete-file SHA-256, and atomic publication.

## Access and budget cases

Use original, reversed, grouped, maximally interleaved, and fixed-seed random
orders. Report first process access as `PROCESS_COLD` or `FRESH_FILE_COPY` unless
hardware-cold cache is defensibly controlled; report the second pass as `WARM`.

Cache cases are 0, below smallest record, exactly one record, 32 MiB, 64 MiB,
and one workload-appropriate larger budget. Include oversized scratch success
and above-scratch failure.

## Repetitions and metrics

Every accepted case has at least three independent repetitions. Report median,
minimum-maximum, wall time, CPU user/system where defensible, plans/s, queries/s,
MB/s, external process peak RSS, charged cache and scratch high-water, temporary
and final disk high-water, and deterministic hit/miss/eviction/bypass counters.

Correctness golden bytes and all 1,974 authority plans are mandatory on Linux,
macOS, and Windows. Hosted-runner performance is not compared as controlled
hardware. A sanitizer or equivalent memory-safety run is included where
feasible.

