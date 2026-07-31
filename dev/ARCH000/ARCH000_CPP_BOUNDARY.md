# ARCH000 R/C++ boundary

ARCH000 does not modify or production-implement C++ code. This document fixes
the candidate boundary for a later authorized task.

## R owns

- public API and compatibility policy;
- `ape::phylo`, `multiPhylo`, file, and character-input integration;
- user-facing input validation and taxon-name diagnostics;
- configuration, warnings, conditions, and summaries;
- output classes and schema-aware materialized views;
- mapping internal branch support to `ape::phylo$node.label`;
- plotting and chunked/export formats.

## C++ kernel candidates

- canonical taxon and primitive-edge integer axes;
- exact packed retained-taxa bitset keys with collision-safe lookup;
- pattern-keyed truth-plan construction;
- exact packed projected splits;
- B* exact member-bitset accumulation and deterministic registry sort;
- one-gene empirical split indexing and deterministic queries;
- raw/double matrix row fill;
- thread-local internal counters and deterministic reduction;
- optionally, a grammar-conformant taxa-only Newick scanner.

## Required interfaces

An implementation can expose internal calls conceptually equivalent to:

```text
species_authority <- build_species_authority(validated_species)
discovery <- discover_patterns_and_bstar(species_authority, record_source)
registry <- freeze_registries(discovery)
result <- recover_stream(species_authority, registry, replayable_source)
```

The mapper call has no fixed/free parameter. A separate paired finalizer is
directional because its inputs have fixed and free roles.

## Parallelism

After registries are frozen, genes can be processed independently. Workers
write disjoint matrix rows and private branch counters. Reduction is performed
in fixed worker and primitive order. Pattern construction can be parallel only
if the final pattern and B* sort/remap remains canonical.

## Forbidden implementation shortcuts

- no binary-tree-only structure and no assumption of bifurcation;
- no synchronous species/gene DFS node reconciliation;
- no node-local `NA_fuse` flag;
- no projected-split string as global B* identity;
- no hash equality as exact taxa/B* identity;
- no mapper mode inferred from topology;
- no default construction of full long ledgers.

## Prototype hotspot evidence

The R feasibility prototype is intentionally transparent rather than fast. On
the full authority, its largest persistent component is the list-based truth
plan cache and its dominant compute cost is truth-plan construction plus
per-gene empirical split indexing. Packed bitsets, typed arrays, and compiled
query loops are therefore evidence-driven C++ targets. R orchestration and
user-facing objects do not need a wholesale rewrite.
