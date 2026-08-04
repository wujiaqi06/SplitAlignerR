# ENGINE002-FIX001A sanitizer evidence

The dedicated Linux job compiles and links the installed package shared
library with AddressSanitizer and UndefinedBehaviorSanitizer, preloads both
runtimes, and runs the ENGINE002 codec, direct-view, memory-store, streaming
disk-store, disk-reopen, LRU/scratch, fault-cleanup, collision, XPtr/finalizer,
GC, and close/read-after-close tests through R and Rcpp.

The exact build flags and runtime variables are recorded in the uploaded
`sanitizer_environment.txt`.  Address and undefined-behavior findings are
fatal.  Leak detection is explicitly disabled because the host R executable
is not itself sanitizer-built; this limitation is not represented as a leak
check.

The normalized outcome is in `evidence/SANITIZER_RESULTS.txt`.  This is
package-level R-boundary evidence, not a relabelled standalone C++ harness.
