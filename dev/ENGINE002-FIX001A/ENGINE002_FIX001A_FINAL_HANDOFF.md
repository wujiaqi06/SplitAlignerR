# ENGINE002-FIX001A final handoff

## Classification

`ENGINE002_FIX001A_PASS`

This task closes the cross-platform and installed R/Rcpp evidence gap for the
accepted ENGINE002-FIX001 implementation.  It does not begin ENGINE003.

## Frozen starting identity

```text
branch: engine002-fix001a-cross-platform-evidence
base commit: 94b45820b811e95ce29c9a9c062cbf8e8bbfbbdf
base tree: 5c54821018de8f3a03d67e319c23eeceb46488d8
certified v0.1.0 peeled commit: 17a0927095c7a067817bf598a2556cbe7348a6d0
```

The exact final evidence commit and tree are recorded after commit creation in
the external handoff manifest and complete Git bundle.

## Commit discipline

1. `3b8ade3` — `FIX001A-CI`: workflow, evidence scripts, platform tests, and
   initial scope documents; no production source change.
2. `af933a5` — `FIX001A-PORTABILITY`: MinGW system-header correction and
   portable R temporary paths; test runner records expected option warnings
   without treating them as failures.
3. `c1b146a` — `FIX001A-PORTABILITY-FOLLOWUP`: Windows absolute-path traversal
   begins at the complete drive root.  A separate follow-up was necessary
   because this second genuine hosted failure appeared only after commit 2
   allowed package compilation to complete.  Neither earlier commit was
   amended.
4. `98e16d2` — `FIX001A-CI-FOLLOWUP`: completes the explicitly required
   memory-store build/finalize and disk-store reopen timing fields.  This is an
   evidence-script-only correction found by final contract reconciliation;
   production source is unchanged.
5. `086fad1` — `FIX001A-CI-FOLLOWUP`: permits only zero warnings or the exact
   two visible `scipen=-999` clamp warnings; every other warning remains fatal.
6. `FIX001A-EVIDENCE` — ordinary final evidence commit containing this handoff.

## Hosted failure disposition

Run `30872697932` exposed the missing MinGW system declaration, expected
`scipen=-999` clamp warning classification, and nonportable test-only
`/private/tmp` paths.  Run `30873020835` proved that compilation/check advanced
past those failures and then exposed the drive-root traversal defect.  Both
runs were preserved and classified before the corresponding narrow patches.
Run `30873484912` then passed every platform gate but was retained only as an
interim replay because final contract reconciliation found incomplete phase
timings.  Run `30875077996` was cancelled when self-audit found that the custom
installed-suite runner accepted arbitrary warnings.  The final strict replay,
`30875359482` at commit `086fad1b752d90819183d54ee6e9885439e06dc2`,
completed every mandatory and advisory job successfully with the exact warning
allowlist.  All run dispositions are listed in `evidence/CI_RUN_URLS.txt`.

## Final gates

The authoritative per-gate outcomes are frozen in the normalized evidence
files and their `SHA256SUMS`.  Raw build/check/test, platform, session,
compiler, sanitizer, byte, and runtime artifacts are preserved with the final
workflow run and copied into the external handoff.

No bytes are normalized before deterministic comparison.  No mandatory test
is skipped to obtain a green run.  Linux R-devel is advisory; all three R
release platforms are mandatory.

The final mandatory results are:

```text
Linux R release package/check/tests: PASS
macOS R release package/check/tests: PASS
Windows R release package/check/tests: PASS
three-platform golden plan bytes: PASS
three-platform golden store bytes: PASS
three-platform 1,974 authority: PASS
three-platform R lifecycle: PASS
Windows u64/binary/no-replace: PASS
package-level Rcpp ASan/UBSan: PASS
mandatory skips: 0
```

## Scope boundary

Production changes are limited to Windows compilation and absolute-path
inspection.  Scientific truth states, plan/store wire schemas, authority,
existing mapper behavior, public exports, default engine, `DESCRIPTION`,
release metadata, and certified `v0.1.0` are unchanged.

Runtime evidence is diagnostic only and is not a controlled cross-platform
performance comparison.  Windows does not claim a physical greater-than-4-GiB
store; that accepted evidence remains in FIX001.

## Independent review

The `pro_recert/` prompt and checklist prepare an independent review object but
do not answer it.  Pro must verify the exact Git objects, external sidecars,
raw artifacts, deterministic hashes, authority, lifecycle, Windows, and
sanitizer evidence before issuing its own verdict.
