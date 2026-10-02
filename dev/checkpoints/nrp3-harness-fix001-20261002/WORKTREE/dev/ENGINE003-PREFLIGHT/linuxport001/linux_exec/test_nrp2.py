"""NRP-2 pure-model matrix (no native effects).

Explicit opt-in Linux entry seam (linux_entry) + post-spawn identity
handoff (journal EFFECT record, EFFECT_PROTOCOL) + finite pre-effect close
lock wait.  Every case runs the exact stage_b_controller.launch_request /
stage_b_dispatch_journal (and, for next_dispatch, stage_b_orchestrator) over
FakeKernel, FakePopen, SimulatedObjectSignalPort and MemoryStorage.  No fork,
pidfd, signal, /proc or FileStorage.  Fake spawn counts are the test's
observation, never evidence used by the code under test.

    cd linux_exec && python3 -B -m unittest -v test_nrp2
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import linux_entry  # noqa: E402
import test_dev006 as T  # noqa: E402
import test_dev007_fix001 as V  # noqa: E402
import test_dev007_fix002 as F2  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix005 as X  # noqa: E402
import test_dev_phase_evidence001 as P  # noqa: E402
from synthetic import advance  # noqa: E402

C, J = T.C, T.J
records, record, next_dispatch = X.records, X.record, X.next_dispatch
IDENT = "modeled-root-7"


class FakeLock:
    """Injected table lock: acquire(timeout) never succeeds; records timeouts."""

    def __init__(self):
        self.timeouts = []

    def acquire(self, blocking=True, timeout=-1):
        self.timeouts.append(timeout)
        return False

    def release(self):
        raise AssertionError("never acquired")


class EntryLaunch(T.Launch):
    """T.Launch, but the ports come from linux_entry.LinuxControllerEntry."""

    def __init__(self, *a, opt_in=linux_entry.OPT_IN, identity=True,
                 entry_override=None, **kw):
        super().__init__(*a, **kw)
        k = self.k
        entry_kw = dict(opt_in=opt_in, capability_backend=self.backend,
                        termination_factory=lambda: self.route,
                        clock=lambda: k.clock, sleep=lambda s: advance(k, s),
                        run_id=self.run_id, dispatch_latch=self.latch,
                        modeled_identity=(lambda proc: IDENT) if identity else None)
        entry_kw.update(entry_override or {})
        self.entry = linux_entry.LinuxControllerEntry(C, **entry_kw)

    def run(self):
        t = self.tmp
        request = {"schema": C.LIVE_SCHEMA, "execution_mode": C.BOUNDED_MODE,
                   "timeout_seconds": 5, "runtime_target": str(t / "runtime" / "target"),
                   "evidence_root": str(t / "evidence"), "workload_id": "W",
                   "candidate_id": "CAND", "schedule_row_sha256": "0" * 64,
                   "source_commit": "c", "source_tree": "t"}
        (t / "runtime").mkdir()
        self.start_clock = self.k.clock
        stubs = dict(
            load_exact_runtime_resource_capture=lambda path, digest: ({}, b"{}"),
            strict_json_load=lambda path: {}, ExecutionAuthority=lambda *a: None,
            FrozenAssets=lambda a: None,
            prelaunch_guard=lambda *a: {"worker_launch_authorized": True, "status": "PASS"})
        self.output_path, self.log_path = t / "out" / "result.json", t / "out" / "log.txt"
        self.output_path.parent.mkdir()
        with mock.patch.multiple(C, **stubs), mock.patch.object(C, "sys", T.SysAs("linux")):
            try:
                self.result = C.launch_request(
                    t, t / "runtime", t / "res.json", t / "dur.json", request,
                    t / "request.json", self.output_path, self.log_path,
                    worker_command=["synthetic"], watchdog_timeout_seconds=5.0,
                    popen_factory=self.popen_factory,
                    sampler_factory=T.manual_sampler_factory(self.k, made=self.samplers),
                    dispatch_journal=self.journal, **self.entry.launch_kwargs())
                return None
            except C.StopSignal as stop:
                return stop
            finally:
                if self.entry.contexts:
                    self.context = self.entry.contexts[-1]


def zero_effect_refusal(run):
    """Real controller path: the EFFECT_PERMITTED handoff write fails once, so
    TICKET_CHECK refuses before spawn and _pre_effect_refusal closes the slot."""
    P.fail_once(run.journal.progression, f"{run.journal.state()['next_seq']:06d}.PHASE",
                OSError(28, "EFFECT_PERMITTED_ENOSPC"))
    return run.run()


def launch(j=None, run_id="RUN-A", accept=True, **kw):
    run = EntryLaunch(*T.world(descendant=False)[:2], journal=j, run_id=run_id, **kw)
    if accept:
        V.finish(run)
    return run


def run_accepted(j=None, run_id="RUN-A", **kw):
    run = launch(j, run_id, **kw)
    with V.valid_worker([]):
        stop = run.run()
    assert stop is None, stop and (stop.stop_id, stop.detail)
    return run


def effect(j, seq=1):
    return record(j, f"{seq:06d}.EFFECT")


def identity_evidence(j, run_id, token=IDENT, **override):
    ev = F2.reconciliation(j, run_id, **override)
    for kind in ("ROOT_PROCESS", "KNOWN_DESCENDANTS", "CAPABILITY_CUSTODY"):
        ev["obligations"][kind]["identity"] = token
    return ev


def never_evidence(j, run_id):
    return P.never_evidence(j, run_id)


class Base(unittest.TestCase):
    def assert_refused_unchanged(self, j, seq, run_id, evidence, code):
        before = records(j)
        with self.assertRaises(J.JournalRefused) as caught:
            W.rebuilt(j).reconcile(seq, run_id, evidence)
        self.assertIn(code, str(caught.exception))
        self.assertEqual(records(j), before)

    def reconcile(self, j, seq, run_id, evidence):
        rebuilt = W.rebuilt(j)
        rebuilt.reconcile(seq, run_id, evidence)
        j.storage.records.update(rebuilt.storage.records)


# 1 entry seam: default deny ---------------------------------------------------
class E1EntrySeamDenial(Base):
    def test_no_opt_in_refuses_pre_effect_zero_writes(self):
        for opt in (None, "yes", linux_entry.OPT_IN.lower()):
            run = launch(opt_in=opt)
            before = records(run.journal)
            stop = run.run()
            self.assertEqual(stop.stop_id, "SB_STOP_SAMPLER_CAPABILITY")
            self.assertIn("LINUX_ENTRY_NOT_OPTED_IN", stop.detail)
            self.assertEqual((records(run.journal), run.popen_calls), (before, 0))

    def test_missing_injected_port_refuses(self):
        for name in ("capability_backend", "termination_factory", "clock", "sleep"):
            run = launch(entry_override={name: None})
            stop = run.run()
            self.assertIn("LINUX_ENTRY_PORT_NOT_INJECTED:" + name, stop.detail)
            self.assertEqual(run.popen_calls, 0)

    def test_no_termination_authority_refuses_zero_writes(self):
        # NRP-2 FIX001 (F-05): the RUN_CONTEXT capability refusal is the
        # controller's ordinary pre-effect STOP (formerly a raw
        # NativeSamplerCapabilityError); the cause is chained, zero effects.
        run = launch(entry_override={"termination_factory": C.NoTerminationAuthority})
        before = records(run.journal)
        stop = run.run()
        self.assertIsInstance(stop, C.StopSignal)
        self.assertEqual(stop.stop_id, "SB_STOP_SAMPLER_CAPABILITY")
        self.assertIn("LINUX_ENTRY_NO_TERMINATION_AUTHORITY", stop.detail)
        self.assertIsInstance(stop.__cause__, C.NativeSamplerCapabilityError)
        self.assertEqual((records(run.journal), run.popen_calls), (before, 0))

    def test_controller_defaults_unchanged_deny_on_linux(self):
        with mock.patch.object(C, "sys", T.SysAs("linux")):
            with self.assertRaises(C.NativeSamplerCapabilityError):
                C._sampler_capability_backend()
            ctx = C.default_run_context(None)
        self.assertIsInstance(ctx.termination, C.NoTerminationAuthority)


# 2 normal A/B + identity handoff ----------------------------------------------
class E2AcceptedIdentityHandoff(Base):
    def test_normal_a_b_effect_record_bound_before_sampler(self):
        a = run_accepted()
        j = a.journal
        eff, raw = effect(j), j.storage.records["000001.EFFECT"]
        ev = eff["evidence"]
        self.assertEqual((ev["custody"], ev["root_authority_state"]),
                         ("REGISTERED", "ACQUIRED"))
        self.assertEqual(ev["identity"], {"token": IDENT, "provenance": "MODELED_INJECTED"})
        self.assertEqual(ev["observed_root"]["pid"], a.root.pid)
        self.assertEqual(eff["phase_sha256"], J.sha256(j.storage.records["000001.PHASE"]))
        self.assertEqual(eff["evidence_class"], J.EFFECT_EVIDENCE_CLASS)
        self.assertEqual(record(j, "000001.FINAL")["effect_sha256"], J.sha256(raw))
        steps = a.result["receipt"]["completed_in_order"]
        self.assertLess(steps.index("JOURNAL_EFFECT_IDENTITY_PUBLISHED"),
                        steps.index("JOURNAL_CLEANUP_RECORD_PUBLISHED"))
        # EFFECT written before any sampler object existed
        order = [e["kind"] for e in a.context.evidence]
        self.assertIn("ROOT_AUTHORITY", order)
        b = run_accepted(j, run_id="RUN-B")
        self.assertIsNotNone(effect(b.journal, 2))
        state = W.rebuilt(j).state()
        self.assertEqual([h["status"] for h in state["history"]], ["ACCEPTED", "ACCEPTED"])
        self.assertEqual(next_dispatch(j), (False, 1, 1))

    def test_provider_without_identity_records_none_never_invented(self):
        a = run_accepted(identity=False)
        self.assertIsNone(effect(a.journal)["evidence"]["identity"])
        self.assertTrue(W.rebuilt(a.journal).state()["ready"])

    def test_historical_a_after_refused_b(self):
        a = run_accepted()
        j = a.journal
        a_final = j.storage.records["000001.FINAL"]
        b = launch(j, run_id="RUN-B", accept=False)
        self.assertEqual(zero_effect_refusal(b).stop_id, "SB_STOP_DISPATCH_TICKET")
        self.assertEqual(P.phase(j, 2)["phase"], "CLOSED_ZERO_EFFECT")
        self.assertIsNone(effect(j, 2))
        self.assertEqual(j.accepted_dispatch(1)["status"], "ACCEPTED")
        self.assertEqual(W.rebuilt(j).accepted_dispatch(1)["sha"]["FINAL"], J.sha256(a_final))
        self.assertEqual(W.rebuilt(j).state()["reason"], "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def test_notification_loss_after_correct_commit(self):
        original = J.commit_current_dispatch

        def lost(*a, **k):
            original(*a, **k)
            raise ConnectionError("NOTIFICATION_LOST")
        run = launch()
        with V.valid_worker([]), mock.patch.object(J, "commit_current_dispatch", lost):
            with self.assertRaises(ConnectionError):
                run.run()
        j = run.journal
        self.assertEqual(record(j, "000001.FINAL")["status"], "ACCEPTED")
        rec = J.recover_committed_dispatch(
            W.rebuilt(j), 1, request_sha256=record(j, "000001.IN_FLIGHT")["request_sha256"],
            output_path=run.output_path)
        self.assertEqual(rec["seq"], 1)
        self.assertEqual(run.popen_calls, 1)                 # no rerun
        self.assertEqual(next_dispatch(j), (False, 1, 1))


# 3 zero-effect -------------------------------------------------------------
class E3ZeroEffect(Base):
    def test_zero_effect_refusal_and_reconcile_without_identity(self):
        run = launch(accept=False)
        self.assertEqual(zero_effect_refusal(run).stop_id, "SB_STOP_DISPATCH_TICKET")
        j = run.journal
        self.assertEqual(run.popen_calls, 0)
        self.assertEqual(P.phase(j, 1)["phase"], "CLOSED_ZERO_EFFECT")
        self.assertIsNone(effect(j))
        # identity facts over a mirrored zero-effect closure: refused (the
        # older, more specific zero-effect rule fires first)
        self.assert_refused_unchanged(j, 1, "RUN-A", identity_evidence(j, "RUN-A"),
                                      "CONTRADICTS_ZERO_EFFECT_CLOSURE")
        self.reconcile(j, 1, "RUN-A", never_evidence(j, "RUN-A"))
        rec = record(j, "000001.RECONCILED")
        for kind in ("ROOT_PROCESS", "KNOWN_DESCENDANTS", "CAPABILITY_CUSTODY"):
            self.assertNotIn("identity", rec["obligations"][kind])
        self.assertIsNone(rec["disposition"]["observed_effect_sha256"])
        self.assertTrue(W.rebuilt(j).state()["ready"])
        self.assertEqual(next_dispatch(j), (False, 1, 1))

    def test_pre_effect_close_lock_exhaustion_is_finite_and_fails_closed(self):
        run = launch(accept=False)
        lock = FakeLock()
        prog = run.journal.progression
        original = prog.create_new

        def fail_phase(name, data):       # after admission: lock then refuse
            if name == "000001.PHASE":
                run.route.table._lock = lock
                raise OSError(28, "ENOSPC")
            return original(name, data)
        prog.create_new = fail_phase
        stop = run.run()
        prog.create_new = original
        self.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_TICKET")
        self.assertEqual(lock.timeouts, [C.PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS])
        self.assertIn("RUN_CONTEXT_CUSTODY_UNRESOLVED", stop.detail)
        j = run.journal
        self.assertIsNone(P.phase(j, 1))                   # no zero-effect proof
        self.assertEqual(record(j, "000001.FINAL")["pre_effect_cause"]["run_context_close"],
                         "CUSTODY_UNRESOLVED:TABLE_LOCK_NOT_ACQUIRED_WITHIN_DEADLINE")
        self.assertFalse(run.context.closed)
        self.assert_refused_unchanged(j, 1, "RUN-A", never_evidence(j, "RUN-A"),
                                      "NO_ZERO_EFFECT_PHASE_EVIDENCE")
        self.assertEqual(run.popen_calls, 0)
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def test_pre_effect_close_uses_existing_deadline_never_resets(self):
        k = T.FakeKernel()
        route = T.sim_route(k)
        ctx = T.context_for(k, T.make_backend(k), route)
        dl = ctx.start_deadline(5.0, "X")
        advance(k, 2.0)
        seen = []
        with mock.patch.object(ctx, "close", side_effect=lambda lock_timeout: seen.append(
                lock_timeout) or "CLOSED"):
            C._pre_effect_close(ctx)
        self.assertIs(ctx.deadline, dl)
        self.assertAlmostEqual(seen[0], 3.0)


# 4 spawn uncertainty / acquisition failure ------------------------------------
class E4PossibleEffectWithoutIdentity(Base):
    def test_spawn_raises_effect_permitted_no_identity(self):
        run = launch(accept=False)
        lock = FakeLock()

        def boom(*a, **k):
            run.popen_calls += 1
            run.route.table._lock = lock
            raise OSError(5, "EIO_SPAWN_UNCERTAIN")
        run.popen_factory = boom
        with self.assertRaises(OSError):
            run.run()
        self.assertEqual(lock.timeouts, [C.PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS])
        j = run.journal
        self.assertEqual(P.phase(j, 1)["phase"], "EFFECT_PERMITTED")
        self.assertEqual(record(j, "000001.FINAL")["reason"], "SPAWN_FAILED")
        self.assertIsNone(effect(j))
        self.assert_refused_unchanged(j, 1, "RUN-A", never_evidence(j, "RUN-A"),
                                      "NO_ZERO_EFFECT_PHASE_EVIDENCE")
        self.assert_refused_unchanged(j, 1, "RUN-A", identity_evidence(j, "RUN-A"),
                                      "NO_RECORDED_IDENTITY:NO_EFFECT_IDENTITY_RECORD")
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def test_acquisition_failure_recorded_not_registered_refuses_acceptance(self):
        run = launch()
        with mock.patch.object(run.route, "acquire_root",
                               side_effect=OSError(1, "EPERM_ACQUIRE")):
            with V.valid_worker([]):
                stop = run.run()
        j = run.journal
        ev = effect(j)["evidence"]
        self.assertEqual((ev["custody"], ev["identity"]), ("NOT_REGISTERED", None))
        self.assertTrue(ev["root_authority_state"].startswith("UNAVAILABLE"))
        self.assertIsNotNone(stop)
        self.assertNotEqual((record(j, "000001.FINAL") or {}).get("status"), "ACCEPTED")
        self.assertFalse(W.rebuilt(j).state()["ready"])
        self.assert_refused_unchanged(j, 1, "RUN-A", identity_evidence(j, "RUN-A"),
                                      "NO_RECORDED_IDENTITY:EFFECT_RECORD")
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def test_attach_raises_non_oserror(self):
        run = launch(accept=False)
        with mock.patch.object(run.route, "acquire_root",
                               side_effect=RuntimeError("ACQUIRE_BROKEN")):
            stop = run.run()
        j = run.journal
        self.assertIsNotNone(stop)
        self.assertIsNone(effect(j))
        self.assertEqual(record(j, "000001.FINAL")["status"], "STOP")
        self.assert_refused_unchanged(j, 1, "RUN-A", identity_evidence(j, "RUN-A"),
                                      "NO_RECORDED_IDENTITY")
        self.assertEqual(next_dispatch(j), (True, 0, 0))


# 5 identity write failure after effect -----------------------------------------
class E5IdentityWriteFailure(Base):
    def test_effect_write_fails_owned_root_cleaned_primary_kept(self):
        run = launch(accept=False)
        run.journal.storage.fail[("create", "000001.EFFECT")] = OSError(28, "EFFECT_ENOSPC")
        stop = run.run()
        j = run.journal
        self.assertIsNotNone(stop)
        self.assertIn("EFFECT_ENOSPC", json.dumps(stop.cleanup, default=str))
        self.assertIn("EFFECT_IDENTITY", json.dumps(stop.cleanup, default=str))
        self.assertIsNone(effect(j))
        self.assertIsNone(record(j, "000001.CLEANUP"))
        self.assertEqual(record(j, "000001.FINAL")["status"], "STOP")
        # the already-owned fake root was signalled through its capability
        self.assertTrue(T.delivered(run.route.port))
        self.assertNotIn(run.root.pid, [p for p, s in run.k.procs.items() if s.state != "Z"])
        j.storage.fail.clear()
        self.assertFalse(W.rebuilt(j).state()["ready"])
        self.assert_refused_unchanged(j, 1, "RUN-A", identity_evidence(j, "RUN-A"),
                                      "NO_RECORDED_IDENTITY")
        self.assert_refused_unchanged(j, 1, "RUN-A", never_evidence(j, "RUN-A"),
                                      "NO_ZERO_EFFECT_PHASE_EVIDENCE")
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def test_effect_late_return_after_persist(self):
        run = launch(accept=False)
        store = run.journal.storage
        original = store.create_new

        def late(name, data):
            original(name, data)
            if name.endswith(".EFFECT"):
                raise TimeoutError("LATE_RETURN_AFTER_PERSIST")
        store.create_new = late
        stop = run.run()
        store.create_new = original
        j = run.journal
        self.assertIsNotNone(stop)
        self.assertIsNotNone(effect(j))                 # durable, but not acted on
        self.assertIsNone(record(j, "000001.CLEANUP"))
        self.assertEqual(record(j, "000001.FINAL")["status"], "STOP")
        self.assertEqual(next_dispatch(j), (True, 0, 0))
        # positive reconciliation cites the RECORDED identity + disposition
        self.assert_refused_unchanged(j, 1, "RUN-A",
                                      identity_evidence(j, "RUN-A", token="other"),
                                      "IDENTITY_NOT_RECORDED_IDENTITY")
        good = identity_evidence(j, "RUN-A")
        self.assertEqual(good["disposition"]["observed_effect_sha256"],
                         J.sha256(j.storage.records["000001.EFFECT"]))
        self.reconcile(j, 1, "RUN-A", good)
        self.assertTrue(W.rebuilt(j).state()["ready"])
        self.assertEqual(next_dispatch(j), (False, 1, 1))

    def test_all_later_writes_fail(self):
        run = launch()
        for name in ("000001.CLEANUP", "000001.FINAL"):
            run.journal.storage.fail[("create", name)] = OSError(5, "EIO_LATER")
        with V.valid_worker([]):
            stop = run.run()
        j = run.journal
        self.assertIsNotNone(stop)
        j.storage.fail.clear()
        self.assertIsNotNone(effect(j))
        self.assertIsNone(record(j, "000001.FINAL"))
        self.assertEqual(W.rebuilt(j).state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        self.assertTrue(run.latch.blocked)
        self.assertEqual(next_dispatch(j), (True, 0, 0))
        self.reconcile(j, 1, "RUN-A", identity_evidence(j, "RUN-A"))
        self.assertTrue(W.rebuilt(j).state()["ready"])


# 6 binding mismatches, stale/copied tickets ------------------------------------
class E6Bindings(Base):
    def stopped_with_effect(self):
        run = launch()
        run.journal.storage.fail[("create", "000001.CLEANUP")] = OSError(5, "EIO")
        with V.valid_worker([]):
            run.run()
        run.journal.storage.fail.clear()
        return run, run.journal

    def test_wrong_run_scope_disposition_identity(self):
        run, j = self.stopped_with_effect()
        good = identity_evidence(j, "RUN-A")
        bad_disp = json.loads(json.dumps(good))
        bad_disp["disposition"]["observed_effect_sha256"] = "0" * 64
        bad_ident = json.loads(json.dumps(good))
        bad_ident["disposition"]["observed_root_identity"]["token"] = "forged"
        for ev, code in ((bad_disp, "DISPOSITION_BINDING:observed_effect_sha256"),
                         (bad_ident, "DISPOSITION_BINDING:observed_root_identity"),
                         (identity_evidence(j, "RUN-A", token="x"),
                          "IDENTITY_NOT_RECORDED_IDENTITY")):
            self.assert_refused_unchanged(j, 1, "RUN-A", ev, code)
        self.assert_refused_unchanged(j, 1, "RUN-B", good, "RUN_MISMATCH")
        with self.assertRaises(J.JournalRefused):
            W.rebuilt(j, dispatcher_owner="OTHER").reconcile(1, "RUN-A", good)
        self.assertEqual(W.rebuilt(j, dispatcher_owner="OTHER").state()["reason"],
                         "RECORD_SCOPE_OR_SCHEMA_MISMATCH")

    def test_tampered_effect_record_refuses_integrity(self):
        run, j = self.stopped_with_effect()
        raw = j.storage.records["000001.EFFECT"]
        for old, new in ((IDENT.encode(), b"forged-root-7"),
                         (b'"seq":1', b'"seq":2'),
                         (b"MODELED_INJECTED", b"NATIVE_PIDFD_XX")):
            k = W.rebuilt(j)
            k.storage.records["000001.EFFECT"] = raw.replace(old, new)
            reason = k.state()["reason"]
            self.assertIn(reason, ("EFFECT_BINDING_MISMATCH", "RECORD_SEQ_MISMATCH",
                                   "FINAL_BINDING_MISMATCH"))
            with self.assertRaises(J.JournalRefused):
                k.reconcile(1, "RUN-A", identity_evidence(k, "RUN-A"))

    def test_retained_and_copied_ticket_after_final_and_reconcile(self):
        a = run_accepted()
        j = a.journal
        ticket = J.DispatchTicket(j, dict(W.rebuilt(j).load_ticket(1).binding))
        ev = C._effect_evidence(a.popen, a.context)
        before = records(j)
        with self.assertRaises(J.JournalRefused) as c1:
            ticket.record_effect_identity(ev)
        self.assertIn("no_effect_handoff", str(c1.exception))
        ticket.effect_permitted = True                        # retained-authority object
        with self.assertRaises(J.JournalRefused) as c2:
            ticket.record_effect_identity(ev)
        self.assertIn("FINAL_present", str(c2.exception))
        with self.assertRaises(J.JournalRefused):
            W.rebuilt(j).load_ticket(1).record_effect_identity(ev)
        self.assertEqual(records(j), before)
        run, k = self.stopped_with_effect()
        self.reconcile(k, 1, "RUN-A", identity_evidence(k, "RUN-A"))
        t2 = J.DispatchTicket(k, dict(k.load_ticket(1).binding))
        t2.effect_permitted = True
        before = records(k)
        with self.assertRaises(J.JournalRefused) as c3:
            t2.record_effect_identity(ev)
        self.assertIn("RECONCILED_present", str(c3.exception))
        self.assertEqual(records(k), before)
        self.assertEqual(next_dispatch(k), (False, 1, 1))


# 7 historical pre-identity-protocol records -------------------------------------
BEFORE_JOURNAL = os.environ.get("NRP2_BEFORE_JOURNAL")


def before_journal_module():
    spec = importlib.util.spec_from_file_location("nrp2_before_journal", BEFORE_JOURNAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(BEFORE_JOURNAL and os.path.isfile(BEFORE_JOURNAL),
                     "set NRP2_BEFORE_JOURNAL to the pre-NRP-2 journal bytes")
class E7HistoricalPreIdentity(Base):
    def old_stopped(self):
        O = before_journal_module()
        j = O.DispatchJournal(O.MemoryStorage(), progression=O.MemoryStorage(),
                              run_generation=1, input_identity="TEST-INPUT",
                              dispatcher_owner="TEST-DISPATCHER")
        j.initialize_scope()
        t = j.reserve("OLD-1", "a" * 64, "/r", "/o")
        t.check_execution(run_id="OLD-1", request_sha256="a" * 64, raw_path="/r",
                          output_path="/o")
        t.stop("OLD_POST_SPAWN_STOP")
        return O, j

    def test_old_reconciled_identity_readable_new_write_refused(self):
        O, old = self.old_stopped()
        new = W.rebuilt(old)
        self.assertNotIn("effect_protocol",
                         json.loads(new.progression.records["000001.RESERVED"]))
        self.assert_refused_unchanged(new, 1, "OLD-1", F2.reconciliation(new, "OLD-1"),
                                      "NO_RECORDED_IDENTITY:PRE_IDENTITY_PROTOCOL")
        old.reconcile(1, "OLD-1", F2.reconciliation(old, "OLD-1"))   # old rule, old code
        new = W.rebuilt(old)
        state = new.state()
        self.assertEqual(state["history"][0]["status"], "RECONCILED")   # old status kept
        self.assertTrue(state["ready"])
        self.assertEqual(next_dispatch(new), (False, 1, 1))



# 8 NRP-2 FIX001: real orchestrator adapter (journaled_exact_launch) + ledger --
class ArmedLock(FakeLock):
    """Table lock that works (in-process threading lock) until armed, then
    never acquires; records only the armed (refused) timeouts."""

    def __init__(self):
        super().__init__()
        import threading
        self.real, self.armed = threading.Lock(), False

    def acquire(self, blocking=True, timeout=-1):
        if self.armed:
            return super().acquire(blocking, timeout)
        return self.real.acquire(blocking, timeout)

    def release(self):
        self.real.release()


class E8OrchestratorAdapter(Base):
    """Drives the exact stage_b_orchestrator.journaled_exact_launch with the
    exact launch_request (W.HarnessLauncher: fake kernel/popen/sampler); the
    route records a MODELED_INJECTED root token unless identity=False.  The
    adapter's return value is the only thing that may reach a ledger."""

    def call(self, j=None, identity=True, route_tweak=None, context_tweak=None,
             store_tweak=None):
        j = j if j is not None else W.journal()
        launcher = W.HarnessLauncher(["ACCEPT"])
        paths = self.paths = X.Paths("e8")
        original_route, original_ctx = T.sim_route, T.Launch.context_factory

        def route(k, run_id="RUN-A", **kw):
            r = original_route(k, run_id, **kw)
            if route_tweak:
                route_tweak(r)
            return linux_entry.ModeledRootIdentity(r, lambda p: IDENT) if identity else r

        def context_factory(launch, backend):
            return (context_tweak or original_ctx)(launch, backend)
        out = {"launcher": launcher, "paths": paths, "j": j}
        with mock.patch.object(T, "sim_route", route), \
                mock.patch.object(T.Launch, "context_factory", context_factory):
            if store_tweak:
                store_tweak(j)
            try:
                out["ledger"] = paths.call(launcher, j, W.orch_request(0, paths.tmp),
                                           stem="e8")
                out["stop"] = None
            except C.StopSignal as stop:
                out["ledger"], out["stop"] = None, stop
        out["output"] = paths.output("e8")
        out["run"] = launcher.runs[-1] if launcher.runs else None
        return out

    def assert_refused_scope(self, o):
        j = o["j"]
        self.assertIsNone(o["ledger"])                          # no ledger row
        self.assertEqual(o["stop"].stop_id, "SB_STOP_GLOBAL")
        self.assertFalse(o["output"].exists())                  # no envelope
        self.assertNotEqual((record(j, "000001.FINAL") or {}).get("status"), "ACCEPTED")
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(o["output"], W.rebuilt(j))
        self.assertFalse(W.rebuilt(j).state()["ready"])
        self.assertEqual(next_dispatch(j), (True, 0, 0))      # reconstruct + next fake spawn

    def test_positive_adapter_control(self):
        o = self.call()
        j = o["j"]
        self.assertIsNone(o["stop"])
        self.assertIsNotNone(o["ledger"])
        ev = effect(j)["evidence"]
        self.assertEqual((ev["custody"], ev["identity"]),
                         ("REGISTERED", {"token": IDENT, "provenance": "MODELED_INJECTED"}))
        self.assertEqual(record(j, "000001.FINAL")["status"], "ACCEPTED")
        env = J.verify_controller_acceptance(o["output"], W.rebuilt(j))
        self.assertEqual(env["accepted_result"], o["ledger"])
        self.assertEqual(o["launcher"].spawns, 1)
        self.assertEqual(next_dispatch(j), (False, 1, 1))

    def test_effect_write_fails_before_persist(self):
        def fail(j):
            j.storage.fail[("create", "000001.EFFECT")] = OSError(28, "EFFECT_ENOSPC")
        o = self.call(store_tweak=fail)
        j, run = o["j"], o["run"]
        j.storage.fail.clear()
        self.assertEqual(o["launcher"].spawns, 1)
        self.assertIsNone(effect(j))
        self.assertIsNone(record(j, "000001.CLEANUP"))
        final = record(j, "000001.FINAL")
        self.assertEqual(final["status"], "STOP")
        self.assertIn("EFFECT_ENOSPC", o["stop"].cleanup["primary"])       # primary kept
        # the lower controller's own STOP is already durable: no duplicate
        # FINAL write error is manufactured by the adapter refusal
        self.assertEqual(o["stop"].cleanup["secondary_failures"], [])
        self.assertTrue(T.delivered(run.route.port))                  # owned root cleaned
        self.assert_refused_scope(o)
        self.assert_refused_unchanged(j, 1, "STAGEB_REQUEST",
                                      identity_evidence(j, "STAGEB_REQUEST"),
                                      "NO_RECORDED_IDENTITY")

    def test_effect_late_failure_after_persist(self):
        def late(j):
            original = j.storage.create_new

            def create(name, data):
                original(name, data)
                if name.endswith(".EFFECT"):
                    raise TimeoutError("LATE_RETURN_AFTER_PERSIST")
            j.storage.create_new = create
        o = self.call(store_tweak=late)
        j = o["j"]
        self.assertIsNotNone(effect(j))                     # durable, not acted on
        self.assertIsNone(record(j, "000001.CLEANUP"))
        self.assertEqual(record(j, "000001.FINAL")["status"], "STOP")
        self.assertIn("LATE_RETURN_AFTER_PERSIST", o["stop"].cleanup["primary"])
        self.assertEqual(o["stop"].cleanup["secondary_failures"], [])
        self.assertTrue(T.delivered(o["run"].route.port))
        self.assert_refused_scope(o)
        # the recorded modeled token is the only positive identity route
        self.assert_refused_unchanged(j, 1, "STAGEB_REQUEST",
                                      identity_evidence(j, "STAGEB_REQUEST", token="other"),
                                      "IDENTITY_NOT_RECORDED_IDENTITY")
        self.reconcile(j, 1, "STAGEB_REQUEST", identity_evidence(j, "STAGEB_REQUEST"))
        self.assertTrue(W.rebuilt(j).state()["ready"])

    def test_all_subsequent_writes_fail(self):
        def fail(j):
            for name in ("000001.CLEANUP", "000001.FINAL"):
                j.storage.fail[("create", name)] = OSError(5, "EIO_LATER")
        o = self.call(store_tweak=fail)
        j = o["j"]
        cleanup = o["stop"].cleanup
        self.assertIn("EIO_LATER", cleanup["primary"])
        self.assertTrue(any(f.startswith("JOURNAL_FINAL_STOP:") and "EIO_LATER" in f
                            for f in cleanup["secondary_failures"]), cleanup)
        j.storage.fail.clear()
        self.assertIsNotNone(effect(j))
        self.assertIsNone(record(j, "000001.FINAL"))
        self.assertEqual(W.rebuilt(j).state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        raw = C.raw_worker_output_path(o["output"], "STAGEB_REQUEST")
        if raw.exists():                                   # raw preserved, not accepted
            self.assertTrue(raw.read_bytes())
        self.assert_refused_scope(o)

    # FIX002: distinct markers per failed write, so a secondary failure can
    # never pass for the primary one.
    CLEANUP_EIO = "PREPARED_PUBLISH:OSError:[Errno 5] EIO_CLEANUP"
    FINAL_EIO = "JOURNAL_FINAL_STOP:OSError:[Errno 5] EIO_FINAL"
    RAW_BYTES = 487             # the harness worker result (Fable P13, Astra)

    def failing(self, *names):
        def tweak(j):
            for name in names:
                j.storage.fail[("create", "000001." + name)] = OSError(5, "EIO_" + name)
        return tweak

    def assert_raw_kept(self, o):
        raw = C.raw_worker_output_path(o["output"], "STAGEB_REQUEST")
        data = raw.read_bytes()
        self.assertEqual(len(data), self.RAW_BYTES)
        self.assertEqual(json.loads(data)["measured_repetition"], 0)
        return raw, data

    def assert_natural_reap_not_signal(self, o, completion):
        # the worker exited by itself and completion cleanup reaped it:
        # no capability signal was sent and ownership closed normally
        self.assertEqual(T.delivered(o["run"].route.port), [])
        self.assertEqual((completion["worker_returncode"], completion["root_reaped"],
                          completion["custody"]["outcome"], completion["context_closed"]),
                         (0, True, "ALL_CLOSED", True))

    def test_cleanup_then_final_failure_primary_is_cleanup(self):
        # ASTRA-NRP2-FIX002-PRIMARY: CLEANUP publication fails, then the
        # controller's own FINAL STOP fails too.
        o = self.call(store_tweak=self.failing("CLEANUP", "FINAL"))
        j, outer = o["j"], o["stop"].cleanup
        self.assertIn("EIO_CLEANUP", outer["primary"])
        self.assertNotIn("EIO_FINAL", outer["primary"])
        self.assertEqual(outer["primary"], "StopSignal:SB_STOP_ACCEPTANCE_PUBLICATION:"
                         + self.CLEANUP_EIO)
        self.assertEqual(outer["secondary_failures"], [self.FINAL_EIO])
        inner = o["stop"].__cause__                     # the controller's StopSignal
        self.assertIsInstance(inner, C.StopSignal)
        self.assertEqual((inner.stop_id, inner.detail),
                         ("SB_STOP_ACCEPTANCE_PUBLICATION", self.CLEANUP_EIO))
        self.assertIsInstance(inner.__cause__, OSError)  # original cause kept
        self.assertEqual(inner.__cause__.strerror, "EIO_CLEANUP")
        receipt = inner.cleanup["receipt"]              # full receipt kept
        self.assertEqual(receipt["failures"], [self.CLEANUP_EIO, self.FINAL_EIO])
        self.assertEqual(receipt["final"], "STOP")
        self.assertEqual(receipt["completed_in_order"], [
            "PROGRESSION_RESERVED_PUBLISHED", "JOURNAL_IN_FLIGHT_PUBLISHED",
            "TICKET_CHECKED_BEFORE_SPAWN", "JOURNAL_EFFECT_IDENTITY_PUBLISHED"])
        self.assertIn({"run_id": "STAGEB_REQUEST", "reasons": ["PREPARED_PUBLISH_FAILED"]},
                      o["launcher"].latch.records)
        self.assert_natural_reap_not_signal(o, inner.cleanup["completion"])
        j.storage.fail.clear()
        raw, data = self.assert_raw_kept(o)
        self.assertIsNotNone(effect(j))
        self.assertIsNone(record(j, "000001.CLEANUP"))
        self.assertIsNone(record(j, "000001.FINAL"))
        self.assertEqual(W.rebuilt(j).state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        self.assert_refused_scope(o)                    # no envelope/ledger, next refused
        self.assertEqual(raw.read_bytes(), data)        # raw untouched by the refusals

    def test_single_cleanup_failure_control(self):
        o = self.call(store_tweak=self.failing("CLEANUP"))
        j, outer = o["j"], o["stop"].cleanup
        self.assertEqual(outer["primary"], "StopSignal:SB_STOP_ACCEPTANCE_PUBLICATION:"
                         + self.CLEANUP_EIO)
        self.assertEqual(outer["secondary_failures"], [])  # its own STOP is durable
        inner = o["stop"].__cause__
        self.assertEqual(inner.__cause__.strerror, "EIO_CLEANUP")
        receipt = inner.cleanup["receipt"]
        self.assertEqual(receipt["failures"], [self.CLEANUP_EIO])
        self.assertEqual(receipt["completed_in_order"][-1], "JOURNAL_FINAL_STOP_PUBLISHED")
        self.assert_natural_reap_not_signal(o, inner.cleanup["completion"])
        j.storage.fail.clear()
        raw, data = self.assert_raw_kept(o)
        self.assertIsNone(record(j, "000001.CLEANUP"))
        final = record(j, "000001.FINAL")
        self.assertEqual((final["status"], final["reason"]),
                         ("STOP", "PREPARED_PUBLISH_FAILED"))
        self.assert_refused_scope(o)
        self.assertEqual(raw.read_bytes(), data)

    def test_only_final_failure_control(self):
        # CLEANUP succeeds; the coordinator's FINAL ACCEPTED is the primary
        # failure and its FINAL STOP the secondary one.  The envelope was
        # published before FINAL but is unjournaled, so it is refused.
        o = self.call(store_tweak=self.failing("FINAL"))
        j, outer = o["j"], o["stop"].cleanup
        self.assertEqual(outer["primary"], "JournalRefused:COMMIT_PUBLISH_FAILED:after:"
                         "ACCEPTANCE_ENVELOPE_PUBLISHED:OSError:[Errno 5] EIO_FINAL")
        self.assertEqual(outer["secondary_failures"], [self.FINAL_EIO])
        self.assertNotIn("EIO_CLEANUP", json.dumps(outer))
        self.assertEqual(T.delivered(o["run"].route.port), [])
        j.storage.fail.clear()
        raw, data = self.assert_raw_kept(o)
        self.assertIsNotNone(record(j, "000001.CLEANUP"))
        self.assertIsNone(record(j, "000001.FINAL"))
        self.assertIsNone(o["ledger"])
        self.assertTrue(o["output"].exists())
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(o["output"], W.rebuilt(j))
        self.assertEqual(W.rebuilt(j).state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        self.assertEqual(next_dispatch(j), (True, 0, 0))
        self.assertEqual(raw.read_bytes(), data)

    def test_acquisition_refusal_no_envelope_before_commit(self):
        # F-04: custody NOT_REGISTERED is refused by the coordinated prepared
        # verification BEFORE any acceptance envelope is published.
        def tweak(route):
            route.acquire_root = mock.Mock(side_effect=OSError(1, "EPERM_ACQUIRE"))
        o = self.call(route_tweak=tweak)
        j = o["j"]
        ev = effect(j)["evidence"]
        self.assertEqual((ev["custody"], ev["identity"]), ("NOT_REGISTERED", None))
        final = record(j, "000001.FINAL")
        self.assertEqual(final["status"], "STOP")
        text = json.dumps(final)
        self.assertIn("effect_custody_registered", text)
        self.assertNotIn("COMMIT_PUBLISH_FAILED", text)
        self.assertIn("CURRENT_DISPATCH_MISMATCH", o["stop"].cleanup["primary"])
        self.assertEqual(o["stop"].cleanup["secondary_failures"], [])
        self.assert_refused_scope(o)

    def test_run_context_refusal_on_ticket_path_single_durable_stop(self):
        # F-05 on the adapter: RUN_CONTEXT refusal -> controller StopSignal,
        # its CLOSED_ZERO_EFFECT + STOP is the durable refusal; the adapter
        # manufactures no duplicate FINAL write error.
        def refuse(launch, backend):
            entry = linux_entry.LinuxControllerEntry(
                C, opt_in=linux_entry.OPT_IN, capability_backend=backend,
                termination_factory=C.NoTerminationAuthority,
                clock=lambda: launch.k.clock, sleep=lambda s: advance(launch.k, s),
                run_id=launch.run_id, dispatch_latch=launch.latch)
            return entry.run_context_factory(backend)
        o = self.call(context_tweak=refuse)
        j = o["j"]
        self.assertEqual(o["launcher"].spawns, 0)
        self.assertEqual(P.phase(j, 1)["phase"], "CLOSED_ZERO_EFFECT")
        final = record(j, "000001.FINAL")
        self.assertEqual((final["status"], final["reason"]),
                         ("STOP", "PRE_EFFECT_ADMISSION_REFUSED"))
        self.assertIn("LINUX_ENTRY_NO_TERMINATION_AUTHORITY", o["stop"].cleanup["primary"])
        self.assertEqual(o["stop"].cleanup["secondary_failures"], [])
        self.assertIsNone(effect(j))
        self.assert_refused_scope(o)

    def test_pre_effect_close_single_wait_on_ticket_path(self):
        # F-08: inline close + _pre_effect_refusal share ONE finite wait and
        # its unresolved outcome (no zero-effect proof, no second wait).
        lock = ArmedLock()
        original_ctx = T.Launch.context_factory

        def armed(launch, backend):
            ctx = original_ctx(launch, backend)
            real_admit = ctx.admit

            def admit(*a, **k):
                result = real_admit(*a, **k)
                launch.route.table._lock = lock
                lock.armed = True
                raw = C.raw_worker_output_path(self.paths.output("e8"), launch.run_id)
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text("{}")         # raw path no longer fresh
                return result
            ctx.admit = admit
            return ctx
        o = self.call(context_tweak=armed)
        j = o["j"]
        self.assertEqual(lock.timeouts, [C.PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS])
        self.assertEqual(o["launcher"].spawns, 0)
        self.assertIsNone(P.phase(j, 1))                      # no zero-effect proof
        final = record(j, "000001.FINAL")
        self.assertEqual(final["pre_effect_cause"]["run_context_close"],
                         "CUSTODY_UNRESOLVED:TABLE_LOCK_NOT_ACQUIRED_WITHIN_DEADLINE")
        self.assertIn("output_paths_not_fresh", o["stop"].cleanup["primary"])
        self.assertFalse(o["run"].context.closed)             # custody unresolved
        self.assert_refused_unchanged(j, 1, "STAGEB_REQUEST",
                                      never_evidence(j, "STAGEB_REQUEST"),
                                      "NO_ZERO_EFFECT_PHASE_EVIDENCE")

    def test_pre_effect_close_outcome_reused_not_rewaited(self):
        k = T.FakeKernel()
        ctx = T.context_for(k, T.make_backend(k), T.sim_route(k))
        calls = []
        with mock.patch.object(ctx, "close", side_effect=lambda lock_timeout: calls.append(
                lock_timeout) or "CUSTODY_UNRESOLVED:X"):
            self.assertEqual(C._pre_effect_close(ctx), "CUSTODY_UNRESOLVED:X")
            self.assertEqual(C._pre_effect_close(ctx), "CUSTODY_UNRESOLVED:X")
        self.assertEqual(calls, [C.PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS])
        ctx2 = T.context_for(k, T.make_backend(k), T.sim_route(k))
        with mock.patch.object(ctx2, "close", side_effect=RuntimeError("CLOSE_BROKEN")):
            with self.assertRaises(RuntimeError):
                C._pre_effect_close(ctx2)
            self.assertEqual(C._pre_effect_close(ctx2), "CLOSE_FAILED:RuntimeError")


class E9StopAlreadyDurable(Base):
    def test_only_valid_stop_of_this_ticket_counts_as_already_durable(self):
        # F-05: real inconsistencies are never suppressed
        guard = J.JournalRefused("DISPATCH_HISTORY_CLOSED",
                                 {"seq": 1, "kind": "FINAL", "failed": ["FINAL_present"]})
        accepted = run_accepted().journal                     # FINAL ACCEPTED
        self.assertFalse(J._ticket_stop_already_durable(accepted, accepted.load_ticket(1),
                                                        guard))
        run = launch(accept=False)
        self.assertEqual(zero_effect_refusal(run).stop_id, "SB_STOP_DISPATCH_TICKET")
        j = run.journal                                       # controller's own STOP
        ticket = j.load_ticket(1)
        self.assertTrue(J._ticket_stop_already_durable(j, ticket, guard))
        for other in (J.JournalRefused("DISPATCH_HISTORY_CLOSED", {
                          "seq": 1, "failed": ["FINAL_present", "IN_FLIGHT_mismatch"]}),
                      J.JournalRefused("RECORD_LOST", "x"), OSError(5, "EIO")):
            self.assertFalse(J._ticket_stop_already_durable(j, ticket, other))
        # a FINAL that no longer validates is not "already durable"
        value = json.loads(j.storage.records["000001.FINAL"])
        value["ticket_sha256"] = "0" * 64
        j.storage.records["000001.FINAL"] = J.canonical(value)
        self.assertFalse(J._ticket_stop_already_durable(j, ticket, guard))
        failures = J.refuse_current_dispatch(j, ticket, "X", "Y")
        self.assertTrue(failures and failures[0].startswith("JOURNAL_FINAL_STOP:"), failures)


class E9EffectShape(Base):
    def test_returncode_at_attach_int_or_none_on_write_and_read(self):
        run = run_accepted()
        ev = effect(run.journal)["evidence"]
        for good in (None, 0, -9):
            J.validate_effect_evidence(dict(ev, observed_root=dict(
                ev["observed_root"], returncode_at_attach=good)))
        for bad in ("weird", True, False, 1.0, [], {}):
            with self.assertRaises(J.JournalRefused):
                J.validate_effect_evidence(dict(ev, observed_root=dict(
                    ev["observed_root"], returncode_at_attach=bad)))
        # read time: a durable EFFECT rewritten with a bool is refused
        j = run.journal
        value = json.loads(j.storage.records["000001.EFFECT"])
        value["evidence"]["observed_root"]["returncode_at_attach"] = True
        j.storage.records["000001.EFFECT"] = J.canonical(value)
        self.assertFalse(W.rebuilt(j).state()["ready"])


if __name__ == "__main__":
    unittest.main()
