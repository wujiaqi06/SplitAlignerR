"""DEV007_FIX004 pure-simulation regressions (no native effects).

A007F3-1  current-request / current-dispatch binding of the consumer adapter
          (stage_b_orchestrator.journaled_exact_launch, bound through
          stage_b_dispatch_journal.bind_current_dispatch /
          verify_current_dispatch_acceptance) and its coupled protocol
          consumer execute_fresh_authorized_protocol.
A007F3-2  timeout primary failure retained as a structured record; later
          cleanup/helper/sampler/evidence/interrupt outcomes are secondary.

Launches run the exact stage_b_controller.launch_request over the fake
kernel / FakePopen / MemoryStorage fixtures (test_dev006, test_dev007_fix003
HarnessLauncher).  Stale/mutating launchers are injected adapter-contract
counterexamples, not claims about the default launcher or formal Stage B.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import test_dev006 as T  # noqa: E402
import test_dev007_fix001 as V  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402

C = T.C
J = C.journal_protocol


def request_sha(request):
    return hashlib.sha256(C.canonical_json_bytes(dict(request))).hexdigest()


class Paths:
    def __init__(self, stem):
        self.tmp = Path(tempfile.mkdtemp(prefix="fix004_adapter_"))
        self.stem = stem

    def call(self, launcher, j, request, stem=None, output=None):
        O = W.orchestrator()
        stem = stem or self.stem
        t = self.tmp
        return O.journaled_exact_launch(
            launcher, j, t, t / "runtime", t / "res.json", t / "dur.json", request,
            t / "req" / f"{stem}.request.json",
            output if output is not None else t / "results" / f"{stem}.result.json",
            t / "logs" / f"{stem}.log.txt", t / "branch.json", f"ADAPTER:{stem}")

    def output(self, stem):
        return self.tmp / "results" / f"{stem}.result.json"


class Recording:
    """Injected launcher wrapper: counts calls, optionally transforms."""

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# A007F3-1: adapter binding to the exact current request and dispatch
# ---------------------------------------------------------------------------
class CurrentDispatchBindingTests(unittest.TestCase):

    def setUp(self):
        self.j = W.journal()
        self.p = Paths("a")
        self.req_a = W.orch_request(0, self.p.tmp)
        self.real = W.HarnessLauncher(["ACCEPT"] * 8)
        # an authentic accepted dispatch of request A (seq 1)
        self.result_a = self.p.call(self.real, self.j, self.req_a, stem="a")
        self.env_a = J.verify_controller_acceptance(self.p.output("a"), self.j)
        self.req_b = dict(self.req_a, timeout_seconds=self.req_a["timeout_seconds"] + 1)

    def refused(self, launcher, request, code, stem="b", output=None):
        before = self.j.state()
        with self.assertRaises(C.StopSignal) as caught:
            self.p.call(launcher, self.j, request, stem=stem, output=output)
        stop = caught.exception
        self.assertEqual(stop.stop_id, "SB_STOP_GLOBAL")
        self.assertIn("later_launches=0", stop.detail)
        self.assertIn(code, stop.detail)
        return stop, before

    def test_positive_control_fresh_dispatch_is_bound(self):
        self.assertEqual(self.env_a["request_sha256"], request_sha(self.req_a))
        self.assertEqual(self.env_a["seq"], 1)
        result_b = self.p.call(self.real, self.j, self.req_b, stem="b")
        env_b = J.verify_controller_acceptance(self.p.output("b"), self.j)
        self.assertEqual((env_b["seq"], env_b["request_sha256"]), (2, request_sha(self.req_b)))
        self.assertEqual(result_b, env_b["accepted_result"])
        self.assertEqual([h["status"] for h in self.j.state()["history"]],
                         ["ACCEPTED", "ACCEPTED"])

    def test_astra_a007f3_1_stale_envelope_same_output_refused_before_launch(self):
        """The Astra probe: old valid envelope for A returned for request B
        (timeout changed, same result identity) at A's own output path."""
        stale = Recording(lambda *a, **k: self.env_a)
        stop, before = self.refused(stale, self.req_b, "CURRENT_OUTPUT_NOT_FRESH",
                                    output=self.p.output("a"))
        self.assertEqual(stale.calls, 0)                 # authority never handed
        self.assertEqual(self.j.state(), before)

    def test_stale_envelope_fresh_output_without_new_dispatch(self):
        stale = Recording(lambda *a, **k: self.env_a)
        self.refused(stale, self.req_b, "ACCEPTANCE_UNREADABLE")
        self.assertEqual(stale.calls, 1)
        self.assertEqual(self.j.state()["next_seq"], 2)  # nothing new journaled

    def test_stale_envelope_bytes_copied_to_fresh_output(self):
        def copy(*a, **k):
            shutil.copyfile(self.p.output("a"), a[6])
            return self.env_a
        self.refused(Recording(copy), self.req_b, "ACCEPTANCE_JOURNAL_MISMATCH")

    def test_changed_timeout_same_result_identity_real_dispatch_refused(self):
        """Launcher really dispatches, but a DIFFERENT request (timeout+1):
        persisted evidence is authentic and seq/output are current; only the
        request binding differs.  accepted_result identity fields are equal."""
        def mutate(repo, rt, rp, dp, request, *rest, **k):
            return self.real(repo, rt, rp, dp,
                             dict(request, timeout_seconds=request["timeout_seconds"] + 1),
                             *rest, **k)
        stop, _ = self.refused(Recording(mutate), self.req_b, "CURRENT_DISPATCH_MISMATCH")
        self.assertIn("request", stop.detail.split("CURRENT_DISPATCH_MISMATCH:")[1])
        env = J.verify_controller_acceptance(self.p.output("b"), self.j)
        self.assertEqual(env["seq"], 2)                  # historically accepted...
        for field in W.IDENTITY:                         # ...same result identity
            self.assertEqual(env["accepted_result"][field], self.result_a[field])

    def test_other_request_binding_mismatches(self):
        for n, (field, value) in enumerate((("evidence_root", "/elsewhere"),
                                            ("fresh_available_memory_bytes", 2),
                                            ("runtime_target", "/other/target"))):
            def mutate(repo, rt, rp, dp, request, *rest, _f=field, _v=value, **k):
                return self.real(repo, rt, rp, dp, dict(request, **{_f: _v}), *rest, **k)
            self.refused(Recording(mutate), self.req_b, "CURRENT_DISPATCH_MISMATCH",
                         stem=f"b{n}")

    def test_stale_prior_acceptance_returned_after_fresh_dispatch(self):
        def fresh_then_stale(*a, **k):
            self.real(*a, **k)                            # real seq-2 dispatch
            return dict(self.env_a, receipt={"seq": 1, "final": "ACCEPTED",
                                             "failures": [], "completed_in_order":
                                             ["JOURNAL_FINAL_ACCEPTED_PUBLISHED"]})
        stop, _ = self.refused(Recording(fresh_then_stale), self.req_b,
                               "CURRENT_DISPATCH_MISMATCH")
        self.assertIn("returned_envelope", stop.detail)
        self.assertIn("returned_receipt", stop.detail)

    def test_returned_receipt_missing_or_stale(self):
        for n, receipt in enumerate((None, {"seq": 1, "final": "ACCEPTED", "failures": [],
                                            "completed_in_order":
                                            ["JOURNAL_FINAL_ACCEPTED_PUBLISHED"]},
                                     {"seq": 2, "final": "STOP", "failures": [],
                                      "completed_in_order": ["X"]})):
            def edit(*a, _r=receipt, **k):
                env = dict(self.real(*a, **k))
                if _r is None:
                    env.pop("receipt")
                else:
                    env["receipt"] = _r
                return env
            stop, _ = self.refused(Recording(edit), self.req_b,
                                   "CURRENT_DISPATCH_MISMATCH", stem=f"r{n}")
            self.assertIn("returned_receipt", stop.detail)

    def test_wrong_run_in_returned_envelope(self):
        def edit(*a, **k):
            return dict(self.real(*a, **k), run_id="SOME-OTHER-RUN")
        stop, _ = self.refused(Recording(edit), self.req_b, "CURRENT_DISPATCH_MISMATCH")
        self.assertIn("returned_envelope", stop.detail)

    def test_wrong_sequence_extra_dispatch(self):
        def twice(repo, rt, rp, dp, request, qp, op, lp, bp, **k):
            self.real(repo, rt, rp, dp, request, qp, op.with_name("side.result.json"),
                      lp, bp, **k)
            return self.real(repo, rt, rp, dp, request, qp, op, lp, bp, **k)
        stop, _ = self.refused(Recording(twice), self.req_b, "CURRENT_DISPATCH_MISMATCH")
        self.assertIn("seq", stop.detail)

    def test_wrong_output_path(self):
        def elsewhere(repo, rt, rp, dp, request, qp, op, lp, bp, **k):
            return self.real(repo, rt, rp, dp, request, qp,
                             op.with_name("elsewhere.result.json"), lp, bp, **k)
        self.refused(Recording(elsewhere), self.req_b, "ACCEPTANCE_UNREADABLE")

    def test_wrong_scope(self):
        other = W.journal(dispatcher_owner="OTHER-DISPATCHER")

        def foreign(*a, **k):
            k["dispatch_journal"] = other
            return self.real(*a, **k)
        self.refused(Recording(foreign), self.req_b, "ACCEPTANCE_SCOPE_MISMATCH")

    def test_not_permitted_scope_never_launches(self):
        j = W.journal(init=False)
        launcher = Recording(self.real)
        with self.assertRaises(C.StopSignal) as caught:
            self.p.call(launcher, j, self.req_b, stem="np")
        self.assertIn("CURRENT_DISPATCH_NOT_PERMITTED", caught.exception.detail)
        self.assertEqual(launcher.calls, 0)

    def test_historical_acceptance_is_not_current_permission(self):
        """The stale A record still verifies historically, but is never the
        current result; permission remains state()['ready'] only."""
        self.assertEqual(J.verify_controller_acceptance(self.p.output("a"), self.j)["seq"], 1)
        expected = J.bind_current_dispatch(self.j, request_sha256=request_sha(self.req_a),
                                           output_path=self.p.output("new"))
        with self.assertRaises(J.JournalRefused) as caught:
            J.verify_current_dispatch_acceptance(expected, self.p.output("a"), self.j,
                                                 self.env_a)
        self.assertEqual(caught.exception.code, "CURRENT_BINDING_CHANGED")


class BindingLauncher(W.HarnessLauncher):
    """HarnessLauncher with injected stale/mutating modes (adapter-contract
    counterexamples); ACCEPT still calls the exact launch_request."""

    def __call__(self, repo, runtime, resource_path, durability_path, request,
                 request_path, output_path, log_path, branch_resource_path,
                 dispatch_journal=None):
        mode = self.modes[self.calls]
        if mode == "STALE_REPLAY":
            self.calls += 1
            return self.last
        if mode == "MUTATED_TIMEOUT":
            self.modes[self.calls] = "ACCEPT"
            request = dict(request, timeout_seconds=request["timeout_seconds"] + 1)
        self.last = super().__call__(
            repo, runtime, resource_path, durability_path, request, request_path,
            output_path, log_path, branch_resource_path,
            dispatch_journal=dispatch_journal)
        return self.last


class CoupledProtocolBindingTests(unittest.TestCase):
    """execute_fresh_authorized_protocol -> exact_launch -> journaled_exact_launch
    -> execute_runtime_bound_workload -> ledger, with injected launchers."""

    def run_protocol(self, modes, n):
        with mock.patch.object(W, "HarnessLauncher", BindingLauncher):
            return W.OrchestratorConsumerTests().run_protocol(modes, W.journal(), n=n)

    def test_fresh_success_positive_control(self):
        out, stop, launcher = self.run_protocol(["ACCEPT"] * 3, 3)
        self.assertIsNone(stop)
        self.assertEqual((launcher.calls, launcher.spawns), (3, 3))
        self.assertEqual(out["request_count"], 3)
        self.assertEqual(len(out["decision_input_ledger"]), 2)

    def test_stale_replay_stops_with_no_ledger_and_no_later_launch(self):
        out, stop, launcher = self.run_protocol(["ACCEPT", "STALE_REPLAY", "ACCEPT"], 3)
        self.assertIsNone(out)                            # no ledger consumed
        self.assertEqual(stop.stop_id, "SB_STOP_GLOBAL")
        self.assertIn("first_nonpass=W:1;later_launches=0", stop.detail)
        self.assertEqual((launcher.calls, launcher.spawns), (2, 1))

    def test_mutated_timeout_dispatch_stops_with_no_later_launch(self):
        out, stop, launcher = self.run_protocol(["ACCEPT", "MUTATED_TIMEOUT", "ACCEPT"], 3)
        self.assertIsNone(out)
        self.assertIn("CURRENT_DISPATCH_MISMATCH", stop.detail)
        self.assertEqual((launcher.calls, launcher.spawns), (2, 2))


# ---------------------------------------------------------------------------
# A007F3-2: timeout primary failure retained; secondary outcomes separate
# ---------------------------------------------------------------------------
class TimeoutPrimarySecondaryTests(unittest.TestCase):

    def launch(self, output="partial-timeout-output", raw=True):
        k, root, _ = T.world()
        run = T.Launch(k, root)
        run.popen.output = output
        real = run.popen.communicate

        def communicate(timeout=None):
            if raw and not run.raw_path.exists():   # worker wrote raw before timing out
                run.raw_path.write_text('{"raw":"kept"}')
            return real(timeout=timeout)
        run.popen.communicate = communicate
        return run

    def assert_primary(self, run, rec, output="partial-timeout-output"):
        primary = rec["primary_failure"]
        self.assertEqual((primary["type"], primary["phase"]), ("TimeoutExpired", "TIMEOUT"))
        self.assertEqual(primary["timeout_nanoseconds"], 5_000_000_000)
        self.assertEqual(primary["output_raw_sha256"],
                         hashlib.sha256(output.encode()).hexdigest())
        self.assertEqual(rec["original_failure"], primary["label"])
        self.assertEqual(rec["failure_phase"], "TIMEOUT")
        starts = [e for e in run.context.evidence if e["kind"] == "DEADLINE_START"]
        self.assertEqual([e.get("label") for e in starts], ["TIMEOUT"])   # one deadline
        if run.raw_path.exists():
            self.assertEqual(run.raw_path.read_text(), '{"raw":"kept"}')  # raw preserved
        self.assertFalse(run.journal.state()["ready"])
        W.assert_new_run_refused(self, W.rebuilt(run.journal))           # zero spawn

    def secondary(self, rec):
        return [(s["step"], s["error"]) for s in rec["secondary_failures"]]

    def test_ordinary_timeout_positive_control_frozen_grace(self):
        run = self.launch()
        stop = run.run()
        self.assertEqual((stop.stop_id, stop.detail), ("SB_STOP_TIMEOUT", "parameterized_worker"))
        self.assert_primary(run, stop.cleanup)
        self.assertEqual(stop.cleanup["secondary_failures"], [])
        self.assertEqual(stop.cleanup["timeout_stop_evidence"], "WRITTEN")
        term = run.evidence()["termination"]
        self.assertEqual(term["production_grace_seconds"], 60)
        self.assertEqual(term["primary_failure"], stop.cleanup["primary_failure"])
        self.assertEqual(C.TIMEOUT_CLEANUP_TOTAL_SECONDS,
                         stop.cleanup["bounded_cleanup_deadline"]["total_nanoseconds"] / 1e9)
        self.assertFalse(run.latch.blocked)
        self.assertIn("JOURNAL_FINAL_STOP_PUBLISHED", stop.cleanup["receipt"]["completed_in_order"])

    def test_astra_a007f3_2_evidence_write_failure_is_secondary(self):
        run = self.launch()
        with mock.patch.object(C, "_timeout_stop_evidence",
                               side_effect=OSError(28, "SECONDARY_TIMEOUT_RECORD_WRITE")):
            stop = run.run()
        rec = stop.cleanup
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assert_primary(run, rec)
        self.assertNotIn("SECONDARY_TIMEOUT_RECORD_WRITE", rec["original_failure"])
        self.assertEqual(self.secondary(rec), [("TIMEOUT_STOP_EVIDENCE_WRITE",
                                                "OSError:[Errno 28] SECONDARY_TIMEOUT_RECORD_WRITE")])
        self.assertTrue(rec["secondary_failures"][0]["after_cleanup_completed"])
        # no second cleanup/close: the timeout cleanup's own outcome stands
        self.assertEqual(rec["custody_close_outcome"], "CLOSED")
        kinds = [e["kind"] for e in run.context.evidence]
        self.assertNotIn("FAILURE_CLEANUP", kinds)
        self.assertEqual(kinds.count("CONTEXT_CLOSE"), 1)
        self.assertTrue(run.latch.blocked and rec["dispatch_blocked"])
        self.assertIn("JOURNAL_FINAL_STOP_PUBLISHED", rec["receipt"]["completed_in_order"])

    def test_timeout_log_write_failure_is_secondary(self):
        real = C._write_log

        def log(path, text, collector, phase):
            if phase == "TIMEOUT_STOP_EVIDENCE":
                raise OSError(5, "TIMEOUT_LOG_EIO")
            return real(path, text, collector, phase)
        run = self.launch()
        with mock.patch.object(C, "_write_log", log):
            stop = run.run()
        self.assert_primary(run, stop.cleanup)
        self.assertEqual(self.secondary(stop.cleanup)[0][0], "TIMEOUT_STOP_EVIDENCE_WRITE")
        self.assertIn("TIMEOUT_LOG_EIO", stop.cleanup["evidence_write_failure"])

    def test_timeout_cleanup_helper_exception_keeps_primary(self):
        for helper in ("_bounded_collect", "_stop_sampler_bounded", "_finish_custody"):
            with self.subTest(helper=helper):
                run = self.launch()
                with mock.patch.object(C, helper, side_effect=RuntimeError("HELPER_" + helper)):
                    stop = run.run()
                rec = stop.cleanup
                self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
                self.assert_primary(run, rec)
                self.assertEqual(rec["secondary_failures"][0]["step"], "TIMEOUT:HANDLING")
                self.assertIn("HELPER_" + helper, rec["secondary_failures"][0]["error"])
                self.assertNotIn("HELPER_", rec["original_failure"])
                self.assertTrue(run.latch.blocked)
                self.assertIn("residual_owned_targets", rec)
                self.assertEqual(rec["ownership_retained"], rec["ownership_unresolved"])

    def test_latest_output_kept_after_later_no_payload_error(self):
        run = self.launch(output="latest-cumulative-bytes")
        with mock.patch.object(C, "_bounded_collect",
                               side_effect=OSError(5, "NO_PAYLOAD_COLLECT")):
            stop = run.run()
        rec = stop.cleanup
        self.assert_primary(run, rec, output="latest-cumulative-bytes")
        self.assertEqual(run.log_path.read_text(), "latest-cumulative-bytes")
        self.assertEqual(rec["output_contract"]["chars"], len("latest-cumulative-bytes"))
        self.assertTrue(rec["output_contract"]["persisted_log_matches_latest"])

    def test_interrupt_after_timeout_cleanup_stays_interrupt(self):
        run = self.launch()
        with mock.patch.object(C, "_timeout_stop_evidence", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt) as caught:
                run.run()
        rec = caught.exception.cleanup
        self.assert_primary(run, rec)
        self.assertTrue(rec["secondary_failures"][-1]["interrupt"])
        self.assertEqual(rec["custody_close_outcome"], "CLOSED")     # not re-cleaned
        self.assertNotIn("FAILURE_CLEANUP", [e["kind"] for e in run.context.evidence])
        self.assertIn("JOURNAL_FINAL_STOP_PUBLISHED", rec["receipt"]["completed_in_order"])

    def test_interrupt_during_timeout_cleanup_contained_then_reraised(self):
        run = self.launch()
        with mock.patch.object(C, "_stop_sampler_bounded", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt) as caught:
                run.run()
        rec = caught.exception.cleanup
        self.assert_primary(run, rec)
        first = rec["secondary_failures"][0]
        self.assertEqual((first["step"], first["interrupt"]), ("TIMEOUT:HANDLING", True))
        self.assertTrue(run.latch.blocked)

    def test_termination_failure_then_evidence_failure(self):
        run = self.launch()

        def refused(*a, **k):
            raise C.StopSignal("SB_STOP_TIMEOUT_TERMINATION", "INJECTED_AUTHORITY_FAILURE")
        with mock.patch.object(C, "exact_timeout_state_machine", refused), \
                mock.patch.object(C, "_timeout_stop_evidence",
                                  side_effect=OSError(28, "LATE_EVIDENCE")):
            stop = run.run()
        rec = stop.cleanup
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT_TERMINATION")
        self.assert_primary(run, rec)
        self.assertIn("INJECTED_AUTHORITY_FAILURE",
                      rec["timeout_termination_failure"]["message"])
        self.assertEqual(self.secondary(rec)[-1][0], "TIMEOUT_STOP_EVIDENCE_WRITE")
        self.assertEqual([e["kind"] for e in run.context.evidence].count("FAILURE_CLEANUP"), 1)

    def test_all_late_writes_fail_prior_durable_intent_refuses(self):
        """Fully unwritable after IN_FLIGHT: evidence, FINAL STOP and publish
        all fail.  The primary survives in memory only (honest fallback); the
        durable RESERVED + IN_FLIGHT without FINAL still refuse."""
        run = self.launch()
        run.journal.storage.fail[("create", "000001.FINAL")] = OSError(28, "ENOSPC_FINAL")
        with mock.patch.object(C, "_timeout_stop_evidence",
                               side_effect=OSError(28, "ENOSPC_EVIDENCE")), \
                mock.patch.object(J, "publish_no_clobber", side_effect=OSError(28, "ENOSPC")):
            stop = run.run()
        rec = stop.cleanup
        self.assertEqual(rec["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("JOURNAL_FINAL_STOP", rec["receipt"]["failures"][0])
        self.assertEqual(run.journal.state()["reason"], "PRIOR_DISPATCH_IN_FLIGHT")
        del run.journal.storage.fail[("create", "000001.FINAL")]
        self.assert_primary(run, rec)


if __name__ == "__main__":
    unittest.main()
