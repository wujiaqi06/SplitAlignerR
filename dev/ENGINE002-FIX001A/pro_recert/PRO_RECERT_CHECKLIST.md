# Independent Pro RECERT checklist

- Verify every external SHA-256 sidecar before unpacking.
- Clone the FIX001A bundle and verify the advertised head, tree, and ancestry.
- Confirm FIX001A starts at exact accepted FIX001 commit `94b45820...`.
- Confirm all production corrections are minimal, independently committed,
  and tied to preserved hosted failures.
- Confirm no public export, default engine, DESCRIPTION, scientific state,
  wire schema, mapper, authority, or certified-release identity changed.
- Verify the final mandatory Linux, macOS, and Windows jobs succeeded.
- Verify package build/check, installed testthat, and ENGINE002 tests.
- Verify the installed-test runner accepts only zero warnings or the exact two
  visible `scipen=-999` clamp warnings and fails every other warning set.
- Independently compare golden plan, store component, and manifest bytes.
- Independently compare the 1,974 authority record/store hashes.
- Inspect R lifecycle, XPtr/GC, fresh-process reopen, and corruption gates.
- Inspect Windows binary, u64, bounded physical-store, and no-replace evidence.
- Inspect the Linux package/Rcpp ASan+UBSan logs and stated leak limitation.
- Reconcile runtime and RSS claims with raw artifacts; do not compare hosted
  runners as controlled hardware.
- Issue an independent PASS/INCOMPLETE/FAIL decision; do not inherit the
  construction-side classification without verification.
