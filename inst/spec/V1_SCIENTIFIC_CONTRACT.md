# SplitAlignerR V1 scientific and implementation contract

Status: Phase 1 draft, frozen for the first implementation slice.

This file records the implementation boundary used by SplitAlignerR. It is not
a new algorithm specification. Any change that alters the frozen scientific
semantics requires new evidence and explicit approval.

## Authority and evidence anchors

- Published SplitAligner archive: RECERT-013, publication commit
  `1aea990946e08d13349bc6a164dc7334d61cae08`.
- Catnip10 Benchmark V1: two frozen unrooted scenarios, 136 primitive cells per
  scenario, with zero unexpected Perl-versus-oracle mismatches.
- Independent Oracle source anchors:
  - `oracle_utils.R` SHA-256
    `d139da9cd106d558a61cd1e7ba447662aee776821bd4b9ab3fe1fc5fe2b4e159`
  - `benchmark.R` SHA-256
    `b04dd5c3b7d5827be6c934e097b52785f3fa67995b9e99a49befcf0c09028b7d`
  - `Benchmark_V1_Spec.md` SHA-256
    `901095c3a7bddf99d1ef568150ec8e3a95a8721b00e956e54160fbd01329d56f`
- SplitAligner manuscript and the branch-coordinate theorem manuscript define
  the scientific interpretation. Audit packages are behavioral evidence, not
  scratch inputs.
- SAR-V1-SEM-003 retains the residual-NA conclusions of SAR-V1-SEM-002 and
  supersedes its token-only paired-finalizer wording with structured graph and
  numeric rules. SAR-V1-SEM-001 remains withdrawn.

## Architecture

1. The production branch-alignment engine is C++17.
2. R validates arguments, converts inputs, calls the compiled core, and wraps
   deterministic results. It does not duplicate production state logic.
3. The benchmark Oracle is pure R node-edge graph surgery. It must not call the
   C++ core and must not use splits or projected splits to classify
   `NA_struct`/`NA_fuse`.
4. A future Python interface may wrap the same C++ core; it may not create a
   second scientific implementation.

## Tree contract

- Branch identity is unrooted and root-representation invariant.
- Reference/species trees contribute topology and tip labels. Branch lengths,
  internal support, and annotation blocks are ignored with diagnostics.
- Gene/empirical trees contribute tip labels, topology, and branch-length
  evidence. Internal support and annotation blocks are ignored. A root length
  is not a biological edge value.
- Duplicate or missing leaf labels, parse failures, unexpected taxa, and silent
  multifurcation refinement are errors.
- Degree-2 representation nodes are suppressed under the frozen conventions.
- A multifurcating reference defines only its actual edges.
- Coordinates and member sets are ordered deterministically.

## Single-tree state ledger

| State | Meaning |
|---|---|
| `mapped` | The eligible projected reference split is recovered by the empirical topology. Numeric evidence is recorded independently and may be unavailable. |
| `NA_struct` | Restriction makes the primitive coordinate structurally undefined. |
| `NA_fuse` | The primitive coordinate survives only as a member of a composite/fused coordinate. |
| `NA_topo` | The projected eligible reference split is not recovered by the empirical tree. |

The finalized matrix alphabet is finite numeric, literal `NA`, `NA_struct`,
`NA_fuse`, and `NA_topo`. Literal `NA` is intentional output, not an R missing
value and not a graph state. `residual_NA` is only the paired ledger/summary
name for cells whose `final_matrix_token` is literal `NA`; serialization must
write `NA`, never `residual_NA`.

`pair_alignment_results()` is a separate paired-output layer. It requires
matched ordered gene and primitive-coordinate axes plus identical core/schema
conventions and retains the single-tree graph ledgers unchanged. It calls one
canonical structured finalizer. The true free pre-promotion token is:

- numeric for graph state `mapped` with finite primitive evidence;
- `NA_fuse` for graph state `NA_fuse` with finite fused evidence;
- literal `NA` otherwise, including graph states `NA_struct` and `NA_topo`,
  mapped but numeric-unavailable, and fused but numeric-unavailable cells.

Paired finalization then maps graph state `NA_struct` to `NA_struct`; maps graph
state `NA_topo` to `NA_topo` only when the fixed graph state is `mapped` and
its primitive evidence is finite; and otherwise retains the free
pre-promotion token. Finite fixed fused evidence cannot substitute for fixed
primitive evidence. Numeric unavailability cannot manufacture topological
absence.

Only the exact finalized tokens `NA`, `NA_struct`, `NA_fuse`, and `NA_topo`
are legal alongside finite numeric tokens. Unknown `NA_*` spellings, padded
biological tokens, and actual R missing values are input-quality errors.
Recognized raw software failure markers are normalized to unavailable numeric
evidence before paired finalization.

The frozen 2,275-gene authority contains 407 literal-`NA` cells whose fixed
primitive graph state is `NA_fuse`, fixed primitive numeric evidence is absent,
free pre-promotion token is `NA`, and fixed fused coordinate is finite. Its
independent FREE-tree conflict audit is empirical mechanism evidence, not a
classification predicate. The frozen five-gene 302 authority contains six
additional cells with the same finalize condition. Neither key set is embedded
as a classification whitelist.

## Numeric policy: `finite-double-v1`

- Consume the entire decimal token; trailing text is invalid.
- Accept explicit zero, including signed zero.
- Accept representable finite positive and negative decimal values.
- Flag finite negative values as outside the nonnegative theorem scope.
- Accept representable finite subnormal values without converting them to zero.
- Reject overflow, non-finite values, and values that underflow to zero.
- Treat recognized software failure/missing markers as unavailable evidence.
- Never convert failure markers, unavailable evidence, or parse failures to zero.

This is an approved input-hardening difference from the Perl implementation.
It changes validation behavior, not branch-identity semantics.

## Result layers

The V1 result object keeps these components separate:

1. primitive and composite coordinate table;
2. single-tree state ledger;
3. numeric value matrix containing accepted finite evidence only;
4. primitive-member provenance for each composite coordinate;
5. structured diagnostics;
6. conventions, schema, and core version metadata;
7. optional paired bookkeeping, schema `1.0.0-draft.3`, with graph provenance,
   free pre-promotion token, fixed primitive/fused numeric availability, final
   matrix token, and summary class kept in separate fields. The redundant
   `legacy_gate_failed` field is not part of this schema.

Literal finalized tokens such as `NA` must be read with
`na.strings = character(0)` when using base R tabular readers.
Actual R `NA` inside a finalized token matrix is a data-quality error.

Topology recovery and numeric availability are orthogonal. In particular, a
recognized IQ-TREE/PAML/RAxML-style failure marker on an otherwise recovered
gene-tree edge does not create `NA_topo`; the state remains `mapped`, the
numeric cell is missing, and a structured diagnostic records the marker.

## First-slice acceptance gates

- C++17 core loads from R and reports versioned policy metadata.
- Numeric validation is whole-token and finite-range hardened.
- C++ reference-tree parsing reproduces the frozen B-axis/canonical-split map,
  is invariant to representation-root placement at the split level, and retains
  genuine multifurcations.
- Pure R Oracle reproduces every bundled Catnip10 matrix cell and every bundled
  fusion group for both scenarios.
- The Oracle contains no call into the production C++ core.
- Existing seed-release tests continue to pass.

The next mapper slice additionally requires exact agreement with all 272
Catnip10 primitive cells and all frozen composite member sets, plus explicit
discordance and unavailable-numeric toys. These are development gates rather
than a self-signed release certification.

Passing these gates authorizes further implementation; it is not final V1
certification. The developer does not self-sign release PASS.
