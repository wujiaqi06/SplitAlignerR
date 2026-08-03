# ENGINE001 peak RSS method

Each packed-schema or matrix-layout case ran in a fresh R process. A separate
monitor process used the `ps` R package to sample that target process's resident
set size every 0.02 seconds.

Reported `peak_rss_bytes` is the maximum sampled OS RSS. It is not
`object.size()`, a sum of R objects, or a kernel-guaranteed high-water mark.

The monitor files record target PID, interval, sample count, observed peak and
monitor wall time. Startup/runtime overhead, prototype objects and allocator
behavior are included. Child processes are not expected in the R layout cases.

Matrix files were created one case at a time and deleted after metrics were
captured. `logical_file_bytes` is the exact combined component-file length,
including the prototype header/footer allowance. It is distinct from physical
filesystem allocation and peak RSS.

The 100,000 x 4,913 cases intentionally did not materialize a 4.42 GB logical
result into R because it exceeded the 1 GiB prototype materialization gate. That
status is recorded as `NOT_ATTEMPTED_PLANNER_LIMIT`, not as a measured time.
