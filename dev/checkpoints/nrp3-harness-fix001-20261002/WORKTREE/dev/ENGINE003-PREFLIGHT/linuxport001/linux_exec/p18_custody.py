"""Native custody port: the unchanged p18 NativeOwnerController behind the
lifecycle's custody interface (one pidfd acquisition, one admitted close).

The 17 p18_working files are used byte-identical, loaded from verified bytes
by dev_build001/native_close_smoke.py. Nothing here reads `_key`, forges a
capability, monkeypatches a module or retries a close.

Development guard: `ObservingDevelopmentGuard` subclasses the p18
`DevelopmentGuard` and adds one thing, a declared observation window. The
window may only be opened while the guard is installed and IDLE. Controller
phases cannot be entered while a window is open. Inside the window, the only
extra admission is a read-only open (audited as mode "r", no write flags) of `/proc/<n>/stat` or
`/proc/<n>/smaps_rollup`. These reads are counted, not logged per read,
because the base guard's event log is bounded at 512 entries. Every other
rule is still the base guard's: os.close only in an admitted callback, no
fork/kill/exec/threads/sockets, no p01 proof functions outside proof phases,
and no other /proc read. The window lets the control plane's sampler observe
the owned process group while the provider holds the pidfd; it is not a
syscall census and grants no effect.
"""
import contextlib
import os
import re

from hook_health import HookHealthMonitor
from lifecycle import LifecycleError, need
from native_close_smoke import pins_sha, safe

OBSERVE_PATH = re.compile(r"/proc/[1-9][0-9]*/(stat|smaps_rollup)\Z")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
SOURCE_ID = "native_owner_controller.py"
IDS = {"reservation": "RES-1", "register": "EV-REGISTER-1",
       "attempt": "ATTEMPT-1", "begin": "EV-BEGIN-1", "complete": "EV-COMPLETE-1"}
ROLLBACK_IDS = {"attempt": "RB-ATTEMPT-1", "begin": "EV-RB-BEGIN-1",
                "complete": "EV-RB-COMPLETE-1"}
CONTROLLER_PHASES = (
    "PRE_OPEN_PREPARE", "RAW_CAPTURE", "REGISTER", "POST_REGISTER_PROOF",
    "VIEW_AND_RETURN", "NORMAL_CLOSE_BEGIN", "NORMAL_CLOSE_CALLBACK",
    "NORMAL_CLOSE_COMPLETE")


def observing_guard_class(base):
    class ObservingDevelopmentGuard(base):
        def __init__(self, runtime, run_root, source_files):
            super().__init__(runtime, run_root, source_files)
            self.observing = False
            self.observe_windows = 0
            self.observe_reads = 0

        def enter_phase(self, phase, token, capability, context=None):
            self._need(not self.observing, "CONTROLLER_PHASE_DURING_OBSERVE_WINDOW")
            return super().enter_phase(phase, token, capability, context)

        @contextlib.contextmanager
        def observe_window(self):
            self._need(self.installed and self.phase == "IDLE" and not self.observing,
                       "OBSERVE_WINDOW_STATE")
            self.observing = True
            self.observe_windows += 1
            self._record("observe_enter", {"window": self.observe_windows})
            try:
                yield self
            finally:
                self.observing = False
                self._record("observe_leave", {"window": self.observe_windows})

        def audit(self, event, args):
            if (self.installed and self.observing and event == "open"
                    and type(args[0]) is str and args[1] == "r"
                    and type(args[2]) is int and not args[2] & WRITE_FLAGS
                    and OBSERVE_PATH.match(args[0])):
                self.observe_reads += 1
                return None
            return super().audit(event, args)

        def report(self):
            out = super().report()
            out.update(scope="DEV_IMPLEMENT004_OBSERVING_DEVELOPMENT_GUARD_SUBCLASS",
                       base_scope=out["scope"], observe_windows=self.observe_windows,
                       observe_reads=self.observe_reads)
            return out

    return ObservingDevelopmentGuard


@contextlib.contextmanager
def _checked_window(window, health):
    """Hook identity is checked on entry and exit of every observe window."""
    with window as value:
        health.check("observe_enter")
        try:
            yield value
        finally:
            health.check("observe_leave")


def guard_state(guard):
    return {"phase": guard.phase, "events": len(guard.events)}


class P18Custody:
    """Single-use: one acquisition, at most one public normal close."""

    def __init__(self, m, runtime, native, policy, pins, run_root, run_id, owner_id):
        self.m, self.runtime, self.native, self.policy = m, runtime, native, policy
        self.pins, self.run_root = pins, run_root
        self.token = {"run_id": run_id, "owner_id": owner_id, "resource_id": "CHILD-1",
                      "generation": 1, "acquisition_id": "ACQ-1", "source_id": SOURCE_ID,
                      "source_sha256": pins[SOURCE_ID]["sha256"]}
        self.ledger = m["ledger"].Ledger({
            "run_id": run_id, "owner_id": owner_id,
            "sources": [{"source_id": SOURCE_ID, "sha256": pins[SOURCE_ID]["sha256"]}]})
        self.controller = self.guard = self.recorded = self.view = None
        self.expected = None
        self.close_attempted = False
        self.diagnostic_events = []
        self.guard_after_acquire = self.guard_before_finish = None
        self.hook_health = HookHealthMonitor()

    def preflight(self):
        env = self.native.acquisition_environment()
        try:
            self.m["p01"].validate_acquisition_environment(
                self.policy, env, self.native.no_cldwait)
            ok, observed = True, None
        except BaseException as exc:
            ok, observed = False, getattr(exc, "code", repr(exc))
        return [{"name": "p18_acquisition_environment", "ok": ok,
                 "observed": {"error": observed, "handler": env.handler,
                              "flags": env.flags, "task_count": env.task_count,
                              "python_threads": env.python_threads}}]

    def acquire(self, pid):
        need(self.controller is None, "CUSTODY_SINGLE_USE")
        # /proc/<pid>/stat is admitted by the guard only inside its proof
        # phases, so the expected identity is read before install.
        self.expected = self.m["p01"].direct_child_stat(pid)

        def diagnostic(event):
            self.diagnostic_events.append(event)
            return None
        self.recorded = self.m["recorded"].RecordedRegisteredNative(diagnostic)
        self.controller = self.m["controller"].NativeOwnerController(
            self.ledger, self.runtime, self.native, self.token, self.recorded,
            pins_sha(self.pins))
        cls = observing_guard_class(self.m["guard"].DevelopmentGuard)
        self.guard = cls(self.runtime, self.run_root,
                         [os.path.join(self.runtime.root, n) for n in sorted(self.pins)])
        self.runtime.bind_monitor(self.guard)
        self.hook_health.admit()
        self.guard.install()
        self.hook_health.bind(self.guard)
        view = self.controller.acquire_register_prove_direct_child(
            IDS["reservation"], IDS["register"], self.token, self.native, pid,
            self.expected, self.policy, dict(ROLLBACK_IDS))
        self.guard_after_acquire = guard_state(self.guard)
        self.hook_health.check("after_acquire")
        if type(view) is not self.runtime.view_class:
            raise LifecycleError("CUSTODY_ACQUIRE_NO_VIEW", type(view).__name__)
        self.view = view
        return {"pid": view.pid, "borrowed_fd": view.borrowed_fd,
                "starttime_ticks": view.proof.starttime_ticks,
                "expected": [self.expected.pid, self.expected.ppid,
                             self.expected.starttime_ticks]}

    def observe_window(self):
        return _checked_window(self.guard.observe_window(), self.hook_health)

    def close_pending(self):
        return self.view is not None and not self.close_attempted

    def close(self):
        need(self.close_pending(), "CUSTODY_CLOSE_NOT_PENDING")
        self.close_attempted = True
        snapshot = self.controller.close_registered_direct_child(
            self.token, {"attempt": IDS["attempt"], "begin": IDS["begin"],
                         "complete": IDS["complete"]})
        self.guard_before_finish = guard_state(self.guard)
        self.hook_health.check("before_finish")
        return {"confirmed": snapshot["controller_confirmed"] is True
                and snapshot["custody"] == "CONFIRMED_CLOSE", "snapshot": snapshot}

    def finish(self):
        if self.guard is not None and self.guard.installed:
            self.guard.finish()
            self.hook_health.release()

    def finished(self):
        return self.guard is None or not self.guard.installed

    def report(self):
        out = {"token": self.token, "expected": None, "close_attempted": self.close_attempted,
               "guard_after_acquire": self.guard_after_acquire,
               "guard_before_finish": self.guard_before_finish,
               "diagnostic_events": safe(self.diagnostic_events),
               "hook_health": self.hook_health.report()}
        if self.expected is not None:
            out["expected"] = [self.expected.pid, self.expected.ppid,
                               self.expected.starttime_ticks]
        for key, obj in (("controller", self.controller),
                         ("provider", self.controller and self.controller.effects),
                         ("guard", self.guard), ("recorded_native", self.recorded)):
            out[key] = None if obj is None else safe(obj.report())
        return out

    def evaluate(self, rep, pid):
        """Custody acceptance, same criteria as the verified one-child smoke."""
        checks = []

        def check(name, ok, observed=None):
            checks.append({"name": name, "ok": bool(ok), "observed": safe(observed)})

        ctl, led = rep["controller"], rep["controller"]["ledger"]
        row, adapter, snap = ctl["row"], ctl["adapter"], ctl["snapshot"]
        check("ledger_history_register_begin_complete",
              [(h["kind"], h["event_id"]) for h in led["history"]]
              == [("REGISTER", IDS["register"]), ("BEGIN", IDS["begin"]),
                  ("COMPLETE", IDS["complete"])], led["history"])
        replies = [row["full_register_reply"], adapter["begin_reply"],
                   adapter["complete_reply"]]
        check("ledger_exactly_three_submissions_all_accepted",
              ctl["admission"]["submission_slots"] == 3 and led["accepted_event_count"] == 3
              and [(r["accepted"], r["reason"], r["submission_slot"]) for r in replies]
              == [(True, None, 1), (True, None, 2), (True, None, 3)], ctl["admission"])
        check("ledger_single_obligation_confirmed_close",
              len(led["obligations"]) == 1
              and led["obligations"][0]["state"] == "CONFIRMED_CLOSE"
              and led["obligations"][0]["token"] == rep["token"]
              and led["obligations"][0]["fd"] == row["fd"]
              and led["all_close_outcomes_confirmed"] is True, led["obligations"])
        check("complete_outcome_success", led["history"][-1].get("outcome") == {
            "result": "SUCCESS", "return_value": 0, "errno": None,
            "diagnostic": "close returned None"}, led["history"][-1])
        check("controller_confirmed_no_holds_no_primary",
              snap["controller_confirmed"] is True and snap["holds"] == []
              and snap["primary"] == "NONE" and snap["custody"] == "CONFIRMED_CLOSE"
              and snap["rollback"] == "NOT_REQUESTED", snap)
        check("terminal_stop_latch_after_complete", snap["stop"] is True, snap["stop"])
        check("adapter_one_callback_raw_none",
              adapter["callback_entries"] == 1 and adapter["raw_observation"] == {
                  "kind": "RETURN", "python_type": "NoneType",
                  "representation": "None", "returned_normally": True}, adapter)
        calls = rep["provider"]["calls"]
        check("provider_single_callback_matches_begin_action",
              len(calls) == 1 and calls[0]["action"] == adapter["action"]
              and calls[0]["action"]["fd"] == row["fd"], calls)
        check("expected_identity_is_lifecycle_child",
              rep["expected"] is not None and rep["expected"][0] == pid, rep["expected"])
        g = rep["guard"]
        counters = g["counters"]
        check("guard_no_denials", g["denied"] == [], g["denied"])
        check("hook_health_never_compromised",
              rep["hook_health"]["compromised"] is False, rep["hook_health"])
        check("guard_one_open_one_close_one_invoke",
              counters.get("pidfd_open_entry") == 1 and counters.get("os_close_entry") == 1
              and counters.get("provider_invoke_entry") == 1, counters)
        check("guard_idle_after_public_operations",
              rep["guard_after_acquire"]["phase"] == "IDLE"
              and rep["guard_before_finish"]["phase"] == "IDLE",
              [rep["guard_after_acquire"], rep["guard_before_finish"]])
        check("guard_finish_added_no_events",
              rep["guard_before_finish"]["events"] == len(g["events"]))
        phases = [(e["kind"], e["details"].get("phase")) for e in g["events"]
                  if e["kind"] in ("phase_enter", "phase_leave")]
        want = [(k, p) for p in CONTROLLER_PHASES for k in ("phase_enter", "phase_leave")]
        check("guard_controller_phases_exactly_paired", phases == want, phases)
        windows = [e["kind"] for e in g["events"]
                   if e["kind"] in ("observe_enter", "observe_leave")]
        check("guard_observe_windows_paired_outside_phases",
              g["observe_windows"] >= 1
              and windows == ["observe_enter", "observe_leave"] * g["observe_windows"]
              and all(e["phase"] == "IDLE" for e in g["events"]
                      if e["kind"] in ("observe_enter", "observe_leave"))
              and g["observe_reads"] > 0,
              {"windows": g["observe_windows"], "reads": g["observe_reads"]})
        rec = rep["recorded_native"]["events"]
        check("recorded_open_attempt_and_return",
              len(rec) == 2 and rec[0]["kind"] == "PIDFD_OPEN_ATTEMPT"
              and rec[1]["status"] == "PIDFD_OPEN_RETURN_RECORDED", rec)
        return checks
