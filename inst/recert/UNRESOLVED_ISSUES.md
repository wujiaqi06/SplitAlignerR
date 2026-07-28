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

Required FIX006A diagnosis before any RC3 decision:

- run only the 10-tip comb topology with a 900-second operational limit;
- compare first and second numeric validation calls in one fresh process;
- compare fixed alignment without and after numeric-policy pre-warm;
- run no-length and free-mode controls in their own fresh processes;
- time wrapper conversion and direct `cpp_align_branches()` boundaries;
- compile, without modifying package C++ source, a standalone microprobe for
  `validate_numeric_token("1")` and explicit `std::regex` construction;
- retain all raw stage markers, timings, process-tree termination evidence,
  compiler command/output, runner identity, and run ID.

If the numeric-regex cold-start pattern is independently reproduced, source
construction stops with `ROOT CAUSE CONFIRMED`; replacing the parser requires a
separate Fix007 authority. If it is not reproduced, the handoff reports only
the last completed stages and timings without guessing another cause.

## SAR-OPTION-EFFECTIVE-001 — requested versus effective session options

Status: evidence policy corrected in FIX006A; hosted replay pending.

FIX006 recorded requested `scipen` values but did not record the value returned
by `getOption("scipen")`. Hosted R 4.6.1 clamped `-999` to `-9`, so the former
aggregate PASS could not prove exact `-999` coverage. FIX006A uses `-9`, `0`,
and `999` as the mandatory portable matrix and records requested/effective
OutDec and scipen, warning text, exact-application status, and case status.
`-999` remains an optional extreme boundary and may truthfully report
`NOT_AVAILABLE_CLAMPED_TO_<effective>`.
