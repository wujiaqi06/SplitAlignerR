# Historical regression-suite provenance

The 11 `testthat/test-*.R` files (76 `test_that` blocks), one fixture,
`testthat.R` entry point, and `vignettes/quick-start.Rmd` were restored from
SplitAlignerR commit `e847dd0cc4bc8026cd75a34d2ca75be1b4fe0771`
(version 0.1.0.9000). Each original byte sequence was verified against its
Git blob before restoration. `SOURCE_PROVENANCE.json` records the original
SHA256 values and identifies every adapted test file.

The authoritative 0.1.0.9002 tar archive, SHA256
`c4fcc16cce3aaf90189a686b57dd0eadba2d20fccfd246d42deeef353f83522f`,
and release commit `d3d212d847fc3526bee2077c32d8e1e0141e3dce` contain no
tests or vignettes. The restored suite is not represented as a recovered
complete 9002 suite. Its original scientific, numeric, oracle, input/error,
and persistence expectations are retained.

For 0.1.0.9004, only package/core/development metadata assertions were adapted in
`test-core.R` and `test-release-metadata.R` for package 0.1.0.9004 and
core 0.2.0-fast-abi2. The existing core metadata block additionally verifies
the backend name, ABI, and exact source commit. No runtime version is mocked.
The original 76 test blocks remain present.

The suite exercises the public alignment, tree validation, numeric policy,
independent Catnip10 oracle, result provenance/persistence, fixed/free paired
finalizer, and session-option invariance contracts. It contains no exchange
or ENGINE002 storage tests. Exchange compatibility was tested separately in
the earlier scoped 0.1.0.9003 validation. That earlier evidence
does not qualify the current candidate automatically.

The two external mammal tests keep their original opt-in environment variables
and fixture requirements. Source-only oracle and public-metadata checks keep
their explicit missing-source skips. Record all actual skips with their
reasons; successful execution does not imply coverage of a skipped test.

Testthat >= 3.1.7 is required because the suite uses
`local_mocked_bindings()`. The quick-start vignette uses `knitr::knitr`.

## New Fast-adapter tests

`testthat/test-fast-adapter.R` is a separate addition to version 0.1.0.9004 with seven
new test blocks. It is not part of the 11 restored historical test files or
their 76 blocks. It covers byte-key deduplication against the frozen scalar
algorithm; empty, repeated, named, missing, invalid-byte and mixed-encoding
inputs and classed/dimensional fallback; complete result encoding restoration and its malformed/unknown-ID
rejections; exact Fast backend identity and tamper/missing rejection even with
`check_version = FALSE`; and the public result display/summary identity.

The scalar algorithm intentionally distinguishes byte-different UTF-8 and
latin1 representations. It also historically maps `NA_character_` to the key
for literal `NA`. The differential tests preserve that internal behavior while
separately checking that a missing matrix-axis ID is rejected. Public missing
gene-ID rejection remains covered by the historical tests. This optimization
does not redefine which malformed native outputs the original helper accepted.

Long coverage-cache eviction and gctorture cases remain in the separate
0.1.0.9003 stress suite; they are not duplicated by this bounded package
test file. No passing result is asserted by adding these source tests.

## Layered fusion groups

Version 0.1.0.9005 tests the Figure 4 three-gene example and edge cases in
`testthat/test-fusion-groups.R`. Frozen comparisons in the original paired
tests and external mammal tests explicitly select `rule = "legacy"`.
