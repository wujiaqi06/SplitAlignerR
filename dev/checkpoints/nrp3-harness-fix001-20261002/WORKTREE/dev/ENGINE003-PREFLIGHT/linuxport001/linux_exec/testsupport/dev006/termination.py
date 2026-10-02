"""Linux development termination provider for the shared Stage-B controller.

DEVELOPMENT ONLY / SIMULATION ONLY. A `LinuxDevelopmentRoute` is the
`termination` of exactly one `stage_b_controller.RunContext`; there is no
module-global registration. It never signals a numeric PID or PGID:

    capability    every effect goes through a Capability that names the
                  kernel object observed at acquisition (the simulated
                  analogue of a pidfd), bound to run/owner/generation and an
                  allowed-operation set. Bare integers, borrowed read-only
                  views, closed/invalidated capabilities, capabilities of
                  another run/table, and reused fd numbers are refused.
    root          acquired right after spawn from the unreaped direct child
                  (Popen is the unique reaper), independent of any sampler.
    members       acquired only for a pid that the bound backend's stable
                  census + F3 classification shows live in the bound group,
                  whose identity matches the controller's recorded owned
                  identity (or, while the root object still exists, is not
                  older than the root); the capability is verified by a
                  post-open stat re-read. That proof is a bounded development
                  proof, NOT historical ownership and NOT complete descendant
                  discovery.
    retirement    an empty census, whoever discovers it first (this route,
                  the sampler, cleanup), is the backend's one irreversible
                  transition; after it nothing is ever acquired or signalled.
    leases        each signal holds a lease; close during a lease is deferred
                  and completes when the lease ends; close is irreversible.
    errors        EPERM is GroupSignalRefused (never "absent"); ESRCH of an
                  object means that object is gone; no numeric reopen,
                  group, root or killpg fallback exists.

`NativeTerminationUnavailable` is the only native port: it refuses open and
signal. Linux native termination stays HOLD until separately authorized;
`SimulatedObjectSignalPort` (synthetic.py) is the only port that has effects,
and only on a FakeKernel.
"""
import contextlib
import errno
import signal
import threading

from linux_proc_backend import LinuxProcSamplerBackend

ALLOWED_SIGNALS = (signal.SIGTERM, signal.SIGKILL)
SIGNAL_OP = "SIGNAL"
PROOF_ROOT = "DIRECT_CHILD_UNREAPED_AT_SPAWN_POPEN_UNIQUE_REAPER"
PROOF_MEMBER = "BOUND_GROUP_STABLE_CENSUS_OWNED_IDENTITY_POST_OPEN_STAT_MATCH"


class NativeTerminationUnavailable:
    """Default-deny native port: no open, no signal, ever."""
    description = "LINUX_NATIVE_TERMINATION_NOT_AUTHORIZED"

    def __init__(self, refused_error):
        self._refused = refused_error
        self.calls = []

    def open(self, pid):
        self.calls.append(("open", pid))
        raise self._refused(errno.EPERM, self.description)

    def signal(self, handle, signum):
        self.calls.append(("signal", getattr(handle, "pid", None), int(signum)))
        raise self._refused(errno.EPERM, self.description)

    def close(self, handle):
        self.calls.append(("close", getattr(handle, "pid", None)))

    def object_present(self, handle):
        return False

    def object_matches(self, handle, pid, starttime):
        return False

    def kill(self, pgid, signum):             # historical numeric entry
        self.calls.append((pgid, int(signum)))
        raise self._refused(errno.EPERM, self.description)


class Capability:
    """An unforgeable (by value) signal authority over one kernel object."""
    __slots__ = ("table", "handle", "kind", "pid", "identity", "proof",
                 "allowed_ops", "state", "leases", "close_pending",
                 "binding", "borrowed")

    def __init__(self, table, handle, kind, pid, identity, proof, allowed_ops,
                 borrowed=False):
        self.table, self.handle, self.kind = table, handle, kind
        self.pid, self.identity, self.proof = pid, identity, proof
        self.allowed_ops = frozenset(allowed_ops)
        self.state, self.leases, self.close_pending = "LIVE", 0, False
        self.binding = (table.run_id, table.owner, table.generation)
        self.borrowed = borrowed

    @property
    def fd(self):
        return getattr(self.handle, "fd", None)

    def report(self):
        return {"kind": self.kind, "pid": self.pid, "fd": self.fd,
                "identity": list(self.identity) if self.identity else None,
                "proof": self.proof, "state": self.state, "leases": self.leases,
                "borrowed": self.borrowed}


class CapabilityTable:
    """Per-run capability owner: unique owner/closer; refuses foreign handles."""

    def __init__(self, port, refused, run_id, owner, generation):
        self.port, self._refused = port, refused
        self.run_id, self.owner, self.generation = run_id, owner, generation
        self._caps = []
        self._lock = threading.Lock()
        self.invalidated = None
        self.log = []

    def refuse(self, code):
        self.log.append({"outcome": code})
        raise self._refused(errno.EPERM, code)

    def _register(self, cap):
        with self._lock:
            if self.invalidated is not None:
                self.port.close(cap.handle)
                self.refuse("TABLE_INVALIDATED:" + self.invalidated)
            self._caps.append(cap)
        return cap

    def acquire(self, pid, kind, identity, proof, verify=None):
        """port.open(pid) binds the object; `verify(handle)` must then pass."""
        if self.invalidated is not None:
            self.refuse("TABLE_INVALIDATED:" + self.invalidated)
        handle = self.port.open(pid)
        if verify is not None:
            try:
                verify(handle)
            except BaseException:
                self.port.close(handle)
                raise
        return self._register(Capability(self, handle, kind, pid, identity, proof,
                                         (SIGNAL_OP,)))

    def borrowed_view(self, cap):
        """A read-only view: carries no SIGNAL authority and never upgrades."""
        return self._register(Capability(self, cap.handle, cap.kind + "_BORROWED",
                                         cap.pid, cap.identity, cap.proof, (),
                                         borrowed=True))

    def check(self, cap, op, binding):
        if type(cap) is not Capability:
            self.refuse("NOT_A_CAPABILITY:%s" % type(cap).__name__)
        with self._lock:
            owned = any(c is cap for c in self._caps)
        if cap.table is not self or not owned:
            self.refuse("CAPABILITY_FROM_ANOTHER_TABLE")
        if cap.binding != binding or binding != (self.run_id, self.owner,
                                                  self.generation):
            self.refuse("CAPABILITY_BINDING_MISMATCH")
        if cap.state != "LIVE" or cap.close_pending:
            self.refuse("CAPABILITY_NOT_LIVE:%s" % cap.state)
        if op not in cap.allowed_ops:
            self.refuse("OPERATION_NOT_ALLOWED:%s:%s" % (op, cap.kind))

    @contextlib.contextmanager
    def lease(self, cap, op, binding):
        self.check(cap, op, binding)
        with self._lock:
            cap.leases += 1
        try:
            yield cap
        finally:
            with self._lock:
                cap.leases -= 1
                finish = cap.close_pending and cap.leases == 0
            if finish:
                self._finish_close(cap)

    def signal(self, cap, signum, binding):
        with self.lease(cap, SIGNAL_OP, binding):
            self.port.signal(cap.handle, signum)

    def _finish_close(self, cap):
        if cap.state == "CLOSED":
            return
        cap.state = "CLOSED"
        if not cap.borrowed:
            self.port.close(cap.handle)

    def close(self, cap):
        """Irreversible; deferred (not interleaved) while a lease is held."""
        with self._lock:
            if cap.state == "CLOSED":
                return "ALREADY_CLOSED"
            if cap.leases:
                cap.close_pending = True
                return "DEFERRED_LEASE_HELD"
            cap.close_pending = True
        self._finish_close(cap)
        return "CLOSED"

    def invalidate(self, reason):
        """Irreversible: every capability becomes unusable, never re-enabled."""
        with self._lock:
            if self.invalidated is None:
                self.invalidated = reason
            caps = list(self._caps)
        for cap in caps:
            if cap.state == "LIVE":
                cap.state = "INVALIDATED"
        return [self.close(cap) for cap in caps]

    def live_caps(self, kind=None):
        with self._lock:
            return [c for c in self._caps if c.state == "LIVE" and not c.borrowed
                    and (kind is None or c.kind == kind)]

    def report(self):
        with self._lock:
            return {"run_id": self.run_id, "owner": self.owner,
                    "generation": self.generation, "invalidated": self.invalidated,
                    "capabilities": [c.report() for c in self._caps],
                    "log": list(self.log)}


class RootAuthority:
    """The controller-facing root cleanup authority (RunContext.root_authority)."""
    covers_process_group = False

    def __init__(self, route, cap):
        self.route, self.cap = route, cap

    def signal(self, signum):
        self.route.signal_root(self.cap, signum)

    def close(self):
        return self.route.table.close(self.cap)


class LinuxDevelopmentRoute:
    """termination provider for one RunContext (never shared across runs)."""
    authority_id = "LINUX_DEVELOPMENT_SIMULATED_CAPABILITIES"

    def __init__(self, controller, port, run_id="DEV-RUN", owner="DEV-OWNER",
                 generation=1):
        self._refused = controller.GroupSignalRefused
        self.port = port
        self.table = CapabilityTable(port, self._refused, run_id, owner, generation)
        self.context = None
        self.root_cap = None
        self.log = []

    # -- binding -------------------------------------------------------------
    @property
    def binding(self):
        return (self.table.run_id, self.table.owner, self.table.generation)

    def _refuse(self, pgid, signum, code):
        self.log.append({"pgid": pgid, "signal": int(signum), "outcome": code})
        raise self._refused(errno.EPERM, code)

    def _bind_context(self, context):
        if self.context is None:
            if (context.run_id, context.generation) != (self.table.run_id,
                                                        self.table.generation):
                raise self._refused(errno.EPERM, "ROUTE_CONTEXT_RUN_MISMATCH")
            self.context = context
        elif self.context is not context:
            raise self._refused(errno.EPERM, "ROUTE_BOUND_TO_ANOTHER_RUN_CONTEXT")

    # -- controller protocol ---------------------------------------------------
    def acquire_root(self, process, context):
        self._bind_context(context)
        if self.root_cap is not None:
            raise self._refused(errno.EPERM, "ROOT_ALREADY_ACQUIRED")
        if process.returncode is not None:
            raise self._refused(errno.EPERM, "ROOT_ALREADY_REAPED_AT_ACQUISITION")
        self.root_cap = self.table.acquire(process.pid, "ROOT", None, PROOF_ROOT)
        self.log.append({"outcome": "ROOT_ACQUIRED", "pid": process.pid,
                         "fd": self.root_cap.fd})
        return RootAuthority(self, self.root_cap)

    def signal_root(self, cap, signum):
        if signum not in ALLOWED_SIGNALS:
            self._refuse(cap.pid, signum, "SIGNAL_NOT_ALLOWED")
        self._deliver(cap, signum)

    def _deliver(self, cap, signum):
        try:
            self.table.signal(cap, signum, self.binding)
        except ProcessLookupError:
            self.log.append({"pid": cap.pid, "signal": int(signum),
                             "outcome": "OBJECT_GONE_ESRCH"})
            raise
        except PermissionError as exc:
            self.log.append({"pid": cap.pid, "signal": int(signum),
                             "outcome": "EPERM"})
            raise self._refused(errno.EPERM, "SIGNAL_EPERM:pid=%d" % cap.pid) from exc
        self.log.append({"pid": cap.pid, "signal": int(signum), "outcome": "SENT"})

    def group_signal(self, pgid, signum, context, owned):
        """Signal every proven-owned live member of the bound group via its
        own capability. Numeric pgid is only a key into bound authority."""
        self._bind_context(context)
        backend = context.native_backend
        if signum not in ALLOWED_SIGNALS:
            self._refuse(pgid, signum, "SIGNAL_NOT_ALLOWED")
        if not isinstance(backend, LinuxProcSamplerBackend):
            self._refuse(pgid, signum, "BACKEND_NOT_LINUX_DEVELOPMENT")
        with backend._authority_lock:
            bound, root = backend._authority_pgid, backend._authority_root_identity
            retired = backend._group_retired
        if type(pgid) is not int or pgid <= 0 or bound != pgid or root is None:
            self._refuse(pgid, signum, "GROUP_AUTHORITY_NOT_BOUND_TO_TARGET")
        known = _parse_owned(owned)
        try:
            live, _absent = backend.classify_group_members(pgid, known, "SIGNAL_ROUTE")
        except backend._errors.CapabilityError as exc:
            code = str(exc).split(":")[0]
            if code == "PGID_REUSE_OR_AMBIGUITY" or retired:
                self._refuse(pgid, signum, "PGID_REUSE_AFTER_RETIREMENT")
            self._refuse(pgid, signum, "GROUP_CENSUS_REFUSED:%s" % code)
        except Exception as exc:
            self._refuse(pgid, signum, "GROUP_CENSUS_FAILED:%s" % type(exc).__name__)
        if not live:
            self.log.append({"pgid": pgid, "signal": int(signum),
                             "outcome": "GROUP_ABSENT",
                             "retired": backend._group_retired})
            raise ProcessLookupError(errno.ESRCH, "GROUP_ABSENT")
        # Retirement/absence is observed above at every entry; any effect
        # additionally needs the run's root capability.
        if self.root_cap is None:
            self._refuse(pgid, signum, "ROOT_CAPABILITY_ABSENT")
        root_object_present = self.port.object_present(self.root_cap.handle)
        if pgid in live and live[pgid] != root:
            self._refuse(pgid, signum, "GROUP_LEADER_IDENTITY_CHANGED")
        caps = []
        for pid, identity in sorted(live.items()):
            caps.append(self._member_cap(pgid, signum, pid, identity, root, known,
                                         root_object_present, backend))
        sent, gone, denied = [], [], []
        for cap in caps:
            try:
                self._deliver(cap, signum)
                sent.append(cap.pid)
            except ProcessLookupError:
                gone.append(cap.pid)
            except self._refused:
                denied.append(cap.pid)
        self.log.append({"pgid": pgid, "signal": int(signum), "outcome": "DELIVERED",
                         "members": sent, "gone": gone, "denied": denied})
        if denied:
            raise self._refused(errno.EPERM, "MEMBER_SIGNAL_EPERM:pids=%r" % denied)
        if not sent:
            raise ProcessLookupError(errno.ESRCH, "ALL_TARGET_OBJECTS_GONE")

    def _member_cap(self, pgid, signum, pid, identity, root, known,
                    root_object_present, backend):
        if pid == pgid and self.root_cap.identity in (None, identity):
            return self.root_cap
        for cap in self.table.live_caps("MEMBER"):
            if cap.pid == pid:
                if cap.identity != identity:
                    self._refuse(pgid, signum, "MEMBER_CAPABILITY_IDENTITY_STALE")
                return cap
        if pid in known:
            if known[pid] != identity:
                self._refuse(pgid, signum, "MEMBER_IDENTITY_NOT_OWNED")
        elif not root_object_present:
            # Leader gone and never recorded: numeric group membership alone
            # does not prove this process belongs to the old job.
            self._refuse(pgid, signum, "UNPROVEN_MEMBER_AFTER_ROOT_OBJECT_GONE")
        elif identity[1:] < root[1:]:
            self._refuse(pgid, signum, "GROUP_MEMBER_PREDATES_AUTHORITY_ROOT")

        def verify(handle):
            record = backend.observe(pid)
            if (record.identity != identity or record.pgid != pgid or record.absent
                    or not self.port.object_matches(handle, pid, identity[1])):
                self._refuse(pgid, signum, "POST_OPEN_IDENTITY_MISMATCH")
        return self.table.acquire(pid, "MEMBER", identity, PROOF_MEMBER, verify)

    def report(self):
        return {"authority_id": self.authority_id, "log": list(self.log),
                "table": self.table.report()}


def _parse_owned(owned):
    known = {}
    for pid, text in dict(owned or {}).items():
        try:
            values = tuple(int(v) for v in str(text).split(":"))
        except ValueError:
            continue
        if len(values) == 3 and values[0] == pid:
            known[pid] = values
    return known
