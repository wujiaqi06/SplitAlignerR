"""Shared-controller platform dispatch: explicit per-run context with the
Linux development provider, and Darwin regression against the bundled exact
baseline (testsupport/baseline_7a90d33, sha256 in testsupport/MANIFEST.json;
no git needed). Synthetic only: fake kernel, fake Popen, recorded os.killpg,
object-bound simulated signal port. No host process is signalled; nothing
here validates Linux native signals.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_controller_dispatch
"""
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import control_plane  # noqa: E402
import termination  # noqa: E402
from synthetic import (SELF_PID, FakeGroupSignals, FakeKernel, FakePopen,  # noqa: E402
                       SimulatedObjectSignalPort)
from test_linux_exec import CONTROLLER, PARSERS, no_sleep  # noqa: E402

CONTROLLER_REL = "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py"
TERM, KILL = int(signal.SIGTERM), int(signal.SIGKILL)


TESTSUPPORT = os.path.join(HERE, "testsupport")


def load_bundled(rel, name):
    """Exact bundled source bytes (sha256-checked against MANIFEST.json)."""
    with open(os.path.join(TESTSUPPORT, "MANIFEST.json")) as fh:
        manifest = json.load(fh)
    with open(os.path.join(TESTSUPPORT, rel), "rb") as fh:
        raw = fh.read()
    if hashlib.sha256(raw).hexdigest() != manifest["files"][rel]["sha256"]:
        raise RuntimeError("BUNDLED_BASELINE_HASH_MISMATCH:" + rel)
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = os.path.join(TESTSUPPORT, rel)
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module


def load_frozen_controller():
    """The accepted 7a90d33 controller bytes, as a separate module."""
    return load_bundled("baseline_7a90d33/stage_b_controller.py",
                        "stage_b_controller_frozen_7a90d33")


FROZEN = load_frozen_controller()


class SysAs:
    """Module-local `sys` with an overridden platform."""

    def __init__(self, platform):
        self.platform = platform

    def __getattr__(self, name):
        return getattr(sys, name)


def world(extra_descendant=True):
    """SELF -> worker root R (own group/session) [-> descendant D in R's group]."""
    k = FakeKernel()
    root = k.spawn(SELF_PID)
    desc = k.spawn(root.pid, pgid=root.pid, session=root.pid, rss_kb=4000) \
        if extra_descendant else None
    return k, root, desc


def backend(controller, k):
    from synthetic import FakeProcSource
    return control_plane.linux_backend(controller, FakeProcSource(k),
                                       PARSERS.parse_proc_stat, sleep=no_sleep)


class KillpgRecorder:
    """Replaces os.killpg; applies FakeGroupSignals effects and records."""

    def __init__(self, k, ignore_term=()):
        self.signals = FakeGroupSignals(k, ignore_term)

    def __call__(self, pgid, signum):
        self.signals.kill(pgid, signum)

    @property
    def calls(self):
        return self.signals.calls


def linux_context(controller, b, route, run_id="DEV-RUN", generation=1):
    return controller.RunContext(run_id=run_id, generation=generation,
                                 native_backend=b, termination=route,
                                 clock=lambda: k_clock(b), sleep=lambda s: None,
                                 dispatch_latch=controller.DispatchLatch())


def k_clock(b):
    return b._source.k.clock


def run_timeout(controller, k, root, *, platform, route=None, during_grace=None,
                ignore_term=(), sampler_ticks=1, pass_backend=True):
    """Drive the controller's own exact_timeout_state_machine synthetically."""
    b = backend(controller, k)
    sampler = control_plane.make_sampler(controller, root.pid, b)
    for _ in range(sampler_ticks):
        control_plane.sample_once(sampler)
    popen = FakePopen(k, root.pid)
    waits = []

    def waiter(process, seconds):
        waits.append(seconds)
        if during_grace:
            during_grace(k)
        return process.poll() is not None

    killpg = KillpgRecorder(k, ignore_term)
    outcome = {}
    context = None
    if route is not None:
        context = linux_context(controller, b if pass_backend else None, route)
        context.attach_root(popen)
    with mock.patch.object(controller, "sys", SysAs(platform)), \
            mock.patch.object(os, "killpg", killpg):
        try:
            args = (popen, waiter, sampler.owned_identity_snapshot,
                    b if pass_backend and context is None else None)
            outcome["result"] = (
                controller.exact_timeout_state_machine(*args, run_context=context)
                if context is not None
                else controller.exact_timeout_state_machine(*args))
        except controller.StopSignal as exc:
            outcome["stop"] = (exc.stop_id, exc.detail.split(":")[0])
    outcome["killpg"] = list(killpg.calls)
    outcome["waits"] = waits
    return outcome


class LinuxUnregisteredTests(unittest.TestCase):
    """Default Linux: no survivor authority, no group signal, no fallback."""

    def test_timeout_refused_before_any_signal(self):
        k, root, _ = world()
        out = run_timeout(CONTROLLER, k, root, platform="linux")
        self.assertEqual(out["stop"], ("SB_STOP_TIMEOUT_TERMINATION",
                                       "unsupported_platform_no_termination_authority"))
        self.assertEqual((out["killpg"], out["waits"]), ([], []))

    def test_frozen_controller_did_fall_through_to_blind_killpg(self):
        # Evidence for the change: the HEAD controller on Linux emits
        # SIGTERM then, after its process-table probe fails, SIGKILL.
        k, root, _ = world()
        out = run_timeout(FROZEN, k, root, platform="linux", ignore_term={root.pid + 1})
        self.assertEqual([s for _, s in out["killpg"]][:2], [TERM, KILL])

    def test_every_posix_signal_site_refuses(self):
        k, root, _ = world()
        popen = FakePopen(k, root.pid)
        killpg = KillpgRecorder(k)
        with mock.patch.object(CONTROLLER, "sys", SysAs("linux")), \
                mock.patch.object(os, "killpg", killpg), \
                mock.patch.object(CONTROLLER, "PROCESS_TREE_FORCE_VERIFY_SECONDS", 0.01):
            context = CONTROLLER.default_run_context(None)
            context.dispatch_latch = CONTROLLER.DispatchLatch()
            context.attach_root(popen)
            self.assertFalse(CONTROLLER._cooperative_stop(popen, context))
            self.assertFalse(CONTROLLER._cooperative_stop(popen, None))
            cleanup = CONTROLLER._timeout_authority_failure_cleanup(popen, context)
            with self.assertRaisesRegex(CONTROLLER.StopSignal, "process_group_force_failed"):
                CONTROLLER._force_live_processes(popen, {root.pid}, {}, 1.0,
                                                 None, context)
            with self.assertRaises(CONTROLLER.StopSignal):
                CONTROLLER._force_terminate_tree(popen, {root.pid: ""}, None, context)
        self.assertIsInstance(context.termination, CONTROLLER.NoTerminationAuthority)
        self.assertFalse(cleanup["force_process_group_signal_emitted"])
        self.assertIn("UNSUPPORTED_PLATFORM_NO_ROOT_AUTHORITY",
                      cleanup["signal_outcomes"][0]["outcome"])
        self.assertTrue(cleanup["dispatch_blocked"])
        self.assertEqual(killpg.calls, [])
        self.assertIsNone(popen.poll())      # nothing happened to the worker

    def test_other_posix_platform_also_refused(self):
        k, root, _ = world()
        out = run_timeout(CONTROLLER, k, root, platform="freebsd13")
        self.assertIn("stop", out)
        self.assertEqual(out["killpg"], [])

    def test_sampler_factory_still_refuses_linux_and_default_has_no_authority(self):
        with mock.patch.object(CONTROLLER, "sys", SysAs("linux")):
            with self.assertRaisesRegex(CONTROLLER.NativeSamplerCapabilityError,
                                        "UNSUPPORTED_PLATFORM_NO_FALLBACK"):
                CONTROLLER._sampler_capability_backend()
            context = CONTROLLER.default_run_context(object())
        self.assertIsInstance(context.termination, CONTROLLER.NoTerminationAuthority)
        self.assertFalse(context.has_signal_authority)
        self.assertFalse(hasattr(CONTROLLER, "_LINUX_DEVELOPMENT_ROUTE"))
        self.assertFalse(hasattr(CONTROLLER, "register_linux_development_route"))


class LinuxRouteSyntheticTests(unittest.TestCase):
    """Registered development route with a SYNTHETIC signal port."""

    def route(self, k, ignore_term=()):
        return termination.LinuxDevelopmentRoute(
            CONTROLLER, SimulatedObjectSignalPort(k, ignore_term))

    def test_cooperative_exit_during_grace(self):
        k, root, desc = world()
        route = self.route(k)
        out = run_timeout(CONTROLLER, k, root, platform="linux", route=route)
        r = out["result"]
        self.assertEqual(out["waits"], [60])
        # Per-object delivery to every proven member (what killpg reached).
        self.assertEqual(sent(route), [(root.pid, TERM), (desc.pid, TERM)])
        self.assertEqual((r["cooperative_stop_request_emitted"], r["cooperative_outcome"],
                          r["force_terminate_process_tree_executed"]),
                         (True, "EXITED_DURING_GRACE", False))
        self.assertEqual(out["killpg"], [])

    def test_descendant_survives_grace_then_validated_force(self):
        k, root, desc = world()
        route = self.route(k, ignore_term={desc.pid})
        out = run_timeout(CONTROLLER, k, root, platform="linux", route=route)
        r = out["result"]
        self.assertEqual(sent(route), [(root.pid, TERM), (desc.pid, TERM),
                                       (desc.pid, KILL)])
        self.assertEqual(r["survivor_pids_after_grace"], [desc.pid])
        self.assertTrue(r["descendant_survived_grace"])
        self.assertTrue(r["whole_process_tree_quiescent"])
        self.assertEqual(route.log[-1]["members"], [desc.pid])
        self.assertEqual(out["killpg"], [])

    def test_route_without_bound_backend_refused(self):
        k, root, _ = world()
        route = self.route(k)
        out = run_timeout(CONTROLLER, k, root, platform="linux", route=route,
                          pass_backend=False)
        self.assertEqual(out["stop"][1], "run_context_requires_bound_backend")
        self.assertEqual(sent(route), [])

    def test_root_pid_reuse_during_grace_no_force(self):
        k, root, desc = world(extra_descendant=False)
        route = self.route(k, ignore_term={root.pid})
        out = run_timeout(CONTROLLER, k, root, platform="linux", route=route,
                          during_grace=lambda kk: kk.reuse(root.pid))
        self.assertEqual(out["stop"][0], "SB_STOP_TIMEOUT_TERMINATION")
        self.assertEqual(sent(route), [(root.pid, TERM)])     # no SIGKILL

    def test_descendant_escaping_group_during_grace_fails_closed(self):
        k, root, desc = world()
        route = self.route(k, ignore_term={desc.pid})

        def escape(kk):
            kk.procs[desc.pid].pgid = 5700
        out = run_timeout(CONTROLLER, k, root, platform="linux", route=route,
                          during_grace=escape)
        self.assertEqual(out["stop"][0], "SB_STOP_TIMEOUT_TERMINATION")
        self.assertEqual(sent(route), [(root.pid, TERM), (desc.pid, TERM)])

    def test_native_port_unavailable_never_claims_quiescence(self):
        k, root, desc = world()
        port = termination.NativeTerminationUnavailable(CONTROLLER.GroupSignalRefused)
        route = termination.LinuxDevelopmentRoute(CONTROLLER, port)
        with mock.patch.object(CONTROLLER, "PROCESS_TREE_FORCE_VERIFY_SECONDS", 0.05):
            out = run_timeout(CONTROLLER, k, root, platform="linux", route=route)
        self.assertEqual(out["stop"], ("SB_STOP_TIMEOUT_TERMINATION",
                                       "process_group_force_failed"))
        # Only the refused root acquisition reached the port; no signal call.
        self.assertEqual(port.calls, [("open", root.pid)])
        self.assertEqual({p.state for p in (root, desc)}, {"S"})   # no effect

    def group_signal(self, k, b, pgid, signum=signal.SIGKILL, route=None):
        route = route or self.route(k)
        context = linux_context(CONTROLLER, b, route)
        popen = FakePopen(k, getattr(b, "_authority_pgid", None) or pgid)
        try:
            context.attach_root(popen)
            context.group_signal(pgid, signum, None)
            return "SENT", route
        except ProcessLookupError:
            return "ABSENT", route
        except CONTROLLER.GroupSignalRefused as exc:
            return exc.strerror, route

    def bound(self, k, root):
        b = backend(CONTROLLER, k)
        control_plane.make_sampler(CONTROLLER, root.pid, b)
        return b

    def test_group_signal_validation(self):
        k, root, desc = world()
        b = self.bound(k, root)
        self.assertEqual(self.group_signal(k, b, root.pid, signal.SIGUSR1)[0],
                         "SIGNAL_NOT_ALLOWED")
        self.assertEqual(self.group_signal(k, b, 4100)[0],
                         "GROUP_AUTHORITY_NOT_BOUND_TO_TARGET")
        self.assertEqual(self.group_signal(k, object(), root.pid)[0],
                         "BACKEND_NOT_LINUX_DEVELOPMENT")
        k.read_errors[(4100, "stat")] = 13
        self.assertEqual(self.group_signal(k, b, root.pid)[0],
                         "GROUP_CENSUS_REFUSED:PROC_CENSUS_READ_FAILED")
        del k.read_errors[(4100, "stat")]
        k.reuse(root.pid)
        self.assertEqual(self.group_signal(k, b, root.pid)[0],
                         "GROUP_LEADER_IDENTITY_CHANGED")

    def test_pgid_reuse_after_retirement_refused(self):
        k, root, desc = world(extra_descendant=False)
        b = self.bound(k, root)
        k.exit(root.pid)
        del k.procs[root.pid]
        live, _ = b.live_owned_tree({root.pid: (root.pid, root.starttime, 0)})
        self.assertEqual((live, b._group_retired), ({}, True))
        self.assertEqual(self.group_signal(k, b, root.pid)[0], "ABSENT")
        stranger = k.spawn(1, pgid=root.pid, session=root.pid)   # PGID reused
        outcome, route = self.group_signal(k, b, root.pid)
        self.assertEqual(outcome, "PGID_REUSE_AFTER_RETIREMENT")
        self.assertEqual(sent(route), [])
        self.assertEqual(k.procs[stranger.pid].state, "S")

    def test_run_context_requires_termination_provider(self):
        with self.assertRaises(TypeError):
            CONTROLLER.RunContext(run_id="X", generation=1, native_backend=None,
                                  termination=object())


class DarwinDifferentialTests(unittest.TestCase):
    """Patched vs frozen HEAD controller with sys.platform == 'darwin'.

    The Darwin branch runs its shared algorithm on an injected backend that
    implements the same protocol; os.killpg is a recorder. Outputs and the
    exact signal sequences must be identical.
    """

    SCENARIOS = {
        "cooperative": dict(),
        "descendant_survives_grace": dict(ignore_desc=True),
        "root_reuse_during_grace": dict(ignore_root=True, reuse_root=True),
        "descendant_escape_during_grace": dict(ignore_desc=True, escape=True),
    }

    def scenario(self, controller, ignore_desc=False, ignore_root=False,
                 reuse_root=False, escape=False):
        k, root, desc = world()
        ignore = ({desc.pid} if ignore_desc else set()) | ({root.pid} if ignore_root else set())

        def during(kk):
            if reuse_root:
                kk.reuse(root.pid)
            if escape:
                kk.procs[desc.pid].pgid = 5700
        return run_timeout(controller, k, root, platform="darwin",
                           during_grace=during, ignore_term=ignore)

    # Intentional, listed bounded-cleanup change: one added result key.
    ADDED_RESULT_KEYS = {"bounded_cleanup_deadline"}

    def test_timeout_state_machine_identical(self):
        for name, kwargs in self.SCENARIOS.items():
            with self.subTest(name):
                frozen = self.scenario(FROZEN, **kwargs)
                patched = self.scenario(CONTROLLER, **kwargs)
                if "result" in patched:
                    added = set(patched["result"]) - set(frozen["result"])
                    self.assertEqual(added, self.ADDED_RESULT_KEYS)
                    for key in added:
                        patched["result"].pop(key)
                self.assertEqual(patched, frozen)
                self.assertTrue(frozen["killpg"])   # Darwin really signals

    def test_authority_failure_cleanup_signal_sequence_preserved(self):
        """Preserved: one SIGKILL to the dedicated group, root reaped, never
        quiescent. Intentional change: the record gains separate
        output/sampler/custody/deadline fields and a dispatch decision."""
        outs = []
        for controller in (FROZEN, CONTROLLER):
            k, root, _ = world()
            killpg = KillpgRecorder(k)
            with mock.patch.object(controller, "sys", SysAs("darwin")), \
                    mock.patch.object(os, "killpg", killpg):
                cleanup = controller._timeout_authority_failure_cleanup(FakePopen(k, root.pid))
            outs.append((cleanup, killpg.calls))
        self.assertEqual(outs[0][1], outs[1][1])
        self.assertEqual(outs[1][1], [(outs[1][1][0][0], KILL)])
        for key in ("force_process_group_signal_emitted", "root_process_reaped",
                    "native_survivor_state", "whole_process_tree_quiescent"):
            self.assertEqual(outs[1][0][key], outs[0][0][key], key)

    def test_sampler_ticks_identical(self):
        reports = []
        for controller in (FROZEN, CONTROLLER):
            k, root, desc = world()
            s = control_plane.make_sampler(controller, root.pid, backend(controller, k))
            ticks = [control_plane.sample_once(s)]
            k.exit(desc.pid)
            ticks.append(control_plane.sample_once(s))
            reports.append((ticks, control_plane.sampler_report(s)["maximum_bytes"]))
        self.assertEqual(reports[0], reports[1])

    def test_only_darwin_authority_calls_killpg(self):
        with open(CONTROLLER.__file__) as fh:
            src = fh.read()
        self.assertEqual(src.count("os.killpg("), 2)
        darwin = src[src.index("class _DarwinGroupRootAuthority"):
                     src.index("CLOSED_CUSTODY_OUTCOMES")]
        self.assertEqual(darwin.count("os.killpg("), 2)
        self.assertIn('DarwinKillpgAuthority() if sys.platform == "darwin"', src)


def sent(route):
    """Signals the object port actually delivered (pid, signum)."""
    return [(c[1], c[3]) for c in getattr(route.port, "calls", ())
            if c[0] == "signal" and c[4] == "DELIVERED"]


if __name__ == "__main__":
    unittest.main()
