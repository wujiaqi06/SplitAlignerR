# ENGINE002-FIX001 portability contract

The streaming writer uses binary descriptors on every platform. Durable fields
and positions are fixed-width little-endian integers; no C long, native struct,
or text-mode stream defines store bytes. Reads and writes are chunked before
conversion to platform I/O widths, and every u64 offset is range-checked before
conversion to off_t, streamoff, or __int64.

POSIX publication retains the same-directory hard-link plus unlink no-replace
protocol. Windows retains MoveFileExW without MOVEFILE_REPLACE_EXISTING and
opens component files with _O_BINARY. Unsupported no-replace behavior remains
ENGINE_UNSUPPORTED_ATOMICITY; there is no copy or overwrite fallback.

tools/engine002/fix001_large_offset.R constructs actual wire-valid 302-taxon,
601-primitive stores with 15–25 KB records. It records first/last index entries,
u64 section offsets, footer count, exact file length, and construction memory.
tools/engine002/fix001_large_offset_reopen.R recreates the exact authority in a
fresh R process, performs complete validation, and queries first, middle, and
last records.

Platform and large-file gates are evidence gated. A source inspection or
arithmetic projection is never recorded as execution PASS.

## Local physical execution

The macOS arm64 run completed three non-sparse, fully hashed and validated
authority-sized stores:

| records | exact file bytes | large-offset role | fresh reopen |
|---:|---:|---|---|
| 100,000 | 1,587,660,960 | mandatory storage stress | PASS |
| 140,000 | 2,223,669,984 | physical greater-than-2-GiB gate | PASS |
| 275,000 | 4,371,260,760 | physical greater-than-4-GiB gate | PASS |

For each, the u64 header exact length, filesystem length, footer offset/count,
last index ID, complete-file integrity, first/middle/last semantic lookup, and
new-process reopen agree. A separate fixed-seed standalone probe reopened each
store, performed complete validation, and retrieved exact near-boundary IDs
99,740, 139,740, and 274,740 respectively (259 records before the last ID).

These results establish the large-offset gate on macOS only. Windows and Linux
remain execution-evidence blockers; source portability is not substituted for
hosted execution.
