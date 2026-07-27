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

The C++ Newick parser and descendant-tip traversals are recursive. Fix005 tests
them in independent R subprocesses generated as deterministic left-comb trees.
The generator starts with `(t000001:1,t000002:1):1`, repeatedly appends
`(previous,tNNNNNN:1):1`, and terminates with `;`. Dedicated clean-runner jobs
used R 4.6.1 and a 60-second classification limit per case. Windows validation
and alignment ran in separate jobs so that each operation began on a clean
runner.

| Platform | Operation | Maximum passing tips | First observed boundary |
| --- | --- | ---: | --- |
| macOS ARM64 | validation | 3,000 | not reached before alignment stopped the combined probe |
| macOS ARM64 | alignment | 2,000 | timeout at 3,000 |
| Linux X64 | validation | 1,500 | not reached before alignment stopped the combined probe |
| Linux X64 | alignment | 1,000 | timeout at 1,500 |
| Windows X64 | validation | 1,500 | timeout at 2,000 |
| Windows X64 | alignment | none | timeout at the first requested case, 50 tips |

No direct crash, segfault, unclassified nonzero exit, or graceful parser
failure was observed. The Windows alignment result is specific to the deeply
imbalanced comb topology: the same platform passed the ordinary package tests,
302-mammal and 2,275-gene authorities, and the balanced 50/200/302/500-tip
benchmark. Fix005 therefore adds no speculative recursion guard. Very deep or
highly imbalanced trees, especially on Windows, remain a documented V1
limitation; raw stdout, stderr, exit status, runner metadata, and timeout rows
belong to the external Fix005 evidence.

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
