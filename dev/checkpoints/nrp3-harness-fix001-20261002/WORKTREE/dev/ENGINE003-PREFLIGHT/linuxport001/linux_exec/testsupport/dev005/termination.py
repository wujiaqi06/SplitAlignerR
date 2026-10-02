"""Linux development termination route for the shared Stage-B controller.

DEVELOPMENT ONLY. Registered with
`stage_b_controller.register_linux_development_route(route)`; the controller
then sends every POSIX group signal on Linux through `route.group_signal`
(and never through os.killpg). Without registration Linux has no group
signal and no survivor authority at all.

    route.group_signal(pgid, signum, backend)
      1. signum must be SIGTERM or SIGKILL;
      2. backend must be a LinuxProcSamplerBackend whose bound authority is
         exactly `pgid` (dedicated group, root identity recorded);
      3. a fresh stable census of `pgid` is taken:
           empty                    -> ProcessLookupError (nothing to signal;
                                       the controller treats this as absent);
           non-empty after the group
           was observed retired     -> refused (PGID reuse);
           pid == pgid present with
           another identity         -> refused (leader PID/PGID reuse);
           a member that predates
           the authority root       -> refused;
      4. only then `port.kill(pgid, signum)`.
    Every refusal is GroupSignalRefused (an OSError that is not
    ProcessLookupError), so the controller's handlers never count it as sent.

`NativeTerminationUnavailable` is the only native port here: it refuses
every call. Linux native termination stays unavailable until separately
authorized. Synthetic ports (synthetic.FakeGroupSignals) exercise the
timeout/grace/identity/reuse/descendant logic only; they validate no Linux
kernel signal behaviour. Steps 3 and 4 are not atomic (see RESULT.md).
"""
import errno
import signal

from linux_proc_backend import LinuxProcSamplerBackend

ALLOWED_SIGNALS = (signal.SIGTERM, signal.SIGKILL)


class NativeTerminationUnavailable:
    description = "LINUX_NATIVE_TERMINATION_NOT_AUTHORIZED"

    def __init__(self, refused_error):
        self._refused = refused_error
        self.calls = []

    def kill(self, pgid, signum):
        self.calls.append((pgid, int(signum)))
        raise self._refused(errno.EPERM, self.description)


class LinuxDevelopmentRoute:
    def __init__(self, controller, port):
        self._refused = controller.GroupSignalRefused
        self.port = port
        self.log = []

    def _refuse(self, pgid, signum, code):
        self.log.append({"pgid": pgid, "signal": int(signum), "outcome": code})
        raise self._refused(errno.EPERM, code)

    def group_signal(self, pgid, signum, backend):
        if signum not in ALLOWED_SIGNALS:
            self._refuse(pgid, signum, "SIGNAL_NOT_ALLOWED")
        if not isinstance(backend, LinuxProcSamplerBackend):
            self._refuse(pgid, signum, "BACKEND_NOT_LINUX_DEVELOPMENT")
        with backend._authority_lock:
            bound, root = backend._authority_pgid, backend._authority_root_identity
        if type(pgid) is not int or pgid <= 0 or bound != pgid or root is None:
            self._refuse(pgid, signum, "GROUP_AUTHORITY_NOT_BOUND_TO_TARGET")
        try:
            census = backend.process_group_pids(pgid)
            live = {}
            for pid in census:
                try:
                    _ppid, observed_pgid, identity = backend.identity_and_group(pid)
                except backend._errors.ProcessAbsent:
                    continue            # zombie or gone: not signalable
                if observed_pgid != pgid:
                    continue
                live[pid] = identity
        except self._refused:
            raise
        except Exception as exc:
            self._refuse(pgid, signum, "GROUP_CENSUS_FAILED:%s" % type(exc).__name__)
        if not live:
            self.log.append({"pgid": pgid, "signal": int(signum), "outcome": "GROUP_ABSENT"})
            raise ProcessLookupError(errno.ESRCH, "GROUP_ABSENT")
        if backend._group_retired:
            self._refuse(pgid, signum, "PGID_REUSE_AFTER_RETIREMENT")
        if pgid in live and live[pgid] != root:
            self._refuse(pgid, signum, "GROUP_LEADER_IDENTITY_CHANGED")
        if any(identity[1:] < root[1:] for identity in live.values()):
            self._refuse(pgid, signum, "GROUP_MEMBER_PREDATES_AUTHORITY_ROOT")
        self.port.kill(pgid, signum)
        self.log.append({"pgid": pgid, "signal": int(signum), "outcome": "SENT",
                         "members": sorted(live)})
