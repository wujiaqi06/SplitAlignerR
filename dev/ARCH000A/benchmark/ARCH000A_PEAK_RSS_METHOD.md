# ARCH000A peak-RSS method

Each final benchmark case executes in a fresh R process. A second R process
uses the ps package to poll the exact target PID every 0.020 seconds:

    ps::ps_memory_info(ps::ps_handle(pid))[["rss"]]

The monitor records the maximum sampled RSS, number of successful samples,
poll interval and monitor wall time. It begins immediately after the target is
spawned and ends when that PID is no longer running.

The resulting peak_rss_bytes column is a sampled OS RSS maximum. It is not
object.size, an R allocation total, or a kernel-maintained high-water mark.
Shorter spikes between samples may be missed. Evidence therefore calls it
sampled peak RSS and retains each raw monitor record.

BSD time with the -l flag was attempted first. The managed sandbox denied its
kern.clockrate query and returned no maximum-resident-set value. That failed
attempt is not promoted to evidence. The unprivileged ps monitor is the
documented, read-only alternative.

The 20 ms interval produced thousands of observations for authority and stress
cases. Cache, registry, B-star, matrix/sink and temporary-disk component sizes
are reported separately for attribution; they are not added together and
called peak RSS.

Projected 500,000-locus rows never project peak RSS.
