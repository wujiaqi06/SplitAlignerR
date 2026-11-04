# Fast-core development dependency contract

## R package declarations

- R >= 3.5.0 (declared runtime minimum; not a new validation claim)
- Imports: ape, digest, Rcpp, utils
- LinkingTo: Rcpp
- Suggests: jsonlite, knitr, markdown, testthat >= 3.1.7
- VignetteBuilder: knitr
- System requirement: a C++17 compiler

The restored historical suite uses `local_mocked_bindings()`, introduced in
testthat 3.1.7. Its testing requirement is stricter than the earlier declared
minimum of 3.0.0. Test execution also requires an R version supported by the
selected testthat release and its complete dependency closure. The runtime
minimum alone does not certify that closure on every R version.

## Build and vignette dependency closure

The quick-start vignette uses the `knitr::knitr` engine. Record the actual
versions and sources of knitr, markdown, and every transitive build dependency,
as well as all runtime and test dependencies. Rmarkdown is not directly used
by this vignette. Use the isolated, pinned dependency set selected for the
current validation stage; do not silently upgrade the user's default library.

The historical construction record used markdown 2.0, which imports litedown
and xfun; litedown 0.9 imports commonmark >= 2.0.0 and xfun >= 0.55. Those
versions describe that earlier environment. They are not an instruction to
install the same chain into a different R runtime. The current stage must
record the closure actually selected and whether it supports that runtime.

Dependency preflight precedes the validation run. Missing tools, compiler,
locale, or required packages are failures, not successful test evidence.
External mammal regressions retain their explicit fixture-dependent skips.
See `tests/README.md` and `tests/SOURCE_PROVENANCE.json` in the source package
for the restored test suite's origin and coverage boundary.
