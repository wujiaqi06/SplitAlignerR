# V1 release-candidate dependency contract

## R package declarations

- R >= 3.5.0
- Imports: ape, Rcpp, utils
- LinkingTo: Rcpp
- Suggests: knitr, markdown, testthat >= 3.0.0
- VignetteBuilder: knitr
- System requirement: a C++17 compiler

## Replay build and vignette closure

Release replay must probe and record the actual installed versions of every
package above and of this direct build/vignette chain:

- xfun
- litedown
- commonmark
- markdown
- knitr

In the accepted construction chain, markdown 2.0 imports litedown and xfun;
litedown 0.9 imports commonmark >= 2.0.0 and xfun >= 0.55. Therefore litedown
and commonmark are explicit replay dependencies even though SplitAlignerR does
not import their namespaces directly.

The replay preflight must finish before creating an official accepted-run
output directory. A missing tool, locale, compiler, or R package is a nonzero
failure and must not leave a directory that resembles completed evidence.
