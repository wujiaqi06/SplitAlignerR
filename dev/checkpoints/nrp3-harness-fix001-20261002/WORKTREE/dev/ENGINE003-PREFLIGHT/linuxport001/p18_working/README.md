# P17-FIX002 direct-child custody implementation repair

This is `p17_fix002_closeout001`, the versioned successor of `p17_fix002`,
which is itself the versioned successor of the frozen `p17_fix001` source set.
The `p17_fix002` step changes exactly one behaviour, the P17FIX001-WORK-F01
primary-record handoff in `native_owner_controller.py`, plus the runner,
checklist and manifest support that change requires. Relative to the original
`p17_fix001`, 5 of the 17 files changed — `README.md`,
`SOURCE_ISOLATION_MANIFEST.json`, `STATIC_CHECKLIST.json`,
`native_owner_controller.py` and `pure_candidate_runner.py` — and the other 12,
including the five exact P14 dependency copies, stay byte-identical to
`p17_fix001`.

Relative to `p17_fix002`, this closeout copy changes documentation and manifest
metadata only: exactly `README.md` and `SOURCE_ISOLATION_MANIFEST.json` differ.
Every Python file, `SUPPLIED_FIXTURES.json` and `STATIC_CHECKLIST.json` are
byte-identical to `p17_fix002`. No behaviour, extraction definition, AST
authority pin or native contract was changed by the closeout.

`PureDirectChildController.capture_primary_failure` now returns the exact
`PrimaryFailureRecord` it retains as `_primary_record`. Its
`CAPTURE_PRIMARY_FAILURE` report is generated and logged separately by
`_log_primary_report`, so a report dictionary is never returned as authority
and a report-formatting failure can no longer replace or discard the retained
primary. `NativeOwnerController.capture_primary_failure` forwards that identical
object and revalidates its exact type and identity, so the native catch path in
`acquire_register_prove_direct_child` satisfies the unchanged exact-identity
requirement of `record_primary_and_rollback` without reaching into
`core._primary_record`. Both rollback consumers and
`retain_secondary_rollback_failure` were strengthened, not weakened: they now
require exact type as well as exact identity. Origin classification, the native
proof guard, `RuntimeBindings.validate_native`, capability provenance, raw
primary/context/cause/traceback retention and row/token custody are unchanged.

One behaviour remains bounded and unresolved: a failure raised inside
`PrimaryFailureRecord.__init__` itself still propagates. The raw primary and its
token stay retained, but no authority object exists at that point, and none is
fabricated. This is not a claim of arbitrary-failure resilience.

No candidate, native or runtime execution was performed for P17-FIX002 or for
this P17-FIX002 closeout. The added runner checks close the P17-FIX001
producer-to-consumer coverage gap but have not been run; they require a
separately authorized bounded round. The closeout used static AST, data and
byte checks only.

The remaining text below describes the design inherited unchanged from
P17-FIX001.

This versioned development root implements the accepted P16-FIX001 design. It
does not activate the implementation, change the public package, or authorize a
live pidfd fixture.

The production shell retains the exact P01 pre-open and post-register checks,
one provider-owned raw integer FD, exact public REGISTER/BEGIN/COMPLETE events,
a controller-held capability authority, internally issued prepare/capture/proof/
view capabilities, a non-owning view, origin-aware primary preservation, sticky
external-submission STOP enforcement, and a single admitted rollback callback.
Invalid normalization retains the raw observation and primary without COMPLETE.
The five P14 dependencies are byte-identical copies.

`pure_candidate_runner.py` never imports this directory as modules. It parses
and extracts only the allowed pure definitions listed in
`SOURCE_ISOLATION_MANIFEST.json`, loads the unchanged copied Ledger/common
definitions by the same mechanism, and runs exactly 12 supplied cases. The
fixture losslessly nests the original D01-D06 JSON and adds H01-H04 external-
submission negatives plus N01-N02 invalid-normalization negatives. The raw
FD/PID values and the provider digest of 64 `a` characters remain supplied
fixture premises.

Static-only in P17-FIX001: every real `NativeSyscalls`/`RuntimeBindings` construction,
native provider and guard construction, pre-open/post-register host proof,
authentic caught exception path, proof/view/diagnostic failure path, pidfd open,
`os.close`, owning `PidfdHandle`, child/reap/wait/signal/receive/transfer, and
formal008 behavior. The source-isolated cases construct only pure data,
capability, custody-transition, adapter, and controller-core objects; their four
original callbacks plus three new callbacks are inert Python callables. The two
invalid-normalization callbacks return integer zero or raise a supplied fresh
`ValueError`; neither is represented as a native failure.

D06 alone constructs and submits the invalid REGISTER in this runner, then
passes the actual Ledger reply to shared production reconciliation while keeping
captured FD 41 in custody metadata. Production `register_captured` always builds
its request from the retained row FD and contains no D06/41/-1 fixture logic.

P05-F01 and P08-G01–G10 remain OPEN. Process exit, reap, EBADF and descriptor
snapshots never confirm close. Public `v0.1.0`, Attempt006, Mac007, Linux008 and
P18–P50 retain the Work-order statuses.
