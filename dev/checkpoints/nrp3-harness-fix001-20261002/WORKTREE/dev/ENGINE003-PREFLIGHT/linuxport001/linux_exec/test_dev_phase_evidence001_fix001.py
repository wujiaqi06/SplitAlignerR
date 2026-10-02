"""DEV_PHASE_EVIDENCE001_FIX001 pure-simulation regression (no native effects).

APHASE001-1: a retained/copied/reconstructed ticket (and the lower
controller's fallback STOP) must never write into terminal history: the
journal's durable mutation services (_guard_open_write) refuse any write to
a dispatch that is not the latest or already has FINAL/RECONCILED.

APHASE001-2: a genuine FIX005-era history (exact pinned FIX005 journal
bytes) with a lawfully reconciled B and an accepted C stays READABLE under
its declared historical contract (HISTORICAL_V3_CONTRACT), but confers no
current authority: new work, open_dispatch and new reconciliation refuse.

Same exact controller/orchestrator/journal and fake kernel, FakePopen and
MemoryStorage fixtures as test_dev_phase_evidence001.
"""
from __future__ import annotations

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

import test_dev007_fix002 as F2  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix005 as X  # noqa: E402
import test_dev_phase_evidence001 as P  # noqa: E402
from test_dev007_fix004 import Paths  # noqa: E402

C, J = P.C, P.J
LABEL = P.LABEL
records, record, next_dispatch = X.records, X.record, X.next_dispatch
FIX005_SHA = "67c30c731601ce6e7d74d0b2198f7b485b3af3b1230477bc6261338782010755"


def completion_for(ticket):
    """A cleanup record that passes the predicates (only the guard refuses)."""
    return {"run_id": ticket.run_id, "completion_resolved": True,
            "root_reaped": True, "pipe_eof": True, "context_closed": True,
            "unresolved_reasons": [], "sampler_stop": {"state": "STOPPED"},
            "descendant_resolution": {"resolved": True, "live": [], "uncertain": []},
            "whole_process_tree_quiescent": "NOT_CLAIMED",
            "dispatch_ticket": ticket.ticket_sha256}


# 1 ---------------------------------------------------------------------------
class Q1TerminalHistoryWriteGuard(P.Base):
    """Astra APHASE001-1: closure mirrored, B's FINAL initially unwritable."""

    def setUp(self):
        super().setUp()
        self.held = []

        def launcher(*a, **k):
            self.held.append(k["dispatch_ticket"])
            self.j.storage.fail[("create", "000002.FINAL")] = OSError(28, "FINAL_WRITE")
            with P.ContextAdmissionFailure(OSError(1, "EPERM")):
                return self.real(*a, **k)
        stop = self.refuse_b(launcher)
        self.j.storage.fail.clear()
        self.assertIn("JOURNAL_FINAL_STOP", str(stop.cleanup["secondary_failures"]))
        self.assertIsNone(record(self.j, "000002.FINAL"))
        self.assertEqual(self.j.storage.records["000002.PHASE"],
                         self.j.progression.records["000002.PHASE"])
        self.assertEqual(P.phase(self.j)["phase"], "CLOSED_ZERO_EFFECT")
        self.assertEqual(W.rebuilt(self.j).state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")

    def reconcile(self):
        rebuilt = W.rebuilt(self.j)
        rebuilt.reconcile(2, LABEL, P.never_evidence(rebuilt))       # explicit act
        self.j.storage.records.update(rebuilt.storage.records)
        self.assertIsNone(record(self.j, "000002.RECONCILED")["final_sha256"])
        self.assertTrue(W.rebuilt(self.j).state()["ready"])

    def unchanged(self, j, fn, code=("DISPATCH_HISTORY_CLOSED",)):
        before, spawns = records(j), self.real.spawns
        with self.assertRaises(J.JournalRefused) as caught:
            fn()
        self.assertIn(caught.exception.code, (code,) if isinstance(code, str) else code)
        self.assertEqual(records(j), before)                         # every byte
        self.assertEqual(self.real.spawns, spawns)
        return caught.exception

    def late_controller(self, ticket, stem):
        """Virtual late call of the REAL lower controller (its closure is
        refused, so it takes the fallback ticket.stop path)."""
        before, spawns = records(self.j), self.real.spawns
        with self.assertRaises(C.StopSignal) as caught:
            self.real(self.p.tmp, self.p.tmp / "runtime", self.p.tmp / "res.json",
                      self.p.tmp / "dur.json", self.req_b,
                      self.p.tmp / "req" / "b.request.json", self.p.output("b"),
                      self.p.tmp / "logs" / f"{stem}.txt", self.p.tmp / "branch.json",
                      dispatch_ticket=ticket)
        self.assertEqual(records(self.j), before)
        self.assertEqual(self.real.spawns, spawns)
        return caught.exception

    def direct_writes(self, j, binding):
        """Every ticket-side write service of a copied ticket bound to j."""
        t = J.DispatchTicket(j, binding)
        self.unchanged(j, lambda: t.stop("LATE", stopped_by="LATE"))
        self.unchanged(j, lambda: j.finish(t.seq, t.run_id, "STOP", reason="LATE"))
        self.unchanged(j, lambda: t.record_prepared(
            completion_for(t), Path(t.raw_path), b"{}", {"x": 1}, t.request_sha256))
        self.unchanged(j, lambda: j._commit_accepted(t, acceptance_sha256="0" * 64))
        self.unchanged(j, lambda: t._claim_slot("EFFECT_PERMITTED", authority="LATE"))
        self.unchanged(j, lambda: t.close_zero_effect({"late": True}),
                       ("ZERO_EFFECT_CLOSURE_REFUSED", "EXTRA_DISPATCH_RESERVED"))
        b = t.binding
        self.unchanged(j, lambda: J.DispatchTicket(j, b).check_execution(
            run_id=b["run_id"], request_sha256=b["request_sha256"],
            raw_path=Path(b["raw_path"]), output_path=Path(b["output_path"])),
            "TICKET_BINDING_REFUSED")

    def test_late_real_controller_after_reconciliation_before_and_after_c(self):
        self.reconcile()
        binding = self.held[0].binding
        for label, ticket in (("retained", self.held[0]),
                              ("copy", J.DispatchTicket(self.j, binding)),
                              ("reconstructed", J.DispatchTicket(W.rebuilt(self.j), binding))):
            with self.subTest(label):
                stop = self.late_controller(ticket, label)
                self.assertIn("SB_STOP_DISPATCH_TICKET", str(stop.stop_id))
                # fallback closure and STOP both refused by the durable guard
                self.assertIn("ZERO_EFFECT_CLOSURE:JournalRefused", stop.detail)
                self.assertIn("JOURNAL_FINAL_STOP:JournalRefused:DISPATCH_HISTORY_CLOSED",
                              stop.detail)
                self.assertIn("RECONCILED_present", stop.detail)
                self.assertTrue(W.rebuilt(self.j).state()["ready"])
        # the explicit next dispatch C (seq 3) is accepted on the same stores
        c = self.p.call(self.keep, self.j, W.orch_request(5, self.p.tmp), stem="c")
        self.assertTrue(c)
        c_env = J.verify_controller_acceptance(self.p.output("c"), W.rebuilt(self.j))
        self.assertEqual(c_env["seq"], 3)
        for label, ticket in (("retained_after_c", self.held[0]),
                              ("copy_after_c", J.DispatchTicket(W.rebuilt(self.j), binding))):
            with self.subTest(label):
                self.late_controller(ticket, label)
        rebuilt = W.rebuilt(self.j)
        self.assertEqual(rebuilt.state()["next_seq"], 4)
        self.assertEqual(J.verify_controller_acceptance(self.p.output("c"), rebuilt), c_env)
        J.verify_committed_dispatch(rebuilt, self.ticket_a)
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))

    def test_ticket_write_methods_refused_once_resolved(self):
        self.reconcile()
        binding = self.held[0].binding
        self.direct_writes(self.j, binding)                            # B reconciled
        self.direct_writes(W.rebuilt(self.j), binding)                 # after restart
        self.direct_writes(self.j, self.ticket_a.binding)              # A ACCEPTED
        self.p.call(self.keep, self.j, W.orch_request(5, self.p.tmp), stem="c")
        for b in (binding, self.ticket_a.binding):                     # not latest
            self.direct_writes(W.rebuilt(self.j), b)
        c_view = W.rebuilt(self.j).load_ticket(3)                      # read-only
        self.unchanged(self.j, lambda: c_view.stop("LATE"))
        self.unchanged(self.j, lambda: J.DispatchTicket(
            self.j, c_view.binding).stop("LATE"))                      # C ACCEPTED
        self.assertTrue(W.rebuilt(self.j).state()["ready"])

    def test_open_unresolved_dispatch_still_gets_stop(self):
        """Before reconciliation B is open (no FINAL): a late fallback STOP
        is still persisted (not hidden), refusal continues, and the explicit
        reconciliation then binds that FINAL."""
        spawns = self.real.spawns
        with self.assertRaises(C.StopSignal):
            self.real(self.p.tmp, self.p.tmp / "runtime", self.p.tmp / "res.json",
                      self.p.tmp / "dur.json", self.req_b,
                      self.p.tmp / "req" / "b.request.json", self.p.output("b"),
                      self.p.tmp / "logs" / "open.txt", self.p.tmp / "branch.json",
                      dispatch_ticket=J.DispatchTicket(self.j, self.held[0].binding))
        self.assertEqual(self.real.spawns, spawns)
        final = record(self.j, "000002.FINAL")
        self.assertEqual((final["status"], final["reason"]),
                         ("STOP", "TICKET_BINDING_REFUSED_BEFORE_SPAWN"))
        self.assertNotIn("phase_sha256", final)       # the late holder did not close
        self.assertEqual(W.rebuilt(self.j).state()["reason"],
                         "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        rebuilt = W.rebuilt(self.j)
        rebuilt.reconcile(2, LABEL, P.never_evidence(rebuilt))      # slot still decides
        self.assertTrue(rebuilt.state()["ready"])

    def test_reconcile_interleaved_inside_write_fails_closed(self):
        """Outside the single-dispatcher model: an injected storage callback
        performs the operator reconcile between the guard and the create.
        Not prevented, but it fails closed (no acceptance, no spawn)."""
        j = W.rebuilt(self.j)
        original = j.storage.create_new

        def create_new(name, data):
            if name == "000002.FINAL":
                j.reconcile(2, LABEL, P.never_evidence(j))
            return original(name, data)
        j.storage.create_new = create_new
        J.DispatchTicket(j, self.held[0].binding).stop("LATE_RACE")
        self.assertEqual(j.state(), {"ready": False, "reason": "RECONCILIATION_INVALID",
                                     "detail": "STALE_RECORD_BINDING"})
        self.assertEqual(next_dispatch(j), (True, 0, 0))


# 2 ---------------------------------------------------------------------------
class Q2HistoricalCompatibility(X.Base):
    """Astra APHASE001-2 on exact pinned FIX005 journal bytes."""

    def setUp(self):
        self.old = P.fix005_module()
        self.assertEqual(J.sha256(Path(self.old.__file__).read_bytes()), FIX005_SHA)
        self.real = W.HarnessLauncher(["ACCEPT"] * 8)
        self.p = Paths("hist")
        self.req = [W.orch_request(i, self.p.tmp) for i in range(4)]
        self.oj = self.old.DispatchJournal(
            J.MemoryStorage(), progression=J.MemoryStorage(), run_generation=1,
            input_identity="HIST", dispatcher_owner="O")
        self.oj.initialize_scope()

    def fix005(self):
        return mock.patch.dict(sys.modules, {"stage_b_dispatch_journal": self.old}), \
            mock.patch.object(C, "journal_protocol", self.old)

    def old_run(self, fn):
        a, b = self.fix005()
        with a, b:
            return fn()

    def mutate(self, *args, **kw):
        args = list(args)
        args[4] = dict(args[4], timeout_seconds=args[4]["timeout_seconds"] + 1)
        return self.real(*args, **kw)

    def build(self, evidence=None, with_c=True):
        """FIX005: A accepted, B wrong-request pre-spawn refusal, B lawfully
        reconciled under the original v3 model, C accepted."""
        def run():
            self.p.call(self.real, self.oj, self.req[0], stem="a")
            with self.assertRaises(C.StopSignal):
                self.p.call(self.mutate, self.oj, self.req[1], stem="b")
            self.oj.reconcile(2, LABEL, (evidence or P.never_evidence)(self.oj))
            if with_c:
                self.p.call(self.real, self.oj, self.req[2], stem="c")
                self.assertEqual(self.old.verify_controller_acceptance(
                    self.p.output("c"), self.oj)["seq"], 3)
        self.old_run(run)
        self.assertEqual(json.loads(self.oj.storage.records["000002.FINAL"])["reason"],
                         "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
        return self.new()

    def new(self):
        return J.DispatchJournal(J.MemoryStorage(records=self.oj.storage.records),
                                 progression=J.MemoryStorage(records=self.oj.progression.records),
                                 **self.oj.scope)

    def test_historical_valid_accepted_suffix_readable(self):
        nj = self.build()
        before = records(nj)
        self.assertEqual(J.verify_controller_acceptance(self.p.output("c"), nj)["seq"], 3)
        self.assertEqual(J.verify_controller_acceptance(self.p.output("a"), nj)["seq"], 1)
        entry = nj._reconstruct(historical=True)["history"][1]
        self.assertEqual((entry["status"], entry["authority"]),
                         ("RECONCILED", J.HISTORICAL_V3_CONTRACT))
        view = nj.load_ticket(3)                                       # read-only
        self.assertTrue(view.read_only)
        J.recover_committed_dispatch(nj, 3, request_sha256=view.request_sha256,
                                     output_path=self.p.output("c"))
        self.assertEqual(records(nj), before)                          # no upgrade
        self.assertNotIn("000002.PHASE", nj.storage.records)           # nothing fabricated

    def test_historical_only_confers_no_current_authority(self):
        nj = self.build()
        before = records(nj)
        state = nj.state()
        self.assertEqual((state["ready"], state["reason"]),
                         (False, "HISTORICAL_ONLY_RECONCILIATION"))
        self.assertEqual(state["detail"], {"seq": 2, "contract": J.HISTORICAL_V3_CONTRACT})
        for fn in (lambda: nj.open_dispatch(3), lambda: nj.required_disposition(3),
                   lambda: nj.reserve(LABEL, "1" * 64, "r", "o")):
            with self.assertRaises(J.JournalRefused) as caught:
                fn()
            self.assertEqual(caught.exception.code, "HISTORICAL_ONLY_RECONCILIATION")
        with self.assertRaises(J.JournalRefused) as caught:
            nj.reconcile(2, LABEL, P.never_evidence(nj))
        self.assertEqual(str(caught.exception),
                         "NOT_RECONCILABLE:HISTORICAL_ONLY_RECONCILIATION")
        self.assertEqual(records(nj), before)
        self.assertEqual(next_dispatch(nj), (True, 0, 0))              # no spawn
        # a (never lawfully creatable) later phase-protocol dispatch refuses
        # even in the history view; C before it stays readable
        with mock.patch.object(J.DispatchJournal, "_reconstruct", _forced):
            nj.reserve(LABEL, "2" * 64, "r4", "o4")
        with self.assertRaises(J.JournalRefused) as caught:
            nj._reconstruct(historical=True)
        self.assertEqual(caught.exception.detail,
                         {"seq": 2, "later_phase_dispatch": 4})
        self.assertEqual(J.verify_controller_acceptance(self.p.output("c"), nj)["seq"], 3)

    def test_corrupted_old_reconciliation_rejected(self):
        self.build(with_c=False)
        good = self.oj.storage.records["000002.RECONCILED"]
        tamper = {
            "decision": ("VOID_DISPATCH_NO_RESULT_NO_AUTO_RESAMPLE",
                         "RESAMPLE", "DISPOSITION_DECISION"),
            "seq_binding": ('"seq":2,"stop_reason"', '"seq":1,"stop_reason"',
                            "DISPOSITION_BINDING:seq"),
            "trust": ("OPERATOR_ASSERTED_MODELED_EVIDENCE", "NATIVE_VERIFIED",
                      "TRUST_LABEL"),
            "final_binding": (json.loads(good)["final_sha256"], "0" * 64,
                              "STALE_RECORD_BINDING"),
        }
        for label, (old, new, detail) in tamper.items():
            with self.subTest(label):
                nj = self.new()
                raw = good.replace(old.encode(), new.encode())
                self.assertNotEqual(raw, good)
                nj.storage.records["000002.RECONCILED"] = raw
                with self.assertRaises(J.JournalRefused) as caught:
                    nj._reconstruct(historical=True)
                self.assertEqual(str(caught.exception), "RECONCILIATION_INVALID:" + detail)
                self.assertFalse(nj.state()["ready"])

    def test_historical_contract_keeps_fix005_reason_rule(self):
        """FIX005 refused ROOT_NEVER_SPAWNED over a generic COORDINATOR_REFUSED
        STOP; forged-but-bound bytes of that kind stay refused."""
        def run():
            self.p.call(self.real, self.oj, self.req[0], stem="a")

            def boom(*a, **k):
                raise RuntimeError("GENERIC")
            with self.assertRaises(C.StopSignal):
                self.p.call(boom, self.oj, self.req[1], stem="b")
        self.old_run(run)
        self.assertEqual(json.loads(self.oj.storage.records["000002.FINAL"])["reason"],
                         "COORDINATOR_REFUSED")
        with self.assertRaises(self.old.JournalRefused):
            self.oj.reconcile(2, LABEL, P.never_evidence(self.oj))     # FIX005 itself
        nj = self.new()
        entry = nj._reconstruct(upto=2, open_last=True, historical=True)["history"][-1]
        forged = dict(P.never_evidence(nj), seq=2, original_run_id=LABEL,
                      reservation_sha256=entry["reservation_sha256"],
                      flight_sha256=entry["sha"]["IN_FLIGHT"],
                      final_sha256=entry["sha"]["FINAL"])
        nj.storage.records["000002.RECONCILED"] = nj._record("RECONCILED", **forged)
        with self.assertRaises(J.JournalRefused) as caught:
            nj._reconstruct(historical=True)
        self.assertEqual(str(caught.exception),
                         "RECONCILIATION_INVALID:CONTRADICTS_RECORDED_SPAWN")

    def test_phase_protocol_never_falls_back_and_legacy_below_caller_refuses(self):
        # a phase-protocol B with EFFECT_PERMITTED (post-spawn failure) and
        # forged, correctly bound never-facts: no historical fallback
        j, p, real = W.journal(), Paths("phase"), W.HarnessLauncher(["ACCEPT"] * 4)
        p.call(real, j, W.orch_request(0, p.tmp), stem="a")
        with mock.patch.object(C.CumulativeOutputCollector, "final",
                               side_effect=RuntimeError("POST")):
            with self.assertRaises(C.StopSignal):
                p.call(real, j, W.orch_request(1, p.tmp), stem="b")
        self.assertEqual(P.phase(j)["phase"], "EFFECT_PERMITTED")
        entry = j._reconstruct(upto=2, open_last=True)["history"][-1]
        forged = dict(P.never_evidence(j), seq=2, original_run_id=LABEL,
                      reservation_sha256=entry["reservation_sha256"],
                      flight_sha256=entry["sha"]["IN_FLIGHT"],
                      final_sha256=entry["sha"]["FINAL"])
        j.storage.records["000002.RECONCILED"] = j._record("RECONCILED", **forged)
        for historical in (False, True):
            with self.assertRaises(J.JournalRefused) as caught:
                j._reconstruct(historical=historical)
            self.assertEqual(str(caught.exception),
                             "RECONCILIATION_INVALID:NO_ZERO_EFFECT_PHASE_EVIDENCE")
        X.M9HistoryAndReconciliation("test_legacy_below_caller_accepted_default_refuses") \
            .test_legacy_below_caller_accepted_default_refuses()

    def test_new_current_no_evidence_refusal_and_mixed_history(self):
        # FIX005 B refused, NOT yet reconciled: a new reconciliation is judged
        # by the current rules only (no phase proof -> refused)
        def run():
            self.p.call(self.real, self.oj, self.req[0], stem="a")
            with self.assertRaises(C.StopSignal):
                self.p.call(self.mutate, self.oj, self.req[1], stem="b")
        self.old_run(run)
        nj = self.new()
        before = records(nj)
        with self.assertRaises(J.JournalRefused) as caught:
            nj.reconcile(2, LABEL, P.never_evidence(nj))
        self.assertEqual(str(caught.exception),
                         "RECONCILIATION_INVALID:NO_ZERO_EFFECT_PHASE_EVIDENCE")
        self.assertEqual(records(nj), before)
        self.assertEqual(next_dispatch(nj), (True, 0, 0))
        # NRP-2 FIX001 re-specification (Astra recorded-identity decision;
        # same rule as test_nrp2 E7): B is pre-identity-protocol history with
        # no controller-recorded root token, so a NEW identity-bearing
        # reconciliation is refused too (formerly accepted here); nothing is
        # written and the scope stays closed.
        with self.assertRaises(J.JournalRefused) as caught:
            nj.reconcile(2, LABEL, F2.reconciliation(nj, LABEL))
        self.assertEqual(str(caught.exception),
                         "RECONCILIATION_INVALID:ROOT_PROCESS:"
                         "NO_RECORDED_IDENTITY:PRE_IDENTITY_PROTOCOL")
        self.assertEqual(records(nj), before)
        self.assertEqual(next_dispatch(nj), (True, 0, 0))
        # Historical records keep their readable status: B lawfully reconciled
        # by the FIX005 code under its own rule (read-only history, never
        # upgraded) -> the mixed history continues with genuine phase-protocol
        # dispatches (the original non-identity assertions, unchanged).
        self.old_run(lambda: self.oj.reconcile(2, LABEL, F2.reconciliation(self.oj, LABEL)))
        nj = self.new()
        self.assertTrue(nj.state()["ready"])
        self.p.call(self.real, nj, self.req[3], stem="d")
        rebuilt = self.new_from(nj)
        entry = rebuilt._reconstruct()["history"]
        self.assertEqual([e.get("authority") for e in entry], [None, "CURRENT", None])
        self.assertEqual(entry[2]["reservation"]["phase_protocol"], J.PHASE_PROTOCOL)
        self.assertEqual(J.verify_controller_acceptance(self.p.output("d"), rebuilt)["seq"], 3)
        self.assertEqual(J.verify_controller_acceptance(self.p.output("a"), rebuilt)["seq"], 1)

    def new_from(self, j):
        return J.DispatchJournal(J.MemoryStorage(records=j.storage.records),
                                 progression=J.MemoryStorage(records=j.progression.records),
                                 **j.scope)


_ORIGINAL_RECONSTRUCT = J.DispatchJournal._reconstruct


def _forced(self, *a, **k):
    """Test-only forgery aid: reserve a phase dispatch past a HISTORICAL_ONLY
    entry (the production reserve() refuses exactly this)."""
    k["historical"] = True
    return _ORIGINAL_RECONSTRUCT(self, *a, **k)


if __name__ == "__main__":
    unittest.main()
