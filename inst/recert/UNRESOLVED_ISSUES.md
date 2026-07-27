# V1 release-candidate unresolved issues

## SAR-WIN-COMB-001 — Windows comb-tree alignment coverage

Status: unresolved operational observation; not a demonstrated scientific
correctness defect.

In GitHub Actions run `30267368278`, the Windows X64 alignment-only deep-tree
job ran on `Windows-2025Server-10.0.26100-SP0` with R 4.6.1 and a 60-second
per-case operational limit. Its first requested deterministic left-comb case
was 50 tips. That case timed out cleanly, so the harness-integrity status was
valid but the job supplied no passing Windows comb-tree `align_branches()` case.

The same Windows run passed the complete Catnip10, 302-mammal, 407-cell
residual-NA, and package-suite correctness gates. A separate balanced-tree
benchmark completed at 50 tips. Current evidence cannot determine whether the
comb observation is a Windows-specific hang or a pathological tree-shape
slowdown, and it does not define an unsupported input size or a maximum
capability.

Required RC3 evidence:

- sample 10, 20, 30, 40, and 50-tip comb trees in isolated process trees;
- retain raw stage markers, termination evidence, runner identity, run ID, and
  the 60-second operational limit for every attempted case;
- establish at least one passing Windows comb-tree alignment case;
- report clean timeouts as operational observations rather than crashes;
- report `harness_integrity_status` independently from
  `operation_coverage_status`.

If the 10-tip case cannot start and pass within the operational limit, the run
must stop with `INCONCLUSIVE_NO_PASSING_CASE` and return to the main console.
