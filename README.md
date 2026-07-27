# SplitAlignerR

<!-- badges: start -->
[![R-CMD-check](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml/badge.svg)](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml)
[![Codecov test coverage](https://codecov.io/gh/wujiaqi06/SplitAlignerR/graph/badge.svg)](https://app.codecov.io/gh/wujiaqi06/SplitAlignerR)
[![pkgdown](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/pkgdown.yaml/badge.svg)](https://wujiaqi06.github.io/SplitAlignerR/)
[![License: GPL-3](https://img.shields.io/badge/License-GPL--3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
<!-- badges: end -->

SplitAlignerR is the R interface and independent benchmark track for the
SplitAligner branch-coordinate framework. Package version 0.1.0 is the V1
release-candidate line. The frozen `v0.1.0-rc1` tag is retained as an abandoned
first candidate; this Fix005 source is the controlled pre-tag candidate for
`v0.1.0-rc2`. It provides a
production C++17 graph-first mapper, strict finite-range branch-length
validation, and a pure R node-edge implementation that independently recomputes
the Catnip10 graph-oracle benchmark. The candidate is not a final release
certificate; independent RECERT remains pending.

Documentation site: <https://wujiaqi06.github.io/SplitAlignerR/>

## Installation

```r
# install.packages("remotes")
remotes::install_github("wujiaqi06/SplitAlignerR")

# After the annotated RC2 tag is published:
remotes::install_github("wujiaqi06/SplitAlignerR@v0.1.0-rc2")
```

## Minimal Example

```r
library(SplitAlignerR)

catnip10_expected()
catnip10_summary_counts()
validate_catnip10_oracle()

# Independently rebuild all Catnip10 graph states in pure R.
rebuilt <- recompute_catnip10_oracle("global")
identical(rebuilt$matrix, catnip10_matrix("global"))

# Inspect the compiled core and its numeric input policy.
splitaligner_core_info()
validate_branch_length_tokens(c("0", "1e-8", "NaN", "1e9999"))

# Parse and canonicalize a reference tree in the C++ core.
validate_species_tree("((A:1,B:1),(C:1,D:1));")

# Align empirical trees. State and finite numeric evidence stay separate.
species <- "((A:1,B:1):1,(C:1,D:1):1);"
genes <- c(
  concordant = "((A:1,B:1):1,(C:1,D:1):1);",
  discordant = "((A:1,C:1):1,(B:1,D:1):1);",
  marker = "((A:NaN,B:1):1,(C:1,D:1):1);"
)
aligned <- align_branches(species, genes, mode = "free")
aligned$state_matrix
aligned$numeric_matrix
```

## V1 Release-Candidate Scope

This V1 release candidate combines the production mapper with the independent
Catnip10 benchmark track. It includes:

- `catnip10_expected()` / `catnip10_matrix()` for the wide primitive-coordinate
  oracle matrix;
- `catnip10_summary_counts()` for per-regime status accounting;
- `catnip10_fusion_groups()` for graph-oracle fused-coordinate membership;
- `validate_catnip10_oracle()` for deterministic benchmark sanity checks;
- `recompute_catnip10_oracle()` for an independent pure R reconstruction of
  every Catnip10 primitive state and fusion group;
- `validate_branch_length_tokens()` for C++ whole-token and finite-range numeric
  validation;
- `validate_species_tree()` for C++ Newick parsing, diagnostics, and canonical
  unrooted primitive coordinates;
- `align_branches()` for C++ graph-first primitive classification, empirical
  split recovery, composite provenance, and finite numeric evidence;
- `coordinate_provenance()` and `summary()` for member-set and run-level
  inspection;
- `save_splitaligner_result()` / `read_splitaligner_result()` for checked,
  lossless result persistence;
- `pair_alignment_results()` for a separate fixed/free finalized-output layer
  that preserves literal `NA`, summarizes it as `residual_NA`, and never
  changes the single-tree graph ledger;
- `splitaligner_core_info()` for core, schema, and numeric-policy metadata;
- `catnip10_oracle`, the bundled data object containing the frozen species tree,
  branch-label crosswalk, per-cell oracle states, and fusion groups.

The Catnip10 benchmark is discordance-free by design. It exercises
the graph-defined `observed`, `NA_fuse`, and `NA_struct` ledger states under
taxon pruning. `NA_topo` is not expected in this benchmark because empirical
gene-tree discordance is outside the Catnip10 oracle fixture.

## Release-candidate and audit boundary

The production mapper lives in the C++ core. R converts inputs and wraps the
result; the Catnip10 Oracle remains a separate pure R node-edge implementation
that never calls the core or uses projected splits for structural states.

The contract field `finalized_perl_matrices_are_authoritative` is intentionally
named. Here, Perl refers to the frozen SplitAligner reference implementation;
SplitAlignerR does not require Perl at runtime.

The release-candidate tests reproduce all 272 frozen Catnip10 primitive
cells and all 19 fusion events, and include explicit discordance and unavailable
numeric-evidence toys. This is implementation evidence, not final V1 release
certification. The scientific, numeric, provenance, and paired-bookkeeping
boundaries are recorded in `inst/spec/V1_SCIENTIFIC_CONTRACT.md`.

See `vignette("quick-start", package = "SplitAlignerR")` for the layered result
model, batch input forms, diagnostics, provenance lookup, and save/reload flow.

## Citation

If you use SplitAlignerR, please cite the SplitAligner preprint. A software DOI
will be added only after final release approval.

> Wu J. (2026). *SplitAligner: A Gene-Species Tree Reconciliation Framework
> Using Split-Based Branch Mapping.* bioRxiv.
> <https://doi.org/10.64898/2026.02.24.707838>

See [`CITATION.cff`](CITATION.cff) and `citation("SplitAlignerR")`.

## License

GPL-3. See [LICENSE.md](LICENSE.md).
