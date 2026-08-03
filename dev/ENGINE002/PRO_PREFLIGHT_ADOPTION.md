# Pro preflight blocker adoption

The byte-identical Pro review is preserved as
`evidence/SAR_PRO_ENGINE002_PREFLIGHT_REVIEW_20260803.md`; its verified SHA-256
is `72dfd3d3e88cc167e8ea0178ee8deb99205877870f1fa37b35aacdbc8dd582b2`.

| blocker | frozen contract | implementation target | verification target | current state |
|---|---|---|---|---|
| E2-B01 complete store wire format | `ENGINE002_STORE_V1.md`, `ENGINE002_ATOMIC_PUBLICATION.md` | store/index/footer/manifest and streaming checksum modules | independent plan/store golden fixtures and region corruption tests | CLOSED LOCALLY; three-platform replay pending |
| E2-B02 canonical record conventions | `ENGINE002_PLAN_RECORD_V1.md` | `engine002_plan_codec.*`, authority binding, endian/checked-math helpers | 1,974/1,974 exact reference comparisons and byte-identical re-encode | CLOSED LOCALLY; three-platform replay pending |
| E2-B03 create/open and view lifetime | `ENGINE002_LIFECYCLE_CONTRACT.md`, `ENGINE002_R_CPP_BOUNDARY.md` | BUILDING/FINALIZED/OPEN_VALIDATED/CLOSED stores, guarded XPtrs and pins | lifecycle, pin, repeat-close, durable reopen, direct-access probe | CLOSED LOCALLY; new-session and hosted replay pending |
| E2-B04 hard LRU and oversized record | lifecycle and benchmark contracts | deterministic charged cache, intrusive O(1) victim order, pinned eviction exclusion, one-plan scratch and planner sub-budgets | budget matrix plus 100k RSS/high-water/counter stress | CLOSED LOCALLY; hosted replay pending |
| E2-B05 atomic publication | `ENGINE002_ATOMIC_PUBLICATION.md` | exclusive binary writer, structural revalidation, POSIX/Windows no-replace, manifest-last protocol | all 15 stages, no-clobber, missing-manifest and corrupt-component rejection | PARTIAL: short-write, ENOSPC, interrupt and Windows replay pending |
| E2-B06 identity and collision seam | `ENGINE002_IDENTITY_REGISTRY.md` | SHA-256/XXH64, authority/pattern/registry/semantics/store identities implemented; exact-key maps | public reference vectors and constant-bucket exact-pattern test | PARTIAL: explicit injectable fast-hash seam absent because production identity maps do not use fast hash |
| E2-B07 authority and benchmark rubric | `ENGINE002_BENCHMARK_CONTRACT.md`, work order sections 16-19 | codec/store benchmark harness | authority 1,974 PASS; 10k/100k three-repetition runtime/RSS PASS | PARTIAL: 2/4-GiB and three-platform gates pending |

This matrix is updated only with evidence paths as later ordinary commits close
each implementation and test obligation. No blocker is called closed merely
because its specification now exists.
