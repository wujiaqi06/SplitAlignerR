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
them in independent R subprocesses with deterministic left-comb trees. On the
local macOS arm64 / R 4.4.2 investigation, `validate_species_tree()` completed
at 3,000 tips (depth 2,999) and first timed out at 5,000 tips under a 60-second
case limit; `align_branches()` completed at 2,000 tips (depth 1,999) and first
timed out at 3,000 tips. No crash, segfault, or graceful parser failure was
observed. Consequently Fix005 adds no speculative recursion guard. Exact
macOS, Linux, and Windows pre-tag probe outputs belong in the external Fix005
evidence; platform values not yet run must remain explicitly pending.

## Performance boundary

The reproducible `balanced-projection-v1` benchmark uses a deterministic
balanced species tree, three gene trees (full concordant, deterministic 10%
taxon deletion, and full reversed-label topology), three repetitions, and
separate file-I/O and alignment timings. Local pre-commit median alignment wall
times were approximately 0.007, 0.059, 0.127, and 0.331 seconds at 50, 200, 302,
and 500 tips, respectively. These are measurements, not extrapolations.

Runtime grows clearly faster than taxa count over this range. Measured text-file
I/O was orders of magnitude smaller than alignment time, so branch
projection/canonicalization computation, not disk I/O, is the principal V1
bottleneck in this benchmark. V1 is not optimized for thousands to tens of
thousands of taxa. Bitset replacement, split-hash redesign, descendant-tip
caching, and parallel restructuring are deferred to the V1.1 performance
backlog; Fix005 performs none of those scientific-core changes.
