"""Persistent dispatch journal and controller acceptance envelope.

DEV007_FIX002 protocol, extended in DEV007_FIX003 with an independent
progression store, typed reconciliation and persisted cleanup evidence.
A small injectable protocol, not a framework.

Scope.  One stable scope binds (run_generation, input_identity,
dispatcher_owner).  Records live in TWO independent storage ports:

  progression store (high-watermark, written BEFORE the journal suffix):
    GENESIS                written first by explicit initialize_scope()
    NNNNNN.RESERVED        intent reservation of dispatch NNNNNN, written
                           before its IN_FLIGHT; hash-chained to the previous
                           RESERVED (or GENESIS) and to the digest of every
                           journal record of dispatch NNNNNN-1

  journal store:
    ANCHOR                 written by initialize_scope(), binds GENESIS
    NNNNNN.IN_FLIGHT       before ANY spawn; binds its RESERVED record
    NNNNNN.CLEANUP         successful completion-cleanup + validation evidence
                           (written before the acceptance envelope)
    NNNNNN.FINAL           ACCEPTED (binds flight, cleanup, envelope, raw) or STOP
    NNNNNN.RECONCILED      typed operator reconciliation (see below)

Refusal is the default.  state() reconstructs both stores and is READY only
if GENESIS/ANCHOR bind each other and the scope, the reservation chain is
contiguous and unbroken, no journal record exists beyond the progression
high-watermark, and every reserved dispatch is ACCEPTED (with a valid CLEANUP
and bindings) or validly RECONCILED.  So a lost latest IN_FLIGHT/FINAL, an
interrupted begin (RESERVED without IN_FLIGHT), a truncated/corrupt record in
either store, a lost ANCHOR or GENESIS, a rolled-back progression store and a
rewritten/removed earlier dispatch record all refuse.  A fresh run id, owner
label, output path or in-memory latch cannot change this: the scope, not the
run, is the key.  Every record is checked for its exact kind, seq and typed
fields on every read, not only on write.

Storage model and trusted persistence assumptions (explicit bound):
  * each port: list(); read(name) -> bytes | None (None = absent, raise =
    unreadable); create_new(name, data): no-clobber, all-or-nothing;
  * the two ports are independent failure domains: a deletion/rollback/
    corruption affects at most one of them at a time;
  * EXCLUDED, inherently undetectable: an exact simultaneous rollback of ALL
    independent durable evidence to an earlier consistent cut (both stores and
    any output file), including deletion of both stores entirely followed by
    a new explicit initialize_scope().  Explicit initialization is an operator
    act that asserts the scope was never used before; it is not verified.
  * MemoryStorage satisfies the model in simulation (and injects failures and
    CrashCut process death).  FileStorage is UNQUALIFIED (no directory-fsync
    proof, no cross-process lock, no disk-full/crash experiment, no_delete
    NOT_ENFORCED); NATIVE_STORAGE_QUALIFIED = False keeps native use denied.

Reconciliation.  An operator-supplied, typed record that must positively
resolve EVERY obligation in RECONCILIATION_OBLIGATIONS, bound to the
original run id, scope generation/owner and the exact reservation/flight/
final record hashes.  Unknown kinds, NUMERIC_PID_ABSENT, resolved != True,
missing/extra/duplicated obligations and stale/wrong run all refuse, both in
reconcile() and whenever state() re-reads the record.  It is modeled operator
evidence, NOT proof that anyone observed native resolution.

Acceptance contract.  verify_controller_acceptance() answers "is this
historical result accepted?": it re-validates the scope anchor/genesis, the
reservation chain and all records of dispatches 1..seq (the referenced
prefix), the flight/cleanup/final/envelope bindings, the persisted cleanup
predicates and the raw bytes.  It deliberately ignores dispatches after
seq, so later unresolved work neither invalidates nor is authorized by an
intact older result.  Permission to start new work is ONLY state()['ready'].

Caller-bound transaction (DEV007_FIX005, protocol CALLER_BOUND_COMMIT/v3).
One transaction owner (the coordinator: the orchestrator adapter, or
launch_request itself for a single caller-supplied request / the CLI):

  1. reserve_current_dispatch(): pure admission (digest, state()['ready'],
     fresh raw/output paths) with ZERO writes on refusal; then RESERVED +
     IN_FLIGHT bind the caller's request digest, seq, raw/output paths and
     display run id.  The reservation sha256 is the durable ticket id.
  2. The lower layer receives only a DispatchTicket: authority to execute
     THAT reserved dispatch once (check_execution() before spawn), to publish
     its prepared evidence (CLEANUP: completion bound to the ticket, raw
     bytes, executed request digest, validated result) and to record STOP.
     It cannot pick another request/seq and cannot write FINAL ACCEPTED.
  3. commit_current_dispatch(): verify_prepared_dispatch() (never depends on
     a FINAL) checks caller binding, ticket/scope/seq/paths/receipt, raw
     bytes against the persisted CLEANUP, the ticket-bound resolved
     completion, the caller's result-identity rule and "no extra dispatch";
     only then the acceptance envelope and the unique FINAL ACCEPTED (commit
     label COORDINATOR_VERIFIED_CURRENT_DISPATCH) are written, and only
     afterwards is the result returned to consumers/ledgers.  Any refusal
     after reservation writes a STOP carrying the binding violation, or, if
     that write fails, leaves the non-terminal IN_FLIGHT; both refuse.
  4. verify_committed_dispatch(): read-only recovery of a committed result by
     the SAME ticket (lost return notification): no rerun, no recleanup.

Legacy records (no protocol label, i.e. FIX004-and-earlier below-caller
ACCEPTED) are LEGACY_BELOW_CALLER_EXECUTION_VALIDATION_HISTORY: they are never
read as complete acceptance and a scope containing them refuses (it is not
reinitialized; only a new explicit scope may be initialized by an operator).

Reconciliation of a v3 dispatch additionally requires a disposition that
cites the original scope/seq, the expected request digest, the observed
evidence (binding violation or prepared CLEANUP, if any) and an explicit
controller decision; the resource-closure facts alone never reopen it.
Run ids are display labels, not binding keys.

Effect-handoff slot (DEV_PHASE_EVIDENCE001, phase protocol EFFECT_HANDOFF/v1,
carried by every new RESERVED/IN_FLIGHT).  Each dispatch has ONE authority
slot NNNNNN.PHASE, created no-clobber first in the progression store (the
decisive write) and then mirrored with identical bytes in the journal store.
Exactly one of two values can ever occupy it:

  EFFECT_PERMITTED    written by DispatchTicket.check_execution() after every
                      binding check and BEFORE check_execution returns; the
                      lower controller spawns only after it returns.  Any
                      failure of either write refuses the spawn.
  CLOSED_ZERO_EFFECT  written by DispatchTicket.close_zero_effect(), called
                      only by the lower controller's own pre-effect refusal
                      path (launch_request: admission or ticket-check refusal
                      before any spawn/acquisition), binding the controller
                      phase and cause to the ticket/seq/scope/flight.

Proof obligations at each handoff:
  * caller -> launcher: the ticket exists only after RESERVED + IN_FLIGHT are
    durable (reserve()); a launcher never holds authority for an unrecorded
    dispatch.
  * launcher -> effect: an effect needs EFFECT_PERMITTED durable in both
    stores first; so an empty slot proves no sanctioned effect happened, and
    a CLOSED_ZERO_EFFECT slot (created while the slot was empty, the dispatch
    open and the ticket object never permitted) proves none ever can: any
    retained, copied or reconstructed ticket's later check_execution fails on
    the durable slot (no-clobber), on the FINAL/RECONCILED record and, once a
    later dispatch exists, on "not the latest".
  * zero-effect -> reconciliation: ROOT_NEVER_SPAWNED is accepted only for a
    reservation whose ticket was never issued (no IN_FLIGHT) or whose slot is
    CLOSED_ZERO_EFFECT in BOTH stores; the disposition must cite the slot's
    sha256 and cause.  A generic COORDINATOR_REFUSED, an empty slot, an
    unmirrored or EFFECT_PERMITTED slot, or an older v3 dispatch without the
    phase protocol never supports ROOT_NEVER_SPAWNED, and a CLOSED_ZERO_EFFECT
    slot refuses any fact that claims a process/capability identity (nothing
    is fabricated).  Nothing reconciles automatically.
Trust bound: code that spawns outside launch_request's ticket path (a
launcher wrapper acting on its own) is outside the internal interface
contract; this is not a sandbox and carries no cryptographic claim.

Terminal history is write-protected (DEV_PHASE_EVIDENCE001_FIX001).  Every
ticket-side durable mutation service (_claim_slot, _record_prepared, finish,
_commit_accepted) first re-reads both stores (_guard_open_write) and refuses,
writing nothing, unless the target dispatch is the latest reservation, its
RESERVED/IN_FLIGHT are the ticket's and it has no FINAL and no RECONCILED
(and, for its own kind, no record yet).  So a retained, copied, recovered or
reconstructed ticket, including a lower-controller fallback STOP, can never
append to a resolved dispatch or to one a later dispatch's
prior_dispatch_digest already binds.  An open, unresolved dispatch still
gets its STOP (or keeps the non-terminal IN_FLIGHT if that write fails).
Bound: single dispatcher; an operator reconcile() interleaved between the
guard and the create_new of a concurrent holder is outside that model and
fails closed (STALE_RECORD_BINDING), it is not claimed to be prevented.

Historical compatibility (versioned, read-only).  Each dispatch is validated
under the protocol its own RESERVED declares.  A CALLER_BOUND_COMMIT/v3
reservation WITHOUT phase_protocol (FIX005 era) whose RECONCILED passes the
current rules is current.  If it fails the current rules only for
NO_ZERO_EFFECT_PHASE_EVIDENCE, it is re-checked under the declared
HISTORICAL_V3_CONTRACT (FIX005: ROOT_NEVER_SPAWNED only over no FINAL or a
STOP reason in NEVER_SPAWNED_REASONS, with the exact v3 disposition); if
valid it is HISTORICAL_ONLY: the history view (accepted_dispatch /
verify_controller_acceptance / load_ticket) may read accepted results of
that prefix, but it confers no current authority: state(), reserve(),
open_dispatch() and reconcile() refuse with HISTORICAL_ONLY_RECONCILIATION
(not reconcilable, no phase proof is fabricated, no record is rewritten).
A phase-protocol dispatch is always judged by the current rules, and a
phase-protocol dispatch after a HISTORICAL_ONLY one refuses even in the
history view (new code can never have reserved it).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

JOURNAL_SCHEMA = "SplitAlignerR/ENGINE003DispatchJournal/v2"
ACCEPTANCE_SCHEMA = "SplitAlignerR/ENGINE003ControllerAcceptance/v2"
NATIVE_STORAGE_QUALIFIED = False
FINAL_STATUSES = ("ACCEPTED", "STOP")
JOURNAL_KINDS = ("IN_FLIGHT", "PHASE", "EFFECT", "CLEANUP", "FINAL",
                 "RECONCILED")
RECONCILABLE = ("RESERVED_DISPATCH_UNRESOLVED", "PRIOR_DISPATCH_IN_FLIGHT",
                "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
RECONCILIATION_TRUST = "OPERATOR_ASSERTED_MODELED_EVIDENCE"
DISPATCH_PROTOCOL = "CALLER_BOUND_COMMIT/v3"
COMMIT_AUTHORITY = "COORDINATOR_VERIFIED_CURRENT_DISPATCH"
PREPARED_SCHEMA = "SplitAlignerR/ENGINE003PreparedDispatch/v1"
LEGACY_LABEL = "LEGACY_BELOW_CALLER_EXECUTION_VALIDATION_HISTORY"
# The only decision a disposition may record: the dispatch has no accepted
# result; nothing is retried or resampled and the sampling plan is unchanged.
DISPOSITION_DECISIONS = ("VOID_DISPATCH_NO_RESULT_NO_AUTO_RESAMPLE",)
# FIX005 history: STOP reasons it treated as spawn-free.  No longer used as
# evidence: a STOP reason is a label, the effect-handoff slot is the proof.
NEVER_SPAWNED_REASONS = ("SPAWN_FAILED", "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
# The only historical contract: FIX005 v3 reservations without phase_protocol.
HISTORICAL_V3_CONTRACT = "FIX005_V3_STOP_REASON"
PHASE_PROTOCOL = "EFFECT_HANDOFF/v1"
PHASE_VALUES = ("EFFECT_PERMITTED", "CLOSED_ZERO_EFFECT")
ZERO_EFFECT_FACTS = {"ROOT_PROCESS": "ROOT_NEVER_SPAWNED",
                     "KNOWN_DESCENDANTS": "NO_KNOWN_DESCENDANT",
                     "CAPABILITY_CUSTODY": "NO_CAPABILITY_ACQUIRED",
                     "OUTPUT_COLLECTOR": "COLLECTOR_NEVER_STARTED",
                     "RSS_SAMPLER": "SAMPLER_NEVER_STARTED"}
# NRP-2: post-spawn identity handoff, declared by the RESERVATION (before any
# effect).  NNNNNN.EFFECT (journal store) is written by the lower controller
# from its own modeled acquisition (RunContext.attach_root) and before any
# sampler: attempted effect, observed root, registered custody and the root
# identity AS REPORTED by the termination provider (None when the provider
# reports none; never invented).  It is a model record: not proof of real
# persistence, current ownership or process identity.
# Recorded-identity semantic (Astra NRP2 decision 2026-09-29): a NEW
# identity-bearing reconciliation must cite the one controller-recorded root
# token.  That token binds the operator's modeled descendant/custody
# assertions to THIS dispatch; it is not evidence of each descendant's or
# lease's own identity and proves no actual resource fact (trust stays
# OPERATOR_ASSERTED_MODELED_EVIDENCE).  A dispatch that may have had an
# effect but has no recorded token (identity-less provider, lost/absent
# EFFECT, pre-identity protocol) gets neither a positive identity
# reconciliation nor ROOT_NEVER_SPAWNED: every current provider without
# root_identity has NO positive post-effect reconciliation path.  This is a
# deliberate fail-closed limitation and a native-activation blocker, not a
# claim that all future recovery is impossible (a qualified provider
# identity/provenance and a reviewed recovery kind would be separate, newly
# authorized work).  Scope switch/reinitialization is not a workaround.
# Pre-identity history keeps its original readable status; it is never
# upgraded and never newly reconciled positively.  Trust bound unchanged:
# same-process code holding journal/ticket internals (e.g. a copied ticket
# flagged effect_permitted) is outside the internal interface contract; no
# provenance authentication is claimed.
EFFECT_PROTOCOL = "POST_SPAWN_IDENTITY/v1"
EFFECT_EVIDENCE_CLASS = "MODEL_RECORD_NOT_PROOF_OF_PERSISTENCE_OR_OWNERSHIP"
IDENTITY_PROVENANCE = ("MODELED_INJECTED",)     # no native provider exists
EFFECT_FIELDS = ("attempted_effect", "observed_root", "root_authority_state",
                 "custody", "identity", "controller_phase")
# obligation -> {positive kind: identity token required}
RECONCILIATION_OBLIGATIONS = {
    "ROOT_PROCESS": {"ROOT_REAPED_IDENTITY_VERIFIED": True,
                     "ROOT_NEVER_SPAWNED": False},
    "KNOWN_DESCENDANTS": {"ALL_KNOWN_EXITED_IDENTITY_VERIFIED": True,
                          "NO_KNOWN_DESCENDANT": False},
    "CAPABILITY_CUSTODY": {"ALL_ACQUISITIONS_LEASES_CLOSED": True,
                           "NO_CAPABILITY_ACQUIRED": False},
    "OUTPUT_COLLECTOR": {"COLLECTOR_EOF_OR_CLOSED": False,
                         "COLLECTOR_NEVER_STARTED": False},
    "RSS_SAMPLER": {"SAMPLER_STOPPED": False,
                    "SAMPLER_NEVER_STARTED": False},
}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class JournalRefused(Exception):
    def __init__(self, code: str, detail: Any = None) -> None:
        super().__init__(f"{code}:{detail}" if detail is not None else code)
        self.code, self.detail = code, detail


class CrashCut(BaseException):
    """Simulated process death at a durable boundary (not an Exception)."""


class MemoryStorage:
    """Injected storage.  fail: {(op, name_prefix): exception};
    truncate: {name_prefix: n} persists the first n bytes then raises;
    crash_after: after that many successful create_new calls every further
    operation raises CrashCut (models the process dying)."""

    guarantees = {"no_clobber_create": "SIMULATED", "atomic_visibility":
                  "SIMULATED", "durability": "SIMULATED_ONLY",
                  "no_delete": "SIMULATED_TESTS_DELETE_EXPLICITLY"}

    def __init__(self, fail=None, truncate=None, crash_after=None,
                 records=None):
        self.records: Dict[str, bytes] = dict(records or {})
        self.fail = dict(fail or {})
        self.truncate = dict(truncate or {})
        self.crash_after = crash_after
        self.creates = 0
        self.ops: list = []

    def _inject(self, op: str, name: str) -> None:
        if self.crash_after is not None and self.creates >= self.crash_after:
            raise CrashCut(f"{op}:{name}")
        for (fop, prefix), exc in self.fail.items():
            if fop == op and name.startswith(prefix):
                raise exc

    def list(self):
        self._inject("list", "")
        return sorted(self.records)

    def read(self, name):
        self._inject("read", name)
        return self.records.get(name)

    def create_new(self, name, data):
        self._inject("create", name)
        if name in self.records:
            raise FileExistsError(name)
        for prefix, n in self.truncate.items():
            if name.startswith(prefix):
                self.records[name] = bytes(data[:n])
                self.ops.append(("create_truncated", name))
                raise OSError(28, "injected ENOSPC after partial write")
        self.records[name] = bytes(data)
        self.creates += 1
        self.ops.append(("create", name))


class FileStorage:
    """Directory-backed port (UNQUALIFIED; see module docstring)."""

    guarantees = {"no_clobber_create": "OS_LINK_EEXIST_UNQUALIFIED",
                  "atomic_visibility": "LINK_OF_COMPLETE_TEMP_UNQUALIFIED",
                  "durability": "UNQUALIFIED_NO_DIR_FSYNC_PROOF",
                  "no_delete": "NOT_ENFORCED"}

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def list(self):
        return sorted(p.name for p in self.root.iterdir()
                      if not p.name.startswith(".tmp-"))

    def read(self, name):
        path = self.root / name
        return path.read_bytes() if path.exists() else None

    def create_new(self, name, data):
        publish_no_clobber(self.root / name, data)


def publish_no_clobber(path: Path, data: bytes) -> None:
    """Complete temp file, fsync, then os.link (EEXIST if present)."""
    path = Path(path)
    tmp = path.with_name(f".tmp-{path.name}-{os.getpid()}-{id(data)}")
    with open(tmp, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _need(record: Mapping[str, Any], name: str, **types: Any) -> None:
    for field, kind in types.items():
        value = record.get(field)
        if kind == "sha":
            ok = isinstance(value, str) and len(value) == 64
        elif kind == "sha?":
            ok = value is None or (isinstance(value, str) and len(value) == 64)
        elif kind == "str":
            ok = isinstance(value, str) and bool(value)
        else:
            ok = isinstance(value, kind) and not isinstance(value, bool)
        if not ok:
            raise JournalRefused("RECORD_MALFORMED", f"{name}:{field}")


def validate_reconciliation(record: Mapping[str, Any], *, scope: Mapping[str, Any],
                            run_id: str, reservation_sha256: str,
                            flight_sha256: Optional[str],
                            final_sha256: Optional[str],
                            final: Optional[Mapping[str, Any]] = None,
                            disposition: Optional[Mapping[str, Any]] = None,
                            zero_effect: Optional[str] = None,
                            identity: Optional[Mapping[str, Any]] = None) -> None:
    """Typed reconciliation check, used on write AND on every read.  For a
    v3 dispatch, disposition is the required disposition_binding() and
    zero_effect the reader's durable effect-handoff evidence: "NOT_ISSUED"
    (no IN_FLIGHT: no ticket ever existed), "CLOSED_ZERO_EFFECT" (mirrored
    slot) or "UNPROVEN" (anything else)."""
    def bad(detail: str) -> JournalRefused:
        return JournalRefused("RECONCILIATION_INVALID", detail)
    if record.get("original_run_id") != run_id or record.get("cited_run_id") != run_id:
        raise bad("RUN_MISMATCH")
    if (record.get("run_generation") != scope["run_generation"]
            or record.get("dispatcher_owner") != scope["dispatcher_owner"]):
        raise bad("SCOPE_GENERATION_OR_OWNER_MISMATCH")
    if (record.get("reservation_sha256") != reservation_sha256
            or record.get("flight_sha256") != flight_sha256
            or record.get("final_sha256") != final_sha256):
        raise bad("STALE_RECORD_BINDING")
    if record.get("trust") != RECONCILIATION_TRUST:
        raise bad("TRUST_LABEL")
    if not isinstance(record.get("operator"), str) or not record["operator"]:
        raise bad("OPERATOR")
    obligations = record.get("obligations")
    if not isinstance(obligations, dict) or set(obligations) != set(
            RECONCILIATION_OBLIGATIONS):
        raise bad("OBLIGATION_SET")
    for name, fact in obligations.items():
        allowed = RECONCILIATION_OBLIGATIONS[name]
        if not isinstance(fact, dict) or set(fact) - {"kind", "resolved", "run_id",
                                                      "identity"}:
            raise bad(f"{name}:FACT_SHAPE")
        if fact.get("kind") not in allowed:
            raise bad(f"{name}:KIND")
        if fact.get("resolved") is not True:
            raise bad(f"{name}:NOT_RESOLVED")
        if fact.get("run_id") != run_id:
            raise bad(f"{name}:RUN")
        if allowed[fact["kind"]] and not (isinstance(fact.get("identity"), str)
                                          and fact["identity"]):
            raise bad(f"{name}:IDENTITY")
    if (obligations["ROOT_PROCESS"]["kind"] == "ROOT_NEVER_SPAWNED"
            and obligations["KNOWN_DESCENDANTS"]["kind"] != "NO_KNOWN_DESCENDANT"):
        raise bad("CONTRADICTORY_FACTS")
    never = obligations["ROOT_PROCESS"]["kind"] == "ROOT_NEVER_SPAWNED"
    if zero_effect is None:     # FIX003-era direct callers only
        if never and final is not None and final.get("reason") not in NEVER_SPAWNED_REASONS:
            raise bad("CONTRADICTS_RECORDED_SPAWN")
    elif never and zero_effect not in ("NOT_ISSUED", "CLOSED_ZERO_EFFECT"):
        raise bad("NO_ZERO_EFFECT_PHASE_EVIDENCE")
    elif zero_effect == "CLOSED_ZERO_EFFECT" and any(obligations[k]["kind"] != v
                             for k, v in ZERO_EFFECT_FACTS.items()):
        # no spawn/acquisition happened: an identity fact would be invented
        raise bad("CONTRADICTS_ZERO_EFFECT_CLOSURE")
    if identity is not None:
        # NRP-2: every identity-bearing fact cites the recorded root identity
        # (EFFECT record); missing/None/different refuses, no fallback.
        for name, fact in obligations.items():
            if RECONCILIATION_OBLIGATIONS[name][fact["kind"]]:
                if identity.get("token") is None:
                    raise bad(f"{name}:NO_RECORDED_IDENTITY:{identity.get('source')}")
                if fact.get("identity") != identity["token"]:
                    raise bad(f"{name}:IDENTITY_NOT_RECORDED_IDENTITY")
    if disposition is not None:
        cited = record.get("disposition")
        if not isinstance(cited, dict):
            raise bad("DISPOSITION_MISSING")    # resource facts alone: refused
        if set(cited) != set(disposition) | {"decision", "controller"}:
            raise bad("DISPOSITION_SHAPE")
        for field, value in disposition.items():
            if cited.get(field) != value:
                raise bad(f"DISPOSITION_BINDING:{field}")
        if cited.get("decision") not in DISPOSITION_DECISIONS:
            raise bad("DISPOSITION_DECISION")
        if not isinstance(cited.get("controller"), str) or not cited["controller"]:
            raise bad("DISPOSITION_CONTROLLER")


def disposition_binding(scope_id: str, seq: int, reservation: Mapping[str, Any],
                        cleanup_sha256: Optional[str],
                        final: Optional[Mapping[str, Any]],
                        phase: Optional[Mapping[str, Any]] = None,
                        phase_sha256: Optional[str] = None,
                        effect: Optional[Mapping[str, Any]] = None,
                        effect_sha256: Optional[str] = None) -> Dict[str, Any]:
    """What a v3 reconciliation must cite: original scope/seq, the caller's
    expected request, the observed evidence (the STOP's binding violation,
    else the prepared CLEANUP, else none) and the STOP reason; for a
    phase-protocol dispatch also the effect-handoff slot value, its sha256
    and the recorded cause (only a mirrored slot counts as observed)."""
    violation = (final or {}).get("binding_violation")
    binding = {"scope_id": scope_id, "seq": seq,
               "expected_request_sha256": reservation["request_sha256"],
               "observed_binding_violation_sha256": (
                   None if violation is None else sha256(canonical(violation))),
               "observed_prepared_cleanup_sha256": cleanup_sha256,
               "stop_reason": (final or {}).get("reason")}
    if reservation.get("phase_protocol") == PHASE_PROTOCOL:
        binding.update(observed_phase=(phase or {}).get("phase"),
                       observed_phase_sha256=phase_sha256,
                       phase_cause_sha256=(
                           None if phase is None or phase.get("cause") is None
                           else sha256(canonical(phase["cause"]))))
    if reservation.get("effect_protocol") == EFFECT_PROTOCOL:
        ident = (effect or {}).get("identity")
        binding.update(observed_effect_sha256=effect_sha256,
                       observed_custody=(effect or {}).get("custody"),
                       observed_root_identity=None if ident is None else dict(ident))
    return binding


def validate_effect_evidence(evidence: Any) -> Dict[str, Any]:
    """Shape of the controller's post-spawn evidence (on write and read)."""
    def bad(detail: str) -> JournalRefused:
        return JournalRefused("EFFECT_EVIDENCE_INVALID", detail)
    if not isinstance(evidence, dict) or set(evidence) != set(EFFECT_FIELDS):
        raise bad("FIELDS")
    if evidence["attempted_effect"] != "SPAWN_RETURNED_PROCESS_OBJECT":
        raise bad("ATTEMPTED_EFFECT")
    root = evidence["observed_root"]
    if (not isinstance(root, dict) or set(root) != {"pid", "returncode_at_attach"}
            or not isinstance(root["pid"], int) or isinstance(root["pid"], bool)
            or not (root["returncode_at_attach"] is None
                    or (isinstance(root["returncode_at_attach"], int)
                        and not isinstance(root["returncode_at_attach"], bool)))):
        raise bad("OBSERVED_ROOT")
    state = evidence["root_authority_state"]
    if not isinstance(state, str) or not state:
        raise bad("ROOT_AUTHORITY_STATE")
    if evidence["custody"] != ("REGISTERED" if state == "ACQUIRED"
                               else "NOT_REGISTERED"):
        raise bad("CUSTODY")
    ident = evidence["identity"]
    if ident is not None and not (
            isinstance(ident, dict) and set(ident) == {"token", "provenance"}
            and isinstance(ident["token"], str) and ident["token"]
            and ident["provenance"] in IDENTITY_PROVENANCE
            and evidence["custody"] == "REGISTERED"):
        raise bad("IDENTITY")
    if evidence["controller_phase"] != "POST_SPAWN:ROOT_ACQUISITION":
        raise bad("CONTROLLER_PHASE")
    return dict(evidence)


def validate_cleanup_predicates(completion: Any, run_id: str) -> None:
    """The persisted successful completion-cleanup record itself."""
    def bad(detail: str) -> JournalRefused:
        return JournalRefused("CLEANUP_UNRESOLVED", detail)
    if not isinstance(completion, dict):
        raise bad("NOT_OBJECT")
    if str(completion.get("run_id")) != run_id:
        raise bad("RUN")
    checks = {
        "completion_resolved": completion.get("completion_resolved") is True,
        "root_reaped": completion.get("root_reaped") is True,
        "pipe_eof": completion.get("pipe_eof") is True,
        "context_closed": completion.get("context_closed") is True,
        "no_unresolved_reasons": completion.get("unresolved_reasons") == [],
        "sampler_stopped": (completion.get("sampler_stop") or {}).get("state")
        == "STOPPED",
        "descendants_resolved": (
            (completion.get("descendant_resolution") or {}).get("resolved") is True
            and completion["descendant_resolution"].get("live") == []
            and completion["descendant_resolution"].get("uncertain") == []),
        "tree_quiescence_not_claimed":
            completion.get("whole_process_tree_quiescent") == "NOT_CLAIMED",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise bad(",".join(failed))


class DispatchJournal:
    def __init__(self, storage: Any, *, run_generation: Any,
                 input_identity: str, dispatcher_owner: str,
                 progression: Any = None) -> None:
        self.storage = storage
        self.progression = progression
        self.scope = {"run_generation": run_generation,
                      "input_identity": input_identity,
                      "dispatcher_owner": dispatcher_owner}
        self.scope_id = sha256(canonical(self.scope))

    # -- initialization -------------------------------------------------
    def initialize_scope(self) -> None:
        """Explicit, legitimate first initialization only (GENESIS, then
        ANCHOR binding it).  Refuses if either store has any record."""
        if self.progression is None:
            raise JournalRefused("PROGRESSION_STORE_REQUIRED")
        if self.storage.list() or self.progression.list():
            raise JournalRefused("SCOPE_ALREADY_HAS_RECORDS")
        genesis = self._record("GENESIS", scope=self.scope)
        self.progression.create_new("GENESIS", genesis)
        self.storage.create_new("ANCHOR", self._record(
            "ANCHOR", scope=self.scope, genesis_sha256=sha256(genesis)))

    # -- reading --------------------------------------------------------
    def _raw(self, store: Any, name: str) -> bytes:
        try:
            raw = store.read(name)
        except CrashCut:
            raise
        except BaseException as error:
            raise JournalRefused("RECORD_UNREADABLE",
                                 f"{name}:{type(error).__name__}:{error}")
        if raw is None:
            raise JournalRefused("RECORD_LOST", name)
        return raw

    def _parse(self, raw: bytes, name: str, kind: str,
               seq: Optional[int] = None) -> Dict[str, Any]:
        try:
            value = json.loads(raw.decode("ascii"))
        except Exception:
            raise JournalRefused("RECORD_CORRUPT", name)
        if (not isinstance(value, dict) or value.get("schema") != JOURNAL_SCHEMA
                or value.get("scope_id") != self.scope_id):
            raise JournalRefused("RECORD_SCOPE_OR_SCHEMA_MISMATCH", name)
        if value.get("kind") != kind:
            raise JournalRefused("RECORD_KIND_MISMATCH", name)
        if seq is not None and (value.get("seq") != seq
                                or isinstance(value.get("seq"), bool)):
            raise JournalRefused("RECORD_SEQ_MISMATCH", name)
        if kind in ("RESERVED", "IN_FLIGHT"):
            _need(value, name, run_id="str", request_sha256="sha",
                  raw_path="str", output_path="str")
        if kind in ("IN_FLIGHT", "PHASE", "CLEANUP", "FINAL"):
            _need(value, name, run_id="str")
        return value

    def _load(self, name: str, kind: str, seq: Optional[int] = None,
              store: Any = None):
        raw = self._raw(self.storage if store is None else store, name)
        return raw, self._parse(raw, name, kind, seq)

    def _names(self):
        if self.progression is None:
            raise JournalRefused("PROGRESSION_STORE_REQUIRED")
        try:
            return self.storage.list(), self.progression.list()
        except CrashCut:
            raise
        except BaseException as error:
            raise JournalRefused("SCOPE_UNREADABLE",
                                 f"{type(error).__name__}:{error}")

    def _reconstruct(self, upto: Optional[int] = None,
                     open_last: bool = False,
                     historical: bool = False) -> Dict[str, Any]:
        """Raises JournalRefused; returns per-dispatch facts.  With upto,
        only the referenced prefix 1..upto is required to be resolved; with
        open_last, dispatch upto itself may be unresolved (prepared-evidence
        verification of the current ticket, which has no FINAL yet).  Only
        historical=True (read-only history view) admits a HISTORICAL_ONLY
        reconciliation, and then no later phase-protocol dispatch."""
        jnames, pnames = self._names()
        if not jnames and not pnames:
            raise JournalRefused("SCOPE_NOT_INITIALIZED")
        if "GENESIS" not in pnames:
            raise JournalRefused("PROGRESSION_GENESIS_LOST")
        if "ANCHOR" not in jnames:
            raise JournalRefused("ANCHOR_LOST_RECORDS_PRESENT")
        journal: Dict[int, set] = {}
        for name in jnames:
            if name == "ANCHOR":
                continue
            seq, _, kind = name.partition(".")
            if not (seq.isdigit() and len(seq) == 6 and kind in JOURNAL_KINDS):
                raise JournalRefused("UNKNOWN_RECORD", name)
            journal.setdefault(int(seq), set()).add(kind)
        reserved, phased = set(), set()
        for name in pnames:
            if name == "GENESIS":
                continue
            seq, _, kind = name.partition(".")
            if not (seq.isdigit() and len(seq) == 6 and kind in ("RESERVED", "PHASE")):
                raise JournalRefused("UNKNOWN_PROGRESSION_RECORD", name)
            (reserved if kind == "RESERVED" else phased).add(int(seq))
        high = max(reserved, default=0)
        if reserved != set(range(1, high + 1)):
            raise JournalRefused("RESERVATION_LOST",
                                 sorted(set(range(1, high + 1)) - reserved))
        if max(journal, default=0) > high:
            raise JournalRefused("PROGRESSION_ROLLBACK_JOURNAL_AHEAD",
                                 max(journal))
        if phased - reserved:
            raise JournalRefused("PHASE_WITHOUT_RESERVATION", sorted(phased - reserved))
        self._phased = phased
        genesis_raw, _ = self._load("GENESIS", "GENESIS", store=self.progression)
        _, anchor = self._load("ANCHOR", "ANCHOR")
        if anchor.get("genesis_sha256") != sha256(genesis_raw):
            raise JournalRefused("ANCHOR_GENESIS_MISMATCH")
        prev_sha, prior_digest = sha256(genesis_raw), None
        last = high if upto is None else upto
        if last > high:
            raise JournalRefused("RESERVATION_LOST", last)
        history, legacy_only = [], None
        for seq in range(1, last + 1):
            entry = self._dispatch(seq, journal.get(seq, set()), prev_sha,
                                   prior_digest)
            if legacy_only is not None and (
                    entry["reservation"].get("phase_protocol") == PHASE_PROTOCOL):
                raise JournalRefused("HISTORICAL_ONLY_RECONCILIATION", {
                    "seq": legacy_only, "later_phase_dispatch": seq})
            if entry.get("authority") == HISTORICAL_V3_CONTRACT:
                if not historical:
                    raise JournalRefused("HISTORICAL_ONLY_RECONCILIATION", {
                        "seq": seq, "contract": HISTORICAL_V3_CONTRACT})
                legacy_only = seq
            history.append(entry)
            if open_last and seq == last:
                break
            if entry["status"] not in ("ACCEPTED", "RECONCILED"):
                raise JournalRefused(entry["status"], {
                    "seq": seq, "run_id": entry["run_id"]})
            prev_sha, prior_digest = entry["reservation_sha256"], entry["digest"]
        return {"high": high, "history": history}

    def _dispatch(self, seq: int, kinds: set, prev_sha: str,
                  prior_digest: Optional[str]) -> Dict[str, Any]:
        p = f"{seq:06d}"
        res_raw, res = self._load(p + ".RESERVED", "RESERVED", seq,
                                  store=self.progression)
        if (res.get("prev_sha256") != prev_sha
                or res.get("prior_dispatch_digest") != prior_digest):
            raise JournalRefused("HISTORY_ROLLBACK_OR_REWRITE", seq)
        entry: Dict[str, Any] = {
            "seq": seq, "run_id": res["run_id"], "reservation": res,
            "reservation_sha256": sha256(res_raw), "records": {}}
        raws: Dict[str, bytes] = {}
        for kind in JOURNAL_KINDS:
            if kind in kinds:
                raws[kind], entry["records"][kind] = self._load(
                    f"{p}.{kind}", kind, seq)
        entry["digest"] = sha256(canonical(sorted(
            [k, sha256(v)] for k, v in raws.items())))
        entry["sha"] = {k: sha256(v) for k, v in raws.items()}
        rec = entry["records"]
        flight, cleanup = rec.get("IN_FLIGHT"), rec.get("CLEANUP")
        final, reconciled = rec.get("FINAL"), rec.get("RECONCILED")
        if res.get("protocol") != DISPATCH_PROTOCOL:
            # Old bytes are preserved and never upgraded: a below-caller
            # ACCEPTED is execution/validation history only.
            raise JournalRefused("LEGACY_PROTOCOL_DISPATCH", {
                "seq": seq, "run_id": res["run_id"],
                "label": LEGACY_LABEL if (final or {}).get("status") == "ACCEPTED"
                else "LEGACY_UNQUALIFIED_DISPATCH"})
        if flight is not None:
            for field in ("run_id", "request_sha256", "raw_path", "output_path",
                          "protocol", "phase_protocol", "effect_protocol"):
                if flight.get(field) != res.get(field):
                    raise JournalRefused("FLIGHT_RESERVATION_MISMATCH",
                                         f"{seq}:{field}")
            if flight.get("reservation_sha256") != entry["reservation_sha256"]:
                raise JournalRefused("FLIGHT_RESERVATION_MISMATCH", f"{seq}:sha")
        elif cleanup is not None or final is not None:
            raise JournalRefused("RECORD_LOST", p + ".IN_FLIGHT")
        entry["phase"], entry["zero_effect"] = self._phase(
            seq, res, entry, flight, rec.get("PHASE"), cleanup, final)
        entry["effect"] = self._effect(seq, res, entry, rec.get("EFFECT"), cleanup)
        for name, value in (("CLEANUP", cleanup), ("FINAL", final)):
            if value is not None and (value.get("run_id") != res["run_id"]
                                      or value.get("flight_sha256")
                                      != entry["sha"].get("IN_FLIGHT")):
                raise JournalRefused(f"{name}_BINDING_MISMATCH", seq)
        if final is not None and final.get("status") not in FINAL_STATUSES:
            raise JournalRefused("UNKNOWN_FINAL_STATUS", seq)
        if (final is not None and res.get("effect_protocol") == EFFECT_PROTOCOL
                and final.get("effect_sha256") != entry["sha"].get("EFFECT")):
            raise JournalRefused("FINAL_BINDING_MISMATCH", f"{seq}:effect")
        if final is not None and "phase_sha256" in final and (
                final["phase_sha256"] != entry["sha"].get("PHASE")):
            raise JournalRefused("FINAL_BINDING_MISMATCH", f"{seq}:phase")
        if cleanup is not None:
            if cleanup.get("status") != "COMPLETION_RESOLVED_VALIDATED":
                raise JournalRefused("CLEANUP_STATUS_UNKNOWN", seq)
            validate_cleanup_predicates(cleanup.get("completion"), res["run_id"])
            _need(cleanup, p + ".CLEANUP", raw_worker_result_sha256="sha",
                  raw_worker_result_bytes=int, executed_request_sha256="sha")
            if (cleanup.get("ticket_sha256") != entry["reservation_sha256"]
                    or cleanup["completion"].get("dispatch_ticket")
                    != entry["reservation_sha256"]):
                raise JournalRefused("CLEANUP_TICKET_MISMATCH", seq)
        if final is not None and final["status"] == "ACCEPTED":
            if cleanup is None:
                raise JournalRefused("RECORD_LOST", p + ".CLEANUP")
            if (res.get("phase_protocol") == PHASE_PROTOCOL
                    and (final.get("phase_sha256") != entry["sha"].get("PHASE")
                         or entry["phase"] != "EFFECT_PERMITTED")):
                raise JournalRefused("FINAL_BINDING_MISMATCH", f"{seq}:phase")
            _need(final, p + ".FINAL", acceptance_sha256="sha")
            if res.get("effect_protocol") == EFFECT_PROTOCOL and (
                    entry["effect"] is None
                    or entry["effect"]["custody"] != "REGISTERED"
                    or final.get("effect_sha256") != entry["sha"].get("EFFECT")):
                raise JournalRefused("FINAL_BINDING_MISMATCH", f"{seq}:effect")
            if (final.get("cleanup_sha256") != entry["sha"]["CLEANUP"]
                    or final.get("raw_worker_result_sha256")
                    != cleanup["raw_worker_result_sha256"]
                    or final.get("commit") != COMMIT_AUTHORITY
                    or final.get("ticket_sha256") != entry["reservation_sha256"]
                    or cleanup["executed_request_sha256"] != res["request_sha256"]):
                raise JournalRefused("FINAL_BINDING_MISMATCH", seq)
        if reconciled is not None:
            if final is not None and final["status"] == "ACCEPTED":
                raise JournalRefused("CONTRADICTORY_ACCEPTED_AND_RECONCILED", seq)
            bound = dict(scope=self.scope, run_id=res["run_id"],
                         reservation_sha256=entry["reservation_sha256"],
                         flight_sha256=entry["sha"].get("IN_FLIGHT"),
                         final_sha256=entry["sha"].get("FINAL"), final=final,
                         disposition=self._disposition(entry))
            try:
                validate_reconciliation(reconciled, zero_effect=entry["zero_effect"],
                                        identity=self._identity_binding(entry),
                                        **bound)
                entry["authority"] = "CURRENT"
            except JournalRefused as refused:
                # FIX005-era v3 only, and only for the missing phase proof:
                # the original declared rule, never current authority.
                if (res.get("phase_protocol") is not None
                        or refused.detail != "NO_ZERO_EFFECT_PHASE_EVIDENCE"):
                    raise
                validate_reconciliation(reconciled, zero_effect=None, **bound)
                entry["authority"] = HISTORICAL_V3_CONTRACT
            entry["status"] = "RECONCILED"
        elif flight is None:
            entry["status"] = "RESERVED_DISPATCH_UNRESOLVED"
        elif final is None:
            entry["status"] = "PRIOR_DISPATCH_IN_FLIGHT"
        elif final["status"] == "STOP":
            entry["status"] = "PRIOR_DISPATCH_STOPPED_UNRECONCILED"
        else:
            entry["status"] = "ACCEPTED"
        return entry

    def _phase(self, seq: int, res: Mapping[str, Any], entry: Dict[str, Any],
               flight: Any, phase: Any, cleanup: Any, final: Any):
        """(slot value, zero-effect evidence) of one dispatch; raises on an
        integrity failure.  The slot counts only when both stores hold the
        identical bytes; a progression-only slot (mirror write lost or not yet
        done) is an effect-possible/unproven state, never zero-effect."""
        name = f"{seq:06d}.PHASE"
        in_progression = seq in self._phased
        if res.get("phase_protocol") != PHASE_PROTOCOL:
            if phase is not None or in_progression:
                raise JournalRefused("PHASE_UNEXPECTED_FOR_PROTOCOL", seq)
            return None, "NOT_ISSUED" if flight is None else "UNPROVEN"
        if flight is None:
            if phase is not None or in_progression:
                raise JournalRefused("RECORD_LOST", f"{seq:06d}.IN_FLIGHT")
            return None, "NOT_ISSUED"
        if phase is None and not in_progression:
            if cleanup is not None:
                raise JournalRefused("RECORD_LOST", name)
            return None, "UNPROVEN"
        if not in_progression:
            raise JournalRefused("PHASE_MIRROR_LOST", seq)
        p_raw, p_value = self._load(name, "PHASE", seq, store=self.progression)
        if phase is None:
            if cleanup is not None:
                raise JournalRefused("RECORD_LOST", name)
            return "UNMIRRORED:" + str(p_value.get("phase")), "UNPROVEN"
        if sha256(p_raw) != entry["sha"]["PHASE"]:
            raise JournalRefused("PHASE_MIRROR_MISMATCH", seq)
        if (phase.get("phase") not in PHASE_VALUES
                or phase.get("run_id") != res["run_id"]
                or phase.get("ticket_sha256") != entry["reservation_sha256"]
                or phase.get("flight_sha256") != entry["sha"]["IN_FLIGHT"]
                or phase.get("phase_protocol") != PHASE_PROTOCOL):
            raise JournalRefused("PHASE_BINDING_MISMATCH", seq)
        if phase["phase"] == "CLOSED_ZERO_EFFECT":
            if phase.get("authority") != "LOWER_CONTROLLER_PRE_EFFECT":
                raise JournalRefused("PHASE_BINDING_MISMATCH", f"{seq}:authority")
            if cleanup is not None:
                raise JournalRefused("CONTRADICTORY_ZERO_EFFECT_AND_CLEANUP", seq)
            if not isinstance(phase.get("cause"), dict):
                raise JournalRefused("PHASE_BINDING_MISMATCH", f"{seq}:cause")
            return "CLOSED_ZERO_EFFECT", "CLOSED_ZERO_EFFECT"
        return "EFFECT_PERMITTED", "UNPROVEN"

    def _effect(self, seq: int, res: Mapping[str, Any], entry: Dict[str, Any],
                effect: Any, cleanup: Any) -> Optional[Dict[str, Any]]:
        """The validated post-spawn identity record of an EFFECT_PROTOCOL
        dispatch, or None (absent).  Present but unbound/malformed/foreign
        is an integrity failure (not reconcilable).  An absent record never
        supports identity-based reconciliation (see validate_reconciliation)."""
        if res.get("effect_protocol") != EFFECT_PROTOCOL:
            if effect is not None:
                raise JournalRefused("EFFECT_UNEXPECTED_FOR_PROTOCOL", seq)
            return None
        if effect is None:
            if cleanup is not None:
                raise JournalRefused("RECORD_LOST", f"{seq:06d}.EFFECT")
            return None
        if (entry["phase"] != "EFFECT_PERMITTED"
                or effect.get("phase_sha256") != entry["sha"].get("PHASE")
                or effect.get("ticket_sha256") != entry["reservation_sha256"]
                or effect.get("flight_sha256") != entry["sha"].get("IN_FLIGHT")
                or effect.get("request_sha256") != res["request_sha256"]
                or effect.get("run_id") != res["run_id"]
                or effect.get("effect_protocol") != EFFECT_PROTOCOL
                or effect.get("evidence_class") != EFFECT_EVIDENCE_CLASS):
            raise JournalRefused("EFFECT_BINDING_MISMATCH", seq)
        try:
            evidence = validate_effect_evidence(effect.get("evidence"))
        except JournalRefused as refused:
            raise JournalRefused("EFFECT_BINDING_MISMATCH", f"{seq}:{refused.detail}")
        return evidence

    def _disposition(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        mirrored = entry["phase"] in PHASE_VALUES
        return disposition_binding(
            self.scope_id, entry["seq"], entry["reservation"],
            entry["sha"].get("CLEANUP"), entry["records"].get("FINAL"),
            entry["records"].get("PHASE") if mirrored else None,
            entry["sha"].get("PHASE") if mirrored else None,
            entry.get("effect"), entry["sha"].get("EFFECT"))

    def _identity_binding(self, entry: Mapping[str, Any],
                          write: bool = False) -> Optional[Dict[str, Any]]:
        """The recorded identity an identity-bearing reconciliation must cite.
        None = pre-identity-protocol history read under its old rule (never
        upgraded); a NEW reconciliation write of such a dispatch gets
        {"token": None} (no recorded identity: identity facts refused)."""
        if entry["reservation"].get("effect_protocol") != EFFECT_PROTOCOL:
            return {"token": None, "source": "PRE_IDENTITY_PROTOCOL"} if write else None
        effect = entry.get("effect")
        if effect is None:
            return {"token": None, "source": "NO_EFFECT_IDENTITY_RECORD"}
        ident = effect["identity"]
        return {"token": None if ident is None else ident["token"],
                "source": "EFFECT_RECORD"}

    def state(self) -> Dict[str, Any]:
        """Permission to start NEW work (never implied by old acceptance)."""
        try:
            built = self._reconstruct()
        except JournalRefused as refused:
            return {"ready": False, "reason": refused.code,
                    "detail": refused.detail}
        return {"ready": True, "next_seq": built["high"] + 1, "history": [
            {"seq": e["seq"], "run_id": e["run_id"], "status": e["status"]}
            for e in built["history"]]}

    # -- writing --------------------------------------------------------
    def _guard_open_write(self, seq: int, kind: str,
                          ticket_sha256: Optional[str] = None,
                          flight_sha256: Optional[str] = None) -> None:
        """Durable write guard of every ticket-side mutation service: re-read
        both stores and refuse (writing nothing) unless seq is the latest
        reservation, holds the ticket's RESERVED/IN_FLIGHT and is still open
        (no FINAL, no RECONCILED, no record of this kind yet; a CLEANUP of a
        phase-protocol dispatch also needs the mirrored EFFECT_PERMITTED).
        Independent of any in-memory ticket flag."""
        p = f"{seq:06d}"
        jnames, pnames = self._names()
        high = max((int(n[:6]) for n in pnames
                    if n.endswith(".RESERVED") and n[:6].isdigit()), default=0)
        failed = [] if high == seq else [f"not_latest:{high}"]
        for terminal in dict.fromkeys(("FINAL", "RECONCILED", kind)):
            if f"{p}.{terminal}" in jnames:
                failed.append(f"{terminal}_present")
        if f"{p}.IN_FLIGHT" not in jnames:
            failed.append("IN_FLIGHT_absent")
        elif flight_sha256 is not None and self._flight_sha(seq) != flight_sha256:
            failed.append("flight")
        res_raw, res = self._load(p + ".RESERVED", "RESERVED", seq,
                                  store=self.progression)
        if ticket_sha256 is not None and sha256(res_raw) != ticket_sha256:
            failed.append("ticket")
        if (kind in ("CLEANUP", "EFFECT")
                and res.get("phase_protocol") == PHASE_PROTOCOL):
            phase = (self._load(p + ".PHASE", "PHASE", seq)[1]
                     if f"{p}.PHASE" in jnames else {})
            if phase.get("phase") != "EFFECT_PERMITTED":
                failed.append("effect_not_permitted")
        if (kind == "CLEANUP" and res.get("effect_protocol") == EFFECT_PROTOCOL
                and f"{p}.EFFECT" not in jnames):
            failed.append("effect_identity_not_recorded")
        if failed:
            raise JournalRefused("DISPATCH_HISTORY_CLOSED",
                                 {"seq": seq, "kind": kind, "failed": failed})

    def _record(self, kind: str, **fields: Any) -> bytes:
        return canonical({"schema": JOURNAL_SCHEMA, "kind": kind,
                          "scope_id": self.scope_id, **fields})

    def reserve(self, run_id: str, request_sha256: str, raw_path: str,
                output_path: str) -> "DispatchTicket":
        """The caller's durable intent, before ANY execution authority
        exists: RESERVED (progression) then IN_FLIGHT (journal) bind the
        caller's request digest, seq, raw/output paths and display run id.
        A failure after RESERVED leaves an interrupted reservation, which
        refuses until explicitly reconciled.  Returns the ticket of exactly
        this dispatch."""
        try:
            built = self._reconstruct()
        except JournalRefused as refused:
            raise JournalRefused(refused.code, refused.detail)
        seq = built["high"] + 1
        last = built["history"][-1] if built["history"] else None
        fields = dict(seq=seq, run_id=run_id, request_sha256=request_sha256,
                      raw_path=raw_path, output_path=output_path,
                      protocol=DISPATCH_PROTOCOL, phase_protocol=PHASE_PROTOCOL,
                      effect_protocol=EFFECT_PROTOCOL)
        reservation = self._record(
            "RESERVED", prev_sha256=(last["reservation_sha256"] if last else
                                     sha256(self._raw(self.progression, "GENESIS"))),
            prior_dispatch_digest=last["digest"] if last else None, **fields)
        flight = self._record("IN_FLIGHT", reservation_sha256=sha256(reservation),
                              **fields)
        for store, name, data, code in (
                (self.progression, f"{seq:06d}.RESERVED", reservation,
                 "RESERVATION_PUBLISH_FAILED"),
                (self.storage, f"{seq:06d}.IN_FLIGHT", flight,
                 "IN_FLIGHT_PUBLISH_FAILED")):
            try:
                store.create_new(name, data)
            except CrashCut:
                raise
            except BaseException as error:
                raise JournalRefused(code, f"{type(error).__name__}:{error}")
        fields.pop("phase_protocol")
        fields.pop("effect_protocol")
        return DispatchTicket(self, dict(
            fields, scope_id=self.scope_id, ticket_sha256=sha256(reservation),
            flight_sha256=sha256(flight)))

    def begin(self, run_id: str, request_sha256: str,
              raw_path: str, output_path: str) -> int:
        """reserve(), returning only the seq (the ticket is discarded)."""
        return self.reserve(run_id, request_sha256, raw_path, output_path).seq

    def open_dispatch(self, seq: int) -> Dict[str, Any]:
        """Dispatch seq while it is still the current one: every earlier
        dispatch resolved and no later reservation (no extra dispatch)."""
        built = self._reconstruct(upto=seq, open_last=True)
        if built["high"] != seq:
            raise JournalRefused("EXTRA_DISPATCH_RESERVED",
                                 {"seq": seq, "high": built["high"]})
        return built["history"][-1]

    def load_ticket(self, seq: int) -> "DispatchTicket":
        """Read-only ticket view rebuilt from the durable RESERVED/IN_FLIGHT
        (recovery by the same ticket); it carries no execution authority."""
        entry = self._reconstruct(upto=seq, open_last=True,
                                  historical=True)["history"][-1]
        flight = entry["records"].get("IN_FLIGHT")
        if flight is None:
            raise JournalRefused("RECORD_LOST", f"{seq:06d}.IN_FLIGHT")
        ticket = DispatchTicket(self, dict(
            {k: flight[k] for k in ("seq", "run_id", "request_sha256", "raw_path",
                                    "output_path", "protocol")},
            scope_id=self.scope_id, ticket_sha256=entry["reservation_sha256"],
            flight_sha256=entry["sha"]["IN_FLIGHT"]))
        ticket.claimed = ticket.read_only = True
        return ticket

    def _flight_sha(self, seq: int) -> str:
        return sha256(self._raw(self.storage, f"{seq:06d}.IN_FLIGHT"))

    def _record_prepared(self, ticket: "DispatchTicket",
                         completion: Mapping[str, Any], raw_path: Path,
                         raw_bytes: bytes, validated_result: Mapping[str, Any],
                         executed_request_sha256: str) -> str:
        """Prepared evidence (CLEANUP): the persisted successful
        completion-cleanup record bound to the ticket, the raw bytes, the
        digest of the request actually executed and the validated result.
        NOT an acceptance; returns its sha256."""
        validate_cleanup_predicates(dict(completion), ticket.run_id)
        if completion.get("dispatch_ticket") != ticket.ticket_sha256:
            raise JournalRefused("CLEANUP_TICKET_MISMATCH", ticket.seq)
        self._guard_open_write(ticket.seq, "CLEANUP", ticket.ticket_sha256,
                               ticket.flight_sha256)
        data = self._record(
            "CLEANUP", seq=ticket.seq, run_id=ticket.run_id,
            flight_sha256=ticket.flight_sha256,
            ticket_sha256=ticket.ticket_sha256,
            status="COMPLETION_RESOLVED_VALIDATED",
            completion=json.loads(canonical(dict(completion))),
            raw_worker_result_path=str(raw_path),
            raw_worker_result_bytes=len(raw_bytes),
            raw_worker_result_sha256=sha256(raw_bytes),
            executed_request_sha256=executed_request_sha256,
            validated_result_sha256=sha256(canonical(dict(validated_result))))
        self.storage.create_new(f"{ticket.seq:06d}.CLEANUP", data)
        return sha256(data)

    def finish(self, seq: int, run_id: str, status: str,
               **fields: Any) -> None:
        """FINAL STOP only.  FINAL ACCEPTED is written solely by the
        coordinator's commit_current_dispatch() (via _commit_accepted)."""
        if status != "STOP":
            raise ValueError(status)
        self._guard_open_write(seq, "FINAL", fields.get("ticket_sha256"))
        res = self._load(f"{seq:06d}.RESERVED", "RESERVED", seq,
                         store=self.progression)[1]
        if res.get("effect_protocol") == EFFECT_PROTOCOL:
            # the STOP binds the identity record as it exists (or its absence)
            effect_raw = self.storage.read(f"{seq:06d}.EFFECT")
            fields["effect_sha256"] = (None if effect_raw is None
                                       else sha256(effect_raw))
        self.storage.create_new(f"{seq:06d}.FINAL", self._record(
            "FINAL", seq=seq, run_id=run_id, status=status,
            flight_sha256=self._flight_sha(seq), **fields))

    def _commit_accepted(self, ticket: "DispatchTicket", **fields: Any) -> None:
        self._guard_open_write(ticket.seq, "FINAL", ticket.ticket_sha256,
                               ticket.flight_sha256)
        entry = self._reconstruct(upto=ticket.seq, open_last=True)["history"][-1]
        verified_effect = fields.pop("effect_sha256", None)
        if entry["reservation"].get("effect_protocol") == EFFECT_PROTOCOL:
            # defense: verify_prepared_dispatch refused these before the
            # envelope; here they re-check the durable record at the write
            if (entry["effect"] is None
                    or entry["effect"]["custody"] != "REGISTERED"
                    or entry["sha"].get("EFFECT") != verified_effect):
                raise JournalRefused("DISPATCH_HISTORY_CLOSED", {
                    "seq": ticket.seq, "kind": "FINAL",
                    "failed": ["effect_identity_custody_not_registered"]})
            fields["effect_sha256"] = entry["sha"]["EFFECT"]
        self.storage.create_new(f"{ticket.seq:06d}.FINAL", self._record(
            "FINAL", seq=ticket.seq, run_id=ticket.run_id, status="ACCEPTED",
            flight_sha256=ticket.flight_sha256, ticket_sha256=ticket.ticket_sha256,
            commit=COMMIT_AUTHORITY, **fields))

    def required_disposition(self, seq: int) -> Dict[str, Any]:
        """Read-only: the bindings a reconciliation of seq must cite."""
        return self._disposition(
            self._reconstruct(upto=seq, open_last=True)["history"][-1])

    def reconcile(self, seq: int, original_run_id: str,
                  resolution_evidence: Mapping[str, Any]) -> None:
        """Explicit operator reconciliation of the FIRST unresolved dispatch
        (interrupted reservation, IN_FLIGHT without FINAL, or STOP).
        Integrity failures (lost anchor, rollback, corruption) and legacy
        protocol records are not reconcilable."""
        try:
            self._reconstruct()
        except JournalRefused as refused:
            if refused.code not in RECONCILABLE or not isinstance(
                    refused.detail, dict) or refused.detail.get("seq") != seq:
                raise JournalRefused("NOT_RECONCILABLE", refused.code)
        else:
            raise JournalRefused("NOT_RECONCILABLE", "NOTHING_UNRESOLVED")
        # the facts of seq exactly as the reader validates them
        entry = self._reconstruct(upto=seq, open_last=True)["history"][-1]
        res = entry["reservation"]
        shas, final = entry["sha"], entry["records"].get("FINAL")
        evidence = dict(resolution_evidence)
        record = {"seq": seq, "original_run_id": original_run_id,
                  "cited_run_id": evidence.get("cited_run_id"),
                  "run_generation": evidence.get("run_generation"),
                  "dispatcher_owner": evidence.get("dispatcher_owner"),
                  "operator": evidence.get("operator"),
                  "trust": evidence.get("trust"),
                  "obligations": evidence.get("obligations"),
                  "disposition": evidence.get("disposition"),
                  "reservation_sha256": entry["reservation_sha256"],
                  "flight_sha256": shas.get("IN_FLIGHT"),
                  "final_sha256": shas.get("FINAL")}
        if res["run_id"] != original_run_id:
            raise JournalRefused("RECONCILIATION_INVALID", "RUN_MISMATCH")
        validate_reconciliation(record, scope=self.scope, run_id=res["run_id"],
                                reservation_sha256=entry["reservation_sha256"],
                                flight_sha256=shas.get("IN_FLIGHT"),
                                final_sha256=shas.get("FINAL"), final=final,
                                disposition=self._disposition(entry),
                                zero_effect=entry["zero_effect"],
                                identity=self._identity_binding(entry, write=True))
        self.storage.create_new(f"{seq:06d}.RECONCILED",
                                self._record("RECONCILED", **record))

    def accepted_dispatch(self, seq: int) -> Dict[str, Any]:
        """Historical-acceptance view of dispatch seq: validates the anchor,
        genesis, reservation chain and every record of 1..seq, each under the
        protocol it declares; ignores later dispatches.  Raises unless seq
        itself is ACCEPTED.  Read-only; confers no current authority."""
        built = self._reconstruct(upto=seq, historical=True)
        entry = built["history"][-1]
        if entry["status"] != "ACCEPTED":
            raise JournalRefused("DISPATCH_NOT_ACCEPTED", entry["status"])
        return entry


# -- execution ticket (DEV007_FIX005) -----------------------------------
TICKET_FIELDS = ("scope_id", "seq", "run_id", "request_sha256", "raw_path",
                 "output_path", "protocol", "ticket_sha256", "flight_sha256")


class DispatchTicket:
    """Execution authority for ONE reserved dispatch: execute it once after
    check_execution(), publish its prepared evidence, or record STOP.  It
    cannot reserve another seq, execute another request or write FINAL
    ACCEPTED.  An internal interface contract, not a sandbox against
    arbitrary Python holding the journal object."""

    def __init__(self, journal: DispatchJournal, binding: Mapping[str, Any]) -> None:
        self._journal = journal
        self.binding = {field: binding[field] for field in TICKET_FIELDS}
        for field in TICKET_FIELDS:
            setattr(self, field, self.binding[field])
        self.claimed = False
        self.read_only = False
        self.effect_permitted = False     # this object passed the handoff

    def _claim_slot(self, phase: str, **fields: Any) -> str:
        """Create the dispatch's single effect-handoff slot: progression
        first (decisive, no-clobber), then the identical journal mirror.
        Raises on any failure; returns the slot sha256."""
        data = self._journal._record(
            "PHASE", seq=self.seq, run_id=self.run_id, phase=phase,
            ticket_sha256=self.ticket_sha256, flight_sha256=self.flight_sha256,
            phase_protocol=PHASE_PROTOCOL, **fields)
        name = f"{self.seq:06d}.PHASE"
        self._journal._guard_open_write(self.seq, "PHASE", self.ticket_sha256,
                                        self.flight_sha256)
        self._journal.progression.create_new(name, data)
        self._journal.storage.create_new(name, data)
        return sha256(data)

    def check_execution(self, *, run_id: str, request_sha256: str,
                        raw_path: Path, output_path: Path) -> None:
        """Before spawn: the actual request, paths and run label must be the
        ticket's, the ticket unused, and the durable dispatch still open and
        the latest (a stale seq ticket cannot authorize anything)."""
        observed = {"run_id": str(run_id), "request_sha256": request_sha256,
                    "raw_path": str(raw_path), "output_path": str(output_path)}
        failed = [k for k, v in observed.items() if v != self.binding[k]]
        if self.claimed:
            failed.append("ticket_already_executed")
        try:
            entry = self._journal.open_dispatch(self.seq)
        except JournalRefused as refused:
            failed.append(f"durable:{refused.code}")
        else:
            if (entry["reservation_sha256"] != self.ticket_sha256
                    or entry["sha"].get("IN_FLIGHT") != self.flight_sha256):
                failed.append("durable_ticket")
            if set(entry["records"]) != {"IN_FLIGHT"}:
                failed.append("dispatch_not_open")
            if entry.get("phase") is not None:
                failed.append("effect_slot_occupied")
            if entry["reservation"].get("phase_protocol") != PHASE_PROTOCOL:
                failed.append("phase_protocol")   # pre-phase dispatch: no handoff
        was_claimed, self.claimed = self.claimed, True
        if not failed and not was_claimed:
            # effect handoff: durable EFFECT_PERMITTED in both stores, or no
            # spawn (a lost race / write failure refuses here)
            try:
                self.phase_sha256 = self._claim_slot(
                    "EFFECT_PERMITTED", authority="TICKET_CHECK_EXECUTION")
                self.effect_permitted = True
            except CrashCut:
                raise
            except BaseException as error:
                failed.append(f"effect_handoff:{type(error).__name__}:{error}")
        if failed:
            raise JournalRefused("TICKET_BINDING_REFUSED",
                                 {"failed": failed, "observed": observed})

    def close_zero_effect(self, cause: Mapping[str, Any]) -> str:
        """The lower controller's pre-effect refusal: occupy the slot with
        CLOSED_ZERO_EFFECT (cause = the controller phase and failure), which
        durably extinguishes this dispatch's execution authority for every
        holder.  Refused, writing nothing, for a read-only/recovered ticket,
        a ticket object that already handed off an effect, or a dispatch that
        is not the open latest one with an empty slot.  Raises unless both
        slot writes succeed; returns the slot sha256."""
        if self.read_only or self.effect_permitted:
            raise JournalRefused("ZERO_EFFECT_CLOSURE_REFUSED",
                                 "read_only" if self.read_only else "effect_permitted")
        self.claimed = True                 # this object can never hand off now
        entry = self._journal.open_dispatch(self.seq)
        if (entry["reservation_sha256"] != self.ticket_sha256
                or entry["sha"].get("IN_FLIGHT") != self.flight_sha256
                or set(entry["records"]) != {"IN_FLIGHT"}
                or entry.get("phase") is not None
                or entry["reservation"].get("phase_protocol") != PHASE_PROTOCOL):
            raise JournalRefused("ZERO_EFFECT_CLOSURE_REFUSED", "dispatch_not_open")
        return self._claim_slot("CLOSED_ZERO_EFFECT", cause=json.loads(
            canonical(dict(cause))), authority="LOWER_CONTROLLER_PRE_EFFECT")

    def record_effect_identity(self, evidence: Mapping[str, Any]) -> str:
        """NRP-2: the lower controller's post-spawn identity handoff, after
        RunContext.attach_root and before any sampler.  Only the ticket
        object that passed the effect handoff may write it, once, while the
        dispatch is open (durable guard).  Returns the EFFECT sha256."""
        self._writable()
        if not self.effect_permitted:
            raise JournalRefused("DISPATCH_HISTORY_CLOSED", "no_effect_handoff")
        checked = validate_effect_evidence(json.loads(canonical(dict(evidence))))
        self._journal._guard_open_write(self.seq, "EFFECT", self.ticket_sha256,
                                        self.flight_sha256)
        data = self._journal._record(
            "EFFECT", seq=self.seq, run_id=self.run_id,
            ticket_sha256=self.ticket_sha256, flight_sha256=self.flight_sha256,
            phase_sha256=sha256(self._journal._raw(
                self._journal.storage, f"{self.seq:06d}.PHASE")),
            request_sha256=self.request_sha256, effect_protocol=EFFECT_PROTOCOL,
            evidence_class=EFFECT_EVIDENCE_CLASS, evidence=checked)
        self._journal.storage.create_new(f"{self.seq:06d}.EFFECT", data)
        return sha256(data)

    def _writable(self) -> None:
        if self.read_only:      # recovered view: never a mutation authority
            raise JournalRefused("DISPATCH_HISTORY_CLOSED", "read_only_ticket")

    def record_prepared(self, completion: Mapping[str, Any], raw_path: Path,
                        raw_bytes: bytes, validated_result: Mapping[str, Any],
                        executed_request_sha256: str) -> str:
        self._writable()
        return self._journal._record_prepared(
            self, completion, raw_path, raw_bytes, validated_result,
            executed_request_sha256)

    def stop(self, reason: str, **fields: Any) -> None:
        self._writable()
        self._journal.finish(self.seq, self.run_id, "STOP", reason=str(reason),
                             ticket_sha256=self.ticket_sha256, **fields)


# -- acceptance envelope ------------------------------------------------
def acceptance_envelope(*, journal: DispatchJournal, ticket: DispatchTicket,
                        raw_bytes: bytes, cleanup: Mapping[str, Any],
                        cleanup_sha256: str,
                        accepted_result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema": ACCEPTANCE_SCHEMA, "status": "CONTROLLER_ACCEPTED",
        "acceptance_protocol": DISPATCH_PROTOCOL,
        "scope_id": journal.scope_id, "seq": ticket.seq, "run_id": ticket.run_id,
        "flight_sha256": ticket.flight_sha256,
        "reservation_sha256": ticket.ticket_sha256,
        "request_sha256": ticket.request_sha256,
        "output_path": ticket.output_path,
        "raw_worker_result_path": ticket.raw_path,
        "raw_worker_result_bytes": len(raw_bytes),
        "raw_worker_result_sha256": sha256(raw_bytes),
        "completion_cleanup_sha256": cleanup_sha256,
        "completion_resolved":
            cleanup["completion"].get("completion_resolved") is True,
        "accepted_result": dict(accepted_result),
    }


def verify_controller_acceptance(output_path: Path,
                                 journal: DispatchJournal) -> Dict[str, Any]:
    """The one consumer check (historical acceptance; see module docstring).
    A raw worker PASS alone, or a digest of unavailable evidence, never
    passes it."""
    try:
        data = Path(output_path).read_bytes()
        envelope = json.loads(data.decode("ascii"))
    except Exception as error:
        raise JournalRefused("ACCEPTANCE_UNREADABLE", type(error).__name__)
    if (not isinstance(envelope, dict) or envelope.get("schema") != ACCEPTANCE_SCHEMA
            or envelope.get("status") != "CONTROLLER_ACCEPTED"
            or envelope.get("completion_resolved") is not True
            or not isinstance(envelope.get("accepted_result"), dict)):
        raise JournalRefused("NOT_A_CONTROLLER_ACCEPTANCE")
    if envelope.get("scope_id") != journal.scope_id:
        raise JournalRefused("ACCEPTANCE_SCOPE_MISMATCH")
    seq = envelope.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise JournalRefused("NOT_A_CONTROLLER_ACCEPTANCE", "seq")
    try:
        entry = journal.accepted_dispatch(seq)
    except JournalRefused as refused:
        raise JournalRefused("ACCEPTANCE_NOT_JOURNALED", refused.code)
    rec, shas = entry["records"], entry["sha"]
    flight, cleanup, final = rec["IN_FLIGHT"], rec["CLEANUP"], rec["FINAL"]
    checks = {
        "run_id": envelope.get("run_id") == entry["run_id"],
        "flight": envelope.get("flight_sha256") == shas["IN_FLIGHT"],
        "reservation": envelope.get("reservation_sha256") == entry["reservation_sha256"],
        "request": envelope.get("request_sha256") == flight["request_sha256"],
        "output_path": envelope.get("output_path") == flight["output_path"]
        == str(output_path),
        "raw_path": envelope.get("raw_worker_result_path") == flight["raw_path"]
        == cleanup.get("raw_worker_result_path"),
        "cleanup": envelope.get("completion_cleanup_sha256") == shas["CLEANUP"],
        "final": final.get("acceptance_sha256") == sha256(data),
        "raw_sha": envelope.get("raw_worker_result_sha256")
        == cleanup["raw_worker_result_sha256"],
        "raw_bytes": envelope.get("raw_worker_result_bytes")
        == cleanup["raw_worker_result_bytes"],
        "protocol": envelope.get("acceptance_protocol") == DISPATCH_PROTOCOL,
        "validated": cleanup.get("validated_result_sha256")
        == sha256(canonical(envelope["accepted_result"])),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise JournalRefused("ACCEPTANCE_JOURNAL_MISMATCH", ",".join(failed))
    try:
        raw = Path(envelope["raw_worker_result_path"]).read_bytes()
    except Exception as error:
        raise JournalRefused("RAW_WORKER_BYTES_UNREADABLE", type(error).__name__)
    if len(raw) != envelope["raw_worker_result_bytes"] or sha256(raw) != (
            envelope["raw_worker_result_sha256"]):
        raise JournalRefused("RAW_WORKER_BYTES_MISMATCH")
    return envelope


# -- caller-bound transaction (DEV007_FIX005) ------------------------------
def reserve_current_dispatch(journal: DispatchJournal, *, run_id: str,
                             request_sha256: str, raw_path: Path,
                             output_path: Path) -> DispatchTicket:
    """Coordinator step 1.  Pure admission first (digest, permission now,
    fresh raw/output paths): a refusal here writes nothing and no launcher
    is called.  Then the durable caller-bound reservation -> ticket."""
    if not (isinstance(request_sha256, str) and len(request_sha256) == 64):
        raise JournalRefused("CURRENT_REQUEST_DIGEST_INVALID")
    state = journal.state()
    if state.get("ready") is not True:
        raise JournalRefused("CURRENT_DISPATCH_NOT_PERMITTED", state.get("reason"))
    for path in (Path(raw_path), Path(output_path)):
        if path.exists() or path.is_symlink():
            raise JournalRefused("CURRENT_OUTPUT_NOT_FRESH", str(path))
    return journal.reserve(str(run_id), request_sha256, str(raw_path),
                           str(output_path))


def verify_prepared_dispatch(journal: DispatchJournal, ticket: DispatchTicket,
                             returned: Any, result_check: Any = None) -> Dict[str, Any]:
    """Coordinator step 2 (never depends on an existing FINAL): the returned
    prepared evidence is exactly this ticket's, the durable dispatch is still
    open and the latest (no extra dispatch), the persisted CLEANUP binds the
    ticket, the caller's request digest and the raw bytes, the validated
    result is the persisted one and passes the caller's identity rule."""
    ret = dict(returned) if isinstance(returned, Mapping) else {}
    receipt = ret.get("receipt") if isinstance(ret.get("receipt"), Mapping) else {}
    failed: list = []

    def need(name: str, ok: bool) -> None:
        if not ok:
            failed.append(name)
    need("scope", journal.scope_id == ticket.scope_id)
    need("prepared_schema", ret.get("schema") == PREPARED_SCHEMA
         and ret.get("status") == "PREPARED_NOT_ACCEPTED")
    need("returned_ticket", ret.get("ticket") == ticket.binding)
    need("returned_receipt", receipt.get("seq") == ticket.seq
         and receipt.get("ticket_sha256") == ticket.ticket_sha256
         and receipt.get("failures") == [] and receipt.get("final") is None
         and (receipt.get("completed_in_order") or [None])[-1]
         == "JOURNAL_CLEANUP_RECORD_PUBLISHED")
    entry, cleanup, raw, result = None, None, None, ret.get("validated_result")
    try:
        entry = journal.open_dispatch(ticket.seq)
    except JournalRefused as refused:
        failed.append(f"durable_dispatch:{refused.code}")
    if entry is not None:
        rec = entry["records"]
        flight, cleanup = rec.get("IN_FLIGHT") or {}, rec.get("CLEANUP")
        need("durable_ticket", entry["reservation_sha256"] == ticket.ticket_sha256
             and entry["sha"].get("IN_FLIGHT") == ticket.flight_sha256)
        need("prepared_open", cleanup is not None and "FINAL" not in rec
             and "RECONCILED" not in rec)
        need("request", flight.get("request_sha256") == ticket.request_sha256
             and (cleanup or {}).get("executed_request_sha256")
             == ticket.request_sha256)
        need("paths", flight.get("raw_path") == ticket.raw_path
             and flight.get("output_path") == ticket.output_path
             and (cleanup or {}).get("raw_worker_result_path") == ticket.raw_path)
        need("returned_cleanup", ret.get("cleanup_sha256") == entry["sha"].get("CLEANUP"))
        need("effect_handoff", entry.get("phase") == "EFFECT_PERMITTED")
        if entry["reservation"].get("effect_protocol") == EFFECT_PROTOCOL:
            # NRP-2 FIX001: knowable before any envelope is published; the
            # EFFECT's ticket/flight/PHASE/request/run binding was already
            # validated by open_dispatch (_effect).  _commit_accepted and the
            # reader keep the same checks as defense.
            need("effect_identity_record", entry.get("effect") is not None)
            need("effect_custody_registered",
                 (entry.get("effect") or {}).get("custody") == "REGISTERED")
    if cleanup is not None:
        try:
            raw = Path(ticket.raw_path).read_bytes()
        except Exception:
            raw = None
        need("raw_bytes", raw is not None
             and len(raw) == cleanup["raw_worker_result_bytes"]
             and sha256(raw) == cleanup["raw_worker_result_sha256"])
        need("validated_result", isinstance(result, Mapping)
             and sha256(canonical(dict(result))) == cleanup["validated_result_sha256"])
        if result_check is not None and isinstance(result, Mapping):
            try:
                result_check(dict(result))
            except Exception as error:
                failed.append(f"result_identity:{type(error).__name__}:{error}")
    output = Path(ticket.output_path)
    need("output_fresh", not (output.exists() or output.is_symlink()))
    if failed:
        raise JournalRefused("CURRENT_DISPATCH_MISMATCH", ",".join(failed))
    return {"cleanup": cleanup, "cleanup_sha256": entry["sha"]["CLEANUP"],
            "phase_sha256": entry["sha"]["PHASE"],
            "effect_sha256": entry["sha"].get("EFFECT"),
            "raw": raw, "result": dict(result),
            "steps": list(receipt["completed_in_order"])}


def refuse_current_dispatch(journal: DispatchJournal, ticket: DispatchTicket,
                            reason: str, failed: Any, returned: Any = None,
                            outcome: Optional[Dict[str, Any]] = None) -> list:
    """Durable refusal after execution authority was handed out: FINAL STOP
    carrying the binding violation (expected ticket binding, observed
    returned evidence, failed checks).  If the write fails the non-terminal
    IN_FLIGHT stays and refuses as well.  Never overwrites an existing FINAL
    (no clobber); returns the secondary write failures.

    NRP-2 FIX001: if the write guard refuses ONLY because a FINAL exists and
    that FINAL is a valid STOP of exactly this ticket's open latest dispatch
    (typically the lower controller's own STOP), the refusal is already
    durable: nothing is written and no secondary failure is manufactured.
    Any other refusal, or a FINAL that does not validate, stays a failure.
    outcome (optional dict) receives "stop": PUBLISHED | ALREADY_DURABLE |
    FAILED."""
    outcome = {} if outcome is None else outcome
    try:
        observed = sha256(canonical(returned))
    except Exception:
        observed = "UNSERIALIZABLE:" + type(returned).__name__
    violation = {"expected": dict(ticket.binding), "failed": str(failed),
                 "observed_returned_sha256": observed}
    try:
        ticket.stop(reason, binding_violation=violation, stopped_by="COORDINATOR")
    except CrashCut:
        raise
    except BaseException as error:
        if _ticket_stop_already_durable(journal, ticket, error):
            outcome["stop"] = "ALREADY_DURABLE"
            return []
        outcome["stop"] = "FAILED"
        return [f"JOURNAL_FINAL_STOP:{type(error).__name__}:{error}"]
    outcome["stop"] = "PUBLISHED"
    return []


def _ticket_stop_already_durable(journal: DispatchJournal, ticket: DispatchTicket,
                                 error: BaseException) -> bool:
    """True only for a guard refusal whose sole cause is FINAL_present, where
    the durable dispatch is this ticket's open latest one (every record
    validated by the reader) and its FINAL is a STOP bound to this ticket."""
    if not (isinstance(error, JournalRefused) and error.code == "DISPATCH_HISTORY_CLOSED"
            and isinstance(error.detail, dict)
            and error.detail.get("failed") == ["FINAL_present"]):
        return False
    try:
        entry = journal.open_dispatch(ticket.seq)
    except JournalRefused:
        return False
    final = entry["records"].get("FINAL") or {}
    return (entry["reservation_sha256"] == ticket.ticket_sha256
            and entry["sha"].get("IN_FLIGHT") == ticket.flight_sha256
            and "RECONCILED" not in entry["records"]
            and final.get("status") == "STOP"
            and final.get("ticket_sha256") == ticket.ticket_sha256)


def commit_current_dispatch(journal: DispatchJournal, ticket: DispatchTicket,
                            returned: Any, result_check: Any = None) -> Dict[str, Any]:
    """Coordinator step 3, the unique final-commit service: verify the
    prepared evidence against the caller's ticket, then publish the
    acceptance envelope and FINAL ACCEPTED, then verify the committed
    result.  Only the returned envelope may reach consumers/ledgers."""
    def refuse(refused: JournalRefused, reason: str, steps: list) -> JournalRefused:
        outcome: Dict[str, Any] = {}
        refused.stop_failures = refuse_current_dispatch(
            journal, ticket, reason, refused.detail, returned, outcome)
        refused.completed_in_order = steps + (
            ["JOURNAL_FINAL_STOP_PUBLISHED"] if outcome.get("stop") == "PUBLISHED"
            else [])
        return refused
    try:
        facts = verify_prepared_dispatch(journal, ticket, returned, result_check)
    except JournalRefused as refused:
        receipt = (returned.get("receipt") if isinstance(returned, Mapping)
                   else None)
        raise refuse(refused, "CURRENT_BINDING_REFUSED", list(
            (receipt or {}).get("completed_in_order") or []
            if isinstance(receipt, Mapping) else []))
    steps = facts["steps"] + ["COORDINATOR_CURRENT_BINDING_VERIFIED"]
    envelope = acceptance_envelope(
        journal=journal, ticket=ticket, raw_bytes=facts["raw"],
        cleanup=facts["cleanup"], cleanup_sha256=facts["cleanup_sha256"],
        accepted_result=facts["result"])
    data = canonical(envelope)
    try:
        publish_no_clobber(Path(ticket.output_path), data)
        steps.append("ACCEPTANCE_ENVELOPE_PUBLISHED")
        journal._commit_accepted(
            ticket, acceptance_sha256=sha256(data),
            cleanup_sha256=facts["cleanup_sha256"],
            phase_sha256=facts["phase_sha256"],
            effect_sha256=facts["effect_sha256"],
            raw_worker_result_sha256=envelope["raw_worker_result_sha256"],
            completed_steps=list(steps))
    except CrashCut:
        raise
    except Exception as error:
        # Nothing committed (an unjournaled envelope is refused by every
        # consumer check): STOP, or the non-terminal IN_FLIGHT, refuses.
        raise refuse(JournalRefused(
            "COMMIT_PUBLISH_FAILED", f"after:{steps[-1]}:{type(error).__name__}:"
            f"{error}"), "COMMIT_PUBLISH_FAILED", steps) from error
    steps.append("JOURNAL_FINAL_ACCEPTED_PUBLISHED")
    committed = verify_committed_dispatch(journal, ticket)
    return dict(committed, receipt={
        "seq": ticket.seq, "ticket_sha256": ticket.ticket_sha256,
        "completed_in_order": steps, "failures": [], "final": "ACCEPTED",
        "receipt_phase": "FINAL_AS_OF_RETURN"})


def verify_committed_dispatch(journal: DispatchJournal,
                              ticket: DispatchTicket) -> Dict[str, Any]:
    """Already-committed historical acceptance of THIS ticket (also the
    read-only recovery after a lost return notification: no rerun, no
    recleanup, no relabel)."""
    envelope = verify_controller_acceptance(Path(ticket.output_path), journal)
    checks = {
        "scope": envelope["scope_id"] == ticket.scope_id,
        "seq": envelope["seq"] == ticket.seq,
        "ticket": envelope["reservation_sha256"] == ticket.ticket_sha256,
        "flight": envelope["flight_sha256"] == ticket.flight_sha256,
        "request": envelope["request_sha256"] == ticket.request_sha256,
        "paths": envelope["output_path"] == ticket.output_path
        and envelope["raw_worker_result_path"] == ticket.raw_path,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise JournalRefused("COMMITTED_DISPATCH_MISMATCH", ",".join(failed))
    return envelope


def recover_committed_dispatch(journal: DispatchJournal, seq: int, *,
                               request_sha256: str, output_path: Path) -> Dict[str, Any]:
    """Read-only recovery by the caller's own (seq, request, output)."""
    ticket = journal.load_ticket(seq)
    if (ticket.request_sha256 != request_sha256
            or ticket.output_path != str(output_path)):
        raise JournalRefused("COMMITTED_DISPATCH_MISMATCH", "caller_binding")
    return verify_committed_dispatch(journal, ticket)
