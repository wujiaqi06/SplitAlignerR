# ENGINE001 R/C++ boundary freeze

## Boundary model

Select a hybrid boundary:

```text
ordinary R objects:
  user inputs, validated labels, controls, durable descriptors, summaries

Rcpp RawVector/integer/numeric vectors:
  small construction inputs and explicit diagnostic copies

external pointers:
  active immutable authority and mutable run context only

file-backed handles:
  owned inside the run context; durable identity remains in ordinary files
```

The boundary is coarse-grained. R does not call C++ once per branch. One C++
call processes a pattern or a gene block, returning compact status/progress and
ordinary summaries.

## R responsibilities

R retains:

- public API and backward-compatible wrappers;
- `ape::phylo`, `multiPhylo`, Newick-file and connection integration;
- container, label and high-level input validation;
- taxon-label normalization before canonical integer assignment;
- user-facing conditions, warnings, progress and control objects;
- durable result classes and file-backed descriptors;
- summaries, plots, exports and safe materialization;
- Support(b) attachment to internal `ape::phylo$node.label`;
- paired fixed/free orchestration and directional finalization;
- reference/shadow-engine normalized comparison.

R does not implement a second numeric parser or reclassify errors by matching
low-level message text.

## C++ responsibilities

C++ owns performance-critical canonical operations:

- integer IDs and packed taxon/split bitsets;
- one-pattern truth/fiber construction;
- packed truth-plan encode, validate and direct view;
- truth-store lookup, cache accounting and file I/O;
- empirical canonical-split indexing;
- deterministic split query and numeric recovery;
- primitive state and numeric row fill;
- branch-counter update;
- tiled matrix I/O and validation;
- optional taxa-only Newick scanning after a separate differential gate.

C++ receives no fixed/free mapper mode. Dataset role is metadata in R.

## Boundary objects and ownership

| object | creator | owner | destructor/close | copy behavior | thread safety | serialization | invalid use |
|---|---|---|---|---|---|---|---|
| validated species descriptor | R | R | normal GC | ordinary deep copy | immutable | yes | R validation error |
| `SpeciesAuthorityXPtr` | C++ factory from descriptor | R external pointer owns C++ object | registered finalizer; idempotent close | pointer copy shares one control block | immutable/read-only after creation | pointer no; canonical descriptor yes | `ENGINE_CONTEXT_CLOSED` |
| finalized pattern bytes | C++ or R scanner | run context/store | context close | copied into compact arena or durable file | immutable after finalization | yes | schema/pattern error |
| `RunContextXPtr` | C++ factory | R external pointer owns C++ context | explicit close plus idempotent finalizer | pointer copy shares one control block; no raw duplicate owner | single-thread in initial engine | pointer no; manifest/results yes | `ENGINE_CONTEXT_CLOSED` |
| `TruthPlanView` | store lookup | C++ scoped stack object | automatic release/unpin | noncopyable; movable within one call | one worker initially | no | never returned to R |
| matrix backend handle | run context | run context | explicit finalize/close | noncopyable | one writer initially | descriptor/files yes | typed lifecycle error |
| completed result descriptor | R finalizer/orchestrator | R | normal GC; files retained | ordinary copy | read-only | yes | component validation error |
| materialized matrix/table | R | R | normal GC | ordinary R copy semantics | immutable by contract | R serialization allowed | ordinary R error |

## External-pointer discipline

Pointers contain a magic/type tag, ABI major, generation token, open/closed
state, and shared control block. Every entry point checks type, ABI, generation,
thread ownership where applicable, and lifecycle before dereference.

Rules:

- explicit `close()` is idempotent;
- the finalizer calls the same no-throw close path;
- close marks invalid before releasing handles;
- stale pointer calls fail with a stable internal category;
- active calls hold a local shared guard so R GC cannot destroy the context;
- no pointer address is serialized, printed as identity, or embedded in a
  durable result;
- file handles close on normal return, R interrupt, Rcpp exception, C++
  exception, and finalizer cleanup;
- completed file-backed output can be reopened in a later R session using its
  validated manifest without recreating an old pointer.

The isolated ownership prototype demonstrates an ordinary snapshot surviving
pointer GC, idempotent close, and safe closed-context failure. It is not linked
into the package.

## Preferred call boundary

Logical internal calls:

```text
cpp_authority_create(validated_descriptor) -> authority_xptr + fingerprints
cpp_pattern_scan_block(authority_xptr, tree_source_block) -> compact scan block
cpp_pattern_registry_finalize(scan_blocks) -> registry descriptor/bytes
cpp_truth_store_build(authority_xptr, registry, control) -> store descriptor
cpp_coordinate_finalize(authority_xptr, store) -> coordinate descriptor
cpp_run_create(authority_xptr, store, matrix_descriptor, control) -> run_xptr
cpp_map_gene_block(run_xptr, gene_block, row_range) -> progress/QC
cpp_run_finalize(run_xptr) -> ordinary durable result descriptor
cpp_component_read(result_descriptor, block) -> ordinary R block
cpp_run_close(run_xptr)
```

Strings cross only at input/diagnostic boundaries. Inner truth/query/matrix
paths use integer IDs, raw bitsets, offsets and typed arrays.

## Copy and materialization policy

R inputs are validated before C++ construction and then copied once into owned
canonical storage. C++ never retains an unprotected pointer into a temporary R
vector. Diagnostic `RawVector` output is an explicit copy.

Large matrix payloads do not cross as one R object. File-backed readers return
bounded blocks; explicit materialization is planner-gated. Final summaries and
registries use ordinary R data frames/lists because they are durable and small.

## Interrupt checks

Single-thread kernels check for user interruption at deterministic safe points:

```text
between input records
between truth plans
between gene rows or bounded gene sub-blocks
between matrix tiles
before durable publication
```

No interrupt is raised while a file header/index/footer is half-updated. The
kernel first returns the component to an explicitly incomplete state, releases
pins/handles, then propagates a typed interruption condition to R.

## Future parallelism

The initial engine is single-threaded. Future workers may share only immutable
authority, finalized pattern/coordinate registries, and a read-only finalized
truth store. Each worker owns one gene buffer, non-overlapping row blocks, and
thread-local counters. Reduction order is worker ID then primitive ID.

Mutable unordered maps are not shared. A coordinator serializes manifest/index
publication in canonical order. Output must be byte/semantically reproducible
independent of thread count before parallelism is exposed.
