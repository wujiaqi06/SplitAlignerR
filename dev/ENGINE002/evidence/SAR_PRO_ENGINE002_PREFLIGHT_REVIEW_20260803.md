# SplitAlignerR PRO-ENGINE002-PREFLIGHT

## Independent Production-Schema Red-Team Review

**Reviewer:** GPT-5.6-Pro  
**Role:** Independent adversarial reviewer  
**Date:** 2026-08-03 JST

# Verdict

# `ENGINE002_GO_WITH_BLOCKERS`

The ENGINE001 design is scientifically capable of representing the frozen truth-plan object, and its selected record body is a defensible basis for a narrow production implementation. It is **not yet complete enough to emit a durable `TruthPlanStore-v1` format or finalize ownership/publication behavior without additional pre-implementation freezes**.

Codex may begin ENGINE002 production work only after the blockers in this report are inserted into, and accepted as part of, the ENGINE002 work order. Until then, no production code may write a durable store, publish a manifest, or establish a reusable XPtr/store lifecycle contract.

This is a preflight authorization, not production certification.

---

## 1. Reviewed frozen objects and artifact hashes

### Git objects independently verified from the complete ENGINE001 Git bundle

| Object | Commit | Tree | Parent |
|---|---|---|---|
| Certified release baseline | `17a0927095c7a067817bf598a2556cbe7348a6d0` | `8df164a570ff7ee540381ab381535174044f7918` | `2fc1dd370843d54f3ca90942ce84228c5f08a0eb` |
| ARCH000A | `8ce0d263f0def588f65be4546268ae6d8b2ab38e` | `5c38e46ba4db4a9757deb3dfcd83a11976a85a3c` | `50054bd43abc3fbc840a750f50a3e6ac7f357183` |
| ENGINE001 | `93e8bf79ff6fb6b6419d794b7ef70bac702b8665` | `67ec5592f406843341f0966ba50f6b71058d876a` | `8ce0d263f0def588f65be4546268ae6d8b2ab38e` |

`93e8bf7` is a direct ordinary child of `8ce0d26`. Its 43 changed files are all under `dev/ENGINE001/`; no production path changed.

### Delivered artifacts

| Artifact | SHA-256 | Verification |
|---|---|---|
| `SplitAlignerR_ARCH000A_Bounded_Truth_Store_Handoff_8ce0d26.zip` | `51aabb1da597c9ef6a7421d3f5b22820b6e0b8c784b2953b6031ef0ae29383fd` | sidecar match; 90 files; internal manifest pass |
| `SplitAlignerR_ENGINE001_Production_Design_Handoff_93e8bf7.zip` | `f42569d3a48c577845dc7d226ad3137f6277c7b7968f739a97d2b208e6eea289` | sidecar match; 45 files; internal manifest pass |
| `SplitAlignerR_ENGINE001_Production_Design_93e8bf7.bundle` | `69ade89455a29c4c13af0da35dd0ae9ad2ed32abbecb8eccfc6db50500bb1be0` | complete-history bundle; clone/fsck pass |
| ARCH000A package manifest | `68cb29b4ab1aab0ea31a4ea5924d52421a0afffcc51ce4749947d18ae15077af` | all listed files pass |
| ENGINE001 package manifest | `a161fc71c46514a5cd8f744f77ff58254476ec8248c011bc4499ac9aa506a615` | all listed files pass |
| ENGINE001 evidence manifest | `0b7b3f26c5e3630e9f73bc14fd24450cd3ba826f54515d72ff16ee01819d8974` | all listed evidence files pass |

Both ZIPs have no duplicate members, absolute paths, `..` traversal, or symlink members.

---

## 2. Scientific completeness assessment

### Assessment: conditionally complete; no fundamental scientific-field loss found

The selected plan representation can preserve the required frozen truth object **provided every view is bound to the exact `SpeciesAuthority` and the canonical-validation rules below are mandatory**.

The design can represent:

- exact retained-taxa identity through the full species-universe bitset;
- primitive truth states `eligible`, `NA_struct`, and `NA_fuse` through the two-bit state vector;
- eligible primitive coordinates as exactly state-code 0 primitives;
- projected primitive queries through active-primitive references to exact canonical query entries;
- restriction fibers by grouping primitives that reference the same exact query;
- composite primitive-member sets as the sorted exact state-2 member group;
- composite projected queries as the common pattern-local query of that group;
- terminal/internal classification through the exact authority-bound primitive axis;
- species-authority binding through the frozen authority fingerprint.

The following scientific invariants are correct and must remain hard gates:

1. `NA_struct` and `NA_fuse` are pre-empirical truth states.
2. `NA_topo` is not a packed truth-plan state; state code 3 is invalid in a truth record.
3. A state-0 primitive is only **eligible**, never already `mapped`.
4. B-star identity is the exact canonical primitive-member set, not a projected split and not a hash.
5. Projected splits are pattern-local query values and never global coordinate identity.
6. A retained terminal primitive may be state 0 or state 2, never state 1.
7. A later terminal `NA_topo` remains impossible and must be a hard empirical-kernel failure.
8. Within one pattern, state-2 fibers form disjoint exact groups. Across patterns, B-star sets may overlap or be nested and must not be treated as a global partition.

### Information not required by the frozen truth identity

The selected record does not preserve oriented side-A/side-B counts or path order inside a fiber. This is acceptable because the frozen scientific identity is unrooted, projected queries are canonical, and B-star identity is the exact unordered primitive-member set. No ENGINE002 code may later infer an orientation or ordered path from the packed record.

### Condition on terminal/internal classification

Terminal/internal type is not duplicated inside each plan record. That is safe only if:

- `TruthPlanView` cannot be constructed without the exact, open `SpeciesAuthority`;
- authority species/primitive counts and fingerprint are checked before any state/query access;
- primitive type is read from the immutable authority axis;
- a bare record view is never returned as a scientifically complete object.

---

## 3. Mandatory pre-implementation blockers

## E2-B01 — Freeze the complete `TruthPlanStore-v1` wire format

**Status:** blocker.

The 144-byte plan header and the plan payload sections are substantially specified. The durable store is not. ENGINE001 gives only:

- a 256-byte store header;
- records;
- 64-byte index entries;
- a 128-byte footer;
- a prose list of fields.

It does not freeze exact byte offsets for the store header/footer, store magic, store flags, plan-schema binding, checksum scopes, hash seed, manifest schema, or semantic-version binding. This is insufficient for a durable cross-platform format.

Before code, the work order must include exact byte tables for the 256-byte header and 128-byte footer and must define:

- store magic and completion magic;
- store schema major/minor, plan schema major/minor, header/footer byte counts;
- byte order and flags; v1.0 unknown flags must be rejected;
- species taxon count, primitive count, pattern count;
- records start, index offset, footer offset, exact file length;
- whether offsets are absolute from byte zero; v1 should use absolute u64 offsets;
- no gaps, padding, alignment bytes, or trailing bytes unless explicitly reserved and zero;
- species-authority SHA-256;
- exact pattern-registry fingerprint;
- truth-semantics/kernel-contract fingerprint or frozen semantic version;
- exact byte ranges and order for header, record, index, ordered-record, footer, payload, and complete-file hashes;
- exact XXH64 algorithm, **seed**, and little-endian stored digest representation;
- SHA-256 domain strings and length-prefix rules;
- footer self-hash rule without circular coverage;
- minimal versioned store-manifest schema and publication names.

No native C++ struct layout, `sizeof`, compiler packing pragma, `size_t`, `long`, or native enum may define the format.

## E2-B02 — Freeze the remaining canonical record conventions

**Status:** blocker.

The work order must explicitly freeze:

- disk pattern-ID base and valid range; IDs must be contiguous and deterministic after exact retained-bitset sort;
- disk primitive-ID base and its relation to authority order;
- taxon bit numbering: taxon ID 0 is bit 0, the least-significant bit of byte 0;
- state packing: primitive ID 0 is bits 0–1 of state byte 0;
- zero padding in retained and dense-query final bytes;
- whether header `taxon_count` means global species taxon count; it should be named unambiguously;
- exact canonical query sort key, independent of dense/sparse physical encoding; use the canonical dense selected-side bitset bytes in unsigned lexicographic order;
- sparse IDs as strictly increasing, in-range, retained, zero-based u32 values;
- dense popcount equal to `selected_count`, and all selected bits a subset of retained taxa;
- canonical-side validation relative to the retained set, including equal-side byte tie-breaking;
- query pool strictly sorted and unique; all entries referenced; all refs in range;
- active count exactly equal to the number of state-0 plus state-2 primitives;
- state-2 groups have at least two members and contain no state-0 member;
- no two distinct pattern IDs may encode the same exact retained bitset;
- behavior for an empty store and for zero-query records;
- exact schema-minor policy. The initial reader should accept only major 1/minor 0/header 144/flags 0 unless a later registered compatibility rule exists.

## E2-B03 — Separate create/open states and freeze view lifetime

**Status:** blocker.

The current logical interface uses one `open()` operation and permits lookup during construction. At the same time, `PackedMemoryStore` is a contiguous arena whose growth could invalidate offsets/pointers. This must be resolved before implementation.

The work order must distinguish at least:

- create/build mode;
- finalized immutable mode;
- open-existing validated disk mode;
- closed mode.

It must freeze:

- whether lookup is prohibited until finalize, or whether memory construction preallocates an exact stable arena and never relocates it;
- duplicate insertion behavior: same ID/same bytes, same ID/different bytes, different ID/same retained bits must all be typed failures;
- missing or out-of-order pattern behavior at finalize;
- double-finalize behavior: either idempotent success with no mutation or a stable typed error;
- close with an outstanding view: reject close or retain the backing control block until the last view releases; never leave a dangling span;
- read-after-close as `ENGINE_CONTEXT_CLOSED`;
- view noncopyability, pin ownership, generation check, and release semantics;
- disk cross-session reopen behavior;
- the meaning of “reopen” for `PackedMemoryStore`; cross-session durability applies to disk unless a canonical memory image is separately frozen.

A `TruthPlanView` must never outlive its arena, disk-read buffer, mapped region, cache pin, or store generation.

## E2-B04 — Close the hard-bound LRU and oversized-record contract

**Status:** blocker.

The design correctly rejects `object.size()` as a hard cache bound, but the oversized-record path is not fully closed. A record larger than the cache budget cannot be served by an uncharged buffer while still claiming the cache budget is a whole truth-memory bound.

The work order must define:

- exact charged bytes for slabs, key, metadata, alignment/fragmentation, verified flag, pin bookkeeping, and allocator reservation;
- cache budget high-water assertion after every insert/eviction;
- a separate, planner-reserved single-plan scratch budget;
- behavior when cache budget is below one record;
- behavior when a record exceeds cache budget but fits single-plan scratch: bypass cache, one scoped scratch view, no insertion;
- behavior when a record exceeds single-plan limit: fail before mapping;
- whether the disk index is charged to truth-store memory and how it is bounded;
- pinned-entry allowance and close/eviction behavior;
- deterministic stats counters and overflow handling.

The acceptance invariant is:

```text
cache slabs + cache metadata + pins <= cache budget
single oversize scratch <= single-plan budget
all truth-store runtime allocations <= planner-recorded combined bound
```

## E2-B05 — Freeze one non-contradictory atomic-publication protocol

**Status:** blocker.

ENGINE001 documents differ on whether `fsync` occurs before or after the completion footer. The durable sequence must be one exact protocol. The accepted sequence must include a final flush/sync **after** the footer and all header/index patches.

The work order must freeze:

1. exclusive temporary creation in the destination directory;
2. header/records/index writes with checked short-write handling;
3. final header patch and header hash;
4. footer write;
5. file flush and platform durability request after all bytes exist;
6. close and read-only reopen;
7. full structural and checksum validation;
8. complete-file SHA-256;
9. separate temporary `INCOMPLETE`/candidate manifest creation;
10. no-clobber atomic component rename;
11. validation under final component names;
12. no-clobber atomic `VALIDATED` manifest rename last;
13. directory sync where supported;
14. typed failure if any durability primitive fails.

Pre-existing destination files must never be overwritten. A preflight existence check alone is not sufficient because of TOCTOU; publication needs no-replace semantics or an exclusive reservation. Cross-device rename, symlink redirection, partial copy fallback, and in-place manifest mutation are prohibited.

## E2-B06 — Freeze the exact identity registry and collision test seam

**Status:** blocker.

The species and per-pattern fingerprint formulas are largely specified, but the exact pattern-registry fingerprint and truth-semantic binding used for store reuse are not.

Before code, define canonical bytes for:

- ordered finalized pattern IDs and exact retained bitsets;
- pattern-registry fingerprint;
- truth-plan semantic/kernel contract fingerprint;
- store identity that binds both.

Fast hashes may choose buckets or detect corruption only. Tests must be able to inject a constant fast hash so that distinct:

- retained patterns;
- canonical queries;
- B-star member sets;
- LRU/cache keys;
- record-index lookup buckets

collide deliberately while exact bytes remain distinct. No collision may merge plans, queries, fibers, coordinates, or cache entries.

## E2-B07 — Freeze the ENGINE002 authority and benchmark rubric before coding

**Status:** blocker.

The existing 1,974-plan round trip is a pure-R prototype-body comparison. It does not exercise the final 144-byte header, production XXH64/SHA fields, C++ direct views, store container, LRU, atomic publication, Linux, or Windows. The 10,000 and 100,000 ARCH000A storage cases use the earlier fixed-width experimental record, not the selected hybrid production record.

The ENGINE002 work order must therefore carry the complete acceptance checklist and benchmark contract below before implementation begins. Prototype timings may be cited only as prototype baselines.

---

## 4. Binary-schema hazard findings

| Hazard | Review finding | Required ENGINE002 disposition |
|---|---|---|
| Plan magic/version/header | Plan header offsets cover exactly 144 bytes | Keep exact; add golden bytes |
| Store magic/version/footer | Exact layout absent | E2-B01 blocker |
| Endianness | Little-endian selected | Explicit byte loads/stores only; no unaligned casts |
| Integer widths | u16/u32/u64 selected | Checked arithmetic before every add/multiply/seek/allocation |
| Offset widths | Record query offsets u32; store offsets u64 | Reject record payload `>=2^32`; test store offsets across 2 and 4 GiB |
| Alignment/padding | No struct dumps selected | Canonical byte stream has no implicit alignment; reserved bytes zero |
| `flags` | Present but undefined | v1.0 flags must be exactly zero until registered |
| Schema minor | Compatibility rule unclear | v1 reader initially accepts minor 0 only |
| Zero-length sections | Not completely specified | Freeze valid/invalid empty store, zero-query and zero-pattern cases |
| Maximum counts | Widths named, practical limits not closed | Check against u32/u64, `size_t`, `streamoff`, file API, R limits and configured budgets |
| >2/4 GiB | Store u64 is conceptually adequate | Actual large-offset store test required, including Windows |
| Truncation | General rejection stated | Section-by-section and failpoint tests required |
| Duplicate records | Duplicate IDs mentioned, duplicate exact patterns not | Reject both |
| Offset tables | Monotonicity stated | Also check first=0, last=pool bytes, strict entry boundaries, no overlap/gap/overflow |
| Enum values | Some invalid values described | Reject unknown state, query encoding, endian, width, flags and schema values |
| Forward compatibility | Not closed | Fail closed for unknown minor/flags/encodings in v1.0 |
| Hash algorithm | “xxHash64” named | Freeze XXH64 variant, seed and byte coverage; add reference vectors |

All numeric parsing and bit access must be implemented through explicit endian helpers or `memcpy` into fixed-width integers. A direct view must not `reinterpret_cast` potentially unaligned record bytes to native integer structs.

---

## 5. Ownership and lifecycle hazards

1. **Memory-arena relocation:** lookup during construction can conflict with a growing contiguous arena. Resolve under E2-B03.
2. **Stale LRU view:** an evicted or closed backing entry must remain pinned or make every later access fail before dereference.
3. **Close with pins:** close semantics with active views are unspecified and must be frozen.
4. **Double finalization:** not specified; add deterministic behavior and tests.
5. **Memory-store reopening:** distinguish same-process immutable arena reopening from durable cross-session disk reopening.
6. **Index lifetime:** disk index, file handle, cache slabs and scratch buffers must share one generation-controlled owner.
7. **Cache bypass:** oversized records must use a separately charged scratch owner whose lifetime equals the view.
8. **Recompute callback:** ENGINE002 may define/test a producer callback, but the scientific truth kernel remains ENGINE004. Recompute must return bytes accepted by the same canonical encoder/validator, not a second schema.

---

## 6. Atomicity and corruption hazards

ENGINE002 must reject, with stable typed categories, at least:

- truncated plan header;
- truncated retained bitset, state vector, refs, offsets or query pool;
- truncated store header, records, index or footer;
- missing footer;
- wrong header/footer byte count;
- nonzero reserved bytes or padding bits;
- invalid state/query encoding/flags;
- malformed sparse IDs and noncanonical dense query;
- malformed, overlapping, out-of-range or overflowing offsets;
- duplicate/missing/out-of-order pattern IDs;
- duplicate exact pattern bytes under different IDs;
- mixed state-0/state-2 query group;
- singleton state-2 group;
- unreferenced query entry;
- wrong record/header/index/footer checksum;
- wrong complete-file SHA-256;
- wrong species authority;
- wrong pattern-registry or semantic fingerprint;
- unsupported schema version;
- unexpected trailing bytes;
- single-byte corruption in every logical region;
- interrupted write after every publication stage;
- short write and injected `ENOSPC`/disk-full failure;
- pre-existing final store or manifest;
- cross-device destination;
- stale/incomplete manifest;
- component renamed but manifest absent.

An incomplete store must never be accepted based on a valid-looking footer alone. Acceptance requires the exact footer, complete-file validation and the final `VALIDATED` manifest.

---

## 7. R/C++ safety boundary required for ENGINE002

The design direction is acceptable, but production acceptance requires:

- R owns ordinary inputs, controls, durable descriptors and diagnostic copies;
- C++ copies canonical input bytes and never retains an unprotected R-vector pointer;
- direct `TruthPlanView` objects never cross into R;
- XPtrs carry type tag, ABI major, generation and open state;
- every entry point validates the XPtr before dereference;
- active calls hold a strong local guard;
- explicit close and finalizer share one no-throw idempotent path;
- invalid/closed XPtrs produce `ENGINE_CONTEXT_CLOSED`;
- all standard/unknown exceptions are translated to typed conditions;
- `std::bad_alloc` maps to `ENGINE_ALLOCATION_FAILURE`;
- R interrupts remain interrupts, not generic unknown C++ errors;
- file handles, pins, temporary paths and scratch buffers release on normal return, error, interrupt and GC;
- no ordinary durable output depends on an XPtr remaining alive;
- no plan/store larger than R's safe raw-vector/materialization limit is copied into one R object;
- completed disk stores reopen in a later R session from validated ordinary metadata.

The current isolated ownership sketch is evidence for intent only. It does not implement the frozen magic/ABI/generation contract and is not production certification.

---

## 8. Frozen ENGINE002 acceptance checklist

### A. Scope and identity

- [ ] Implementation commit is an ordinary child of accepted ENGINE001 or a separately approved narrow base.
- [ ] Certified `v0.1.0` commit and public/default API remain unchanged.
- [ ] No empirical mapper replacement, matrix backend, public API migration or default switch.
- [ ] Exact changed-file manifest and source archive/hash supplied.

### B. Plan codec and direct view

- [ ] Exact cross-language golden vectors for header, retained bits, states, refs, offsets and dense/sparse entries.
- [ ] Encode -> decode -> re-encode gives byte-identical output.
- [ ] Direct view and decoded object agree field-for-field.
- [ ] Direct view exposes retained membership, state per primitive, active query, fiber members and composite query without full R reconstruction.
- [ ] State code 3 is rejected in truth plans.
- [ ] All canonical/padding/subset/order rules from E2-B02 enforced.
- [ ] Unknown minor/flags/encodings fail closed.

### C. Scientific authority

- [ ] All 1,974 real authority plans exactly equal ARCH000A for retained taxa, every primitive state, eligible set, every projected query, every fiber, every composite member set and every composite query.
- [ ] Terminal/internal type is obtained from exact authority and all retained-terminal truth invariants pass.
- [ ] Zero-input and one-taxon plans produce the frozen stable rejection.
- [ ] Accepted two- and three-taxon plans round-trip and direct-query exactly.
- [ ] Endpoint collapse and terminal fusion cases pass.
- [ ] Within-pattern fibers are disjoint; across-pattern nested and overlapping B-star sets are preserved exactly.
- [ ] No pre-empirical `NA_topo` exists.

### D. Identity and collision resistance

- [ ] Constant-hash collision tests for patterns, queries, B-star sets, cache buckets and index buckets.
- [ ] Exact bytes resolve every collision.
- [ ] Wrong exact retained bits with a correct ID/hash are rejected.
- [ ] Correct exact bits with a wrong ID are rejected.
- [ ] Duplicate exact pattern under another ID is rejected.

### E. `PackedMemoryStore`

- [ ] Empty-store behavior is frozen and tested.
- [ ] Single-record and 1,974-record stores pass.
- [ ] Insert order cannot change finalized canonical store bytes/index.
- [ ] Finalization detects duplicate/missing/out-of-order records.
- [ ] Views remain valid only under the frozen pin/generation rule.
- [ ] Double finalize and repeated close behavior are exact.
- [ ] Read-after-close fails safely.

### F. `PackedDiskStore`

- [ ] Exact store header/index/footer/manifest golden bytes.
- [ ] Build, finalize, close, reopen and full validation pass.
- [ ] Cross-session reopen with correct authority passes.
- [ ] Wrong authority, pattern registry, semantic contract and schema fail.
- [ ] Files above 2 GiB and 4 GiB use correct u64 offsets and last-record lookup.
- [ ] No signed 32-bit or C `long` truncation on Windows.

### G. LRU and oversized plans

- [ ] Budget zero/below one record/exactly one record/multiple records tested.
- [ ] Record larger than cache but within single-plan scratch is served without cache insertion and without exceeding combined bound.
- [ ] Record larger than single-plan limit fails before use.
- [ ] Pinned entry cannot be evicted.
- [ ] Evicted view cannot be accessed.
- [ ] Hit/miss/eviction/high-water counters are deterministic and overflow-safe.
- [ ] Actual charged bytes never exceed budget.

### H. Atomic publication and corruption

- [ ] Failpoint after each write/publication stage leaves no accepted store.
- [ ] Missing footer, truncated header/payload/index/footer all rejected.
- [ ] Single-byte corruption across all logical regions rejected.
- [ ] Bad checksum, bad SHA, malformed offsets, invalid enum and trailing bytes rejected.
- [ ] Disk-full/short-write failure leaves no final manifest.
- [ ] Pre-existing destination remains byte-identical and is not overwritten.
- [ ] Component-without-manifest and manifest-with-missing-component both rejected.
- [ ] Final store and manifest publication uses no-clobber same-filesystem atomic rename.

### I. R/C++ lifecycle

- [ ] Wrong type, wrong ABI, stale generation and closed XPtr rejected.
- [ ] Finalizer is idempotent and no-throw.
- [ ] GC during/after ordinary snapshot does not invalidate durable bytes/output.
- [ ] Interrupt during encode, validation, checksum and store write closes resources and publishes nothing.
- [ ] Raw C++ exceptions do not reach ordinary users.
- [ ] Completed disk store reopens after original pointer GC and in a new R session.

### J. Cross-platform determinism

- [ ] Linux, macOS and Windows decode the same golden bytes.
- [ ] Re-encoding produces identical bytes and hashes on all three.
- [ ] Big-endian interpretation is covered by an explicit byte-swap/golden test even if no big-endian runner is available.
- [ ] File operations are binary-mode and CRLF/locale independent.

---

## 9. Mandatory ENGINE002 runtime benchmark contract

### Workloads

1. **Real authority:** all 1,974 exact plans.
2. **Exact stress:** 10,000 exact deterministic plans encoded in the selected hybrid schema.
3. **Store stress:** 100,000 canonical packed-store records using the selected production record and index format; label synthetic storage-only data as non-scientific.
4. **Large-offset fixture:** a validated store whose last record/index/footer crosses 2 GiB and 4 GiB.

The previous ARCH000A 10,000/100,000 rows are prototype baselines for the older fixed-width record and cannot substitute for these measurements.

### Operations to measure

- plan encode wall time;
- full decode/reconstruction wall time;
- validated direct-view construction time;
- direct primitive-query throughput;
- direct fiber/composite enumeration throughput;
- `PackedMemoryStore` build, finalize and same-process reopen/validation time under the frozen meaning;
- `PackedDiskStore` write, finalize, close and cross-session reopen/full-validation time;
- sequential lookup throughput;
- fixed-seed random lookup throughput;
- process-cold and warm lookup results;
- LRU hit, miss, insert, pin, eviction and oversized-bypass cost;
- checksum/SHA/full-validation overhead;
- peak RSS from an external process monitor;
- cache charged-byte high-water;
- temporary and final disk high-water;
- CPU user/system time where defensible.

### Cache/access cases

At minimum:

- no cache or zero-byte cache where supported;
- cache below the smallest record;
- cache equal to one record;
- 32 MiB, 64 MiB and a workload-appropriate larger budget;
- original authority order;
- reversed order;
- grouped-by-pattern order;
- maximally interleaved reuse order;
- fixed-seed random order;
- cold first pass and warm second pass.

“Cold” must be defined. If the OS page cache cannot be reliably cleared, report `PROCESS_COLD` or `FRESH_FILE_COPY`, not an unsupported hardware-cold claim.

### Repetitions and reporting

Each accepted benchmark case requires at least three independent repetitions. Report:

```text
median
minimum–maximum
plans/second
queries/second
MB/second
wall time
CPU user/system time where defensible
peak RSS
charged cache high-water
temporary/final disk bytes
hit/miss/eviction counts
```

Correctness gates run on Linux, macOS and Windows. Full performance measurements may use a documented reference host, but cross-platform golden-byte and 1,974-authority results are mandatory. Hosted-runner performance must not be compared as if hardware were controlled.

### Prototype baseline label

The ENGINE001 values—approximately 97.667 s R encode, 186.644 s R decode, and 531,234,816-byte sampled RSS for the 1,974-plan selected candidate—must be labelled:

```text
PURE-R PROTOTYPE BASELINE — NOT A PRODUCTION C++ SPEED CLAIM
```

No production speedup claim is allowed until ENGINE002 measurements exist.

---

## 10. Issues deferred to ENGINE003 or later

The following are explicitly outside ENGINE002 and must not be pulled into this task:

- typed in-memory/tiled matrix backend, validity bitmap and matrix manifest: ENGINE003;
- empirical split index, `Mapped`/`NA_topo` recovery, branch-length row fill and terminal empirical invariant: ENGINE004;
- full mapper integration, paired fixed/free orchestration, 2,275-gene empirical replay and 407 residual ledger: ENGINE005;
- independent three-platform end-to-end RECERT: ENGINE006;
- public exported names, result classes, default selection and migration: ENGINE007;
- parallel workers and deterministic reduction: later separately authorized task;
- resume/checkpoint schema: later major schema/task;
- compression, encryption, remote stores and alternate tile/record layouts: later registered schema work;
- replacement Newick scanner/parser: separate differential authorization.

ENGINE002 may provide a recompute-store callback interface and synthetic/golden producer for tests. The actual truth-construction kernel remains later work.

---

## 11. Final recommendation

`ENGINE001` is scientifically sound enough to continue, but it is **not** a complete durable-store specification as frozen. The missing decisions are concentrated in byte-level store identity, canonical ID/bit conventions, view/store lifecycle, hard LRU accounting, and atomic no-clobber publication. These can be closed without changing SplitAligner scientific semantics or reopening the public API.

**Recommendation:** Codex may begin ENGINE002 production work only after the main console adopts E2-B01 through E2-B07 and the acceptance/benchmark rubrics above as binding work-order clauses. Before that adoption, no production durable-format or store-lifecycle implementation is authorized.

---

## 12. No-modification statement

No repository file, Git object, tag, release, package source, authority input, test, or implementation was modified during this review. The review used read-only archive extraction, checksum verification, Git bundle clone/fsck, Git history/diff inspection, and source/document analysis only.
