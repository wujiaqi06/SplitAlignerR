# FIX001 peak RSS method

The benchmark runner starts one direct Rscript or standalone C++ benchmark
process and samples:

    ps -o rss= -p PID

every 50 ms until process exit. The largest reported KiB value is multiplied
by 1,024 and recorded as peak_rss_bytes. The benchmark must run outside the
Codex filesystem/process sandbox because sandboxed ps is denied on this host;
the approved run writes only disposable stores and result text under
/private/tmp.

This is an external sampled peak, not allocator instrumentation. It can miss a
spike shorter than 50 ms, includes the runtime and benchmark harness, and does
not distinguish anonymous heap from mapped pages. It is suitable for the
controlled same-host old/new comparison and is not presented as an exact heap
profile. Very short smoke runs that completed before the first successful
sample were discarded.

macOS /usr/bin/time -l was attempted for the real 1,974 authority process, but
its final system query was denied in the sandbox. That attempt is retained as a
functional authority run only; it is not used as RSS evidence.
