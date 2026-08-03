# ENGINE002 changed-file scope plan

## Frozen base

```text
branch: engine002-core-schema-storage-primitives
parent: 93e8bf79ff6fb6b6419d794b7ef70bac702b8665
tree:   67ec5592f406843341f0966ba50f6b71058d876a
```

ENGINE002 is a limited production implementation of packed truth-plan records,
validated direct views, packed stores, hard-bounded cache/scratch storage,
lifecycle safety, and atomic publication. It does not replace the truth
constructor or empirical mapper and does not add a public R API.

## Authorized paths

```text
src/engine002_*.h
src/engine002_*.cpp
R/engine002-internal.R
tests/testthat/test-engine002-*.R
tests/testthat/fixtures/engine002/
tools/engine002/
dev/ENGINE002/
```

`src/RcppExports.cpp` and `R/RcppExports.R` may change only for internal test
bindings. `NAMESPACE` may change only if native registration generation requires
it. `DESCRIPTION` must not change and no dependency may be added.

## Locked paths and behavior

The existing mapper, public API, package metadata, authorities, fixtures,
expected scientific results, tags, releases, default engine, fixed/free
semantics, numeric policy, and matrix implementation are locked.

## Required ordinary commits

1. `ENGINE002-SPEC`
2. `ENGINE002-CODEC`
3. `ENGINE002-STORES`
4. `ENGINE002-TESTS`
5. `ENGINE002-BENCH`

No durable writer is permitted before the specification validator passes.
