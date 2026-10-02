"""DEV006 regression matrix (Pro review F1-F4, work packages A-F).

Pure simulation only: FakeKernel, virtual-time FakePopen, object-bound
SimulatedObjectSignalPort, FakeSamplerThread, fake hook getters. No fork,
no pidfd, no signal, no /proc read of the host, no git. The full shared
path `launch_request -> watchdog -> exact_timeout_state_machine -> bounded
cleanup` runs with injected ports; admission/prelaunch helpers that read the
repository are stubbed (A004 admission is covered by LifecycleAdmission*).

DEV005 reproducers load the exact DEV005 bytes bundled in testsupport/dev005
(sha256 in testsupport/MANIFEST.json) and show each original defect; the
same scenario then runs against the current candidate.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_dev006
"""
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hook_health  # noqa: E402
import linux_proc_backend  # noqa: E402
import p18_custody  # noqa: E402
import termination  # noqa: E402
from synthetic import (SELF_PID, FakeKernel, FakePopen, FakeProcSource,  # noqa: E402
                       FakeSamplerThread, FdPool, SimulatedObjectSignalPort,
                       UnboundedWaitReached, advance)
from test_controller_dispatch import SysAs, load_bundled  # noqa: E402
from test_linux_exec import CONTROLLER as C, C_ERR, PARSERS  # noqa: E402
J = C.journal_protocol

TERM, KILL = int(signal.SIGTERM), int(signal.SIGKILL)
Refused = C.GroupSignalRefused


def make_backend(k):
    return linux_proc_backend.LinuxProcSamplerBackend(
        FakeProcSource(k), linux_proc_backend.kernel_thread_tolerant(PARSERS.parse_proc_stat),
        errors=C_ERR, sleep=lambda s: advance(k, s))


def world(k=None, descendant=True, root_leader=True):
    k = k or FakeKernel()
    root = k.spawn(SELF_PID) if root_leader else k.spawn(SELF_PID, pgid=SELF_PID,
                                                         session=SELF_PID)
    desc = (k.spawn(root.pid, pgid=root.pid, session=root.pid, rss_kb=4000)
            if descendant and root_leader else None)
    return k, root, desc


def ident(proc):
    return (proc.pid, proc.starttime, 0)


def itext(proc):
    return "%d:%d:0" % (proc.pid, proc.starttime)


def sim_route(k, run_id="RUN-A", port=None, **port_kwargs):
    port = port or SimulatedObjectSignalPort(k, **port_kwargs)
    return termination.LinuxDevelopmentRoute(C, port, run_id=run_id)


def context_for(k, backend, route, run_id="RUN-A", latch=None, generation=1):
    return C.RunContext(run_id=run_id, generation=generation, native_backend=backend,
                        termination=route, clock=lambda: k.clock,
                        sleep=lambda s: advance(k, s),
                        dispatch_latch=latch if latch is not None else C.DispatchLatch())


def manual_sampler_factory(k, stuck=False, ticks=1, made=None):
    class ManualSampler(C.ProcessTreeRssSampler):
        def start(self):
            self._thread = FakeSamplerThread(k, self, stuck)
            for _ in range(ticks):
                self._timed_sample()

    def factory(pid, native_backend=None):
        sampler = ManualSampler(pid, native_backend=native_backend,
                                clock_ns=lambda: int(k.clock * 1e9))
        if made is not None:
            made.append(sampler)
        return sampler
    return factory


def delivered(port):
    return [(c[1], c[3]) for c in port.calls if c[0] == "signal" and c[4] == "DELIVERED"]


class Launch:
    """Runs the controller's own launch_request with pure injected ports."""

    def __init__(self, k, root, *, route_factory=None, backend=None, latch=None,
                 pipe_holders=None, stuck_sampler=False, waiter=None, run_id="RUN-A",
                 journal=None):
        self.k, self.root = k, root
        if journal is None:          # explicit legitimate first initialization
            journal = J.DispatchJournal(J.MemoryStorage(), run_generation=1,
                                        input_identity="TEST-INPUT",
                                        dispatcher_owner="TEST-DISPATCHER",
                                        progression=J.MemoryStorage())
            journal.initialize_scope()
        self.journal = journal
        self.backend = backend or make_backend(k)
        self.latch = latch if latch is not None else C.DispatchLatch()
        self.popen = FakePopen(k, root.pid, pipe_holders=pipe_holders)
        self.route = (route_factory or (lambda: sim_route(k, run_id)))()
        self.samplers = []
        self.popen_calls = 0
        self.stuck_sampler, self.waiter, self.run_id = stuck_sampler, waiter, run_id
        self.context = None
        self.tmp = Path(tempfile.mkdtemp(prefix="dev006_"))

    def context_factory(self, backend):
        self.context = context_for(self.k, backend, self.route, self.run_id, self.latch)
        return self.context

    def popen_factory(self, *args, **kwargs):
        self.popen_calls += 1
        return self.popen

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
        with mock.patch.multiple(C, **stubs), mock.patch.object(C, "sys", SysAs("linux")):
            try:
                C.launch_request(
                    t, t / "runtime", t / "res.json", t / "dur.json", request,
                    t / "request.json", self.output_path, self.log_path,
                    timeout_grace_waiter=self.waiter, worker_command=["synthetic"],
                    watchdog_timeout_seconds=5.0,
                    sampler_backend_factory=lambda: self.backend,
                    run_context_factory=self.context_factory,
                    popen_factory=self.popen_factory,
                    sampler_factory=manual_sampler_factory(
                        self.k, self.stuck_sampler, made=self.samplers),
                    dispatch_latch=self.latch, dispatch_journal=self.journal)
                return None
            except C.StopSignal as stop:
                return stop

    @property
    def raw_path(self):
        return C.raw_worker_output_path(self.output_path, self.run_id)

    @property
    def elapsed(self):
        return self.k.clock - self.start_clock

    def evidence(self):
        import json
        return json.loads(self.output_path.read_text())


# ---------------------------------------------------------------------------
# A / F1: bounded failure cleanup through the complete shared path
# ---------------------------------------------------------------------------

class BoundedCleanupTests(unittest.TestCase):

    def test_normal_timeout_path_resolved_and_unchanged_grace(self):
        k, root, desc = world()
        run = Launch(k, root)
        stop = run.run()
        self.assertEqual((stop.stop_id, stop.detail), ("SB_STOP_TIMEOUT", "parameterized_worker"))
        term = run.evidence()["termination"]
        self.assertEqual(term["production_grace_seconds"], 60)
        self.assertTrue(term["whole_process_tree_quiescent"])
        self.assertEqual(term["cooperative_outcome"], "EXITED_DURING_GRACE")
        self.assertTrue(term["controller_stdout_complete"])
        self.assertEqual(term["sampler_stop"]["state"], "STOPPED")
        self.assertEqual((term["dispatch_blocked"], run.latch.blocked), (False, False))
        self.assertEqual(delivered(run.route.port), [(root.pid, TERM), (desc.pid, TERM)])
        self.assertNotIn(("communicate", None), run.popen.calls)

    def test_descendant_survives_grace_then_capability_force(self):
        k, root, desc = world()
        run = Launch(k, root, route_factory=lambda: sim_route(k, ignore_term={desc.pid}))
        stop = run.run()
        term = run.evidence()["termination"]
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        self.assertEqual(term["whole_tree_outcome"], "QUIESCENT_AFTER_FORCE")
        self.assertEqual(delivered(run.route.port),
                         [(root.pid, TERM), (desc.pid, TERM), (desc.pid, KILL)])
        self.assertFalse(run.latch.blocked)

    def test_init_failure_all_signals_refused_child_always_alive(self):
        """Pro matrix row 2: bounded return, original failure kept, child
        unresolved, next request blocked before any Popen."""
        k, root, _ = world(descendant=False, root_leader=False)   # sampler init fails
        latch = C.DispatchLatch()
        run = Launch(k, root, latch=latch, route_factory=lambda: termination.LinuxDevelopmentRoute(
            C, termination.NativeTerminationUnavailable(Refused), run_id="RUN-A"))
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_SAMPLER_CAPABILITY")
        rec = stop.cleanup
        self.assertIn("WORKER_ROOT_NOT_DEDICATED_PROCESS_GROUP_LEADER", rec["original_failure"])
        self.assertTrue(rec["root_authority_state"].startswith("UNAVAILABLE"))
        self.assertEqual([r["outcome"].split(":")[0] for r in rec["signal_outcomes"]],
                         ["REFUSED", "REFUSED"])
        self.assertFalse(rec["root_process_reaped"])
        self.assertEqual(rec["residual_owned_targets"], [root.pid])
        self.assertFalse(rec["output_complete"])
        self.assertEqual(rec["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertTrue(rec["dispatch_blocked"] and latch.blocked)
        self.assertFalse(rec["whole_process_tree_quiescent"])
        self.assertLessEqual(run.elapsed, C.FAILURE_CLEANUP_TOTAL_SECONDS + 5.0 + 1e-9)
        self.assertEqual(k.procs[root.pid].state, "S")            # zero effects
        self.assertTrue((run.output_path.with_suffix(".initialization-cleanup.json")).is_file())
        # Next request: refused before any effect.
        k2, root2, _ = world()
        nxt = Launch(k2, root2, latch=latch)
        stop2 = nxt.run()
        self.assertEqual(stop2.stop_id, "SB_STOP_DISPATCH_BLOCKED")
        self.assertEqual((nxt.popen_calls, nxt.samplers), (0, []))

    def test_init_failure_root_authority_independent_of_sampler(self):
        """The root capability acquired at spawn survives the sampler failure."""
        k, root, _ = world(descendant=False, root_leader=False)
        run = Launch(k, root)
        stop = run.run()
        rec = stop.cleanup
        self.assertEqual(rec["root_authority_state"], "ACQUIRED")
        self.assertEqual({k: v for k, v in rec["signal_outcomes"][0].items()
                          if k != "remaining_nanoseconds"},
                         {"signal": "SIGTERM", "outcome": "SENT"})
        self.assertIsInstance(rec["signal_outcomes"][0]["remaining_nanoseconds"], int)
        self.assertTrue(rec["root_process_reaped"] and rec["output_complete"])
        self.assertEqual(rec["custody_close_outcome"], "CLOSED")
        self.assertFalse(rec["dispatch_blocked"] or run.latch.blocked)
        self.assertEqual(delivered(run.route.port), [(root.pid, TERM)])

    def test_init_failure_eperm_root_is_not_absent(self):
        k, root, _ = world(descendant=False, root_leader=False)
        run = Launch(k, root, route_factory=lambda: sim_route(k, eperm={root.pid}))
        rec = run.run().cleanup
        self.assertEqual([r["outcome"].split(":")[0] for r in rec["signal_outcomes"]],
                         ["REFUSED", "REFUSED"])
        self.assertIn("SIGNAL_EPERM", rec["signal_outcomes"][0]["outcome"])
        self.assertTrue(rec["dispatch_blocked"])
        self.assertEqual(k.procs[root.pid].state, "S")

    def _escape_during_grace(self, k, desc, stream=False):
        def waiter(process, seconds):
            self.assertEqual(seconds, 60)            # frozen value, virtual time
            k.procs[desc.pid].pgid = 5700            # escapes: census contradiction
            advance(k, seconds)
            return process.poll() is not None
        return waiter

    def test_root_reaped_pipe_never_eof_partial_output_kept(self):
        """Pro matrix row 3 + continuous output: bounded, output_complete
        false, partial output preserved, original STOP kept."""
        k, root, desc = world()
        popen_holder = {}

        def stream(kernel, seconds):
            p = popen_holder.get("p")
            if p is not None and kernel.procs.get(desc.pid) is not None:
                p.write("tick@%.1f\n" % kernel.clock)
        k.on_advance = [stream]
        run = Launch(k, root, pipe_holders={root.pid, desc.pid},
                     route_factory=lambda: sim_route(k, ignore_term={desc.pid}),
                     waiter=self._escape_during_grace(k, desc))
        popen_holder["p"] = run.popen
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT_TERMINATION")
        rec = stop.cleanup
        # FIX004: timeout stays primary; termination failure kept separately
        self.assertEqual(rec["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("OWNED_PROCESS_ESCAPED_WORKER_PGID", rec["timeout_termination_failure"]["message"])
        self.assertTrue(rec["root_process_reaped"])
        self.assertFalse(rec["output_complete"])
        self.assertEqual(rec["collector_state"], "PIPE_EOF_NOT_OBSERVED_WITHIN_DEADLINE")
        self.assertIn(desc.pid, rec["residual_owned_targets"])
        self.assertTrue(rec["dispatch_blocked"])
        log = run.log_path.read_text()
        self.assertIn("tick@", log)
        self.assertNotIn("CONTROLLER_STDOUT_NOT_AVAILABLE", log)
        self.assertLessEqual(run.elapsed, 5.0 + C.TIMEOUT_CLEANUP_TOTAL_SECONDS + 1e-9)
        self.assertNotIn(("communicate", None), run.popen.calls)
        self.assertEqual(k.procs[desc.pid].state, "S")   # escaped: never signalled

    def test_success_path_pipe_held_outside_group_is_bounded(self):
        k, root, desc = world()
        run = Launch(k, root, pipe_holders={root.pid, 4100})   # never-owned holder
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        term = run.evidence()["termination"]
        self.assertTrue(term["whole_process_tree_quiescent"])   # census claim only
        self.assertFalse(term["controller_stdout_complete"])
        # DEV007: output unresolved -> capabilities are retained, not closed
        self.assertEqual(term["unresolved_reasons"],
                         ["OUTPUT_EOF_NOT_OBSERVED", "CUSTODY_NOT_CLOSED"])
        self.assertEqual(term["custody_close_outcome"], "RETAINED_OWNERSHIP_UNRESOLVED")
        self.assertFalse(run.context.closed)
        self.assertTrue(run.latch.blocked)
        self.assertEqual(k.procs[4100].state, "S")

    def test_collector_failure_kept_as_evidence(self):
        k, root, desc = world()
        run = Launch(k, root, route_factory=lambda: sim_route(k, ignore_term={desc.pid}))

        def waiter(process, seconds):
            k.procs[desc.pid].pgid = 5700
            process.collector_error = OSError(5, "fake collector EIO")
            advance(k, seconds)
            return process.poll() is not None
        run.waiter = waiter
        stop = run.run()
        rec = stop.cleanup
        self.assertEqual(rec["collector_state"], "COLLECTOR_FAILED:OSError:[Errno 5] fake collector EIO")
        self.assertFalse(rec["output_complete"])
        self.assertTrue(rec["dispatch_blocked"])

    def test_sampler_not_stopped_is_unresolved(self):
        k, root, desc = world()
        run = Launch(k, root, stuck_sampler=True)
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT")
        term = run.evidence()["termination"]
        self.assertEqual(term["sampler_stop"]["state"], "RUNNING_AFTER_BOUNDED_JOIN_UNRESOLVED")
        self.assertIn("SAMPLER_NOT_STOPPED", term["unresolved_reasons"])
        self.assertTrue(run.latch.blocked)
        # exactly one bounded join; the finally clause adds no second budget
        self.assertEqual(len(run.samplers[0]._thread.joins), 1)
        self.assertLessEqual(run.samplers[0]._thread.joins[0], C.SAMPLER_STOP_JOIN_SECONDS)
        self.assertEqual(term["sampler_stop"]["join_timeout_nanoseconds"],
                         int(run.samplers[0]._thread.joins[0] * 1e9))

    def test_slow_census_overruns_total_deadline(self):
        """E: a census cannot be preempted; its late answer is not accepted,
        cleanup gets only the remaining (zero) budget, result unresolved."""
        k, root, desc = world()
        run = Launch(k, root, route_factory=lambda: sim_route(k, ignore_term={desc.pid}))

        def waiter(process, seconds):
            advance(k, seconds)
            src = run.backend._source
            real = src.list_pids

            def slow():
                advance(k, 20.0)
                return real()
            src.list_pids = slow
            return process.poll() is not None
        run.waiter = waiter
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT_TERMINATION")
        rec = stop.cleanup
        # FIX004: timeout stays primary; termination failure kept separately
        self.assertEqual(rec["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("census_overran_cleanup_deadline", rec["timeout_termination_failure"]["message"])
        self.assertTrue(rec["cleanup_deadline_exhausted"])
        self.assertTrue(rec["cleanup_deadline"]["overruns"] or rec["cleanup_deadline"]["exhausted"])
        self.assertIn("CLEANUP_DEADLINE_EXHAUSTED", rec["unresolved_reasons"])
        self.assertTrue(run.latch.blocked)
        waits = [c for c in run.popen.calls if c[0] in ("wait", "communicate")]
        self.assertTrue(all(t is not None for _, t in waits))

    def test_census_permission_failure_fails_closed_bounded(self):
        k, root, desc = world()
        run = Launch(k, root)

        def waiter(process, seconds):
            k.read_errors[(4100, "stat")] = 13      # EACCES somewhere in /proc
            k.procs[desc.pid].state = "S"
            advance(k, seconds)
            return process.poll() is not None
        run.waiter = waiter
        run.route = sim_route(k, ignore_term={root.pid, desc.pid})
        stop = run.run()
        self.assertEqual(stop.stop_id, "SB_STOP_TIMEOUT_TERMINATION")
        # FIX004: timeout stays primary; termination failure kept separately
        self.assertEqual(stop.cleanup["primary_failure"]["type"], "TimeoutExpired")
        self.assertIn("PROC_CENSUS_READ_FAILED", stop.cleanup["timeout_termination_failure"]["message"])
        self.assertTrue(stop.cleanup["dispatch_blocked"])


# ---------------------------------------------------------------------------
# B / F4: explicit per-run context
# ---------------------------------------------------------------------------

class RunContextTests(unittest.TestCase):

    def setup_run(self, run_id):
        k, root, desc = world()
        b = make_backend(k)
        C.ProcessTreeRssSampler(root.pid, native_backend=b)
        route = sim_route(k, run_id)
        ctx = context_for(k, b, route, run_id)
        popen = FakePopen(k, root.pid)
        ctx.attach_root(popen)
        owned = {root.pid: itext(root), desc.pid: itext(desc)}
        return k, root, desc, b, route, ctx, popen, owned

    def test_nested_interleaved_runs_close_one_other_continues(self):
        kA, rootA, descA, bA, routeA, ctxA, popA, ownedA = self.setup_run("RUN-A")
        kB, rootB, descB, bB, routeB, ctxB, popB, ownedB = self.setup_run("RUN-B")
        routeA.port.ignore_term = {descA.pid}
        nested = {}

        def waiter_a(process, seconds):
            # Run B's complete state machine inside A's grace wait, then close B.
            nested["B"] = C.exact_timeout_state_machine(
                popB, lambda p, s: p.poll() is not None, lambda: ownedB,
                run_context=ctxB)
            nested["B_close"] = ctxB.close()
            return process.poll() is not None
        with mock.patch.object(C, "sys", SysAs("linux")):
            resultA = C.exact_timeout_state_machine(popA, waiter_a, lambda: ownedA,
                                                    run_context=ctxA)
            with self.assertRaisesRegex(Refused, "RUN_CONTEXT_CLOSED"):
                ctxB.group_signal(rootB.pid, KILL, ownedB)
        self.assertTrue(nested["B"]["whole_process_tree_quiescent"])
        self.assertEqual(nested["B_close"], "CLOSED")
        self.assertEqual(resultA["whole_tree_outcome"], "QUIESCENT_AFTER_FORCE")
        self.assertEqual(delivered(routeA.port),
                         [(rootA.pid, TERM), (descA.pid, TERM), (descA.pid, KILL)])
        self.assertEqual(delivered(routeB.port), [(rootB.pid, TERM), (descB.pid, TERM)])
        self.assertEqual({e["run_id"] for e in ctxA.evidence}, {"RUN-A"})
        self.assertEqual({e["run_id"] for e in ctxB.evidence}, {"RUN-B"})
        self.assertIsNot(ctxA.deadline, ctxB.deadline)

    def test_route_cannot_serve_second_context(self):
        k, root, desc, b, route, ctx, popen, owned = self.setup_run("RUN-A")
        other = context_for(k, b, route, "RUN-A")
        other.attach_root(popen)
        self.assertIn("ROUTE_BOUND_TO_ANOTHER_RUN_CONTEXT", other.root_authority_state)
        with self.assertRaisesRegex(Refused, "ROUTE_BOUND_TO_ANOTHER_RUN_CONTEXT"):
            other.group_signal(root.pid, TERM, owned)
        self.assertEqual(delivered(route.port), [])

    def test_route_rejects_context_of_other_run(self):
        k, root, _ = world(descendant=False)
        route = sim_route(k, "RUN-A")
        ctx = context_for(k, make_backend(k), route, "RUN-B")
        ctx.attach_root(FakePopen(k, root.pid))
        self.assertIn("ROUTE_CONTEXT_RUN_MISMATCH", ctx.root_authority_state)

    def test_backend_mismatch_refused(self):
        k, root, desc, b, route, ctx, popen, owned = self.setup_run("RUN-A")
        with mock.patch.object(C, "sys", SysAs("linux")):
            with self.assertRaisesRegex(C.StopSignal, "run_context_backend_mismatch"):
                C.exact_timeout_state_machine(popen, None, lambda: owned,
                                              make_backend(k), run_context=ctx)

    def test_no_module_global_route_lookup(self):
        with open(C.__file__) as fh:
            src = fh.read()
        for name in ("_LINUX_DEVELOPMENT_ROUTE", "register_linux_development_route",
                     "_linux_development_route"):
            self.assertNotIn(name, src)


# ---------------------------------------------------------------------------
# C / F3: readable Z/X classification matrix
# ---------------------------------------------------------------------------

class ObservationMatrixTests(unittest.TestCase):
    """Non-session-leader descendant D of root R (pgid R, session R).
    {same, reused identity} x {same, changed PGID} x {live, Z, X}."""

    CASES = [(i, g, st) for i in ("same", "reused") for g in ("same", "changed")
             for st in ("S", "Z", "X")]

    def mutate(self, k, d, identity, group, state):
        if identity == "reused":
            k.reuse(d.pid, pgid=d.pgid)
        p = k.procs[d.pid]
        if group == "changed":
            p.pgid = d.pid                          # setpgid(0,0) by D
        p.state = state
        if state != "S":
            p.rss_kb = 0

    def expect(self, identity, group, state):
        if identity == "reused" or group == "changed":
            return "REJECT"
        return "LIVE" if state == "S" else "EXIT"

    def fresh(self):
        k, root, d = world()
        b = make_backend(k)
        b.bind_process_group_authority(root.pid, ident(root))
        known = {root.pid: ident(root), d.pid: ident(d)}
        live, _ = b.live_owned_tree(known)
        self.assertEqual(set(live), {root.pid, d.pid})
        return k, root, d, b, known

    def classify(self, fn, b):
        try:
            value = fn()
        except C.NativeSamplerIdentityAwareExitRace:
            return "EXIT"
        except C.NativeSamplerProcessAbsent:
            return "EXIT"
        except C.NativeSamplerCapabilityError:
            return "REJECT"
        return value

    def test_explicit_rss(self):
        for case in self.CASES:
            with self.subTest(case):
                k, root, d, b, known = self.fresh()
                self.mutate(k, d, *case)
                got = self.classify(lambda: "LIVE" if b.rss(d.pid, ident(d), root.pid) else "?", b)
                self.assertEqual(got, self.expect(*case))

    def test_default_rss_remembered_authority(self):
        for case in self.CASES:
            with self.subTest(case):
                k, root, d, b, known = self.fresh()
                self.mutate(k, d, *case)
                got = self.classify(lambda: "LIVE" if b.rss(d.pid) else "?", b)
                self.assertEqual(got, self.expect(*case))

    def test_zero_rss_retry_uses_same_rule(self):
        for case in self.CASES:
            with self.subTest(case):
                k, root, d, b, known = self.fresh()
                k.procs[d.pid].rss_kb = 0
                reads = {"n": 0}

                def hook(kernel, pid, name):
                    if pid == d.pid and name == "smaps_rollup":
                        reads["n"] += 1
                        if reads["n"] == 1:
                            kernel.on_read.remove(hook)
                            self.mutate(kernel, d, *case)
                            if case == ("same", "same", "S"):
                                kernel.procs[d.pid].rss_kb = 10
                k.on_read.append(hook)
                got = self.classify(lambda: "LIVE" if b.rss(d.pid, ident(d), root.pid) else "?", b)
                self.assertEqual(got, self.expect(*case))

    def owned_tree_outcome(self, k, root, d, b, known, case, via_controller):
        self.mutate(k, d, *case)
        fn = ((lambda: C._native_live_owned_tree(b, known)) if via_controller
              else (lambda: b.live_owned_tree(known)))
        try:
            live, absent = fn()
        except C.NativeSamplerCapabilityError:
            return "REJECT"
        return "LIVE" if d.pid in live else ("EXIT" if d.pid in absent else "?")

    def test_known_member_refresh_backend_and_shared_controller(self):
        for via in (False, True):
            for case in self.CASES:
                with self.subTest(case=case, via_controller=via):
                    k, root, d, b, known = self.fresh()
                    self.assertEqual(self.owned_tree_outcome(k, root, d, b, known, case, via),
                                     self.expect(*case))

    def test_shared_sampler_tick(self):
        for case in self.CASES:
            with self.subTest(case):
                k, root, d = world()
                b = make_backend(k)
                s = C.ProcessTreeRssSampler(root.pid, native_backend=b)
                s._sample()
                self.assertIn(d.pid, s.native_owned_identities)
                self.mutate(k, d, *case)
                try:
                    s._sample()
                    got = "LIVE" if d.pid in s.active_owned_pids else (
                        "EXIT" if d.pid in s.identity_aware_exit_pids else "?")
                except C.NativeSamplerCapabilityError:
                    got = "REJECT"
                self.assertEqual(got, self.expect(*case))

    def test_enoent_vs_eacces_vs_parse(self):
        k, root, d, b, known = self.fresh()
        del k.procs[d.pid]
        self.assertEqual(b.revalidate_expected_exit(d.pid, ident(d), root.pid), "ABSENT_ENOENT")
        k, root, d, b, known = self.fresh()
        k.read_errors[(d.pid, "stat")] = 13
        with self.assertRaisesRegex(C.NativeSamplerCapabilityError, "errno=13"):
            b.rss(d.pid, ident(d), root.pid)
        k, root, d, b, known = self.fresh()
        k.stat_override[d.pid] = b"garbage"
        with self.assertRaisesRegex(C.NativeSamplerCapabilityError, "PROC_STAT_PARSE"):
            b.live_owned_tree(known)

    def test_authority_consensus_preserved(self):
        k, root, d, b, known = self.fresh()
        with self.assertRaisesRegex(C.NativeSamplerCapabilityError,
                                    "RSS_GROUP_AUTHORITY_CONTRADICTION"):
            b.rss(d.pid, ident(d), 4100)


# ---------------------------------------------------------------------------
# D / F2: retirement and simulated capabilities
# ---------------------------------------------------------------------------

class CapabilityRouteTests(unittest.TestCase):

    def bound(self, descendant=True):
        k, root, d = world(descendant=descendant)
        b = make_backend(k)
        C.ProcessTreeRssSampler(root.pid, native_backend=b)
        return k, root, d, b

    def signal(self, ctx, pgid, signum=KILL, owned=None):
        try:
            ctx.group_signal(pgid, signum, owned)
            return "SENT"
        except ProcessLookupError:
            return "ABSENT"
        except Refused as exc:
            return exc.strerror

    def test_first_empty_group_discovered_by_route_retires(self):
        k, root, _, b = self.bound(descendant=False)
        route = sim_route(k)
        ctx = context_for(k, b, route)
        popen = FakePopen(k, root.pid)
        ctx.attach_root(popen)
        k.exit(root.pid)
        popen.poll()                                  # reaped: group empty
        self.assertFalse(b._group_retired)            # nobody refreshed before
        self.assertEqual(self.signal(ctx, root.pid), "ABSENT")
        self.assertTrue(b._group_retired)
        self.assertEqual(b.authority_evidence()["retirement_source"], "SIGNAL_ROUTE")
        # number reused by a new group whose leader then exits
        leader = k.spawn(1, pgid=root.pid, session=root.pid)
        newer = k.spawn(leader.pid, pgid=root.pid, session=root.pid)
        del k.procs[leader.pid]
        k.procs[root.pid] = leader.__class__(root.pid, 1, root.pid, root.pid,
                                             root.starttime + 90, 100)
        del k.procs[root.pid]
        self.assertEqual(self.signal(ctx, root.pid), "PGID_REUSE_AFTER_RETIREMENT")
        self.assertEqual(route.port.effects(), [])
        self.assertTrue(b._group_retired)             # never resurrected
        with self.assertRaisesRegex(C.NativeSamplerCapabilityError, "PGID_REUSE_OR_AMBIGUITY"):
            b.live_owned_tree({root.pid: ident(root)})
        self.assertEqual(k.procs[newer.pid].state, "S")

    def test_leader_absent_unrecorded_member_refused(self):
        """Group never observed empty; root object gone; a member not in the
        recorded owned identities is unproven -> refused, zero effects."""
        k, root, _, b = self.bound(descendant=False)
        route = sim_route(k)
        ctx = context_for(k, b, route)
        popen = FakePopen(k, root.pid)
        ctx.attach_root(popen)
        stranger = k.spawn(root.pid, pgid=root.pid, session=root.pid)
        k.exit(root.pid)
        popen.poll()
        self.assertEqual(self.signal(ctx, root.pid, owned={root.pid: itext(root)}),
                         "UNPROVEN_MEMBER_AFTER_ROOT_OBJECT_GONE")
        self.assertEqual(route.port.effects(), [])
        self.assertEqual(k.procs[stranger.pid].state, "S")

    def test_recorded_member_after_root_reaped_is_signalled(self):
        k, root, d, b = self.bound()
        route = sim_route(k)
        ctx = context_for(k, b, route)
        popen = FakePopen(k, root.pid)
        ctx.attach_root(popen)
        owned = {root.pid: itext(root), d.pid: itext(d)}
        k.exit(root.pid)
        popen.poll()                                  # root reaped during grace
        self.assertEqual(self.signal(ctx, root.pid, KILL, owned), "SENT")
        self.assertEqual(delivered(route.port), [(d.pid, KILL)])
        # root capability now names a gone object: ESRCH, never a number
        with self.assertRaises(ProcessLookupError):
            ctx.root_signal(KILL)

    def test_generation_change_after_census_before_effect(self):
        """New object at the same pid after final census gets zero effects."""
        k, root, d, b = self.bound()
        swapped = {}

        def before_effect(kernel, handle):
            if handle.pid == d.pid and not swapped:
                kernel.reuse(d.pid, pgid=root.pid)
                swapped["new"] = kernel.procs[d.pid]
        route = sim_route(k, before_effect=before_effect)
        ctx = context_for(k, b, route)
        ctx.attach_root(FakePopen(k, root.pid))
        k.exit(root.pid)                              # root zombie (unreaped)
        owned = {root.pid: itext(root), d.pid: itext(d)}
        self.assertEqual(self.signal(ctx, root.pid, KILL, owned), "ABSENT")
        self.assertEqual(swapped["new"].state, "S")
        self.assertEqual(route.port.effects(), [])

    def test_member_reused_before_acquisition_refused(self):
        k, root, d, b = self.bound()
        route = sim_route(k)
        ctx = context_for(k, b, route)
        ctx.attach_root(FakePopen(k, root.pid))
        owned = {root.pid: itext(root), d.pid: itext(d)}
        k.reuse(d.pid, pgid=root.pid)
        self.assertEqual(self.signal(ctx, root.pid, KILL, owned),
                         "GROUP_CENSUS_REFUSED:OWNED_PID_REUSE_REJECTED")
        self.assertEqual(route.port.effects(), [])

    def test_eperm_esrch_and_revocation(self):
        k, root, d, b = self.bound()
        port = SimulatedObjectSignalPort(k)
        route = sim_route(k, port=port)
        ctx = context_for(k, b, route)
        ctx.attach_root(FakePopen(k, root.pid))
        owned = {root.pid: itext(root), d.pid: itext(d)}
        port.eperm = {d.pid}                          # permission revoked
        outcome = self.signal(ctx, root.pid, TERM, owned)
        self.assertTrue(outcome.startswith("MEMBER_SIGNAL_EPERM"))
        self.assertEqual(k.procs[d.pid].state, "S")
        self.assertFalse(any(c[0] == "kill" for c in port.calls))   # no numeric path
        opens_before = sum(1 for c in port.calls if c[0] == "open")
        self.signal(ctx, root.pid, TERM, owned)
        self.assertEqual(sum(1 for c in port.calls if c[0] == "open"), opens_before)

    def test_capability_table_bindings(self):
        k, root, d, b = self.bound()
        pool = FdPool()
        tA = termination.CapabilityTable(SimulatedObjectSignalPort(k, fd_pool=pool),
                                         Refused, "RUN-A", "OWNER", 1)
        tB = termination.CapabilityTable(SimulatedObjectSignalPort(k, fd_pool=pool),
                                         Refused, "RUN-B", "OWNER", 1)
        capA = tA.acquire(d.pid, "MEMBER", ident(d), "TEST")
        fd = capA.fd
        self.assertEqual(tA.close(capA), "CLOSED")
        capB = tB.acquire(root.pid, "MEMBER", ident(root), "TEST")
        self.assertEqual(capB.fd, fd)                 # fd number reused
        bindA = ("RUN-A", "OWNER", 1)
        for bad, code in ((fd, "NOT_A_CAPABILITY"), (capB, "CAPABILITY_FROM_ANOTHER_TABLE"),
                          (capA, "CAPABILITY_NOT_LIVE")):
            with self.assertRaisesRegex(Refused, code):
                tA.signal(bad, KILL, bindA)
        capA2 = tA.acquire(d.pid, "MEMBER", ident(d), "TEST")
        with self.assertRaisesRegex(Refused, "CAPABILITY_BINDING_MISMATCH"):
            tA.signal(capA2, KILL, ("RUN-A", "OWNER", 2))
        view = tA.borrowed_view(capA2)
        with self.assertRaisesRegex(Refused, "OPERATION_NOT_ALLOWED"):
            tA.signal(view, KILL, bindA)
        tA.invalidate("TEST_INVALIDATION")
        with self.assertRaisesRegex(Refused, "CAPABILITY_NOT_LIVE"):
            tA.signal(capA2, KILL, bindA)
        with self.assertRaisesRegex(Refused, "TABLE_INVALIDATED"):
            tA.acquire(d.pid, "MEMBER", ident(d), "TEST")
        self.assertEqual(k.procs[root.pid].state, "S")
        self.assertEqual(k.procs[d.pid].state, "S")

    def test_lease_defers_close_no_interleave(self):
        k, root, d, b = self.bound()
        order = []
        port = SimulatedObjectSignalPort(k)
        table = termination.CapabilityTable(port, Refused, "RUN-A", "O", 1)
        cap = table.acquire(d.pid, "MEMBER", ident(d), "TEST")

        def before_effect(kernel, handle):
            order.append(("close_attempt", table.close(cap)))
        port.before_effect = before_effect
        table.signal(cap, TERM, ("RUN-A", "O", 1))
        closes = [c for c in port.calls if c[0] == "close"]
        self.assertEqual(order, [("close_attempt", "DEFERRED_LEASE_HELD")])
        self.assertEqual(len(closes), 1)
        self.assertLess(port.calls.index(("signal", d.pid, cap.fd, TERM, "DELIVERED")),
                        port.calls.index(closes[0]))
        self.assertEqual(cap.state, "CLOSED")
        self.assertEqual(table.close(cap), "ALREADY_CLOSED")

    def test_native_port_default_denial(self):
        k, root, d, b = self.bound()
        port = termination.NativeTerminationUnavailable(Refused)
        route = termination.LinuxDevelopmentRoute(C, port)
        ctx = context_for(k, b, route, "DEV-RUN")
        ctx.attach_root(FakePopen(k, root.pid))
        self.assertIn("LINUX_NATIVE_TERMINATION_NOT_AUTHORIZED", ctx.root_authority_state)
        self.assertEqual(self.signal(ctx, root.pid, KILL,
                                     {root.pid: itext(root)}),
                         "ROOT_CAPABILITY_ABSENT")
        self.assertEqual(port.calls, [("open", root.pid)])


# ---------------------------------------------------------------------------
# E: cadence diagnostics (observed only)
# ---------------------------------------------------------------------------

class CadenceDiagnosticsTests(unittest.TestCase):

    def test_ticks_record_phases_overrun_no_catch_up(self):
        k, root, d = world()
        b = make_backend(k)
        s = C.ProcessTreeRssSampler(root.pid, native_backend=b,
                                    clock_ns=lambda: int(k.clock * 1e9))
        real = b._source.list_pids

        def slow():
            advance(k, 0.2)                           # 200 ms per scan
            return real()
        b._source.list_pids = slow
        s._timed_sample()
        advance(k, s.interval)
        s._timed_sample()
        rep = s.cadence_report()
        self.assertEqual(rep["tick_count_recorded"], 2)    # no catch-up ticks
        self.assertEqual(rep["overrun_tick_count"], 2)
        row = rep["ticks"][1]
        self.assertIsNotNone(row["scheduled_ns"])
        self.assertGreaterEqual(row["census_ns"], int(0.4e9))
        self.assertIsNotNone(row["rss_ns"])
        self.assertIsNotNone(row["lock_wait_ns"])
        self.assertEqual(rep["cadence_claim"], "OBSERVED_ONLY_NOT_A_10MS_GUARANTEE")

    def test_join_timeout_is_not_stop_proof(self):
        k, root, d = world()
        s = manual_sampler_factory(k, stuck=True)(root.pid, make_backend(k))
        s.start()
        state = s.stop_bounded(5.0)
        self.assertEqual(state["state"], "RUNNING_AFTER_BOUNDED_JOIN_UNRESOLVED")
        self.assertTrue(state["thread_alive_after_join"])


# ---------------------------------------------------------------------------
# F: hook health
# ---------------------------------------------------------------------------

class FakeGuard:
    def trace(self, *a):
        return None

    def profile(self, *a):
        return None


class HookHealthTests(unittest.TestCase):

    def monitor(self, hooks):
        return hook_health.HookHealthMonitor(lambda: hooks["trace"], lambda: hooks["profile"])

    def test_existing_hooks_refused_at_admission(self):
        hooks = {"trace": None, "profile": print}
        m = self.monitor(hooks)
        with self.assertRaises(hook_health.HookAdmissionRefused):
            m.admit()
        self.assertEqual(m.state, "ADMISSION_REFUSED")

    def test_loss_replacement_latch_irreversibly(self):
        g = FakeGuard()
        hooks = {"trace": None, "profile": None}
        m = self.monitor(hooks)
        m.admit()
        hooks.update(trace=g.trace, profile=g.profile)
        m.bind(g)
        self.assertTrue(m.check("ok"))
        hooks["profile"] = None                       # callback failure clears it
        self.assertFalse(m.check("lost"))
        hooks["profile"] = g.profile                  # reinstall: still compromised
        self.assertFalse(m.check("reinstalled"))
        self.assertEqual(m.state, hook_health.COMPROMISED)
        self.assertEqual(m.latched["label"], "lost")
        other = FakeGuard()
        m2 = self.monitor({"trace": None, "profile": None})
        m2.admit()
        m2._gettrace = lambda: other.trace            # replaced by another object
        m2._getprofile = lambda: g.profile
        m2.bind(g)
        self.assertTrue(m2.compromised)

    def test_window_checks_and_custody_evaluation(self):
        g = FakeGuard()
        hooks = {"trace": None, "profile": None}
        m = self.monitor(hooks)
        m.admit()
        hooks.update(trace=g.trace, profile=g.profile)
        m.bind(g)
        import contextlib

        @contextlib.contextmanager
        def window():
            yield "w"
        with p18_custody._checked_window(window(), m):
            hooks["trace"] = None
        self.assertTrue(m.compromised)
        self.assertEqual(m.latched["label"], "observe_leave")
        report = m.report()
        self.assertFalse(report["isolation_claim"] or report["syscall_census_claim"])


# ---------------------------------------------------------------------------
# DEV005 reproducers (exact bundled bytes): the original defects
# ---------------------------------------------------------------------------

class Dev005ReproducerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.OLD_C = load_bundled("dev005/stage_b_controller.py", "stage_b_controller_dev005")
        saved = sys.modules.get("linux_proc_backend")
        cls.OLD_B = load_bundled("dev005/linux_proc_backend.py", "linux_proc_backend_dev005")
        sys.modules["linux_proc_backend"] = cls.OLD_B
        try:
            cls.OLD_T = load_bundled("dev005/termination.py", "termination_dev005")
        finally:
            sys.modules["linux_proc_backend"] = saved

    def test_f1_dev005_reaches_unbounded_communicate(self):
        k, root, _ = world(descendant=False)
        popen = FakePopen(k, root.pid)
        with mock.patch.object(self.OLD_C, "sys", SysAs("linux")):
            with self.assertRaises(UnboundedWaitReached):
                self.OLD_C._stop_worker_after_sampler_initialization_failure(popen)
        self.assertIn(("communicate", None), popen.calls)
        # candidate: bounded, recorded, blocked
        ctx = C.default_run_context(None)
        ctx.clock, ctx.dispatch_latch = (lambda: k.clock), C.DispatchLatch()
        with mock.patch.object(C, "sys", SysAs("linux")):
            ctx.attach_root(FakePopen(k, root.pid))
            rec = C._stop_worker_after_sampler_initialization_failure(
                FakePopen(k, root.pid), ctx)["record"]
        self.assertTrue(rec["dispatch_blocked"])

    def old_backend(self, k):
        return self.OLD_B.LinuxProcSamplerBackend(
            FakeProcSource(k), self.OLD_B.kernel_thread_tolerant(PARSERS.parse_proc_stat),
            errors=C_ERR, sleep=lambda s: None)

    def test_f3_dev005_contradicting_zombie_counted_as_exit(self):
        k, root, d = world()
        old = self.old_backend(k)
        old.bind_process_group_authority(root.pid, ident(root))
        old.live_owned_tree({root.pid: ident(root), d.pid: ident(d)})
        k.procs[d.pid].pgid = d.pid
        k.procs[d.pid].state = "Z"
        with self.assertRaises(C.NativeSamplerProcessAbsent):
            old.rss(d.pid, ident(d), root.pid)
        new = make_backend(k)
        with self.assertRaisesRegex(C.NativeSamplerCapabilityError, "RSS_PGID_CHANGED"):
            new.rss(d.pid, ident(d), root.pid)

    def test_f2_dev005_route_does_not_retire_empty_group(self):
        k, root, _ = world(descendant=False)
        old = self.old_backend(k)
        old.bind_process_group_authority(root.pid, ident(root))
        calls = []

        class Port:
            def kill(self, pgid, signum):
                calls.append((pgid, signum))
        route = self.OLD_T.LinuxDevelopmentRoute(self.OLD_C, Port())
        k.exit(root.pid)
        del k.procs[root.pid]
        with self.assertRaises(ProcessLookupError):
            route.group_signal(root.pid, KILL, old)
        self.assertFalse(old._group_retired)          # the DEV005 defect
        k.spawn(1, pgid=root.pid, session=root.pid)   # number reused, newer member
        route.group_signal(root.pid, KILL, old)
        self.assertEqual(calls, [(root.pid, KILL)])   # DEV005 would signal it

    def test_f4_dev005_global_route_replaced_mid_call(self):
        self.assertTrue(hasattr(self.OLD_C, "register_linux_development_route"))
        seen = []

        class R:
            def __init__(self, name):
                self.name = name

            def group_signal(self, pgid, signum, backend):
                seen.append(self.name)
        with mock.patch.object(self.OLD_C, "sys", SysAs("linux")):
            self.OLD_C.register_linux_development_route(R("A"))
            backend_a = object()
            self.OLD_C.register_linux_development_route(R("B"))
            self.OLD_C._posix_group_signal(5000, TERM, backend_a)
            self.OLD_C.register_linux_development_route(None)
        self.assertEqual(seen, ["B"])


if __name__ == "__main__":
    unittest.main()
