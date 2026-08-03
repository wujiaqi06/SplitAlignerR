# ENGINE001 staged production implementation sequence

No stage below is authorized by ENGINE001. Each requires a separate narrow task,
ordinary child commit, review evidence, and explicit acceptance.

## ENGINE002 — Core schema and storage primitives

Scope:

- implement versioned hybrid packed truth-plan record;
- exact encode/decode/direct-view validation;
- pattern fingerprints and canonical golden vectors;
- truth-store interface, memory arena, disk index, checksums and atomic footer;
- no empirical mapper replacement and no public API change.

Dependencies: accepted ENGINE001 contracts.

Mandatory gates: cross-language golden bytes, all 1,974 authority plan round
trips, forced hash collisions, wrong authority/schema, truncation, single-byte
corruption, interrupted store, exact byte accounting.

Rollback point: remove/disable new internal schema namespace; reference engine
and outputs are untouched.

## ENGINE003 — Compact matrix backend

Scope:

- implement in-memory typed arrays;
- implement separate 256x256 tiled state, validity and numeric components;
- tile index, manifest, validation, block reads and safe R materialization;
- no mapper replacement and no default change.

Dependencies: ENGINE002 integrity/fingerprint utilities and coordinate golden
axes.

Mandatory gates: exact state/numeric/validity round trip, edge tiles, >2 GiB
offset arithmetic, incomplete component rejection, disk full, block/column
reads, bounded RSS, same-filesystem atomic publication.

Rollback point: disable matrix backend factory; no user data or reference path
is migrated.

## ENGINE004 — C++ truth and empirical kernels

Scope:

- one-pattern truth/fiber construction;
- empirical canonical-split index;
- direct hybrid packed-plan query;
- primitive state/numeric row fill and branch counters;
- single-thread only; no exported API and no default switch.

Dependencies: ENGINE002 plan view and ENGINE003 row-writer interfaces.

Mandatory gates: degenerate/fusion torture cases, Catnip10, all pattern-level
truth fields, numeric differential, terminal `NA_topo=0`, denominator-zero
Support, sanitizer/overflow checks, deterministic block output.

Rollback point: internal factory selects existing reference mapper; new schema
and matrix readers remain isolated.

## ENGINE005 — Shadow integration

Scope:

- internal R orchestration and lifecycle conditions;
- file/in-memory input planning without loading all trees;
- reference/new dual execution and compact comparator;
- Catnip10, 302 subset and full 2,275 authority;
- no public default switch.

Dependencies: accepted ENGINE002-ENGINE004.

Mandatory gates: full fixed/free state/numeric/composite equality, paired inputs,
407/407 ledger, order/repeat/backend determinism, bounded memory and cleanup.

Rollback point: remove shadow invocation; reference engine remains sole public
path.

## ENGINE006 — Cross-platform recertification

Scope:

- Linux, macOS and Windows clean builds;
- single-thread authority replay;
- memory/RSS and I/O evidence;
- corruption, interruption, disk-full and stale-pointer diagnostics;
- no public default switch.

Dependencies: frozen ENGINE005 candidate commit and independent replay harness.

Mandatory gates: identical schemas/axes, normalized science, 407/407, terminal
zero, deterministic repeats/order, complete evidence artifacts and immutable
identity.

Rollback point: candidate remains opt-in/internal; no certified/default object
moves.

## ENGINE007 — Public API migration

Scope only after independent authorization:

- finalize exported names and one optional control object;
- result accessors, summaries, file-backed export and documentation;
- staged opt-in or default policy;
- reference fallback retained for at least one release cycle.

Dependencies: ENGINE006 independent PASS and explicit main-console task.

Mandatory gates: backward-compatible user journeys, package checks, public API
review, release metadata/citation, migration and rollback documentation.

Rollback point: restore reference default through the documented selector while
retaining readers/export for already validated new-format results.

## Deferred parallel task

Parallel gene blocks are not part of ENGINE002-ENGINE005. A separate task may
begin only after single-thread ENGINE006 equivalence. It must prove immutable
shared authority/store, disjoint tile-row writes, deterministic counter
reduction, stable error selection, and output independence from thread count.

## Sequencing rule

Stages are not combined into one mega-commit. A failed gate stops the current
stage; later-stage work does not begin to conceal or work around it. Scientific
semantics reopen only upon demonstrated contradiction and a separate control-
desk ruling.
