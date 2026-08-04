# ENGINE002-FIX001B implementation

## Scope

ENGINE002-FIX001B repairs the existing internal incremental SHA-256 state
machine so that `TruthPlanStore-v1.0` implements the standard SHA-256 contract
already required by its frozen wire specification.  It does not introduce a
new digest, schema, public API, scientific state, mapper, or interpretation.

Frozen base:

```text
b96634c7f43307102714fc2e13dd8780e2126b69
tree 64c7e4ef231e637e264abf5ca19d696979c39c06
```

The certified release remains outside this development checkpoint:

```text
v0.1.0 -> 17a0927095c7a067817bf598a2556cbe7348a6d0
```

## Repair

`src/engine002_hash.cpp` now preserves an existing partial 64-byte block when
the next update is insufficient to complete it.  It completes and compresses
exactly one old partial block when possible, then consumes full new blocks and
retains the final partial bytes.  Checked state transitions require:

```text
buffered_ <= 63
total_ <= UINT64_MAX / 8 before bit-length conversion
buffered_ == total_ mod 64
```

`update(nullptr, 0)` remains accepted without invalid pointer arithmetic;
`update(nullptr, n)` for nonzero `n` is rejected with the existing typed
invalid-argument condition.  `digest()` remains non-mutating, repeatable, and
does not prohibit later updates.

## Failure discipline

The first hosted replay exposed one test-tool portability defect: the
independent C++ SHA probe used Windows text-mode standard streams for a binary
protocol.  Production package/check, installed tests, 1,974-authority replay,
Windows physical-store gates, and Pro's exact MRE had already passed in that
job.  The probe was corrected in a separate ordinary commit by selecting
binary mode on Windows; no production source changed.  The complete mandatory
matrix was then replayed at the corrected commit.

That replay exposed a second, separately classified blocker: GCC 13 could not
prove that the buffered-byte index used during digest padding was at most 63,
despite the typed invariant already guarding every valid state.  The Linux job
therefore completed at workflow level but its raw `R CMD check` result was one
WARNING, so it was not accepted as final evidence.  A separate narrow
production follow-up copied `buffered_` into a checked local bounded value
before indexing the 128-byte tail.  This did not change any reachable valid
digest behavior.  The full platform, authority, differential, sanitizer, and
comparison matrix was replayed again at
`9588400014a65170bc7dbb718817d9f258237f9d`; every mandatory release
platform then reported `R CMD check: Status OK`.

The maintained independent aggregate checker also underwent a local
self-audit before CI: a Python XXH64 tail rotation omitted the required
64-bit mask.  That was a test defect, not a production discrepancy.  The
checker was repaired before its CI commit, and standard SHA-256 remains
provided solely by Python `hashlib`.

## Commit sequence

```text
50eb182169ce9cd6ffaaf319fb4ad0b7f8064311  FIX001B-SHA
0479ea0fd86d859fc69b5affd73e1a60e3aefcb6  FIX001B-UNIT
65ebc05b10c40c521720c6a1716b7e84fdfcef0e  FIX001B-REGEN
83fd7ac75812a1272f31a85986abfd60a2db8ea2  FIX001B-CI
80c6c24a5abf82150e5fdf1426810208673c4dde  FIX001B-CI-FOLLOWUP
9588400014a65170bc7dbb718817d9f258237f9d  FIX001B-SHA-FOLLOWUP
FIX001B-EVIDENCE                                final evidence commit
```

The final evidence commit and tree cannot be self-recorded in a file it
contains; they are frozen by the external handoff manifest, bundle, ZIP
manifests, and SHA-256 sidecars.
