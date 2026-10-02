"""P17 phase monitor; source/API control, not syscall isolation or authority."""
import copy
import os
import sys


PHASES = (
    "PRE_OPEN_PREPARE", "RAW_CAPTURE", "REGISTER",
    "POST_REGISTER_PROOF", "VIEW_AND_RETURN", "ROLLBACK_BEGIN",
    "ROLLBACK_CALLBACK", "ROLLBACK_COMPLETE", "NORMAL_CLOSE_BEGIN",
    "NORMAL_CLOSE_CALLBACK", "NORMAL_CLOSE_COMPLETE", "STOP",
)


class ScopeViolation(BaseException):
    pass


class DevelopmentGuard:
    def __init__(self, runtime, run_root, source_files):
        self.runtime = runtime
        self.run_root = str(run_root) + "/"
        self.source_files = set(str(item) for item in source_files)
        self.phase = "IDLE"
        self.token = None
        self.capability = None
        self.context = {}
        self.events = []
        self.denied = []
        self.counters = {}
        self.installed = False
        self.last_effect_phase = None

    def _record(self, kind, details=None):
        if len(self.events) >= 512:
            raise ScopeViolation("DEVELOPMENT_EVENT_BOUND")
        self.counters[kind] = self.counters.get(kind, 0) + 1
        row = {
            "index": len(self.events), "kind": kind, "phase": self.phase,
            "token": copy.deepcopy(self.token), "details": details or {},
        }
        self.events.append(row)
        return row

    def _need(self, condition, reason):
        if not condition:
            self.denied.append({
                "reason": reason, "phase": self.phase,
                "token": copy.deepcopy(self.token),
                "context": copy.deepcopy(self.context),
            })
            raise ScopeViolation(reason)

    def enter_phase(self, phase, token, capability, context=None):
        self._need(self.phase == "IDLE", "NESTED_DIRECT_CHILD_PHASE")
        self._need(phase in PHASES, "UNKNOWN_DIRECT_CHILD_PHASE")
        if phase == "PRE_OPEN_PREPARE":
            self._need(type(capability) is self.runtime.prepare_capability_class,
                       "PREPARE_CAPABILITY_PHASE")
        elif phase == "RAW_CAPTURE":
            self._need(type(capability) is self.runtime.capture_capability_class,
                       "CAPTURE_CAPABILITY_PHASE")
        elif phase == "POST_REGISTER_PROOF":
            self._need(type(capability) is self.runtime.proof_capability_class,
                       "PROOF_CAPABILITY_PHASE")
        elif phase == "VIEW_AND_RETURN":
            self._need(type(capability) is self.runtime.view_capability_class,
                       "VIEW_CAPABILITY_PHASE")
        self.phase = phase
        self.token = copy.deepcopy(token)
        self.capability = capability
        self.context = dict(context or {})
        self._record("phase_enter", {"phase": phase})
        return len(self.events)

    def leave_phase(self):
        self.last_effect_phase = self.phase
        self._record("phase_leave", {"phase": self.phase})
        self.phase = "IDLE"
        self.token = None
        self.capability = None
        self.context = {}

    def trace(self, frame, event, arg):
        if event != "call":
            return None
        code = frame.f_code
        if code.co_filename == self.runtime.p01_path:
            name = code.co_name
            pre = {
                "acquisition_environment", "validate_acquisition_environment",
                "wait_without_reaping", "direct_child_stat", "bounded_read",
            }
            post = set(pre)
            if name in pre:
                self._need(self.phase in ("PRE_OPEN_PREPARE",
                                          "POST_REGISTER_PROOF"),
                           "P01_PROOF_FUNCTION_PHASE:" + name)
                if self.phase == "POST_REGISTER_PROOF":
                    self._need(type(self.capability)
                               is self.runtime.proof_capability_class,
                               "POST_REGISTER_PROOF_CAPABILITY")
                self._record("p01_" + name)
            elif name == "open":
                native = frame.f_locals.get("self")
                self._need(self.phase == "RAW_CAPTURE"
                           and type(native) is self.runtime.native_class
                           and type(frame.f_locals.get("pid")) is int
                           and not isinstance(frame.f_locals.get("pid"), bool)
                           and frame.f_locals.get("flags") == 0
                           and self.counters.get("pidfd_open_entry", 0) == 0,
                           "PIDFD_OPEN_RAW_CAPTURE_ONLY")
                self._record("pidfd_open_entry", {
                    "pid": frame.f_locals.get("pid"), "flags": 0})
            elif name in ("send", "ready", "close"):
                self._need(False, "FORBIDDEN_PIDFD_PATH:" + name)
            elif name == "__init__":
                obj = frame.f_locals.get("self")
                if type(obj) is self.runtime.handle_class:
                    self._need(False, "OWNING_PIDFD_HANDLE_CONSTRUCTION")
        if code.co_filename == self.runtime.effects_path and code.co_name == "invoke":
            self._need(self.phase in ("ROLLBACK_CALLBACK",
                                      "NORMAL_CLOSE_CALLBACK")
                       and self.context.get("accepted_begin_action") is True,
                       "PROVIDER_CALLBACK_PHASE")
            self._record("provider_invoke_entry")
        return None

    def profile(self, frame, event, function):
        if event != "c_call":
            return
        name = getattr(function, "__name__", "")
        module = getattr(function, "__module__", None)
        owner = getattr(function, "__self__", None)
        if function is self.runtime.os_close:
            self._need(self.phase in ("ROLLBACK_CALLBACK",
                                      "NORMAL_CLOSE_CALLBACK")
                       and self.context.get("accepted_begin_action") is True
                       and frame.f_code.co_filename == self.runtime.effects_path
                       and frame.f_code.co_name == "invoke"
                       and self.counters.get("os_close_entry", 0) == 0,
                       "OS_CLOSE_ACCEPTED_BEGIN_ONLY")
            self._record("os_close_entry", {
                "fd": frame.f_locals.get("row").fd,
                "token": copy.deepcopy(self.token),
            })
        elif module == "posix" and name in {
                "fork", "forkpty", "posix_spawn", "posix_spawnp", "execv",
                "execve", "kill", "killpg", "system", "dup", "dup2",
                "pipe", "pipe2", "_exit"}:
            self._need(False, "FORBIDDEN_POSIX_ENTRY:" + name)
        elif module == "_thread" and name in {"start_new_thread", "start_new"}:
            self._need(False, "CANDIDATE_THREAD_CREATION")
        elif name in {"send", "sendall", "sendto", "sendmsg", "recv",
                      "recv_into", "recvfrom", "recvmsg", "connect",
                      "connect_ex", "bind", "listen", "accept", "dup"}:
            if owner is not None and type(owner).__module__ in ("socket", "_socket"):
                self._need(False, "FORBIDDEN_SOCKET_ENTRY:" + name)

    def audit(self, event, args):
        if not self.installed:
            return
        if event in {
                "os.fork", "os.forkpty", "os.kill", "os.killpg",
                "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                "socket.connect", "socket.bind", "socket.getaddrinfo",
                "socket.sendto", "socket.sendmsg"}:
            self._need(False, "FORBIDDEN_AUDIT:" + event)
        if event == "open":
            path, mode, flags = args
            self._need(not isinstance(path, int), "UNPLANNED_FDOPEN")
            path = os.fspath(path)
            writing = isinstance(mode, str) and any(
                item in mode for item in ("w", "a", "x", "+"))
            if writing:
                self._need(self.phase == "IDLE"
                           and path.startswith(self.run_root),
                           "WRITE_OUTSIDE_RUN_EVIDENCE")
            elif path.startswith("/proc/"):
                allowed_pre = (self.phase == "PRE_OPEN_PREPARE"
                               and path.endswith("/stat"))
                allowed_post = (self.phase == "POST_REGISTER_PROOF"
                                and (path.endswith("/stat")
                                     or path.startswith("/proc/self/fdinfo/")))
                self._need(allowed_pre or allowed_post,
                           "PROC_READ_PHASE")
                self._record("proc_read", {"path": path_tail(path)})
            else:
                self._need(path in self.source_files
                           or path.startswith(self.run_root),
                           "UNPLANNED_READ:" + path)

    def install(self):
        self._need(not self.installed, "MONITOR_ALREADY_INSTALLED")
        self.installed = True
        sys.addaudithook(self.audit)
        sys.settrace(self.trace)
        sys.setprofile(self.profile)

    def finish(self):
        if self.phase != "IDLE":
            self.leave_phase()
        self.installed = False
        sys.setprofile(None)
        sys.settrace(None)

    def report(self):
        return {
            "scope": "P17_DEVELOPMENT_SOURCE_API_MONITOR_ONLY",
            "counters": dict(self.counters),
            "events": copy.deepcopy(self.events),
            "denied": copy.deepcopy(self.denied),
            "kernel_syscall_census": False,
            "arbitrary_code_isolation": False,
            "native_candidate_execution": False,
        }


def path_tail(path):
    return path.rsplit("/", 2)[-1]
