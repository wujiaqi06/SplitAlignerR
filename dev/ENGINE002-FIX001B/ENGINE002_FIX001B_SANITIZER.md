# ENGINE002-FIX001B sanitizer replay

Final workflow:

```text
run: 30890940707
job: 91932591013
head: 9588400014a65170bc7dbb718817d9f258237f9d
conclusion: SUCCESS
```

The package shared library was installed and exercised through the R/Rcpp
boundary under AddressSanitizer and UndefinedBehaviorSanitizer.  Leak detection
was disabled because the host R executable itself is not sanitizer-built;
address and undefined-behavior diagnostics remained fatal.

Recorded gates:

```text
codec: PASS
direct view: PASS
memory store: PASS
streaming disk builder: PASS
disk reopen: PASS
LRU and oversized scratch: PASS
fault cleanup: PASS
incremental SHA and targeted aggregate: PASS
constant-fast-hash collision path: PASS
XPtr finalizer/GC: PASS
close and read-after-close: PASS
```

A separately compiled sanitizer SHA probe also passed all 15 fixed-vector
forms, all 34,191 two-part cases, and a 100-case multipart sanitizer subset
against Python `hashlib`, with zero mismatch.  The full 10,000-case multipart
gate is mandatory on each release-platform job rather than repeated under the
slower sanitizer runner.

Classification: `PASS` for the required package/R-boundary sanitizer gate.
