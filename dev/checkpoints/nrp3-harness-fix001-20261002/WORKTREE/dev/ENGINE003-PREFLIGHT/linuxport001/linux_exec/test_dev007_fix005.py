"""DEV007_FIX005 pure-simulation matrix (no native effects).

PRO-DEV007-FIX004-01: final acceptance was committed below the caller
before current-request binding was verified.  FIX005 moves the transaction
boundary: the coordinator durably reserves the caller's request (ticket)
before any launcher gets authority, the lower layer only prepares evidence,
and the unique commit service writes FINAL ACCEPTED after verification.

Every case checks the current decision, the durable records and bindings,
raw/cleanup preservation, the permission of a RECONSTRUCTED journal
(W.rebuilt: same stores, nothing in memory) and the next fake spawn count.
Launches run the exact stage_b_controller.launch_request over the fake
kernel / FakePopen / MemoryStorage fixtures (test_dev006, test_dev007_fix003
HarnessLauncher).  Mutating launchers are injected contract counterexamples,
not claims about the default launcher or formal Stage B.  The two-store
independence is the module's stated model assumption, not physical proof;
an exact simultaneous rollback of all evidence stays excluded.
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

import test_dev006 as T  # noqa: E402
import test_dev007_fix001 as V  # noqa: E402
import test_dev007_fix002 as F2  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402
from test_dev007_fix004 import Paths, Recording, request_sha  # noqa: E402

C = T.C
J = C.journal_protocol
LABEL = "STAGEB_REQUEST"


def records(j):
    return dict(j.storage.records), dict(j.progression.records)


def record(j, name):
    raw = j.storage.records.get(name)
    return None if raw is None else json.loads(raw)


def next_dispatch(j):
    """A NEW controller process on the same durable stores tries a fresh,
    legitimate request: (refused, launcher calls, fake spawns)."""
    p = Paths("next")
    launcher = W.HarnessLauncher(["ACCEPT"])
    try:
        p.call(launcher, W.rebuilt(j), W.orch_request(9, p.tmp), stem="next")
        refused = False
    except C.StopSignal:
        refused = True
    return refused, launcher.calls, launcher.spawns


class Base(unittest.TestCase):
    def setUp(self):
        self.j = W.journal()
        self.p = Paths("a")
        self.req_a = W.orch_request(0, self.p.tmp)
        self.req_b = W.orch_request(1, self.p.tmp)
        self.prepared = []
        self.real = W.HarnessLauncher(["ACCEPT"] * 8)

        def keep(*a, **k):
            out = self.real(*a, **k)
            self.prepared.append(out)
            return out
        self.keep = keep
        self.result_a = self.p.call(keep, self.j, self.req_a, stem="a")
        self.ticket_a = self.j.load_ticket(1)

    def assert_durably_refused(self, j, seq=2, final_status=None):
        state = W.rebuilt(j).state()
        self.assertFalse(state["ready"])
        final = record(j, f"{seq:06d}.FINAL")
        if final_status is None:
            self.assertIsNone(final)
        else:
            self.assertEqual(final["status"], final_status)
        self.assertEqual(next_dispatch(j), (True, 0, 0))
        return state

    def refused(self, launcher, request, stem="b", output=None):
        with self.assertRaises(C.StopSignal) as caught:
            self.p.call(launcher, self.j, request, stem=stem, output=output)
        stop = caught.exception
        self.assertEqual(stop.stop_id, "SB_STOP_GLOBAL")
        self.assertIn("later_launches=0", stop.detail)
        return stop


# 1 ---------------------------------------------------------------------------
class M1SameRunIdSequentialSuccess(Base):
    def test_fresh_a_then_b_same_label_distinct_tickets(self):
        result_b = self.p.call(self.keep, self.j, self.req_b, stem="b")
        self.assertEqual(result_b["measured_repetition"], 1)
        state = W.rebuilt(self.j).state()
        self.assertEqual((state["ready"], state["next_seq"]), (True, 3))
        self.assertEqual([h["status"] for h in state["history"]], ["ACCEPTED"] * 2)
        f1, f2 = record(self.j, "000001.FINAL"), record(self.j, "000002.FINAL")
        self.assertEqual({f1["commit"], f2["commit"]}, {J.COMMIT_AUTHORITY})
        self.assertNotEqual(f1["ticket_sha256"], f2["ticket_sha256"])
        for seq, req, stem in ((1, self.req_a, "a"), (2, self.req_b, "b")):
            flight = record(self.j, f"{seq:06d}.IN_FLIGHT")
            self.assertEqual((flight["run_id"], flight["protocol"]),
                             (LABEL, J.DISPATCH_PROTOCOL))
            self.assertEqual(flight["request_sha256"], request_sha(req))
            env = J.recover_committed_dispatch(self.j, seq, request_sha256=request_sha(req),
                                               output_path=self.p.output(stem))
            self.assertEqual(env["seq"], seq)
        # the lower layer only prepared; the coordinator committed afterwards
        self.assertEqual(self.prepared[1]["status"], "PREPARED_NOT_ACCEPTED")
        steps = f2["completed_steps"]
        self.assertEqual(steps[-3:], ["JOURNAL_CLEANUP_RECORD_PUBLISHED",
                                      "COORDINATOR_CURRENT_BINDING_VERIFIED",
                                      "ACCEPTANCE_ENVELOPE_PUBLISHED"])
        self.assertEqual(self.real.spawns, 2)

    def test_coupled_protocol_ledger(self):
        out, stop, launcher = W.OrchestratorConsumerTests().run_protocol(
            ["ACCEPT", "ACCEPT"], W.journal())
        self.assertIsNone(stop)
        self.assertEqual((launcher.calls, launcher.spawns), (2, 2))
        self.assertEqual(len(out["decision_input_ledger"]), 1)

    def test_single_request_cli_path_same_commit_service(self):
        run = T.Launch(*T.world(descendant=False)[:2])
        V.finish(run)
        with V.valid_worker([]), mock.patch.object(
                J, "commit_current_dispatch", wraps=J.commit_current_dispatch) as spy:
            self.assertIsNone(run.run())
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(record(run.journal, "000001.FINAL")["commit"], J.COMMIT_AUTHORITY)
        run2 = T.Launch(*T.world(descendant=False)[:2], journal=run.journal)
        V.finish(run2)
        with V.valid_worker([]):
            self.assertIsNone(run2.run())                  # same run id "RUN-A"
        self.assertEqual(W.rebuilt(run.journal).state()["next_seq"], 3)

    def test_finish_cannot_write_accepted(self):
        with self.assertRaises(ValueError):
            self.j.finish(1, LABEL, "ACCEPTED")


# 2 ---------------------------------------------------------------------------
class M2AdmissionBeforeReservation(Base):
    def test_existing_output_refused_zero_effects(self):
        before = records(self.j)
        launcher = Recording(self.real)
        stop = self.refused(launcher, self.req_b, output=self.p.output("a"))
        self.assertIn("CURRENT_OUTPUT_NOT_FRESH", stop.detail)
        self.assertEqual(launcher.calls, 0)
        self.assertEqual(records(self.j), before)          # no new dispatch
        self.assertTrue(W.rebuilt(self.j).state()["ready"])
        J.verify_committed_dispatch(self.j, self.ticket_a)  # A unmodified

    def test_invalid_digest_and_unpermitted_scope(self):
        with self.assertRaises(J.JournalRefused):
            J.reserve_current_dispatch(self.j, run_id=LABEL, request_sha256="x",
                                       raw_path=self.p.tmp / "r", output_path=self.p.tmp / "o")
        self.assertEqual(W.rebuilt(self.j).state()["next_seq"], 2)


# 3 ---------------------------------------------------------------------------
class M3WrongRequestAfterReservation(Base):
    def mutate(self, repo, rt, rp, dp, request, *rest, **kw):
        return self.real(repo, rt, rp, dp, dict(
            request, timeout_seconds=request["timeout_seconds"] + 1), *rest, **kw)

    def test_ticket_check_refuses_before_spawn(self):
        """Astra/Pro reproduction: R' instead of R on a new seq/path."""
        spawns = self.real.spawns
        stop = self.refused(self.mutate, self.req_b)
        self.assertIn("TICKET_BINDING_REFUSED", stop.detail)
        self.assertEqual(self.real.spawns, spawns)          # refused before spawn
        final = record(self.j, "000002.FINAL")
        self.assertEqual(final["reason"], "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
        self.assertEqual(final["binding_violation"]["expected"]["request_sha256"],
                         request_sha(self.req_b))
        self.assertIsNone(record(self.j, "000002.CLEANUP"))
        self.assertFalse(self.p.output("b").exists())
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_prepared_evidence_mismatch_when_earliest_check_bypassed(self):
        def no_check(ticket, **kw):
            # DEV_PHASE_EVIDENCE001: the bypass skips the binding checks but
            # still performs the durable effect handoff (without it the spawn
            # is unsanctioned and the CLEANUP refuses as RECORD_LOST earlier)
            ticket.claimed = True
            ticket._claim_slot("EFFECT_PERMITTED", authority="TEST_BYPASS")
            ticket.effect_permitted = True
        with mock.patch.object(J.DispatchTicket, "check_execution", no_check):
            stop = self.refused(self.mutate, self.req_b)
        self.assertIn("CURRENT_DISPATCH_MISMATCH", stop.detail)
        self.assertIn("request", stop.detail.split("CURRENT_DISPATCH_MISMATCH:")[1])
        cleanup = record(self.j, "000002.CLEANUP")         # R' was executed
        self.assertNotEqual(cleanup["executed_request_sha256"], request_sha(self.req_b))
        self.assertTrue(cleanup["completion"]["completion_resolved"])
        raw = Path(record(self.j, "000002.IN_FLIGHT")["raw_path"])
        self.assertEqual(J.sha256(raw.read_bytes()), cleanup["raw_worker_result_sha256"])
        final = record(self.j, "000002.FINAL")
        self.assertEqual((final["status"], final["reason"], final["stopped_by"]),
                         ("STOP", "CURRENT_BINDING_REFUSED", "COORDINATOR"))
        self.assertFalse(self.p.output("b").exists())      # no envelope, no ACCEPTED
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(self.p.output("b"), self.j)
        self.assert_durably_refused(self.j, final_status="STOP")


# 4 ---------------------------------------------------------------------------
class M4StaleForeignExtraWrong(Base):
    def test_stale_prepared_receipt_returned(self):
        def stale(*a, **k):
            self.real(*a, **k)                              # real seq-2 execution
            return self.prepared[0]                         # A's prepared evidence
        stop = self.refused(stale, self.req_b)
        for check in ("returned_ticket", "returned_receipt", "returned_cleanup"):
            self.assertIn(check, stop.detail)
        self.assertTrue(Path(record(self.j, "000002.IN_FLIGHT")["raw_path"]).exists())
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_old_seq_cleanup_cannot_bind_new_ticket(self):
        original = C._completion_cleanup

        def old_ticket_cleanup(*a, **k):
            return dict(original(*a, **k), dispatch_ticket=self.ticket_a.ticket_sha256)
        with mock.patch.object(C, "_completion_cleanup", old_ticket_cleanup):
            stop = self.refused(self.real, self.req_b)
        self.assertIn("SB_STOP_ACCEPTANCE_PUBLICATION", stop.detail)
        self.assertIsNone(record(self.j, "000002.CLEANUP"))
        self.assertEqual(record(self.j, "000002.FINAL")["reason"], "PREPARED_PUBLISH_FAILED")
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_stale_ticket_cannot_authorize(self):
        def old_ticket(*a, **k):
            k["dispatch_ticket"] = self.ticket_a
            return self.real(*a, **k)
        spawns = self.real.spawns
        stop = self.refused(old_ticket, self.req_b)
        self.assertIn("TICKET_BINDING_REFUSED", stop.detail)
        self.assertEqual(self.real.spawns, spawns)
        self.assertEqual(record(self.j, "000001.FINAL")["status"], "ACCEPTED")  # untouched
        self.assertEqual(record(self.j, "000002.FINAL")["reason"], "COORDINATOR_REFUSED")
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_extra_dispatch_reserved_by_lower_layer(self):
        def extra(*a, **k):
            out = self.real(*a, **k)
            j = self.j                                      # bypasses permission
            with mock.patch.object(j, "_reconstruct", lambda upto=None, open_last=False:
                                   J.DispatchJournal._reconstruct(j, upto=2, open_last=True)):
                j.reserve(LABEL, "e" * 64, "extra.raw", "extra.out")
            return out
        stop = self.refused(extra, self.req_b)
        self.assertIn("EXTRA_DISPATCH_RESERVED", stop.detail)
        self.assertIsNone(record(self.j, "000003.FINAL"))
        # DEV_PHASE_EVIDENCE001_FIX001: seq 3's prior_dispatch_digest already
        # binds seq 2, so no STOP is appended to it (write guard); the
        # non-terminal IN_FLIGHT stays and refuses.
        self.assertIn("DISPATCH_HISTORY_CLOSED", str(stop.cleanup["secondary_failures"]))
        self.assertIsNone(record(self.j, "000002.FINAL"))
        self.assertFalse(self.p.output("b").exists())
        self.assert_durably_refused(self.j, final_status=None)

    def test_extra_reservation_refused_while_ticket_open(self):
        seen = []

        def extra(*a, **k):
            try:
                self.j.reserve(LABEL, "e" * 64, "x.raw", "x.out")
            except J.JournalRefused as refused:
                seen.append(refused.code)
            return self.real(*a, **k)
        self.p.call(extra, self.j, self.req_b, stem="b")   # nothing extra happened
        self.assertEqual(seen, ["PRIOR_DISPATCH_IN_FLIGHT"])
        self.assertEqual(W.rebuilt(self.j).state()["next_seq"], 3)

    def test_wrong_scope(self):
        other = W.journal(dispatcher_owner="OTHER-DISPATCHER")

        def foreign(repo, rt, rp, dp, request, qp, op, lp, bp, **k):
            k["dispatch_ticket"] = J.reserve_current_dispatch(
                other, run_id=LABEL, request_sha256=request_sha(request),
                raw_path=C.raw_worker_output_path(Path(op), LABEL), output_path=op)
            return self.real(repo, rt, rp, dp, request, qp, op, lp, bp, **k)
        stop = self.refused(foreign, self.req_b)
        self.assertIn("returned_ticket", stop.detail)
        self.assertFalse(self.p.output("b").exists())
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_wrong_output_path(self):
        def elsewhere(repo, rt, rp, dp, request, qp, op, lp, bp, **k):
            return self.real(repo, rt, rp, dp, request, qp,
                             Path(op).with_name("elsewhere.result.json"), lp, bp, **k)
        spawns = self.real.spawns
        stop = self.refused(elsewhere, self.req_b)
        self.assertIn("output_path", stop.detail)
        self.assertEqual(self.real.spawns, spawns)
        self.assert_durably_refused(self.j, final_status="STOP")


# 5 ---------------------------------------------------------------------------
class M5PreparedThenFailure(Base):
    def run_then(self, action):
        def launcher(*a, **k):
            self.real(*a, **k)
            return action()
        return launcher

    def assert_prepared_kept(self):
        cleanup = record(self.j, "000002.CLEANUP")
        self.assertTrue(cleanup["completion"]["completion_resolved"])
        raw = Path(record(self.j, "000002.IN_FLIGHT")["raw_path"])
        self.assertEqual(J.sha256(raw.read_bytes()), cleanup["raw_worker_result_sha256"])

    def test_bad_return(self):
        self.refused(self.run_then(lambda: None), self.req_b)
        self.assert_prepared_kept()
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_exception(self):
        def boom():
            raise RuntimeError("LAUNCHER_RETURN_PATH")
        stop = self.refused(self.run_then(boom), self.req_b)
        self.assertEqual(stop.cleanup["primary"], "RuntimeError:LAUNCHER_RETURN_PATH")
        self.assert_prepared_kept()
        self.assertEqual(record(self.j, "000002.FINAL")["reason"], "COORDINATOR_REFUSED")
        self.assert_durably_refused(self.j, final_status="STOP")

    def test_simulated_crash_before_verification(self):
        def crash():
            raise J.CrashCut("PROCESS_DEATH_BEFORE_COORDINATOR_VERIFICATION")
        with self.assertRaises(J.CrashCut):
            self.p.call(self.run_then(crash), self.j, self.req_b, stem="b")
        self.assert_prepared_kept()
        state = self.assert_durably_refused(self.j, final_status=None)
        self.assertEqual(state["reason"], "PRIOR_DISPATCH_IN_FLIGHT")

    def test_keyboard_interrupt_before_verification(self):
        def interrupt():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.p.call(self.run_then(interrupt), self.j, self.req_b, stem="b")
        self.assert_prepared_kept()
        self.assert_durably_refused(self.j, final_status="STOP")


# 6 ---------------------------------------------------------------------------
class M6WriteFailures(Base):
    def test_reservation_write_failure_zero_effects(self):
        before = records(self.j)
        self.j.progression.fail[("create", "000002.RESERVED")] = OSError(28, "ENOSPC")
        launcher = Recording(self.real)
        stop = self.refused(launcher, self.req_b)
        self.assertIn("RESERVATION_PUBLISH_FAILED", stop.detail)
        self.assertEqual((launcher.calls, records(self.j)), (0, before))
        self.j.progression.fail.clear()
        self.assertTrue(W.rebuilt(self.j).state()["ready"])

    def test_in_flight_write_failure_refuses_without_launch(self):
        self.j.storage.fail[("create", "000002.IN_FLIGHT")] = OSError(28, "ENOSPC")
        launcher = Recording(self.real)
        self.refused(launcher, self.req_b)
        self.assertEqual(launcher.calls, 0)
        self.j.storage.fail.clear()
        state = self.assert_durably_refused(self.j)
        self.assertEqual(state["reason"], "RESERVED_DISPATCH_UNRESOLVED")

    def test_all_writes_fail_after_reservation(self):
        # DEV_PHASE_EVIDENCE001: "all later writes" now start after the
        # durable effect handoff (the slot is written before spawn); failure
        # from the handoff itself is test_dev_phase_evidence001 M4.
        # NRP-2: ... and after the post-spawn identity record (EFFECT); an
        # EFFECT write failure itself is test_nrp2 E5.
        original = J.DispatchTicket.record_effect_identity

        def effect_then_fail(ticket, evidence):
            sha = original(ticket, evidence)
            self.j.storage.fail[("create", "000002")] = OSError(28, "ALL_LATER_WRITES")
            return sha

        def launcher(*a, **k):
            with mock.patch.object(J.DispatchTicket, "record_effect_identity",
                                   effect_then_fail):
                return self.real(*a, **k)
        stop = self.refused(launcher, self.req_b)
        self.assertIn("SB_STOP_ACCEPTANCE_PUBLICATION", stop.detail)
        self.assertEqual(stop.cleanup["secondary_failures"][0].split(":")[0],
                         "JOURNAL_FINAL_STOP")
        self.assertEqual(sorted(n for n in self.j.storage.records if n.startswith("000002")),
                         ["000002.EFFECT", "000002.IN_FLIGHT", "000002.PHASE"])
        raw = Path(record(self.j, "000002.IN_FLIGHT")["raw_path"])
        self.assertEqual(json.loads(raw.read_text())["measured_repetition"], 1)  # raw kept
        self.j.storage.fail.clear()
        state = self.assert_durably_refused(self.j)
        self.assertEqual(state["reason"], "PRIOR_DISPATCH_IN_FLIGHT")

    def test_envelope_and_final_failures_do_not_commit(self):
        for target, attr, error in ((J, "publish_no_clobber", OSError(28, "ENVELOPE")),
                                    (J.DispatchJournal, "_commit_accepted",
                                     OSError(5, "FINAL"))):
            with self.subTest(attr):
                self.setUp()
                with mock.patch.object(target, attr, side_effect=error):
                    stop = self.refused(self.real, self.req_b)
                self.assertIn("COMMIT_PUBLISH_FAILED", stop.detail)
                self.assert_durably_refused(self.j, final_status="STOP")
                with self.assertRaises(J.JournalRefused):
                    J.verify_controller_acceptance(self.p.output("b"), self.j)


# 7 ---------------------------------------------------------------------------
class M7NotificationLoss(Base):
    def test_committed_then_return_lost(self):
        original = J.verify_committed_dispatch
        with mock.patch.object(J, "verify_committed_dispatch",
                               side_effect=OSError(5, "RETURN_NOTIFICATION_LOST")):
            stop = self.refused(self.keep, self.req_b)
        self.assertIn("RETURN_NOTIFICATION_LOST", stop.detail)
        # no relabel over FINAL (FIX001: refused by the write guard before
        # the no-clobber create)
        self.assertEqual(stop.cleanup["secondary_failures"][0].split(":")[1:3],
                         ["JournalRefused", "DISPATCH_HISTORY_CLOSED"])
        final = record(self.j, "000002.FINAL")
        self.assertEqual((final["status"], final["commit"]), ("ACCEPTED", J.COMMIT_AUTHORITY))
        calls, spawns = self.real.calls, self.real.spawns
        cleanups = [e["kind"] for e in self.real.runs[-1].context.evidence].count(
            "COMPLETION_CLEANUP")
        rebuilt = W.rebuilt(self.j)
        env = J.recover_committed_dispatch(rebuilt, 2, request_sha256=request_sha(self.req_b),
                                           output_path=self.p.output("b"))
        self.assertIs(original, J.verify_committed_dispatch)
        self.assertEqual(env["accepted_result"]["measured_repetition"], 1)
        self.assertEqual((self.real.calls, self.real.spawns), (calls, spawns))
        self.assertEqual(cleanups, 1)
        self.assertTrue(rebuilt.state()["ready"])
        with self.assertRaises(J.JournalRefused):           # another caller: refused
            J.recover_committed_dispatch(rebuilt, 2, request_sha256=request_sha(self.req_a),
                                         output_path=self.p.output("b"))
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))


# 8 ---------------------------------------------------------------------------
class M8TimeoutPlusEvidenceError(unittest.TestCase):
    def check(self, all_writes_fail):
        k, root, _ = T.world()
        run = T.Launch(k, root)
        if all_writes_fail:
            run.journal.storage.fail[("create", "000001.FINAL")] = OSError(28, "STOP_WRITE")
        with mock.patch.object(C, "_timeout_stop_evidence",
                               side_effect=OSError(28, "SECONDARY_TIMEOUT_RECORD_WRITE")):
            stop = run.run()
        rec = stop.cleanup
        self.assertEqual(rec["primary_failure"]["type"], "TimeoutExpired")
        self.assertEqual(rec["original_failure"], rec["primary_failure"]["label"])
        self.assertTrue(any("SECONDARY_TIMEOUT_RECORD_WRITE" in x["error"]
                            for x in rec["secondary_failures"]))
        kinds = [e["kind"] for e in run.context.evidence]
        self.assertEqual([e for e in run.context.evidence if e["kind"] == "DEADLINE_START"][0]
                         ["label"], "TIMEOUT")
        self.assertEqual(kinds.count("DEADLINE_START"), 1)
        self.assertNotIn("FAILURE_CLEANUP", kinds)
        run.journal.storage.fail.clear()
        state = W.rebuilt(run.journal).state()
        self.assertFalse(state["ready"])
        self.assertEqual(state["reason"], "PRIOR_DISPATCH_IN_FLIGHT" if all_writes_fail
                         else "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        fresh = T.Launch(*T.world(descendant=False)[:2], journal=W.rebuilt(run.journal),
                         run_id="AFTER-TIMEOUT")
        self.assertEqual(fresh.run().stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertEqual(fresh.popen_calls, 0)

    def test_timeout_evidence_error_durable_stop(self):
        self.check(False)

    def test_timeout_evidence_error_and_stop_write_failure(self):
        self.check(True)


# 9 ---------------------------------------------------------------------------
class M9HistoryAndReconciliation(Base):
    def setUp(self):
        super().setUp()

        def mutate(repo, rt, rp, dp, request, *rest, **kw):
            return self.real(repo, rt, rp, dp, dict(
                request, timeout_seconds=request["timeout_seconds"] + 1), *rest, **kw)
        self.refused(mutate, self.req_b)
        self.stop_bytes = self.j.storage.records["000002.FINAL"]

    def evidence(self, **override):
        return F2.reconciliation(self.j, LABEL, obligations={
            k: {"kind": v, "resolved": True, "run_id": LABEL} for k, v in {
                "ROOT_PROCESS": "ROOT_NEVER_SPAWNED",
                "KNOWN_DESCENDANTS": "NO_KNOWN_DESCENDANT",
                "CAPABILITY_CUSTODY": "NO_CAPABILITY_ACQUIRED",
                "OUTPUT_COLLECTOR": "COLLECTOR_NEVER_STARTED",
                "RSS_SAMPLER": "SAMPLER_NEVER_STARTED"}.items()}, **override)

    def test_a_readable_b_refuses_resource_only_inadequate_then_explicit(self):
        J.verify_committed_dispatch(self.j, self.ticket_a)          # A readable
        self.assertEqual(J.verify_controller_acceptance(self.p.output("a"), self.j)["seq"], 1)
        self.assertEqual(next_dispatch(self.j), (True, 0, 0))       # A never reopens B
        resource_only = self.evidence()
        resource_only.pop("disposition")
        bad = {"resource_only": resource_only}
        good = self.evidence()
        for field, value in (("decision", "RESAMPLE_AUTOMATICALLY"),
                             ("expected_request_sha256", request_sha(self.req_a)),
                             ("observed_binding_violation_sha256", None),
                             ("seq", 1)):
            bad[field] = dict(good, disposition=dict(good["disposition"], **{field: value}))
        for name, ev in bad.items():
            with self.subTest(name):
                with self.assertRaises(J.JournalRefused) as caught:
                    W.rebuilt(self.j).reconcile(2, LABEL, ev)
                self.assertEqual(caught.exception.code, "RECONCILIATION_INVALID")
                self.assertIn("DISPOSITION", str(caught.exception.detail))
                self.assertEqual(next_dispatch(self.j), (True, 0, 0))
        self.assertEqual(good["disposition"]["expected_request_sha256"],
                         request_sha(self.req_b))
        self.assertEqual(good["disposition"]["stop_reason"],
                         "TICKET_BINDING_REFUSED_BEFORE_SPAWN")
        self.j.reconcile(2, LABEL, good)                              # positive control
        self.assertEqual(self.j.storage.records["000002.FINAL"], self.stop_bytes)
        self.assertEqual(next_dispatch(self.j), (False, 1, 1))
        J.verify_committed_dispatch(self.j, self.ticket_a)
        with self.assertRaises(J.JournalRefused):                     # B: no result
            J.verify_controller_acceptance(self.p.output("b"), self.j)

    def test_legacy_below_caller_accepted_default_refuses(self):
        j = W.journal()
        fields = dict(seq=1, run_id="LEGACY", request_sha256="1" * 64,
                      raw_path="legacy.raw", output_path="legacy.out")
        genesis = j.progression.records["GENESIS"]
        res = j._record("RESERVED", prev_sha256=J.sha256(genesis),
                        prior_dispatch_digest=None, **fields)
        j.progression.create_new("000001.RESERVED", res)
        flight = j._record("IN_FLIGHT", reservation_sha256=J.sha256(res), **fields)
        j.storage.create_new("000001.IN_FLIGHT", flight)
        j.storage.create_new("000001.FINAL", j._record(
            "FINAL", seq=1, run_id="LEGACY", status="ACCEPTED",
            flight_sha256=J.sha256(flight), acceptance_sha256="a" * 64))
        before = records(j)
        state = W.rebuilt(j).state()
        self.assertEqual((state["ready"], state["reason"]),
                         (False, "LEGACY_PROTOCOL_DISPATCH"))
        self.assertEqual(state["detail"]["label"], J.LEGACY_LABEL)
        with self.assertRaises(J.JournalRefused) as caught:
            j.reconcile(1, "LEGACY", F2.reconciliation(j, "LEGACY"))
        self.assertEqual(caught.exception.code, "NOT_RECONCILABLE")
        with self.assertRaises(J.JournalRefused):
            j.initialize_scope()                                        # never silent
        self.assertEqual(records(j), before)
        self.assertEqual(next_dispatch(j), (True, 0, 0))


# 10 --------------------------------------------------------------------------
class M10SingleStoreLossAtNewBoundaries(Base):
    """Bounded two-store model: loss/rollback in ONE store at a time."""

    def boundary(self, name):
        if name == "caller_reservation":
            def launcher(*a, **k):
                raise J.CrashCut("AFTER_RESERVATION")
        elif name == "prepared_evidence":
            def launcher(*a, **k):
                self.real(*a, **k)
                raise J.CrashCut("AFTER_PREPARED")
        else:
            launcher = self.real
        if name == "pre_final_commit":
            with mock.patch.object(J.DispatchJournal, "_commit_accepted",
                                   side_effect=J.CrashCut("BEFORE_FINAL")):
                with self.assertRaises(J.CrashCut):
                    self.p.call(launcher, self.j, self.req_b, stem="b")
        elif name == "post_final_commit":
            self.p.call(launcher, self.j, self.req_b, stem="b")
        else:
            with self.assertRaises(J.CrashCut):
                self.p.call(launcher, self.j, self.req_b, stem="b")
        return records(self.j)

    def variants(self, jrec, prec):
        later = [f"000002.{k}" for k in ("IN_FLIGHT", "CLEANUP", "FINAL")
                 if f"000002.{k}" in jrec]             # protocol write order
        yield "journal_latest_record_lost", (
            {k: v for k, v in jrec.items() if k != later[-1]}, prec)
        yield "journal_rolled_back_before_dispatch", (
            {k: v for k, v in jrec.items() if k not in later}, prec)
        yield "progression_rolled_back", (
            jrec, {k: v for k, v in prec.items() if k != "000002.RESERVED"})
        corrupt = dict(jrec)
        corrupt[later[-1]] = jrec[later[-1]].replace(b'"seq":2', b'"seq":3')
        yield "journal_inconsistent_rewrite", (corrupt, prec)

    def test_each_boundary(self):
        # DEV_PHASE_EVIDENCE001: an executed dispatch also has its PHASE slot
        # NRP-2: ... and its post-spawn EFFECT identity record
        expected_kinds = {"caller_reservation": ["IN_FLIGHT"],
                          "prepared_evidence": ["CLEANUP", "EFFECT", "IN_FLIGHT", "PHASE"],
                          "pre_final_commit": ["CLEANUP", "EFFECT", "IN_FLIGHT", "PHASE"],
                          "post_final_commit": ["CLEANUP", "EFFECT", "FINAL", "IN_FLIGHT",
                                                "PHASE"]}
        for boundary, kinds in expected_kinds.items():
            self.setUp()
            jrec, prec = self.boundary(boundary)
            self.assertEqual(sorted(n[7:] for n in jrec if n.startswith("000002")), kinds)
            intact = J.DispatchJournal(J.MemoryStorage(records=jrec), **self.j.scope,
                                       progression=J.MemoryStorage(records=prec))
            self.assertEqual(intact.state()["ready"], boundary == "post_final_commit")
            if boundary == "pre_final_commit":                        # envelope w/o FINAL
                self.assertTrue(self.p.output("b").exists())
                with self.assertRaises(J.JournalRefused):
                    J.verify_controller_acceptance(self.p.output("b"), intact)
            for variant, (vj, vp) in self.variants(jrec, prec):
                with self.subTest(boundary=boundary, variant=variant):
                    j = J.DispatchJournal(J.MemoryStorage(records=vj), **self.j.scope,
                                          progression=J.MemoryStorage(records=vp))
                    self.assertFalse(j.state()["ready"])
                    self.assertEqual(next_dispatch(j), (True, 0, 0))
                    if variant == "progression_rolled_back":
                        # scope-wide integrity failure: every read refuses
                        with self.assertRaises(J.JournalRefused):
                            J.verify_committed_dispatch(j, self.ticket_a)
                    else:
                        J.verify_committed_dispatch(j, self.ticket_a)   # A readable


if __name__ == "__main__":
    unittest.main()
