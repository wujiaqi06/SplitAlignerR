# SplitAlignerR

<!-- badges: start -->
[![R-CMD-check](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml/badge.svg)](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/R-CMD-check.yaml)
[![Codecov test coverage](https://codecov.io/gh/wujiaqi06/SplitAlignerR/graph/badge.svg)](https://app.codecov.io/gh/wujiaqi06/SplitAlignerR)
[![pkgdown](https://github.com/wujiaqi06/SplitAlignerR/actions/workflows/pkgdown.yaml/badge.svg)](https://wujiaqi06.github.io/SplitAlignerR/)
[![License: GPL-3](https://img.shields.io/badge/License-GPL--3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
<!-- badges: end -->

SplitAlignerR aligns gene-tree branches to species-tree coordinates. The C++17
SplitAlignerFast backend maps exact taxon bitsets through C ABI 2. A separate
pure R implementation independently recomputes the Catnip10 graph-oracle benchmark.
The package checks branch-length tokens before using them as numeric evidence.

`v0.1.0` is the immutable Pro-RECERT-certified release. The default branch is
the post-release development line. This source candidate has package version
`0.1.0.9005` and is not covered by the `v0.1.0` RECERT decision. The frozen
`v0.1.0-rc1`, `v0.1.0-rc2`, and `v0.1.0-rc3` tags are retained as historical
release candidates.

Documentation site: <https://wujiaqi06.github.io/SplitAlignerR/>

## Installation

```r
# install.packages("remotes")

# Stable, Pro-RECERT-certified release:
remotes::install_github("wujiaqi06/SplitAlignerR@v0.1.0")

# Post-release development line (not covered by the v0.1.0 RECERT decision):
remotes::install_github("wujiaqi06/SplitAlignerR")
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

## Fast-backed development package

Build the candidate with a C++17 compiler and the Rcpp, ape and digest packages.
Install the source archive using `R CMD INSTALL SplitAlignerR_0.1.0.9005.tar.gz`.
Use `splitaligner_core_info()` to inspect the active backend and source version.

The mapper uses exact taxon bitsets. It caches coverage projections within an
alignment while preserving the R result's branch order, source indices and
fusion memberships. The fixed and free outputs retain separate graph states
and numeric evidence. Pair them with `pair_alignment_results()` to produce
the finalized matrix. Full result objects include per-cell provenance ledgers.

### Fusion members and their shared split

For each gene, missing taxa can cause two or more reference branches to project
onto one split. Each primitive member keeps `NA_fuse` in its own cell. Inspect
the group once to find its length or see why the length is unavailable:

```r
species <- "((A,B),C,(D,(E,F)));"
genes <- c(g1 = "((A,B):0.31,D,(E,F):0.17);",
           g2 = "((A,B):0.26,E,(D,F));",
           g3 = "((A,D),B,(E,F):0.23);")
free <- align_branches(species, genes, mode = "free")
groups <- free_fusion_groups(free)
groups[, c("gene_id", "primitive_members", "projected_split", "recovery_status",
           "graph_class", "final_token")]
```

For these three genes, the same two reference branches form a fusion group.
The shared split is present at length 0.31 in g1 and 0.26 in g2. The g3 tree
lacks the split, so its group token is `NA_fuse_topo`. Both members still
carry `NA_fuse` in all three genes. A displayed group with no finite length
has graph class `Mapped` and a literal `NA` value. An unresolved free tree
can also lack the split. Count each group once in group summaries and count
each member once on the primitive axis.

The default `pair_alignment_results(fixed, free)` exposes the same group
table as `$free_fusion_groups`. Use `rule = "legacy"` for frozen paired
schema 1.0.0 matrices, including their historical residual `NA` tokens.

Use `export_splitaligner_exchange()` for fixed-mode exchange and
`validate_splitaligner_exchange()` to verify an exchange object's structure
and seals. See `?splitaligner_exchange` for its reference-tree requirements.

## V1 Scope

The certified V1 release combines the production mapper with the independent
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

## Release and audit boundary

The production mapper lives in the C++ core. R converts inputs and wraps the
result; the Catnip10 Oracle remains a separate pure R node-edge implementation
that never calls the core or uses projected splits for structural states.

The legacy contract field `finalized_perl_matrices_are_authoritative` is intentionally
named. Here, Perl refers to the frozen SplitAligner reference implementation;
SplitAlignerR does not require Perl at runtime.

The V1 tests reproduce all 272 frozen Catnip10 primitive cells and all 19
fusion events, and include explicit discordance and unavailable
numeric-evidence toys. The immutable `v0.1.0` source passed independent Pro
RECERT; changes on the default development branch do not inherit that
certification. The scientific, numeric, provenance, and paired-bookkeeping
boundaries are recorded in `inst/spec/V1_SCIENTIFIC_CONTRACT.md`.

See `vignette("quick-start", package = "SplitAlignerR")` for the layered result
model, batch input forms, diagnostics, provenance lookup, and save/reload flow.

## Citation

If you use SplitAlignerR, please cite the SplitAligner preprint. A software DOI
has not yet been assigned.

> Wu J. (2026). *SplitAligner: A Gene-Species Tree Reconciliation Framework
> Using Split-Based Branch Mapping.* bioRxiv.
> <https://doi.org/10.64898/2026.02.24.707838>

See [`CITATION.cff`](CITATION.cff) and `citation("SplitAlignerR")`.

## License

SplitAlignerR uses GPL-3. See [LICENSE.md](LICENSE.md). The four vendored
SplitAlignerFast core files are distributed under the [MIT License](inst/fast-backend/LICENSE).

## Acknowledgments

We are especially grateful to Chao Zhang (张超) for his generous technical
help and for sharing his fastSplitAligner.py implementation. His
implementation provided an important reference for efficient split-based
branch mapping and a comparison baseline during the development and
validation of SplitAlignerFast.

SplitAlignerR also benefits from this contribution through its shared
SplitAlignerFast core.
