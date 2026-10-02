"""NRP3_IMPL001 pure tests: fake sys_ports only (no fork, pidfd, /proc,
signal or ctypes).  Run only under the NRP2 pure guard with an explicit ID
manifest.  T16 injects fake p18 module objects; no real adapter backend or
NativeSyscalls is ever constructed here."""
import ast
import errno
import hashlib
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXEC = os.path.normpath(os.path.join(HERE, "..", "..", "exec_preflight"))
for _p in (HERE, EXEC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import stage_b_controller as C  # noqa: E402
import stage_b_dispatch_journal as J  # noqa: E402
import termination  # noqa: E402
import linux_entry  # noqa: E402
import native_root_port as N  # noqa: E402

PID, ME, START = 4242, 1000, 777
BOOT = "0123abcd-0123-4567-89ab-0123456789ab"
FD = 9
PORT_SRC = os.path.join(HERE, "native_root_port.py")

ACQUIRE_LOG = ["getpid", "validate_environment", "child_stat", "wait_nowait",
               "child_stat", "boot_id", "getpid", "pidfd_open", "child_stat",
               "wait_nowait", "validate_environment", "read_fdinfo", "boot_id"]


class FakePidfdError(RuntimeError):
    def __init__(self, code, operation="", error_number=None):
        self.code, self.operation, self.errno = code, operation, error_number
        super().__init__("%s:%s:errno=%s" % (code, operation, error_number))


class FakeSys:
    """Ordered call log; `fail` maps a step key to an exception (or callable)."""

    def __init__(self, **fail):
        self.log, self.fail = [], dict(fail)
        self.env_calls = 0
        self.stat_calls = 0
        self.boot_calls = 0
        self.pid = ME
        self.env = {"handler": 0, "flags": 0, "task_count": 1, "python_threads": 1}
        self.fdinfo = b"pos:\t0\nflags:\t02000002\nPid:\t%d\n" % PID

    def _maybe(self, key):
        error = self.fail.get(key)
        if error is not None:
            raise error

    def getpid(self):
        self.log.append("getpid")
        return self.pid

    def validate_environment(self):
        self.log.append("validate_environment")
        self.env_calls += 1
        self._maybe("env%d" % self.env_calls)
        env = self.env
        if env["handler"] != 0:
            raise FakePidfdError("SIGCHLD_MUST_BE_DEFAULT")
        if env["flags"] & 2:
            raise FakePidfdError("SA_NOCLDWAIT_UNSUPPORTED")
        if env["task_count"] != 1 or env["python_threads"] != 1:
            raise FakePidfdError("CONCURRENT_REAPER_UNSUPPORTED")

    def child_stat(self, pid):
        self.log.append("child_stat")
        self.stat_calls += 1
        self._maybe("stat%d" % self.stat_calls)
        value = self.fail.get("stat_value%d" % self.stat_calls)
        return value if value is not None else (pid, ME, START)

    def wait_nowait(self, pid):
        self.log.append("wait_nowait")
        self._maybe("wait%d" % self.log.count("wait_nowait"))
        return bool(self.fail.get("zombie", False))

    def boot_id(self):
        self.log.append("boot_id")
        self.boot_calls += 1
        return self.fail.get("boot%d" % self.boot_calls, BOOT)

    def pidfd_open(self, pid):
        self.log.append("pidfd_open")
        self._maybe("open")
        return FD

    def open_failed_without_fd(self, error):
        return isinstance(error, FakePidfdError) and error.code == "SYSCALL_ERROR"

    def read_fdinfo(self, fd):
        self.log.append("read_fdinfo")
        return self.fail.get("fdinfo", self.fdinfo)

    def close_fd(self, fd):
        self.log.append("close_fd")
        self._maybe("close")


class HandoffInterrupt(FakeSys):
    """pidfd_open 'returns' an fd inside the fake, then an async exception
    lands before the value reaches the port (models the handoff window)."""

    def pidfd_open(self, pid):
        self.log.append("pidfd_open")
        self.returned_fd = FD
        raise KeyboardInterrupt("HANDOFF_WINDOW")


class Proc:
    def __init__(self, pid=PID, returncode=None):
        self.pid, self.returncode = pid, returncode


def build(sys_ports=None, run_id="R1"):
    sys_ports = FakeSys() if sys_ports is None else sys_ports
    port = N.PidfdRootPort(sys_ports, C.GroupSignalRefused)
    route = N.NativeRootRoute(C, termination, port, run_id, "OWNER", 1)
    latch = C.DispatchLatch()
    context = C.RunContext(run_id=run_id, generation=1, native_backend=object(),
                           termination=route, clock=lambda: 0.0,
                           sleep=lambda s: None, dispatch_latch=latch)
    return sys_ports, port, route, context


def finish(context):
    """The controller layer that owns the dispatch latch (_finish_custody)."""
    deadline = C.CleanupDeadline(lambda: 0.0, 5.0, "NRP3_TEST")
    return C._finish_custody(context, deadline, [])


def root_row(route):
    return route.table.report()["capabilities"][0]


class T01DefaultDenial(unittest.TestCase):
    # definition_sha256 values of INPUTS/CURRENT_GAPS.json (G1, G8); method:
    # sha256 of source lines lineno..end_lineno joined by "\n" plus "\n".
    EXPECTED = {
        ("exec_preflight/stage_b_controller.py", "default_run_context"):
            "2b88c7b10fd444b9e3432f068470c4c30455d98452ae6937e00f6233396f85e6",
        ("exec_preflight/stage_b_controller.py", "_sampler_capability_backend"):
            "e4acd27ab0a769d37a7b99f4a29acd7837a4e840a592e4c35dc8cfbd19d018fe",
        ("exec_preflight/stage_b_controller.py", "NoTerminationAuthority"):
            "33d77abca57028a2dc82df49e984c2fe089b503f90877a968d3baab5b8e5b033",
        ("linuxport001/linux_exec/termination.py", "NativeTerminationUnavailable"):
            "e10b72184f80e43add5d5af355b43adce456ad9de704b89dff3617ee38c14c9a",
    }

    def test_default_denial_definition_hashes(self):
        root = os.path.normpath(os.path.join(HERE, "..", ".."))
        for (rel, name), expected in self.EXPECTED.items():
            with open(os.path.join(root, rel), "rb") as fh:
                src = fh.read()
            nodes = [n for n in ast.parse(src).body if getattr(n, "name", None) == name]
            self.assertEqual(len(nodes), 1, name)
            lines = src.split(b"\n")[nodes[0].lineno - 1:nodes[0].end_lineno]
            got = hashlib.sha256(b"\n".join(lines) + b"\n").hexdigest()
            self.assertEqual(got, expected, name)


class T02NativeEntry(unittest.TestCase):
    def _call(self, **kw):
        made = []
        entry_ns = types.SimpleNamespace(
            OPT_IN=linux_entry.OPT_IN,
            LinuxControllerEntry=lambda *a, **k: made.append("entry"))
        args = dict(opt_in=linux_entry.OPT_IN, run_id="R1", generation=1, owner="O")
        args.update(kw)
        try:
            N.build_native_entry(C, termination, entry_ns,
                                 lambda: made.append("sys_ports") or FakeSys(), object(),
                                 lambda: 0.0, lambda s: None, **args)
        except C.NativeSamplerCapabilityError as error:
            return str(error), made
        return None, made

    def test_refusals_before_any_object(self):
        cases = [({"opt_in": None}, "LINUX_NATIVE_NOT_OPTED_IN"),
                 ({"opt_in": "WRONG"}, "LINUX_NATIVE_NOT_OPTED_IN"),
                 ({"modeled_identity": lambda p: "tok"},
                  "LINUX_NATIVE_UNEXPECTED_ARGUMENT:modeled_identity"),
                 ({"extra": 1}, "LINUX_NATIVE_UNEXPECTED_ARGUMENT:extra")]
        for kw, code in cases:
            message, made = self._call(**kw)
            self.assertIsNotNone(message, kw)
            self.assertIn(code, message)
            self.assertEqual(made, [])         # no entry, RunContext or sys_ports
        with self.assertRaises(TypeError):     # no modeled_identity parameter
            N.build_native_entry(C, termination, linux_entry, FakeSys, object(),
                                 lambda: 0.0, lambda s: None, linux_entry.OPT_IN,
                                 "R1", 1, "O")

    def test_missing_opt_in_keyword_refused(self):
        with self.assertRaises(TypeError):
            N.build_native_entry(C, termination, linux_entry, FakeSys, object(),
                                 lambda: 0.0, lambda s: None, run_id="R1",
                                 generation=1, owner="O")

    def test_opt_in_entry_builds_unwrapped_route(self):
        made = []
        entry = N.build_native_entry(C, termination, linux_entry,
                                     lambda: made.append(1) or FakeSys(), object(),
                                     lambda: 0.0, lambda s: None,
                                     opt_in=linux_entry.OPT_IN, run_id="R1",
                                     generation=1, owner="O")
        self.assertIsNone(entry.modeled_identity)
        self.assertEqual(made, [])
        context = entry.run_context_factory(object())
        self.assertIsInstance(context.termination, N.NativeRootRoute)
        self.assertEqual(made, [1])


class T02bWrapperRefusal(unittest.TestCase):
    def test_wrapped_route_refused_at_admit_and_acquire(self):
        sys_ports = FakeSys()
        route_box = []

        def factory():
            port = N.PidfdRootPort(sys_ports, C.GroupSignalRefused)
            route_box.append(N.NativeRootRoute(C, termination, port, "R1", "O", 1))
            return route_box[0]
        entry = linux_entry.LinuxControllerEntry(
            C, opt_in=linux_entry.OPT_IN, capability_backend=object(),
            termination_factory=factory, clock=lambda: 0.0, sleep=lambda s: None,
            run_id="R1", generation=1, modeled_identity=lambda p: "tok")
        context = entry.run_context_factory(object())
        self.assertIsInstance(context.termination, linux_entry.ModeledRootIdentity)
        with self.assertRaises(C.GroupSignalRefused) as caught:
            context.admit()
        self.assertIn("NATIVE_ROUTE_WRAPPED_OR_FOREIGN_TERMINATION", str(caught.exception))
        self.assertEqual(sys_ports.log, [])
        with self.assertRaises(C.GroupSignalRefused) as caught:
            context.termination.acquire_root(Proc(), context)
        self.assertIn("NATIVE_ROUTE_WRAPPED_OR_FOREIGN_TERMINATION", str(caught.exception))
        self.assertEqual(sys_ports.log, [])
        route = route_box[0]
        self.assertIsNone(getattr(route, "root_identity", None))
        self.assertNotIn("__getattr__", vars(N.NativeRootRoute))
        self.assertNotIn("root_identity", vars(N.NativeRootRoute))


class T03HappyPath(unittest.TestCase):
    def test_happy_path_real_run_context(self):
        sys_ports, port, route, context = build()
        context.admit()
        process = Proc()
        context.attach_root(process)
        self.assertEqual(context.root_authority_state, "ACQUIRED")
        cap = route.inner.root_cap
        self.assertEqual(cap.state, termination.LIVE)
        self.assertEqual(cap.acquisition["phase"], "REGISTERED_LIVE")
        self.assertEqual(cap.identity, (BOOT, PID, START))
        self.assertIsInstance(cap.identity[0], str)
        self.assertIs(type(cap.identity[1]), int)
        self.assertIs(type(cap.identity[2]), int)
        evidence = C._effect_evidence(process, context)
        self.assertIsNone(evidence["identity"])
        self.assertEqual(evidence["custody"], "REGISTERED")
        J.validate_effect_evidence(evidence)
        self.assertIsNone(getattr(context.termination, "root_identity", None))
        report = route.native_identity_report()
        self.assertEqual(report["label"], "NATIVE_OBSERVATION_NOT_JOURNAL_IDENTITY")
        self.assertIsNone(report["journal_identity"])
        self.assertFalse(report["provenance_recorded_in_journal"])
        self.assertEqual(cap.handle.proof["zombie_before"], False)
        self.assertEqual(context.close(), "CLOSED")
        self.assertTrue(context.closed)

    def test_zombie_before_accepted(self):
        sys_ports, port, route, context = build(FakeSys(zombie=True))
        context.admit()
        context.attach_root(Proc())
        self.assertEqual(context.root_authority_state, "ACQUIRED")
        self.assertTrue(route.inner.root_cap.handle.proof["zombie_before"])
        self.assertTrue(route.inner.root_cap.handle.proof["zombie_after"])


class T03bExactOrder(unittest.TestCase):
    def test_fake_log_exact(self):
        sys_ports, port, route, context = build()
        context.admit()
        self.assertEqual(sys_ports.log, ["validate_environment"])
        context.attach_root(Proc())
        self.assertEqual(sys_ports.log[1:], ACQUIRE_LOG)
        # A0 getpid and the owner sample inside PidfdRootPort.open are
        # separate entries; the owner sample immediately precedes pidfd_open.
        acquire = sys_ports.log[1:]
        self.assertEqual([i for i, s in enumerate(acquire) if s == "getpid"], [0, 6])
        self.assertEqual(acquire[7], "pidfd_open")
        del sys_ports.log[:]
        self.assertEqual(context.close(), "CLOSED")
        self.assertEqual(sys_ports.log, ["getpid", "close_fd"])


class T04Failures(unittest.TestCase):
    def _attach(self, sys_ports):
        _, port, route, context = build(sys_ports)
        context.admit()
        process = Proc()
        context.attach_root(process)
        return port, route, context, process

    def test_pre_open_failures(self):
        cases = {
            "A1_env": FakeSys(env2=FakePidfdError("SIGCHLD_MUST_BE_DEFAULT")),
            "A2_ppid": FakeSys(stat_value1=(PID, ME + 1, START)),
            "A2_pid": FakeSys(stat_value1=(PID + 1, ME, START)),
            "A3_echild": FakeSys(wait1=FakePidfdError("CHILD_ALREADY_REAPED_OR_NOT_OWNED")),
            "A4_mismatch": FakeSys(stat_value2=(PID, ME, START + 1)),
        }
        for name, sys_ports in cases.items():
            port, route, context, _ = self._attach(sys_ports)
            self.assertNotIn("pidfd_open", sys_ports.log, name)
            self.assertEqual(route.table.report()["capabilities"], [], name)
            self.assertTrue(context.root_authority_state.startswith("UNAVAILABLE:"), name)
            self.assertEqual(port.handles, [], name)

    def test_post_open_failures(self):
        cases = {
            "V1": FakeSys(stat_value3=(PID, ME, START + 5)),
            "V2": FakeSys(wait2=FakePidfdError("CHILD_ALREADY_REAPED_OR_NOT_OWNED")),
            "V3": FakeSys(env3=FakePidfdError("CONCURRENT_REAPER_UNSUPPORTED")),
            "V4_zero": FakeSys(fdinfo=b"pos:\t0\n"),
            "V4_two": FakeSys(fdinfo=b"Pid:\t%d\nPid:\t%d\n" % (PID, PID)),
            "V4_wrong": FakeSys(fdinfo=b"Pid:\t%d\n" % (PID + 1)),
            "V5": FakeSys(boot2="ffffffff-0123-4567-89ab-0123456789ab"),
        }
        for name, sys_ports in cases.items():
            port, route, context, process = self._attach(sys_ports)
            self.assertIn("pidfd_open", sys_ports.log, name)
            self.assertEqual(sys_ports.log.count("close_fd"), 1, name)
            self.assertTrue(context.root_authority_state.startswith("UNAVAILABLE:"), name)
            row = root_row(route)
            self.assertEqual(row["state"], termination.CLOSED, name)
            self.assertIn("verify_error", row["acquisition"], name)
            self.assertIsNone(row["close_error"], name)
            self.assertEqual(port.handles[0].custody, N.H_CLOSED, name)
            self.assertEqual(C._effect_evidence(process, context)["custody"],
                             "NOT_REGISTERED", name)
            self.assertEqual(context.close(), "CLOSED", name)
            self.assertEqual(sys_ports.log.count("close_fd"), 1, name)


class T04bVerifyAndCloseFail(unittest.TestCase):
    def test_verify_fail_and_close_fail(self):
        sys_ports, port, route, context = build(
            FakeSys(fdinfo=b"", close=OSError(errno.EIO, "close failed")))
        context.admit()
        context.attach_root(Proc())
        self.assertTrue(context.root_authority_state.startswith("UNAVAILABLE:"))
        row = root_row(route)
        self.assertEqual(row["state"], termination.CLOSE_FAILED)
        self.assertIn("PIDFD_PID_BINDING", row["acquisition"]["verify_error"])
        self.assertIn("OSError", row["close_error"])
        self.assertEqual(port.handles[0].custody, N.H_CLOSE_CALLED)
        outcome = context.close()
        self.assertTrue(outcome.startswith("CUSTODY_UNRESOLVED:"), outcome)
        self.assertFalse(context.closed)
        self.assertEqual(sys_ports.log.count("close_fd"), 1)
        self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:"))
        self.assertEqual(sys_ports.log.count("close_fd"), 1)
        # Latch adaptation: RunContext has no latch of its own; the controller's
        # _finish_custody blocks context.dispatch_latch on an unresolved close.
        self.assertTrue(finish(context).startswith("CUSTODY_UNRESOLVED:"))
        self.assertTrue(context.dispatch_latch.blocked)
        self.assertEqual(sys_ports.log.count("close_fd"), 1)


class T05OpenFailures(unittest.TestCase):
    def test_no_fd_open_error(self):
        error = FakePidfdError("SYSCALL_ERROR", "pidfd_open", errno.ESRCH)
        sys_ports, port, route, context = build(FakeSys(open=error))
        context.admit()
        process = Proc()
        context.attach_root(process)
        self.assertEqual(root_row(route)["state"], termination.OPEN_FAILED)
        self.assertEqual(port.handles[0].custody, N.H_NO_FD)
        self.assertEqual(context.root_authority_state,
                         "UNAVAILABLE:NATIVE_ROOT_ACQUISITION_REFUSED:SYSCALL_ERROR")
        self.assertEqual(sys_ports.log.count("close_fd"), 0)
        self.assertTrue(route.teardown(context)["resolved"])
        self.assertEqual(context.close(), "CLOSED")

    def test_translation_keeps_cause(self):
        error = FakePidfdError("SYSCALL_ERROR", "pidfd_open", errno.ESRCH)
        sys_ports, port, route, context = build(FakeSys(open=error))
        context.admit()
        with self.assertRaises(C.GroupSignalRefused) as caught:
            route.acquire_root(Proc(), context)
        self.assertIs(caught.exception.__cause__, error)


class T05bHandoffGap(unittest.TestCase):
    def test_async_exception_in_handoff_window(self):
        sys_ports, port, route, context = build(HandoffInterrupt())
        context.admit()
        with self.assertRaises(KeyboardInterrupt):
            context.attach_root(Proc())
        self.assertEqual(root_row(route)["state"], termination.OPEN_FAILED)
        self.assertEqual(port.handles[0].custody, N.H_OPEN_IN_FLIGHT)
        result = route.teardown(context)
        self.assertFalse(result["resolved"])
        self.assertTrue(result["outcome"].startswith("PORT_CUSTODY_UNRESOLVED:"))
        self.assertEqual(sys_ports.log.count("close_fd"), 0)
        self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:PORT_CUSTODY"))
        self.assertFalse(context.closed)


class T05cMemoryError(unittest.TestCase):
    def test_memory_error_in_open(self):
        sys_ports, port, route, context = build(FakeSys(open=MemoryError()))
        context.admit()
        context.attach_root(Proc())
        self.assertEqual(port.handles[0].custody, N.H_OPEN_IN_FLIGHT)
        self.assertEqual(context.root_authority_state,
                         "UNAVAILABLE:NATIVE_ROOT_ACQUISITION_REFUSED:MemoryError")
        self.assertFalse(route.teardown(context)["resolved"])
        self.assertFalse(context.closed)
        self.assertEqual(sys_ports.log.count("close_fd"), 0)


class T06InterruptInVerify(unittest.TestCase):
    def test_keyboard_interrupt_in_verify(self):
        sys_ports, port, route, context = build(FakeSys(wait2=KeyboardInterrupt()))
        context.admit()
        with self.assertRaises(KeyboardInterrupt):
            context.attach_root(Proc())
        self.assertEqual(sys_ports.log.count("close_fd"), 1)
        self.assertEqual(root_row(route)["state"], termination.CLOSED)
        self.assertEqual(context.root_authority_state, "NOT_ACQUIRED")
        self.assertEqual(port.handles[0].custody, N.H_CLOSED)


class T06bInterruptInClose(unittest.TestCase):
    def test_keyboard_interrupt_in_close_fd(self):
        sys_ports, port, route, context = build(FakeSys(close=KeyboardInterrupt()))
        context.admit()
        context.attach_root(Proc())
        with self.assertRaises(KeyboardInterrupt):
            context.close()
        self.assertEqual(root_row(route)["state"], termination.CLOSING)
        self.assertEqual(port.handles[0].custody, N.H_CLOSE_CALLED)
        self.assertFalse(route.teardown(context)["resolved"])
        self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:"))
        self.assertEqual(sys_ports.log.count("close_fd"), 1)


class T07CloseOnce(unittest.TestCase):
    def test_close_once(self):
        sys_ports, port, route, context = build()
        context.admit()
        context.attach_root(Proc())
        self.assertEqual(context.close(), "CLOSED")
        self.assertEqual(root_row(route)["state"], termination.CLOSED)
        self.assertEqual(sys_ports.log.count("close_fd"), 1)
        self.assertEqual(context.close(), "ALREADY_CLOSED")
        self.assertEqual(sys_ports.log.count("close_fd"), 1)


class T08CompletionCloseFails(unittest.TestCase):
    def test_eintr_and_ebadf_never_retried(self):
        for code in (errno.EINTR, errno.EBADF):
            sys_ports, port, route, context = build(
                FakeSys(close=OSError(code, os.strerror(code))))
            context.admit()
            context.attach_root(Proc())
            for _ in range(3):
                self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:"))
            self.assertEqual(root_row(route)["state"], termination.CLOSE_FAILED)
            self.assertEqual(sys_ports.log.count("close_fd"), 1)
            self.assertFalse(context.closed)
            self.assertTrue(finish(context).startswith("CUSTODY_UNRESOLVED:"))
            self.assertTrue(context.dispatch_latch.blocked)
            self.assertEqual(sys_ports.log.count("close_fd"), 1)


class T09OwnerChange(unittest.TestCase):
    def test_owner_pid_change_refuses_close(self):
        sys_ports, port, route, context = build()
        context.admit()
        context.attach_root(Proc())
        sys_ports.pid = ME + 1
        self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:"))
        row = root_row(route)
        self.assertEqual(row["state"], termination.CLOSE_FAILED)
        self.assertIn("PIDFD_OWNER_PROCESS_CHANGED", row["close_error"])
        self.assertEqual(sys_ports.log.count("close_fd"), 0)


class T10RootSignalRefused(unittest.TestCase):
    def test_root_signal_refused(self):
        sys_ports, port, route, context = build()
        context.admit()
        context.attach_root(Proc())
        del sys_ports.log[:]
        with self.assertRaises(C.GroupSignalRefused) as caught:
            context.root_authority.signal(15)
        self.assertIn("NRP3_NATIVE_SIGNAL_NOT_IMPLEMENTED", str(caught.exception))
        self.assertEqual(sys_ports.log, [])
        cap = route.inner.root_cap
        self.assertEqual(cap.leases, 0)
        self.assertEqual(cap.state, termination.LIVE)
        self.assertEqual(port.counters["signal_refused"], 1)


class T11GroupRefusals(unittest.TestCase):
    def test_group_and_object_refusals_first(self):
        sys_ports, port, route, context = build()
        context.admit()
        context.attach_root(Proc())
        calls = []
        route.inner._bind_context = lambda c: calls.append("bind")
        route.inner._member_cap = lambda *a: calls.append("member")
        route.table.acquire = lambda *a, **k: calls.append("acquire")

        class Backend:
            def __getattr__(self, name):
                calls.append("backend:" + name)
                raise AssertionError(name)
        context.native_backend = Backend()
        del sys_ports.log[:]
        with self.assertRaises(C.GroupSignalRefused) as caught:
            context.group_signal(PID, 15)
        self.assertIn("NATIVE_GROUP_SIGNAL_NOT_IN_NRP3_SCOPE", str(caught.exception))
        self.assertEqual(calls, [])
        self.assertEqual(sys_ports.log, [])
        for call in (lambda: port.object_present(None),
                     lambda: port.object_matches(None, PID, START)):
            with self.assertRaises(C.GroupSignalRefused):
                call()
        kinds = [c["kind"] for c in route.table.report()["capabilities"]]
        self.assertEqual(kinds, ["ROOT"])


class T12ScheduledTeardown(unittest.TestCase):
    def test_teardown_in_flight_and_late_return(self):
        for point in ("ACQUIRE_BEFORE_OPEN", "ACQUIRE_OPENED", "ACQUIRE_VERIFIED"):
            sys_ports, port, route, context = build()
            context.admit()
            seen = []

            def schedule(name, cap, point=point, route=route, context=context):
                if name == point:
                    seen.append(route.teardown(context))
            route.table.schedule_point = schedule
            context.attach_root(Proc())
            self.assertEqual(len(seen), 1, point)
            self.assertFalse(seen[0]["resolved"], point)
            self.assertNotEqual(seen[0]["outcome"], "ALL_CLOSED", point)
            self.assertTrue(context.root_authority_state.startswith("UNAVAILABLE:"), point)
            self.assertIn("TABLE_INVALIDATED", context.root_authority_state, point)
            row = root_row(route)
            self.assertIn("LATE_RETURN_AFTER_INVALIDATION",
                          row["acquisition"]["rollback_reason"], point)
            self.assertEqual(sys_ports.log.count("close_fd"), 1, point)
            route.table.schedule_point = None
            self.assertTrue(route.teardown(context)["resolved"], point)


class T13PreflightRefusal(unittest.TestCase):
    def test_p0_environment_failures(self):
        cases = {"handler": ("handler", 1, "SIGCHLD_MUST_BE_DEFAULT"),
                 "nocldwait": ("flags", 2, "SA_NOCLDWAIT_UNSUPPORTED"),
                 "tasks": ("task_count", 2, "CONCURRENT_REAPER_UNSUPPORTED"),
                 "threads": ("python_threads", 2, "CONCURRENT_REAPER_UNSUPPORTED")}
        for name, (key, value, code) in cases.items():
            sys_ports, port, route, context = build()
            sys_ports.env[key] = value
            with self.assertRaises(C.GroupSignalRefused) as caught:
                context.admit()
            self.assertIn("NATIVE_ROOT_ACQUISITION_REFUSED:" + code,
                          str(caught.exception), name)
            self.assertFalse(context.admitted, name)
            self.assertEqual(sys_ports.log, ["validate_environment"], name)
            self.assertEqual(port.handles, [], name)


class T13bAcquisitionEnvironment(unittest.TestCase):
    def test_a1_pre_open_and_v3_rollback(self):
        a1 = FakeSys(env2=FakePidfdError("CONCURRENT_REAPER_UNSUPPORTED"))
        _, port, route, context = build(a1)
        context.admit()
        context.attach_root(Proc())
        self.assertEqual(context.root_authority_state,
                         "UNAVAILABLE:NATIVE_ROOT_ACQUISITION_REFUSED:"
                         "CONCURRENT_REAPER_UNSUPPORTED")
        self.assertNotIn("pidfd_open", a1.log)
        v3 = FakeSys(env3=FakePidfdError("CONCURRENT_REAPER_UNSUPPORTED"))
        _, port, route, context = build(v3)
        context.admit()
        context.attach_root(Proc())
        self.assertIn("CONCURRENT_REAPER_UNSUPPORTED", context.root_authority_state)
        self.assertEqual(v3.log.count("close_fd"), 1)
        self.assertEqual(root_row(route)["state"], termination.CLOSED)


class T14NonPidfdError(unittest.TestCase):
    def test_value_error_translated(self):
        error = ValueError("bad stat field")
        sys_ports, port, route, context = build(FakeSys(stat1=error))
        context.admit()
        context.attach_root(Proc())
        self.assertEqual(context.root_authority_state,
                         "UNAVAILABLE:NATIVE_ROOT_ACQUISITION_REFUSED:ValueError")
        self.assertEqual(route.table.report()["capabilities"], [])
        self.assertEqual(port.handles, [])
        _, _, route2, context2 = build(FakeSys(stat1=ValueError("x")))
        context2.admit()
        with self.assertRaises(C.GroupSignalRefused) as caught:
            route2.acquire_root(Proc(), context2)
        self.assertIsInstance(caught.exception.__cause__, ValueError)


class T15StaticPort(unittest.TestCase):
    def setUp(self):
        with open(PORT_SRC, "rb") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def _func(self, cls, name):
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == name:
                        return item
        raise AssertionError((cls, name))

    def test_forbidden_tokens_absent(self):
        text = self.src.decode("utf-8")
        for token in ("os.kill", "killpg", "kill", "pidfd_send_signal", ".send(",
                      "prctl", "waitpid", "os.wait", "os.pidfd_open",
                      "acquire_direct_child", "open_self", "_member_cap",
                      "root_identity", "__getattr__", "ctypes"):
            self.assertNotIn(token, text, token)
        consts = [n.value for n in ast.walk(self.tree) if isinstance(n, ast.Constant)]
        self.assertNotIn(424, consts)
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for name in ("kill", "killpg", "waitpid", "ctypes", "root_identity"):
            self.assertNotIn(name, names | attrs)

    def test_close_sites_and_open_shape(self):
        sites = {}
        for cls in [n for n in self.tree.body if isinstance(n, ast.ClassDef)]:
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr in ("close_fd", "close")):
                        owner = ast.unparse(node.func.value) if hasattr(ast, "unparse") \
                            else ast.dump(node.func.value)
                        sites.setdefault(node.func.attr, []).append(
                            (cls.name, fn.name, owner))
        self.assertEqual([s[:2] for s in sites["close_fd"]], [("PidfdRootPort", "close")])
        os_close = [s for s in sites.get("close", []) if s[2] in ("os", ast.dump(
            ast.Name(id="os", ctx=ast.Load())))]
        self.assertEqual([s[:2] for s in os_close], [("P18SysPorts", "close_fd")])
        self.assertEqual(len(sites.get("close", [])), 1)
        body = self._func("PidfdRootPort", "open").body
        tries = [i for i, s in enumerate(body) if isinstance(s, ast.Try)]
        self.assertEqual(len(tries), 1)
        self.assertEqual(len(body[tries[0]].body), 1)
        after = body[tries[0] + 1:]
        self.assertEqual([type(s).__name__ for s in after], ["Assign", "Return"])
        self.assertEqual(after[0].targets[0].attr, "custody")
        acquires = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "acquire"]
        self.assertTrue(acquires)
        for call in acquires:
            self.assertEqual(call.args[1].value, "ROOT")
        signal_fn = self._func("PidfdRootPort", "signal")
        self.assertIsInstance(signal_fn.body[-1], ast.Raise)
        group_fn = self._func("NativeRootRoute", "group_signal")
        self.assertEqual(len(group_fn.body), 1)
        self.assertIsInstance(group_fn.body[0], ast.Raise)
        for name in ("preflight", "acquire_root"):
            first = self._func("NativeRootRoute", name).body[0]
            self.assertIsInstance(first, ast.If)
            self.assertIn("termination", ast.dump(first.test))
            self.assertIsInstance(first.test.ops[0], ast.IsNot)
        handlers = [h for h in ast.walk(self.tree) if isinstance(h, ast.ExceptHandler)]
        for h in handlers:
            self.assertFalse(isinstance(h.type, ast.Name) and h.type.id == "BaseException")
            self.assertIsNotNone(h.type)


class FakeAcquisitionPolicy:
    def __init__(self, *flags):
        self.flags = flags


class FakeProcStat:
    def __init__(self, pid, ppid, starttime_ticks):
        self.pid, self.ppid, self.starttime_ticks = pid, ppid, starttime_ticks


def fake_p18(reads):
    """Fake p18 pidfd_primitives module object: records calls, touches no host."""
    calls = []

    class NativeSyscalls:
        def __init__(self):
            calls.append("NativeSyscalls()")
    mod = types.SimpleNamespace(
        PidfdError=FakePidfdError, AcquisitionPolicy=FakeAcquisitionPolicy,
        NativeSyscalls=NativeSyscalls,
        bounded_read=lambda path, bound: calls.append(("bounded_read", path, bound))
        or reads.get(path, b""),
        direct_child_stat=lambda pid: calls.append(("stat", pid))
        or FakeProcStat(pid, ME, START),
        wait_without_reaping=lambda pid: calls.append(("wait", pid)) or False,
        validate_acquisition_environment=lambda *a: calls.append("validate") or True)
    return mod, calls


class T16AdapterShape(unittest.TestCase):
    def test_construction_is_inert_and_policy_declared(self):
        mod, calls = fake_p18({})
        adapter = N.P18SysPorts(mod, types.SimpleNamespace())
        self.assertEqual(calls, [])
        self.assertEqual(adapter.policy.flags, (True, True, True))
        self.assertEqual(adapter.child_stat(PID), (PID, ME, START))

    def test_open_failed_without_fd_truth_table(self):
        mod, calls = fake_p18({})
        adapter = N.P18SysPorts(mod, types.SimpleNamespace())
        table = [
            (FakePidfdError("PIDFD_OPEN_ARGUMENT"), True),
            (FakePidfdError("SYSCALL_ERROR", "pidfd_open", 3), True),
            (FakePidfdError("ENOSYS_UNSUPPORTED", "pidfd_open", 38), True),
            (FakePidfdError("SYSCALL_ERROR", "sigaction_query", 1), False),
            (FakePidfdError("PROC_READ_ERROR", "pidfd_open"), False),
            (FakePidfdError("UNSUPPORTED_ARCH"), False),
            (MemoryError(), False), (OSError(errno.EBADF, "x"), False),
            (ValueError("SYSCALL_ERROR"), False),
        ]
        for error, expected in table:
            self.assertIs(adapter.open_failed_without_fd(error), expected, repr(error))
        self.assertEqual(calls, [])

    def test_boot_id_strict(self):
        good = BOOT.encode() + b"\n"
        for raw, ok in ((good, True), (BOOT.upper().encode(), False),
                        (b"", False), (BOOT.encode()[:-1], False),
                        (b"\xff" * 36, False), (BOOT.encode() + b"0", False)):
            mod, calls = fake_p18({N.BOOT_ID_PATH: raw})
            adapter = N.P18SysPorts(mod, types.SimpleNamespace())
            if ok:
                self.assertEqual(adapter.boot_id(), BOOT)
            else:
                with self.assertRaises(FakePidfdError):
                    adapter.boot_id()
            self.assertEqual(calls, [("bounded_read", N.BOOT_ID_PATH, 64)])

    def test_read_fdinfo_bound(self):
        mod, calls = fake_p18({})
        adapter = N.P18SysPorts(mod, types.SimpleNamespace())
        adapter.read_fdinfo(FD)
        self.assertEqual(calls, [("bounded_read", "/proc/self/fdinfo/%d" % FD, 8192)])


class T17TeardownOverlay(unittest.TestCase):
    class InnerTable:
        def __init__(self, resolved=True, raises=None):
            self.resolved, self.raises = resolved, raises

        def __call__(self, context, lock_timeout=None):
            if self.raises is not None:
                raise self.raises
            return {"resolved": self.resolved,
                    "outcome": "ALL_CLOSED" if self.resolved else "ROOT:1:CLOSING"}

    def _route(self, custody=None, inner=None):
        sys_ports, port, route, context = build()
        if custody is not None:
            handle = N.PidfdRootHandle(PID, ME)
            handle.custody = custody
            port.handles.append(handle)
        route.inner.teardown = inner or self.InnerTable()
        return sys_ports, port, route, context

    def test_five_states(self):
        for custody in (N.H_OPEN_IN_FLIGHT, N.H_NO_FD, N.H_OWNED,
                        N.H_CLOSE_CALLED, N.H_CLOSED):
            sys_ports, port, route, context = self._route(custody)
            result = route.teardown(context)
            if custody in (N.H_NO_FD, N.H_CLOSED):
                self.assertTrue(result["resolved"], custody)
                self.assertEqual(context.close(), "CLOSED")
                self.assertTrue(context.closed)
            else:
                self.assertFalse(result["resolved"], custody)
                self.assertTrue(result["outcome"].startswith("PORT_CUSTODY_UNRESOLVED:"))
                outcome = context.close()
                self.assertTrue(outcome.startswith("CUSTODY_UNRESOLVED:"), outcome)
                self.assertFalse(context.closed)
            self.assertEqual(sys_ports.log.count("close_fd"), 0)

    def test_inner_unresolved_port_resolved(self):
        sys_ports, port, route, context = self._route(
            N.H_CLOSED, self.InnerTable(resolved=False))
        self.assertFalse(route.teardown(context)["resolved"])
        self.assertTrue(context.close().startswith("CUSTODY_UNRESOLVED:"))
        self.assertFalse(context.closed)

    def test_inner_teardown_raises(self):
        for error in (C.GroupSignalRefused(errno.EPERM, "INNER_REFUSED"),
                      OSError(errno.EIO, "io"), RuntimeError("boom")):
            sys_ports, port, route, context = self._route(
                N.H_CLOSED, self.InnerTable(raises=error))
            with self.assertRaises(type(error)):
                route.teardown(context)
            outcome = context.close()
            self.assertTrue(outcome.startswith("CUSTODY_UNRESOLVED:TEARDOWN_FAILED"),
                            outcome)
            self.assertIn("TEARDOWN_FAILED", context.custody["outcome"])
            self.assertFalse(context.closed)
            self.assertEqual(sys_ports.log.count("close_fd"), 0)
