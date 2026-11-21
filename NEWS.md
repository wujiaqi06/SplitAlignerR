# SplitAlignerR 0.1.0.9015 (development prerelease)

* Native compact-vector initialization is retained when Rcpp attributes are
  regenerated. CI checks generated registration on all three platforms and
  with the distribution's Rcpp package.
* Release metadata checks and software citations identify the current
  development prerelease. Historical release identities remain unchanged.
* The panel cleanup diagnostic test compares normalized paths on Windows.
* README relates current manuscript algorithm numbers to legacy software
  identifiers. Numerical algorithms and result schemas are unchanged.

# SplitAlignerR 0.1.0.9014 (local development candidate)

* Default split alignment keeps projected-split ledger text in a compact
  deferred character representation. Full taxon names are rendered when
  requested, while branch identities, matrices and provenance remain intact.
  Version-3 RDS serialization preserves the compact representation and needs
  SplitAlignerR 0.1.0.9014 or later to read it. Explicit version-2 RDS is an
  ordinary-character fallback for older readers, at greater memory/file cost.
  Restored Unicode split labels retain their character meaning when the
  reader's native locale differs from the writer's.
* Selected fusion-source queries render only the requested split records.
  Requesting or modifying an entire text column can still materialize it.
* Fixed-topology graph assembly writes fusion-ledger columns directly and
  avoids unused source tables for original-branch cells. It retains the same
  observation, state, numerical and source-table schema.

# SplitAlignerR 0.1.0.9013 (local development candidate)

* Gene-specific S4 errors identify the gene without losing condition metadata.
  Unrepresented ancestral stems are described relative to the declared
  unrooted observation view; original input Newick remains retained.
* Direct fusion views exclude multi-component numerical construction before
  overflow or missing-length checks, consistently with S4.
* Disk readers accept empty fusion selections. Export diagnostics distinguish
  occupied paths, including dangling symlinks, while preserving no-clobber
  publication. Failed cleanup is reported without replacing the primary error.

# SplitAlignerR 0.1.0.9012 (local development candidate)

* Empty disk-panel fusion catalogs now explicitly retain character coordinate
  IDs on R versions whose default is `stringsAsFactors = TRUE`. The reader
  continues to validate the same schema; no fusion or matrix semantics change.

# SplitAlignerR 0.1.0.9011 (local development candidate)

* Native Linux validation found that R 3.6 lacks `unlink(expand = FALSE)`.
  Disk-output cleanup now uses literal filesystem paths across supported R
  versions, preserving neighboring paths that contain wildcard characters.
* Package checks now inspect every raw test event, including errors followed
  by warnings, so a test reporter summary cannot conceal a failed check.
* The S4 reference, observation, numerical and mismatch contracts are unchanged.
  This compatibility candidate preserves the 9010 source and its check evidence.

# SplitAlignerR 0.1.0.9010 (local development candidate)

* S4 now separates `reference_semantics` from `gene_semantics`. Rooted reference
  identity preserves the original root exactly as S3 does; gene inputs default
  to unrooted observations, with `reference_rooted` available by declaration.
* The new `s4-observation-v1` result separates reference states and components
  from empirical observations. Joint observations caused by forgetting a root
  are recorded once, without inventing separate root-child lengths or deletion
  fusions. Unrepresented stems remain in reference truth and receive no length.
* Observation provenance distinguishes one input edge from a complete sum of
  input edges after normalization. Whole/direct fusion views respect complete
  observation units and retain each target's contributing sources.
* A fixed-topology mismatch skips that gene and records its ID and reason.
  Reference rows cover all inputs; numeric rows cover successful genes only.
  Counts and typed empty outputs remain available when every gene is skipped.
  Other input errors still fail explicitly; there is no S2 fallback.
* The old `tree_semantics = "unrooted"` spelling is a deprecated alias. The old
  rooted spelling raises a migration error because its MRCA-stem convention
  differs from the new reference definition. New results have no ambiguous
  `state_matrix` or `component_ledger` aliases. Historical results are preserved.
* S4 gene inputs may explicitly represent unary stem structure. Original
  reference inputs retain the 9009 contract: every internal node, including
  the root, must have at least two children. A unary root created by S3
  restriction remains valid; the S2 parser's input contract is unchanged.
* S3 reference truth, S2/Fast mapping, Support and deletion-fusion identities
  keep their existing definitions. This candidate is not a published release.

# SplitAlignerR 0.1.0.9009 (local development candidate)

* `reference_truth()` exposes the S3 graph algorithm for arbitrary reference
  trees and retained-taxon sets, with separate original-branch and shared
  fusion matrices, complete members and expected reference-length provenance.
* Rooted S3 preserves the original root and its path to the retained-tip MRCA.
  It never adopts S4's MRCA promotion rule. Reference truth accepts no empirical
  gene trees and makes no topology-recovery classification.
* Both graph paths share the optimized table builder. Existing unrooted
  Catnip10 behavior and the default S2/Fast mapping entry are unchanged.

# SplitAlignerR 0.1.0.9008 (local development candidate)

* S4 assembles component and fusion ledgers by columns and indexes each
  primitive's current component once per gene. Complete provenance and all
  existing whole/direct, rooted/unrooted output semantics are retained.
* Document the split-based `align_branches()` path as the default for both
  free and fixed inputs. S4 remains an explicit choice and the Catnip10 oracle
  remains a separate validation entry. No automatic algorithm switching was
  introduced.

# SplitAlignerR 0.1.0.9007 (local development candidate)

* `align_fixed_topology()` implements Algorithm S4 independently of the Fast
  mapper: graph restriction with complete member tracking, followed by exact
  labeled-tree isomorphism and empirical edge-length assignment.
* Explicit rooted and unrooted semantics, strict topology-mismatch errors,
  primitive states, whole/direct fusion views, and source-edge provenance are
  exposed in a separate `splitaligner_fixed_result`. Existing S2 APIs retain
  their current behavior.
* Rooted restriction promotes the root to the retained taxa's MRCA. Discarded
  stem members become `NA_struct`; root promotion is recorded per gene. This
  differs from the historical rooted/global Catnip10 oracle's retained stem,
  and the old benchmark artifacts remain unchanged.

# SplitAlignerR 0.1.0.9006 (development)

* New panels record the whole-component or direct fusion view. Use
  `read_panel_fusion_cells()` to trace each value to the original gene tree.
  Existing v1 panels retain their original direct-only values.
* Align large collections in batches with `align_panel_to_disk()`. Look up
  fusion patterns across all batches and read selected genes and branches.
* Fixed and free in-memory alignments return branch Support and an annotated
  Newick reference tree. Each new disk panel also exports support for the
  complete gene set using the totals from all batches.

# SplitAlignerR 0.1.0.9005 (development prerelease)

* `free_fusion_groups()` reports the exact projected split, primitive members
  and recovered length or `NA_fuse_topo` once per gene and fusion group.
* `count_free_topology()` summarizes five disjoint outcomes per gene in an
  explicit primitive-member or projected-coordinate unit.
* The default paired schema 2.0.0 retains `NA_fuse` on every fused primitive.
  Select `rule = "legacy"` to replay schema 1.0.0 final matrices.

# SplitAlignerR 0.1.0.9004 (development)

* The exact-bitset SplitAlignerFast backend supplies branch mapping through C ABI 2.
  The R adapter reuses display strings and gene-ID keys when building full result
  matrices and ledgers.
* The package includes fixed-mode exchange and label tools introduced in 0.1.0.9002.
* Restored the Catnip10 regression suite and quick-start vignette and added
  backend identity, byte-key and result restoration tests.
* Included the MIT notice for the four vendored Fast source files.

# SplitAlignerR 0.1.0.9000

* Published the immutable, Pro-RECERT-certified `v0.1.0` release.
* Started post-release development; this development line is not covered by
  the `v0.1.0` RECERT decision.
* Deferred subsequent user-usability APIs to separately scoped development
  tasks.

# SplitAlignerR 0.1.0

* Added the conditional FIX007 Windows R-hosted numeric-path isolation: CRLF-
  safe evidence parsing with raw-byte preservation, explicit snapshot commit
  metadata, an independent source-clean gate, and fresh-process bare-R DLL and
  package-Rcpp microprobes. Windows run `30346950266` objectively triggered
  authorized case A: hosted automatic/static regex, frozen numeric policy, and
  the public validator timed out while noop, `strtod`, marker, and core-info
  controls passed.
* Replaced only the decimal-token `std::regex` predicate with an allocation-free
  ASCII full-token parser for the identical frozen grammar. Marker handling,
  `strtod`, ERANGE, finite/subnormal/negative policy, diagnostics, and all
  scientific mapping semantics are unchanged. A fixed-seed 100,000-token
  old-regex/manual-parser differential is part of every platform RECERT.
* The Windows harness obtains effective `LC_CTYPE`, `LC_COLLATE`, and
  `LC_NUMERIC` values through a separate fresh-process bare-C-runtime DLL
  operation. This avoids a Windows R 4.6.1 crash observed in both individual
  and combined R-level locale queries without pre-warming D1-D7.
* Corrected RECERT session-option evidence to distinguish requested from
  effective values, require the portable `scipen=-9/0/999` matrix, and report
  clamped `-999` probes as unavailable rather than exact PASS.
* Added a bounded Windows 10-tip fresh-process cold-start diagnostic with
  numeric pre-warm, no-length, fixed/free, wrapper/core, and standalone C++
  regex timing controls; the diagnostic does not change scientific semantics.
* Closed Fix005A gene-ID routes by validating existing object names under the
  same Unicode-preserving whitespace/control/duplicate rules as `gene_ids=`,
  while retaining deterministic auto-fill only for truly missing names.
* Added a byte-key order assertion before restoring gene-ID encodings so the R
  wrapper cannot mask a reordered C++ result axis.
* Replaced single-process deep-tree timeouts with process-tree termination and
  an independent evidence verifier that rejects timeout rows containing late
  R completion output.
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
