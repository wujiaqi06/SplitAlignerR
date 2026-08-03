# ENGINE002-FIX001 implementation

## Frozen boundary

Implementation branch: engine002-fix001-bounded-streaming-store.
The exact parent is ENGINE002 commit
8c0d494f57f4594ff5acfd8e02ef546fcc387f0b (tree
d5350a6500671bd70d83f2d46840f596760741ba). The certified v0.1.0
object is not modified. No public R export, mapper, scientific state, wire
schema, authority, version, or release metadata changes in FIX001.

## Corrective implementation

PackedDiskStore now receives an already-finalized PatternRegistry, creates
an exclusive binary temporary component immediately, and accepts only the next
canonical pattern ID. Every record is fully decoded and checked against the
exact retained-pattern registry entry before its bytes are written. The writer
then updates incremental record and payload hashes, appends one 64-byte wire
index entry, and releases the record owner.

The disk builder no longer owns a StoreBuilder, std::map of records, or
FinalizedPlanSet. PackedMemoryStore deliberately retains its existing
arbitrary-insertion/finalization behavior.

Finalization writes the index and footer, patches the header, flushes and closes
the writer, performs complete validation, publishes without replacement, fully
validates the published component, and publishes VALIDATED manifest last.
Failure cleanup removes only recognized temporary/current-run outputs.

The former unlocked const FinalizedPlanSet& finalized() accessor was removed.
R-facing lookups return owned decoded snapshots; a regression test proves a
snapshot remains valid after store close.

## Safety and portability

SHA-256 finalization explicitly checks buffered_ <= 63 and
total_ <= UINT64_MAX / 8; update and bit-length arithmetic are checked.
Deterministic seams cover short/partial writes, flush, close, ENOSPC,
cancellation, and all 15 publication stages. The fast hash is injectable across
all seven lookup domains, while exact bytes remain the authoritative equality.

Durable offsets remain little-endian unsigned 64-bit. POSIX and Windows paths
retain binary I/O and no-replace publication; unsupported atomicity remains a
typed error.

## Evidence boundary

Local macOS execution covers package check, the exact 1,974-plan authority,
faults, collision behavior, interruption, sanitizer core harness, and physical
large stores documented in this folder. Linux/GCC, Windows/MSVC or Rtools, and
package-level R-boundary sanitizer evidence are not inferred from macOS and are
listed as blockers unless independent runs are attached.
