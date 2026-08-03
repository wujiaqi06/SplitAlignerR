# ENGINE001 compatibility and shadow-engine plan

## Immutable reference boundary

Certified v0.1.0 behavior remains the reference engine. Initial production
development adds new internal components beside it; it does not rewrite or
delete the reference path.

The compatibility sequence is fixed:

```text
reference engine retained
-> new engine internal only
-> shadow dual execution on bounded fixtures
-> normalized output comparison
-> explicit opt-in
-> cross-platform independent RECERT
-> default switch under separate authorization
-> reference fallback for at least one release cycle
```

No ENGINE00x task may silently change the default.

## Normalized comparison object

Comparison operates on compact blocks, registries and counters rather than the
15.5 GB enriched object. For each bounded row block it compares:

```text
ordered gene IDs
primitive coordinate axis
state bytes
numeric validity
finite numeric values under the frozen tolerance
composite coordinate axis and member sets
pattern IDs after exact-key normalization
sparse fusion/composite provenance
branch counters and Support(b)
terminal NA_topo invariant
```

The reference result may be streamed or reduced to block checksums plus exact
disagreement extracts. A checksum match accelerates comparison but any mismatch
is resolved by exact typed values, not by hash alone.

Paired comparison additionally reconstructs the fixed/final categorical ledger
and validates every residual literal-`NA` authority key.

## Authority ladder

New-engine integration must pass in this order:

1. schema golden vectors and corruption cases;
2. degenerate 0/1 rejection and accepted 2/3-taxon truth patterns;
3. endpoint-collapse and terminal-fusion torture cases;
4. Catnip10 primitive/composite oracle;
5. 302-mammal 5 x 601 fixed/free subset;
6. all authority retained patterns exact packed round trip;
7. full 2,275 fixed and 2,275 free run;
8. 407/407 residual ledger;
9. input reversal, repeats, backend/budget changes and platform matrix;
10. interrupt, disk-full, corruption and stale-pointer cases.

Any failure stops promotion. Accepted scientific semantics are not changed to
make the new engine agree with older manuscript matrices.

## Runtime selection stages

### Internal shadow

Test-only control invokes both engines and returns the reference result. The new
result is retained only as bounded evidence or disagreement diagnostics.

### Opt-in

After ENGINE006, an explicit advanced control may request the new engine. The
result manifest records engine and schema versions. Reference remains default.

### Default candidate

Only ENGINE007 may propose the new default. It requires independent approval,
documented migration, updated public tests/docs, and a rollback switch.

### Reference fallback

For at least one release cycle after a default switch, users and RECERT can
select the reference engine where its input scale is safe. The fallback is not
removed in the same release that changes the default.

## Compatibility surfaces

The new engine preserves:

- state meanings and literal `NA` handling;
- canonical primitive and composite identity;
- finite numeric policy and tolerance;
- paired directionality;
- deterministic ordering;
- `ape::phylo` integration;
- existing result access through adapters where feasible.

It may change internal storage and offer file-backed descriptors. Derived long
tables remain available through bounded access/export, but are not primary
objects.

## Rollback

Each production stage is a normal child commit/branch with no default switch.
Rollback disables/removes the new internal path while leaving reference files
and certified release tags untouched. New schema files carry a distinct magic
and are never interpreted by the reference engine.

After public opt-in, rollback retains readers long enough to export validated
new-format results even if new writes are disabled.
