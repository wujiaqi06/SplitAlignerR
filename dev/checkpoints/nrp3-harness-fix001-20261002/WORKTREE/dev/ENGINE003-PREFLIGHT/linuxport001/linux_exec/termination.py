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


LIVE, CLOSE_PENDING, CLOSING = "LIVE", "CLOSE_PENDING", "CLOSING"
CLOSED, CLOSE_FAILED = "CLOSED", "CLOSE_FAILED"
# Acquisition states (DEV007_FIX002 / D3): a pending acquisition is in the
# same ledger as registered capabilities from before port.open() until it is
# LIVE or rolled back.  ACQUIRING: open in flight, no handle yet.  UNVERIFIED:
# handle returned and owned, verification pending, no operation allowed.
# OPEN_FAILED: open raised and returned no handle (terminal, nothing to close).
ACQUIRING, UNVERIFIED, OPEN_FAILED = "ACQUIRING", "UNVERIFIED", "OPEN_FAILED"
IN_FLIGHT_STATES = (ACQUIRING, UNVERIFIED)
RESOLVED_STATES = (CLOSED, OPEN_FAILED)


class Capability:
    """An unforgeable (by value) signal authority over one kernel object.

    States (all transitions under the owning table's lock):
        LIVE -> CLOSING -> CLOSED | CLOSE_FAILED      close, no lease held
        LIVE -> CLOSE_PENDING -> CLOSING -> ...       close while leased; the
                                                      last lease release claims
                                                      the provider close
    Only the caller that moves the state to CLOSING calls the provider close,
    so it happens exactly once.  CLOSE_FAILED is never retried (a retried
    close could hit a reused descriptor number) and stays unresolved.
    """
    __slots__ = ("table", "handle", "kind", "pid", "identity", "proof",
                 "allowed_ops", "state", "leases", "invalidated", "close_error",
                 "binding", "borrowed", "source", "acquisition")

    def __init__(self, table, handle, kind, pid, identity, proof, allowed_ops,
                 borrowed=False, source=None):
        self.table, self.handle, self.kind = table, handle, kind
        self.pid, self.identity, self.proof = pid, identity, proof
        self.allowed_ops = frozenset(allowed_ops)
        self.state, self.leases = LIVE, 0
        self.invalidated, self.close_error = None, None
        self.binding = (table.run_id, table.owner, table.generation)
        self.borrowed, self.source = borrowed, source
        self.acquisition = None     # acquisition evidence; None for views

    @property
    def fd(self):
        return getattr(self.handle, "fd", None)

    @property
    def close_pending(self):
        return self.state == CLOSE_PENDING

    def report(self):
        return {"kind": self.kind, "pid": self.pid, "fd": self.fd,
                "identity": list(self.identity) if self.identity else None,
                "proof": self.proof, "state": self.state, "leases": self.leases,
                "borrowed": self.borrowed, "invalidated": self.invalidated,
                "close_error": self.close_error,
                "acquisition": (dict(self.acquisition)
                                if self.acquisition is not None else None)}


class CapabilityTable:
    """Per-run capability owner: unique owner/closer; refuses foreign handles.

    Validation and lease acquisition are one critical section, so no close,
    invalidation or teardown can fall between "checked" and "leased".  The
    lock is never held across a port call; `schedule_point(name, cap)` is
    the (test-visible) place where another actor may run between the
    unlocked steps.
    """

    def __init__(self, port, refused, run_id, owner, generation):
        self.port, self._refused = port, refused
        self.run_id, self.owner, self.generation = run_id, owner, generation
        self._caps = []
        self._lock = threading.Lock()
        self.invalidated = None
        self.log = []
        self.schedule_point = None

    @property
    def binding(self):
        return (self.run_id, self.owner, self.generation)

    def _yield(self, name, cap):
        if self.schedule_point is not None:
            self.schedule_point(name, cap)

    def refuse(self, code):
        self.log.append({"outcome": code})
        raise self._refused(errno.EPERM, code)

    def acquire(self, pid, kind, identity, proof, verify=None):
        """Ledgered acquisition: the pending entry exists before port.open().

        open -> the returned handle is owned at once (UNVERIFIED, no ops);
        verify(handle) -> SIGNAL is granted only after it passes and only if
        the table is still live.  A teardown that falls anywhere in between
        cannot report ALL_CLOSED: it sees the in-flight entry.  Rollback and
        late-return close use the same exactly-once provider close; the
        verify error stays primary and the close error is kept beside it;
        a failed close is never retried (possibly reused descriptor).
        """
        with self._lock:
            if self.invalidated is not None:
                invalidated = self.invalidated
            else:
                invalidated = None
                cap = Capability(self, None, kind, pid, identity, proof, ())
                cap.state = ACQUIRING
                cap.acquisition = {"phase": "OPEN_PENDING"}
                self._caps.append(cap)
        if invalidated is not None:
            self.refuse("TABLE_INVALIDATED:" + invalidated)
        self._yield("ACQUIRE_BEFORE_OPEN", cap)
        try:
            handle = self.port.open(pid)
        except BaseException as error:
            with self._lock:
                cap.state = OPEN_FAILED
                cap.acquisition.update(
                    phase="OPEN_FAILED_NO_HANDLE_RETURNED",
                    open_error="%s:%s" % (type(error).__name__, error))
            raise
        with self._lock:
            cap.handle = handle
            cap.state = UNVERIFIED
            cap.acquisition["phase"] = "OPENED_UNVERIFIED"
        self._yield("ACQUIRE_OPENED", cap)
        if verify is not None:
            try:
                verify(handle)
            except BaseException as error:
                cap.acquisition["verify_error"] = "%s:%s" % (
                    type(error).__name__, error)
                self._rollback(cap, "VERIFY_REJECTED")
                raise                   # verify error stays the primary one
        self._yield("ACQUIRE_VERIFIED", cap)
        with self._lock:
            invalidated = self.invalidated or cap.invalidated
            if invalidated is None:
                cap.allowed_ops = frozenset((SIGNAL_OP,))
                cap.state = LIVE
                cap.acquisition["phase"] = "REGISTERED_LIVE"
        if invalidated is not None:     # late return after teardown fence
            self._rollback(cap, "LATE_RETURN_AFTER_INVALIDATION")
            self.refuse("TABLE_INVALIDATED:" + invalidated)
        return cap

    def _rollback(self, cap, reason):
        with self._lock:
            claim = cap.state == UNVERIFIED
            if claim:
                cap.state = CLOSING
        cap.acquisition["rollback_reason"] = reason
        outcome = self._provider_close(cap) if claim else "NOT_CLAIMED:" + cap.state
        cap.acquisition["rollback_close"] = outcome
        cap.acquisition["phase"] = "ROLLED_BACK:" + reason
        self.log.append({"outcome": "ACQUISITION_ROLLED_BACK", "pid": cap.pid,
                         "reason": reason, "close": outcome,
                         "close_error": cap.close_error,
                         "verify_error": cap.acquisition.get("verify_error")})
        return outcome

    def _register(self, cap):
        """Borrowed views only (never own a descriptor)."""
        with self._lock:
            invalidated = self.invalidated
            if invalidated is None:
                self._caps.append(cap)
        if invalidated is not None:
            self.refuse("TABLE_INVALIDATED:" + invalidated)
        return cap

    def borrowed_view(self, cap):
        """A read-only view: carries no SIGNAL authority, never upgrades, and
        its release never closes the owner's descriptor."""
        return self._register(Capability(self, cap.handle, cap.kind + "_BORROWED",
                                         cap.pid, cap.identity, cap.proof, (),
                                         borrowed=True, source=cap))

    def _validate_locked(self, cap, op, binding):
        if not any(c is cap for c in self._caps) or cap.table is not self:
            self.refuse("CAPABILITY_FROM_ANOTHER_TABLE")
        if cap.binding != binding or binding != self.binding:
            self.refuse("CAPABILITY_BINDING_MISMATCH")
        if self.invalidated is not None or cap.invalidated is not None:
            self.refuse("CAPABILITY_NOT_LIVE:INVALIDATED")
        if cap.state != LIVE:
            self.refuse("CAPABILITY_NOT_LIVE:%s" % cap.state)
        if op not in cap.allowed_ops:
            self.refuse("OPERATION_NOT_ALLOWED:%s:%s" % (op, cap.kind))

    def check(self, cap, op, binding):
        """Diagnostic only: a passing check authorizes nothing later."""
        if type(cap) is not Capability:
            self.refuse("NOT_A_CAPABILITY:%s" % type(cap).__name__)
        with self._lock:
            self._validate_locked(cap, op, binding)

    @contextlib.contextmanager
    def lease(self, cap, op, binding):
        if type(cap) is not Capability:
            self.refuse("NOT_A_CAPABILITY:%s" % type(cap).__name__)
        self._yield("BEFORE_LEASE", cap)
        with self._lock:                  # validate + acquire: one transition
            self._validate_locked(cap, op, binding)
            cap.leases += 1
        try:
            self._yield("LEASED", cap)
            yield cap
        finally:
            self._release(cap)

    def _release(self, cap):
        with self._lock:
            cap.leases -= 1
            claim = cap.state == CLOSE_PENDING and cap.leases == 0
            if claim:
                cap.state = CLOSING
        if claim:
            self._yield("LAST_LEASE_RELEASED_CLOSE_CLAIMED", cap)
            self._provider_close(cap)

    def signal(self, cap, signum, binding):
        with self.lease(cap, SIGNAL_OP, binding):
            self.port.signal(cap.handle, signum)

    def _provider_close(self, cap):
        """Called exactly once, by whoever moved the state to CLOSING."""
        try:
            if not cap.borrowed:
                self.port.close(cap.handle)
        except Exception as error:
            with self._lock:
                cap.state = CLOSE_FAILED
                cap.close_error = "%s:%s" % (type(error).__name__, error)
            self.log.append({"outcome": "PROVIDER_CLOSE_FAILED", "pid": cap.pid,
                             "fd": cap.fd, "error": cap.close_error})
            return CLOSE_FAILED
        with self._lock:
            cap.state = CLOSED
            views = [c for c in self._caps if c.source is cap and c.state == LIVE]
            for view in views:        # a view aliases a now-closed descriptor
                view.state = CLOSED
        return CLOSED

    def close(self, cap, binding=None):
        """Idempotent; only this table's own capabilities.  Success is
        reported only after the provider close outcome is known."""
        if type(cap) is not Capability:
            self.refuse("NOT_A_CAPABILITY:%s" % type(cap).__name__)
        with self._lock:
            if not any(c is cap for c in self._caps) or cap.table is not self:
                self.refuse("CLOSE_OF_FOREIGN_CAPABILITY")
            if binding is not None and binding != self.binding:
                self.refuse("CLOSE_BINDING_MISMATCH")
            state = cap.state
            if state in IN_FLIGHT_STATES:   # the acquirer owns this close
                return "ACQUISITION_IN_FLIGHT_ACQUIRER_CLOSES"
            if state == OPEN_FAILED:
                return "OPEN_FAILED_NO_HANDLE"
            if state == CLOSED:
                return "ALREADY_CLOSED"
            if state == CLOSE_FAILED:
                return "CLOSE_FAILED_NOT_RETRIED"
            if state == CLOSING:
                return "CLOSE_IN_PROGRESS"
            if cap.leases:
                cap.state = CLOSE_PENDING
                return "DEFERRED_LEASE_HELD"
            cap.state = CLOSING
        return self._provider_close(cap)

    def invalidate(self, reason):
        """Irreversible: every capability becomes unusable, never re-enabled."""
        with self._lock:
            if self.invalidated is None:
                self.invalidated = reason
            caps = list(self._caps)
            for cap in caps:
                if cap.invalidated is None:
                    cap.invalidated = reason
        return [self.close(cap) for cap in caps]

    def teardown(self, binding, reason="TEARDOWN", lock_timeout=None):
        """Complete-table teardown by the unique owner.

        Resolved only when every capability (root, members, borrowed views)
        is CLOSED; a lease-held, in-progress or failed close stays recorded
        as unresolved and the capability stays in the table.
        """
        if binding != self.binding:
            self.refuse("TEARDOWN_BINDING_MISMATCH")
        if not self._lock.acquire(timeout=-1 if lock_timeout is None
                                  else max(0.0, lock_timeout)):
            return {"resolved": False,
                    "outcome": "TABLE_LOCK_NOT_ACQUIRED_WITHIN_DEADLINE"}
        try:
            if self.invalidated is None:
                self.invalidated = reason
            caps = list(self._caps)
            for cap in caps:
                if cap.invalidated is None:
                    cap.invalidated = reason
        finally:
            self._lock.release()
        rows = []
        for cap in caps:
            outcome = self.close(cap)
            rows.append(dict(cap.report(), close_outcome=outcome))
        unresolved = [row for row in rows if row["state"] not in RESOLVED_STATES]
        return {
            "resolved": not unresolved,
            "outcome": "ALL_CLOSED" if not unresolved else ",".join(
                "%s:%s:%s" % (row["kind"], row["pid"], row["state"])
                for row in unresolved),
            "root": [row for row in rows if row["kind"] == "ROOT"],
            "members": [row for row in rows if row["kind"] == "MEMBER"],
            "borrowed": [row for row in rows if row["borrowed"]],
            "acquisitions_in_flight": [row for row in rows
                                       if row["state"] in IN_FLIGHT_STATES],
            "unresolved": unresolved,
        }

    def live_caps(self, kind=None):
        with self._lock:
            return [c for c in self._caps if c.state == LIVE and not c.borrowed
                    and (kind is None or c.kind == kind)]

    def held_caps(self):
        """Every non-borrowed capability whose descriptor is not known closed."""
        with self._lock:
            return [c for c in self._caps
                    if c.state not in RESOLVED_STATES and not c.borrowed]

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
        return self.route.table.close(self.cap, self.route.binding)


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
    def preflight(self, context):
        """Admission before any spawn: a fresh route for this one context."""
        if self.context is not None and self.context is not context:
            raise self._refused(errno.EPERM, "ROUTE_BOUND_TO_ANOTHER_RUN_CONTEXT")
        if (context.run_id, context.generation) != (self.table.run_id,
                                                    self.table.generation):
            raise self._refused(errno.EPERM, "ROUTE_CONTEXT_RUN_MISMATCH")
        if self.table.invalidated is not None:
            raise self._refused(errno.EPERM,
                                "ROUTE_TABLE_INVALIDATED:" + self.table.invalidated)
        if self.root_cap is not None or self.table.report()["capabilities"]:
            raise self._refused(errno.EPERM, "ROUTE_ALREADY_HOLDS_CAPABILITIES")
        self._bind_context(context)

    def teardown(self, context, lock_timeout=None):
        """Unique-owner teardown of the complete capability table."""
        self._bind_context(context)
        return self.table.teardown(self.binding, "CONTEXT_TEARDOWN", lock_timeout)

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
