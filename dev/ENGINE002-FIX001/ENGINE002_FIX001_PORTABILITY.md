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
