# ENGINE002-FIX001A Windows evidence

## Hosted defects found and corrected

The first hosted run failed while compiling the production package because
MinGW did not expose `_S_IREAD` and `_S_IWRITE` without `<sys/stat.h>`.  The
correction only adds that system header under `_WIN32`.

The next run compiled, built, and checked the package, then failed when the
disk-store path guard walked a Windows absolute path from an empty path.  That
made the first inspected component drive-relative (`D:`) instead of the drive
root (`D:\\`).  The follow-up correction seeds the walk with
`absolute.root_path()` and visits `absolute.relative_path()` components.

Both were genuine hosted portability failures.  They are isolated from the CI
and evidence changes and were followed by a complete mandatory replay.  The
failed run URLs and their disposition are preserved in
`evidence/CI_RUN_URLS.txt`; no failing gate was skipped or weakened.

## Final Windows gate

The final run must demonstrate exact binary golden plan/store bytes, no CRLF
transformation, u64 arithmetic above 4 GiB, no `long` truncation, actual
bounded disk construction/reopen and last-record lookup, no-replace
publication, pre-existing destination rejection, and preservation of the
original destination bytes.

FIX001A does not claim a physical Windows store above 4 GiB.  The physical
greater-than-2-GiB and greater-than-4-GiB evidence remains the accepted FIX001
macOS evidence.  Windows provides independent large-offset interpretation and
a bounded physical store run.

See `evidence/WINDOWS_OFFSET_ATOMICITY_RESULTS.txt` and the final Windows raw
artifact for exact measured values.
