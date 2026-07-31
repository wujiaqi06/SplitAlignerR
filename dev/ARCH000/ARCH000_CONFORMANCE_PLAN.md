# ARCH000 conformance plan

## Rule

Performance and compactness cannot authorize the architecture unless frozen
scientific semantics are reproduced. The development prototype is compared
against both independent/frozen authorities and the unchanged production
mapper where appropriate.

## Executed gates

| Gate | Required comparison |
|---|---|
| Toy complete/discordant/fusion/multifurcation | Full primitive state, numeric matrix, coordinate order, composite members |
| Toy residual literal `NA` | Compact paired final token equals production paired finalizer |
| Pattern cache | One plan per exact set; same-pattern truth identity; reversal-invariant IDs |
| B* accumulator | Equality with simple exact reference; overlapping/nested sets; forced hash collisions |
| Scanner | Taxa-only result equals complete package parse for quotes, annotations, exponent lengths, markers, multifurcation, root representations, and multi-record files |
| Catnip10 | 272 primitive states; composite members and values; canonical order |
| 302 mammal | Five common genes × 601 coordinates, fixed and free through one computational path |
| Full authority | 2,275 fixed + 2,275 free; paired inputs; exact 407 residual-key set |
| Determinism | Three repeated runs plus reversed gene order |

Categorical comparisons are exact. Numeric comparisons use existing frozen
tolerances: `1e-12` for the 302 fixed authority, `5e-8` for its free authority,
and `1e-9` for Catnip10 composite lengths.

## Internal invariant checks

- empirical topology cannot alter structural/fused templates;
- retained terminal primitives cannot become `NA_struct`;
- any terminal `NA_topo` aborts the prototype;
- B* identity decodes to the exact primitive-member vector;
- final coordinate order is primitive B then exact-member-sorted B*;
- pass-2 retained taxa must equal the pass-1 pattern exactly;
- actual R missing values are not categorical state tokens;
- Support is calculated only after the full scan and only for internal B.

## Scanner boundary

The complete-parse baseline calls the package's validated C++ Newick parser.
The taxa-only candidate remains experimental. Current production line-based
files require one complete record per non-comment line; line-wrapped trees are
therefore documented as unsupported rather than silently joined.

## Evidence and failure policy

`prototype/run_conformance.R` writes machine-readable tab-separated gate
results. Any `FAIL` exits nonzero. Missing authority paths or a disabled full
run are recorded as `INCOMPLETE`, never PASS. Full authority is claimed only
when the entire paired run finishes and all 407 exact keys match.

For the full run, the unchanged current production core is replayed in bounded
chunks and compared against every compact primitive state and every
primitive/composite numeric column. This is an implementation-conformance gate,
not a second independent oracle. Independent/frozen external evidence is
provided by Catnip10, the 302 regression, and the 407-key residual ledger.

An exploratory comparison found that older manuscript-distribution full
matrices encode some current `NA_fuse` primitive members as ordinary numeric
cells. Those files were not in the RC3 RECERT authority set and contradict the
locked ARCH000 graph-first invariant; they are recorded as a non-gating lineage
diagnostic rather than silently promoted to a new authority.
