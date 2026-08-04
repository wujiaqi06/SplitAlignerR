# ENGINE002-FIX001A runtime evidence

All measurements in this task are labelled:

```text
HOSTED-RUNNER DIAGNOSTIC - NOT A CONTROLLED CROSS-PLATFORM PERFORMANCE COMPARISON
```

Each mandatory platform records package build/check time, three full
1,974-pattern R-boundary repetitions, pure-R reference precomputation, encode,
decode, direct-view and re-encode phases, authority disk-store build/finalize,
random lookup, final store bytes, and peak RSS where the runner exposes a
reliable process value.

The per-run observations are preserved without treating operating-system
runner differences as hardware-controlled comparisons.  Medians and observed
ranges are summarized in `evidence/RUNTIME_RESULTS.csv`.

No end-to-end SplitAligner speedup claim is made by FIX001A.
