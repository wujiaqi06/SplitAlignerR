"""Focused tests for native_close_smoke.py harness helpers.

No native effects: no pidfd, no guard install, no real fork. Child lifecycle
faults are injected through a fake `ops` object passed to harness helpers
only; production modules are never mocked. Import-isolation tests run in
subprocesses so poisoned candidate modules never enter this process.

    cd dev_build001 && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_native_close_smoke

SMOKE_PINS overrides the pins file (default: DEV_BUILD001 INPUTS/SOURCE_PINS.json).
"""
import copy
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

import native_close_smoke as h

HERE = os.path.dirname(os.path.realpath(__file__))
PINS = os.environ.get("SMOKE_PINS", os.path.realpath(os.path.join(
    HERE, "..", "..", "..", "..", "..", "INPUTS", "SOURCE_PINS.json")))
PRIOR_EVIDENCE = os.environ.get("SMOKE_PRIOR_EVIDENCE", os.path.realpath(
    os.path.join(HERE, "..", "..", "..", "..", "..", "RUNS",
                 "native_attempt_1", "evidence", "evidence.json")))
POISON = b'open(__import__("os").environ["POISON_MARKER"], "w").close()\n'


def read_pin_rows():
    with open(PINS) as fh:
        return json.load(fh)


def write_json(path, value):
    with open(path, "w") as fh:
        json.dump(value, fh)
    return path


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smoke_test_")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.tree = os.path.join(self.tmp, "p18")
        os.mkdir(self.tree)
        for name in h.EXPECTED_SOURCES:
            shutil.copyfile(os.path.join(h.SOURCE_ROOT, name),
                            os.path.join(self.tree, name))
        self.marker = os.path.join(self.tmp, "SIDE_EFFECT_MARKER")

    def poison(self, name="ledger.py"):
        path = os.path.join(self.tree, name)
        with open(path, "rb") as fh:
            data = fh.read()
        with open(path, "wb") as fh:
            fh.write(POISON + data)

    def pins_for_tree(self):
        rows = []
        for name in sorted(h.EXPECTED_SOURCES):
            with open(os.path.join(self.tree, name), "rb") as fh:
                data = fh.read()
            rows.append({"path": name, "bytes": len(data),
                         "sha256": h.hashlib.sha256(data).hexdigest()})
        return write_json(os.path.join(self.tmp, "tree_pins.json"), rows)

    def run_child(self, script):
        env = dict(os.environ, POISON_MARKER=self.marker,
                   PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n"
             % HERE + script],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])


class SourceIdentityTests(TreeCase):
    """Finding 1: nothing from the candidate tree runs before verification."""

    def test_real_pins_and_tree_verify(self):
        verified = h.verify_source_tree(h.SOURCE_ROOT, h.load_pins(PINS))
        self.assertEqual(set(verified), h.EXPECTED_SOURCES)

    def assert_pins_rejected(self, rows, code):
        path = write_json(os.path.join(self.tmp, "bad_pins.json"), rows)
        with self.assertRaises(h.HarnessError) as cm:
            h.load_pins(path)
        self.assertEqual(cm.exception.code, code)

    def test_pins_duplicate_missing_extra_rejected(self):
        rows = read_pin_rows()
        self.assert_pins_rejected(rows + [rows[0]], "PINS_DUPLICATE_PATH")
        self.assert_pins_rejected(rows[1:], "PINS_MISSING_PATH")
        extra = dict(rows[0], path="evil.py")
        self.assert_pins_rejected(rows + [extra], "PINS_UNEXPECTED_PATH")
        self.assert_pins_rejected(
            rows[1:] + [dict(rows[0], path="../" + rows[0]["path"])],
            "PINS_UNEXPECTED_PATH")
        self.assert_pins_rejected(
            [dict(rows[0], sha256="0" * 63)] + rows[1:], "PINS_DIGEST")
        self.assert_pins_rejected(
            [dict(rows[0], extra=1)] + rows[1:], "PINS_ROW_SCHEMA")

    def assert_tree_rejected(self, code):
        with self.assertRaises(h.HarnessError) as cm:
            h.verify_source_tree(self.tree, h.load_pins(PINS))
        self.assertEqual(cm.exception.code, code)

    def test_extra_tree_entries_rejected(self):
        os.mkdir(os.path.join(self.tree, "__pycache__"))
        self.assert_tree_rejected("SOURCE_TREE_ENTRIES")
        os.rmdir(os.path.join(self.tree, "__pycache__"))
        open(os.path.join(self.tree, "evil.py"), "w").close()
        self.assert_tree_rejected("SOURCE_TREE_ENTRIES")

    def test_symlink_with_correct_bytes_rejected(self):
        path = os.path.join(self.tree, "ledger.py")
        shutil.move(path, os.path.join(self.tmp, "ledger_real.py"))
        os.symlink(os.path.join(self.tmp, "ledger_real.py"), path)
        self.assert_tree_rejected("SOURCE_NOT_REGULAR_FILE")

    def test_wrong_bytes_rejected(self):
        self.poison()
        self.assert_tree_rejected("SOURCE_FILE_BYTES")

    def test_preloaded_candidate_module_rejected(self):
        sys.modules["ledger"] = types.ModuleType("ledger")
        try:
            with self.assertRaises(h.HarnessError) as cm:
                h.import_shell(h.SOURCE_ROOT, {})
            self.assertEqual(cm.exception.code, "CANDIDATE_MODULE_PRELOADED")
        finally:
            del sys.modules["ledger"]

    def test_poisoned_wrong_hash_rejected_before_side_effect(self):
        self.poison()
        out = os.path.join(self.tmp, "out")
        result = self.run_child(
            "import json, os, native_close_smoke as h\n"
            "rc = h.main(['--pins', %r, '--native', '--out', %r], root=%r)\n"
            "ev = json.load(open(os.path.join(%r, 'evidence.json')))\n"
            "print(json.dumps({'rc': rc, 'marker': os.path.exists(%r),\n"
            "  'loaded': sorted(h.CANDIDATE_MODULES & set(sys.modules)),\n"
            "  'primary': ev['primary_failure'], 'forks': ev['forks']}))\n"
            % (PINS, out, self.tree, out, self.marker))
        self.assertEqual(result["rc"], 1)
        self.assertFalse(result["marker"], "poisoned import side effect ran")
        self.assertEqual(result["loaded"], [])
        self.assertEqual(result["forks"], 0)
        self.assertEqual(result["primary"]["stage"], "SOURCE_VERIFY")
        self.assertEqual(result["primary"]["code"], "SOURCE_FILE_BYTES")

    def test_poisoned_same_length_wrong_hash_rejected_by_digest(self):
        path = os.path.join(self.tree, "common.py")
        with open(path, "rb") as fh:
            data = fh.read()
        # Same byte count: only the digest can reject it.
        poisoned = POISON + data[len(POISON):]
        with open(path, "wb") as fh:
            fh.write(poisoned)
        result = self.run_child(
            "import json, os, native_close_smoke as h\n"
            "try:\n"
            "    h.verify_source_tree(%r, h.load_pins(%r)); code = None\n"
            "except h.HarnessError as exc:\n"
            "    code = exc.code\n"
            "print(json.dumps({'code': code, 'marker': os.path.exists(%r)}))\n"
            % (self.tree, PINS, self.marker))
        self.assertEqual(result, {"code": "SOURCE_FILE_SHA256",
                                  "marker": False})

    def test_positive_control_side_effect_is_observable(self):
        # Correctly pinned poison does run on import, so the absence above
        # is due to verification, not to an unobservable side effect.
        self.poison()
        pins = self.pins_for_tree()
        result = self.run_child(
            "import json, os, native_close_smoke as h\n"
            "h.import_shell(%r, h.verify_source_tree(%r, h.load_pins(%r)))\n"
            "print(json.dumps({'marker': os.path.exists(%r)}))\n"
            % (self.tree, self.tree, pins, self.marker))
        self.assertTrue(result["marker"])

    def test_disk_change_after_verify_not_executed_and_bindings_reject(self):
        result = self.run_child(
            "import json, os, native_close_smoke as h\n"
            "pins = h.load_pins(%r)\n"
            "verified = h.verify_source_tree(%r, pins)\n"
            "path = os.path.join(%r, 'ledger.py')\n"
            "data = open(path, 'rb').read()\n"
            "open(path, 'wb').write(%r + data)\n"
            "m = h.import_shell(%r, verified)\n"
            "marker = os.path.exists(%r)\n"
            "try:\n"
            "    h.setup_runtime(m, pins, %r); code = None\n"
            "except m['ledger'].LedgerError as exc:\n"
            "    code = exc.code\n"
            "print(json.dumps({'marker': marker, 'code': code}))\n"
            % (PINS, self.tree, self.tree, POISON, self.tree, self.marker,
               self.tree))
        self.assertEqual(result, {"marker": False,
                                  "code": "P17_SOURCE_FILE_PIN"})

    def test_clean_tree_imports_from_verified_loader(self):
        result = self.run_child(
            "import json, os, native_close_smoke as h\n"
            "m = h.import_shell(%r, h.verify_source_tree(%r, h.load_pins(%r)))\n"
            "print(json.dumps({'files': sorted(os.path.basename(\n"
            "  sys.modules[n].__file__) for n in h.RUNTIME_MODULES),\n"
            "  'finder_removed': not any(type(f).__name__ ==\n"
            "  'VerifiedSourceLoader' for f in sys.meta_path),\n"
            "  'pycache': os.path.exists(os.path.join(%r, '__pycache__'))}))\n"
            % (self.tree, self.tree, PINS, self.tree))
        self.assertEqual(result["files"], sorted(
            n + ".py" for n in h.RUNTIME_MODULES))
        self.assertEqual(len(result["files"]), 12)
        self.assertTrue(result["finder_removed"])
        self.assertFalse(result["pycache"])

    def test_bad_pins_file_writes_partial_evidence(self):
        rows = read_pin_rows()
        pins = write_json(os.path.join(self.tmp, "dup.json"), rows + rows[:1])
        out = os.path.join(self.tmp, "out")
        rc = h.main(["--pins", pins, "--native", "--out", out])
        self.assertEqual(rc, 1)
        with open(os.path.join(out, "evidence.json")) as fh:
            ev = json.load(fh)
        self.assertEqual(ev["primary_failure"]["stage"], "PINS")
        self.assertEqual(ev["primary_failure"]["code"], "PINS_DUPLICATE_PATH")
        self.assertFalse(ev["overall_ok"])
        self.assertEqual(ev["forks"], 0)


class FakeOps:
    """Harness-helper fault injection; has no kill/signal on purpose."""

    def __init__(self, pid=4242, fds=(10, 11), fork_exc=None, close_exc=None,
                 reap_after=0, wait_exc=None, clock_exc=None):
        self.pid, self.fds, self.fork_exc = pid, fds, fork_exc
        self.close_exc = close_exc or {}
        self.reap_after, self.wait_exc, self.clock_exc = reap_after, wait_exc, clock_exc
        self.calls, self.now = [], 0.0

    def pipe(self):
        self.calls.append(("pipe",))
        return self.fds

    def fork(self):
        self.calls.append(("fork",))
        if self.fork_exc:
            raise self.fork_exc
        return self.pid

    def close(self, fd):
        self.calls.append(("close", fd))
        if fd in self.close_exc:
            raise self.close_exc[fd]

    def waitpid(self, pid, flags):
        self.calls.append(("waitpid", pid, flags))
        if self.wait_exc:
            raise self.wait_exc
        if self.reap_after is not None and self.reap_after <= 0:
            return pid, 0
        if self.reap_after is not None:
            self.reap_after -= 1
        return 0, 0

    def monotonic(self):
        if self.clock_exc:
            raise self.clock_exc
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def closes(self):
        return [c[1] for c in self.calls if c[0] == "close"]


class FakeGuard:
    """Stands in for the guard in harness-flow unit tests only."""

    def __init__(self, finish_exc=None):
        self.installed, self.finish_exc, self.finish_calls = True, finish_exc, 0

    def finish(self):
        self.finish_calls += 1
        if self.finish_exc:
            raise self.finish_exc
        self.installed = False

    def report(self):
        return {"counters": {}, "events": [], "denied": []}


class ChildLifecycleTests(unittest.TestCase):
    """Finding 2: explicit ownership, single close, primary vs cleanup."""

    def run_flow(self, ops, body):
        return h.run_native(None, None, None, None, h.load_pins(PINS),
                            "/nonexistent", ops=ops, body=body)

    def assert_serialisable(self, ev):
        json.dumps(h.safe(ev))

    def test_fake_ops_interface_matches_real_ops(self):
        # native_smoke_1 failed cleanup because the default ops (`os`) lacked
        # monotonic/sleep that FakeOps provided. Fakes must not be richer.
        self.assertEqual({n for n in dir(h.REAL_OPS) if not n.startswith("_")},
                         h.OPS_INTERFACE)
        self.assertEqual({n for n in vars(FakeOps) if not n.startswith("_")}
                         - {"closes"}, h.OPS_INTERFACE)
        for fn in (h.spawn_child, h.release_child, h.cleanup, h.run_native):
            self.assertIs(fn.__defaults__[0], h.REAL_OPS)
        self.assertIs(h.REAL_OPS.close, os.close)
        self.assertIs(h.REAL_OPS.monotonic, h.time.monotonic)

    def test_release_with_real_clock_pipe_and_close(self):
        # Real pipe/close/monotonic/sleep; only fork and waitpid are faked,
        # so no process is created or waited on.
        class RealExceptProcess(h.RealOps):
            def __init__(self):
                self.waits = 0

            def fork(self):
                return 4242

            def waitpid(self, pid, flags):
                self.waits += 1
                return (pid, 0) if self.waits >= 3 else (0, 0)

        ops = RealExceptProcess()
        res, steps = h.ChildResources(), []
        h.spawn_child(res, steps, ops)
        child, cl = h.cleanup({}, res, steps, ops)
        self.assertTrue(cl["complete"], cl)
        self.assertEqual([s["step"] for s in steps], [
            "parent_pipe_read_close", "control_pipe_close", "child_reap"])
        self.assertEqual((child["reaped"], child["exit_code"], ops.waits),
                         (True, 0, 3))

    def test_fork_failure_closes_each_pipe_end_once_and_reraises(self):
        ops = FakeOps(fork_exc=OSError(errno.EAGAIN, "fork"))
        res, steps = h.ChildResources(), []
        with self.assertRaises(OSError) as cm:
            h.spawn_child(res, steps, ops)
        self.assertEqual(cm.exception.errno, errno.EAGAIN)
        self.assertEqual(ops.closes(), [10, 11])
        self.assertEqual((res.pid, res.read_fd, res.write_fd), (None, None, None))
        self.assertTrue(all(s["ok"] for s in steps))

    def test_fork_failure_close_error_not_retried_original_error_kept(self):
        ops = FakeOps(fork_exc=OSError(errno.EAGAIN, "fork"),
                      close_exc={10: OSError(errno.EINTR, "close")})
        res, steps = h.ChildResources(), []
        with self.assertRaises(OSError) as cm:
            h.spawn_child(res, steps, ops)
        self.assertEqual(cm.exception.errno, errno.EAGAIN)
        self.assertEqual(ops.closes(), [10, 11])
        self.assertEqual([(s["step"], s["ok"]) for s in steps], [
            ("spawn_failed_pipe_read_close", False),
            ("spawn_failed_pipe_write_close", True)])
        self.assertFalse(steps[0]["retried"])

    def test_spawn_failure_in_run_native_keeps_evidence(self):
        ops = FakeOps(fork_exc=OSError(errno.EAGAIN, "fork"))
        called = []
        ev = self.run_flow(ops, lambda *a: called.append(1))
        self.assertEqual(called, [])
        self.assertEqual(ev["primary_failure"]["stage"], "SPAWN")
        # OSError(EAGAIN, ...) is constructed as its BlockingIOError subclass.
        self.assertEqual(ev["primary_failure"]["type"], "BlockingIOError")
        self.assertTrue(ev["cleanup"]["complete"])
        self.assertNotIn("waitpid", [c[0] for c in ops.calls])
        self.assertFalse(all(c["ok"] for c in ev["checks"]))
        self.assert_serialisable(ev)

    def test_parent_read_close_failure_stops_before_body(self):
        ops = FakeOps(close_exc={10: OSError(errno.EIO, "close")})
        called = []
        ev = self.run_flow(ops, lambda *a: called.append(1))
        self.assertEqual(called, [])
        self.assertEqual(ev["primary_failure"]["code"],
                         "PARENT_PIPE_READ_CLOSE_FAILED")
        self.assertEqual(ops.closes(), [10, 11])
        self.assertTrue(ev["child"]["reaped"])
        self.assertFalse(ev["cleanup"]["complete"])
        # Review fix: the fork succeeded, so the child pid is reported (and
        # main() therefore counts forks=1) even though spawn_child raised.
        self.assertEqual(ev["pid"], 4242)

    def test_control_pipe_close_failure_still_reaps_without_retry(self):
        ops = FakeOps(close_exc={11: OSError(errno.EINTR, "close")},
                      reap_after=3)
        res, steps = h.ChildResources(), []
        h.spawn_child(res, steps, ops)
        child, cl = h.cleanup({}, res, steps, ops)
        self.assertEqual(ops.closes(), [10, 11])
        self.assertTrue(child["reaped"])
        self.assertEqual(child["reap_deadline_s"],
                         h.CHILD_SELF_TIMEOUT_S + h.REAP_DEADLINE_S)
        self.assertFalse(cl["complete"])
        self.assertEqual([f["step"] for f in cl["failures"]],
                         ["control_pipe_close"])
        self.assertIsNone(cl["still_owned"]["write_fd"])

    def test_waitpid_error_recorded_as_incomplete(self):
        ops = FakeOps(wait_exc=ChildProcessError(errno.ECHILD, "waitpid"))
        res, steps = h.ChildResources(), []
        h.spawn_child(res, steps, ops)
        child, cl = h.cleanup({}, res, steps, ops)
        self.assertFalse(child["reaped"])
        self.assertFalse(cl["complete"])
        self.assertEqual(cl["still_owned"]["pid"], 4242)
        self.assertEqual([c[0] for c in ops.calls].count("waitpid"), 1)

    def test_not_reaped_by_deadline_no_signal(self):
        ops = FakeOps(reap_after=None)
        res, steps = h.ChildResources(), []
        h.spawn_child(res, steps, ops)
        child, cl = h.cleanup({}, res, steps, ops)
        self.assertFalse(child["reaped"])
        self.assertEqual(child["signals_sent"], 0)
        self.assertFalse(cl["complete"])
        self.assertEqual({c[0] for c in ops.calls},
                         {"pipe", "fork", "close", "waitpid"})
        self.assertGreaterEqual(ops.now, h.REAP_DEADLINE_S)

    def test_guard_finish_failure_keeps_primary_and_releases_child(self):
        ops, guard = FakeOps(), FakeGuard(RuntimeError("finish failed"))

        def body(m, runtime, native, policy, pins, out, pid, ctx, ev):
            ctx["guard"] = guard
            ev["stage"] = "GUARDED_ACQUIRE"
            raise ValueError("primary failure")

        ev = self.run_flow(ops, body)
        self.assertEqual(ev["primary_failure"]["type"], "ValueError")
        self.assertEqual(ev["primary_failure"]["stage"], "GUARDED_ACQUIRE")
        steps = [(s["step"], s["ok"]) for s in ev["cleanup"]["steps"]]
        self.assertEqual(steps, [("parent_pipe_read_close", True),
                                 ("guard_finish", False),
                                 ("control_pipe_close", True),
                                 ("child_reap", True)])
        self.assertEqual(guard.finish_calls, 1)
        self.assertFalse(ev["cleanup"]["complete"])
        self.assertTrue(ev["cleanup"]["guard_installed_after_cleanup"])
        self.assertEqual(ops.closes(), [10, 11])
        self.assert_serialisable(ev)

    def test_guard_finish_failure_after_success_fails_acceptance(self):
        ops, guard = FakeOps(), FakeGuard(RuntimeError("finish failed"))

        def body(m, runtime, native, policy, pins, out, pid, ctx, ev):
            ctx["guard"] = guard

        ev = self.run_flow(ops, body)
        self.assertIsNone(ev["primary_failure"])
        failed = {c["name"] for c in ev["checks"] if not c["ok"]}
        self.assertIn("cleanup_complete", failed)
        self.assertTrue(ev["child"]["reaped"])

    def test_body_failure_before_guard_cleanup_complete(self):
        ops = FakeOps()

        def body(m, runtime, native, policy, pins, out, pid, ctx, ev):
            ev["stage"] = "EXPECTED_IDENTITY"
            raise FileNotFoundError("/proc/4242/stat")

        ev = self.run_flow(ops, body)
        self.assertEqual(ev["primary_failure"]["stage"], "EXPECTED_IDENTITY")
        self.assertTrue(ev["cleanup"]["complete"])
        self.assertNotIn("guard_finish",
                         [s["step"] for s in ev["cleanup"]["steps"]])
        self.assertIsNone(ev["guard_report"])

    def test_release_internal_error_recorded_primary_kept(self):
        ops = FakeOps(clock_exc=RuntimeError("clock"))

        def body(m, runtime, native, policy, pins, out, pid, ctx, ev):
            raise KeyError("primary")

        ev = self.run_flow(ops, body)
        self.assertEqual(ev["primary_failure"]["type"], "KeyError")
        self.assertEqual(ev["cleanup"]["failures"][-1]["step"], "child_release")
        self.assertFalse(ev["cleanup"]["complete"])
        self.assertEqual(ops.closes(), [10, 11])


class AcceptanceTests(unittest.TestCase):
    """Finding 3: strict success acceptance; malformed evidence fails."""

    @classmethod
    def setUpClass(cls):
        with open(PRIOR_EVIDENCE) as fh:
            base = json.load(fh)
        events = base["guard_report"]["events"]
        acquired = 1 + max(i for i, e in enumerate(events)
                           if e["kind"] == "phase_leave"
                           and e["details"]["phase"] == "VIEW_AND_RETURN")
        base.pop("exception", None)
        base.update({
            "primary_failure": None,
            "guard_after_acquire": {"phase": "IDLE", "events": acquired},
            "guard_before_finish": {"phase": "IDLE", "events": len(events)},
            "cleanup": {"complete": True, "failures": [], "steps": [
                {"step": n, "ok": True} for n in (
                    "parent_pipe_read_close", "guard_finish",
                    "control_pipe_close", "child_reap")]}})
        cls.base = base
        cls.token = h.make_token(h.load_pins(PINS))

    def failed(self, ev):
        checks = []
        try:
            h.evaluate(ev, ev["pid"], self.token, checks)
        except Exception:
            checks.append({"name": "evaluation", "ok": False})
        return {c["name"] for c in checks if not c["ok"]}

    def mutate(self):
        return copy.deepcopy(self.base)

    def test_evaluation_failure_reads_no_source_lines(self):
        # Review fix: evaluate_safely must not use traceback.format_exc, which
        # reads files through linecache (denied under a stuck active guard).
        import linecache
        ev = self.mutate()
        del ev["controller_report"]["ledger"]
        real = linecache.getlines

        def refuse(*args, **kwargs):
            raise AssertionError("linecache read during evaluation")
        linecache.getlines = refuse
        try:
            checks = h.evaluate_safely(ev, h.load_pins(PINS))
        finally:
            linecache.getlines = real
        last = checks[-1]
        self.assertEqual(last["name"], "evaluation")
        self.assertFalse(last["ok"])
        self.assertEqual(last["observed"]["type"], "KeyError")

    def test_well_formed_success_passes(self):
        self.assertEqual(self.failed(self.mutate()), set())

    def test_controller_left_phase_open_finish_auto_left(self):
        ev = self.mutate()
        events = ev["guard_report"]["events"]
        # Controller never left NORMAL_CLOSE_COMPLETE; finish() did.
        ev["guard_before_finish"] = {"phase": "NORMAL_CLOSE_COMPLETE",
                                     "events": len(events) - 1}
        self.assertEqual(self.failed(ev), {
            "guard_idle_after_public_operations",
            "guard_finish_added_no_events"})

    def test_unpaired_or_extra_phase_events_fail(self):
        ev = self.mutate()
        events = ev["guard_report"]["events"]
        drop = max(i for i, e in enumerate(events) if e["kind"] == "phase_leave"
                   and e["details"]["phase"] == "REGISTER")
        del events[drop]
        ev["guard_report"]["counters"]["phase_leave"] -= 1
        ev["guard_before_finish"]["events"] -= 1
        self.assertEqual(self.failed(ev), {
            "guard_phase_enter_leave_exactly_paired",
            "guard_phase_counters_match"})
        ev = self.mutate()
        events = ev["guard_report"]["events"]
        extra = dict(events[0], details={"phase": "ROLLBACK_BEGIN"})
        events.insert(1, extra)
        ev["guard_before_finish"]["events"] += 1
        self.assertIn("guard_phase_enter_leave_exactly_paired", self.failed(ev))

    def test_rejected_or_extra_submission_fails(self):
        ev = self.mutate()
        ev["controller_report"]["admission"]["submission_slots"] = 4
        self.assertEqual(self.failed(ev), {
            "ledger_exactly_three_submissions_all_accepted_zero_rejected"})
        ev = self.mutate()
        ev["controller_report"]["adapter"]["complete_reply"].update(
            accepted=False, reason="DUPLICATE_COMPLETION")
        self.assertIn(
            "ledger_exactly_three_submissions_all_accepted_zero_rejected",
            self.failed(ev))

    def test_stop_false_fails(self):
        ev = self.mutate()
        ev["close_snapshot"]["stop"] = False
        self.assertEqual(self.failed(ev), {"terminal_stop_latch_after_complete"})

    def test_primary_or_incomplete_cleanup_fails(self):
        ev = self.mutate()
        ev["primary_failure"] = {"stage": "GUARDED_NORMAL_CLOSE"}
        self.assertEqual(self.failed(ev), {"no_primary_failure"})
        ev = self.mutate()
        ev["cleanup"]["steps"][2]["ok"] = False
        self.assertEqual(self.failed(ev), {"cleanup_complete"})
        ev = self.mutate()
        del ev["cleanup"]["steps"][1]
        self.assertEqual(self.failed(ev), {"cleanup_complete"})

    def test_missing_guard_state_fails(self):
        ev = self.mutate()
        ev["guard_before_finish"] = None
        self.assertIn("evaluation", self.failed(ev))


if __name__ == "__main__":
    unittest.main()
