# ARCH000 final handoff

## Identity and classification

```text
branch: arch000-unified-streaming-feasibility
base commit: e847dd0cc4bc8026cd75a34d2ca75be1b4fe0771
production paths changed: no
architecture classification: ARCHITECTURE_PASS
```

The final branch head is recorded by the enclosing handoff package's
`00_PACKAGE_IDENTITY.txt`; a Git commit cannot embed its own object ID without
changing that ID.

## Architecture verdict

Pattern-keyed immutable truth plans, exact bounded B* accumulation, canonical
registry freezing, and per-gene streaming recovery are implementable without
semantic loss. The complete paired authority recovered all 407 frozen residual
literal-`NA` keys. Remaining work is production engineering and optimization,
not an unresolved conceptual blocker.

## Prototype status

- Prototype A: exact pattern keys, shared truth plans, gene mapping, and
  reversal-invariant final pattern IDs — complete.
- Prototype B: exact B* member keys, actual-size flush threshold, sorted merge,
  overlapping/nested sets, all-memory reference equality, and forced hash
  collisions — complete.
- Prototype C: complete-parse baseline and taxa-only candidate with accepted
  grammar fixtures — complete as an experimental candidate; not promoted to
  production.
- Prototype D: compact raw/double matrices, sparse registries, one-gene
  recovery, terminal invariant, counters, and post-scan Support(b) — complete.

## Measured memory result

The preferred single-dataset 2,275-locus run peaked at 500,269,056 bytes RSS
and returned a 258,732,048-byte compact prototype object. The combined full
fixed/free compact-only audit peaked at 1,013,055,488 bytes. The strengthened
final validation, which additionally replayed unchanged production mapping in
bounded chunks, peaked at 1,399,799,808 bytes. These are OS high-water marks,
not `object.size()` substitutes; the extra validation peak is not the
architecture memory-mode benchmark.

On the authority, the largest component was the inspectable R truth-plan cache:
1,974 unique patterns and 192,039,008 bytes. This is the measured target for a
future packed C++ representation. The B* pending buffer peaked at 124,040 bytes
and global unique B* count was 485.

## Measured I/O result

For the 25,823,497-byte fixed authority file:

```text
taxa-only first pass:       174.415 s
full recovery pass:        159.411 s
two-pass total:            333.826 s
first-pass overhead:         0.522

full-parse first pass:     515.714 s
full-parse-twice total:    676.434 s
all-text-resident total:   677.524 s
```

Thus the extra sequential scan is favorable on the measured local APFS SSD;
the experimental taxa scan halves total time relative to reparsing complete
topology in pass 1. Gzip was slightly slower than plain input on the replicated
local workload. No second storage class was available, so no remote/HDD claim
is made.

## Growth observations

```text
authority 2,275 loci: 1,974 patterns, 485 B*
Catnip-derived 10,000: 15 patterns, 13 B*
Catnip-derived 100,000: 15 patterns, 13 B*
```

The authority demonstrates the difficult low-reuse regime; the replicated
workload demonstrates saturation and matrix-dominated scaling. The largest
directly measured scale was 100,000 loci: 84.789 seconds, 350,732,288 bytes peak
RSS, and a 48,251,536-byte compact object. The 500,000-locus row is explicitly
projected (423.945 seconds and 241,257,680 object bytes); peak RSS is not
projected.

## Completed oracle gates

- complete mapping, topology discordance, missing-taxa fusion,
  multifurcation, and literal residual `NA` toy boundaries;
- Catnip10: all 272 primitive cells plus composite provenance and numeric
  values;
- 302-mammal: five genes × 601 coordinates for fixed and free;
- full authority: 2,275 fixed + 2,275 free and 407/407 residual keys;
- unchanged production replay: 2 × 1,367,275 primitive cells and every
  observed composite numeric column;
- exact B* reference and hash-collision resistance;
- three repeated runs and reversed input order;
- post-optimization quick replay from a fresh 0.1.0.9000 source build.

## Uncompleted gates and known limits

- 500,000 loci were projected, not directly measured; this is allowed by the
  task and is labelled throughout.
- No second storage class was available.
- Disk spill was designed but not activated because unique B* growth never
  approached the configured threshold.
- The taxa-only scanner remains experimental. The architecture can ship first
  with a complete-parse first pass if broader grammar differential coverage is
  required; this affects speed, not semantics or bounded result memory.
- The transparent R truth-plan representation is deliberately not a production
  performance implementation.
- Older manuscript-distribution full matrices use a pre-current classification
  for some fused primitive members. They are not RC3/ARCH000 authorities and
  are documented separately in `LEGACY_MANUSCRIPT_LINEAGE_DIAGNOSTIC.txt`;
  reconciling their publication lineage requires a separate task.

None is a conceptual or scientific blocker to the architecture.

## Recommended implementation sequence

1. Freeze internal typed schemas and cross-language golden vectors.
2. Implement canonical taxa/primitive bitsets and one-plan-per-pattern C++
   truth construction.
3. Implement exact B* accumulator, deterministic sort/remap, and spill tests.
4. Implement one-gene C++ split index/query and direct compact row fill.
5. Add deterministic counters and the R `phylo$node.label` Support(b) adapter.
6. Add file-backed replay and an opt-in scanner after broader differential
   grammar tests; retain `multiPhylo` as a convenient non-bounded route.
7. Add derived/chunked long views and a memory-budget execution planner.
8. Re-run all V1 authorities and a new multi-platform RECERT before any public
   API replacement.

## Authorization boundary

Production implementation is **not authorized** by ARCH000. No package source,
test, metadata, authority, tag, release, or public API was changed. Do not merge
this branch into `main` or open a production PR without a separate task.
