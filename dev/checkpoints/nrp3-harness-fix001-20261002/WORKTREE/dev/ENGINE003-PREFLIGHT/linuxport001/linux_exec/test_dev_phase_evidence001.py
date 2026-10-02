"""DEV_PHASE_EVIDENCE001 pure-simulation matrix (no native effects).

Usability gap after DEV007_FIX005 PASS: a lower-controller refusal before the
ticket check was only recorded as COORDINATOR_REFUSED, so a truthful
ROOT_NEVER_SPAWNED reconciliation was refused.  Protocol EFFECT_HANDOFF/v1
(stage_b_dispatch_journal module docstring) adds ONE durable effect-handoff
slot per dispatch, mirrored no-clobber in both stores: EFFECT_PERMITTED
(check_execution, before any spawn) or CLOSED_ZERO_EFFECT (the controller's
own pre-effect refusal path, _pre_effect_refusal).  Only a mirrored
CLOSED_ZERO_EFFECT slot (or a never-issued ticket) supports
ROOT_NEVER_SPAWNED, and nothing reconciles automatically.

Every case runs the exact stage_b_orchestrator.journaled_exact_launch /
stage_b_controller.launch_request / stage_b_dispatch_journal over the fake
kernel, FakePopen and MemoryStorage fixtures and checks: current decision,
durable slot/cause/STOP bindings, raw/old-final preservation, the permission
of a RECONSTRUCTED journal (W.rebuilt) and the next fake spawn count.  The
"fixture counted zero spawns" is never used as evidence by the code under
test; it is only the test's observation.
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

import test_dev006 as T  # noqa: E402
import test_dev007_fix001 as V  # noqa: E402
import test_dev007_fix002 as F2  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix005 as X  # noqa: E402
from test_dev007_fix004 import Paths, request_sha  # noqa: E402

C = T.C
J = C.journal_protocol
LABEL = "STAGEB_REQUEST"
record, records, next_dispatch = X.record, X.records, X.next_dispatch
NEVER = dict(J.ZERO_EFFECT_FACTS)


def never_evidence(j, run_id=LABEL, **override):
    """Truthful zero-effect facts: no identity is asserted anywhere."""
    return F2.reconciliation(j, run_id, obligations={
        k: {"kind": v, "resolved": True, "run_id": run_id} for k, v in NEVER.items()},
        **override)


def edit_cause(raw):
    changed = raw.replace(b"PRE_EFFECT:RUN_CONTEXT", b"PRE_EFFECT:RUN_CONTEXX")
    assert changed != raw
    return changed


def fail_once(store, name, error):
    original, done = store.create_new, []

    def create_new(n, data):
        if n == name and not done:
            done.append(n)
            raise error
        return original(n, data)
    store.create_new = create_new


def phase(j, seq=2, store="storage"):
    raw = getattr(j, store).records.get(f"{seq:06d}.PHASE")
    return None if raw is None else json.loads(raw)


class ContextAdmissionFailure:
    """Injected fake: RunContext.admit fails inside the real controller."""

    def __init__(self, error):
        self.error = error

    def __enter__(self):
        self.patch = mock.patch.object(C.RunContext, "admit", side_effect=self.error)
        self.patch.start()

    def __exit__(self, *exc):
        self.patch.stop()


class Base(X.Base):
    def refuse_b(self, launcher, **kw):
        return self.refused(launcher, self.req_b, **kw)

    def admission_refused_b(self, error=OSError(1, "EPERM_CONTEXT_ADMISSION")):
        with ContextAdmissionFailure(error):
            return self.refuse_b(self.real)

    def assert_zero_effect_closed(self, cause_phase, reason="PRE_EFFECT_ADMISSION_REFUSED"):
        p_j, p_p = phase(self.j), phase(self.j, store="progression")
        self.assertEqual(self.j.storage.records["000002.PHASE"],
                         self.j.progression.records["000002.PHASE"])     # mirrored
        self.assertEqual((p_j["phase"], p_j["authority"]),
                         ("CLOSED_ZERO_EFFECT", "LOWER_CONTROLLER_PRE_EFFECT"))
        self.assertEqual(p_j["cause"]["controller_phase"], cause_phase)
        flight_raw = self.j.storage.records["000002.IN_FLIGHT"]
        self.assertEqual(p_j["flight_sha256"], J.sha256(flight_raw))
        self.assertEqual(p_j["ticket_sha256"],
                         J.sha256(self.j.progression.records["000002.RESERVED"]))
        final = record(self.j, "000002.FINAL")
        self.assertEqual((final["status"], final["reason"]), ("STOP", reason))
        self.assertEqual(final["phase_sha256"],
                         J.sha256(self.j.storage.records["000002.PHASE"]))
        self.assertIsNone(record(self.j, "000002.CLEANUP"))
        self.assertEqual(p_p, p_j)
        return p_j

    def assert_never_refused(self, j=None, code="NO_ZERO_EFFECT_PHASE_EVIDENCE"):
        j = self.j if j is None else j
        before = records(j)
        with self.assertRaises(J.JournalRefused) as caught:
            W.rebuilt(j).reconcile(2, LABEL, never_evidence(j))
        self.assertIn(code, str(caught.exception))
        self.assertEqual(records(j), before)
        self.assertEqual(next_dispatch(j), (True, 0, 0))

    def reconcile_and_reopen(self):
        a_final = self.j.storage.records["000001.FINAL"]
        rebuilt = W.rebuilt(self.j)
        self.assertFalse(rebuilt.state()["ready"])                 # restart refuses
        self.assertEqual(next_dispatch(self.j), (True, 0, 0))
        good = never_evidence(rebuilt)
        rebuilt.reconcile(2, LABEL, good)                          # explicit act
        self.j.storage.records.update(rebuilt.storage.records)
        self.assertEqual(self.j.storage.records["000001.FINAL"], a_final)
        J.verify_committed_dispatch(W.rebuilt(self.j), self.ticket_a)   # A kept
        with self.assertRaises(J.JournalRefused):                   # B: no result
            J.verify_controller_acceptance(self.p.output("b"), self.j)
        return good


# 1 ---------------------------------------------------------------------------
class P1GenuinePreEffectAdmission(Base):
    def test_context_admission_adapter_positive(self):
        spawns = self.real.spawns
        stop = self.admission_refused_b()
        self.assertIn("run_context_admission", stop.detail)
        self.assertEqual(self.real.spawns, spawns)
        ph = self.assert_zero_effect_closed("PRE_EFFECT:RUN_CONTEXT")
        self.assertEqual(ph["cause"]["stop_id"], "SB_STOP_ACTIVATION")
        self.assertEqual(ph["cause"]["run_context_close"], "CLOSED")
        # coordinator's generic STOP did not clobber the controller's STOP
        # (FIX001: refused by the durable write guard before no-clobber).
        # NRP-2 FIX001 (F-05) re-specification: the guard refusal is still
        # what prevents the clobber, but because the durable FINAL is a valid
        # STOP of exactly this ticket it is reported as already durable, not
        # as a manufactured secondary FINAL write error.
        self.assertEqual(stop.cleanup["secondary_failures"], [])
        final = json.loads(self.j.storage.records["000002.FINAL"])
        self.assertEqual((final["status"], final["reason"]),
                         ("STOP", "PRE_EFFECT_ADMISSION_REFUSED"))
        good = self.reconcile_and_reopen()
        disp = good["disposition"]
        self.assertEqual((disp["observed_phase"], disp["observed_phase_sha256"],
                          disp["stop_reason"]),
                         ("CLOSED_ZERO_EFFECT", J.sha256(self.j.storage.records["000002.PHASE"]),
                          "PRE_EFFECT_ADMISSION_REFUSED"))
        for kind in ("ROOT_PROCESS", "KNOWN_DESCENDANTS", "CAPABILITY_CUSTODY"):
            self.assertNotIn("identity", good["obligations"][kind])
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))     # explicit next

    def test_output_freshness_inside_controller_positive(self):
        def stale_raw(repo, rt, rp, dp, request, qp, op, lp, bp, **k):
            C.raw_worker_output_path(Path(op), LABEL).write_text("{}")   # appears late
            return self.real(repo, rt, rp, dp, request, qp, op, lp, bp, **k)
        spawns = self.real.spawns
        stop = self.refuse_b(stale_raw)
        self.assertIn("output_paths_not_fresh", stop.detail)
        self.assertEqual(self.real.spawns, spawns)
        self.assert_zero_effect_closed("PRE_EFFECT:OUTPUT_AND_COMMAND")
        self.reconcile_and_reopen()
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))

    def test_ticket_check_refusal_positive_is_the_same_protocol(self):
        def mutate(repo, rt, rp, dp, request, *rest, **kw):
            return self.real(repo, rt, rp, dp, dict(
                request, timeout_seconds=request["timeout_seconds"] + 1), *rest, **kw)
        self.refuse_b(mutate)
        self.assert_zero_effect_closed("PRE_EFFECT:TICKET_CHECK",
                                       "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
        self.reconcile_and_reopen()

    def test_single_request_entry(self):
        # (a) admission before the caller reservation: zero writes, READY
        run = T.Launch(*T.world(descendant=False)[:2])
        V.finish(run)
        with V.valid_worker([]):
            self.assertIsNone(run.run())                            # A accepted
        j = run.journal
        before = records(j)
        run2 = T.Launch(*T.world(descendant=False)[:2], journal=j)
        with ContextAdmissionFailure(OSError(1, "EPERM")):
            self.assertEqual(run2.run().stop_id, "SB_STOP_ACTIVATION")
        self.assertEqual((records(j), run2.popen_calls), (before, 0))
        self.assertTrue(W.rebuilt(j).state()["ready"])
        # (b) after the caller reservation: transient handoff write failure
        original, calls = j.progression.create_new, []

        def once(name, data):
            if name == "000002.PHASE" and not calls:
                calls.append(name)
                raise OSError(5, "EIO_HANDOFF")
            return original(name, data)
        j.progression.create_new = once
        run3 = T.Launch(*T.world(descendant=False)[:2], journal=j)
        stop = run3.run()
        self.assertEqual((stop.stop_id, run3.popen_calls), ("SB_STOP_DISPATCH_TICKET", 0))
        self.assertIn("effect_handoff", stop.detail)
        ph = phase(j)
        self.assertEqual((ph["phase"], ph["cause"]["controller_phase"]),
                         ("CLOSED_ZERO_EFFECT", "PRE_EFFECT:TICKET_CHECK"))
        rebuilt = W.rebuilt(j)
        self.assertFalse(rebuilt.state()["ready"])
        rebuilt.reconcile(2, "RUN-A", never_evidence(rebuilt, "RUN-A"))
        self.assertTrue(rebuilt.state()["ready"])
        env = J.verify_controller_acceptance(run.output_path, rebuilt)   # A kept
        self.assertEqual(env["seq"], 1)


# 2 ---------------------------------------------------------------------------
class P2DeniedWithoutControllerProof(Base):
    def test_generic_launcher_exception_before_controller(self):
        def boom(*a, **k):
            raise RuntimeError("GENERIC_BOOM")
        self.refuse_b(boom)
        self.assertIsNone(phase(self.j))
        self.assertEqual(record(self.j, "000002.FINAL")["reason"], "COORDINATOR_REFUSED")
        self.assert_never_refused()
        # resource-only facts (no disposition) and reaped assertions are no proof
        ev = never_evidence(self.j)
        ev.pop("disposition")
        with self.assertRaises(J.JournalRefused):
            W.rebuilt(self.j).reconcile(2, LABEL, ev)

    def test_same_generic_error_discriminated_by_phase(self):
        # pre-effect inside the controller: closed zero-effect
        self.admission_refused_b(RuntimeError("GENERIC_BOOM"))
        self.assertEqual(phase(self.j)["cause"]["failure_type"], "RuntimeError")
        self.reconcile_and_reopen()
        # identical error after the effect handoff (post-spawn, WATCHDOG)
        self.setUp()
        with mock.patch.object(C.CumulativeOutputCollector, "final",
                               side_effect=RuntimeError("GENERIC_BOOM")):
            self.refuse_b(self.real)
        self.assertEqual(phase(self.j)["phase"], "EFFECT_PERMITTED")
        self.assertEqual(self.real.spawns, 2)
        self.assert_never_refused()

    def test_forged_stale_foreign_wrong_bindings(self):
        self.admission_refused_b()
        good = never_evidence(self.j)
        d = good["disposition"]
        cases = {
            "wrong_phase_sha": dict(d, observed_phase_sha256="0" * 64),
            "wrong_cause": dict(d, phase_cause_sha256="1" * 64),
            "claims_effect_phase": dict(d, observed_phase="EFFECT_PERMITTED"),
            "wrong_seq": dict(d, seq=1),
            "wrong_scope": dict(d, scope_id="2" * 64),
            "wrong_request": dict(d, expected_request_sha256=request_sha(self.req_a)),
            "wrong_decision": dict(d, decision="RESAMPLE_AUTOMATICALLY"),
            "no_phase_fields": {k: v for k, v in d.items() if "phase" not in k},
        }
        for name, disp in cases.items():
            with self.subTest(name):
                with self.assertRaises(J.JournalRefused):
                    W.rebuilt(self.j).reconcile(2, LABEL, dict(good, disposition=disp))
        with self.subTest("fabricated_identity_over_zero_effect"):
            reaped = F2.reconciliation(self.j, LABEL)          # ROOT_REAPED... identities
            with self.assertRaises(J.JournalRefused) as caught:
                W.rebuilt(self.j).reconcile(2, LABEL, reaped)
            self.assertIn("CONTRADICTS_ZERO_EFFECT_CLOSURE", str(caught.exception))
        with self.subTest("foreign_scope_copy"):
            other = W.journal(dispatcher_owner="OTHER")
            self.assertEqual(W.rebuilt(self.j).state()["reason"],
                             "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
            forged = W.rebuilt(self.j)
            forged.storage.records["000002.PHASE"] = other._record(
                "PHASE", **{k: v for k, v in phase(self.j).items()
                            if k not in ("schema", "kind", "scope_id")})
            self.assertEqual(forged.state()["reason"], "RECORD_SCOPE_OR_SCHEMA_MISMATCH")
        with self.subTest("stale_phase_from_other_seq"):
            forged = W.rebuilt(self.j)
            ph = dict(phase(self.j), seq=1)
            forged.storage.records["000002.PHASE"] = self.j._record(
                "PHASE", **{k: v for k, v in ph.items() if k not in ("schema", "kind",
                                                                        "scope_id")})
            self.assertFalse(forged.state()["ready"])
        self.assertEqual(next_dispatch(self.j), (True, 0, 0))
        self.assertEqual(self.real.spawns, 1)

    def test_blanket_coordinator_refused_never_implies_zero_spawn(self):
        # a COORDINATOR_REFUSED STOP after a real spawn (prepared then boom)
        def after(*a, **k):
            self.real(*a, **k)
            raise RuntimeError("GENERIC_BOOM")
        self.refuse_b(after)
        self.assertEqual(record(self.j, "000002.FINAL")["reason"], "COORDINATOR_REFUSED")
        self.assertEqual(phase(self.j)["phase"], "EFFECT_PERMITTED")
        self.assert_never_refused()


# 3 ---------------------------------------------------------------------------
class P3RetainedAuthority(Base):
    def retained_launcher(self, holder):
        def launcher(*a, **k):
            holder.append(k["dispatch_ticket"])
            with ContextAdmissionFailure(OSError(1, "EPERM")):
                return self.real(*a, **k)
        return launcher

    def late_use(self, ticket, stem="late"):
        """Virtual late call of the REAL controller with a retained ticket."""
        spawns, before = self.real.spawns, records(self.j)
        with self.assertRaises(C.StopSignal) as caught:
            self.real(self.p.tmp, self.p.tmp / "runtime", self.p.tmp / "res.json",
                      self.p.tmp / "dur.json", self.req_b,
                      self.p.tmp / "req" / "b.request.json", self.p.output("b"),
                      self.p.tmp / "logs" / f"{stem}.txt", self.p.tmp / "branch.json",
                      dispatch_ticket=ticket)
        self.assertEqual(self.real.spawns, spawns)                   # no fake spawn
        for store in (0, 1):                                          # no clobber
            for name, data in before[store].items():
                self.assertEqual(records(self.j)[store][name], data)
        self.assertEqual({n for n in records(self.j)[0]} - set(before[0]), set())
        return caught.exception

    def test_after_closure_and_after_reconciliation(self):
        held = []
        self.refuse_b(self.retained_launcher(held))
        copy = J.DispatchTicket(self.j, held[0].binding)              # unclaimed copy
        stop = self.late_use(held[0])
        self.assertIn("ticket_already_executed", stop.detail)
        stop = self.late_use(copy)
        self.assertIn("effect_slot_occupied", stop.detail)
        self.reconcile_and_reopen()
        self.late_use(J.DispatchTicket(self.j, held[0].binding))
        # the explicit, separate next dispatch (seq 3) on the same stores
        self.p.call(self.keep, self.j, W.orch_request(5, self.p.tmp), stem="c")
        stop = self.late_use(J.DispatchTicket(W.rebuilt(self.j), held[0].binding))
        self.assertIn("EXTRA_DISPATCH_RESERVED", stop.detail)
        self.assertTrue(W.rebuilt(self.j).state()["ready"])

    def test_late_handoff_before_closure_blocks_certification(self):
        """Virtual interleaving: another holder passes the handoff first."""
        def launcher(*a, **k):
            other = J.DispatchTicket(self.j, k["dispatch_ticket"].binding)
            b = other.binding
            other.check_execution(run_id=b["run_id"], request_sha256=b["request_sha256"],
                                  raw_path=Path(b["raw_path"]), output_path=Path(b["output_path"]))
            with ContextAdmissionFailure(OSError(1, "EPERM")):
                return self.real(*a, **k)
        self.refuse_b(launcher)
        self.assertEqual(phase(self.j)["phase"], "EFFECT_PERMITTED")
        final = record(self.j, "000002.FINAL")
        self.assertEqual(final["reason"], "PRE_EFFECT_ADMISSION_REFUSED")
        self.assertNotIn("phase_sha256", final)                       # not certified
        self.assert_never_refused()

    def test_closure_write_failure_not_certified(self):
        self.j.progression.fail[("create", "000002.PHASE")] = OSError(28, "ENOSPC")
        held = []
        self.refuse_b(self.retained_launcher(held))
        self.j.progression.fail.clear()
        self.assertIsNone(phase(self.j, store="progression"))
        self.assertEqual(record(self.j, "000002.FINAL")["status"], "STOP")
        self.assert_never_refused()
        self.late_use(J.DispatchTicket(self.j, held[0].binding))      # FINAL blocks


# 4 ---------------------------------------------------------------------------
class P4CrashAndWriteFailure(Base):
    def cut(self, store, names, error):
        for name in ([names] if isinstance(names, str) else names):
            getattr(self.j, store).fail[("create", name)] = error
        return self

    def run_admission(self, expect_crash):
        with ContextAdmissionFailure(OSError(1, "EPERM")):
            if expect_crash:
                with self.assertRaises(J.CrashCut):
                    self.p.call(self.real, self.j, self.req_b, stem="b")
            else:
                self.refuse_b(self.real)
        self.j.storage.fail.clear()
        self.j.progression.fail.clear()

    def test_boundaries(self):
        cases = {
            # (store, name, error, crash?, expected rebuilt reason, never ok?)
            "crash_at_closure_slot": ("progression", "000002.PHASE",
                                      J.CrashCut("slot"), True,
                                      "PRIOR_DISPATCH_IN_FLIGHT", False),
            "crash_after_slot_before_mirror": ("storage", "000002.PHASE",
                                               J.CrashCut("mirror"), True,
                                               "PRIOR_DISPATCH_IN_FLIGHT", False),
            "mirror_write_failure": ("storage", "000002.PHASE", OSError(5, "EIO"),
                                     False, "PRIOR_DISPATCH_STOPPED_UNRECONCILED", False),
            "all_journal_writes_fail_from_slot": ("storage", ("000002.PHASE", "000002.FINAL"),
                                                  OSError(28, "ALL"), False,
                                                  "PRIOR_DISPATCH_IN_FLIGHT", False),
            "crash_at_stop_after_mirrored_slot": ("storage", "000002.FINAL",
                                                  J.CrashCut("stop"), True,
                                                  "PRIOR_DISPATCH_IN_FLIGHT", True),
            "all_final_writes_fail_after_mirrored_slot": (
                "storage", "000002.FINAL", OSError(28, "ALL_FINAL"), False,
                "PRIOR_DISPATCH_IN_FLIGHT", True),
        }
        for label, (store, name, error, crash, reason, never_ok) in cases.items():
            with self.subTest(label):
                self.setUp()
                spawns = self.real.spawns
                self.cut(store, name, error).run_admission(crash)
                self.assertEqual(self.real.spawns, spawns)
                state = W.rebuilt(self.j).state()
                self.assertEqual((state["ready"], state["reason"]), (False, reason))
                self.assertEqual(next_dispatch(self.j), (True, 0, 0))
                J.verify_committed_dispatch(W.rebuilt(self.j), self.ticket_a)
                if never_ok:        # the slot survived: truthful explicit reopen
                    self.reconcile_and_reopen()
                    self.assertEqual(next_dispatch(self.j), (False, 1, 1))
                else:
                    self.assert_never_refused()

    def test_handoff_write_failures_block_spawn(self):
        for store, error in (("progression", OSError(28, "ENOSPC")),
                             ("storage", OSError(28, "ALL_LATER"))):
            with self.subTest(store):
                self.setUp()
                fail_once(getattr(self.j, store), "000002.PHASE", error)
                spawns = self.real.spawns
                stop = self.refuse_b(self.real)
                self.assertIn("effect_handoff", stop.detail)
                self.assertEqual(self.real.spawns, spawns)
                if store == "storage":     # progression slot = EFFECT: never proven
                    self.assertEqual(phase(self.j, store="progression")["phase"],
                                     "EFFECT_PERMITTED")
                    self.assert_never_refused()
                else:                       # nothing handed off; closure won
                    self.assertEqual(phase(self.j)["phase"], "CLOSED_ZERO_EFFECT")
                    self.reconcile_and_reopen()


# 5 ---------------------------------------------------------------------------
class P5SuccessUnchanged(Base):
    def test_success_binds_effect_slot_and_lost_notification(self):
        with mock.patch.object(J, "verify_committed_dispatch",
                               side_effect=OSError(5, "RETURN_NOTIFICATION_LOST")):
            self.refuse_b(self.keep)
        final = record(self.j, "000002.FINAL")
        self.assertEqual((final["status"], final["commit"]), ("ACCEPTED", J.COMMIT_AUTHORITY))
        self.assertEqual(final["phase_sha256"], J.sha256(self.j.storage.records["000002.PHASE"]))
        self.assertEqual(phase(self.j)["phase"], "EFFECT_PERMITTED")
        spawns = self.real.spawns
        env = J.recover_committed_dispatch(W.rebuilt(self.j), 2,
                                           request_sha256=request_sha(self.req_b),
                                           output_path=self.p.output("b"))
        self.assertEqual((env["seq"], self.real.spawns), (2, spawns))
        with self.assertRaises(J.JournalRefused):
            J.recover_committed_dispatch(W.rebuilt(self.j), 2,
                                         request_sha256=request_sha(self.req_a),
                                         output_path=self.p.output("b"))
        with self.assertRaises(J.JournalRefused):               # ACCEPTED: nothing to do
            W.rebuilt(self.j).reconcile(2, LABEL, never_evidence(self.j))
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))

    def test_accepted_without_effect_slot_refuses(self):
        self.p.call(self.keep, self.j, self.req_b, stem="b")
        for store in ("storage", "progression"):
            with self.subTest(store):
                j = W.rebuilt(self.j)
                del getattr(j, store).records["000002.PHASE"]
                self.assertFalse(j.state()["ready"])
                with self.assertRaises(J.JournalRefused):
                    J.verify_controller_acceptance(self.p.output("b"), j)
                J.verify_committed_dispatch(j, self.ticket_a)           # A readable

    def test_coupled_ledger(self):
        out, stop, launcher = W.OrchestratorConsumerTests().run_protocol(
            ["ACCEPT", "ACCEPT"], W.journal())
        self.assertIsNone(stop)
        self.assertEqual(len(out["decision_input_ledger"]), 1)


# 6 ---------------------------------------------------------------------------
class P6PostEffectUnchanged(Base):
    def test_spawn_failure_is_uncertain_not_zero_effect(self):
        def popen_boom(*pa, **pk):     # the spawn call itself is uncertain
            raise OSError(11, "EAGAIN_AFTER_HANDOFF")

        def launcher(*a, **k):
            with mock.patch.object(T.Launch, "popen_factory", popen_boom):
                return self.real(*a, **k)
        self.refuse_b(launcher)
        final = record(self.j, "000002.FINAL")
        self.assertEqual(final["reason"], "SPAWN_FAILED")
        self.assertEqual(phase(self.j)["phase"], "EFFECT_PERMITTED")
        self.assert_never_refused()

    def test_timeout_keeps_single_deadline_and_effect_phase(self):
        k, root, _ = T.world()
        run = T.Launch(k, root)
        stop = run.run()
        self.assertEqual(stop.cleanup["primary_failure"]["type"], "TimeoutExpired")
        kinds = [e["kind"] for e in run.context.evidence]
        self.assertEqual(kinds.count("DEADLINE_START"), 1)
        ph = json.loads(run.journal.storage.records["000001.PHASE"])
        self.assertEqual(ph["phase"], "EFFECT_PERMITTED")
        with self.assertRaises(J.JournalRefused) as caught:
            W.rebuilt(run.journal).reconcile(1, "RUN-A", never_evidence(run.journal, "RUN-A"))
        self.assertIn("NO_ZERO_EFFECT_PHASE_EVIDENCE", str(caught.exception))
        fresh = T.Launch(*T.world(descendant=False)[:2], journal=W.rebuilt(run.journal),
                         run_id="AFTER")
        self.assertEqual((fresh.run().stop_id, fresh.popen_calls),
                         ("SB_STOP_DISPATCH_JOURNAL", 0))


# 7 ---------------------------------------------------------------------------
def fix005_module():
    path = Path(HERE) / "testsupport" / "fix005_journal" / "stage_b_dispatch_journal_fix005.py"
    spec = importlib.util.spec_from_file_location("stage_b_dispatch_journal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P7IntegrityAndMigration(Base):
    def test_fix005_era_v3_journal(self):
        """A genuine FIX005 journal (exact pinned pre-edit journal bytes):
        A ACCEPTED, B TICKET_BINDING_REFUSED_BEFORE_SPAWN without a slot."""
        old = fix005_module()
        self.assertEqual(J.sha256(Path(old.__file__).read_bytes()),
                         "67c30c731601ce6e7d74d0b2198f7b485b3af3b1230477bc6261338782010755")
        storage, progression = J.MemoryStorage(), J.MemoryStorage()
        oj = old.DispatchJournal(storage, progression=progression, **self.j.scope)
        oj.initialize_scope()

        def mutate(repo, rt, rp, dp, request, *rest, **kw):
            return self.real(repo, rt, rp, dp, dict(
                request, timeout_seconds=request["timeout_seconds"] + 1), *rest, **kw)
        p = Paths("old")
        with mock.patch.dict(sys.modules, {"stage_b_dispatch_journal": old}), \
                mock.patch.object(C, "journal_protocol", old):
            p.call(self.real, oj, self.req_a, stem="a")
            with self.assertRaises(C.StopSignal):
                p.call(mutate, oj, self.req_b, stem="b")
        self.assertNotIn("000002.PHASE", storage.records)
        self.assertEqual(json.loads(storage.records["000002.FINAL"])["reason"],
                         "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
        before = records(oj)
        nj = J.DispatchJournal(J.MemoryStorage(records=storage.records), **self.j.scope,
                               progression=J.MemoryStorage(records=progression.records))
        # historical acceptance preserved
        self.assertEqual(J.verify_controller_acceptance(p.output("a"), nj)["seq"], 1)
        self.assertEqual(nj.state()["reason"], "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        # no pretended no-spawn proof: the FIX005 label alone no longer suffices
        self.assertNotIn("observed_phase", nj.required_disposition(2))
        with self.assertRaises(J.JournalRefused) as caught:
            nj.reconcile(2, LABEL, never_evidence(nj))
        self.assertIn("NO_ZERO_EFFECT_PHASE_EVIDENCE", str(caught.exception))
        self.assertEqual(records(oj), before)
        self.assertEqual(next_dispatch(nj), (True, 0, 0))

    def test_single_store_phase_loss_or_change(self):
        self.admission_refused_b()
        variants = {
            "journal_phase_lost": ("storage", None, "FINAL_BINDING_MISMATCH"),
            "progression_phase_lost": ("progression", None, "PHASE_MIRROR_LOST"),
            "journal_phase_changed": ("storage", b"CAUSE", "PHASE_MIRROR_MISMATCH"),
        }
        for label, (store, change, code) in variants.items():
            with self.subTest(label):
                j = W.rebuilt(self.j)
                recs = getattr(j, store).records
                if change is None:
                    del recs["000002.PHASE"]
                else:
                    recs["000002.PHASE"] = edit_cause(recs["000002.PHASE"])
                state = j.state()
                self.assertFalse(state["ready"])
                self.assertEqual(state["reason"], code)
                with self.assertRaises(J.JournalRefused):
                    j.reconcile(2, LABEL, never_evidence(self.j))
                self.assertEqual(next_dispatch(j), (True, 0, 0))
        # consistent change in BOTH stores after the next dispatch: the STOP
        # (phase_sha256) and the next RESERVED's digest both bind the slot;
        # the STOP binding is checked first
        self.reconcile_and_reopen()
        self.assertEqual(next_dispatch(self.j)[0], False)
        j = W.rebuilt(self.j)
        self.p.call(self.keep, j, X.W.orch_request(5, self.p.tmp), stem="c")
        for store in ("storage", "progression"):
            recs = getattr(j, store).records
            recs["000002.PHASE"] = edit_cause(recs["000002.PHASE"])
        self.assertEqual(j.state()["reason"], "FINAL_BINDING_MISMATCH")

    def test_legacy_below_caller_still_refuses(self):
        X.M9HistoryAndReconciliation("test_legacy_below_caller_accepted_default_refuses") \
            .test_legacy_below_caller_accepted_default_refuses()


if __name__ == "__main__":
    unittest.main()
