# Frozen prompt for independent Pro RECERT

Independently audit the supplied SplitAlignerR ENGINE002-FIX001A package.  Do
not treat Codex's handoff classification or green job summaries as proof.

First verify every outer sidecar, the Git bundle, exact head/tree, and complete
ancestry from ENGINE001 through ENGINE002, FIX001, and FIX001A.  Then inspect
the original ENGINE002 handoff, FIX001 handoff, frozen Pro preflight review,
FIX001A source and raw CI artifacts.

Determine whether the three mandatory R-release platforms independently pass
package build/check/tests, exact golden plan/store bytes, all 1,974 authority
plans through installed R/Rcpp bindings, lifecycle/GC/XPtr, and deterministic
cross-platform comparison.  Separately judge Windows binary/u64/no-replace
evidence and the Linux package-level ASan/UBSan boundary.  Preserve the stated
distinction between accepted FIX001 physical greater-than-4-GiB evidence and
FIX001A Windows large-offset plus bounded physical-store evidence.

Confirm that the installed-suite evidence gate does not suppress warnings and
cannot pass arbitrary warnings: only zero warnings or exactly two messages
matching the recorded base-R `scipen=-999` clamp are accepted.

Check that each portability correction is the minimum response to a preserved
hosted failure and that no scientific semantics, wire format, public API,
default engine, package version, or certified release identity changed.

Return an independent verdict with exact object IDs, artifact hashes, commands
actually rerun, per-gate results, limitations, and any blocker.  Do not create
a tag, release, merge, or source modification.
