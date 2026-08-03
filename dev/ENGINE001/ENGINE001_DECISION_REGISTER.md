# ENGINE001 decision register

Every central production choice is closed below. “Revisit” means a future
schema/task trigger, not an unresolved ENGINE001 blocker.

## D01 — Packed truth-plan schema

- Selected: hybrid deduplicated canonical query pool with per-query
  dense/sparse payload, u32 active references and offset table.
- Rejected: dense-only permanent format; scan-only per-primitive sparse records;
  R serialization.
- Evidence: all three candidates passed 1,974/1,974 actual authority plan round
  trips; selected format supports direct views and has better larger-tree
  observed-shape projection than alternatives.
- Trade-off: approximately 1.5% larger than sparse-only on 302 taxa and more
  encoder complexity.
- Revisit: a new schema major after cross-platform workloads show a different
  query-pool/index design is materially better.

## D02 — Checksum and identity

- Selected: xxHash64 plus strict structural validation for fast components;
  SHA-256 for species/pattern/store/manifest identity.
- Rejected: Adler-32; hash-only identity; cryptographic hash on every hot query.
- Evidence: ARCH000A corruption gates and ENGINE001 manifest rejection cases;
  fast noncryptographic checks are adequate only when exact bytes and SHA-256
  remain authoritative.
- Trade-off: two hashing layers and more metadata.
- Revisit: vetted platform-native CRC32C may replace xxHash64 only with identical
  cross-platform golden vectors and no weaker detection contract.

## D03 — Truth-store interface

- Selected: one backend-neutral insert/lookup/validate/finalize/close interface
  returning scoped immutable packed views.
- Rejected: mapper-specific backend branches; persistent verbose R-plan cache.
- Evidence: ARCH000A cross-strategy scientific equality and measured decode
  cost; one view prevents semantics from depending on cache policy.
- Trade-off: requires a strict pin/lifetime abstraction.
- Revisit: only if direct views cannot support a future registered schema.

## D04 — Truth-store policy

- Selected: packed memory at <=80% cache budget; otherwise disk + hard byte LRU;
  bounded recompute fallback.
- Rejected: unbounded retain-all; automatic mid-run fallback; mandatory disk.
- Evidence: accepted ARCH000A authority and 100,000-pattern storage stress.
- Trade-off: disk-space preflight and cache implementation complexity.
- Revisit: after production C++ reconstruction/storage measurements on three
  platforms.

## D05 — Matrix layout

- Selected: fixed 256x256 row-major tiles.
- Rejected: global row-major and R column-major as file default.
- Evidence: measured 2,275x1,086 and 100,000x4,913 synthetic layout cases; tiles
  balance streaming write, block/column reads and RSS.
- Trade-off: tile index and bounded buffering; raw byte order differs from R.
- Revisit: schema major/minor extension after multi-platform workload evidence.

## D06 — File-backed matrix format

- Selected: separate typed state, validity and numeric component files bound by
  one validated manifest.
- Rejected: one interleaved container; RDS; numeric NaN payload as missingness.
- Evidence: access paths commonly need state or one numeric component; explicit
  validity is portable; separate files retain deterministic tile access.
- Trade-off: multi-file atomic publication requires manifest-last discipline.
- Revisit: optional registered compression or container packaging after exact
  deterministic implementation.

## D07 — Matrix backend selection

- Selected: automatic conservative planner; in-memory only when complete bytes,
  reserves and R materialization limit all fit, otherwise tiled file backend.
- Rejected: user-required backend flag; optimistic allocation then fallback.
- Evidence: authority shape is small while 100,000x4,913 is 4.42 GB and unsafe
  for universal R materialization.
- Trade-off: some high-memory systems may use files conservatively.
- Revisit: calibrated allocator/RSS safety factors after ENGINE006.

## D08 — R/C++ ownership

- Selected: R owns user/durable objects; opaque context owns active C++
  resources; ordinary files/objects survive pointer lifetime.
- Rejected: external pointer as result authority; retained pointers into
  temporary R vectors; branch-granular calls.
- Evidence: isolated compiled lifecycle sketch passes snapshot, GC, close and
  stale-pointer gates.
- Trade-off: explicit descriptor/context split and reopen validation.
- Revisit: no weakening; ABI major may evolve internal fields.

## D09 — External pointers

- Selected: allowed only for immutable authority and active run context with
  type/ABI/generation/open checks and idempotent finalizer.
- Rejected: serialized pointer addresses and user-visible pointer mechanics.
- Evidence: ownership prototype and durable file-backed requirement.
- Trade-off: every entry point pays small validation overhead.
- Revisit: only to reduce pointer use, never to make it durable authority.

## D10 — Single-dataset workflow

- Selected: minimal two-input conceptual workflow plus one optional control.
- Rejected: fixed/free mode, backend/layout/cache top-level parameters.
- Evidence: unified mapper semantics and ordinary-user gate.
- Trade-off: advanced debugging uses manifest/control rather than many arguments.
- Revisit: exported names only in ENGINE007 compatibility review.

## D11 — Paired workflow

- Selected: fixed/free as explicit directional dataset roles sharing authority,
  truth store and coordinate registry while retaining distinct matrices.
- Rejected: two mapper implementations or a fixed/free kernel flag.
- Evidence: ARCH000A free side reused fixed-loaded plans with identical science.
- Trade-off: paired orchestration maintains two matrix descriptors.
- Revisit: public names only; directionality and unified mapping are frozen.

## D12 — Parallelism boundary

- Selected: deferred; future unit is independent gene blocks, immutable shared
  truth, disjoint tile rows and deterministic thread-local counter reduction.
- Rejected: shared mutable unordered maps and pre-authority multithreading.
- Evidence: determinism is mandatory and single-thread kernels are not yet
  production-implemented.
- Trade-off: initial production speed is single-threaded.
- Revisit: separate task after ENGINE006 single-thread PASS.

## D13 — Interruption and resume

- Selected: manifest-last atomic publication; incomplete files rejected;
  schema-v1 restart under a new run ID, no resume.
- Rejected: partial-store reuse and silent cleanup of unrelated files.
- Evidence: five manifest cases pass; ARCH000A interruption gates pass.
- Trade-off: long interrupted runs recompute.
- Revisit: resumability only with a separate checkpoint schema and adversarial
  tests.

## D14 — Backward compatibility

- Selected: reference -> shadow -> compact compare -> opt-in -> RECERT ->
  authorized default; fallback retained at least one release cycle.
- Rejected: rewrite reference engine or immediate default switch.
- Evidence: certified v0.1.0 boundary and prior enriched-object memory blocker.
- Trade-off: temporary maintenance of two engines.
- Revisit: fallback removal only after a later release and explicit evidence.

## D15 — Production sequence

- Selected: ENGINE002 schema/store, ENGINE003 matrix, ENGINE004 kernels,
  ENGINE005 shadow, ENGINE006 cross-platform RECERT, ENGINE007 public migration.
- Rejected: one mega-commit or API-first implementation.
- Evidence: each layer has an independent rollback and gate boundary.
- Trade-off: more review cycles, substantially lower certification risk.
- Revisit: sequence may stop, never silently skip dependencies.
