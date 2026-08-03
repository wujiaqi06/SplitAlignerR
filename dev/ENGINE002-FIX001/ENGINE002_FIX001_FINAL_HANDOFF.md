# ENGINE002-FIX001 final handoff

## Classification

ENGINE002_FIX001_PASS_WITH_BLOCKERS

The implementation blocker is closed: disk construction no longer retains all
packed records. macOS correctness, exact authority, physical large-offset,
fault, collision, deterministic publication, and core sanitizer gates pass.
The classification cannot be elevated to PASS because mandatory Linux,
Windows, GCC, and package/R-boundary sanitizer execution evidence is absent.

## Identity and commit discipline

Branch: engine002-fix001-bounded-streaming-store

Base commit: 8c0d494f57f4594ff5acfd8e02ef546fcc387f0b

Base tree: d5350a6500671bd70d83f2d46840f596760741ba

Ordinary commits:

1. 7779bf1 FIX001-STREAM: implement bounded streaming disk builder
2. 64be3ee FIX001-SAFETY: close hash reference and fault boundaries
3. 45159c5 FIX001-PORTABILITY: add u64 large-store validation fixtures
4. 1f4933a FIX001-TESTS: verify streaming safety and lifecycle boundaries
5. FIX001-BENCH: evidence and handoff commit containing this document

The fifth commit SHA and final tree are recorded in the external handoff
manifest because a commit cannot contain its own hash. No squash, merge to
main, release, version, or certified-tag operation is part of this task.

## Gate results

| gate | result |
|---|---|
| true streaming disk builder | PASS |
| retain-all packed payload removed | yes |
| sequential ID/error contract | PASS |
| SHA-256 invariants and checked length arithmetic | PASS |
| unsafe finalized reference | removed |
| deterministic I/O faults | 9/9 PASS |
| atomic publication failpoints | 15/15 PASS |
| real Ctrl-C interruption | PASS |
| constant-hash exact domains | 7/7 PASS |
| 1,974 real authority | 1,974/1,974 PASS |
| physical greater-than-2-GiB store | PASS |
| physical greater-than-4-GiB store | PASS |
| macOS package and store gates | PASS |
| Linux | INCOMPLETE, not run |
| Windows | INCOMPLETE, not run |
| GCC 14 warning gate | INCOMPLETE, compiler unavailable locally |
| Clang strict warning gate | PASS |
| ASan and UBSan core harness | PASS |
| package/R-boundary sanitizer | INCOMPLETE, not run |
| final R CMD check --no-manual | PASS, Status: OK |
| public exports changed | no |

## Bounded-construction evidence

The required 100,000-record authority-sized stress completed with:

| metric | value |
|---|---:|
| mean/min/max packed bytes | 15,812.606 / 15,617 / 16,001 |
| final store bytes | 1,587,660,960 |
| whole R-process peak RSS | 159,809,536 |
| builder charged high-water | 6,419,889 |
| decoded index charge | 25,600,000 |
| write-buffer high-water | 0 |
| total build seconds | 222.406 |

At 275,000 records the largest completed store is 4,371,260,760 bytes.
Mean record size is 15,831.492 bytes, whole R-process peak RSS is 277,889,024
bytes, builder charged high-water is 17,619,865 bytes, and decoded index charge
is 70,400,000 bytes. This demonstrates the declared
O(one record + fixed buffers + N times compact index) builder model; it does
not claim constant total memory.

## Controlled old/new comparison

The frozen base retain-all builder and final streaming builder were compiled as
standalone C++ binaries with the same compiler, optimization, deterministic
302-taxon/601-primitive record generator, host, and 50-ms external RSS sampler.

At 100,000 records:

| metric | retain-all base | streaming final |
|---|---:|---:|
| final store bytes | 1,587,660,960 | 1,587,660,960 |
| total packed payload | 1,581,260,576 | 1,581,260,576 |
| peak RSS | 1,830,813,696 | 114,737,152 |
| builder retained/charged lower bound | 1,581,260,576 | 6,419,889 |
| insert plus record generation seconds | 129.602 | 117.769 |
| finalize/validate/publish seconds | 121.596 | 109.577 |

The streaming peak is 15.96 times smaller; the directly charged/retained
builder bytes are 246.31 times smaller. The old 100,000 run was completed
rather than projected.

## Functional medians

Three repeated 10,000-record R-package runs produced:

| phase | median seconds | observed range |
|---|---:|---:|
| streaming write | 3.080882 | 3.008325–3.126385 |
| combined finalize/validate/publish | 10.614431 | 10.557654–10.932786 |
| final I/O | 0.917910 | 0.909786–0.920609 |
| temporary complete validation | 4.859908 | 4.797775–4.907145 |
| atomic publication and directory sync | 0.000643 | 0.000639–0.000699 |
| published complete validation | 4.895673 | 4.774647–5.113257 |
| fresh-process complete validation | 4.871424 | 4.788515–4.989845 |
| sequential 100-lookups | 0.043211 | 0.043014–0.068281 |
| fixed-seed random 100-lookups | 0.042487 | 0.042117–0.043829 |
| LRU warm 100-lookups | 0.039528 | 0.039119–0.040440 |
| complete-file SHA-256 | 0.475000 | 0.474000–0.483000 |
| total build | 22.221000 | 22.098000–22.470000 |

Fresh-process results are labelled PROCESS_COLD_FILE_CACHE_UNCONTROLLED.
Repeated same-process lookup and SHA results are WARM. No hardware-cold claim
is made.

## Physical large offsets

The 140,000-record file is 2,223,669,984 bytes, or 76,186,336 bytes above
2 GiB. The 275,000-record file is 4,371,260,760 bytes, or 76,293,464 bytes
above 4 GiB. Both passed exact u64 header/index/footer lengths, full component
and manifest integrity, first/middle/last lookup, new-process reopen, complete
SHA-256, and a separately compiled fixed-seed near-boundary lookup.

Large disposable stores and compiled binaries are deliberately excluded from
Git history and the handoff ZIP.

## Unresolved blockers

1. Linux mandatory correctness suite and GCC 14 strict-warning build were not
   run in the local environment.
2. Windows mandatory correctness suite, binary-mode behavior, u64 offsets, and
   atomic no-replace execution were not run.
3. ASan/UBSan cover the standalone core harness, not package-level or R-boundary
   execution.

No incomplete item above is represented as PASS.
