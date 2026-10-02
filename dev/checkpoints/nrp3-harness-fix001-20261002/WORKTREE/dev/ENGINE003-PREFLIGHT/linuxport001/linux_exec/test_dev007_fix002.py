"""DEV007_FIX002 cross-boundary regressions (pure simulation only).

Adapts the independent Pro boundary probes (which asserted the defects) to
the corrected behaviour, and covers the combined ownership / cleanup /
acquisition / evidence / journal cases.  FakeKernel, FakePopen, virtual
time and injected storage only: no fork, pidfd, signal, /proc, native
smoke, real lock or filesystem-durability experiment.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import linux_entry  # noqa: E402
import termination  # noqa: E402
import test_dev006 as T  # noqa: E402
import test_dev007 as U  # noqa: E402
import test_dev007_fix001 as V  # noqa: E402

C = T.C
J = C.journal_protocol
PASS, STOP = V.PASS, V.STOP


_PROGRESSION = {}     # FIX003: the independent progression store paired with a journal store


def journal(storage=None, init=True):
    storage = storage if storage is not None else J.MemoryStorage()
    j = J.DispatchJournal(storage, run_generation=1, input_identity="TEST-INPUT",
                          dispatcher_owner="TEST-DISPATCHER",
                          progression=_PROGRESSION.setdefault(id(storage),
                                                              J.MemoryStorage()))
    if init:
        j.initialize_scope()
    return j


def reconciliation(j, run_id, operator="OPERATOR-1", identity=None, **override):
    """FIX003 typed, obligation-complete, run/scope-bound reconciliation
    evidence (operator-asserted modeled evidence, not native proof)."""
    kinds = {"ROOT_PROCESS": ("ROOT_REAPED_IDENTITY_VERIFIED", "root-ident"),
             "KNOWN_DESCENDANTS": ("ALL_KNOWN_EXITED_IDENTITY_VERIFIED", "desc-ident"),
             "CAPABILITY_CUSTODY": ("ALL_ACQUISITIONS_LEASES_CLOSED", "custody-ident"),
             "OUTPUT_COLLECTOR": ("COLLECTOR_EOF_OR_CLOSED", None),
             "RSS_SAMPLER": ("SAMPLER_STOPPED", None)}
    obligations = {}
    for name, (kind, ident) in kinds.items():
        fact = {"kind": kind, "resolved": True, "run_id": run_id}
        if ident:
            fact["identity"] = ident
        obligations[name] = fact
    evidence = {"cited_run_id": run_id, "run_generation": j.scope["run_generation"],
                "dispatcher_owner": j.scope["dispatcher_owner"], "operator": operator,
                "trust": J.RECONCILIATION_TRUST, "obligations": obligations}
    # FIX005: a v3 dispatch also needs the explicit disposition citing the
    # first unresolved dispatch's scope/seq, expected request and observed
    # evidence (modeled operator/controller decision).
    detail = j.state().get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("seq"), int):
        try:
            evidence["disposition"] = dict(
                j.required_disposition(detail["seq"]),
                decision="VOID_DISPATCH_NO_RESULT_NO_AUTO_RESAMPLE",
                controller="CONTROLLER-1")
        except J.JournalRefused:        # not reconcilable (e.g. legacy)
            pass
    # NRP-2 FIX001 (Astra recorded-identity decision): identity-bearing facts
    # must cite the ONE controller-recorded root token of the dispatch.  When
    # the durable EFFECT recorded one (modeled provider), the helper cites it;
    # otherwise it keeps the legacy free-form strings, which the current rule
    # refuses (NO_RECORDED_IDENTITY).  The token binds the modeled assertions
    # to this dispatch; it is not a per-descendant/lease identity.
    token = identity or ((evidence.get("disposition") or {})
                         .get("observed_root_identity") or {}).get("token")
    if token:
        for name in ("ROOT_PROCESS", "KNOWN_DESCENDANTS", "CAPABILITY_CUSTODY"):
            obligations[name]["identity"] = token
    evidence.update(override)
    return evidence


MODELED_TOKEN = "modeled-root-fix002"


def modeled_route_factory(k, run_id, token=MODELED_TOKEN):
    """NRP-2 FIX001 positive fixture: the same simulated route wrapped by
    linux_entry.ModeledRootIdentity, so the controller path records a
    MODELED_INJECTED root token in EFFECT (model record, not native proof)."""
    return lambda: linux_entry.ModeledRootIdentity(T.sim_route(k, run_id),
                                                   lambda proc: token)


def assert_next_dispatch_refused(case, run):
    """Same process (latch) AND a newly constructed controller (fresh latch,
    fresh run id, same journal scope) both refuse with zero spawn."""
    same = T.Launch(*T.world(descendant=False)[:2], latch=run.latch,
                    journal=run.journal, run_id="RUN-NEXT")
    stop = same.run()
    case.assertIn(stop.stop_id, ("SB_STOP_DISPATCH_BLOCKED", "SB_STOP_DISPATCH_JOURNAL"))
    case.assertEqual(same.popen_calls, 0)
    fresh = T.Launch(*T.world(descendant=False)[:2], journal=run.journal,
                     run_id="RUN-FRESH")
    stop = fresh.run()
    case.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
    case.assertEqual(fresh.popen_calls, 0)
    case.assertFalse(run.journal.state()["ready"])


# ---------------------------------------------------------------------------
# D1: ownership resolution before custody release / acceptance
# ---------------------------------------------------------------------------
class OwnershipResolutionTests(unittest.TestCase):

    def known_live_child(self, acquire_member):
        k, root, child = T.world(descendant=True)
        run = T.Launch(k, root, pipe_holders={root.pid})
        run.desc = child

        def hook(r):
            assert r.popen.eof(), "fixture must model legitimate EOF"
            assert child.pid in r.samplers[0].owned_identity_snapshot()
            if acquire_member:
                V.member_acquired(r)
        V.finish(run, hook=hook)
        calls = []
        with V.valid_worker(calls):
            stop = run.run()
        return run, stop, calls, child

    def test_known_live_child_refused_without_and_with_member_cap(self):
        """Pro probe normal_completion_known_live_child, corrected."""
        for acquire in (False, True):
            with self.subTest(acquire_member=acquire):
                run, stop, calls, child = self.known_live_child(acquire)
                self.assertEqual(calls, [])                 # never validated
                self.assertEqual(stop.stop_id, STOP)
                rec = stop.cleanup
                self.assertIn("KNOWN_DESCENDANT_LIVE", rec["unresolved_reasons"])
                self.assertEqual(rec["descendant_resolution"]["live"], [child.pid])
                self.assertTrue(rec["root_reaped"] and rec["pipe_eof"])
                self.assertEqual(rec["sampler_stop"]["state"], "STOPPED")
                self.assertEqual(run.k.procs[child.pid].state, "S")
                # custody retained (no fd close treated as process death)
                self.assertFalse(run.context.closed)
                self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
                self.assertGreaterEqual(len(run.route.table.held_caps()), 1 + int(acquire))
                self.assertTrue(run.latch.blocked)
                self.assertEqual(json.loads(run.raw_path.read_text()), V.WORKER_RESULT)
                with self.assertRaises(J.JournalRefused):
                    J.verify_controller_acceptance(run.output_path, run.journal)
                assert_next_dispatch_refused(self, run)

    def test_dead_descendant_control_is_accepted(self):
        """Genuinely exited known descendant: no blanket refusal."""
        for acquire in (False, True):
            with self.subTest(acquire_member=acquire):
                k, root, child = T.world(descendant=True)
                run = T.Launch(k, root)
                run.desc = child

                def hook(r):
                    if acquire:
                        V.member_acquired(r)
                    r.k.exit(child.pid, 0)
                V.finish(run, hook=hook)
                calls = []
                with V.valid_worker(calls):
                    stop = run.run()
                self.assertIsNone(stop)
                env = J.verify_controller_acceptance(run.output_path, run.journal)
                self.assertEqual(env["accepted_result"]["status"], PASS)
                self.assertTrue(run.context.closed)
                self.assertFalse(run.latch.blocked)
                self.assertTrue(run.journal.state()["ready"])

    def test_uncertain_ownership_refused(self):
        k, root, child = T.world(descendant=True)
        run = T.Launch(k, root)
        run.desc = child
        V.finish(run, hook=lambda r: r.k.exit(child.pid, 0))
        calls = []

        real = C._native_live_owned_tree

        def unknown(backend, parsed):     # only the resolution census fails
            if sys._getframe(1).f_code.co_name == "resolve_known_descendants":
                raise RuntimeError("census unreadable")
            return real(backend, parsed)
        with V.valid_worker(calls), mock.patch.object(C, "_native_live_owned_tree", unknown):
            stop = run.run()
        self.assertEqual((stop.stop_id, calls), (STOP, []))
        self.assertIn("DESCENDANT_OWNERSHIP_UNCERTAIN", stop.cleanup["unresolved_reasons"])
        self.assertFalse(run.context.closed)
        assert_next_dispatch_refused(self, run)

    def test_no_descendant_full_success(self):
        run, stop, calls = V.launch()
        self.assertIsNone(stop)
        J.verify_controller_acceptance(run.output_path, run.journal)
        self.assertEqual(run.journal.state()["history"][0]["status"], "ACCEPTED")
        second = T.Launch(*T.world(descendant=False)[:2], journal=run.journal,
                          run_id="RUN-B")
        V.finish(second)
        with V.valid_worker([]):
            self.assertIsNone(second.run())
        self.assertEqual(second.popen_calls, 1)


# ---------------------------------------------------------------------------
# D2: primary failure + secondary cleanup failure; D5: exception snapshot
# ---------------------------------------------------------------------------
def primary_then(run, second_output=None, poll_error=False):
    first = OSError(5, "PRIMARY_COLLECTOR_ERROR")
    first.output = b"valuable-only-snapshot"
    count = [0]

    def communicate(timeout=None):
        assert timeout is not None
        count[0] += 1
        if count[0] == 1:
            if poll_error:
                def poll():
                    raise OSError(5, "SECONDARY_POLL_ERROR")
                run.popen.poll = poll
            raise first
        second = OSError(5, "SECONDARY_COLLECTOR_ERROR")
        if second_output is not None:
            second.output = second_output
        raise second
    run.popen.communicate = communicate
    return count


class SecondaryCleanupFailureTests(unittest.TestCase):

    def check(self, run, stop, step):
        self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE")
        rec = stop.cleanup
        self.assertIn("PRIMARY_COLLECTOR_ERROR", rec["original_failure"])
        self.assertIn(step, [f["step"] for f in rec["secondary_failures"]])
        self.assertTrue(rec["dispatch_blocked"] and run.latch.blocked)
        self.assertIn("valuable-only-snapshot", run.log_path.read_text())
        self.assertLess(run.elapsed, C.FAILURE_CLEANUP_TOTAL_SECONDS + 1e-6)
        self.assertEqual(rec["receipt"]["final"], "STOP")
        assert_next_dispatch_refused(self, run)
        return rec

    def test_pro_probe_wait_error_after_primary(self):
        """Pro probe cleanup_secondary_error_escapes, corrected."""
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(k, eperm={root.pid}))
        primary_then(run)

        def wait_error(timeout=None):
            raise OSError(5, "SECONDARY_WAIT_ERROR")
        run.popen.wait = wait_error
        stop = run.run()
        rec = self.check(run, stop, "WAIT")
        self.assertEqual(k.procs[root.pid].state, "S")
        self.assertIn(root.pid, rec["residual_owned_targets"])
        self.assertFalse(run.context.closed)
        self.assertEqual(len(run.route.table.held_caps()), 1)   # retained, owned
        self.assertTrue(run.output_path.with_suffix(".post-spawn-cleanup.json").is_file())

    def test_poll_error_after_primary(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        primary_then(run, poll_error=True)
        self.check(run, run.run(), "POLL")

    def test_signal_port_error_after_primary(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        primary_then(run)

        def port_fails(self, signum):
            raise RuntimeError("SECONDARY_SIGNAL_PORT_ERROR")
        with mock.patch.object(C.RunContext, "root_signal", port_fails):
            stop = run.run()
        self.check(run, stop, "SIGNAL_PORT")

    def test_collector_helper_error_after_primary(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        primary_then(run)
        real = C._bounded_collect

        def collect(process, budget, collector=None, phase=""):
            if phase == "FAILURE_CLEANUP":
                raise RuntimeError("SECONDARY_COLLECT_HELPER_ERROR")
            return real(process, budget, collector, phase)
        with mock.patch.object(C, "_bounded_collect", collect):
            stop = run.run()
        rec = self.check(run, stop, "COLLECTOR")
        self.assertFalse(rec["output_complete"])

    def test_sampler_stop_error_after_primary(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        primary_then(run)

        def stop_fails(sampler, budget):
            raise RuntimeError("SECONDARY_SAMPLER_STOP_ERROR")
        with mock.patch.object(C, "_stop_sampler_bounded", stop_fails):
            stop = run.run()
        rec = self.check(run, stop, "SAMPLER_STOP")
        self.assertFalse(rec["sampler_stopped"])

    def test_secondary_plus_evidence_persistence_failure(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(k, eperm={root.pid}))
        primary_then(run)

        def wait_error(timeout=None):
            raise OSError(5, "SECONDARY_WAIT_ERROR")
        run.popen.wait = wait_error
        with mock.patch.object(C, "write_canonical_json",
                               V.failing_under(run.tmp / "out", C.write_canonical_json)), \
                mock.patch.object(C, "_write_log", side_effect=OSError(28, "log ENOSPC")):
            stop = run.run()
        rec = stop.cleanup
        self.assertIn("SECONDARY_WAIT_ERROR", json.dumps(rec["secondary_failures"]))
        self.assertIn("evidence_write_failure", rec)
        self.assertTrue(run.latch.blocked)
        # D5: log write failed, but the snapshot is kept in memory evidence
        self.assertEqual(rec["output_contract"]["chars"], len("valuable-only-snapshot"))
        assert_next_dispatch_refused(self, run)

    def test_cleanup_protocol_escape_is_contained(self):
        """Even if the whole cleanup protocol raises, containment latches."""
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        primary_then(run)
        with mock.patch.object(C, "_bounded_failure_cleanup",
                               side_effect=RuntimeError("CLEANUP_PROTOCOL_BUG")):
            stop = run.run()
        rec = stop.cleanup
        self.assertEqual(rec["schema"], "SplitAlignerR/ENGINE003ContainedCleanupEscape/v1")
        self.assertIn("PRIMARY_COLLECTOR_ERROR", rec["original_failure"])
        self.assertTrue(rec["ownership_retained"] and run.latch.blocked)
        self.assertEqual(len(rec["residual_custody_held"]), 1)
        assert_next_dispatch_refused(self, run)

    def test_interrupt_during_cleanup_stays_interrupt(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(k, eperm={root.pid}))
        primary_then(run)

        def wait_interrupt(timeout=None):
            raise KeyboardInterrupt()
        run.popen.wait = wait_interrupt
        with self.assertRaises(KeyboardInterrupt) as caught:
            run.run()
        self.assertTrue(caught.exception.cleanup["dispatch_blocked"])
        self.assertTrue(run.latch.blocked)
        assert_next_dispatch_refused(self, run)


class WatchdogSnapshotTests(unittest.TestCase):
    """D5 at the outer watchdog exception entry."""

    def run_case(self, first_output, second_output=None, log_fails=False):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        first = OSError(5, "watchdog collector EIO")
        if first_output is not None:
            first.output = first_output
        count = [0]

        def communicate(timeout=None):
            count[0] += 1
            if count[0] == 1:
                raise first
            second = OSError(5, "cleanup collector EIO")
            if second_output is not None:
                second.output = second_output
            raise second
        run.popen.communicate = communicate
        if log_fails:
            with mock.patch.object(C, "_write_log", side_effect=OSError(28, "log ENOSPC")):
                stop = run.run()
        else:
            stop = run.run()
        return run, stop

    def test_pro_probe_snapshot_kept(self):
        run, stop = self.run_case(b"valuable-only-snapshot")
        self.assertEqual(run.log_path.read_text(), "valuable-only-snapshot")
        self.assertFalse(stop.cleanup["output_contract"]["complete"])
        self.assertTrue(run.latch.blocked or run.journal.state()["ready"] is False)

    def test_text_empty_none_repeated(self):
        for first, second, want in [("text-snap", None, "text-snap"),
                                    (b"", None, ""), (None, None, ""),
                                    (b"abc", b"abcdef", "abcdef"),
                                    (b"abc", b"abc", "abc")]:
            with self.subTest(first=first, second=second):
                run, stop = self.run_case(first, second)
                self.assertEqual(run.log_path.read_text(), want)   # no dup prefix
                self.assertFalse(stop.cleanup["output_contract"]["complete"])

    def test_first_payload_second_none_plus_log_failure(self):
        run, stop = self.run_case(b"valuable-only-snapshot", None, log_fails=True)
        rec = stop.cleanup
        self.assertEqual(rec["output_contract"]["chars"], len("valuable-only-snapshot"))
        self.assertIn("evidence_write_failure", rec)
        self.assertFalse(rec["output_contract"]["complete"])
        self.assertTrue(run.latch.blocked)


# ---------------------------------------------------------------------------
# D3: acquisition in the same custody ledger
# ---------------------------------------------------------------------------
class AcquisitionLedgerTests(unittest.TestCase):

    def ctx(self, **port_kwargs):
        k, root, _ = T.world(descendant=False)
        route = T.sim_route(k, **port_kwargs)
        ctx = T.context_for(k, T.make_backend(k), route)
        ctx.admit()
        return k, root, route, ctx

    def test_failed_open_no_handle(self):
        k, root, route, ctx = self.ctx()
        with mock.patch.object(route.port, "open", side_effect=OSError(24, "EMFILE")):
            with self.assertRaises(OSError):
                route.table.acquire(root.pid, "ROOT", T.ident(root), "P", None)
        row = route.table.report()["capabilities"][0]
        self.assertEqual(row["state"], termination.OPEN_FAILED)
        self.assertIn("EMFILE", row["acquisition"]["open_error"])
        self.assertEqual(ctx.close(), "CLOSED")

    def test_verify_reject_rollback_close_ok_and_eio(self):
        """Pro probe acquisition_reject_close_error_untracked, corrected."""
        for close_errors in ({}, {3: OSError(5, "injected close EIO")}):
            with self.subTest(close_errors=bool(close_errors)):
                k, root, route, ctx = self.ctx(close_errors=close_errors)

                def reject(handle):
                    raise T.Refused(1, "POST_OPEN_IDENTITY_MISMATCH")
                with self.assertRaises(T.Refused) as caught:  # verify error primary
                    route.table.acquire(root.pid, "ROOT", T.ident(root), "P", reject)
                self.assertIn("POST_OPEN_IDENTITY_MISMATCH", str(caught.exception))
                row = route.table.report()["capabilities"][0]
                self.assertIn("POST_OPEN_IDENTITY_MISMATCH", row["acquisition"]["verify_error"])
                closes = [c for c in route.port.calls if c[0] == "close"]
                self.assertEqual(len(closes), 1)                  # exactly once
                out = ctx.close()
                if close_errors:
                    self.assertEqual(row["state"], termination.CLOSE_FAILED)
                    self.assertIn("EIO", row["close_error"])
                    self.assertFalse(ctx.closed)
                    self.assertNotEqual(out, "CLOSED")
                    ctx.close()
                    self.assertEqual(len([c for c in route.port.calls
                                          if c[0] == "close"]), 1)  # never retried
                else:
                    self.assertEqual(row["state"], termination.CLOSED)
                    self.assertEqual(out, "CLOSED")

    def test_teardown_during_verify_not_all_closed(self):
        """Pro probe inflight_open_not_counted_by_teardown, corrected."""
        for close_errors in ({}, {3: OSError(5, "rollback close EIO")}):
            with self.subTest(close_errors=bool(close_errors)):
                k, root, route, ctx = self.ctx(close_errors=close_errors)
                seen = {}

                def teardown_during_verify(handle):
                    seen["close"] = ctx.close()
                    seen["custody"] = ctx.custody
                with self.assertRaises(OSError):
                    route.table.acquire(root.pid, "ROOT", T.ident(root), "P",
                                        teardown_during_verify)
                self.assertFalse(seen["custody"]["resolved"])
                self.assertEqual(len(seen["custody"]["acquisitions_in_flight"]), 1)
                self.assertNotEqual(seen["close"], "CLOSED")
                row = route.table.report()["capabilities"][0]
                self.assertEqual(row["acquisition"]["rollback_reason"],
                                 "LATE_RETURN_AFTER_INVALIDATION")
                final = ctx.close()
                self.assertEqual(final == "CLOSED", not close_errors)

    def test_teardown_at_open_boundary_and_late_return(self):
        k, root, route, ctx = self.ctx()
        seen = {}
        real_open = route.port.open

        def open_with_teardown(pid):
            seen["close"] = ctx.close()          # teardown while open in flight
            seen["custody"] = ctx.custody
            return real_open(pid)                # late return
        with mock.patch.object(route.port, "open", open_with_teardown):
            with self.assertRaises(OSError):
                route.table.acquire(root.pid, "ROOT", T.ident(root), "P", None)
        self.assertFalse(seen["custody"]["resolved"])
        self.assertEqual(seen["custody"]["acquisitions_in_flight"][0]["state"],
                         termination.ACQUIRING)
        self.assertEqual(ctx.close(), "CLOSED")          # late handle closed once
        self.assertEqual(len([c for c in route.port.calls if c[0] == "close"]), 1)

    def test_teardown_at_register_boundary_and_no_presignal(self):
        k, root, route, ctx = self.ctx()
        table = route.table
        seen = {}

        def point(name, cap):
            if name == "ACQUIRE_OPENED":
                with self.assertRaises(OSError):         # no SIGNAL pre-verify
                    table.signal(cap, T.KILL, table.binding)
            if name == "ACQUIRE_VERIFIED":
                seen["close"] = ctx.close()
        table.schedule_point = point
        with self.assertRaises(OSError):
            table.acquire(root.pid, "ROOT", T.ident(root), "P", lambda h: None)
        table.schedule_point = None
        self.assertNotEqual(seen["close"], "CLOSED")
        self.assertEqual([c for c in route.port.calls if c[0] == "signal"], [])
        self.assertEqual(ctx.close(), "CLOSED")

    def test_registered_lease_and_borrowed_restrictions_preserved(self):
        k, root, route, ctx = self.ctx()
        cap = route.table.acquire(root.pid, "ROOT", T.ident(root), "P", lambda h: None)
        view = route.table.borrowed_view(cap)
        with self.assertRaises(OSError):
            route.table.signal(view, T.KILL, route.table.binding)
        with route.table.lease(cap, termination.SIGNAL_OP, route.table.binding):
            self.assertNotEqual(ctx.close(), "CLOSED")   # deferred while leased
        self.assertEqual(ctx.close(), "CLOSED")


# ---------------------------------------------------------------------------
# D4: raw evidence vs controller records vs acceptance
# ---------------------------------------------------------------------------
class EvidenceSeparationTests(unittest.TestCase):

    def unresolved(self, **patches):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, stuck_sampler=True)
        V.finish(run)
        calls = []
        replace_calls = []

        def replace(a, b):
            replace_calls.append((a, b))
            raise OSError(5, "injected move EIO")
        ctx = [V.valid_worker(calls), mock.patch.object(C.os, "replace", replace)]
        for target, name, value in patches.get("extra", []):
            ctx.append(mock.patch.object(target, name, value))
        for c in ctx:
            c.__enter__()
        try:
            stop = run.run()
        finally:
            for c in reversed(ctx):
                c.__exit__(None, None, None)
        self.assertEqual((stop.stop_id, calls), (STOP, []))
        self.assertEqual(replace_calls, [])                  # no raw move attempted
        self.assertEqual(json.loads(run.raw_path.read_text()), V.WORKER_RESULT)
        self.assertEqual(stop.cleanup["raw_worker_result_sha256"],
                         J.sha256(run.raw_path.read_bytes()))
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(run.output_path, run.journal)
        assert_next_dispatch_refused(self, run)
        return run, stop

    def test_pro_probe_move_failure_raw_preserved(self):
        self.unresolved()

    def test_stop_write_failure_raw_preserved(self):
        real = C.journal_protocol.publish_no_clobber

        def fail_stop_record(path, data):
            if Path(path).name == "result.json":
                raise OSError(28, "stop record ENOSPC")
            return real(path, data)
        run, stop = self.unresolved(extra=[
            (C.journal_protocol, "publish_no_clobber", fail_stop_record)])
        self.assertIn("STOP_RECORD", json.dumps(stop.cleanup["evidence_write_failure"]))

    def test_partial_truncating_stop_write_raw_preserved(self):
        real = C.journal_protocol.publish_no_clobber

        def truncating(path, data):
            Path(path).write_bytes(data[:7])
            raise OSError(28, "ENOSPC after partial write")
        run, stop = self.unresolved(extra=[(C.journal_protocol, "publish_no_clobber",
                                            truncating)])
        self.assertIs(C.journal_protocol.publish_no_clobber, real)
        self.assertEqual(len(run.output_path.read_bytes()), 7)   # corrupt stop rec
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(run.output_path, run.journal)

    def test_log_failure_raw_preserved(self):
        run, stop = self.unresolved(extra=[(C, "_write_log",
                                            mock.Mock(side_effect=OSError(28, "log")))])
        self.assertIn("LOG", json.dumps(stop.cleanup["evidence_write_failure"]))

    def test_acceptance_publish_failure_no_acceptance(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        V.finish(run)
        with V.valid_worker([]), mock.patch.object(
                C.journal_protocol, "publish_no_clobber",
                side_effect=OSError(28, "acceptance ENOSPC")):
            stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_ACCEPTANCE_PUBLICATION")
        self.assertFalse(run.output_path.exists())
        self.assertEqual(json.loads(run.raw_path.read_text()), V.WORKER_RESULT)
        # FIX003: the CLEANUP record is persisted before the envelope
        self.assertEqual(stop.cleanup["receipt"]["completed_in_order"],
                         ["PROGRESSION_RESERVED_PUBLISHED", "JOURNAL_IN_FLIGHT_PUBLISHED",
                          "TICKET_CHECKED_BEFORE_SPAWN",       # FIX005
                          "JOURNAL_EFFECT_IDENTITY_PUBLISHED",  # NRP-2
                          "JOURNAL_CLEANUP_RECORD_PUBLISHED",
                          "COORDINATOR_CURRENT_BINDING_VERIFIED",   # FIX005
                          "JOURNAL_FINAL_STOP_PUBLISHED"])
        assert_next_dispatch_refused(self, run)

    def test_journal_final_failure_envelope_not_trusted(self):
        storage = J.MemoryStorage()
        j = journal(storage)
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, journal=j)
        V.finish(run)
        storage.fail[("create", "000001.FINAL")] = OSError(5, "journal EIO")
        with V.valid_worker([]):
            stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_ACCEPTANCE_PUBLICATION")
        self.assertTrue(run.output_path.exists())            # envelope written...
        with self.assertRaises(J.JournalRefused) as caught:  # ...but not trusted
            J.verify_controller_acceptance(run.output_path, j)
        self.assertEqual(caught.exception.code, "ACCEPTANCE_NOT_JOURNALED")
        del storage.fail[("create", "000001.FINAL")]
        assert_next_dispatch_refused(self, run)

    def test_raw_pass_alone_is_not_acceptance(self):
        tmp = Path(tempfile.mkdtemp(prefix="fix002_"))
        raw = tmp / "result.json"
        raw.write_text(json.dumps(V.WORKER_RESULT))
        with self.assertRaises(J.JournalRefused) as caught:
            J.verify_controller_acceptance(raw, journal())
        self.assertEqual(caught.exception.code, "NOT_A_CONTROLLER_ACCEPTANCE")

    def test_tampered_raw_breaks_acceptance(self):
        run, stop, calls = V.launch()
        self.assertIsNone(stop)
        run.raw_path.write_text(json.dumps(dict(V.WORKER_RESULT, extra=1)))
        with self.assertRaises(J.JournalRefused) as caught:
            J.verify_controller_acceptance(run.output_path, run.journal)
        self.assertEqual(caught.exception.code, "RAW_WORKER_BYTES_MISMATCH")


# ---------------------------------------------------------------------------
# Journal model: scope, refusal, crash cuts, reconciliation
# ---------------------------------------------------------------------------
class DispatchJournalTests(unittest.TestCase):

    def launch_with(self, j, run_id="RUN-J"):
        run = T.Launch(*T.world(descendant=False)[:2], journal=j, run_id=run_id)
        V.finish(run)
        with V.valid_worker([]):
            stop = run.run()
        return run, stop

    def test_absent_scope_is_not_success(self):
        run, stop = self.launch_with(journal(init=False))
        self.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertIn("SCOPE_NOT_INITIALIZED", stop.detail)
        self.assertEqual(run.popen_calls, 0)

    def test_journal_required(self):
        run = T.Launch(*T.world(descendant=False)[:2])
        run.journal = None
        self.assertEqual(run.run().stop_id, "SB_STOP_DISPATCH_JOURNAL")
        self.assertEqual(run.popen_calls, 0)

    def test_in_flight_publish_failure_zero_spawn(self):
        for fail in ({("create", "000001.IN_FLIGHT"): OSError(28, "ENOSPC")},
                     {("list", ""): OSError(5, "EIO")}):
            with self.subTest(fail=list(fail)):
                storage = J.MemoryStorage()
                j = journal(storage)
                storage.fail.update(fail)
                run, stop = self.launch_with(j)
                self.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
                self.assertEqual(run.popen_calls, 0)
                self.assertFalse(run.raw_path.exists())

    def test_existing_scope_states_refuse(self):
        def flight(j, seq=1, run_id="R1"):
            return j._record("IN_FLIGHT", seq=seq, run_id=run_id)
        cases = {
            "IN_FLIGHT": lambda j, s: s.create_new("000001.IN_FLIGHT", flight(j)),
            # FIX001: finish() refuses to write into a scope without the
            # reservation, so the fixture writes the STOP bytes directly
            "STOP": lambda j, s: (s.create_new("000001.IN_FLIGHT", flight(j)),
                                  s.create_new("000001.FINAL", j._record(
                                      "FINAL", seq=1, run_id="R1", status="STOP",
                                      reason="x", flight_sha256=J.sha256(
                                          s.records["000001.IN_FLIGHT"])))),
            "CORRUPT": lambda j, s: s.create_new("000001.IN_FLIGHT", b"{trunc"),
            "UNKNOWN_STATUS": lambda j, s: (
                s.create_new("000001.IN_FLIGHT", flight(j)),
                s.create_new("000001.FINAL", j._record("FINAL", seq=1, run_id="R1",
                                                       status="MAYBE"))),
            "LOST_GAP": lambda j, s: s.create_new("000002.IN_FLIGHT", flight(j, 2)),
            "UNKNOWN_RECORD": lambda j, s: s.create_new("stray", b"x"),
            "ANCHOR_LOST": lambda j, s: (s.create_new("000001.IN_FLIGHT", flight(j)),
                                         s.records.pop("ANCHOR")),
            "FOREIGN_SCOPE": lambda j, s: s.records.__setitem__(
                "ANCHOR", J.canonical({"schema": J.JOURNAL_SCHEMA, "scope_id": "x"})),
        }
        for name, prepare in cases.items():
            with self.subTest(case=name):
                storage = J.MemoryStorage()
                j = journal(storage)
                prepare(j, storage)
                rebuilt = journal(storage, init=False)     # new controller
                self.assertFalse(rebuilt.state()["ready"])
                run, stop = self.launch_with(rebuilt, run_id="RUN-NEW-ID")
                self.assertEqual(stop.stop_id, "SB_STOP_DISPATCH_JOURNAL")
                self.assertEqual(run.popen_calls, 0)
        storage = J.MemoryStorage()
        journal(storage)
        storage.fail[("read", "ANCHOR")] = OSError(5, "EIO")
        self.assertEqual(journal(storage, init=False).state()["reason"],
                         "RECORD_UNREADABLE")
        with self.assertRaises(J.JournalRefused):     # no silent re-init
            journal(storage, init=False).initialize_scope()

    def test_crash_cut_at_each_durable_boundary(self):
        """Durable creates in a success: ANCHOR, IN_FLIGHT, envelope (file),
        FINAL.  Cut after each; a rebuilt controller refuses unless the
        whole sequence completed, which it recognizes as ACCEPTED."""
        # FIX005: creates are ANCHOR, IN_FLIGHT, CLEANUP (prepared), FINAL
        # (commit); the ticket check re-reads the journal before spawn and
        # the commit re-reads it after FINAL.  Cut 2 lands after the
        # reservation but before spawn: it must refuse (no permission is
        # inferred from "no spawn").  Cut 4 lands after a correct commit
        # (lost return): committed and recoverable by the same ticket.
        # DEV_PHASE_EVIDENCE001: the journal mirror of the effect-handoff slot
        # (PHASE, before spawn) is one more create: ANCHOR, IN_FLIGHT, PHASE,
        # CLEANUP, FINAL.  Cut 3 lands after the handoff (spawned, refuses);
        # the lost-return cut moves from 4 to 5.
        # NRP-2: the post-spawn identity record (EFFECT, after attach_root,
        # before the sampler) is one more create: ANCHOR, IN_FLIGHT, PHASE,
        # EFFECT, CLEANUP, FINAL.  Cut 4 lands after EFFECT (spawned,
        # refuses); the lost-return cut moves from 5 to 6.
        outcomes = []
        for cut in range(1, 8):          # counted in the journal MemoryStorage
            storage = J.MemoryStorage()
            _PROGRESSION.pop(id(storage), None)   # id() may be reused after GC
            j = journal(storage)                     # 1 create (ANCHOR)
            storage.crash_after = cut
            run = T.Launch(*T.world(descendant=False)[:2], journal=j)
            V.finish(run)
            try:
                with V.valid_worker([]):
                    stop = run.run()
                crashed = False
            except J.CrashCut:
                crashed, stop = True, None
            storage.crash_after = None
            state = journal(storage, init=False).state()
            outcomes.append((cut, crashed, run.popen_calls, state["ready"]))
            if crashed and state["ready"] and cut == 6:
                self.assertEqual(state["history"][0]["status"], "ACCEPTED")
                rebuilt_j = journal(storage, init=False)
                rec = J.recover_committed_dispatch(
                    rebuilt_j, 1,
                    request_sha256=rebuilt_j.load_ticket(1).request_sha256,
                    output_path=run.output_path)
                self.assertEqual(rec["accepted_result"]["status"], V.PASS)
            elif crashed and run.popen_calls == 0 and cut == 1:
                # FIX003: the journal-store cut 1 lands on begin's first read,
                # before RESERVED: nothing durable, so READY is correct.  The
                # cut after RESERVED (interrupted begin, REFUSES) is covered by
                # test_dev007_fix003.ProgressionTests.test_crash_cut_at_every_durable_boundary
                self.assertTrue(state["ready"])
                self.assertFalse(run.raw_path.exists())
            elif crashed:
                self.assertFalse(state["ready"])
                again = T.Launch(*T.world(descendant=False)[:2],
                                 journal=journal(storage, init=False), run_id="RUN-R")
                self.assertEqual(again.run().stop_id, "SB_STOP_DISPATCH_JOURNAL")
                self.assertEqual(again.popen_calls, 0)
                self.assertEqual(json.loads(run.raw_path.read_text()), V.WORKER_RESULT) \
                    if run.raw_path.exists() else None
            else:
                self.assertIsNone(stop)
                self.assertTrue(state["ready"])
                self.assertEqual(state["history"][0]["status"], "ACCEPTED")
        self.assertEqual(outcomes, [(1, True, 0, True), (2, True, 0, False),
                                    (3, True, 1, False), (4, True, 1, False),
                                    (5, True, 1, False), (6, True, 1, True),
                                    (7, False, 1, True)])
        # a crash between the (file) envelope and the journal FINAL:
        storage = J.MemoryStorage()
        j = journal(storage)
        run = T.Launch(*T.world(descendant=False)[:2], journal=j)
        V.finish(run)
        storage.fail[("create", "000001.FINAL")] = J.CrashCut("after envelope")
        with self.assertRaises(J.CrashCut), V.valid_worker([]):
            run.run()
        del storage.fail[("create", "000001.FINAL")]
        self.assertTrue(run.output_path.exists())
        self.assertFalse(journal(storage, init=False).state()["ready"])
        with self.assertRaises(J.JournalRefused):
            J.verify_controller_acceptance(run.output_path, journal(storage, init=False))

    def test_reconciliation_rules(self):
        # NRP-2 FIX001 re-specification (Astra recorded-identity decision):
        # the FIX002/FIX003 rules below are asserted twice.  (1) An
        # identity-less provider (the plain simulated route; every current
        # real provider): all old refusals hold AND the formerly accepted
        # complete reconciliation is now refused NO_RECORDED_IDENTITY (no
        # positive post-effect path), durable records unchanged.  (2) A
        # modeled provider that records a root token: the same refusals hold
        # and the complete reconciliation citing that token is accepted
        # (the original positive assertion, unchanged).
        for modeled in (False, True):
            with self.subTest(modeled_identity=modeled):
                k, root, child = T.world(descendant=True)
                run = T.Launch(k, root, pipe_holders={root.pid},
                               route_factory=(modeled_route_factory(k, "RUN-A")
                                              if modeled else None))
                run.desc = child
                V.finish(run)
                with V.valid_worker([]):
                    stop = run.run()
                self.assertEqual(stop.stop_id, STOP)
                j = run.journal
                token = json.loads(j.storage.records["000001.EFFECT"])["evidence"]["identity"]
                self.assertEqual(token, {"token": MODELED_TOKEN,
                                         "provenance": "MODELED_INJECTED"}
                                 if modeled else None)
                # FIX003: the FIX002 free-form resolved_facts format is refused
                with self.assertRaises(J.JournalRefused):
                    j.reconcile(1, "RUN-A", {"cited_run_id": "RUN-A", "resolved_facts": [
                        {"kind": "NUMERIC_PID_ABSENT", "pid": child.pid}]})
                with self.assertRaises(J.JournalRefused):
                    j.reconcile(1, "RUN-OTHER", reconciliation(j, "RUN-OTHER"))
                with self.assertRaises(J.JournalRefused):
                    j.reconcile(1, "RUN-A", {"cited_run_id": "RUN-A", "resolved_facts": [
                        {"kind": "OPERATOR_VERIFIED_IDENTITY_EXIT",
                         "identity": T.itext(child)}]})
                self.assertFalse(j.state()["ready"])
                if not modeled:
                    before = dict(j.storage.records)
                    with self.assertRaises(J.JournalRefused) as caught:
                        j.reconcile(1, "RUN-A", reconciliation(j, "RUN-A"))
                    self.assertEqual(str(caught.exception),
                                     "RECONCILIATION_INVALID:ROOT_PROCESS:"
                                     "NO_RECORDED_IDENTITY:EFFECT_RECORD")
                    self.assertEqual(dict(j.storage.records), before)
                    self.assertFalse(j.state()["ready"])
                    continue
                j.reconcile(1, "RUN-A", reconciliation(j, "RUN-A"))
                self.assertEqual(j.state()["history"][0]["status"], "RECONCILED")

    def test_file_storage_no_clobber(self):
        tmp = Path(tempfile.mkdtemp(prefix="fix002_fs_"))
        fs = J.FileStorage(tmp)
        fs.create_new("A", b"1")
        with self.assertRaises(FileExistsError):
            fs.create_new("A", b"2")
        self.assertEqual(fs.read("A"), b"1")
        self.assertEqual(fs.list(), ["A"])
        self.assertFalse(J.NATIVE_STORAGE_QUALIFIED)


# ---------------------------------------------------------------------------
# Coupled protocol: timeout phase metadata, single deadline, CLI tail
# ---------------------------------------------------------------------------
class ProtocolCouplingTests(unittest.TestCase):

    def test_timeout_phase_snapshot_receipt_and_journal_stop(self):
        k, root, desc = T.world()
        run = T.Launch(k, root)
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        ev = run.evidence()
        self.assertEqual(ev["termination_phase"],
                         "PHASE_SNAPSHOT_BEFORE_TIMEOUT_STOP_LOG_WRITE")
        self.assertEqual(ev["final_output_receipt"]["phase"], "AFTER_TIMEOUT_STOP_LOG_WRITE")
        self.assertEqual(ev["final_output_receipt"]["persisted_logs"][-1]["phase"],
                         "TIMEOUT_STOP_EVIDENCE")
        self.assertEqual(ev["dispatch_journal_final"], "NOT_PUBLISHED_AT_THIS_WRITE")
        self.assertEqual(stop.cleanup["receipt"]["completed_in_order"],
                         ["PROGRESSION_RESERVED_PUBLISHED", "JOURNAL_IN_FLIGHT_PUBLISHED",
                          "TICKET_CHECKED_BEFORE_SPAWN",       # FIX005
                          "JOURNAL_EFFECT_IDENTITY_PUBLISHED",  # NRP-2
                          "JOURNAL_FINAL_STOP_PUBLISHED"])
        # resolved timeout: no in-memory latch, but the durable STOP refuses
        self.assertFalse(run.latch.blocked)
        self.assertEqual(run.journal.state()["reason"], "PRIOR_DISPATCH_STOPPED_UNRECONCILED")
        assert_next_dispatch_refused(self, run)

    def test_completion_exception_reuses_the_one_deadline(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        V.finish(run)

        def stop_fails(sampler, budget):
            raise RuntimeError("SAMPLER_STOP_HELPER_BUG")
        with V.valid_worker([]), mock.patch.object(C, "_stop_sampler_bounded", stop_fails):
            stop = run.run()
        rec = stop.cleanup
        self.assertIn("COMPLETION_CLEANUP", rec["original_failure"])
        self.assertEqual(rec["cleanup_deadline"]["label"], "COMPLETION_CLEANUP")
        starts = [e for e in run.context.evidence if e["kind"] == "DEADLINE_START"]
        self.assertEqual(len(starts), 1)                 # never reset
        self.assertIn("SAMPLER_STOP", [f["step"] for f in rec["secondary_failures"]])
        assert_next_dispatch_refused(self, run)

    def test_main_never_rewrites_published_envelope(self):
        envelope = {"status": "CONTROLLER_ACCEPTED",
                    "accepted_result": {"status": PASS}}
        seen = {}

        def launch(*args, **kwargs):
            seen.update(kwargs)
            return envelope
        argv = ["x", "--repo-root", "r", "--runtime-root", "r", "--resource", "a",
                "--branch-resource", "b", "--durability", "d", "--request", "q",
                "--output", "o", "--log", "l"]
        with mock.patch.object(C, "launch_request", launch), \
                mock.patch.object(C, "strict_json_load", return_value={}), \
                mock.patch.object(C, "write_canonical_json") as write, \
                mock.patch.object(sys, "argv", argv), \
                mock.patch("builtins.print"):
            C.main()
        write.assert_not_called()
        self.assertIsNone(seen["dispatch_journal"])      # default: refuses in launch


if __name__ == "__main__":
    unittest.main()
