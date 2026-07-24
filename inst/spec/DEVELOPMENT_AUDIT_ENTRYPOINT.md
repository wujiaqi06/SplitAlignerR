# SplitAlignerR V1 development audit entrypoint

Status: implementation handoff for joint audit. This document is not a release
certificate and does not authorize a V1 tag.

## Implemented boundaries

- C++17 production Newick parser, canonical unrooted primitive axis, projected
  graph grouping, empirical split recovery, and finite-double numeric policy.
- R input conversion for Newick strings/files, `phylo`, `multiPhylo`, and lists.
- Separate primitive state, primitive/composite numeric, coordinate provenance,
  diagnostics, conventions, and metadata layers.
- Pure R node-edge Catnip10 Oracle that does not call the C++ core or use splits
  to classify structural/fused states.
- Separate R fixed/free paired bookkeeping with frozen numeric promotion gates;
  it never changes a single-tree semantic state.
- Result summary, coordinate-member query, checked save/reload, and quick-start
  vignette.

## Claim-to-test entrypoints

| Claim | Evidence entrypoint |
|---|---|
| Whole-token finite-range validation; zero retained; markers unavailable; negative warning | `tests/testthat/test-core.R`, `tests/testthat/test-align.R` |
| Reference B axis and canonical split identity | `tests/testthat/test-tree-input.R` |
| Catnip10 pure R Oracle exactness | `tests/testthat/test-oracle-recompute.R` |
| Production mapper: 272/272 Catnip10 primitive cells | `tests/testthat/test-align.R` |
| Catnip10 composite members and values: 19/19 events | `tests/testthat/test-align.R` |
| Terminal, pruning, root-representation, and wrapper/core properties | `tests/testthat/test-properties.R` |
| Result provenance, summaries, and lossless schema-aware persistence | `tests/testthat/test-result.R` |
| Paired finalization, literal-`NA` round trip, and primitive-only numeric gate | `tests/testthat/test-paired.R` |
| Frozen 302-mammal legacy classes: 6,010/6,010 | `tests/testthat/test-mammal-external.R` and `EXTERNAL_REGRESSION.md` |
| Frozen 2,275-gene literal-`NA` authority: 407 cells / 189 genes / 82 internal coordinates / 202 fixed-fusion events / 0 terminal cells | `tests/testthat/test-mammal-external.R` and `EXTERNAL_REGRESSION.md` |
| Install, examples, tests, vignette rebuild, and compiled-code checks | clean source `R CMD build` plus `R CMD check --no-manual` |

The 302-mammal comparison uses the five explicit fixed/free gene-ID
intersections and never pairs rows by position. Its frozen Free label counts are
`NA=6`, `NA_fuse=141`, `NA_struct=95`, and `NA_topo=382`. Legacy cell classes
match exactly. The largest numeric absolute difference is below `1e-12` on the
fixed side and `5e-8` on the free side; the latter is the display-precision gap
between a 7-decimal expected value and the retained 10-decimal input value.

## Known limits and pending release gates

- Local clean build/check evidence currently covers macOS arm64. The configured
  GitHub Actions matrix includes macOS, Linux, and Windows, but these uncommitted
  changes have not been pushed and therefore have no remote CI evidence yet.
- The 302-mammal and 2,275-gene authorities are external. Environments without
  their documented environment variables explicitly skip only the unavailable
  regression.
- Input numeric spelling is parsed to finite double; exact lexical formatting is
  not preserved. Numeric values and semantic classes are preserved, and legacy
  character matrices use deterministic double formatting.
- Final literal `NA` is summarized as `residual_NA`; empirical FREE-tree
  conflict and adjacent-side-clade loss are not classification predicates.
- Large-production performance and memory profiling have not yet been certified.
- Release citation/version metadata, archive hashes, commit, tag, and changed
  file manifest must be frozen together after joint review.
- No independent Opus/Kimi review or Pro RECERT has been performed on this
  implementation snapshot.

## Joint-audit sequence

1. Review `V1_SCIENTIFIC_CONTRACT.md` and `conventions-v1.json` against the
   frozen Perl program and manuscripts.
2. Review C++ state logic in `src/tree_core.cpp` separately from the pure R
   Oracle in `R/oracle.R`.
3. Review paired finalize gates in `R/paired.R` against SAR-V1-SEM-003 and the
   residual-NA authority.
4. Re-run self-contained tests plus both opt-in mammal regressions from a clean
   source archive.
5. Resolve issues before creating a new frozen review package. Do not modify a
   frozen review input in place.
