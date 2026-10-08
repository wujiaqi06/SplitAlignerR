# External frozen regression hooks

The package test suite contains two opt-in regressions. Their fixtures are not
duplicated into the R package because the frozen publication and POINT5 audit
artifacts remain authoritative.

Set `SPLITALIGNERR_302MAMMAL_DIR` to that directory before running tests. The
test explicitly intersects the fixed/free gene IDs, matching the five genes in
the frozen final matrices; it never pairs rows merely because their positions
match.

The regression compares 5 genes x 601 primitive coordinates on both fixed and
free sides: 6,010 legacy cell classes. Numeric values are compared within the
printed precision of the frozen expected matrices. In the current authority,
the maximum accepted absolute differences are `1e-12` (fixed) and `5e-8`
(free); the latter reflects a 7-decimal frozen output versus a 10-decimal input
value.

The full 2,275-gene regression additionally requires:

- `SPLITALIGNERR_2275_INPUT_DIR`, containing the frozen fixed/free input trees;
- `SPLITALIGNERR_RESIDUAL_NA_DIR`, containing
  `01_residual_NA_cell_ledger.tsv` from the frozen POINT5 audit.

It derives cells through the paired finalize rule and compares their keys to
the authority ledger. It also requires exactly 407 literal-`NA` cells, 189
genes, 82 internal coordinates, 202 unique gene-by-fixed-fusion events, and
zero terminal residual cells. Authority keys are evidence, not an embedded
classification whitelist.

Without the required environment variables or complete authority directories,
the corresponding external test reports `SKIP`. Catnip10, random properties,
toys, package examples, and all self-contained tests still run normally.
