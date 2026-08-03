# ENGINE002-FIX001 benchmark contract

## Workloads

- real frozen authority: 1,974 retained-taxa truth plans from RECERT013;
- deterministic synthetic 302-taxon/601-primitive stores at 1,974 and 10,000
  records, three repetitions;
- deterministic 100,000-record authority-sized storage stress;
- physical valid stores crossing 2 GiB and 4 GiB.

Synthetic records use the production codec and store validator. They are
engineering storage records, not biological authority truth.

## Comparison

The streaming binary is built from the FIX001 source. The retain-all diagnostic
is compiled only against frozen base commit
8c0d494f57f4594ff5acfd8e02ef546fcc387f0b and generates byte-valid records
with the same 302-taxon/601-primitive deterministic recipe. Retain-all runs are
bounded to 1,974 and 10,000 records to avoid deliberately allocating the
projected full payload at 100,000.

## Timing and cache labels

std::chrono::steady_clock measures record generation, streaming insert, and
combined finalize/validate/publish within the C++ diagnostic binding. Fresh
Rscript processes measure complete reopen validation and semantic lookups.
Medians and observed min/max are calculated only across three completed
repetitions.

PROCESS_COLD_FILE_CACHE_UNCONTROLLED means a fresh R process with no claim
about the operating-system file cache. WARM denotes repeated access in the
same process. No result is described as hardware cold.

The current finalizer remains one failure-closed operation, but monotonic
diagnostic timers separately record final I/O, temporary complete validation,
manifest preparation, the two no-replace publications plus directory sync, and
published-component complete validation. The combined finalizer time is also
recorded. Fresh-process complete validation is measured independently.

## External peak RSS

The runner samples the direct benchmark process with ps -o rss every 50 ms
and records the maximum observed KiB converted to bytes. Very short smoke cases
can complete before the first sample and are not evidence workloads. The same
method and host are used for both builders. See FIX001_PEAK_RSS_METHOD.md.

## Integrity

Every large store is a complete physical file. Header/index/footer offsets,
exact file length, first/last index entries, footer record count, full
validation, selected boundary lookup, new-process reopen, and complete-file
SHA-256 are checked. Sparse projections do not count.
