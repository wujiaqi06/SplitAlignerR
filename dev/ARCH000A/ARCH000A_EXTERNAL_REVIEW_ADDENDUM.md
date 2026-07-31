# ARCH000A external-review addendum

## Disposition

The external-review additions are part of ARCH000A, not deferred work. They do
not change production source or scientific semantics.

## Degenerate retained patterns

The current package contract cannot accept a zero-taxon Newick and requires at
least two terminal taxa in every gene tree. Empty input and a syntactically
valid one-tip tree are therefore tested twice for stable validation errors. No
zero- or one-taxon truth plan is silently constructed.

Accepted two- and three-taxon patterns are compared against the production
state matrix and passed through the deterministic packed encode/decode path.
The gate checks every primitive state, every exact composite member set, every
projected query, and absence of empirical queries on structurally absent
coordinates.

## Endpoint collapse and terminal fusion

A deterministic enumeration over an eight-taxon tree selects patterns that
exercise:

- singleton-side endpoint collapse;
- a terminal primitive in a non-singleton fiber;
- at least two terminal primitives in one fused fiber;
- one primitive edge under at least three exact retained patterns.

Each selected plan is compared with the frozen ARCH000 constructor and the
production structural states. A second pair of gene trees has identical taxa
but discordant empirical topology; both resolve to one exact pattern and the
same truth plan. A forced constant hash for B-star members is resolved by exact
canonical member bytes.

## Support denominator boundary

A three-locus full-clade-deletion case requires at least one internal primitive
to have:

    mapped_count + NA_topo_count = 0

Every such support value must be plain `NA_real_`: missing, not NaN, infinite,
zero, or one. Converting the value into an `ape::phylo$node.label` slot must
remain missing. All contributing states must be `NA_struct` or `NA_fuse`, and
terminal NA_topo remains forbidden.

## Measured B-star churn

The engineering workload uses a deterministic 1,000-taxon tree, 250 directly
measured 100%-unique retained patterns, 25--35% taxon deletion, and a 65,536-
byte pending threshold. It is not a biological dataset.

Measured facts:

- 55,830 composite member-set records emitted;
- 706,672 canonical member-set bytes;
- 11 pending-buffer flushes;
- 4,066--5,217 records per flush, mean 5,075.45;
- 0.004 s local sort/unique and 0.038 s global union;
- 0.042 s B-star compaction out of 103.982 s measured stress time;
- 65,548-byte peak pending buffer;
- 2,916 unique B-star coordinates;
- 329,809,920-byte sampled peak RSS.

The observed compaction fraction is 0.000404 on this measured workload. This is
evidence that B-star compaction is not the local bottleneck at the measured
scale; it is not a universal 100,000-locus performance claim.

## Explicit projection boundary

The 100,000-locus row is projected from the 250-pattern measurement:

- 282,668,800 encoded member bytes;
- 22,332,000 emitted records;
- 4,314 projected flushes;
- 41,592.8 seconds under a simple per-pattern linear timing model.

Peak RSS and unique-B-star growth are deliberately `NOT_MEASURED`. Global union
can become superlinear as the registry grows, so the projected time is neither
a completed benchmark nor evidence that target-scale churn is negligible.

Exact rows and projection labels are in
`benchmark/ARCH000A_BSTAR_CHURN_RESULTS.csv`; raw flush/growth evidence is in
`evidence/BSTAR_CHURN_RESULTS.txt`.
