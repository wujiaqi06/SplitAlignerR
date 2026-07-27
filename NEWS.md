# SplitAlignerR 0.1.0

* Opened the controlled Fix005/RC002 candidate without moving the frozen,
  abandoned `v0.1.0-rc1` tag.
* Corrected the SplitAligner paper title associated with DOI
  10.64898/2026.02.24.707838 while keeping the top-level CFF title specific to
  SplitAlignerR software.
* Hardened explicit gene identifiers, Catnip10 validator failure reporting,
  Oracle character ordering, and release metadata consistency gates.

* Froze the first V1 release-candidate identity: package 0.1.0, C++ core
  0.1.0, general schema 1.0.0, and paired schema 1.0.0.
* Added release-candidate provenance, dependency, replay, and multi-platform
  verification metadata without changing the accepted Fix004 scientific logic.
* Retained v0.1.0-rc1 as a candidate identifier only; independent RECERT and
  final release approval remain separate gates.

* Unified paired finalization under SAR-V1-SEM-003: production and unit tests
  now use one graph-state/numeric-evidence finalizer.
* Corrected `free_pre_promotion_matrix` so structural and topological states
  remain literal `NA` until the paired graph-state gate is applied.
* Rejected unknown or padded graph/finalized tokens as input-quality errors.
* Removed the redundant `legacy_gate_failed` ledger field; literal `NA` and
  `residual_NA` remain the only finalized-token and summary representations.

# SplitAlignerR 0.0.2.9001

* Added per-gene retained-taxon provenance and exact fixed/free taxon-set
  pairing gates.
* Restored the frozen paired-finalize rule from SAR-V1-SEM-002: literal `NA`
  is an intentional finalized token, and `residual_NA` is only its summary
  name rather than a graph state or recovery-scoped subtype.
* Added explicit pre-promotion/final-token provenance and enforced that only
  finite fixed primitive evidence can promote `NA_topo`; finite fused evidence
  never substitutes for that primitive gate.
* Strengthened persisted-result object invariants and aligned Oracle numeric
  merging with the production core's all-or-none finite-evidence policy.
* Replaced the unreachable singleton-side structural fallback with a loud
  internal invariant failure and added non-vacuous boundary tests.

# SplitAlignerR 0.0.2.9000

* Implemented the C++17 graph-first empirical mapper exposed by
  `align_branches()`, with separate primitive-state and numeric-evidence layers.
* Added deterministic composite-coordinate provenance and recovery ledgers;
  fused numeric values live on composite coordinates rather than being copied
  into primitive cells.
* Added Newick, line-based file, `phylo`, `multiPhylo`, and list input adapters,
  with fixed-mode mismatch diagnostics and strict taxon/ID validation.
* Added regression coverage reproducing all 272 Catnip10 primitive cells and
  all 19 frozen fusion events across both deletion regimes.
* Added result summaries, member-set provenance queries, checked RDS
  save/reload, a quick-start vignette, and deterministic random-tree property
  tests for pruning, terminal, root-representation, and wrapper/core invariants.
* Added a separate paired-bookkeeping API that preserves frozen fixed/free
  numeric promotion gates and records residual `NA` without changing semantic
  single-tree states.
* Added an opt-in external regression hook for the frozen 302-mammal example,
  covering 6,010 fixed/free legacy cell classes without embedding local paths
  or duplicating the publication authority into the package.
* Added the first C++17 core boundary with strict whole-token, finite-range
  branch-length validation and structured diagnostics.
* Added C++ reference-tree parsing and canonical unrooted coordinate tables with
  root-representation normalization, quoted-label/annotation handling, and
  retained multifurcations.
* Added a pure R node-edge implementation that independently recomputes both
  bundled Catnip10 graph-oracle scenarios without calling the C++ core or using
  projected splits.
* Recorded the V1 scientific, numeric, provenance, and paired-bookkeeping
  contracts under `inst/spec/`.
* Clarified that paired `residual_NA` summarizes finalized literal `NA` and is
  not a fifth graph state.

# SplitAlignerR 0.0.2

* Prepared the package as a public seed release for the SplitAligner R
  reference implementation track.
* Reframed the README and package metadata around bundled Catnip10 graph-oracle
  benchmark data, audit-ready accessors, and validation helpers.
* Added `catnip10_summary_counts()`, `validate_catnip10_oracle()`,
  `catnip10_fusion_groups()`, and `catnip10_matrix()`.
* Removed placeholder software DOI metadata and private local paths from
  public-facing source files.

# SplitAlignerR 0.0.1

* Initial package scaffold (`v0.0.1-scaffold`).
* Bundled the deterministic Catnip10 10-tip coordinate-audit benchmark expected
  oracle outputs (unrooted axis, both the global and local deletion regimes) as
  the `catnip10_oracle` data set, with the `catnip10_expected()` accessor.
* Added `splitalignerR_scaffold()` placeholder so the package installs and
  passes `R CMD check`.
* Set up GitHub Actions `R-CMD-check` continuous integration.
* The split-based branch-mapping engine is not implemented yet.
