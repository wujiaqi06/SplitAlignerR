# ENGINE002 internal R/C++ boundary

R owns ordinary input lists/raw vectors, control values, durable path
descriptors, diagnostic copies, and translated typed conditions. C++ owns every
canonical byte copy, authority descriptor, active store, file handle, arena,
cache slab, scratch buffer, pin/view, generation, and validation state.

C++ copies all R input bytes before retaining them. It never retains an
unprotected pointer into an R vector. `TruthPlanView` is C++-only and no direct
view crosses into R. Snapshot/decode helpers return ordinary copied R values.

Internal-only `.Call` bindings may support:

```text
authority construction and fingerprint
record encode/decode/validate/snapshot
memory-store create/insert/finalize/lookup snapshot/stats/close
disk-store create/insert/finalize/publish/open/lookup snapshot/stats/close
fault and constant-fast-hash test seams
```

No function is exported from `NAMESPACE`. XPtrs have a type tag, ABI major 1,
generation, state, and shared control block. Every entry point checks them
before dereference and holds a strong local guard for the call.

Explicit close and finalization use RAII and share no-throw cleanup. A completed
disk store is ordinary durable files plus its validated manifest and reopens in
a new R session after the original pointer is gone. A store exceeding R's safe
raw-vector size is never materialized as one R object.

