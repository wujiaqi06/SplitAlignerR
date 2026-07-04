# SplitAlignerR

<!-- badges: start -->
[![R-CMD-check](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml/badge.svg)](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml)
[![Codecov test coverage](https://codecov.io/gh/wujiaqi06/SplitAlignerR/graph/badge.svg)](https://app.codecov.io/gh/wujiaqi06/SplitAlignerR)
[![pkgdown](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/pkgdown.yaml/badge.svg)](https://wujiaqi06.github.io/SplitAlignerR/)
[![License: GPL-3](https://img.shields.io/badge/License-GPL--3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
<!-- badges: end -->

SplitAlignerR is the R reference implementation track for the SplitAligner
branch-coordinate framework. The current release provides the Catnip10
graph-oracle benchmark as an executable, audit-ready R package: users can load
the frozen primitive branch axis, inspect oracle cell states, recover
fused-coordinate membership, and validate the benchmark accounting identities.

The split-based empirical gene-tree mapping engine is under active development.

Documentation site: <https://wujiaqi06.github.io/SplitAlignerR/>

## Installation

```r
# install.packages("remotes")
remotes::install_github("wujiaqi06/SplitAlignerR")
```

## Minimal Example

```r
library(SplitAlignerR)

catnip10_expected()
catnip10_summary_counts()
validate_catnip10_oracle()
```

## Current Scope

This seed release focuses on the bundled Catnip10 graph-oracle benchmark and
branch-coordinate ledger accessors. It includes:

- `catnip10_expected()` / `catnip10_matrix()` for the wide primitive-coordinate
  oracle matrix;
- `catnip10_summary_counts()` for per-regime status accounting;
- `catnip10_fusion_groups()` for graph-oracle fused-coordinate membership;
- `validate_catnip10_oracle()` for deterministic seed-release sanity checks;
- `catnip10_oracle`, the bundled data object containing the frozen species tree,
  branch-label crosswalk, per-cell oracle states, and fusion groups.

The Catnip10 benchmark is discordance-free by design. It is intended to exercise
the graph-defined `observed`, `NA_fuse`, and `NA_struct` ledger states under
taxon pruning. `NA_topo` is not expected in this benchmark because empirical
gene-tree discordance is outside the Catnip10 oracle fixture.

## Not Yet Implemented

SplitAlignerR does not yet implement the full split-based empirical gene-tree
mapping engine. The `align_branches()` function is currently an interface
preview that stops with a clear not-implemented message.

This package should be cited and used as an initial benchmark/oracle-ledger
release, not as a complete replacement for the Perl SplitAligner implementation.

## Citation

If you use SplitAlignerR, please cite the SplitAligner preprint. A software DOI
will be added after a tagged release with clean metadata and tests.

> Wu J. (2026). *SplitAligner: Branch-Identity Coordinate System for
> Phylogenomics under Missing Taxa and Gene-Tree Discordance.* bioRxiv.
> <https://doi.org/10.64898/2026.02.24.707838>

See [`CITATION.cff`](CITATION.cff) and `citation("SplitAlignerR")`.

## License

GPL-3. See [LICENSE.md](LICENSE.md).
