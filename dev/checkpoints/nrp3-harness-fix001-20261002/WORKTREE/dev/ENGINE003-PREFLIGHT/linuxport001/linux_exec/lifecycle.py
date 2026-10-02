"""Callable Linux owned-direct-child execution lifecycle (development only).

    result = run_lifecycle(cfg, ports)   # admits internally, then runs
    checks = evaluate(cfg, result)       # reads result["admission"]

`preflight(cfg, ports)` is public for admission-only reporting (no fork),
but its return value is never accepted as approval: `run_lifecycle` takes no
admission argument and re-runs `preflight` on the exact cfg/ports it is about
to use, immediately before the first pipe. A refusal raises
LifecycleError("NOT_ADMITTED") with zero pipe/fork/custody effects.

One harmless owned direct child is driven through

    SPAWNED -> READY -> IDENTIFIED -> SAMPLER_BOUND -> ACQUIRED -> OBSERVED
      -> STOP_REQUESTED -> EXITED -> POST_EXIT_OBSERVED -> CLOSED
    cleanup: custody close (only if still pending) -> custody finish ->
             stop byte / control-pipe close -> bounded reap -> RELEASED

Ports (`Ports`, all injectable so adverse cases run synthetically):
  ops             pipe/fork/close/write/read/wait_readable/waitpid/getpid/
                  monotonic/sleep/uname/thread_count/child_main. There is no
                  kill or signal member: this lifecycle never signals.
  backend         LinuxProcSamplerBackend (identity, census, RSS).
  sampler_factory (root_pid, backend) -> the control plane's sampler.
  sample / sampler_report   one synchronous sampler tick / its report.
  custody         acquire(pid) / observe_window() / close_pending() / close()
                  / finish() / finished() / report() / evaluate(); the native
                  one is p18_custody.P18Custody.
  mounts          () -> parsed /proc/self/mountinfo rows (preflight only).

Ownership rules: the lifecycle owns exactly the child pid and the parent ends
of two pipes; the provider pidfd is never closed, duplicated or signalled
here. The borrowed fd is only polled for exit readiness. Stop is one b"S" on
the control pipe (EOF also stops the child); the child also has a bounded
self-timeout. The child is reaped only after the custody close, so its pid
cannot be reused while custody or observation is live. Reaping is
reclamation, not close confirmation.
"""
import math
import os
import select
import sys
import threading
import time
from dataclasses import dataclass, field, asdict

HERE = os.path.dirname(os.path.realpath(__file__))
DEV_BUILD001 = os.path.realpath(os.path.join(HERE, "..", "dev_build001"))
if DEV_BUILD001 not in sys.path:
    sys.path.append(DEV_BUILD001)
from native_close_smoke import describe_exception, safe  # noqa: E402

SUCCESS_STATES = (
    "ADMITTED", "SPAWNED", "READY", "IDENTIFIED", "SAMPLER_BOUND", "ACQUIRED",
    "OBSERVED", "STOP_REQUESTED", "EXITED", "POST_EXIT_OBSERVED", "CLOSED",
    "RELEASED")
FORBIDDEN_HIDEPID = (b"hidepid=1", b"hidepid=2", b"hidepid=invisible",
                     b"hidepid=noaccess", b"subset=pid")
MAX_BALLAST = 64 << 20
MAX_TIMEOUT_S = 120.0


class LifecycleError(Exception):
    def __init__(self, code, detail=None, admission=None):
        self.code = code
        self.admission = admission
        super().__init__(code if detail is None else "%s: %s" % (code, detail))


def need(ok, code, detail=None):
    if not ok:
        raise LifecycleError(code, detail)


@dataclass(frozen=True)
class LifecycleConfig:
    run_id: str = "DEV_IMPLEMENT004_LIFECYCLE"
    owner_id: str = "DEV_IMPLEMENT004_HARNESS"
    ballast_bytes: int = 8 << 20
    ready_timeout_s: float = 10.0
    observe_samples: int = 3
    observe_interval_s: float = 0.05
    exit_timeout_s: float = 10.0
    reap_timeout_s: float = 10.0
    child_self_timeout_s: float = 60.0

    def problems(self):
        out = []
        if type(self.ballast_bytes) is not int or not 0 <= self.ballast_bytes <= MAX_BALLAST:
            out.append("ballast_bytes")
        if type(self.observe_samples) is not int or not 1 <= self.observe_samples <= 20:
            out.append("observe_samples")
        for name in ("ready_timeout_s", "exit_timeout_s", "reap_timeout_s",
                     "child_self_timeout_s"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 < value <= MAX_TIMEOUT_S):
                out.append(name)
        value = self.observe_interval_s
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            out.append("observe_interval_s")
        return out


# --------------------------------------------------------------------------
# Real child-lifecycle effects
# --------------------------------------------------------------------------

def _child_main(ctl_r, ctl_w, rdy_r, rdy_w, ballast_bytes, self_timeout_s):
    """Harmless owned child: own session, bounded ballast, waits for stop."""
    code = 0
    try:
        os.close(ctl_w)
        os.close(rdy_r)
        os.setsid()
        ballast = b"\x5a" * ballast_bytes
        os.write(rdy_w, b"R")
        os.close(rdy_w)
        deadline = time.monotonic() + self_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                code = 4
                break
            if select.select([ctl_r], [], [], min(remaining, 1.0))[0]:
                if os.read(ctl_r, 1) in (b"", b"S"):
                    break
        del ballast
    except BaseException:
        code = 3
    finally:
        os._exit(code)


def _wait_readable(fd, timeout_s):
    """poll(2) readiness; for a pidfd, readable means the process exited."""
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP)
    events = poller.poll(max(0, int(timeout_s * 1000)))
    if not events:
        return False
    need(len(events) == 1 and events[0][0] == fd
         and not events[0][1] & (select.POLLNVAL | select.POLLERR),
         "POLL_ERROR", events)
    return True


class RealOps:
    pipe = staticmethod(os.pipe)
    fork = staticmethod(os.fork)
    close = staticmethod(os.close)
    write = staticmethod(os.write)
    read = staticmethod(os.read)
    waitpid = staticmethod(os.waitpid)
    getpid = staticmethod(os.getpid)
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    uname = staticmethod(os.uname)
    thread_count = staticmethod(threading.active_count)
    wait_readable = staticmethod(_wait_readable)
    child_main = staticmethod(_child_main)


OPS_INTERFACE = frozenset(
    name for name in vars(RealOps) if not name.startswith("_"))


@dataclass
class Ports:
    ops: object
    backend: object
    sampler_factory: object
    sample: object
    sampler_report: object
    custody: object
    mounts: object


# --------------------------------------------------------------------------
# Owned resources
# --------------------------------------------------------------------------

class OwnedChild:
    """Exactly what the lifecycle owns: one pid and parent pipe ends."""

    def __init__(self):
        self.pid = None
        self.fds = {}

    def still_owned(self):
        return {"pid": self.pid, "fds": dict(self.fds)}


def close_owned(child, name, step, steps, ops):
    """One close per owned fd; ownership dropped first, failure not retried."""
    fd = child.fds.pop(name, None)
    if fd is None:
        return None
    try:
        ops.close(fd)
    except BaseException as exc:
        steps.append({"step": step, "ok": False, "fd": fd, "retried": False,
                      "error": describe_exception(exc)})
        return False
    steps.append({"step": step, "ok": True, "fd": fd})
    return True


def spawn(cfg, child, result, ops):
    """Fork one owned child; pid and fork count are recorded before anything
    that can fail afterwards (a failed parent-side close still reports it)."""
    steps = result["spawn_steps"]
    try:
        child.fds["ctl_r"], child.fds["ctl_w"] = ops.pipe()
        child.fds["rdy_r"], child.fds["rdy_w"] = ops.pipe()
        pid = ops.fork()
    except BaseException:
        for name in ("ctl_r", "ctl_w", "rdy_r", "rdy_w"):
            close_owned(child, name, "spawn_failed_close_" + name, steps, ops)
        raise
    if pid == 0:
        ops.child_main(child.fds["ctl_r"], child.fds["ctl_w"], child.fds["rdy_r"],
                       child.fds["rdy_w"], cfg.ballast_bytes, cfg.child_self_timeout_s)
    child.pid = pid
    result["pid"] = pid
    result["forks"] += 1
    ok_r = close_owned(child, "ctl_r", "parent_close_ctl_r", steps, ops)
    ok_w = close_owned(child, "rdy_w", "parent_close_rdy_w", steps, ops)
    need(ok_r and ok_w, "PARENT_PIPE_CLOSE_FAILED")
    return pid


# --------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------

def preflight(cfg, ports):
    """Development admission: every check must pass before any fork."""
    checks = []

    def check(name, fn):
        try:
            observed = fn()
            ok = observed.pop("ok") if isinstance(observed, dict) and "ok" in observed else bool(observed)
        except BaseException as exc:
            ok, observed = False, describe_exception(exc)
        checks.append({"name": name, "ok": bool(ok), "observed": safe(observed)})

    ops, backend = ports.ops, ports.backend
    check("config_bounds", lambda: {"ok": not cfg.problems(), "problems": cfg.problems()})
    check("platform_linux_x86_64", lambda: (
        lambda u: {"ok": u.sysname == "Linux" and u.machine == "x86_64",
                   "sysname": u.sysname, "machine": u.machine,
                   "release": u.release})(ops.uname()))
    check("single_thread", lambda: {"ok": ops.thread_count() == 1,
                                    "threads": ops.thread_count()})

    def proc_mount():
        rows = [r for r in ports.mounts() if r.mount_point == b"/proc"]
        opts = [o for r in rows for o in r.super_options]
        return {"ok": len(rows) >= 1 and all(r.fs_type == "proc" for r in rows)
                and not any(o in FORBIDDEN_HIDEPID for o in opts),
                "mounts": len(rows), "super_options": [o.decode() for o in opts]}
    check("proc_mounted_without_hidepid", proc_mount)

    def self_identity():
        pid = ops.getpid()
        ppid, pgid, identity = backend.identity_and_group(pid)
        rss = backend.rss(pid)
        return {"ok": identity[0] == pid and rss > 0, "identity": list(identity),
                "pgid": pgid, "rss_bytes": rss}
    check("self_identity_and_rss_readable", self_identity)
    check("no_preexisting_children", lambda: (
        lambda kids: {"ok": kids == (), "children": list(kids)})(
            backend.children(ops.getpid())))
    for row in ports.custody.preflight():
        checks.append(row)
    return {"admitted": bool(checks) and all(c["ok"] for c in checks),
            "checks": checks, "config": asdict(cfg)}


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def new_result(cfg):
    return {"states": [], "stage": "NEW", "pid": None, "forks": 0,
            "primary_failure": None, "spawn_steps": [], "identity": None,
            "view": None, "samples": [], "pidfd_ready_while_alive": [],
            "stop_request_bytes": None, "pidfd_ready_after_stop": None,
            "exit_record": None, "post_exit_sample": None, "close": None,
            "cleanup": None, "child": None, "sampler": None, "custody": None,
            "backend": None, "admission": None, "config": asdict(cfg)}


def _enter(result, state):
    result["states"].append(state)
    result["stage"] = state


def admit(cfg, ports):
    """Current admission for exactly these cfg/ports; raises unless admitted.

    Only reads (uname, thread count, mountinfo, own /proc entries, a /proc
    census, the custody's own environment checks) happen here.
    """
    need(type(cfg) is LifecycleConfig, "CONFIG_TYPE", type(cfg).__name__)
    need(type(ports) is Ports, "PORTS_TYPE", type(ports).__name__)
    need(not cfg.problems(), "CONFIG_BOUNDS", cfg.problems())
    admission = preflight(cfg, ports)
    if admission["admitted"] is not True:
        raise LifecycleError(
            "NOT_ADMITTED", [c["name"] for c in admission["checks"] if not c["ok"]],
            admission=admission)
    return admission


def run_lifecycle(cfg, ports):
    admission = admit(cfg, ports)
    result = new_result(cfg)
    result["admission"] = admission
    ops, backend, custody = ports.ops, ports.backend, ports.custody
    child, sampler = OwnedChild(), None
    _enter(result, "ADMITTED")
    try:
        result["stage"] = "SPAWN"
        spawn(cfg, child, result, ops)
        _enter(result, "SPAWNED")

        result["stage"] = "READY_WAIT"
        need(ops.wait_readable(child.fds["rdy_r"], cfg.ready_timeout_s),
             "CHILD_READY_TIMEOUT")
        need(ops.read(child.fds["rdy_r"], 1) == b"R", "CHILD_READY_PROTOCOL")
        need(close_owned(child, "rdy_r", "parent_close_rdy_r",
                         result["spawn_steps"], ops), "READY_PIPE_CLOSE_FAILED")
        _enter(result, "READY")

        record = backend.observe(child.pid)
        ppid, pgid, identity = backend.identity_and_group(child.pid)
        result["identity"] = {"identity": list(identity), "ppid": ppid, "pgid": pgid,
                              "session": record.session, "state": record.state}
        need(ppid == ops.getpid(), "CHILD_NOT_DIRECT")
        need(pgid == child.pid and record.session == child.pid,
             "CHILD_NOT_DEDICATED_SESSION_LEADER", result["identity"])
        _enter(result, "IDENTIFIED")

        sampler = ports.sampler_factory(child.pid, backend)
        _enter(result, "SAMPLER_BOUND")

        view = custody.acquire(child.pid)
        result["view"] = safe(view)
        need(view["pid"] == child.pid and view["starttime_ticks"] == identity[1],
             "CUSTODY_BACKEND_IDENTITY_DISAGREEMENT", view)
        fd = view["borrowed_fd"]
        _enter(result, "ACQUIRED")

        for _ in range(cfg.observe_samples):
            with custody.observe_window():
                tick = ports.sample(sampler)
            result["samples"].append(tick)
            ready = ops.wait_readable(fd, 0)
            result["pidfd_ready_while_alive"].append(ready)
            need(not ready, "PIDFD_READY_BEFORE_STOP")
            need(child.pid in tick["active_owned_pids"]
                 and tick["current_root_bytes"] > 0, "ROOT_NOT_SAMPLED_LIVE", tick)
            ops.sleep(cfg.observe_interval_s)
        _enter(result, "OBSERVED")

        result["stop_request_bytes"] = ops.write(child.fds["ctl_w"], b"S")
        need(result["stop_request_bytes"] == 1, "STOP_REQUEST_SHORT_WRITE")
        _enter(result, "STOP_REQUESTED")

        result["pidfd_ready_after_stop"] = ops.wait_readable(fd, cfg.exit_timeout_s)
        need(result["pidfd_ready_after_stop"], "CHILD_EXIT_TIMEOUT_NO_SIGNAL")
        _enter(result, "EXITED")

        with custody.observe_window():
            exit_record = backend.observe(child.pid)
            result["post_exit_sample"] = ports.sample(sampler)
        result["exit_record"] = exit_record.report()
        need(exit_record.state == "Z" and exit_record.identity == identity,
             "EXIT_IDENTITY_CONTRADICTION", result["exit_record"])
        need(child.pid in result["post_exit_sample"]["identity_aware_exit_pids"],
             "SAMPLER_EXIT_NOT_OBSERVED", result["post_exit_sample"])
        _enter(result, "POST_EXIT_OBSERVED")

        result["close"] = custody.close()
        need(result["close"]["confirmed"] is True, "CUSTODY_CLOSE_NOT_CONFIRMED")
        _enter(result, "CLOSED")
    except BaseException as exc:
        result["primary_failure"] = describe_exception(exc, result["stage"])
    result["cleanup"], result["child"] = cleanup(cfg, child, custody, result, ops)
    if result["cleanup"]["complete"] and result["primary_failure"] is None:
        _enter(result, "RELEASED")
    for key, fn in (("sampler", lambda: sampler and ports.sampler_report(sampler)),
                    ("backend", backend.authority_evidence),
                    ("custody", custody.report)):
        try:
            result[key] = safe(fn())
        except BaseException as exc:
            result[key] = {"unavailable": describe_exception(exc)}
    return result


def cleanup(cfg, child, custody, result, ops):
    """Never raises. Custody before child, so the pid stays unreaped (and so
    not reusable) until the provider fd has had its single admitted close."""
    steps = []

    def step(name, fn):
        try:
            detail = fn()
            steps.append({"step": name, "ok": True, "detail": safe(detail)})
        except BaseException as exc:
            steps.append({"step": name, "ok": False, "retried": False,
                          "error": describe_exception(exc)})

    if _safe_call(custody.close_pending):
        def late_close():
            result["close"] = custody.close()
            return result["close"]
        step("custody_close_single_attempt", late_close)
    if not _safe_call(custody.finished):
        step("custody_finish", custody.finish)
    child_state = release_child(cfg, child, result, steps, ops)
    complete = (all(s["ok"] for s in steps) and child.pid is None and not child.fds
                and _safe_call(custody.finished) and not _safe_call(custody.close_pending))
    return ({"steps": steps, "complete": complete,
             "failures": [s for s in steps if not s["ok"]],
             "still_owned": child.still_owned()}, child_state)


def _safe_call(fn):
    try:
        return fn()
    except BaseException:
        return None


def release_child(cfg, child, result, steps, ops):
    """Stop byte (unless already sent), pipe closes, bounded reap.

    The stop byte comes first so the child exits promptly even when an fd
    close is refused (e.g. a development guard whose hooks stayed active).
    """
    state = {"pid": child.pid, "reaped": False, "wait_status": None,
             "exit_code": None, "signals_sent": 0, "reap_deadline_s": None,
             "stop_byte_in_cleanup": None}
    if child.pid is None:
        for name in list(child.fds):
            close_owned(child, name, "close_" + name, steps, ops)
        return state
    # One stop byte per lifecycle: never re-sent after the normal request.
    stop_sent = result.get("stop_request_bytes") == 1
    if not stop_sent and "ctl_w" in child.fds:
        try:
            state["stop_byte_in_cleanup"] = ops.write(child.fds["ctl_w"], b"S")
            stop_sent = state["stop_byte_in_cleanup"] == 1
            steps.append({"step": "cleanup_stop_byte", "ok": True})
        except BrokenPipeError:
            stop_sent = True    # child already closed its end
            steps.append({"step": "cleanup_stop_byte", "ok": True,
                          "detail": "EPIPE: child already exited"})
        except BaseException as exc:
            steps.append({"step": "cleanup_stop_byte", "ok": False,
                          "retried": False, "error": describe_exception(exc)})
    closed = close_owned(child, "ctl_w", "close_ctl_w", steps, ops)
    close_owned(child, "rdy_r", "close_rdy_r", steps, ops)
    limit = (cfg.reap_timeout_s if (stop_sent or closed)
             else cfg.child_self_timeout_s + cfg.reap_timeout_s)
    state["reap_deadline_s"] = limit
    try:
        deadline = ops.monotonic() + limit
        while True:
            waited, status = ops.waitpid(child.pid, os.WNOHANG)
            if waited == child.pid:
                child.pid = None
                state.update(reaped=True, wait_status=status,
                             exit_code=os.WEXITSTATUS(status)
                             if os.WIFEXITED(status) else None)
                steps.append({"step": "child_reap", "ok": True})
                return state
            if ops.monotonic() >= deadline:
                steps.append({"step": "child_reap", "ok": False,
                              "error": "not reaped within %ss; no signal sent" % limit})
                return state
            ops.sleep(0.02)
    except BaseException as exc:
        steps.append({"step": "child_reap", "ok": False, "error": describe_exception(exc)})
        return state


# --------------------------------------------------------------------------
# Acceptance (development evidence, not certification)
# --------------------------------------------------------------------------

def evaluate(cfg, result):
    """Checks read from recorded state. Never uses traceback formatting or
    any file I/O, so it is safe even if a guard left hooks active."""
    checks = []
    try:
        _evaluate(cfg, result, checks)
    except BaseException as exc:
        checks.append({"name": "evaluation", "ok": False,
                       "observed": describe_exception(exc)})
    return checks


def _evaluate(cfg, result, checks):
    def check(name, ok, observed=None):
        checks.append({"name": name, "ok": bool(ok), "observed": safe(observed)})

    admission = result["admission"]
    check("admitted_internally_before_fork", admission["admitted"] is True
          and admission["config"] == result["config"] == asdict(cfg),
          [c["name"] for c in admission["checks"] if not c["ok"]])
    check("no_primary_failure", result["primary_failure"] is None,
          result["primary_failure"])
    check("state_sequence", tuple(result["states"]) == SUCCESS_STATES, result["states"])
    check("exactly_one_fork", result["forks"] == 1 and result["pid"] is not None,
          [result["forks"], result["pid"]])
    cl = result["cleanup"]
    check("cleanup_complete", cl["complete"] is True and cl["failures"] == [], cl)
    ident = result["identity"]
    check("child_is_direct_dedicated_session_leader",
          ident["pgid"] == result["pid"] and ident["session"] == result["pid"]
          and ident["identity"][0] == result["pid"], ident)
    check("custody_and_backend_agree_on_identity",
          result["view"]["pid"] == result["pid"]
          and result["view"]["starttime_ticks"] == ident["identity"][1], result["view"])
    samples = result["samples"]
    check("control_plane_sampler_observed_live_root",
          len(samples) == cfg.observe_samples
          and all(result["pid"] in s["active_owned_pids"] and s["current_root_bytes"] > 0
                  for s in samples), samples)
    check("pidfd_not_ready_while_alive",
          result["pidfd_ready_while_alive"] == [False] * cfg.observe_samples,
          result["pidfd_ready_while_alive"])
    check("cooperative_stop_one_byte_no_signal",
          result["stop_request_bytes"] == 1 and result["child"]["signals_sent"] == 0,
          [result["stop_request_bytes"], result["child"]["signals_sent"]])
    check("pidfd_ready_after_stop", result["pidfd_ready_after_stop"] is True)
    rec = result["exit_record"]
    check("exit_is_unreaped_zombie_with_same_identity",
          rec["state"] == "Z" and [rec["pid"], rec["starttime_ticks"], 0]
          == ident["identity"], rec)
    check("sampler_identity_aware_exit",
          result["pid"] in result["post_exit_sample"]["identity_aware_exit_pids"]
          and result["pid"] in result["sampler"]["identity_aware_exit_pids"],
          result["post_exit_sample"])
    check("sampler_error_none_maximum_positive",
          result["sampler"]["error"] == "NONE"
          and result["sampler"]["maximum_root_bytes"] > 0, result["sampler"])
    check("custody_close_confirmed_before_reap",
          result["close"]["confirmed"] is True
          and result["states"].index("CLOSED") < result["states"].index("RELEASED"),
          result["close"])
    child = result["child"]
    check("child_reaped_exit0_reclamation_only",
          child["reaped"] is True and child["exit_code"] == 0
          and child["signals_sent"] == 0, child)
    backend = result["backend"]
    check("backend_no_external_process_table",
          backend["external_process_table_call_count"] == 0
          and backend["group_census_unresolved_count"] == 0, backend)
