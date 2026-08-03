# ENGINE002-FIX001 construction memory model

The corrected disk-builder model is:

    finalized PatternRegistry
    + one current packed record
    + fixed writer/hash/lifecycle metadata
    + 64 bytes * N wire index
    + bounded I/O buffers

It is not constant total memory: the finalized registry and compact index grow
linearly with pattern count. The key closed blocker is that the builder no
longer retains the sum of all full packed-record payloads.

The instrumented builder_charged_high_water is:

    4096 fixed builder bytes
    + current wire-index bytes
    + current record bytes
    + measured writer-buffer high-water

The current writer performs direct bounded writes, so its reported write-buffer
high-water is zero. temporary_disk_high_water tracks the largest current-run
component extent. index_charged_bytes after reopen includes decoded index
containers and exact retained keys, and is deliberately more conservative than
the 64-byte wire index.

builder_charged_high_water does not double-count the caller-owned finalized
registry. External peak RSS includes the R runtime, shared library, registry,
temporary current record, decoded validation index, OS allocator high-water,
and benchmark harness. Consequently external RSS is the authoritative
whole-process measurement, while charged bytes explain the bounded builder
component.

The superseded retain-all comparison reports the total packed payload as a
strict lower bound on builder-owned retained record memory because the old
implementation did not expose a builder charge counter. Its external RSS is
measured by the same polling method and on the same host.

File cache is not resident heap and is not charged to the builder. Physical
store bytes and process RSS are therefore reported separately.
