"""DEV007_FIX001 regressions for Astra A007-1 and A007-2 (pure simulation only).

A007-1  current-request acceptance: a normal worker exit is accepted only
        when completion cleanup is fully resolved.  Unresolved custody,
        sampler uncertainty, incomplete output or an exhausted completion
        deadline give SB_STOP_CONTROLLER_COMPLETION_UNRESOLVED with the full
        completion record persisted; the worker's raw result is moved off the
        authoritative path as worker-only evidence and never validated.
A007-2  a collector exception carrying `output` is a cumulative snapshot
        under the same contract as TimeoutExpired/normal return.

Everything runs through the controller's exact launch_request with the
FakeKernel/FakePopen/SimulatedObjectSignalPort fixtures.  Only the scientific
result helpers (strict_json_load inside validation, identity check, resource
gate) are stubbed to give an independently valid worker result.  No fork,
pidfd, signal or host /proc read.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_dev007_fix001
"""
import json
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import termination  # noqa: E402
import test_dev006 as T  # noqa: E402
import test_dev007 as U  # noqa: E402
from synthetic import advance  # noqa: E402

C = T.C
STOP = "SB_STOP_CONTROLLER_COMPLETION_UNRESOLVED"
PASS = "BOUNDED_PARAMETERIZED_REAL_WORKER_PASS"
WORKER_RESULT = {"schema": C.WORKER_RESULT_SCHEMA, "status": PASS,
                 "cleanup_result": "PASS_TARGET_REMOVED"}


def valid_worker(calls):
    """Wrap the exact _validate_completed_worker; stub only the scientific
    result helpers so that the worker result is independently valid."""
    original = C._validate_completed_worker

    def validate(*args, **kwargs):
        calls.append("VALIDATE")
        with mock.patch.object(C, "strict_json_load", return_value=dict(WORKER_RESULT)), \
                mock.patch.object(C, "validate_worker_result_identity", return_value=None), \
                mock.patch.object(C, "evaluate_resource_hard_gate",
                                  return_value={"status": "PASS"}):
            out = original(*args, **kwargs)
        calls.append(dict(out))
        return out
    return mock.patch.object(C, "_validate_completed_worker", side_effect=validate)


def finish(run, code=0, hook=None, text="complete output"):
    """The worker writes its raw PASS result, exits normally within the
    watchdog; `hook(run)` injects the controller-side condition."""
    def communicate(timeout=None):
        run.popen.calls.append(("communicate", timeout))
        run.raw_path.write_text(json.dumps(WORKER_RESULT))
        if run.k.procs[run.root.pid].state != "Z":
            run.k.exit(run.root.pid, code)
        run.popen.poll()
        if hook is not None:
            hook(run)
        run.popen.output = text
        return text, None
    run.popen.communicate = communicate


def root_cap(run):
    return [c for c in run.route.table._caps if c.kind == "ROOT"][0]


def hold_lease(run):
    table = root_cap(run).table
    run.held = table.lease(root_cap(run), termination.SIGNAL_OP, table.binding)
    run.held.__enter__()                 # an in-flight operation never ends


def close_in_progress(run):
    cap = root_cap(run)
    with cap.table._lock:                # another closer is mid provider-close
        cap.state = termination.CLOSING


def member_acquired(run):
    run.route.table.acquire(run.desc.pid, "MEMBER", T.ident(run.desc), "SIM_PROOF")


def sampler_liveness_unknown(run):
    sampler = run.samplers[0]

    def stop_bounded(budget):
        raise RuntimeError("fake join failure")

    class Unknown:
        def is_alive(self):
            raise RuntimeError("fake liveness failure")
    sampler.stop_bounded = stop_bounded
    sampler._thread = Unknown()


def budget_exhausted(run):
    sampler = run.samplers[0]
    real = sampler.stop_bounded

    def stop_bounded(budget):           # the join itself overruns the budget
        advance(run.k, C.FAILURE_CLEANUP_TOTAL_SECONDS + 1.0)
        return real(budget)
    sampler.stop_bounded = stop_bounded


def failing_under(directory, real):
    """write_canonical_json that fails (ENOSPC) only inside `directory`."""
    def write(path, value):
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(directory):
            raise OSError(28, "fake ENOSPC")
        return real(path, value)
    return write


def failing_publish_under(directory):
    real = C.journal_protocol.publish_no_clobber

    def publish(path, data):
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(directory):
            raise OSError(28, "fake ENOSPC")
        return real(path, data)
    return publish


def launch(case_hook=None, *, code=0, descendant=False, route_kwargs=None,
           stuck=False, calls=None):
    k, root, desc = T.world(descendant=descendant)
    run = T.Launch(k, root, stuck_sampler=stuck, route_factory=lambda: T.sim_route(
        k, **(route_kwargs or {})))
    run.desc = desc
    finish(run, code=code, hook=case_hook)
    calls = [] if calls is None else calls
    with valid_worker(calls):
        stop = run.run()
    return run, stop, calls


class CompletionAcceptanceTests(unittest.TestCase):

    def test_resolved_normal_finish_is_accepted(self):
        run, stop, calls = launch()
        self.assertIsNone(stop)
        self.assertEqual(calls[0], "VALIDATE")
        self.assertEqual(calls[1]["status"], PASS)
        # DEV007_FIX002: output_path is the controller acceptance envelope,
        # bound to the untouched raw worker bytes and verified via journal.
        env = C.journal_protocol.verify_controller_acceptance(run.output_path, run.journal)
        self.assertEqual(env["accepted_result"]["status"], PASS)
        self.assertEqual(json.loads(run.raw_path.read_text()), WORKER_RESULT)
        self.assertTrue(run.journal.state()["ready"])
        self.assertTrue(run.context.closed)
        self.assertFalse(run.latch.blocked)
        self.assertEqual(run.route.table.held_caps(), [])
        self.assertFalse(run.output_path.with_suffix(".worker-unaccepted.json").exists())
        self.assertFalse(run.output_path.with_suffix(".completion-cleanup.json").exists())
        self.assertEqual(run.log_path.read_text(), "complete output")

    def assert_refused(self, run, stop, calls, reason):
        self.assertEqual(calls, [], "worker result must not reach acceptance")
        self.assertIsNotNone(stop)
        self.assertEqual(stop.stop_id, STOP)
        rec = stop.cleanup
        self.assertIn(reason, rec["unresolved_reasons"])
        self.assertIn(reason, stop.detail)
        self.assertFalse(rec["completion_resolved"])
        self.assertTrue(rec["dispatch_blocked"] and run.latch.blocked)
        self.assertEqual(rec["controller_acceptance"], "REFUSED_COMPLETION_UNRESOLVED")
        self.assertEqual(rec["cleanup_deadline"]["label"], "COMPLETION_CLEANUP")
        self.assertNotIn("evidence_write_failure", rec)
        # authoritative output is the stop record, never the worker PASS
        out = json.loads(run.output_path.read_text())
        self.assertEqual(out["status"], STOP)
        self.assertFalse(out["decision_ledger_eligible"])
        self.assertFalse(out["worker_result_validated"])
        # DEV007_FIX002: raw worker bytes stay in place, untouched
        self.assertEqual(json.loads(run.raw_path.read_text()), WORKER_RESULT)
        self.assertEqual(rec["worker_output_disposition"], "RAW_PRESERVED_UNACCEPTED_IN_PLACE")
        self.assertFalse(rec["raw_move_attempted"])
        with self.assertRaises(C.journal_protocol.JournalRefused):
            C.journal_protocol.verify_controller_acceptance(run.output_path, run.journal)
        # full completion record persisted
        persisted = json.loads(run.output_path.with_suffix(".completion-cleanup.json").read_text())
        self.assertEqual(persisted["unresolved_reasons"], rec["unresolved_reasons"])
        self.assertEqual(persisted["custody"], json.loads(json.dumps(rec["custody"])))
        self.assertEqual(out["completion_cleanup"]["unresolved_reasons"], rec["unresolved_reasons"])
        self.assertEqual(run.log_path.read_text(), "complete output")
        # no second cleanup after the completion stop
        self.assertFalse(run.output_path.with_suffix(".post-spawn-cleanup.json").exists())
        self.assertNotIn("SIGKILL", [c[3] for c in U.signals(run.route.port)])
        # the next request is refused before any Popen
        nxt = T.Launch(*T.world()[:2], latch=run.latch)
        self.assertEqual(nxt.run().stop_id, "SB_STOP_DISPATCH_BLOCKED")
        self.assertEqual(nxt.popen_calls, 0)
        # ... and by a NEW controller (fresh latch, fresh run id), same scope
        fresh = T.Launch(*T.world()[:2], journal=run.journal, run_id="RUN-FRESH")
        refused = fresh.run()
        self.assertEqual(refused.stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertEqual(fresh.popen_calls, 0)
        return rec

    def test_root_close_failure_not_accepted(self):
        """Astra A007-1 exact case: root provider close EIO."""
        run, stop, calls = launch(route_kwargs=dict(close_errors={3: OSError(5, "fake close EIO")}))
        rec = self.assert_refused(run, stop, calls, "CUSTODY_NOT_CLOSED")
        self.assertEqual([r["state"] for r in rec["custody"]["root"]], ["CLOSE_FAILED"])
        self.assertFalse(rec["context_closed"] or run.context.closed)
        self.assertEqual(len(U.closes(run.route.port)), 1)     # one close, not retried

    def test_member_close_failure_not_accepted(self):
        def acquired_then_exited(run):   # D1: descendant genuinely exits
            member_acquired(run)
            run.k.exit(run.desc.pid, 0)
            run.k.reap(run.desc.pid) if hasattr(run.k, "reap") else None
        run, stop, calls = launch(acquired_then_exited, descendant=True,
                                  route_kwargs=dict(close_errors={4: OSError(5, "fake close EIO")}))
        rec = self.assert_refused(run, stop, calls, "CUSTODY_NOT_CLOSED")
        self.assertEqual([r["state"] for r in rec["custody"]["root"]], ["CLOSED"])
        self.assertEqual([r["state"] for r in rec["custody"]["members"]], ["CLOSE_FAILED"])
        self.assertEqual(sorted(c[2] for c in U.closes(run.route.port)), [3, 4])

    def test_held_lease_not_accepted(self):
        run, stop, calls = launch(hold_lease)
        rec = self.assert_refused(run, stop, calls, "CUSTODY_NOT_CLOSED")
        self.assertEqual(rec["custody"]["root"][0]["close_outcome"], "DEFERRED_LEASE_HELD")
        self.assertEqual(U.closes(run.route.port), [])          # deferred, not done
        run.held.__exit__(None, None, None)                    # release: close once
        self.assertEqual(len(U.closes(run.route.port)), 1)

    def test_close_in_progress_not_accepted(self):
        run, stop, calls = launch(close_in_progress)
        rec = self.assert_refused(run, stop, calls, "CUSTODY_NOT_CLOSED")
        self.assertEqual(rec["custody"]["root"][0]["close_outcome"], "CLOSE_IN_PROGRESS")
        self.assertEqual(U.closes(run.route.port), [])

    def test_stuck_sampler_not_accepted(self):
        run, stop, calls = launch(stuck=True)
        rec = self.assert_refused(run, stop, calls, "SAMPLER_NOT_STOPPED")
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertEqual(len(run.samplers[0]._thread.joins), 1)

    def test_sampler_stop_uncertain_not_accepted(self):
        run, stop, calls = launch(sampler_liveness_unknown)
        rec = self.assert_refused(run, stop, calls, "SAMPLER_NOT_STOPPED")
        self.assertTrue(rec["sampler_stop"]["state"].startswith("STOP_FAILED_LIVENESS_UNKNOWN"))
        self.assertEqual(len(run.route.table.held_caps()), 1)   # authority retained

    def test_completion_budget_exhaustion_not_accepted(self):
        run, stop, calls = launch(budget_exhausted)
        rec = self.assert_refused(run, stop, calls, "CLEANUP_DEADLINE_EXHAUSTED")
        self.assertTrue(rec["cleanup_deadline"]["exhausted"])
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")

    def test_worker_failure_with_unresolved_completion_keeps_exit(self):
        run, stop, calls = launch(code=3, route_kwargs=dict(
            close_errors={3: OSError(5, "fake close EIO")}))
        rec = self.assert_refused(run, stop, calls, "CUSTODY_NOT_CLOSED")
        rc = run.popen.returncode                 # FakeKernel reports -3
        self.assertNotEqual(rc, 0)
        self.assertIn("worker_exit=%s" % rc, stop.detail)
        self.assertEqual(rec["worker_returncode"], rc)

    def test_evidence_write_failure_still_stops_and_latches(self):
        real = C.write_canonical_json
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(
            k, close_errors={3: OSError(5, "fake close EIO")}))
        failing = failing_under(run.tmp / "out", real)
        finish(run)
        calls = []
        with valid_worker(calls), mock.patch.object(C, "write_canonical_json", failing), \
                mock.patch.object(C.journal_protocol, "publish_no_clobber",
                                  failing_publish_under(run.tmp / "out")):
            stop = run.run()
        self.assertIs(C.write_canonical_json, real)
        self.assertEqual((stop.stop_id, calls), (STOP, []))
        rec = stop.cleanup
        self.assertEqual(len(rec["evidence_write_failure"]), 2)
        self.assertIn("EVIDENCE_WRITE_FAILED", [r for x in run.latch.records
                                                for r in x["reasons"]])
        self.assertIn("CUSTODY_NOT_CLOSED", rec["unresolved_reasons"])
        # DEV007_FIX002: no acceptance; raw bytes untouched in place
        self.assertEqual(json.loads(run.raw_path.read_text()), WORKER_RESULT)

    def test_move_and_stop_write_failure_preserves_raw(self):
        """Replaces the FIX001 REMOVED_NOT_PRESERVED assertion (D4)."""
        def failing_replace(a, b):
            raise OSError(18, "fake EXDEV")
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, stuck_sampler=True)
        failing_write = failing_under(run.tmp / "out", C.write_canonical_json)
        finish(run)
        calls = []
        with valid_worker(calls), mock.patch.object(C, "write_canonical_json", failing_write), \
                mock.patch.object(C.journal_protocol, "publish_no_clobber",
                                  failing_publish_under(run.tmp / "out")), \
                mock.patch.object(C.os, "replace", failing_replace):
            stop = run.run()
        self.assertEqual((stop.stop_id, calls), (STOP, []))
        self.assertEqual(stop.cleanup["worker_output_disposition"],
                         "RAW_PRESERVED_UNACCEPTED_IN_PLACE")
        self.assertEqual(json.loads(run.raw_path.read_text()), WORKER_RESULT)
        self.assertTrue(run.latch.blocked)

    def test_validation_stop_on_resolved_completion_unchanged(self):
        """Resolved completion keeps the unchanged validation stop mapping."""
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        U.completed(run)
        stop = run.run()
        self.assertEqual((stop.stop_id, stop.detail), ("SB_STOP_VALIDATION", "worker_result_identity"))
        self.assertTrue(stop.cleanup["completion_resolved"])
        self.assertFalse(run.latch.blocked)


class CollectorExceptionSnapshotTests(unittest.TestCase):

    def collect(self, prior, error):
        c = C.CumulativeOutputCollector()
        if prior is not None:
            c.timeout_snapshot(prior, "prior")
        p = types.SimpleNamespace(stdout=None, communicate=mock.Mock(side_effect=error))
        text, rec = C._bounded_collect(p, 1, c)
        return c, text, rec

    def err(self, output="absent"):
        e = OSError(5, "collector")
        if output != "absent":
            e.output = output
        return e

    def test_astra_exception_bytes_supersede(self):
        c, text, rec = self.collect(b"prefix", self.err(b"prefix-more"))
        self.assertEqual(text, "prefix-more")
        self.assertFalse(rec["output_complete"] or c.complete)
        last = rec["output_contract"]["snapshots"][-1]
        self.assertEqual((last["kind"], last["error"]), ("COLLECTOR_FAILED_CUMULATIVE",
                                                         "OSError:[Errno 5] collector"))
        self.assertEqual((last["source_type"], last["raw_bytes"], last["lossy_decode"]),
                         ("bytes", 11, False))
        self.assertTrue(rec["output_contract"]["cumulative_contract_consistent"])

    def test_exception_text_none_and_absent(self):
        self.assertEqual(self.collect(b"prefix", self.err("prefix+txt"))[1], "prefix+txt")
        for e in (self.err(None), self.err()):                  # no new snapshot
            c, text, rec = self.collect(b"prefix", e)
            self.assertEqual(text, "prefix")
            self.assertEqual(rec["output_contract"]["snapshots"][-1]["kind"],
                             "COLLECTOR_FAILED_SNAPSHOT_KEPT")
            self.assertFalse(rec["output_complete"])

    def test_genuine_repetition_and_empty_follow_contract(self):
        self.assertEqual(self.collect(b"same\n", self.err(b"same\nsame\n"))[1], "same\nsame\n")
        # empty cumulative snapshot after output violates the contract: it is
        # the latest snapshot, and the superseded text is reported, not lost
        c, text, rec = self.collect(b"prefix", self.err(b""))
        self.assertEqual(text, "")
        self.assertFalse(rec["output_contract"]["cumulative_contract_consistent"])
        self.assertEqual(rec["output_contract"]["inconsistent_snapshots"][0]["superseded_text"],
                         "prefix")
        # empty exception output with no earlier output is consistent
        self.assertTrue(self.collect(None, self.err(b""))[2]["output_contract"]
                        ["cumulative_contract_consistent"])

    def test_lossy_bytes_are_flagged_with_raw_identity(self):
        raw = b"ok\xff"
        c, text, rec = self.collect(None, self.err(raw))
        last = rec["output_contract"]["snapshots"][-1]
        self.assertEqual(text, "ok�")
        self.assertTrue(last["lossy_decode"])
        self.assertEqual(last["raw_bytes"], 3)
        self.assertEqual(last["raw_sha256"], C.hashlib.sha256(raw).hexdigest())
        self.assertEqual(rec["output_contract"]["text_normalization"],
                         "BYTES_DECODED_UTF8_ERRORS_REPLACE;STR_KEPT_AS_IS")

    def test_snapshot_after_persisted_log_is_flagged(self):
        c = C.CumulativeOutputCollector()
        c.timeout_snapshot(b"prefix", "P1")
        c.mark_persisted("LOG1", c.text)
        self.assertTrue(c.report()["persisted_log_matches_latest"])
        c.failure(self.err(b"prefix-more"), "P2")
        rep = c.report()
        self.assertEqual(rep["snapshots"][-1]["differs_from_persisted_log"], "LOG1")
        self.assertFalse(rep["persisted_log_matches_latest"])

    def test_growth_after_timeout_through_launch(self):
        """Timeout, then the TIMEOUT_COLLECT collector fails carrying newer
        cumulative output: log has the new bytes once, output incomplete."""
        k, root, desc = T.world()
        run = T.Launch(k, root)
        run.popen.write("prefix\n")

        def waiter(process, seconds):
            e = OSError(5, "fake collector EIO")
            e.output = b"prefix\nmore\n"
            process.collector_error = e
            advance(k, 1.0)
            return process.poll() is not None
        run.waiter = waiter
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertEqual(run.log_path.read_text(), "prefix\nmore\n")
        collection = stop.cleanup["output_collection"]
        self.assertFalse(collection["output_complete"])
        self.assertIn("OUTPUT_EOF_NOT_OBSERVED", stop.cleanup["unresolved_reasons"])
        self.assertEqual([s["kind"] for s in collection["output_contract"]["snapshots"]],
                         ["TIMEOUT_EXPIRED_CUMULATIVE", "COLLECTOR_FAILED_CUMULATIVE"])
        self.assertTrue(run.latch.blocked)

    def test_post_spawn_record_reflects_persisted_log(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        e = OSError(5, "fake watchdog EIO")
        e.output = "partial\n"
        run.popen.collector_error = e
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE")
        self.assertEqual(run.log_path.read_text(), "partial\n")
        contract = json.loads(run.output_path.with_suffix(
            ".post-spawn-cleanup.json").read_text())["output_contract"]
        self.assertTrue(contract["persisted_log_matches_latest"])
        self.assertEqual(contract["persisted_logs"][-1]["phase"], "POST_SPAWN_CLEANUP")


class AstraDev007ProbeRegressionTests(unittest.TestCase):
    """Astra's two DEV007 counterexamples with the repaired expectations."""

    def test_normal_completion_custody_failure_not_accepted(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(
            k, close_errors={3: OSError(5, "injected close failure")}))
        U.completed(run)
        returned = []
        with valid_worker(returned):
            stop = run.run()
        self.assertEqual(returned, [])
        self.assertEqual(stop.stop_id, STOP)
        self.assertTrue(run.latch.blocked and not run.context.closed)

    def test_collector_failure_fresh_output_kept(self):
        c = C.CumulativeOutputCollector()
        c.timeout_snapshot(b"prefix", "prior")
        e = OSError(5, "collector")
        e.output = b"prefix-more"
        p = types.SimpleNamespace(stdout=None, communicate=mock.Mock(side_effect=e))
        text, rec = C._bounded_collect(p, 1, c)
        self.assertEqual(text, "prefix-more")
        self.assertFalse(rec["output_complete"])


if __name__ == "__main__":
    unittest.main()
