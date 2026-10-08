# V1 release-candidate known limitations

- SAR-ARCH-001 — DEFER TO FUTURE VERSION: the production C++ implementation is
  coupled to Rcpp. Shared-core extraction and a stable C ABI are outside V1.
- Python bindings are outside V1.
- Gene-tree inference, branch-length estimation, La Terra, GBI/Log-GBI,
  LASSO, PCA/SVD, downstream analysis, and GUI work are outside V1.
- Graph state, recovery, numeric evidence, and paired-finalization layers remain
  separate. residual_NA is only the summary name for finalized literal NA.
- `finalized_perl_matrices_are_authoritative` deliberately names the frozen
  SplitAligner Perl reference implementation. SplitAlignerR does not require
  Perl at runtime.
- A release-candidate tag is not independent RECERT and is not final release
  approval. Platform items not run must be reported as NOT RUN, FAILED, or
  BLOCKED BY ENVIRONMENT.

## Recursive depth boundary

The C++ Newick parser and descendant-tip traversals are recursive. Fix005A tests
them in independent R subprocess trees generated as deterministic left-comb trees.
The generator starts with `(t000001:1,t000002:1):1`, repeatedly appends
`(previous,tNNNNNN:1):1`, and terminates with `;`. Dedicated clean-runner jobs
use a 60-second operational limit per case. On Unix, every case starts in a new
session and timeout termination kills its process group. On Windows, an
anchored new process group is terminated with `taskkill /PID /T /F`. Evidence
is accepted only when process-tree termination is confirmed, output pipes are
closed, and timeout stdout contains no late `case_status`.

The earlier Fix005 Windows timeout classifications are rejected because the
outer process timed out while a descendant R process continued and eventually
printed `case_status: PASS`. They are not recursion or performance boundaries.
Fix005A reruns all four dedicated platform jobs with the corrected harness;
exact tested maxima and 60-second operational-limit cases belong to the
external review evidence. A timeout means only that the case did not complete
within that operational limit, not that the input crashes or can never finish.
No speculative recursion guard is added unless the corrected probe observes a
direct crash or segmentation fault.

### RC2 Windows comb-tree alignment observation

GitHub Actions run `30267368278`, on the Windows X64 runner
`Windows-2025Server-10.0.26100-SP0` with R 4.6.1, used a 60-second operational
limit per isolated case. Its alignment-only deterministic left-comb probe began
at 50 tips, and that first case exceeded the limit. The harness confirmed
process-tree termination, closed output streams, and no late `case_status`, but
the run therefore contains no passing Windows comb-tree `align_branches()` data
point.

The same run's ordinary Windows package and authority jobs passed Catnip10, the
302-mammal regression, the 407-cell residual-NA authority, and the package test
suite. Its balanced-tree performance benchmark also completed the 50-tip case,
whereas the 50-tip comb-tree alignment case timed out. Existing evidence does
not reconcile those observations and cannot distinguish a Windows-specific
hang from a pathological tree-shape slowdown.

FIX006 changed the Windows comb-tree alignment sampling to 10, 20, 30, 40, and
50 tips. In GitHub Actions run `30314598409`, the first 10-tip case still did
not complete within 60 seconds. Process-tree termination was confirmed, but no
passing Windows comb-tree alignment point was established. A clean timeout
demonstrates harness integrity only; operation coverage is reported separately
and remains `INCONCLUSIVE_NO_PASSING_CASE` when no case passes. Deep-tree maxima
and timeout boundaries are runner-load-sensitive observations, not stable
capability limits.

FIX006A adds a bounded 10-tip cold-start diagnosis rather than another deep-tree
scan. Each numeric validation, fixed/free alignment, no-length control,
wrapper/core boundary, and standalone C++ microprobe case runs in a fresh
process tree with a 900-second operational limit. The diagnostic evidence is
external to this source document and must not be converted into a capability
claim without its run ID, raw stage markers, and timing records.

That run established only that standalone-executable numeric/regex operations
were fast. The R-hosted package numeric path remained unresolved. FIX007 uses a
separate `R CMD SHLIB` diagnostic DLL and fresh `Rscript` processes to isolate
the R-to-DLL baseline, `strtod`, marker initialization, automatic/static regex,
the frozen numeric function, and package Rcpp boundaries. The diagnostic DLL
is not installed with the package and is not a supported runtime component.
Windows R 4.6.1 hosted attempts showed that both category-specific and combined
R-level locale queries could terminate the process before D1. FIX007 therefore
records effective locale categories through an additional fresh-process bare-C
control; this control is not part of the A/B/C numeric trigger and cannot warm
the separately launched D1-D7 processes.

Windows run `30346950266` then satisfied the authorized A trigger: noop,
`strtod`, and the frozen marker path passed; automatic and function-local
static regex plus the frozen numeric function timed out after their first-call
markers; package core-info passed while the public numeric validator timed out.
The conditional FIX007 change replaces only the decimal grammar regex with an
ASCII cursor parser. The runtime-size/performance observations remain specific
to the recorded runner and do not alter any scientific capability boundary.

## Session-option portability boundary

R versions may constrain the range accepted by `options(scipen=...)`. Hosted R
4.6.1 in run `30314598409` replaced requested `-999` with effective `-9` and
emitted a warning. Consequently, exact `scipen=-999` execution is not a portable
three-platform requirement. FIX006A requires the portable matrix `-9`, `0`, and
`999`, records requested and effective values separately, and treats `-999` as
an optional extreme probe. A clamped extreme is reported as
`NOT_AVAILABLE_CLAMPED_TO_<effective>` rather than PASS for the requested value.
Clamp warnings remain visible in raw RECERT logs and are also copied into the
tabular evidence.

## Performance boundary

The reproducible `balanced-projection-v1` benchmark uses a deterministic
balanced species tree, three gene trees (full concordant, deterministic 10%
taxon deletion, and full reversed-label topology), three repetitions, and
separate file-I/O and alignment timings. Hosted median alignment wall times at
50/200/302/500 tips were 0.012/0.080/0.184/0.405 seconds on macOS ARM64,
0.013/0.111/0.244/0.657 seconds on Linux X64, and
0.020/0.130/0.300/0.800 seconds on Windows X64. These are measurements, not
extrapolations.

Runtime grows clearly faster than taxa count over this range. Measured text-file
I/O was orders of magnitude smaller than alignment time, so branch
projection/canonicalization computation, not disk I/O, is the principal V1
bottleneck in this benchmark. V1 is not optimized for thousands to tens of
thousands of taxa. Bitset replacement, split-hash redesign, descendant-tip
caching, and parallel restructuring are deferred to the V1.1 performance
backlog; Fix005 performs none of those scientific-core changes.
