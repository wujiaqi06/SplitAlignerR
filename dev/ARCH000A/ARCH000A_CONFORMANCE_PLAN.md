# ARCH000A conformance plan

## Failure rule

Storage performance cannot compensate for a scientific mismatch. Any terminal
NA_topo, packed round-trip difference, strategy-dependent output, incomplete
store accepted as complete, or failed full-authority comparison prevents
ARCH000A_PASS.

## Pattern-level equality

For every scientific pattern written to the packed store, decode and compare:

- exact retained taxa;
- primitive truth states;
- projected query splits;
- eligible primitive set;
- exact composite member keys and members;
- composite projected queries.

Terminal/internal classification remains the frozen species-coordinate
authority shared by both representations.

## Degenerate and endpoint patterns

The input contract rejects empty input and gene trees with fewer than two
terminal taxa; repeated calls must return the same validation message. Accepted
two- and three-taxon patterns are checked cell-for-cell against production and
through the packed round trip. A deterministic eight-taxon enumeration selects
endpoint-collapse, terminal-in-fiber, multiple-terminal-fusion, and repeated-
primitive cases. Exact B-star bytes resolve a forced constant-hash collision.

## Support boundary

A full-clade-deletion workload must create at least one internal coordinate
with `mapped_count + NA_topo_count == 0`. Its support must be plain
`NA_real_`, not NaN, infinite, zero, or one. Character conversion into an
`ape::phylo$node.label` slot must preserve missingness.

## Exact identity

Pattern registry tests use constant and truncated hash functions, then resolve
against exact bitset keys. B-star identity continues to use exact canonical
primitive-member sets from ARCH000.

## Cross-strategy equality

Retain-all, recompute, verbose LRU, disk, and packed-disk-plus-LRU process the
same toy and 302 subsets. Normalized per-gene scientific checksums must be
identical. Different budgets and orderings may change cache statistics only.

## Frozen oracle gates

- Catnip10: all 272 primitive cells plus composite order and numeric values.
- 302 mammal: five genes times 601 primitives for fixed and free.
- Full authority selected strategy: 2,275 fixed and 2,275 free, every
  primitive state, every primitive/composite numeric value, paired inputs and
  exact 407 residual literal-NA keys.

The full production comparison is chunked to bound validation memory.

## Determinism

At least three repeats cover original, reversed, grouped and interleaved order,
with multiple cache budgets. Scientific rows are normalized by gene ID before
checksum comparison. Canonical pattern and B-star registries are explicit exact
sorts and never depend on environment iteration.

## LRU budgets

Benchmark cases cover 32, 64, 128 and 256 MiB. A very-small toy cache also
forces eviction/uncached behavior. Every insertion asserts charged bytes at or
below budget. Reported conservative bounds include the largest in-flight plan.

## Interruption and corruption

One test stops after a strict prefix of expected records and omits the footer;
opening must fail. A second test flips one body byte in an otherwise complete
store; full verification must fail. Evidence is recorded before disposable
files are cleaned.

## Stress boundary

Deterministic 302-taxon-like missingness creates 10%, 50%, 90% and 100% unique
pattern series. These are labelled engineering stress inputs, not biological
data. Direct exact-S9 construction is separated from a 100,000-locus packed
storage-substrate test. The latter validates record/index/LRU scaling but makes
no scientific-truth claim for its synthetic payload.

A separate B-star churn stress uses a deterministic 1,000-taxon engineering
tree, 100% unique retained patterns, and a small exact-byte pending threshold.
It measures a smaller direct run and labels the 100,000-locus extension as a
projection. Peak RSS and unique-B-star growth are not projected.

## Peak memory

Each final benchmark case runs in a fresh R process. A separate read-only ps
monitor samples target RSS every 20 ms. Results are labelled sampled OS RSS
maxima, not kernel high-water marks. object.size values are component
attribution only.

## Missing inputs

If any frozen authority path is missing or a required long run is disabled, the
gate records INCOMPLETE. The script never converts missing evidence into PASS.
