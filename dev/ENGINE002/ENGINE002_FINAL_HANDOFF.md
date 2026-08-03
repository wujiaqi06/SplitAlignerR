# ENGINE002 final handoff

## Identity and scope

Branch: `engine002-core-schema-storage-primitives`

Base commit: `93e8bf79ff6fb6b6419d794b7ef70bac702b8665`

Required ordinary history:

1. `855f5b0` — ENGINE002-SPEC
2. `7febbbc` — ENGINE002-CODEC
3. `9d9e2db` — ENGINE002-STORES
4. `321f5ad` — ENGINE002-TESTS
5. ENGINE002-BENCH (the commit containing this handoff)

The external ZIP/bundle manifest records the exact fifth commit and tree after
the commit exists. No public export, DESCRIPTION field, existing mapper,
authority, scientific fixture, release identity, or default engine changed.

## Classification

`ENGINE002_IMPLEMENTATION_PASS_WITH_BLOCKERS`

Locally closed:

- exact plan/store byte contracts and independent golden checks;
- 1,974/1,974 real authority truth plans, including disk-store validation;
- encode/decode/re-encode and direct-view equality;
- degenerate, terminal/fiber, corruption and lifecycle boundaries;
- bounded LRU/scratch matrix and 15 publication failpoints;
- 10,000 exact and 100,000 storage-only benchmark workloads;
- macOS build, install, package tests and zero-error/zero-warning R CMD check.

Unresolved mandatory blockers:

1. physical valid-store last-record lookup above 2 GiB and 4 GiB was not run;
2. Linux and Windows golden/authority/lifecycle replay was not run;
3. short-write, real/simulated ENOSPC, R interrupt cleanup, and Windows
   no-replace execution evidence remains absent;
4. the work order's explicit constant-fast-hash injection seam for every named
   registry is absent. Production scientific registries use exact ordered keys
   rather than fast-hash identity, and the exact-pattern constant-bucket test
   passes, but this does not satisfy the literal all-registry injection gate;
5. sanitizer/equivalent dynamic memory-safety evidence was not produced.

These are evidence/engineering blockers, not observed scientific mismatches.

## Core results

- Plan schema: TruthPlanRecord-v1.0, 144-byte header, little-endian.
- Store schema: TruthPlanStore-v1.0, 256/64/128-byte header/index/footer.
- Identity: domain-separated SHA-256.
- Fast integrity: XXH64 seed 0, stored little-endian u64.
- Authority records: 1,974; total record bytes 37,604,452.
- Synthetic storage records: 100,000; final store 24,200,384 bytes.
- External benchmark peak RSS: 417,759,232 bytes.
- Charged cache high-water: 33,554,304 bytes under 32 MiB budget.
- Temporary/final disk high-water: 48,400,768 / 24,200,384 bytes.

See `benchmark/ENGINE002_BENCHMARK_SUMMARY.md` and the evidence files for
exact repetitions, min/median/max, raw counters, authority hashes, and limits.
