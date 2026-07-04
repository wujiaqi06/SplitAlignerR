# Changelog

## SplitAlignerR 0.0.2

- Prepared the package as a public seed release for the SplitAligner R
  reference implementation track.
- Reframed the README and package metadata around bundled Catnip10
  graph-oracle benchmark data, audit-ready accessors, and validation
  helpers.
- Added
  [`catnip10_summary_counts()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_summary_counts.md),
  [`validate_catnip10_oracle()`](https://wujiaqi06.github.io/SplitAlignerR/reference/validate_catnip10_oracle.md),
  [`catnip10_fusion_groups()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_fusion_groups.md),
  and
  [`catnip10_matrix()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_matrix.md).
- Removed placeholder software DOI metadata and private local paths from
  public-facing source files.

## SplitAlignerR 0.0.1

- Initial package scaffold (`v0.0.1-scaffold`).
- Bundled the deterministic Catnip10 10-tip coordinate-audit benchmark
  expected oracle outputs (unrooted axis, both the global and local
  deletion regimes) as the `catnip10_oracle` data set, with the
  [`catnip10_expected()`](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_expected.md)
  accessor.
- Added
  [`splitalignerR_scaffold()`](https://wujiaqi06.github.io/SplitAlignerR/reference/splitalignerR_scaffold.md)
  placeholder so the package installs and passes `R CMD check`.
- Set up GitHub Actions `R-CMD-check` continuous integration.
- The split-based branch-mapping engine is not implemented yet.
