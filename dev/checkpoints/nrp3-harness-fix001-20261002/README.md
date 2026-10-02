# NRP3 disabled harness FIX001 — source checkpoint

This archive preserves the exact reviewed source for the **R1/R2/R6 disabled-source and guarded fake-contract repair milestone**, accepted with a scoped Pro PASS on 2026-10-02. It is a development checkpoint, not a release or full harness/controller acceptance.

## Contents and provenance

- `WORKTREE/`: 113 previously accepted source/context files at their original relative paths.
- `HARNESS/` and `LIB/`: five exact FIX001 candidate files plus the two unchanged guard/runner files.
- `MANIFEST.json`: SHA-256 and size for each of these 120 files.
- `ACCEPTANCE.json`: exact review-package identities, evidence summary, and retained limitations.

Files are copied byte-for-byte; no implementation changes or tests were made to prepare this checkpoint. This selected snapshot does not contain the complete 996-file worktree, BUILD/RUNS material, operational control state, transcripts, or full review archives. Those remain in the original local evidence store. It is **not a standalone runnable stage**. In particular, the wrapper retains its original stage-specific paths and must not be run from this archive.

The Linux engineering lineage is based on `7a90d33`, which was not present in the GitHub clone at archiving time. This archive branch is based on GitHub main `e847dd0cc4bc8026cd75a34d2ca75be1b4fe0771`; nesting under this directory preserves that distinction and does not replace the package implementation.

## What passed

- **R1:** a spawn exception retains unknown possible-child ownership rather than asserting no child exists.
- **R6:** conservative ownership survives interruptible wait; abort copies bounded previously recorded state, without a second cleanup. An existing non-None returncode is also used for release within the specified fake-process contract; this is not native reaper or identity evidence.
- **R2:** reference232 plus separately mandatory lazy2 gives a 234-name refusal universe. The production harness remains disabled (`HARNESS_ENABLED=False`, `KNOWN_UNSERVED_NAMES_SHA256=None`).

Recorded final results cover 52 explicit IDs per interpreter (Python 3.10.16 and 3.8.10), 104 OK total. **HW01 was not rerun and is not qualified for these final bytes.** Pro performed static review and read existing records; it did not rerun submitted code.

## Limits retained with the seal

The current audit FAIL/PASS records and predicate correction are retained locally. I1 test source is a hash-matching reconstruction, not a contemporaneous original; the old complete R3 FAIL record remains permanently missing. Neither current records nor this archive repair that provenance gap.

Arbitrary throwing sinks, context create-then-raise, native returncode/reaper semantics, and arbitrary statement-interruption snapshots remain outside this acceptance. HB01 covers an execution subset; pinning 17 files does not prove execution of every module. Guard self-reports and worker-hosted logs do not prove host isolation. R7 diagnostic fallback and R8 conservative label limits remain. Full details are in `ACCEPTANCE.json`.

Cumulative usage remains 96/128 wrapped calls and 2/3 repair iterations. The remaining budget is not authorization to resume.

**Native/canary/NX1–NX3, formal experiments, StageB, Attempt008, backend selection, merge and release remain on HOLD. `NATIVE_STORAGE_QUALIFIED=false`.** A future stage needs a separately reviewed scope and explicit authorization. This archival push does not grant execution authority.
