"""DEV007 regressions for Astra A006-1..A006-4 (pure simulation only).

A006-1  complete custody teardown on every resolved exit; retained + latched
        otherwise; idempotent, owner-bound close; root/member outcomes apart.
A006-2  single-use admission before any spawn; one protected post-spawn
        region for every exit (acquisition, sampler construction/start/
        runtime/stop, collector, validation) through launch_request.
A006-3  validate+lease is one transition; deterministic interleavings on a
        faithful fd table (signal/close resolve the number only).
A006-4  cumulative output contract: no duplicated or dropped bytes.

FakeKernel, virtual-time FakePopen, SimulatedObjectSignalPort over FdPool,
FakeSamplerThread. No fork, pidfd, signal or host /proc read.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_dev007
"""
import inspect
import os
import sys
import threading
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import termination  # noqa: E402
import test_dev006 as T  # noqa: E402
from synthetic import SimulatedObjectSignalPort, advance  # noqa: E402
from test_controller_dispatch import load_bundled  # noqa: E402

C, Refused, TERM, KILL = T.C, T.Refused, T.TERM, T.KILL
BIND = ("RUN-A", "OWNER", 1)


def closes(port):
    return [c for c in port.calls if c[0] == "close"]


def signals(port):
    return [c for c in port.calls if c[0] == "signal"]


def completed(run, text="complete output", code=0):
    """communicate() completes normally: the worker exits within the watchdog."""
    def communicate(timeout=None):
        run.popen.calls.append(("communicate", timeout))
        if run.k.procs[run.root.pid].state != "Z":
            run.k.exit(run.root.pid, code)
        run.popen.poll()
        run.popen.output = text
        return text, None
    run.popen.communicate = communicate


def sampler_factory(k, made, *, start_error=None, construct_error=None,
                    runtime_error=None, stuck=False):
    base = T.manual_sampler_factory(k, stuck, made=made)

    def factory(pid, native_backend=None):
        if construct_error is not None:
            raise construct_error
        sampler = base(pid, native_backend=native_backend)
        real_start = sampler.start

        def start():
            real_start()
            if runtime_error is not None:
                sampler.error = runtime_error
            if start_error is not None:
                sampler._thread.alive = False     # thread never ran
                raise start_error
        sampler.start = start
        return sampler
    return factory


class LaunchWith(T.Launch):
    """T.Launch with an injectable sampler factory."""

    def __init__(self, *a, sampler_factory=None, **kw):
        super().__init__(*a, **kw)
        self._sampler_factory = sampler_factory

    def run(self):
        if self._sampler_factory is None:
            return super().run()
        with mock.patch.object(T, "manual_sampler_factory",
                               lambda *a, **kw: self._sampler_factory):
            return super().run()


# ---------------------------------------------------------------------------
# A006-1: complete custody closure
# ---------------------------------------------------------------------------

class CustodyClosureTests(unittest.TestCase):

    def test_normal_timeout_closes_root_and_member_independently(self):
        k, root, desc = T.world()
        run = T.Launch(k, root)
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        term = run.evidence()["termination"]
        self.assertTrue(term["whole_process_tree_quiescent"])
        self.assertEqual(term["custody_close_outcome"], "CLOSED")
        self.assertTrue(term["context_closed"] and run.context.closed)
        custody = term["custody"]
        self.assertEqual([(r["pid"], r["state"], r["close_outcome"]) for r in custody["root"]],
                         [(root.pid, "CLOSED", "CLOSED")])
        self.assertEqual([(r["pid"], r["state"], r["close_outcome"]) for r in custody["members"]],
                         [(desc.pid, "CLOSED", "CLOSED")])
        self.assertEqual(run.route.table.held_caps(), [])
        self.assertEqual(run.route.port.fd_pool.used, set())
        self.assertEqual(sorted((c[1], c[2]) for c in closes(run.route.port)),
                         [(root.pid, 3), (desc.pid, 4)])
        self.assertFalse(run.latch.blocked or term["dispatch_blocked"])
        # idempotent: no second provider close, context stays closed
        self.assertEqual(run.context.close(), "ALREADY_CLOSED")
        self.assertEqual(len(closes(run.route.port)), 2)
        with self.assertRaisesRegex(Refused, "RUN_CONTEXT_CLOSED"):
            run.context.group_signal(root.pid, KILL, {})

    def test_normal_completion_closes_context(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        completed(run)
        stop = run.run()
        # stubbed worker result is not a PASS -> validation stop, custody closed
        self.assertEqual((stop.stop_id, stop.detail), ("SB_STOP_VALIDATION", "worker_result_identity"))
        self.assertEqual(stop.cleanup["custody_close_outcome"], "CLOSED")
        self.assertTrue(run.context.closed)
        self.assertEqual(run.route.table.held_caps(), [])
        self.assertFalse(run.latch.blocked)
        self.assertEqual(run.log_path.read_text(), "complete output")

    def test_member_close_failure_keeps_context_open_and_blocks(self):
        k, root, desc = T.world()
        run = T.Launch(k, root, route_factory=lambda: T.sim_route(
            k, close_errors={4: OSError(5, "fake close EIO")}))
        stop = run.run()
        term = stop.cleanup
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertTrue(term["custody_close_outcome"].startswith("CUSTODY_UNRESOLVED"))
        self.assertFalse(run.context.closed)
        self.assertIn("CUSTODY_NOT_CLOSED", term["unresolved_reasons"])
        self.assertTrue(run.latch.blocked)
        self.assertEqual([r["state"] for r in term["custody"]["root"]], ["CLOSED"])
        self.assertEqual([r["state"] for r in term["custody"]["members"]], ["CLOSE_FAILED"])
        # never retried (the number may already name something else)
        port = run.route.port
        n = len(closes(port))
        other = port.open(k.spawn(1).pid)            # an unrelated process
        self.assertEqual(other.fd, 3)                # lowest free number
        self.assertIn("CUSTODY_UNRESOLVED", run.context.close())
        self.assertEqual(len(closes(port)), n)
        self.assertIn(other.fd, port.fd_pool.used)

    def test_close_while_lease_held_is_not_success_then_resolves(self):
        k, root, _ = T.world(descendant=False)
        route = T.sim_route(k)
        ctx = T.context_for(k, T.make_backend(k), route)
        ctx.attach_root(T.FakePopen(k, root.pid))
        seen = {}

        def during(name, cap):
            if name == "LEASED" and "close" not in seen:
                seen["close"] = ctx.close()          # teardown during the op
                seen["closed_flag"] = ctx.closed
        route.table.schedule_point = during
        ctx.root_signal(TERM)                        # in-flight op completes
        self.assertTrue(seen["close"].startswith("CUSTODY_UNRESOLVED"))
        self.assertFalse(seen["closed_flag"])
        self.assertEqual(T.delivered(route.port), [(root.pid, TERM)])
        # the deferred provider close ran exactly once, after the effect
        self.assertEqual([(c[1], c[2]) for c in closes(route.port)], [(root.pid, 3)])
        self.assertLess(route.port.calls.index(signals(route.port)[0]),
                        route.port.calls.index(closes(route.port)[0]))
        with self.assertRaisesRegex(Refused, "RUN_CONTEXT_TEARDOWN_STARTED"):
            ctx.root_signal(KILL)                    # no new operation
        self.assertEqual(ctx.close(), "CLOSED")      # re-evaluated, now resolved
        self.assertEqual(len(closes(route.port)), 1)

    def test_foreign_context_cannot_teardown_route(self):
        k, root, desc = T.world()
        b = T.make_backend(k)
        route = T.sim_route(k)
        ctx = T.context_for(k, b, route)
        ctx.attach_root(T.FakePopen(k, root.pid))
        foreign = T.context_for(k, b, route)
        self.assertTrue(foreign.close().startswith("CUSTODY_UNRESOLVED:TEARDOWN_FAILED"))
        self.assertFalse(foreign.closed)
        self.assertEqual(len(route.table.live_caps()), 1)
        self.assertEqual(closes(route.port), [])
        self.assertEqual(ctx.close(), "CLOSED")

    def test_borrowed_view_close_never_closes_owner(self):
        k, root, desc = T.world()
        port = SimulatedObjectSignalPort(k)
        table = termination.CapabilityTable(port, Refused, *BIND)
        cap = table.acquire(desc.pid, "MEMBER", T.ident(desc), "TEST")
        view = table.borrowed_view(cap)
        self.assertEqual(table.close(view), "CLOSED")
        self.assertEqual(closes(port), [])
        self.assertIn(cap.fd, port.fd_pool.used)
        table.signal(cap, TERM, BIND)                  # owner still usable
        view2 = table.borrowed_view(cap)
        self.assertEqual(table.close(cap, BIND), "CLOSED")
        self.assertEqual(view2.state, "CLOSED")        # alias of a closed fd
        with self.assertRaisesRegex(Refused, "CLOSE_BINDING_MISMATCH"):
            table.close(cap, ("RUN-A", "OWNER", 2))
        other = termination.CapabilityTable(port, Refused, "RUN-B", "OWNER", 1)
        with self.assertRaisesRegex(Refused, "CLOSE_OF_FOREIGN_CAPABILITY"):
            other.close(cap)
        with self.assertRaisesRegex(Refused, "NOT_A_CAPABILITY"):
            table.close(cap.fd)
        report = table.teardown(BIND)
        self.assertTrue(report["resolved"])
        self.assertEqual(len(closes(port)), 1)


# ---------------------------------------------------------------------------
# A006-2: admission and comprehensive post-spawn cleanup
# ---------------------------------------------------------------------------

class AdmissionAndPostSpawnTests(unittest.TestCase):

    def _prepared(self, prepare, **kw):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, **kw)
        factory = run.context_factory

        def bad_factory(backend):
            ctx = factory(backend)
            prepare(run, ctx)
            return ctx
        run.context_factory = bad_factory
        return k, root, run

    def assert_refused_before_spawn(self, run, root, code):
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_ACTIVATION")
        self.assertIn(code, stop.detail)
        self.assertEqual((run.popen_calls, run.samplers), (0, []))
        self.assertEqual(run.k.procs[root.pid].state, "S")
        self.assertFalse(run.latch.blocked)

    def test_closed_context_refused_before_popen(self):
        k, root, run = self._prepared(lambda run, ctx: ctx.close())
        self.assert_refused_before_spawn(run, root, "RUN_CONTEXT_CLOSED")

    def test_reused_context_refused_before_popen(self):
        k, root, run = self._prepared(lambda run, ctx: ctx.admit())
        self.assert_refused_before_spawn(run, root, "RUN_CONTEXT_NOT_FRESH")

    def test_route_invalidated_or_holding_caps_refused_before_popen(self):
        k, root, run = self._prepared(
            lambda run, ctx: run.route.table.invalidate("EARLIER"))
        self.assert_refused_before_spawn(run, root, "ROUTE_TABLE_INVALIDATED")
        k, root, run = self._prepared(
            lambda run, ctx: run.route.table.acquire(root.pid, "ROOT", None, "X"))
        self.assert_refused_before_spawn(run, root, "ROUTE_ALREADY_HOLDS_CAPABILITIES")

    def test_route_bound_to_other_context_refused_before_popen(self):
        def prepare(run, ctx):
            T.context_for(run.k, ctx.native_backend, run.route).admit()
        k, root, run = self._prepared(prepare)
        self.assert_refused_before_spawn(run, root, "ROUTE_BOUND_TO_ANOTHER_RUN_CONTEXT")

    def test_root_acquisition_error_after_spawn_is_cleaned_up(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)

        def boom(process, context):
            raise RuntimeError("acquisition bug")
        run.route.acquire_root = boom
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE")
        rec = stop.cleanup
        self.assertEqual(rec["failure_phase"], "ROOT_ACQUISITION")
        self.assertIn("RuntimeError:acquisition bug", rec["original_failure"])
        self.assertFalse(rec["root_process_reaped"])      # no authority: unresolved
        self.assertEqual(rec["residual_owned_targets"], [root.pid])
        self.assertTrue(run.latch.blocked and rec["dispatch_blocked"])
        self.assertFalse(run.context.closed)
        self.assertLessEqual(run.elapsed, C.FAILURE_CLEANUP_TOTAL_SECONDS + 1e-9)
        self.assertTrue(run.output_path.with_suffix(".post-spawn-cleanup.json").is_file())

    def test_sampler_construction_and_start_failures_are_cleaned_up(self):
        for kw, phase in ((dict(construct_error=ValueError("ctor")), "SAMPLER_CONSTRUCTION"),
                          (dict(start_error=RuntimeError("start")), "SAMPLER_START")):
            k, root, _ = T.world(descendant=False)
            made = []
            run = LaunchWith(k, root, sampler_factory=sampler_factory(k, made, **kw))
            stop = run.run()
            rec = stop.cleanup
            self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE", phase)
            self.assertEqual(rec["failure_phase"], phase)
            self.assertTrue(rec["root_process_reaped"])
            self.assertEqual(rec["sampler_stop"]["state"],
                             "NOT_CREATED" if phase == "SAMPLER_CONSTRUCTION" else "STOPPED")
            self.assertEqual(rec["custody_close_outcome"], "CLOSED")
            self.assertTrue(run.context.closed)
            self.assertFalse(run.latch.blocked)
            self.assertEqual(T.delivered(run.route.port), [(root.pid, TERM)])

    def test_watchdog_collector_failure_is_cleaned_up(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        run.popen.collector_error = OSError(5, "fake watchdog EIO")
        stop = run.run()
        rec = stop.cleanup
        self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE")
        self.assertEqual(rec["failure_phase"], "WATCHDOG")
        self.assertTrue(rec["root_process_reaped"])
        self.assertFalse(rec["output_complete"])
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertTrue(run.latch.blocked)
        self.assertEqual(run.samplers[0]._thread.alive, False)

    def test_normal_exit_stuck_sampler_blocks_and_retains(self):
        """Astra case normal_exit_stuck_sampler_does_not_block_next_request."""
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, stuck_sampler=True)
        completed(run)
        stop = run.run()
        # DEV007_FIX001 (A007-1): an unresolved completion now stops before
        # result validation, explicitly, instead of via the validator's
        # sampler-alive check (previously SB_STOP_MEASURED_RESOURCE).
        self.assertEqual(stop.stop_id, "SB_STOP_CONTROLLER_COMPLETION_UNRESOLVED")
        self.assertIn("SAMPLER_NOT_STOPPED", stop.detail)
        rec = stop.cleanup
        self.assertIn("SAMPLER_NOT_STOPPED", rec["unresolved_reasons"])
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertTrue(run.latch.blocked)
        self.assertFalse(run.context.closed)
        self.assertEqual(len(run.samplers[0]._thread.joins), 1)   # one bounded join
        self.assertLessEqual(run.samplers[0]._thread.joins[0], C.SAMPLER_STOP_JOIN_SECONDS)
        self.assertLessEqual(run.elapsed, C.FAILURE_CLEANUP_TOTAL_SECONDS + 1e-9)
        nxt = T.Launch(*T.world()[:2], latch=run.latch)
        self.assertEqual(nxt.run().stop_id, "SB_STOP_DISPATCH_BLOCKED")
        self.assertEqual(nxt.popen_calls, 0)

    def test_sampler_runtime_failure_resolved_custody(self):
        k, root, _ = T.world(descendant=False)
        made = []
        run = LaunchWith(k, root, sampler_factory=sampler_factory(
            k, made, runtime_error="OSError:runtime"))
        completed(run)
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_MEASURED_RESOURCE")
        self.assertEqual(stop.cleanup["custody_close_outcome"], "CLOSED")
        self.assertTrue(run.context.closed)
        self.assertFalse(run.latch.blocked)

    def test_non_stop_failure_in_timeout_forces_without_new_grace(self):
        k, root, desc = T.world()
        run = T.Launch(k, root)

        def broken(*a, **kw):
            raise Refused(1, "UNEXPECTED_PROVIDER_REFUSAL")
        with mock.patch.object(C, "exact_timeout_state_machine", broken):
            stop = run.run()
        rec = stop.cleanup
        # FIX004: the timeout stays primary; the provider refusal is secondary
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertEqual(rec["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("UNEXPECTED_PROVIDER_REFUSAL", rec["secondary_failures"][0]["error"])
        self.assertEqual(rec["failure_phase"], "TIMEOUT")
        self.assertEqual([(r["signal"], r["outcome"]) for r in rec["signal_outcomes"]],
                         [("SIGKILL", "SENT")])
        self.assertIn("OWNED_DESCENDANTS_UNVERIFIED", rec["unresolved_reasons"])
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertTrue(run.latch.blocked)
        self.assertEqual(len(run.route.table.held_caps()), 1)   # root cap retained
        self.assertLessEqual(run.elapsed, 5.0 + C.TIMEOUT_CLEANUP_TOTAL_SECONDS + 1e-9)

    def test_keyboard_interrupt_is_cleaned_up_and_reraised(self):
        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        real = run.popen.communicate
        fired = []

        def interrupted(timeout=None):
            if not fired:
                fired.append(1)
                raise KeyboardInterrupt()
            return real(timeout=timeout)
        run.popen.communicate = interrupted
        with self.assertRaises(KeyboardInterrupt) as caught:
            run.run()
        rec = caught.exception.cleanup
        self.assertEqual(rec["failure_phase"], "WATCHDOG")
        self.assertTrue(rec["root_process_reaped"] and rec["output_complete"])
        self.assertEqual(rec["custody_close_outcome"], "CLOSED")
        self.assertTrue(run.context.closed)
        self.assertFalse(run.latch.blocked)

    def test_evidence_write_failure_after_timeout_keeps_primary_and_custody(self):
        k, root, desc = T.world()
        run = T.Launch(k, root)
        real = C._timeout_stop_evidence

        def failing(*a, **kw):
            raise OSError(28, "fake ENOSPC")
        with mock.patch.object(C, "_timeout_stop_evidence", failing):
            stop = run.run()
        # FIX004: primary timeout kept, ENOSPC is a separate secondary, and
        # no second cleanup/close ran (the timeout cleanup's CLOSED stands)
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertEqual(stop.cleanup["failure_phase"], "TIMEOUT")
        self.assertEqual(stop.cleanup["primary_failure"]["type"], "TimeoutExpired")
        self.assertNotIn("ENOSPC", stop.cleanup["original_failure"])
        self.assertIn("ENOSPC", stop.cleanup["secondary_failures"][-1]["error"])
        self.assertTrue(run.context.closed)    # custody already fully closed
        self.assertEqual(stop.cleanup["custody_close_outcome"], "CLOSED")
        self.assertIs(real, C._timeout_stop_evidence)


# ---------------------------------------------------------------------------
# A006-3: atomic lease/close lifecycle on a faithful fd table
# ---------------------------------------------------------------------------

class AtomicLeaseTests(unittest.TestCase):

    def setUp(self):
        self.k, self.root, self.desc = T.world()
        self.bystander = self.k.spawn(1)                 # unrelated process
        self.port = SimulatedObjectSignalPort(self.k)
        self.table = termination.CapabilityTable(self.port, Refused, *BIND)
        self.cap = self.table.acquire(self.desc.pid, "MEMBER", T.ident(self.desc), "TEST")
        self.assertEqual(self.cap.fd, 3)

    def test_lease_has_no_unlocked_check(self):
        src = inspect.getsource(termination.CapabilityTable.lease)
        self.assertNotIn("self.check(", src)

    def test_astra_interleaving_close_and_reuse_before_lease(self):
        reused = {}

        def point(name, cap):
            if name == "BEFORE_LEASE" and not reused:
                self.assertEqual(self.table.close(cap), "CLOSED")
                reused["h"] = self.port.open(self.bystander.pid)   # takes fd 3
        self.table.schedule_point = point
        with self.assertRaisesRegex(Refused, "CAPABILITY_NOT_LIVE:CLOSED"):
            self.table.signal(self.cap, TERM, BIND)
        self.assertEqual(reused["h"].fd, 3)
        self.assertEqual(signals(self.port), [])
        self.assertEqual(self.k.procs[self.bystander.pid].state, "S")

    def test_astra_patch_of_check_cannot_open_a_gap(self):
        """Astra's exact mock target: check() is no longer on the lease path."""
        check = self.table.check
        fired = []

        def close_between(c, op, binding):
            check(c, op, binding)
            fired.append(1)
        with mock.patch.object(self.table, "check", side_effect=close_between):
            self.table.signal(self.cap, TERM, BIND)
        self.assertEqual(fired, [])
        self.assertEqual([(c[1], c[2]) for c in signals(self.port)], [(self.desc.pid, 3)])

    def test_invalidate_before_lease(self):
        self.table.schedule_point = lambda name, cap: (
            name == "BEFORE_LEASE" and self.table.invalidate("REVOKED"))
        with self.assertRaisesRegex(Refused, "CAPABILITY_NOT_LIVE:INVALIDATED"):
            self.table.signal(self.cap, KILL, BIND)
        self.assertEqual(signals(self.port), [])
        self.assertEqual(self.cap.state, "CLOSED")

    def test_close_during_operation_defers_and_fd_not_reused(self):
        seen = {}

        def point(name, cap):
            if name == "LEASED" and not seen:
                seen["close"] = self.table.close(cap)
                seen["again"] = self.table.close(cap)
                seen["other"] = self.port.open(self.bystander.pid)
                with self.assertRaisesRegex(Refused, "CAPABILITY_NOT_LIVE:CLOSE_PENDING"):
                    self.table.signal(cap, KILL, BIND)       # no new lease
        self.table.schedule_point = point
        self.table.signal(self.cap, TERM, BIND)
        self.assertEqual((seen["close"], seen["again"]),
                         ("DEFERRED_LEASE_HELD", "DEFERRED_LEASE_HELD"))
        self.assertEqual(seen["other"].fd, 4)              # fd 3 still ours
        self.assertEqual([(c[1], c[2], c[4]) for c in signals(self.port)],
                         [(self.desc.pid, 3, "DELIVERED")])
        self.assertEqual([(c[1], c[2]) for c in closes(self.port)], [(self.desc.pid, 3)])
        self.assertEqual(self.cap.state, "CLOSED")
        self.assertEqual(self.k.procs[self.bystander.pid].state, "S")

    def test_last_lease_release_vs_close_exactly_once(self):
        seen = []

        def point(name, cap):
            if name == "LEASED" and cap.leases == 1:
                # a second concurrent operation holds its own lease
                with self.table.lease(cap, termination.SIGNAL_OP, BIND):
                    seen.append(("close", self.table.close(cap)))
                seen.append(("after_inner", cap.state, len(closes(self.port))))
            if name == "LAST_LEASE_RELEASED_CLOSE_CLAIMED":
                seen.append(("racing_close", self.table.close(cap)))
        self.table.schedule_point = point
        self.table.signal(self.cap, TERM, BIND)
        self.assertEqual(seen, [("close", "DEFERRED_LEASE_HELD"),
                                ("after_inner", "CLOSE_PENDING", 0),
                                ("racing_close", "CLOSE_IN_PROGRESS")])
        self.assertEqual(len(closes(self.port)), 1)
        self.assertEqual(self.table.close(self.cap), "ALREADY_CLOSED")
        self.assertEqual(len(closes(self.port)), 1)

    def test_close_failure_is_terminal_unresolved_never_retried(self):
        self.port.close_errors = {3: OSError(5, "fake EIO")}
        self.assertEqual(self.table.close(self.cap), "CLOSE_FAILED")
        other = self.port.open(self.bystander.pid)          # number 3 reused
        self.assertEqual(other.fd, 3)
        self.assertEqual(self.table.close(self.cap), "CLOSE_FAILED_NOT_RETRIED")
        with self.assertRaisesRegex(Refused, "CAPABILITY_NOT_LIVE:CLOSE_FAILED"):
            self.table.signal(self.cap, KILL, BIND)
        report = self.table.teardown(BIND)
        self.assertFalse(report["resolved"])
        self.assertEqual([r["state"] for r in report["unresolved"]], ["CLOSE_FAILED"])
        self.assertEqual(len(closes(self.port)), 1)
        self.assertIn(3, self.port.fd_pool.used)            # the bystander's fd intact
        self.assertEqual(signals(self.port), [])
        self.assertEqual(len(self.table.held_caps()), 1)    # authority not dropped

    def test_fd_reuse_across_tables_and_foreign_close(self):
        pool = self.port.fd_pool
        other = termination.CapabilityTable(SimulatedObjectSignalPort(self.k, fd_pool=pool),
                                            Refused, "RUN-B", "OWNER", 1)
        self.assertEqual(self.table.close(self.cap), "CLOSED")
        capB = other.acquire(self.bystander.pid, "MEMBER", T.ident(self.bystander), "TEST")
        self.assertEqual(capB.fd, 3)
        for bad, code in ((3, "NOT_A_CAPABILITY"), (capB, "CAPABILITY_FROM_ANOTHER_TABLE"),
                          (self.cap, "CAPABILITY_NOT_LIVE")):
            with self.assertRaisesRegex(Refused, code):
                self.table.signal(bad, KILL, BIND)
        with self.assertRaisesRegex(Refused, "CLOSE_OF_FOREIGN_CAPABILITY"):
            self.table.close(capB)
        self.assertIn(3, pool.used)
        self.assertEqual(self.k.procs[self.bystander.pid].state, "S")

    def test_fd_table_port_is_faithful_to_number_lookup(self):
        """The simulated port resolves the fd number, like the syscall: this
        is what makes a lifecycle bug observable instead of masked."""
        handle = self.cap.handle
        self.port.fd_pool.free(3)
        self.port.fd_pool.table[3] = self.k.procs[self.bystander.pid]
        self.port.signal(handle, TERM)                     # bypassing the table
        self.assertEqual(self.k.procs[self.bystander.pid].state, "Z")


class BoundaryLock:
    """Table lock that lets another actor run at the n-th scheduling point
    (before every acquire, after every release).  With all shared state
    under the lock, these are the only distinguishable interleavings."""

    def __init__(self, fire_at, actor):
        self._lock = threading.Lock()
        self.n, self.fire_at, self.actor, self.fired = 0, fire_at, actor, False

    def _point(self):
        self.n += 1
        if self.n == self.fire_at and not self.fired:
            self.fired = True
            self.actor()

    def acquire(self, blocking=True, timeout=-1):
        self._point()
        return self._lock.acquire(blocking, timeout)

    def release(self):
        self._lock.release()
        self._point()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def boundary_interleavings(module):
    """close(cap) + an unrelated open at every lock boundary of one signal."""
    rows = []
    for fire_at in range(1, 40):
        k, root, desc = T.world()
        bystander = k.spawn(1)
        port = SimulatedObjectSignalPort(k)
        table = module.CapabilityTable(port, Refused, *BIND)
        cap = table.acquire(desc.pid, "MEMBER", T.ident(desc), "TEST")
        actor_log = []

        def actor():
            actor_log.append(table.close(cap))
            actor_log.append(port.open(bystander.pid).fd)
        lock = BoundaryLock(fire_at, actor)
        table._lock = lock
        try:
            table.signal(cap, TERM, BIND)
            outcome = "SIGNAL_RETURNED"
        except Refused as exc:
            outcome = exc.strerror
        except OSError as exc:
            outcome = "OSError:%s" % exc.errno
        if not lock.fired:
            break
        rows.append({"fire_at": fire_at, "outcome": outcome, "actor": actor_log,
                     "signals": [(c[1], c[2], c[4]) for c in signals(port)],
                     "provider_closes": len(closes(port)),
                     "bystander_pid": bystander.pid, "target_pid": desc.pid,
                     "bystander_state": k.procs[bystander.pid].state,
                     "cap_state": cap.state})
    return rows


class LockBoundaryInterleavingTests(unittest.TestCase):

    def test_candidate_never_reaches_reused_descriptor(self):
        rows = boundary_interleavings(termination)
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["bystander_state"], "S", row)
            self.assertTrue(all(pid == row["target_pid"] for pid, _, _ in row["signals"]),
                            row)
            self.assertEqual(row["provider_closes"], 1, row)
            self.assertEqual(row["cap_state"], "CLOSED", row)

    def test_dev006_bytes_reach_reused_descriptor(self):
        """Reproducer: the bundled DEV006 table (check, then lock+increment)
        lets a close+reuse land in the gap; the effect hits the bystander."""
        dev006 = load_bundled("dev006/termination.py", "termination_dev006")
        rows = boundary_interleavings(dev006)
        hit = [row for row in rows if row["bystander_state"] == "Z"]
        self.assertTrue(hit, rows)
        self.assertEqual(hit[0]["outcome"], "SIGNAL_RETURNED")


# ---------------------------------------------------------------------------
# A006-4: exact output under the cumulative communicate contract
# ---------------------------------------------------------------------------

class OutputContractTests(unittest.TestCase):

    def run_timeout(self, pre, during_grace="", **kw):
        k, root, desc = T.world()
        run = T.Launch(k, root, **kw)
        run.popen.write(pre)

        def waiter(process, seconds):
            process.write(during_grace)
            advance(k, 1.0)
            return process.poll() is not None
        run.waiter = waiter
        return run, run.run()

    def test_pre_timeout_only_output_not_duplicated(self):
        run, stop = self.run_timeout("prefix\n")
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertEqual(run.log_path.read_text(), "prefix\n")
        contract = stop.cleanup["output_collection"]["output_contract"]
        self.assertEqual([s["kind"] for s in contract["snapshots"]],
                         ["TIMEOUT_EXPIRED_CUMULATIVE", "COMMUNICATE_RETURNED_CUMULATIVE"])
        self.assertTrue(contract["cumulative_contract_consistent"])

    def test_growth_during_cleanup_kept_once(self):
        run, stop = self.run_timeout("prefix\n", "more\n")
        self.assertEqual(run.log_path.read_text(), "prefix\nmore\n")

    def test_genuine_repetition_kept(self):
        run, stop = self.run_timeout("same\n", "same\n")
        self.assertEqual(run.log_path.read_text(), "same\nsame\n")

    def test_failure_cleanup_path_partial_output_exact(self):
        k, root, desc = T.world()
        run = T.Launch(k, root, pipe_holders={root.pid, desc.pid},
                       route_factory=lambda: T.sim_route(k, ignore_term={desc.pid}))
        run.popen.write("prefix\n")

        def waiter(process, seconds):
            k.procs[desc.pid].pgid = 5700                 # escape -> failure path
            process.write("late\n")
            advance(k, seconds)
            return process.poll() is not None
        run.waiter = waiter
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT_TERMINATION")
        self.assertFalse(stop.cleanup["output_complete"])
        self.assertEqual(run.log_path.read_text(), "prefix\nlate\n")

    def test_collector_failure_after_timeout_keeps_snapshot(self):
        k, root, desc = T.world()
        run = T.Launch(k, root)
        run.popen.write("prefix\n")

        def waiter(process, seconds):
            process.collector_error = OSError(5, "fake collector EIO")
            advance(k, 1.0)
            return process.poll() is not None
        run.waiter = waiter
        stop = run.run()
        self.assertEqual(run.log_path.read_text(), "prefix\n")
        self.assertFalse(stop.cleanup["controller_stdout_complete"])
        self.assertTrue(run.latch.blocked)

    def test_collector_unit_contract(self):
        c = C.CumulativeOutputCollector()
        c.timeout_snapshot(b"ab", "P1")
        c.timeout_snapshot(None, "P2")                    # no snapshot: keep
        self.assertEqual(c.text, "ab")
        c.final("abab", "P3")                             # genuine repeat
        self.assertEqual((c.text, c.complete), ("abab", True))
        c2 = C.CumulativeOutputCollector()
        c2.timeout_snapshot(b"xy", "P1")
        c2.timeout_snapshot(b"zz", "P2")                  # contract violation
        rep = c2.report()
        self.assertFalse(rep["cumulative_contract_consistent"])
        self.assertEqual(rep["inconsistent_snapshots"][0]["superseded_text"], "xy")


# ---------------------------------------------------------------------------
# Astra's six DEV006 probe cases, adapted to assert the repaired behaviour
# ---------------------------------------------------------------------------

class AstraProbeRegressionTests(unittest.TestCase):

    def test_probe_cases(self):
        k, root, child = T.world()
        run = T.Launch(k, root)
        run.run()
        self.assertEqual(run.route.table.live_caps(), [])
        self.assertTrue(run.context.closed and not run.latch.blocked)
        self.assertEqual(run.route.port.fd_pool.used, set())

        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root)
        factory = run.context_factory

        def closed_factory(backend):
            c = factory(backend)
            c.close()
            return c
        run.context_factory = closed_factory
        stop = run.run()
        self.assertEqual((stop.stop_id, run.popen_calls), ("SB_STOP_ACTIVATION", 0))

        k, root, _ = T.world(descendant=False)
        run = T.Launch(k, root, stuck_sampler=True)

        def completed_communicate(timeout=None):
            k.exit(root.pid)
            run.popen.returncode = 0
            return "complete output", None
        run.popen.communicate = completed_communicate
        run.run()
        self.assertTrue(run.samplers[0]._thread.is_alive())
        self.assertTrue(run.latch.blocked)
        self.assertFalse(run.context.closed)

        class FdPort:
            def __init__(self):
                self.map, self.events = {}, []

            def open(self, pid):
                fd = 3
                while fd in self.map:
                    fd += 1
                self.map[fd] = pid
                return types.SimpleNamespace(fd=fd, pid=pid)

            def close(self, h):
                self.events.append(["close", h.fd])
                self.map.pop(h.fd, None)

            def signal(self, h, sig):
                self.events.append(["signal", h.fd, self.map.get(h.fd), sig])
        p = FdPort()
        table = termination.CapabilityTable(p, Refused, "A", "owner", 1)
        cap = table.acquire(111, "ROOT", (111, 1, 0), "SIM_PROOF")
        fired = [False]

        def close_before_atomic_lease(name, c):
            if name == "BEFORE_LEASE" and not fired[0]:
                fired[0] = True
                table.close(c)
                p.open(222)
        table.schedule_point = close_before_atomic_lease
        with self.assertRaises(Refused):
            table.signal(cap, TERM, ("A", "owner", 1))
        self.assertEqual(p.events, [["close", 3]])

        k, root, child = T.world()
        run = T.Launch(k, root)
        run.popen.write("prefix\n")
        run.run()
        self.assertEqual(run.log_path.read_text(), "prefix\n")


if __name__ == "__main__":
    unittest.main()
