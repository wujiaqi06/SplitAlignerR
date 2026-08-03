# ENGINE002 implementation sequence

## Commit 1: ENGINE002-SPEC

Freeze the exact plan/store/identity/lifecycle/publication/error/boundary and
benchmark contracts. Validate table totals and identity reference vectors. No
durable writer is present.

## Commit 2: ENGINE002-CODEC

Implement fixed-width endian and checked-math helpers, SHA-256, XXH64 seed 0,
authority binding, exact record encoding/decoding, and validated C++ direct
views. Add internal R bindings only.

## Commit 3: ENGINE002-STORES

Implement canonical immutable memory store, disk store, hard-budgeted LRU and
scratch paths, manifest validation, lifecycle/context guards, and atomic
no-clobber publication.

The package-portable header suffix is .h; the earlier ordinary commits used
.hpp, and TESTS records the mechanical rename required for zero-warning
R CMD check.

## Commit 4: ENGINE002-TESTS

Add independent golden vectors, all 1,974 authority plans, degenerate/fusion,
forced collision, lifecycle, corruption, failpoint, cross-session, large-offset,
and three-platform gates without changing existing scientific fixtures.

Local macOS evidence closes the exact 1,974-plan, golden, degenerate, lifecycle,
budget, corruption, 15-stage failpoint, package-build, and package-check gates.
Large-offset and non-macOS evidence remain explicitly incomplete until hosted
runs exist.

## Commit 5: ENGINE002-BENCH

Run and record the frozen performance/RSS matrix, full package regression,
cross-platform results, scope audit, checksums, exact diff/archive identities,
and final classification.

The empirical mapper, truth constructor, matrix backend, public API, default
engine, release identity, and package metadata remain unchanged throughout.
