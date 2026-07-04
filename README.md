# SplitAlignerR

<!-- badges: start -->
[![R-CMD-check](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml/badge.svg)](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml)
[![Codecov test coverage](https://codecov.io/gh/wujiaqi06/SplitAlignerR/graph/badge.svg)](https://app.codecov.io/gh/wujiaqi06/SplitAlignerR)
[![pkgdown](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/pkgdown.yaml/badge.svg)](https://wujiaqi06.github.io/SplitAlignerR/)
[![License: GPL-3](https://img.shields.io/badge/License-GPL--3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
<!-- badges: end -->

📖 Documentation site: <https://wujiaqi06.github.io/SplitAlignerR/>

An R implementation of **SplitAligner**, a branch-identity coordinate system for
phylogenomics under missing taxa and gene-tree discordance.

> **Status: `v0.0.1` scaffold.** This release is deliberately minimal. It ships
> the deterministic **Catnip10** 10-tip coordinate-audit benchmark expected
> oracle outputs as bundled data and a placeholder function, so the package
> installs and passes `R CMD check` / CI. The split-based branch-mapping engine
> is not implemented yet and will arrive in later versions.

## Installation

```r
# install.packages("remotes")
remotes::install_github("wujiaqi06/SplitAlignerR")
```

## What SplitAligner does

SplitAligner defines branch identity through *projected species-tree splits*
evaluated gene by gene, and decomposes branch absence into explicit accounting
categories rather than a single undifferentiated `NA`:

- `NA_struct` — a projected side disappears after taxon pruning (coverage-driven);
- `NA_fuse` — the branch is represented only through a fused/composite coordinate;
- `NA_topo` — the branch is well defined under coverage but absent from a
  discordant gene tree (topology-induced);
- residual `NA` — retained when the fixed side offers no numeric evidence.

The accounting identity is
`|C| = Mapped + NA_struct + NA_fuse + NA_topo + residual_NA`.

## Bundled data: the Catnip10 benchmark oracle

The deterministic 10-tip benchmark (random R/APE topology, seed 42; fixed branch
lengths; no rate shift, discordance, or estimation error) is used to validate
coordinate behaviour under taxon pruning against an independent graph-theoretic
oracle. Its expected outputs on the unrooted primitive axis (17 coordinates:
terminals `t1`–`t10`, internals `N_12`–`N_18`) are bundled:

```r
library(SplitAlignerR)

splitalignerR_scaffold()

# expected gene-by-branch matrix for the global (outgroup-first) regime
head(catnip10_expected("global"))

# full bundled object (both deletion regimes, status-long, fusion groups, tree)
str(catnip10_oracle, max.level = 2)
```

Because the benchmark contains no discordance by design, `NA_topo` never arises
in it — it isolates `NA_struct` and `NA_fuse` cleanly.

## Citation

If you use SplitAlignerR, please cite the SplitAligner preprint (a software DOI
will be added at the first tagged release):

> Wu J. (2026). *SplitAligner: A Gene-Species Tree Reconciliation Framework
> Using Split-Based Branch Mapping.* bioRxiv.
> <https://doi.org/10.64898/2026.02.24.707838>

See [`CITATION.cff`](CITATION.cff) and `citation("SplitAlignerR")`.

## License

GPL-3. See [LICENSE.md](LICENSE.md).
