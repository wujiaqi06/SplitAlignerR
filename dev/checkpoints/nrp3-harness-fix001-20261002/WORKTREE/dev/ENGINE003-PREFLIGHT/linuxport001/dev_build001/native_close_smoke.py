"""Development smoke: one owned direct child, one pidfd, one public normal close.

Drives the unchanged p18_working shell end to end on Linux:

    NativeOwnerController.acquire_register_prove_direct_child
        -> one pidfd_open (provider field) -> REGISTER -> proof -> view
    NativeOwnerController.close_registered_direct_child
        -> BEGIN -> one provider os.close -> normalization -> COMPLETE

Child lifecycle resources (fork, control pipe, reap) are harness-owned and kept
entirely outside the guarded window. The provider pidfd is never touched by the
harness: it is opened and closed only inside the provider. Reaping the child
is reclamation, not close confirmation; ledger CONFIRMED_CLOSE is the recorded
close outcome, not kernel-state proof.

Source identity: the pins file and the source directory are checked for the
exact 17-file set and every file's bytes are hashed *before* any candidate
module is executed. Candidate modules are then executed from those verified
bytes only (never re-read, never from bytecode caches). RuntimeBindings
re-reads and re-checks the files afterwards and remains authoritative.

Usage:
    python3 native_close_smoke.py --pins PINS.json --dry-run --out DIR
    python3 native_close_smoke.py --pins PINS.json --native  --out DIR

--dry-run performs verification, imports, runtime binding, native construction
and the acquisition-environment preflight only: no fork, no pidfd, no guard.
Both modes refuse to reuse an existing DIR so every run keeps its evidence.
"""
import argparse
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import select
import stat
import sys
import time
import traceback

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.realpath(__file__))
SOURCE_ROOT = os.path.realpath(os.path.join(HERE, "..", "p18_working"))
HEADERS = (
    "/usr/include/x86_64-linux-gnu/asm/unistd_64.h",
    "/usr/include/x86_64-linux-gnu/bits/sigaction.h",
    "/usr/include/x86_64-linux-gnu/bits/types/__sigset_t.h",
)
# Same set RuntimeBindings requires; duplicated because nothing from the
# candidate tree may be imported before it is verified.
EXPECTED_SOURCES = frozenset((
    "direct_child_pidfd.py", "integrated_native_effects.py",
    "integrated_native_adapter.py", "native_owner_controller.py",
    "runtime_bindings.py", "development_guard.py", "recorded_native.py",
    "ledger.py", "common.py", "pidfd_primitives.py", "parsers.py",
    "native_syscalls_factory.py", "SUPPLIED_FIXTURES.json",
    "SOURCE_ISOLATION_MANIFEST.json", "pure_candidate_runner.py",
    "STATIC_CHECKLIST.json", "README.md",
))
CANDIDATE_MODULES = frozenset(
    name[:-3] for name in EXPECTED_SOURCES if name.endswith(".py"))
# pure_candidate_runner is pinned but never executed by this harness.
RUNTIME_MODULES = CANDIDATE_MODULES - {"pure_candidate_runner"}
RUN_ID = "DEV_BUILD001_NATIVE_CLOSE_SMOKE"
OWNER_ID = "DEV_BUILD001_HARNESS"
SOURCE_ID = "native_owner_controller.py"
IDS = {"reservation": "RES-1", "register": "EV-REGISTER-1",
       "attempt": "ATTEMPT-1", "begin": "EV-BEGIN-1",
       "complete": "EV-COMPLETE-1"}
ROLLBACK_IDS = {"attempt": "RB-ATTEMPT-1", "begin": "EV-RB-BEGIN-1",
                "complete": "EV-RB-COMPLETE-1"}
SUCCESS_PHASES = (
    "PRE_OPEN_PREPARE", "RAW_CAPTURE", "REGISTER", "POST_REGISTER_PROOF",
    "VIEW_AND_RETURN", "NORMAL_CLOSE_BEGIN", "NORMAL_CLOSE_CALLBACK",
    "NORMAL_CLOSE_COMPLETE")
CHILD_SELF_TIMEOUT_S = 60.0
REAP_DEADLINE_S = 10.0


class HarnessError(Exception):
    def __init__(self, code, detail=None):
        self.code = code
        super().__init__(code if detail is None else "%s: %s" % (code, detail))


def need(ok, code, detail=None):
    if not ok:
        raise HarnessError(code, detail)


# --------------------------------------------------------------------------
# Source identity (before any candidate code runs)
# --------------------------------------------------------------------------

def load_pins(path):
    """Exact 17-row pin set: no duplicate, missing, extra or non-basename path."""
    with open(path) as fh:
        rows = json.load(fh)
    need(type(rows) is list, "PINS_SCHEMA")
    pins = {}
    for row in rows:
        need(type(row) is dict and set(row) == {"path", "bytes", "sha256"},
             "PINS_ROW_SCHEMA", row)
        name = row["path"]
        need(type(name) is str and name in EXPECTED_SOURCES,
             "PINS_UNEXPECTED_PATH", name)
        need(name not in pins, "PINS_DUPLICATE_PATH", name)
        need(type(row["bytes"]) is int and row["bytes"] >= 0,
             "PINS_BYTES", name)
        digest = row["sha256"]
        need(type(digest) is str and len(digest) == 64
             and all(c in "0123456789abcdef" for c in digest),
             "PINS_DIGEST", name)
        pins[name] = {"bytes": row["bytes"], "sha256": digest}
    need(set(pins) == EXPECTED_SOURCES, "PINS_MISSING_PATH",
         sorted(EXPECTED_SOURCES - set(pins)))
    return pins


def verify_source_tree(root, pins):
    """Hash every pinned file; return the verified bytes. Imports nothing."""
    entries = set(os.listdir(root))
    need(entries == EXPECTED_SOURCES, "SOURCE_TREE_ENTRIES",
         {"extra": sorted(entries - EXPECTED_SOURCES),
          "missing": sorted(EXPECTED_SOURCES - entries)})
    verified = {}
    for name in sorted(EXPECTED_SOURCES):
        path = os.path.join(root, name)
        need(stat.S_ISREG(os.lstat(path).st_mode),
             "SOURCE_NOT_REGULAR_FILE", name)
        with open(path, "rb") as fh:
            data = fh.read()
        need(len(data) == pins[name]["bytes"], "SOURCE_FILE_BYTES", name)
        need(hashlib.sha256(data).hexdigest() == pins[name]["sha256"],
             "SOURCE_FILE_SHA256", name)
        verified[name] = data
    return verified


class VerifiedSourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves candidate modules from already-verified bytes only."""

    def __init__(self, root, verified):
        self.root = root
        self.sources = {name[:-3]: data for name, data in verified.items()
                        if name.endswith(".py")}
        self.executed = []

    def find_spec(self, name, path=None, target=None):
        if name not in self.sources:
            return None
        return importlib.util.spec_from_file_location(
            name, os.path.join(self.root, name + ".py"), loader=self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        self.executed.append(name)
        code = compile(self.sources[name], module.__spec__.origin, "exec",
                       dont_inherit=True)
        exec(code, module.__dict__)


def import_shell(root, verified):
    need(not (CANDIDATE_MODULES & set(sys.modules)),
         "CANDIDATE_MODULE_PRELOADED",
         sorted(CANDIDATE_MODULES & set(sys.modules)))
    loader = VerifiedSourceLoader(root, verified)
    sys.meta_path.insert(0, loader)
    try:
        mods = {key: importlib.import_module(name) for key, name in (
            ("ledger", "ledger"), ("runtime_bindings", "runtime_bindings"),
            ("factory", "native_syscalls_factory"),
            ("p01", "pidfd_primitives"), ("guard", "development_guard"),
            ("recorded", "recorded_native"),
            ("controller", "native_owner_controller"),
            ("effects", "integrated_native_effects"))}
    finally:
        sys.meta_path.remove(loader)
    for name in RUNTIME_MODULES:
        mod = sys.modules.get(name)
        need(mod is not None and mod.__spec__.loader is loader
             and mod.__file__ == os.path.join(root, name + ".py"),
             "CANDIDATE_MODULE_ORIGIN", name)
    need("pure_candidate_runner" not in sys.modules, "UNEXPECTED_RUNNER_IMPORT")
    return mods


def host_pins():
    """Operational header self-pins; consistency only, not host authority."""
    rows = []
    for path in HEADERS:
        with open(path, "rb") as fh:
            data = fh.read()
        rows.append({"path": path, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def setup_runtime(m, pins, root=SOURCE_ROOT):
    """Everything that reads files must precede guard.install()."""
    runtime = m["runtime_bindings"].RuntimeBindings(
        root, {name: row["sha256"] for name, row in pins.items()},
        host_pins(), os.getpid())
    # The guard only inspects the provider callback when co_filename equals
    # runtime.effects_path; a mismatch would silently skip that check.
    invoke_file = m["effects"].IntegratedNativeEffects.invoke.__code__.co_filename
    need(invoke_file == runtime.effects_path, "EFFECTS_CO_FILENAME",
         (invoke_file, runtime.effects_path))
    native = m["factory"].construct_native_syscalls()
    runtime.validate_native(native)
    header_view = [(r["path"], r["sha256"]) for r in native.provenance["header_files"]]
    need(header_view == [(r["path"], r["sha256"]) for r in runtime.host_pins],
         "NATIVE_HEADER_PROVENANCE")
    # Legitimate only because this harness forks the single child itself,
    # never reaps it before the close, is single-threaded and keeps SIGCHLD default.
    policy = m["p01"].AcquisitionPolicy(True, True, True)
    m["p01"].validate_acquisition_environment(
        policy, native.acquisition_environment(), native.no_cldwait)
    return runtime, native, policy


# --------------------------------------------------------------------------
# Harness-owned child lifecycle (never the provider pidfd)
# --------------------------------------------------------------------------

def describe_exception(exc, stage=None):
    """No file I/O (no linecache): safe while the guard's hooks may be active."""
    frames = [[f.f_code.co_filename, lineno, f.f_code.co_name]
              for f, lineno in traceback.walk_tb(exc.__traceback__)]
    code = getattr(exc, "code", None)
    return {"stage": stage, "type": type(exc).__name__, "repr": repr(exc),
            "code": code if isinstance(code, (str, int)) else None,
            "frames": frames[-16:],
            "context": repr(exc.__context__) if exc.__context__ else None}


class RealOps:
    """Exactly the real effects the child lifecycle uses (and nothing else:
    no kill/signal). Unit tests substitute an object with this interface."""
    pipe = staticmethod(os.pipe)
    fork = staticmethod(os.fork)
    close = staticmethod(os.close)
    waitpid = staticmethod(os.waitpid)
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


REAL_OPS = RealOps()
OPS_INTERFACE = frozenset(
    ("pipe", "fork", "close", "waitpid", "monotonic", "sleep"))


class ChildResources:
    """Exactly what the harness owns: a child pid and two pipe ends."""

    def __init__(self):
        self.pid = None
        self.read_fd = None
        self.write_fd = None


def close_owned(res, attr, step, steps, ops):
    """One close attempt per owned fd. Ownership is dropped before the call,
    so an ambiguous failure (e.g. EINTR/EIO) is recorded and never retried."""
    fd = getattr(res, attr)
    if fd is None:
        return None
    setattr(res, attr, None)
    try:
        ops.close(fd)
    except BaseException as exc:
        steps.append({"step": step, "ok": False, "fd": fd, "retried": False,
                      "error": describe_exception(exc)})
        return False
    steps.append({"step": step, "ok": True, "fd": fd})
    return True


def _child_main(read_fd, write_fd):
    """Harmless owned child: blocks on the control pipe, bounded self-timeout."""
    code = 0
    try:
        os.close(write_fd)
        deadline = time.monotonic() + CHILD_SELF_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                code = 4
                break
            if select.select([read_fd], [], [], min(remaining, 1.0))[0]:
                if os.read(read_fd, 1) == b"":
                    break
    except BaseException:
        code = 3
    finally:
        os._exit(code)


def spawn_child(res, steps, ops=REAL_OPS):
    read_fd, write_fd = ops.pipe()
    res.read_fd, res.write_fd = read_fd, write_fd
    try:
        pid = ops.fork()
    except BaseException:
        close_owned(res, "read_fd", "spawn_failed_pipe_read_close", steps, ops)
        close_owned(res, "write_fd", "spawn_failed_pipe_write_close", steps, ops)
        raise
    if pid == 0:
        _child_main(read_fd, write_fd)
    res.pid = pid
    if not close_owned(res, "read_fd", "parent_pipe_read_close", steps, ops):
        # Stop before any acquisition; the caller still releases the child.
        raise HarnessError("PARENT_PIPE_READ_CLOSE_FAILED")
    return pid


def release_child(res, steps, ops=REAL_OPS):
    """Close the control pipe once, then always attempt a bounded reap."""
    closed = close_owned(res, "write_fd", "control_pipe_close", steps, ops)
    result = {"pid": res.pid, "reaped": False, "wait_status": None,
              "exit_code": None, "signals_sent": 0, "reap_deadline_s": None}
    if res.pid is None:
        return result
    # If the close failed the child may not see EOF; its own bounded
    # self-timeout is the fallback, so wait for it rather than signal.
    limit = REAP_DEADLINE_S if closed else CHILD_SELF_TIMEOUT_S + REAP_DEADLINE_S
    result["reap_deadline_s"] = limit
    deadline = ops.monotonic() + limit
    while True:
        try:
            waited, status = ops.waitpid(res.pid, os.WNOHANG)
        except BaseException as exc:
            steps.append({"step": "child_reap", "ok": False,
                          "error": describe_exception(exc)})
            return result
        if waited == res.pid:
            res.pid = None
            result.update(reaped=True, wait_status=status,
                          exit_code=os.WEXITSTATUS(status)
                          if os.WIFEXITED(status) else None)
            steps.append({"step": "child_reap", "ok": True})
            return result
        if ops.monotonic() >= deadline:
            steps.append({"step": "child_reap", "ok": False,
                          "error": "not reaped within %ss; no signal sent; "
                                   "child self-timeout %ss"
                                   % (limit, CHILD_SELF_TIMEOUT_S)})
            return result
        ops.sleep(0.02)


def cleanup(ctx, res, steps, ops=REAL_OPS):
    """Never raises. Guard finish first, then child release regardless."""
    guard = ctx.get("guard")
    if guard is not None and guard.installed:
        try:
            guard.finish()
            steps.append({"step": "guard_finish", "ok": True})
        except BaseException as exc:
            # Not retried and not worked around: the guard state is left as
            # is; evidence is written through the pre-opened file.
            steps.append({"step": "guard_finish", "ok": False,
                          "error": describe_exception(exc)})
    try:
        child = release_child(res, steps, ops)
    except BaseException as exc:
        steps.append({"step": "child_release", "ok": False,
                      "error": describe_exception(exc)})
        child = {"pid": res.pid, "reaped": False, "signals_sent": 0}
    guard_down = guard is None or not guard.installed
    complete = (all(s["ok"] for s in steps) and guard_down and res.pid is None
                and res.read_fd is None and res.write_fd is None)
    return child, {"steps": steps, "complete": complete,
                   "failures": [s for s in steps if not s["ok"]],
                   "still_owned": {"pid": res.pid, "read_fd": res.read_fd,
                                   "write_fd": res.write_fd},
                   "guard_installed_after_cleanup": not guard_down}


# --------------------------------------------------------------------------
# Native run
# --------------------------------------------------------------------------

def safe(value, depth=0):
    if depth > 40:
        return repr(value)
    if isinstance(value, dict):
        return {str(k): safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v, depth + 1) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def make_token(pins):
    return {"run_id": RUN_ID, "owner_id": OWNER_ID, "resource_id": "CHILD-1",
            "generation": 1, "acquisition_id": "ACQ-1",
            "source_id": SOURCE_ID, "source_sha256": pins[SOURCE_ID]["sha256"]}


def make_ledger(m, pins):
    return m["ledger"].Ledger({
        "run_id": RUN_ID, "owner_id": OWNER_ID,
        "sources": [{"source_id": SOURCE_ID,
                     "sha256": pins[SOURCE_ID]["sha256"]}]})


def guard_state(guard):
    # Plain attribute reads, taken before finish() (which may auto-leave).
    return {"phase": guard.phase, "events": len(guard.events)}


def native_body(m, runtime, native, policy, pins, out, pid, ctx, ev):
    token = make_token(pins)
    # /proc/<pid>/stat is admitted by the guard only inside its phases,
    # so the expected identity is collected before install.
    ev["stage"] = "EXPECTED_IDENTITY"
    expected = m["p01"].direct_child_stat(pid)
    ev["expected"] = {"pid": expected.pid, "ppid": expected.ppid,
                      "starttime_ticks": expected.starttime_ticks,
                      "state": expected.state}
    ev["stage"] = "CONSTRUCT"

    def diagnostic(event):
        ev["diagnostic_events"].append(event)
        return None

    ctx["recorded"] = m["recorded"].RecordedRegisteredNative(diagnostic)
    ctx["controller"] = controller = m["controller"].NativeOwnerController(
        make_ledger(m, pins), runtime, native, token, ctx["recorded"], pins_sha(pins))
    ctx["guard"] = guard = m["guard"].DevelopmentGuard(
        runtime, out, [os.path.join(runtime.root, n) for n in sorted(pins)])
    runtime.bind_monitor(guard)
    ev["stage"] = "GUARDED_ACQUIRE"
    guard.install()
    view = controller.acquire_register_prove_direct_child(
        IDS["reservation"], IDS["register"], token, native, pid,
        expected, policy, dict(ROLLBACK_IDS))
    ev["guard_after_acquire"] = guard_state(guard)
    if type(view) is not runtime.view_class:
        ev["acquire_result"] = safe(view)
        ev["notes"].append("acquisition did not return a view; "
                           "no normal close attempted")
        ev["guard_before_finish"] = guard_state(guard)
        return
    ev["view"] = view.report()
    ev["stage"] = "GUARDED_NORMAL_CLOSE"
    snapshot = controller.close_registered_direct_child(
        token, {"attempt": IDS["attempt"], "begin": IDS["begin"],
                "complete": IDS["complete"]})
    ev["guard_before_finish"] = guard_state(guard)
    ev["close_snapshot"] = snapshot
    ev["stage"] = "BODY_RETURNED"


def pins_sha(pins):
    return {name: row["sha256"] for name, row in pins.items()}


def run_native(m, runtime, native, policy, pins, out, ops=REAL_OPS,
               body=native_body):
    ev = {"mode": "native", "stage": "SPAWN", "pid": None, "view": None,
          "close_snapshot": None, "guard_after_acquire": None,
          "guard_before_finish": None, "diagnostic_events": [], "notes": [],
          "primary_failure": None}
    res, ctx, steps = ChildResources(), {}, []
    try:
        ev["pid"] = spawn_child(res, steps, ops)
        body(m, runtime, native, policy, pins, out, res.pid, ctx, ev)
    except BaseException as exc:
        ev["primary_failure"] = describe_exception(exc, ev["stage"])
    if ev["pid"] is None and res.pid is not None:
        # fork succeeded but spawn_child raised afterwards (parent read-end
        # close failed): the child exists and must be counted and reported.
        ev["pid"] = res.pid
    ev["child"], ev["cleanup"] = cleanup(ctx, res, steps, ops)
    controller = ctx.get("controller")
    for key, obj in (
            ("controller_report", controller),
            ("provider_report", controller and controller.effects),
            ("guard_report", ctx.get("guard")),
            ("recorded_native_report", ctx.get("recorded"))):
        ev[key] = None
        if obj is None:
            continue
        try:
            ev[key] = safe(obj.report())
        except BaseException as exc:
            ev["notes"].append("%s unavailable: %r" % (key, exc))
    ev["diagnostic_events"] = safe(ev["diagnostic_events"])
    ev["close_snapshot"] = safe(ev["close_snapshot"])
    ev["checks"] = evaluate_safely(ev, pins)
    return ev


# --------------------------------------------------------------------------
# Acceptance
# --------------------------------------------------------------------------

def evaluate_safely(ev, pins):
    checks = []
    try:
        evaluate(ev, ev["pid"], make_token(pins), checks)
    except BaseException as exc:
        # Checks recorded before the malformed field are kept. No
        # traceback.format_exc: it reads source lines through linecache, which
        # a guard whose hooks stayed active would deny.
        checks.append({"name": "evaluation", "ok": False,
                       "observed": describe_exception(exc)})
    return checks


def evaluate(ev, pid, token, checks=None):
    """Acceptance from the actual recorded state, not from the process rc."""
    checks = [] if checks is None else checks

    def check(name, ok, observed=None):
        checks.append({"name": name, "ok": bool(ok), "observed": safe(observed)})

    check("no_primary_failure", ev["primary_failure"] is None,
          ev["primary_failure"])
    cl = ev["cleanup"]
    step_names = [s["step"] for s in cl["steps"]]
    check("cleanup_complete",
          cl["complete"] is True and cl["failures"] == []
          and all(s["ok"] for s in cl["steps"])
          and step_names == ["parent_pipe_read_close", "guard_finish",
                             "control_pipe_close", "child_reap"], cl)
    rep, snap = ev["controller_report"], ev["close_snapshot"]
    led = rep["ledger"]
    row = rep["row"]
    adapter = rep["adapter"]
    check("view_returned", ev["view"] is not None, ev["view"])
    check("view_borrowed_fd_is_provider_fd",
          ev["view"] and row and ev["view"]["borrowed_fd"] == row["fd"]
          and ev["view"]["pid"] == pid, ev["view"])
    check("ledger_history_register_begin_complete",
          [(h["kind"], h["event_id"]) for h in led["history"]] == [
              ("REGISTER", IDS["register"]), ("BEGIN", IDS["begin"]),
              ("COMPLETE", IDS["complete"])],
          [(h["kind"], h["event_id"]) for h in led["history"]])
    replies = [row["full_register_reply"], adapter["begin_reply"],
               adapter["complete_reply"]]
    check("ledger_exactly_three_submissions_all_accepted_zero_rejected",
          rep["admission"]["submission_slots"] == 3
          and led["accepted_event_count"] == 3
          and snap["submission_slots"] == 3
          and snap["accepted_event_count"] == 3
          and [(r["accepted"], r["reason"], r["submission_slot"])
               for r in replies] == [(True, None, 1), (True, None, 2),
                                     (True, None, 3)],
          {"admission": rep["admission"],
           "accepted_event_count": led["accepted_event_count"],
           "replies": [(r["accepted"], r["reason"], r["submission_slot"])
                       for r in replies]})
    check("ledger_single_obligation_confirmed_close",
          len(led["obligations"]) == 1
          and led["obligations"][0]["state"] == "CONFIRMED_CLOSE"
          and led["obligations"][0]["token"] == token
          and led["obligations"][0]["fd"] == (row or {}).get("fd")
          and led["obligations"][0]["attempt_id"] == IDS["attempt"]
          and led["all_close_outcomes_confirmed"] is True
          and led["unresolved_obligation_count"] == 0, led["obligations"])
    check("complete_outcome_success",
          led["history"][-1].get("outcome") == {
              "result": "SUCCESS", "return_value": 0, "errno": None,
              "diagnostic": "close returned None"}, led["history"][-1])
    check("controller_confirmed_no_holds_no_primary",
          snap["controller_confirmed"] is True and snap["holds"] == []
          and snap["primary"] == "NONE" and snap["custody"] == "CONFIRMED_CLOSE"
          and snap["proof"] == "ACCEPTED_RETURN_ELIGIBLE"
          and snap["rollback"] == "NOT_REQUESTED", snap)
    # complete_close latches STOP after any COMPLETE, including success.
    check("terminal_stop_latch_after_complete", snap["stop"] is True, snap["stop"])
    check("adapter_begin_complete_accepted_one_callback",
          adapter and adapter["begin_reply"]["accepted"] is True
          and adapter["complete_reply"]["accepted"] is True
          and adapter["callback_entries"] == 1
          and adapter["raw_observation"] == {
              "kind": "RETURN", "python_type": "NoneType",
              "representation": "None", "returned_normally": True}
          and adapter["normalization"]["valid"] is True,
          adapter and {k: adapter[k] for k in (
              "begin_reply", "complete_reply", "callback_entries",
              "raw_observation")})
    calls = ev["provider_report"]["calls"]
    check("provider_single_callback_matches_begin_action",
          len(calls) == 1 and adapter and calls[0]["action"] == adapter["action"]
          and calls[0]["action"]["fd"] == row["fd"]
          and row["callback_attempted"] is True, calls)
    gr = ev["guard_report"]
    counters = gr["counters"]
    check("guard_no_denials", gr["denied"] == [], gr["denied"])
    check("guard_one_open_one_close_one_invoke",
          counters.get("pidfd_open_entry") == 1
          and counters.get("os_close_entry") == 1
          and counters.get("provider_invoke_entry") == 1, counters)
    # Recorded right after each public operation, before finish() could
    # auto-leave a phase the controller failed to leave itself.
    check("guard_idle_after_public_operations",
          ev["guard_after_acquire"]["phase"] == "IDLE"
          and ev["guard_before_finish"]["phase"] == "IDLE",
          [ev["guard_after_acquire"], ev["guard_before_finish"]])
    check("guard_finish_added_no_events",
          ev["guard_before_finish"]["events"] == len(gr["events"]),
          [ev["guard_before_finish"]["events"], len(gr["events"])])
    phase_events = [(e["kind"], e["details"].get("phase")) for e in gr["events"]
                    if e["kind"] in ("phase_enter", "phase_leave")]
    want = []
    for phase in SUCCESS_PHASES:
        want += [("phase_enter", phase), ("phase_leave", phase)]
    check("guard_phase_enter_leave_exactly_paired", phase_events == want,
          phase_events)
    check("guard_phase_counters_match",
          counters.get("phase_enter") == len(SUCCESS_PHASES)
          and counters.get("phase_leave") == len(SUCCESS_PHASES), counters)
    rec = ev["recorded_native_report"]["events"]
    check("recorded_open_attempt_and_return",
          len(rec) == 2 and rec[0]["kind"] == "PIDFD_OPEN_ATTEMPT"
          and rec[1]["status"] == "PIDFD_OPEN_RETURN_RECORDED", rec)
    check("diagnostic_callback_once", len(ev["diagnostic_events"]) == 1,
          ev["diagnostic_events"])
    check("child_reaped_exit0_reclamation_only",
          ev["child"]["reaped"] is True and ev["child"]["exit_code"] == 0
          and ev["child"]["signals_sent"] == 0, ev["child"])
    return checks


def dry_run_close_gate(m, runtime, native, pins):
    """Normal close on a controller with no custody must refuse before effects."""
    token = make_token(pins)
    ledger = make_ledger(m, pins)
    controller = m["controller"].NativeOwnerController(
        ledger, runtime, native, token,
        m["recorded"].RecordedRegisteredNative(lambda event: None),
        pins_sha(pins))
    good = {"attempt": IDS["attempt"], "begin": IDS["begin"],
            "complete": IDS["complete"]}
    checks = []
    for name, ids, want in (
            ("missing_complete_id", {"attempt": "A", "begin": "B"},
             "NORMAL_CLOSE_IDS_SCHEMA"),
            ("bad_label", dict(good, begin="bad label"), "BEGIN_EVENT_ID_FORMAT"),
            ("no_registered_custody", good, "NORMAL_CLOSE_PROVENANCE")):
        try:
            controller.close_registered_direct_child(token, ids)
            code = None
        except m["ledger"].LedgerError as exc:
            code = exc.code
        admission = ledger.admission_report()["submission_slots"]
        checks.append({"name": "close_gate_" + name,
                       "ok": code == want and admission == 0
                       and controller.effects.report()["calls"] == [],
                       "observed": {"code": code, "submissions": admission}})
    return checks


def main(argv, root=SOURCE_ROOT):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", required=True)
    ap.add_argument("--out", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--native", action="store_true")
    args = ap.parse_args(argv)
    out = os.path.realpath(args.out)
    if os.path.exists(out):
        raise SystemExit("refusing to reuse evidence dir " + out)
    os.makedirs(out)
    # Opened before any guard exists, so evidence can be written even if
    # a guard is left installed in a non-IDLE phase by a failure.
    evidence = open(os.path.join(out, "evidence.json"), "x")
    ev = {"mode": "dry-run" if args.dry_run else "native",
          "source_root": root, "stage": "PINS", "primary_failure": None,
          "checks": [], "forks": 0}
    try:
        pins = load_pins(args.pins)
        ev["stage"] = "SOURCE_VERIFY"
        verified = verify_source_tree(root, pins)
        ev["stage"] = "IMPORT"
        m = import_shell(root, verified)
        ev["stage"] = "RUNTIME_SETUP"
        runtime, native, policy = setup_runtime(m, pins, root)
    except BaseException as exc:
        ev["primary_failure"] = describe_exception(exc, ev["stage"])
    if ev["primary_failure"] is None and args.dry_run:
        ev.update({"stage": "DRY_RUN", "runtime": safe(runtime.report()),
                   "native_provenance": safe(native.provenance),
                   "pidfd_opens": 0, "guard_installed": False})
        try:
            ev["checks"] = dry_run_close_gate(m, runtime, native, pins)
        except BaseException as exc:
            ev["primary_failure"] = describe_exception(exc, "DRY_RUN")
    elif ev["primary_failure"] is None:
        ev.update(run_native(m, runtime, native, policy, pins, out))
        ev["forks"] = 1 if ev["pid"] is not None else 0
    ok = (ev["primary_failure"] is None and bool(ev["checks"])
          and all(c["ok"] for c in ev["checks"]))
    ev["overall_ok"] = ok
    json.dump(safe(ev), evidence, indent=1, sort_keys=True)
    evidence.close()
    for c in ev["checks"]:
        print(("ok   " if c["ok"] else "FAIL ") + c["name"])
    if ev["primary_failure"]:
        print("primary_failure:", json.dumps(ev["primary_failure"]),
              file=sys.stderr)
    for failure in (ev.get("cleanup") or {}).get("failures", []):
        print("cleanup_failure:", json.dumps(safe(failure)), file=sys.stderr)
    for note in ev.get("notes", []):
        print("note:", note)
    print("overall_ok:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
