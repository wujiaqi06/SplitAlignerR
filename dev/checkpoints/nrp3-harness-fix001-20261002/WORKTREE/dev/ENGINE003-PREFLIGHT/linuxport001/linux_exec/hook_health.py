"""Outer hook-health adapter for the frozen p18 DevelopmentGuard.

DEVELOPMENT ONLY. The frozen guard installs `sys.settrace(self.trace)` and
`sys.setprofile(self.profile)` and reports only phase/event counts. CPython
clears a trace/profile hook whose callback raises, hooks are per thread, and
any code can replace them, so "installed" plus counters does not prove
continuous coverage. This adapter, outside the 17 frozen files:

    admit()        refuses admission if a trace or profile hook already
                   exists (it never silently overwrites or later "restores"
                   a caller's hook);
    bind(guard)    after guard.install(), records the expected callbacks by
                   identity (bound method __self__ is the guard and __func__
                   is the class function) and checks them immediately;
    check(label)   compares the current hooks with the expected ones; loss,
                   replacement or an unexpected hook irreversibly latches
                   MONITOR_COMPROMISED. Reinstalling a hook never clears it;
    release()      after guard.finish(), requires both hooks to be absent
                   (the admission state) and records the outcome.

Scope/claim limit: this checks the calling thread's hooks at explicit
points only. It is not isolation, not a syscall census, and a compromise
between two checks is detected only at the next check. The observation
window reads /proc/<pid>/stat of arbitrary pids during a whole-/proc census
(not only owned members).
"""

import sys

HEALTHY = "HEALTHY"
COMPROMISED = "MONITOR_COMPROMISED"


class HookAdmissionRefused(RuntimeError):
    pass


def _same_callback(current, expected_self, expected_func):
    return (current is not None
            and getattr(current, "__self__", None) is expected_self
            and getattr(current, "__func__", None) is expected_func)


class HookHealthMonitor:
    def __init__(self, gettrace=sys.gettrace, getprofile=sys.getprofile):
        self._gettrace, self._getprofile = gettrace, getprofile
        self.state = "NOT_ADMITTED"
        self.latched = None
        self.events = []
        self._guard = self._trace_func = self._profile_func = None

    def _record(self, label, ok, detail=None):
        self.events.append({"label": label, "ok": ok, "detail": detail})

    def _latch(self, label, detail):
        if self.latched is None:
            self.latched = {"label": label, "detail": detail}
        self.state = COMPROMISED
        self._record(label, False, detail)

    @property
    def compromised(self):
        return self.latched is not None

    def admit(self):
        trace, profile = self._gettrace(), self._getprofile()
        if trace is not None or profile is not None:
            self.state = "ADMISSION_REFUSED"
            self._record("admit", False, {"existing_trace": repr(trace),
                                          "existing_profile": repr(profile)})
            raise HookAdmissionRefused("EXISTING_TRACE_OR_PROFILE_HOOK")
        self.state = "ADMITTED"
        self._record("admit", True)

    def bind(self, guard):
        if self.state != "ADMITTED":
            raise HookAdmissionRefused("BIND_WITHOUT_ADMISSION:" + self.state)
        cls = type(guard)
        self._guard = guard
        self._trace_func = getattr(cls, "trace", None)
        self._profile_func = getattr(cls, "profile", None)
        self.state = HEALTHY
        self.check("bind")

    def check(self, label):
        if self._guard is None:
            self._latch(label, "NOT_BOUND")
            return False
        trace, profile = self._gettrace(), self._getprofile()
        ok = (_same_callback(trace, self._guard, self._trace_func)
              and _same_callback(profile, self._guard, self._profile_func))
        if not ok:
            self._latch(label, {"trace": repr(trace), "profile": repr(profile)})
            return False
        if self.latched is not None:
            # Hooks look right again (e.g. reinstalled): still compromised.
            self._record(label, False, "HOOKS_PRESENT_BUT_LATCHED")
            return False
        self._record(label, True)
        return True

    def release(self):
        trace, profile = self._gettrace(), self._getprofile()
        clean = trace is None and profile is None
        self._record("release", clean, None if clean else {
            "trace": repr(trace), "profile": repr(profile)})
        if not clean:
            self._latch("release", "HOOKS_REMAIN_AFTER_FINISH")
        return clean

    def report(self):
        return {"state": self.state, "compromised": self.compromised,
                "latched": self.latched, "events": list(self.events),
                "claim_scope": "CALLING_THREAD_HOOK_IDENTITY_AT_EXPLICIT_CHECKS",
                "isolation_claim": False, "syscall_census_claim": False}
