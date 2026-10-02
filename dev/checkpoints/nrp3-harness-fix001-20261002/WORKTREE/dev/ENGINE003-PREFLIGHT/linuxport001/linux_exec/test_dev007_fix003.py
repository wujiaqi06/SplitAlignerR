"""DEV007_FIX003 pure-simulation regressions (no native effects).

F1  durable progression store / record-loss refusal        (A007F2-1)
F2  typed, obligation-complete reconciliation, read-time    (A007F2-2)
F3  persisted cleanup record + strict acceptance verifier    (A007F2-3)
F4  stage_b_orchestrator consumer wiring in a pure harness   (A007F2-4)

Every launch runs the exact stage_b_controller.launch_request with the
fake kernel / FakePopen / MemoryStorage fixtures of test_dev006; only the
scientific result helpers are stubbed (test_dev007_fix001.valid_worker).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import types
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

C = T.C
J = C.journal_protocol
STOP = V.STOP


def journal(storage=None, progression=None, init=True, **scope):
    kw = dict(run_generation=1, input_identity="TEST-INPUT",
              dispatcher_owner="TEST-DISPATCHER")
    kw.update(scope)
    j = J.DispatchJournal(storage if storage is not None else J.MemoryStorage(),
                          progression=(progression if progression is not None
                                       else J.MemoryStorage()), **kw)
    if init:
        j.initialize_scope()
    return j


def rebuilt(j, **scope):
    """A new controller process: same durable stores, nothing in memory."""
    return journal(J.MemoryStorage(records=j.storage.records),
                   J.MemoryStorage(records=j.progression.records), init=False,
                   **scope)


def accepted_launch(j, run_id, descendant=False):
    run = T.Launch(*T.world(descendant=False)[:2], journal=j, run_id=run_id)
    V.finish(run)
    with V.valid_worker([]):
        stop = run.run()
    assert stop is None, stop
    return run


def stopped_launch(j, run_id, modeled_identity=False):
    """modeled_identity (NRP-2 FIX001): the route records a MODELED_INJECTED
    root token in EFFECT, the positive fixture of the recorded-identity rule;
    False keeps the identity-less provider (no positive reconciliation)."""
    k, root, child = T.world(descendant=True)
    run = T.Launch(k, root, pipe_holders={root.pid}, journal=j, run_id=run_id,
                   route_factory=(F2.modeled_route_factory(k, run_id)
                                  if modeled_identity else None))
    run.desc = child
    V.finish(run)
    with V.valid_worker([]):
        stop = run.run()
    assert stop is not None and stop.stop_id == STOP
    return run


def assert_new_run_refused(case, j, run_id="RUN-NEW-ID"):
    """A new run id, owner-independent latch and output path cannot bypass."""
    run = T.Launch(*T.world(descendant=False)[:2], journal=j, run_id=run_id)
    V.finish(run)
    with V.valid_worker([]):
        stop = run.run()
    case.assertIsNotNone(stop)
    case.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
    case.assertEqual(run.popen_calls, 0)
    case.assertFalse(run.raw_path.exists())
    return stop


def rewrite(storage, name, j, **changes):
    """Replace a record with valid-JSON, same-schema, same-scope bytes."""
    value = json.loads(storage.records[name])
    value.update(changes)
    storage.records[name] = J.canonical(value)


# ---------------------------------------------------------------------------
# F1: durable progression / record-loss refusal
# ---------------------------------------------------------------------------
class ProgressionTests(unittest.TestCase):

    def test_astra_a007f2_1_tail_record_loss_refuses(self):
        j = journal()
        seq = j.begin("ORIGINAL", "0" * 64, "raw", "out")
        self.assertEqual(seq, 1)
        del j.storage.records["000001.IN_FLIGHT"]
        r = rebuilt(j)
        self.assertEqual(r.state()["reason"], "RESERVED_DISPATCH_UNRESOLVED")
        with self.assertRaises(J.JournalRefused):
            r.begin("NEW-RUN", "1" * 64, "newraw", "newout")
        assert_new_run_refused(self, r)

    def test_missing_latest_final_or_flight_after_accepted_prefix(self):
        for lose in (["000002.FINAL"], ["000002.CLEANUP"],
                     ["000002.IN_FLIGHT"],
                     ["000002.FINAL", "000002.CLEANUP", "000002.IN_FLIGHT"]):
            with self.subTest(lose=lose):
                j = journal()
                first = accepted_launch(j, "RUN-1")
                accepted_launch(j, "RUN-2")
                self.assertTrue(j.state()["ready"])
                for name in lose:
                    del j.storage.records[name]
                r = rebuilt(j)
                self.assertFalse(r.state()["ready"])
                assert_new_run_refused(self, r)
                # historical acceptance of the intact dispatch 1 is kept
                self.assertEqual(J.verify_controller_acceptance(
                    first.output_path, r)["run_id"], "RUN-1")

    def test_prior_accepted_prefix_then_unresolved_tail(self):
        j = journal()
        first = accepted_launch(j, "RUN-1")
        j.begin("RUN-2", "2" * 64, "raw2", "out2")         # crash after begin
        r = rebuilt(j)
        self.assertEqual(r.state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        assert_new_run_refused(self, r)
        J.verify_controller_acceptance(first.output_path, r)   # history intact
        del r.storage.records["000002.IN_FLIGHT"]              # tail record loss
        self.assertEqual(rebuilt(r).state()["reason"], "RESERVED_DISPATCH_UNRESOLVED")

    def test_first_dispatch_interrupted_begin_refuses(self):
        j = journal()
        j.storage.fail[("create", "000001.IN_FLIGHT")] = OSError(28, "ENOSPC")
        stop = assert_new_run_refused(self, j, "RUN-FIRST")
        self.assertIn("IN_FLIGHT_PUBLISH_FAILED", stop.detail)
        j.storage.fail.clear()
        self.assertEqual(rebuilt(j).state()["reason"], "RESERVED_DISPATCH_UNRESOLVED")
        assert_new_run_refused(self, rebuilt(j))

    def test_truncated_or_corrupt_progression_record(self):
        j = journal()
        j.progression.truncate["000001.RESERVED"] = 9
        assert_new_run_refused(self, j, "RUN-T")
        j.progression.truncate.clear()
        self.assertEqual(rebuilt(j).state()["reason"], "RECORD_CORRUPT")
        j2 = journal()
        accepted_launch(j2, "RUN-1")
        j2.progression.records["000001.RESERVED"] = b'{"schema":'
        self.assertEqual(rebuilt(j2).state()["reason"], "RECORD_CORRUPT")
        j3 = journal()
        accepted_launch(j3, "RUN-1")
        rewrite(j3.progression, "000001.RESERVED", j3, kind="IN_FLIGHT")
        self.assertEqual(rebuilt(j3).state()["reason"], "RECORD_KIND_MISMATCH")

    def test_lost_anchor_or_genesis_and_no_silent_reinit(self):
        for store, name, reason in (("storage", "ANCHOR", "ANCHOR_LOST_RECORDS_PRESENT"),
                                    ("progression", "GENESIS", "PROGRESSION_GENESIS_LOST")):
            with self.subTest(name=name):
                j = journal()
                accepted_launch(j, "RUN-1")
                del getattr(j, store).records[name]
                r = rebuilt(j)
                self.assertEqual(r.state()["reason"], reason)
                with self.assertRaises(J.JournalRefused):
                    r.initialize_scope()
                assert_new_run_refused(self, r)
        j = journal()                            # anchor lost before any dispatch
        del j.storage.records["ANCHOR"]
        self.assertEqual(rebuilt(j).state()["reason"], "ANCHOR_LOST_RECORDS_PRESENT")

    def test_history_rollback_or_rewrite_refuses(self):
        j = journal()
        accepted_launch(j, "RUN-1")
        accepted_launch(j, "RUN-2")
        cases = {
            "PROGRESSION_TAIL_ROLLBACK": ("progression", "000002.RESERVED", None,
                                          "PROGRESSION_ROLLBACK_JOURNAL_AHEAD"),
            "PROGRESSION_MIDDLE_LOSS": ("progression", "000001.RESERVED", None,
                                        "RESERVATION_LOST"),
            "EARLIER_FINAL_REWRITE": ("storage", "000001.FINAL",
                                      {"completed_steps": ["X"]},
                                      "HISTORY_ROLLBACK_OR_REWRITE"),
            "EARLIER_CLEANUP_REWRITE": ("storage", "000001.CLEANUP",
                                        {"validated_result_sha256": "0" * 64},
                                        "FINAL_BINDING_MISMATCH"),
        }
        for label, (store, name, change, reason) in cases.items():
            with self.subTest(case=label):
                r = rebuilt(j)
                if change is None:
                    del getattr(r, store).records[name]
                else:
                    rewrite(getattr(r, store), name, r, **change)
                self.assertEqual(r.state()["reason"], reason)
                assert_new_run_refused(self, r)

    def test_other_owner_or_generation_on_same_stores_refuses(self):
        j = journal()
        j.begin("ORIGINAL", "0" * 64, "raw", "out")
        for scope in ({"dispatcher_owner": "OTHER-OWNER"}, {"run_generation": 2},
                      {"input_identity": "OTHER-INPUT"}):
            with self.subTest(scope=scope):
                r = rebuilt(j, **scope)
                self.assertEqual(r.state()["reason"], "RECORD_SCOPE_OR_SCHEMA_MISMATCH")
                with self.assertRaises(J.JournalRefused):
                    r.initialize_scope()
                assert_new_run_refused(self, r)

    def test_progression_store_required(self):
        j = J.DispatchJournal(J.MemoryStorage(), run_generation=1,
                              input_identity="TEST-INPUT",
                              dispatcher_owner="TEST-DISPATCHER")
        with self.assertRaises(J.JournalRefused):
            j.initialize_scope()
        self.assertEqual(j.state()["reason"], "PROGRESSION_STORE_REQUIRED")
        assert_new_run_refused(self, j)

    def test_excluded_simultaneous_rollback_of_all_evidence_is_disclosed(self):
        """Model bound, asserted rather than hidden: an exact simultaneous
        rollback of BOTH independent stores to an earlier consistent cut is
        indistinguishable and reopens the scope.  Excluded by assumption."""
        j = journal()
        accepted_launch(j, "RUN-1")
        j.begin("RUN-2", "2" * 64, "raw2", "out2")
        del j.storage.records["000002.IN_FLIGHT"]
        del j.progression.records["000002.RESERVED"]
        self.assertTrue(rebuilt(j).state()["ready"])     # EXCLUDED_BY_MODEL
        self.assertIn("EXCLUDED", J.__doc__)

    def test_legitimate_reconciliation_of_interrupted_begin_reopens(self):
        j = journal()
        j.storage.fail[("create", "000001.IN_FLIGHT")] = OSError(5, "EIO")
        assert_new_run_refused(self, j, "RUN-X")
        j.storage.fail.clear()
        run_id = json.loads(j.progression.records["000001.RESERVED"])["run_id"]
        ev = F2.reconciliation(j, run_id)
        never = {"ROOT_PROCESS": "ROOT_NEVER_SPAWNED",
                 "KNOWN_DESCENDANTS": "NO_KNOWN_DESCENDANT",
                 "CAPABILITY_CUSTODY": "NO_CAPABILITY_ACQUIRED",
                 "OUTPUT_COLLECTOR": "COLLECTOR_NEVER_STARTED",
                 "RSS_SAMPLER": "SAMPLER_NEVER_STARTED"}
        ev["obligations"] = {k: {"kind": v, "resolved": True, "run_id": run_id}
                             for k, v in never.items()}
        j.reconcile(1, run_id, ev)
        state = rebuilt(j).state()
        self.assertTrue(state["ready"])
        self.assertEqual(state["next_seq"], 2)
        r = rebuilt(j)
        run = accepted_launch(r, "RUN-AFTER")
        self.assertEqual(J.verify_controller_acceptance(
            run.output_path, rebuilt(r))["seq"], 2)

    def test_crash_cut_at_every_durable_boundary(self):
        """Boundaries: GENESIS, ANCHOR, RESERVED (before publish), IN_FLIGHT
        (before publish), after IN_FLIGHT before spawn, CLEANUP, envelope,
        FINAL.  After each cut a rebuilt controller refuses with zero spawn
        (except before GENESIS: nothing exists and explicit init is allowed)."""
        # initialization cuts
        s, p = J.MemoryStorage(), J.MemoryStorage()
        p.fail[("create", "GENESIS")] = J.CrashCut("before GENESIS")
        with self.assertRaises(J.CrashCut):
            journal(s, p)
        p.fail.clear()
        self.assertEqual(journal(s, p, init=False).state()["reason"],
                         "SCOPE_NOT_INITIALIZED")
        journal(s, p)                                      # legitimate first init
        s, p = J.MemoryStorage(), J.MemoryStorage()
        s.fail[("create", "ANCHOR")] = J.CrashCut("after GENESIS")
        with self.assertRaises(J.CrashCut):
            journal(s, p)
        s.fail.clear()
        r = journal(s, p, init=False)
        self.assertEqual(r.state()["reason"], "ANCHOR_LOST_RECORDS_PRESENT")
        with self.assertRaises(J.JournalRefused):
            r.initialize_scope()
        # dispatch cuts
        cuts = {
            "BEFORE_RESERVED": ("progression", "000001.RESERVED", 0, "SCOPE_READY"),
            "BEFORE_IN_FLIGHT": ("storage", "000001.IN_FLIGHT", 0,
                                 "RESERVED_DISPATCH_UNRESOLVED"),
            "AFTER_IN_FLIGHT_BEFORE_SPAWN": ("popen", None, 1,
                                             "PRIOR_DISPATCH_IN_FLIGHT"),
            "BEFORE_CLEANUP": ("storage", "000001.CLEANUP", 1,
                               "PRIOR_DISPATCH_IN_FLIGHT"),
            "BEFORE_ENVELOPE": ("envelope", None, 1, "PRIOR_DISPATCH_IN_FLIGHT"),
            "BEFORE_FINAL": ("storage", "000001.FINAL", 1, "PRIOR_DISPATCH_IN_FLIGHT"),
        }
        for label, (where, name, spawns, expect) in cuts.items():
            with self.subTest(cut=label):
                j = journal()
                run = T.Launch(*T.world(descendant=False)[:2], journal=j,
                               run_id="RUN-CUT")
                V.finish(run)
                patches = []
                if where in ("progression", "storage"):
                    getattr(j, where).fail[("create", name)] = J.CrashCut(label)
                elif where == "popen":
                    def dying_popen(*a, **k):
                        run.popen_calls += 1           # counted as spawn attempt
                        j.storage.crash_after = j.storage.creates   # process dies
                        raise J.CrashCut(label)
                    run.popen_factory = dying_popen
                else:
                    patches.append(mock.patch.object(
                        J, "publish_no_clobber", side_effect=J.CrashCut(label)))
                with self.assertRaises(J.CrashCut), V.valid_worker([]):
                    for patch in patches:
                        patch.start()
                    try:
                        run.run()
                    finally:
                        for patch in patches:
                            patch.stop()
                self.assertEqual(run.popen_calls, spawns)
                r = rebuilt(j)
                state = r.state()
                if expect == "SCOPE_READY":            # nothing durable written
                    self.assertTrue(state["ready"])
                    self.assertEqual(state["next_seq"], 1)
                    continue
                self.assertEqual(state["reason"], expect)
                assert_new_run_refused(self, r)
                with self.assertRaises(J.JournalRefused):
                    J.verify_controller_acceptance(run.output_path, r)


# ---------------------------------------------------------------------------
# F2: reconciliation validation
# ---------------------------------------------------------------------------
class ReconciliationTests(unittest.TestCase):

    def stopped(self, modeled_identity=True):
        # NRP-2 FIX001: identity-bearing reconciliation must cite the recorded
        # root token, so the rule matrix below runs on a dispatch whose EFFECT
        # recorded a modeled token (F2.reconciliation cites it).  Otherwise
        # every invalid case would be refused by NO_RECORDED_IDENTITY first and
        # the specific FIX003 checks would no longer be exercised.
        j = journal()
        run = stopped_launch(j, "RUN-A", modeled_identity=modeled_identity)
        self.assertEqual(j.state()["reason"], "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        return j, run

    def test_astra_a007f2_2_explicit_unresolved_refused(self):
        j = journal()
        j.begin("ORIGINAL", "0" * 64, "raw", "out")
        with self.assertRaises(J.JournalRefused):
            j.reconcile(1, "ORIGINAL", {"cited_run_id": "ORIGINAL", "resolved_facts": [
                {"kind": "STILL_LIVE", "resolved": False}]})
        self.assertFalse(j.state()["ready"])
        with self.assertRaises(J.JournalRefused):
            j.reconcile(1, "ORIGINAL", F2.reconciliation(j, "ORIGINAL", obligations=dict(
                F2.reconciliation(j, "ORIGINAL")["obligations"],
                ROOT_PROCESS={"kind": "STILL_LIVE", "resolved": False,
                              "run_id": "ORIGINAL"})))
        self.assertFalse(j.state()["ready"])

    def test_invalid_reconciliation_matrix(self):
        good = lambda j: F2.reconciliation(j, "RUN-A")   # noqa: E731

        def ob(j, name, **fact):
            ev = good(j)
            ev["obligations"][name] = dict(ev["obligations"][name], **fact)
            return ev

        def drop(j, name):
            ev = good(j)
            del ev["obligations"][name]
            return ev
        cases = {
            "UNKNOWN_KIND": lambda j: ob(j, "ROOT_PROCESS", kind="MAYBE_GONE"),
            "NUMERIC_PID_ABSENT": lambda j: ob(j, "ROOT_PROCESS", kind="NUMERIC_PID_ABSENT"),
            "RESOLVED_FALSE": lambda j: ob(j, "RSS_SAMPLER", resolved=False),
            "RESOLVED_TRUTHY_STRING": lambda j: ob(j, "RSS_SAMPLER", resolved="yes"),
            "MIXED_VALID_AND_UNRESOLVED": lambda j: ob(j, "CAPABILITY_CUSTODY",
                                                       resolved=False),
            "MISSING_OBLIGATION": lambda j: drop(j, "KNOWN_DESCENDANTS"),
            "EXTRA_OBLIGATION": lambda j: dict(good(j), obligations=dict(
                good(j)["obligations"], OTHER={"kind": "X", "resolved": True,
                                               "run_id": "RUN-A"})),
            "FACT_WRONG_RUN": lambda j: ob(j, "ROOT_PROCESS", run_id="RUN-B"),
            "CITED_WRONG_RUN": lambda j: dict(good(j), cited_run_id="RUN-B"),
            "STALE_GENERATION": lambda j: dict(good(j), run_generation=0),
            "WRONG_OWNER": lambda j: dict(good(j), dispatcher_owner="OTHER"),
            "MISSING_IDENTITY": lambda j: ob(j, "ROOT_PROCESS", identity=""),
            "CONTRADICTORY": lambda j: ob(j, "ROOT_PROCESS", kind="ROOT_NEVER_SPAWNED"),
            "NEVER_SPAWNED_AFTER_SPAWN": lambda j: dict(good(j), obligations={
                "ROOT_PROCESS": {"kind": "ROOT_NEVER_SPAWNED", "resolved": True,
                                 "run_id": "RUN-A"},
                "KNOWN_DESCENDANTS": {"kind": "NO_KNOWN_DESCENDANT", "resolved": True,
                                      "run_id": "RUN-A"},
                **{k: v for k, v in good(j)["obligations"].items()
                   if k not in ("ROOT_PROCESS", "KNOWN_DESCENDANTS")}}),
            "NO_OPERATOR": lambda j: dict(good(j), operator=""),
            "TRUST_OVERCLAIM": lambda j: dict(good(j), trust="NATIVE_PROOF"),
            "EXTRA_FACT_FIELD": lambda j: ob(j, "ROOT_PROCESS", note="x"),
        }
        for label, make in cases.items():
            with self.subTest(case=label):
                j, _ = self.stopped()
                with self.assertRaises(J.JournalRefused) as caught:
                    j.reconcile(1, "RUN-A", make(j))
                self.assertEqual(caught.exception.code, "RECONCILIATION_INVALID")
                self.assertNotIn("000001.RECONCILED", j.storage.records)
                self.assertFalse(rebuilt(j).state()["ready"])
        j, _ = self.stopped()
        with self.assertRaises(J.JournalRefused):             # wrong original run
            j.reconcile(1, "RUN-B", F2.reconciliation(j, "RUN-B"))

    def test_read_time_validation_of_injected_records(self):
        """A RECONCILED record written around reconcile() is re-validated."""
        # NRP-2 FIX001: the recorded-identity rule also holds at read time:
        # a lawful RECONCILED whose identity facts are rewritten to a token
        # the controller did not record is refused on reconstruction.
        j, _ = self.stopped()
        good = F2.reconciliation(j, "RUN-A")
        j.reconcile(1, "RUN-A", good)
        self.assertTrue(rebuilt(j).state()["ready"])
        forged = json.loads(json.dumps(good["obligations"]))
        forged["ROOT_PROCESS"]["identity"] = "not-the-recorded-token"
        rewrite(j.storage, "000001.RECONCILED", j, obligations=forged)
        self.assertEqual(rebuilt(j).state()["reason"], "RECONCILIATION_INVALID")
        j, _ = self.stopped()
        bad = {"seq": 1, "original_run_id": "RUN-A", "cited_run_id": "RUN-A",
               "resolved_facts": [{"kind": "STILL_LIVE", "resolved": False}]}
        j.storage.records["000001.RECONCILED"] = j._record("RECONCILED", **bad)
        self.assertEqual(rebuilt(j).state()["reason"], "RECONCILIATION_INVALID")
        j, _ = self.stopped()
        j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
        self.assertTrue(rebuilt(j).state()["ready"])
        # stale binding: the record cites a FINAL that is later rewritten
        rewrite(j.storage, "000001.FINAL", j, reason="OTHER")
        self.assertEqual(rebuilt(j).state()["reason"], "RECONCILIATION_INVALID")
        j, _ = self.stopped()
        j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
        rewrite(j.storage, "000001.RECONCILED", j,
                obligations=dict(F2.reconciliation(j, "RUN-A")["obligations"],
                                 RSS_SAMPLER={"kind": "SAMPLER_STOPPED",
                                              "resolved": False, "run_id": "RUN-A"}))
        self.assertEqual(rebuilt(j).state()["reason"], "RECONCILIATION_INVALID")

    def test_not_reconcilable_states(self):
        j = journal()
        accepted_launch(j, "RUN-1")
        with self.assertRaises(J.JournalRefused) as caught:     # nothing open
            j.reconcile(1, "RUN-1", F2.reconciliation(j, "RUN-1"))
        self.assertEqual(caught.exception.code, "NOT_RECONCILABLE")
        j, _ = self.stopped()
        del j.storage.records["ANCHOR"]                        # integrity failure
        with self.assertRaises(J.JournalRefused) as caught:
            j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
        self.assertEqual(caught.exception.code, "NOT_RECONCILABLE")
        j = journal()
        accepted_launch(j, "RUN-1")
        stopped_launch(j, "RUN-2")
        with self.assertRaises(J.JournalRefused):              # wrong seq
            j.reconcile(1, "RUN-1", F2.reconciliation(j, "RUN-1"))

    def test_complete_reconciliation_control(self):
        # NRP-2 FIX001: identity-less provider -> the complete evidence is
        # refused (no recorded identity), nothing written, scope stays closed.
        j, _ = self.stopped(modeled_identity=False)
        before = dict(j.storage.records)
        with self.assertRaises(J.JournalRefused) as caught:
            j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
        self.assertIn("NO_RECORDED_IDENTITY", str(caught.exception))
        self.assertEqual(dict(j.storage.records), before)
        self.assertFalse(rebuilt(j).state()["ready"])
        # recorded modeled token: the original positive control, unchanged
        j, _ = self.stopped()
        j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
        r = rebuilt(j)
        self.assertEqual(r.state()["history"][0]["status"], "RECONCILED")
        run = accepted_launch(r, "RUN-NEXT")
        env = J.verify_controller_acceptance(run.output_path, rebuilt(r))
        self.assertEqual((env["seq"], env["run_id"]), (2, "RUN-NEXT"))


# ---------------------------------------------------------------------------
# F3: persisted cleanup evidence + strict acceptance verification
# ---------------------------------------------------------------------------
class AcceptanceVerificationTests(unittest.TestCase):

    def setUp(self):
        self.j = journal()
        self.run = accepted_launch(self.j, "RUN-OK")

    def verify(self, j=None):
        return J.verify_controller_acceptance(self.run.output_path,
                                              j if j is not None else rebuilt(self.j))

    def refused(self, mutate, code=None):
        r = rebuilt(self.j)
        mutate(r)
        with self.assertRaises(J.JournalRefused) as caught:
            self.verify(r)
        if code:
            self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_positive_control_and_persisted_cleanup(self):
        env = self.verify()
        self.assertEqual(env["status"], "CONTROLLER_ACCEPTED")
        cleanup = json.loads(self.j.storage.records["000001.CLEANUP"])
        self.assertEqual(cleanup["status"], "COMPLETION_RESOLVED_VALIDATED")
        self.assertTrue(cleanup["completion"]["completion_resolved"])
        self.assertEqual(env["completion_cleanup_sha256"],
                         J.sha256(self.j.storage.records["000001.CLEANUP"]))
        final = json.loads(self.j.storage.records["000001.FINAL"])
        self.assertEqual(final["cleanup_sha256"], env["completion_cleanup_sha256"])
        self.assertEqual(final["acceptance_sha256"],
                         J.sha256(self.run.output_path.read_bytes()))
        self.assertEqual(env["output_path"], str(self.run.output_path))

    def test_astra_a007f2_3_anchor_and_flight_removed(self):
        def mutate(r):
            del r.storage.records["ANCHOR"]
            del r.storage.records["000001.IN_FLIGHT"]
        self.refused(mutate, "ACCEPTANCE_NOT_JOURNALED")

    def test_removal_of_each_required_record(self):
        for store, name in (("storage", "ANCHOR"), ("progression", "GENESIS"),
                            ("progression", "000001.RESERVED"),
                            ("storage", "000001.IN_FLIGHT"),
                            ("storage", "000001.CLEANUP"),
                            ("storage", "000001.FINAL")):
            with self.subTest(name=name):
                self.refused(lambda r: getattr(r, store).records.pop(name),
                             "ACCEPTANCE_NOT_JOURNALED")

    def test_valid_json_wrong_semantics(self):
        cases = {
            "FLIGHT_WRONG_KIND": ("storage", "000001.IN_FLIGHT", {"kind": "FINAL"}),
            "FLIGHT_WRONG_SEQ": ("storage", "000001.IN_FLIGHT", {"seq": 2}),
            "FLIGHT_WRONG_RUN": ("storage", "000001.IN_FLIGHT", {"run_id": "OTHER"}),
            "FLIGHT_WRONG_OUTPUT": ("storage", "000001.IN_FLIGHT",
                                    {"output_path": "/elsewhere"}),
            "FINAL_STATUS_STOP": ("storage", "000001.FINAL", {"status": "STOP"}),
            "FINAL_UNKNOWN_STATUS": ("storage", "000001.FINAL", {"status": "OK"}),
            "FINAL_WRONG_RUN": ("storage", "000001.FINAL", {"run_id": "OTHER"}),
            "FINAL_BOOL_SEQ": ("storage", "000001.FINAL", {"seq": True}),
            "CLEANUP_UNRESOLVED": ("storage", "000001.CLEANUP", {"completion": dict(
                json.loads(self.j.storage.records["000001.CLEANUP"])["completion"],
                completion_resolved=False)}),
            "CLEANUP_LIVE_DESCENDANT": ("storage", "000001.CLEANUP", {"completion": dict(
                json.loads(self.j.storage.records["000001.CLEANUP"])["completion"],
                descendant_resolution={"resolved": True, "live": ["1"],
                                       "uncertain": []})}),
            "CLEANUP_STATUS": ("storage", "000001.CLEANUP", {"status": "MAYBE"}),
            "CLEANUP_HASH_MISMATCH": ("storage", "000001.CLEANUP",
                                      {"raw_worker_result_bytes": 1}),
            "RESERVED_WRONG_RUN": ("progression", "000001.RESERVED", {"run_id": "X"}),
            "ANCHOR_FOREIGN": ("storage", "ANCHOR", {"scope_id": "0" * 64}),
        }
        for label, (store, name, change) in cases.items():
            with self.subTest(case=label):
                self.refused(lambda r: rewrite(getattr(r, store), name, r, **change))

    def test_envelope_raw_and_path_tamper(self):
        env = json.loads(self.run.output_path.read_bytes())
        original = self.run.output_path.read_bytes()
        for label, change in (("RESULT", {"accepted_result": {"status": "PASS"}}),
                              ("RAW_SHA", {"raw_worker_result_sha256": "0" * 64}),
                              ("CLEANUP_SHA", {"completion_cleanup_sha256": "0" * 64}),
                              ("SEQ_STR", {"seq": "1"}), ("RESOLVED", {
                                  "completion_resolved": False})):
            with self.subTest(envelope=label):
                self.run.output_path.write_bytes(J.canonical(dict(env, **change)))
                with self.assertRaises(J.JournalRefused):
                    self.verify()
        self.run.output_path.write_bytes(original)
        self.verify()
        moved = self.run.output_path.with_name("copied.json")    # relocated
        moved.write_bytes(original)
        with self.assertRaises(J.JournalRefused) as caught:
            J.verify_controller_acceptance(moved, rebuilt(self.j))
        self.assertIn("output_path", caught.exception.detail)
        raw = self.run.raw_path.read_bytes()
        for label, data in (("TRUNCATED", raw[:-1]),
                            ("SAME_LENGTH", raw[:-2] + (b"x" if raw[-2:-1] != b"x"
                                                         else b"y") + raw[-1:])):
            with self.subTest(raw=label):
                self.run.raw_path.write_bytes(data)
                with self.assertRaises(J.JournalRefused) as caught:
                    self.verify()
                self.assertEqual(caught.exception.code, "RAW_WORKER_BYTES_MISMATCH")
        self.run.raw_path.unlink()
        with self.assertRaises(J.JournalRefused):
            self.verify()

    def test_historical_acceptance_vs_dispatch_permission(self):
        """Contract: later unresolved work does not invalidate the intact
        older result, and the older result never authorizes new work."""
        second = stopped_launch(self.j, "RUN-2")
        r = rebuilt(self.j)
        self.assertFalse(r.state()["ready"])
        self.assertEqual(self.verify(r)["run_id"], "RUN-OK")
        assert_new_run_refused(self, r)
        self.assertFalse(second.output_path.exists() and json.loads(
            second.output_path.read_bytes()).get("status") == "CONTROLLER_ACCEPTED")
        # but tampering inside the referenced prefix still refuses
        del r.storage.records["000001.CLEANUP"]
        with self.assertRaises(J.JournalRefused):
            self.verify(r)

    def test_two_accepted_dispatches_verify(self):
        second = accepted_launch(self.j, "RUN-OK2")
        r = rebuilt(self.j)
        self.assertEqual(self.verify(r)["seq"], 1)
        self.assertEqual(J.verify_controller_acceptance(second.output_path, r)["seq"], 2)


# ---------------------------------------------------------------------------
# F4: stage_b_orchestrator consumer in a pure harness
# ---------------------------------------------------------------------------
def orchestrator():
    import stage_b_orchestrator as O
    return O


IDENTITY = {"workload_id": "W", "candidate_id": "CAND", "selected_schedule_id": "S",
            "schedule_row_sha256": "0" * 64, "source_commit": "c", "source_tree": "t"}


def orch_request(index, tmp):
    return dict(IDENTITY, schema=C.LIVE_SCHEMA, execution_mode=C.BOUNDED_MODE,
                timeout_seconds=5, runtime_target=str(tmp / "runtime" / "target"),
                evidence_root=str(tmp / "evidence"), measured_repetition=index,
                schedule_position=index, fresh_resource_capture_sha256="c" * 64,
                fresh_available_memory_bytes=1, fresh_available_disk_bytes=1)


class HarnessLauncher:
    """Stands in for stage_b_controller.launch_request's CALLER-side fixtures
    only: it calls the exact launch_request with fake kernel/popen/sampler/
    authority stubs.  modes[i] selects the injected world of call i."""

    def __init__(self, modes):
        self.modes, self.calls, self.spawns = list(modes), 0, 0
        self.real_launch_request = C.launch_request    # before it is patched
        self.latch = C.DispatchLatch()
        self.runs = []

    def __call__(self, repo, runtime, resource_path, durability_path, request,
                 request_path, output_path, log_path, branch_resource_path,
                 dispatch_journal=None, dispatch_ticket=None):
        # FIX005: an outer coordinator hands only a ticket (run label bound)
        mode = self.modes[self.calls]
        self.calls += 1
        if mode == "RAW_PASS_ONLY":                 # legacy-style raw return
            result = dict(V.WORKER_RESULT, **{k: request[k] for k in
                                               ("measured_repetition",
                                                "schedule_position")}, **IDENTITY)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(json.dumps(result))
            return result
        k, root, child = T.world(descendant=(mode == "LIVE_DESCENDANT"))
        run = T.Launch(k, root, latch=self.latch, journal=dispatch_journal,
                       run_id=(dispatch_ticket.run_id if dispatch_ticket is not None
                               else f"ORCH-{self.calls}"),
                       pipe_holders={root.pid} if mode == "LIVE_DESCENDANT" else None)
        run.desc = child
        self.runs.append(run)
        result = dict(V.WORKER_RESULT, measured_repetition=request["measured_repetition"],
                      schedule_position=request["schedule_position"],
                      integer_metrics={"m": 1}, operation_integer_values={"o": 1},
                      **IDENTITY)

        def communicate(timeout=None):
            run.popen.calls.append(("communicate", timeout))
            C.raw_worker_output_path(Path(output_path), run.run_id).write_text(
                json.dumps(result))
            k.exit(root.pid, 0)
            run.popen.poll()
            run.popen.output = "out"
            return "out", None
        run.popen.communicate = communicate
        original = C._validate_completed_worker

        def validate(*a, **kw):
            with mock.patch.object(C, "strict_json_load", return_value=dict(result)), \
                    mock.patch.object(C, "validate_worker_result_identity",
                                      return_value=None), \
                    mock.patch.object(C, "evaluate_resource_hard_gate",
                                      return_value={"status": "PASS"}):
                return original(*a, **kw)

        def popen_factory(*a, **kw):
            self.spawns += 1
            return run.popen_factory(*a, **kw)
        for path in (request_path, output_path, log_path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(runtime).mkdir(parents=True, exist_ok=True)
        stubs = dict(
            load_exact_runtime_resource_capture=lambda path, digest: ({}, b"{}"),
            strict_json_load=lambda path: {}, ExecutionAuthority=lambda *a: None,
            FrozenAssets=lambda a: None,
            prelaunch_guard=lambda *a: {"worker_launch_authorized": True,
                                        "status": "PASS"})
        with mock.patch.multiple(C, **stubs), \
                mock.patch.object(C, "sys", T.SysAs("linux")), \
                mock.patch.object(C, "_validate_completed_worker", side_effect=validate):
            envelope = self.real_launch_request(
                repo, runtime, resource_path, durability_path, request, request_path,
                output_path, log_path, branch_resource_path,
                worker_command=["synthetic"], watchdog_timeout_seconds=5.0,
                sampler_backend_factory=lambda: run.backend,
                run_context_factory=run.context_factory, popen_factory=popen_factory,
                sampler_factory=T.manual_sampler_factory(k, False, made=run.samplers),
                dispatch_latch=self.latch, dispatch_journal=dispatch_journal,
                dispatch_ticket=dispatch_ticket)
        if mode == "TAMPER_ENVELOPE" and dispatch_ticket is not None:
            # FIX005: the lower layer returns prepared evidence; edit it
            envelope = dict(envelope, validated_result=dict(
                envelope["validated_result"], status="PASS_EDITED"))
        elif mode == "TAMPER_ENVELOPE":
            data = json.loads(Path(output_path).read_bytes())
            data["accepted_result"]["status"] = "PASS_EDITED"
            Path(output_path).write_bytes(J.canonical(data))
        return envelope


class OrchestratorConsumerTests(unittest.TestCase):
    """Drives the actual execute_fresh_authorized_protocol ->
    exact_launch -> journaled_exact_launch -> execute_runtime_bound_workload
    -> validate_worker_result_identity -> ledger path, with only the frozen
    capture/authority/plan helpers faked.  Formal Stage B is NOT executed."""

    def run_protocol(self, modes, j, n=2):
        O = orchestrator()
        tmp = Path(tempfile.mkdtemp(prefix="fix003_orch_"))
        requests = {i: orch_request(i, tmp) for i in range(n)}
        rows = [{"request_index": i, "candidate_id": "CAND",
                 "run_phase": "UNTIMED_WARMUP" if i == 0 else "MEASURED",
                 "request_identity": [i]} for i in range(n)]
        plan = {"workload_id": "W", "branch_capture_path": str(tmp / "branch.json"),
                "branch_capture_sha256": "b" * 64, "capture_rows": [],
                "static_launch_rows": rows, "allowed_candidate_ids": ["CAND"],
                "candidate_first_launch_order": ["CAND"],
                "request_identity_sha256": hashlib.sha256(O.canonical_json_bytes(
                    [r["request_identity"] for r in rows])).hexdigest(),
                "next_capture_ordinal": 1}
        binding = {"requests": requests, "capture_row": {"capture_sha256": "c" * 64},
                   "resource_path": tmp / "res.json", "resource": {},
                   "next_capture_ordinal": 2}
        launcher = HarnessLauncher(modes)
        capture_mod = types.ModuleType("capture_pretiming_resources")
        capture_mod.capture = lambda root: {}
        frozen = {"activation": {}, "protocol_identity_sha256": "p" * 64}
        with mock.patch.object(O, "WORKLOADS", ("W",)), \
                mock.patch.object(O, "ExecutionAuthority", lambda *a: None), \
                mock.patch.object(O, "FrozenAssets", lambda a: None), \
                mock.patch.object(O, "validate_adaptive_execution_protocol",
                                  return_value=frozen), \
                mock.patch.object(O, "strict_json_load", return_value={}), \
                mock.patch.object(O, "materialize_fresh_workload_plan",
                                  return_value=plan), \
                mock.patch.object(O, "bind_candidate_series", return_value=binding), \
                mock.patch.object(O, "prelaunch_guard", return_value={
                    "worker_launch_authorized": True,
                    "physical_allocation_authorized": True}), \
                mock.patch.object(C, "launch_request", launcher), \
                mock.patch.dict(sys.modules, capture_pretiming_resources=capture_mod):
            try:
                out = O.execute_fresh_authorized_protocol(
                    tmp, tmp / "runtime", tmp / "evidence", tmp / "dur.json",
                    {"source_commit": "c", "source_tree": "t"},
                    dispatch_journal=j)
                return out, None, launcher
            except C.StopSignal as stop:
                return None, stop, launcher

    def test_successful_accepted_results_reach_ledger(self):
        j = journal()
        out, stop, launcher = self.run_protocol(["ACCEPT", "ACCEPT"], j)
        self.assertIsNone(stop)
        self.assertEqual(launcher.spawns, 2)
        self.assertEqual(out["request_count"], 2)
        self.assertEqual(out["measured_result_count"], 1)
        self.assertEqual(out["decision_input_ledger"][0]["integer_metrics"], {"m": 1})
        self.assertEqual([h["status"] for h in j.state()["history"]],
                         ["ACCEPTED", "ACCEPTED"])

    def assert_global_stop(self, modes, spawns_expected, j=None):
        j = j if j is not None else journal()
        out, stop, launcher = self.run_protocol(modes, j)
        self.assertIsNone(out)
        self.assertEqual(stop.stop_id, "SB_STOP_GLOBAL")
        self.assertIn("later_launches=0", stop.detail)
        self.assertEqual(launcher.calls, 1)             # zero later launch
        self.assertEqual(launcher.spawns, spawns_expected)
        return stop, j

    def test_raw_pass_is_not_accepted(self):
        stop, _ = self.assert_global_stop(["RAW_PASS_ONLY", "ACCEPT"], 0)
        # FIX005: refused by the coordinator's prepared-evidence check
        self.assertIn("CURRENT_DISPATCH_MISMATCH:prepared_schema", stop.detail)

    def test_unverifiable_envelope_stops(self):
        stop, j = self.assert_global_stop(["TAMPER_ENVELOPE", "ACCEPT"], 1)
        self.assertIn("validated_result", stop.detail)     # FIX005: pre-commit
        self.assertFalse(j.state()["ready"])

    def test_controller_stop_stops_all_later(self):
        stop, j = self.assert_global_stop(["LIVE_DESCENDANT", "ACCEPT"], 1)
        self.assertFalse(j.state()["ready"])
        # a fresh protocol run on the same scope captures/spawns nothing
        out, stop2, launcher = self.run_protocol(["ACCEPT"], rebuilt(j), n=1)
        self.assertEqual(stop2.stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertEqual((launcher.calls, launcher.spawns), (0, 0))

    def test_journal_required_and_refusing_journal(self):
        out, stop, launcher = self.run_protocol(["ACCEPT"], None, n=1)
        self.assertEqual((stop.stop_id, stop.detail),
                         ("SB_STOP_DISPATCH_JOURNAL", "journal_required"))
        self.assertEqual(launcher.calls, 0)
        out, stop, launcher = self.run_protocol(["ACCEPT"], journal(init=False), n=1)
        self.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertEqual(launcher.calls, 0)

    def test_journal_refusal_mid_protocol_zero_later_spawn(self):
        j = journal()
        j.storage.fail[("create", "000002.IN_FLIGHT")] = OSError(28, "ENOSPC")
        out, stop, launcher = self.run_protocol(["ACCEPT", "ACCEPT", "ACCEPT"], j, n=3)
        self.assertEqual(stop.stop_id, "SB_STOP_GLOBAL")
        self.assertIn("IN_FLIGHT_PUBLISH_FAILED", stop.detail)
        # FIX005: the coordinator reserves BEFORE calling the launcher, so the
        # failed reservation of request 2 calls no launcher at all
        self.assertEqual((launcher.calls, launcher.spawns), (1, 1))

    def test_legacy_execute_authorized_plan_still_held(self):
        O = orchestrator()
        with mock.patch.object(O, "validate_complete_execution_plan_structure"), \
                mock.patch.object(O, "validate_complete_execution_plan"):
            with self.assertRaises(C.StopSignal) as caught:
                O.execute_authorized_plan(Path("r"), Path("r"), Path("e"), Path("a"),
                                          Path("d"), {})
        self.assertEqual(caught.exception.stop_id, "SB_STOP_LEGACY_EXECUTION_PATH")


# ---------------------------------------------------------------------------
# Timeout helper containment check (no new gate) and CLI default denial
# ---------------------------------------------------------------------------
class TimeoutHelperContainmentTests(unittest.TestCase):

    def assert_contained(self, run, stop):
        self.assertIsNotNone(stop)
        starts = [e for e in run.context.evidence if e["kind"] == "DEADLINE_START"]
        self.assertEqual([e.get("label") for e in starts], ["TIMEOUT"])   # one deadline
        self.assertFalse(run.journal.state()["ready"])       # durable STOP/IN_FLIGHT
        self.assertIn("JOURNAL_FINAL_STOP_PUBLISHED",
                      stop.cleanup["receipt"]["completed_in_order"])
        assert_new_run_refused(self, rebuilt(run.journal))

    def test_success_branch_helper_exception_is_contained(self):
        k, root, _ = T.world()
        run = T.Launch(k, root)
        with mock.patch.object(C, "_stop_sampler_bounded",
                               side_effect=RuntimeError("TIMEOUT_HELPER_BUG")):
            stop = run.run()
        self.assert_contained(run, stop)
        # FIX004 adaptation: the helper error is secondary; timeout is primary
        self.assertEqual(stop.cleanup["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("TIMEOUT_HELPER_BUG", json.dumps(stop.cleanup["secondary_failures"]))

    def test_timeout_evidence_failure_after_cleanup_is_contained(self):
        k, root, _ = T.world()
        run = T.Launch(k, root)
        with mock.patch.object(C, "_timeout_stop_evidence",
                               side_effect=OSError(28, "TIMEOUT_EVIDENCE_ENOSPC")):
            stop = run.run()
        self.assert_contained(run, stop)


class CliProgressionTests(unittest.TestCase):

    def main_with(self, extra):
        tmp = Path(tempfile.mkdtemp(prefix="fix003_cli_"))
        (tmp / "j").mkdir()
        (tmp / "p").mkdir()
        seen = {}

        def launch(*args, **kwargs):
            seen.update(kwargs)
            raise C.StopSignal("SB_STOP_TEST", "stopped")
        argv = ["x", "--repo-root", "r", "--runtime-root", "r", "--resource", "a",
                "--branch-resource", "b", "--durability", "d", "--request", "q",
                "--output", "o", "--log", "l", "--dispatch-journal-dir", str(tmp / "j"),
                "--dispatch-generation", "1", "--dispatch-input-identity", "I",
                "--dispatcher-owner", "O"] + [a.replace("TMP", str(tmp)) for a in extra]
        with mock.patch.object(C, "launch_request", launch), \
                mock.patch.object(C, "strict_json_load", return_value={}), \
                mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            try:
                C.main()
            except (C.StopSignal, J.JournalRefused) as error:
                seen["error"] = error
        return seen

    def test_journal_without_progression_refuses(self):
        seen = self.main_with([])
        self.assertIsNone(seen["dispatch_journal"].progression)
        self.assertEqual(seen["dispatch_journal"].state()["reason"],
                         "PROGRESSION_STORE_REQUIRED")
        seen = self.main_with(["--initialize-dispatch-scope"])
        self.assertEqual(seen["error"].code, "PROGRESSION_STORE_REQUIRED")

    def test_progression_dir_wired_unqualified(self):
        seen = self.main_with(["--dispatch-progression-dir", "TMP/p"])
        j = seen["dispatch_journal"]
        self.assertIsInstance(j.progression, J.FileStorage)
        self.assertEqual(j.state()["reason"], "SCOPE_NOT_INITIALIZED")
        self.assertEqual(j.progression.guarantees["no_delete"], "NOT_ENFORCED")
        self.assertFalse(J.NATIVE_STORAGE_QUALIFIED)


if __name__ == "__main__":
    unittest.main()
