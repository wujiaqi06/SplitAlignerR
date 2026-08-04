# ENGINE002-FIX001A R-boundary evidence

The mandatory platform workflow installs the source archive with tests, runs
the complete installed testthat suite, and then exercises ENGINE002 through
the installed package's internal R/Rcpp bindings.  The authority reference is
the frozen SplitAligner commit `1aea990946e08d13349bc6a164dc7334d61cae08`.

The 1,974-pattern gate checks, for every pattern and on every mandatory
platform:

- retained taxa;
- primitive truth state;
- eligible coordinates and projected queries;
- fibers, composite primitive-member sets, and composite queries;
- encode/decode/re-encode exact bytes and direct-view equality;
- the terminal invariant.

Lifecycle coverage includes active pins, busy-close rejection, release,
ordinary and repeated close, read after close, finalizer/GC churn, completed
disk-store reopen in the same and a fresh R process, wrong-authority rejection,
corruption rejection, and missing or unvalidated manifest rejection.

The installed-suite runner accepts either no warning (when that R runtime can
apply `scipen=-999` exactly) or exactly two visible base-R clamp warnings whose
messages match the frozen `scipen=-999` boundary.  Any other warning count or
message is fatal; the clamp warnings are recorded, not suppressed.

The final normalized results are in `evidence/R_BOUNDARY_RESULTS.txt` and
`evidence/AUTHORITY_1974_COMPARISON.txt`.  Raw per-platform logs, session data,
and hashes remain attached to the final GitHub Actions run and are copied into
the external handoff package.

No public export or default engine is introduced by this evidence task.
