# V1 release-candidate unresolved issues

## SAR-WIN-COMB-001 — Windows comb-tree alignment coverage

Status: unresolved operational observation; not a demonstrated scientific
correctness defect.

In GitHub Actions run `30267368278`, the Windows X64 alignment-only deep-tree
job ran on `Windows-2025Server-10.0.26100-SP0` with R 4.6.1 and a 60-second
per-case operational limit. Its first requested deterministic left-comb case
was 50 tips. That case timed out cleanly. FIX006 then sampled from 10 tips in
run `30314598409`; the fresh 10-tip alignment also exceeded 60 seconds. Both
runs preserved valid harness evidence but supplied no passing Windows comb-tree
`align_branches()` case.

The same Windows run passed the complete Catnip10, 302-mammal, 407-cell
residual-NA, and package-suite correctness gates. A separate balanced-tree
benchmark completed at 50 tips. Current evidence cannot determine whether the
comb observation is a Windows-specific hang or a pathological tree-shape
slowdown, and it does not define an unsupported input size or a maximum
capability.

FIX006A run `30331386645` rejected only the standalone-executable regex
cold-start hypothesis: direct `validate_numeric_token("1")` and explicit
`std::regex` construction completed in milliseconds. It did not resolve the
R-hosted package/DLL numeric path. The fresh public R validator stopped after
`NUMERIC_FIRST_CALL_STARTED` for 900 seconds, and branch-length alignment cases
also reached that bound, while the identical no-length comb control passed.

The FIX006A evidence producer additionally parsed Windows CRLF without first
normalizing line endings. Raw stdout remained available, but derived last-stage
and timing tables were wrong and the independent verifier correctly failed.
The precise accepted conclusion boundary is therefore:

```text
Standalone-executable regex cold-start hypothesis rejected.
R-hosted package/DLL numeric path remains unresolved.
```

FIX007 first repairs that evidence path, then builds a diagnostic DLL using
`R CMD SHLIB` and runs fresh-process `.Call()` probes for noop, `strtod`, the
frozen marker path, automatic/static regex, frozen numeric policy, and package
Rcpp boundaries. Package C++ source may change only if those hosted results
satisfy the separately authorized A/B trigger. Otherwise construction stops
without guessing a core cause.

Status update: Windows run `30346950266` satisfied trigger A. Noop, `strtod`,
marker, and package core-info controls passed; both hosted regex controls, the
frozen validator, and the public package validator timed out after their first
call started. The task therefore authorized the narrow manual decimal-parser
replacement. Post-fix remediation, 60-second release-gate, and three-platform
authority evidence remain external review-package evidence rather than claims
established by this historical pre-fix observation.

## SAR-OPTION-EFFECTIVE-001 — requested versus effective session options

Status: evidence policy corrected in FIX006A; three-platform replay accepted.

FIX006 recorded requested `scipen` values but did not record the value returned
by `getOption("scipen")`. Hosted R 4.6.1 clamped `-999` to `-9`, so the former
aggregate PASS could not prove exact `-999` coverage. FIX006A uses `-9`, `0`,
and `999` as the mandatory portable matrix and records requested/effective
OutDec and scipen, warning text, exact-application status, and case status.
`-999` remains an optional extreme boundary and may truthfully report
`NOT_AVAILABLE_CLAMPED_TO_<effective>`.
