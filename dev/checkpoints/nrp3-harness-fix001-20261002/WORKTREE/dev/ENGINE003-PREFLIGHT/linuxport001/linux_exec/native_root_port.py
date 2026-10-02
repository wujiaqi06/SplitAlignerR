"""NRP3: native Linux root-capability provider for the shared controller.

ROOT ONLY.  One native authority: a pidfd for the controller's own unreaped
direct child, acquired right after spawn.  No member, group or descendant
path (group_signal refuses first; object_present/object_matches refuse).
No signal implementation: PidfdRootPort.signal refuses unconditionally and
sys_ports has no send entry.  Option B: no root-identity reporter anywhere,
so the controller's EFFECT identity stays None; the native observation lives
only in native_identity_report() / the capability table and is labelled
NATIVE_OBSERVATION_NOT_JOURNAL_IDENTITY.  Native construction goes only
through build_native_entry (explicit opt-in, no modeled identity), and the
route refuses to run when wrapped by another termination object.

Acquisition order (P01 + boot_id): P0 preflight validate_environment; A0
getpid, A1 validate_environment, A2 child_stat (expected), A3 wait_nowait,
A4 child_stat (before == expected), A5 boot_id, A6 table.acquire -> port open
(getpid owner sample, pidfd_open); verify V1 child_stat (after == before),
V2 wait_nowait, V3 validate_environment, V4 fdinfo Pid binding, V5 boot_id.
The p18 composite direct-child acquisition helper is never used: its own
in-function close is off-ledger.

Custody.  The CapabilityTable ledger (unchanged) plus the port's own custody
ledger (PidfdRootPort.handles), whose entry exists before the syscall.  open
contains no close; PidfdRootPort.close is the only caller of close_fd and
P18SysPorts.close_fd is the only os.close here.  NativeRootRoute.teardown is
resolved only if the inner table AND every port handle are resolved
(OPEN_REFUSED_NO_FD or CLOSED).

Residual handoff gap (delimited, NOT closed).  From the kernel's pidfd_open
return, through p18 NativeSyscalls.checked and the adapter return, to the
`handle.fd` store; and from `custody = FD_OWNED` through `return` to the
table's `cap.handle = handle`.  An asynchronous exception (KeyboardInterrupt)
or MemoryError in either window leaves the table at OPEN_FAILED (its phase
text "OPEN_FAILED_NO_HANDLE_RETURNED" may then be wrong) or ACQUIRING, while
the port handle stays OPEN_IN_FLIGHT_OUTCOME_UNKNOWN or FD_OWNED, so the
route reports PORT_CUSTODY_UNRESOLVED.  The fd is never closed off-ledger;
the kernel releases it at process exit.  No arbitrary-failure resilience is
claimed: an uncatchable process termination, the OOM reaper or a
kernel-blocked syscall get no in-process handling.

Preconditions that sampling does NOT prove (trusted-code declarations): sole
reaper (nothing else waits on the child between spawn and V2), no thread or
SIGCHLD-disposition change between samples, pid reuse excluded only by being
the sole reaper.  P18SysPorts declares AcquisitionPolicy(True, True, True);
it is a declaration by the caller, not a measurement.
"""
import errno
import os
import re

PROOF_NATIVE_ROOT = "LINUX_PIDFD_DIRECT_CHILD_P01_ORDER_PLUS_BOOT_ID"
IDENTITY_FORMAT = "(boot_id:str, pid:int, starttime_ticks:int)"
IDENTITY_LABEL = "NATIVE_OBSERVATION_NOT_JOURNAL_IDENTITY"
FDINFO_PID = re.compile(rb"^Pid:\s+([0-9]+)\s*$", re.M)      # = p18 regex
BOOT_ID_TEXT = re.compile(r"^[0-9a-f-]{36}$")
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
FDINFO_BOUND = 8192
BOOT_ID_BOUND = 64

# Port-side custody of one handle, set BEFORE the syscall.  Only H_NO_FD and
# H_CLOSED are resolved.
H_OPEN_IN_FLIGHT = "OPEN_IN_FLIGHT_OUTCOME_UNKNOWN"
H_NO_FD = "OPEN_REFUSED_NO_FD"
H_OWNED = "FD_OWNED"
H_CLOSE_CALLED = "CLOSE_CALLED_OUTCOME_UNKNOWN"
H_CLOSED = "CLOSED"
PORT_RESOLVED = (H_NO_FD, H_CLOSED)


class PidfdRootHandle:
    """Allocated before pidfd_open.  `fd` is a process-local slot, never identity."""
    __slots__ = ("pid", "owner_pid", "fd", "custody", "proof")

    def __init__(self, pid, owner_pid):
        self.pid, self.owner_pid = pid, owner_pid
        self.fd, self.custody, self.proof = None, H_OPEN_IN_FLIGHT, None


class PidfdRootPort:
    """CapabilityTable port over an injected sys_ports object:
      getpid() -> int
      validate_environment() -> None | raise
      child_stat(pid) -> (pid, ppid, starttime_ticks)
      wait_nowait(pid) -> bool                 (WNOWAIT only, never reaps)
      boot_id() -> str
      pidfd_open(pid) -> int
      open_failed_without_fd(error) -> bool
      read_fdinfo(fd) -> bytes
      close_fd(fd) -> None
    There is deliberately no send entry.
    """

    def __init__(self, sys_ports, refused):
        self.sys, self._refused = sys_ports, refused
        self.handles = []                       # port custody ledger (append-only)
        self.counters = {"open": 0, "close": 0, "signal_refused": 0}

    def open(self, pid):
        handle = PidfdRootHandle(pid, self.sys.getpid())
        self.handles.append(handle)             # custody = OPEN_IN_FLIGHT
        self.counters["open"] += 1
        try:
            handle.fd = self.sys.pidfd_open(pid)
        except Exception as error:
            if self.sys.open_failed_without_fd(error):
                handle.custody = H_NO_FD
            raise                               # anything else stays OPEN_IN_FLIGHT
        handle.custody = H_OWNED
        return handle

    def _owner(self, handle):
        if handle.owner_pid != self.sys.getpid():
            raise self._refused(errno.EPERM, "PIDFD_OWNER_PROCESS_CHANGED")

    def signal(self, handle, signum):
        self.counters["signal_refused"] += 1
        raise self._refused(errno.EPERM, "NRP3_NATIVE_SIGNAL_NOT_IMPLEMENTED")

    def close(self, handle):
        """Called at most once per handle, by the table's CLOSING claimant.
        Exception -> table CLOSE_FAILED, never retried; BaseException -> table
        stays CLOSING.  Port custody stays CLOSE_CALLED unless close_fd
        returned normally."""
        self._owner(handle)
        handle.custody = H_CLOSE_CALLED
        self.counters["close"] += 1
        self.sys.close_fd(handle.fd)
        handle.custody = H_CLOSED

    def object_present(self, handle):
        raise self._refused(errno.EPERM, "NRP3_OBJECT_PRESENCE_NOT_PROVIDED")

    def object_matches(self, handle, pid, starttime):
        raise self._refused(errno.EPERM, "NRP3_MEMBER_MATCH_NOT_PROVIDED")

    def custody_report(self):
        return [{"pid": h.pid, "fd_label": h.fd, "fd_number_is_not_identity": True,
                 "custody": h.custody, "resolved": h.custody in PORT_RESOLVED}
                for h in self.handles]


class NativeRootRoute:
    """Composes (never edits, never subclasses) termination.LinuxDevelopmentRoute.

    Guard state lives on the INNER route (root_cap, log, _bind_context,
    table, binding).  RootAuthority is built on the inner route, so root
    signals reach PidfdRootPort.signal and are refused there.
    """
    authority_id = "LINUX_NATIVE_PIDFD_ROOT_ONLY_NRP3"

    def __init__(self, controller, termination, port, run_id, owner, generation):
        self._refused = controller.GroupSignalRefused
        self._termination = termination
        self.port = port
        self.inner = termination.LinuxDevelopmentRoute(controller, port, run_id,
                                                       owner, generation)

    @property
    def table(self):
        return self.inner.table

    @property
    def binding(self):
        return self.inner.binding

    def _translate(self, error):
        code = getattr(error, "code", None)
        code = code if type(code) is str else type(error).__name__
        return self._refused(errno.EPERM, "NATIVE_ROOT_ACQUISITION_REFUSED:" + code)

    def preflight(self, context):
        if context.termination is not self:
            raise self._refused(errno.EPERM, "NATIVE_ROUTE_WRAPPED_OR_FOREIGN_TERMINATION")
        self.inner.preflight(context)
        try:
            self.port.sys.validate_environment()            # P0
        except self._refused:
            raise
        except Exception as error:
            raise self._translate(error) from error

    def acquire_root(self, process, context):
        if context.termination is not self:
            raise self._refused(errno.EPERM, "NATIVE_ROUTE_WRAPPED_OR_FOREIGN_TERMINATION")
        inner = self.inner
        inner._bind_context(context)
        if inner.root_cap is not None:
            raise self._refused(errno.EPERM, "ROOT_ALREADY_ACQUIRED")
        if process.returncode is not None:
            raise self._refused(errno.EPERM, "ROOT_ALREADY_REAPED_AT_ACQUISITION")
        sys_ports, pid = self.port.sys, process.pid
        try:
            me = sys_ports.getpid()                              # A0
            sys_ports.validate_environment()                     # A1
            expected = tuple(sys_ports.child_stat(pid))          # A2
            if expected[0] != pid or expected[1] != me:
                raise self._refused(errno.EPERM, "EXPECTED_CHILD_IDENTITY")
            zombie_before = sys_ports.wait_nowait(pid)           # A3
            before = tuple(sys_ports.child_stat(pid))            # A4
            if before != expected:
                raise self._refused(errno.EPERM, "CHILD_IDENTITY_CHANGED_BEFORE_OPEN")
            boot0 = sys_ports.boot_id()                          # A5
            identity = (boot0, pid, before[2])

            def verify(handle):                                  # post-open, in table
                after = tuple(sys_ports.child_stat(pid))         # V1
                if after != before:
                    raise self._refused(errno.EPERM, "CHILD_IDENTITY_CHANGED_AFTER_OPEN")
                zombie_after = sys_ports.wait_nowait(pid)        # V2
                sys_ports.validate_environment()                 # V3
                values = FDINFO_PID.findall(sys_ports.read_fdinfo(handle.fd))   # V4
                if len(values) != 1 or int(values[0]) != pid:
                    raise self._refused(errno.EPERM, "PIDFD_PID_BINDING")
                if sys_ports.boot_id() != boot0:                 # V5
                    raise self._refused(errno.EPERM, "BOOT_ID_CHANGED")
                handle.proof = {"identity": identity, "zombie_before": zombie_before,
                                "zombie_after": zombie_after, "fdinfo_pid": pid,
                                "label": IDENTITY_LABEL}

            cap = inner.table.acquire(pid, "ROOT", identity, PROOF_NATIVE_ROOT,
                                      verify)                    # A6 open + verify
            inner.root_cap = cap
            inner.log.append({"outcome": "ROOT_ACQUIRED", "pid": pid,
                              "fd_label": cap.fd, "identity": list(identity)})
            return self._termination.RootAuthority(inner, cap)
        except self._refused:
            raise                                    # already an OSError subclass
        except Exception as error:
            raise self._translate(error) from error  # BaseException never caught

    def group_signal(self, pgid, signum, context, owned):
        raise self._refused(errno.EPERM, "NATIVE_GROUP_SIGNAL_NOT_IN_NRP3_SCOPE")

    def teardown(self, context, lock_timeout=None):
        """Inner complete-table teardown, then the port custody overlay."""
        result = dict(self.inner.teardown(context, lock_timeout))
        port_rows = self.port.custody_report()
        unresolved = [row for row in port_rows if not row["resolved"]]
        result["port_custody"] = port_rows
        if unresolved:
            result["resolved"] = False
            result["outcome"] = "PORT_CUSTODY_UNRESOLVED:%s|%s" % (
                ",".join("%s:%s" % (r["pid"], r["custody"]) for r in unresolved),
                result.get("outcome"))
        return result

    def native_identity_report(self):
        cap = self.inner.root_cap
        return {"identity_format": IDENTITY_FORMAT, "label": IDENTITY_LABEL,
                "journal_identity": None,
                "identity": list(cap.identity) if cap is not None else None,
                "cap_state": cap.state if cap is not None else None,
                "proof": getattr(cap.handle, "proof", None) if cap is not None else None,
                "provenance_recorded_in_journal": False}

    def report(self):
        return {"authority_id": self.authority_id, "inner": self.inner.report(),
                "port_counters": dict(self.port.counters),
                "port_custody": self.port.custody_report(),
                "native_identity": self.native_identity_report()}


class P18SysPorts:
    """Production sys_ports adapter over ALREADY-LOADED frozen p18 modules
    (`pidfd_primitives`, `parsers`) supplied by the caller's pinned loader;
    this class imports no p18 module itself.  Construction reads no host
    file and builds no native object: NativeSyscalls (x86_64 + header ABI)
    is constructed lazily, on the first call that needs it.  The policy
    AcquisitionPolicy(True, True, True) is an explicit DECLARATION of sole
    unreaped-child wait ownership by the caller, not a measurement.
    """

    def __init__(self, pidfd_primitives, parsers):
        self._p18, self._parsers = pidfd_primitives, parsers
        self.policy = pidfd_primitives.AcquisitionPolicy(True, True, True)
        self._native = None

    def _native_syscalls(self):
        if self._native is None:
            self._native = self._p18.NativeSyscalls()
        return self._native

    def getpid(self):
        return os.getpid()

    def validate_environment(self):
        native = self._native_syscalls()
        self._p18.validate_acquisition_environment(
            self.policy, native.acquisition_environment(), native.no_cldwait)

    def child_stat(self, pid):
        value = self._p18.direct_child_stat(pid)
        return (value.pid, value.ppid, value.starttime_ticks)

    def wait_nowait(self, pid):
        return self._p18.wait_without_reaping(pid)

    def boot_id(self):
        raw = self._p18.bounded_read(BOOT_ID_PATH, BOOT_ID_BOUND)
        try:
            text = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            raise self._p18.PidfdError("BOOT_ID_NOT_ASCII", "boot_id")
        if not BOOT_ID_TEXT.match(text):
            raise self._p18.PidfdError("BOOT_ID_FORMAT", "boot_id")
        return text

    def pidfd_open(self, pid):
        return self._native_syscalls().open(pid, 0)

    def open_failed_without_fd(self, error):
        return (isinstance(error, self._p18.PidfdError)
                and (error.code == "PIDFD_OPEN_ARGUMENT"
                     or (error.operation == "pidfd_open"
                         and error.code in ("SYSCALL_ERROR", "ENOSYS_UNSUPPORTED"))))

    def read_fdinfo(self, fd):
        return self._p18.bounded_read("/proc/self/fdinfo/%d" % fd, FDINFO_BOUND)

    def close_fd(self, fd):
        os.close(fd)


def build_native_entry(controller, termination, linux_entry, sys_ports_factory,
                       capability_backend, clock, sleep, *, opt_in, run_id,
                       generation, owner, dispatch_latch=None, **unexpected):
    """The ONLY native construction path; no modeled identity parameter.  Any
    extra keyword or a wrong opt-in is refused before any RunContext, route
    or sys_ports object exists."""
    if unexpected:
        raise controller.NativeSamplerCapabilityError(
            "LINUX_NATIVE_UNEXPECTED_ARGUMENT:" + ",".join(sorted(unexpected)))
    if opt_in != linux_entry.OPT_IN:
        raise controller.NativeSamplerCapabilityError("LINUX_NATIVE_NOT_OPTED_IN")

    def termination_factory():                 # a fresh route per RunContext
        port = PidfdRootPort(sys_ports_factory(), controller.GroupSignalRefused)
        return NativeRootRoute(controller, termination, port, run_id, owner, generation)

    return linux_entry.LinuxControllerEntry(
        controller, opt_in=opt_in, capability_backend=capability_backend,
        termination_factory=termination_factory, clock=clock, sleep=sleep,
        run_id=run_id, generation=generation, dispatch_latch=dispatch_latch,
        modeled_identity=None)
