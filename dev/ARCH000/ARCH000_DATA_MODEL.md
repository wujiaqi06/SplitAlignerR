# ARCH000 internal data model

This schema is an implementation feasibility model, not a frozen public R
class.

## Species authority

| Field | Type | Meaning |
|---|---|---|
| `taxon_id` | dense integer | Canonical UTF-8 taxon identity |
| `taxon_label` | UTF-8 string | Exact validated label |
| `primitive_id` | dense integer plus frozen `B...` display ID | Species-tree edge axis |
| `branch_type` | enum | `terminal` or `internal` |
| `species_split` | packed bitset | Exact canonical unrooted split |

The root is representational. Primitive ordering comes from the validated
frozen axis, not a traversal performed by the prototype.

## Exact retained-taxa pattern

```text
PatternRecord
  pattern_id              canonical post-sort integer
  exact_taxa_bitset       authoritative identity
  retained_taxon_count
  truth_plan_offset
```

The R prototype uses a reversible fixed-width taxa-ID string as its exact key.
A production hash is only an accelerator; collisions resolve against the exact
bitset.

## Truth plan

```text
TruthPlan
  primitive_state[B]      structural, fused, or eligible template
  projected_query[B]      pattern-local split key when non-structural
  projected_side_sizes[B]
  composite_records[]

CompositeRecord
  exact_member_bitset     subset of primitive B
  global_bstar_id         assigned after canonical registry freeze
  projected_query         pattern-local empirical lookup split
```

`NA_fuse` belongs to a primitive-coordinate × retained-pattern truth plan. It
is not an intrinsic node flag. A projected query split is never the global B*
identifier.

## Registries

```text
pattern_registry:
  pattern_id, exact_pattern_key, retained_taxon_count, truth_plan_offset

gene_to_pattern:
  gene_id, pattern_id

coordinate_registry:
  coordinate_id, coordinate_type, canonical_order

composite_provenance:
  bstar_id, exact_member_key, primitive_member_ids
```

Primitive coordinates precede B*. B* ordering compares exact primitive-member
vectors. Gene input order never changes either registry.

## Compact matrices

```text
state_matrix:   uint8 [gene, primitive]
numeric_matrix: float64 [gene, primitive + B*]
```

State codes are:

| Code | State |
|---:|---|
| 0 | `mapped` |
| 1 | `NA_struct` |
| 2 | `NA_fuse` |
| 3 | `NA_topo` |

R missing double means numeric evidence unavailable; it does not create a
fifth graph state. Composite numeric evidence occupies its B* column. A
pattern's sparse composite record maps a fused primitive back to that column
when a paired finalization view is requested.

For 2,275 × 601 primitive cells, the ideal packed state payload is 1,367,275
bytes and the primitive numeric payload is 10,938,200 bytes. Additional B*
numeric columns scale with observed unique B*, not with repeated provenance.

## Internal counters and support

```text
InternalCounter
  primitive_id
  mapped_count
  na_topo_count
  support_after_scan
```

Only internal primitives are represented. Reduction order is deterministic.
Thread-local integer counters can be summed in fixed primitive/thread order.

## Temporary empirical index

One gene owns a temporary map:

```text
canonical retained split -> {
  recovered,
  numeric_available,
  finite branch-length sum
}
```

Complementary representation-root aliases share one canonical split and their
length evidence follows the existing all-or-none finite policy. The index is
destroyed before the next gene.

## Derived materializations

Long ledgers, user tables, summaries, and paired token matrices are functions
of the compact authority plus registries. Implementations must offer row/column
selection or chunked export before offering unrestricted full materialization.
Serialization equivalence across platforms is semantic and schema-aware; it is
not universal byte identity of an R object.
