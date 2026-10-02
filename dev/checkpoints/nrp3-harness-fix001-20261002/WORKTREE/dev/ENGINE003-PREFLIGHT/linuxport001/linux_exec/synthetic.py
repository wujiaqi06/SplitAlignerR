"""Synthetic Linux world for repeatable lifecycle/backend tests. No host effects.

FakeKernel holds fake processes; FakeProcSource renders them as strict
/proc/<pid>/stat and smaps_rollup bytes; FakeOps simulates the owned child
(fork, pipes, stop byte, zombie, reap) on a virtual clock; SyntheticCustody
is a test double of the custody port that hands out a fake pidfd number.
SyntheticCustody is NOT the p18 controller and never passes through its type
checks; claims from synthetic runs are about lifecycle/backend logic only.

Fault hooks let a test change the world at exact points (PID reuse, group
escape, read errors, a child that ignores stop, ...).
"""
import errno
import types

from proc_source import ProcAbsent, ProcReadError

SELF_PID = 4000
INIT_STARTTIME = 1000


class FakeProcess:
    def __init__(self, pid, ppid, pgid, session, starttime, rss_kb, state="S",
                 comm=None, flags=0):
        self.pid, self.ppid, self.pgid, self.session = pid, ppid, pgid, session
        self.starttime, self.rss_kb, self.state = starttime, rss_kb, state
        self.comm = comm if comm is not None else "fake %d" % pid
        self.flags = flags
        self.exit_code = None


class FakeKernel:
    def __init__(self):
        self.procs = {}
        self.clock = 0.0
        self.next_pid = 5000
        self.next_start = INIT_STARTTIME + 100
        self.read_errors = {}          # (pid, name) -> errno, persistent
        self.stat_override = {}        # pid -> raw bytes
        self.on_read = []              # callables(kernel, pid, name)
        self.mountinfo = (b"22 1 0:5 / /proc rw,nosuid,nodev,noexec,relatime "
                          b"shared:15 - proc proc rw\n")
        self.add(FakeProcess(1, 0, 1, 1, 1, 9000))
        self.add(FakeProcess(2, 0, 0, 0, 1, 0, comm="kthreadd", flags=0x00208040))
        # Linux 5.4 workqueue worker: 25-byte comm, pgrp 0, PF_KTHREAD.
        self.add(FakeProcess(8, 2, 0, 0, 2, 0, state="I",
                             comm="kworker/u128:0-efi_rts_wq", flags=0x04208060))
        self.add(FakeProcess(SELF_PID, 1, SELF_PID, SELF_PID, INIT_STARTTIME, 20000))
        self.add(FakeProcess(4100, 1, 4100, 4100, INIT_STARTTIME + 5, 3000))

    def add(self, proc):
        self.procs[proc.pid] = proc
        return proc

    def spawn(self, ppid, pgid=None, session=None, rss_kb=12000):
        pid = self.next_pid
        self.next_pid += 1
        start = self.next_start
        self.next_start += 3
        return self.add(FakeProcess(pid, ppid, pgid or pid, session or pid, start, rss_kb))

    def exit(self, pid, code=0):
        proc = self.procs[pid]
        proc.state, proc.exit_code, proc.rss_kb = "Z", code, 0

    def reuse(self, pid, starttime_delta=50, pgid=None):
        """Replace pid with an unrelated process of a later start time."""
        old = self.procs[pid]
        self.procs[pid] = FakeProcess(pid, 1, pgid or old.pgid, old.session,
                                      old.starttime + starttime_delta, 7777)

    # rendering ---------------------------------------------------------
    @staticmethod
    def stat_bytes(proc):
        values = [0] * 49                      # fields 4..52
        def put(field, value):
            values[field - 4] = value
        put(4, proc.ppid); put(5, proc.pgid); put(6, proc.session)
        put(8, -1); put(9, proc.flags); put(18, 20); put(20, 1)
        put(22, proc.starttime)
        return ("%d (%s) %s %s\n" % (proc.pid, proc.comm, proc.state,
                " ".join(str(v) for v in values))).encode()

    @staticmethod
    def rollup_bytes(proc):
        if proc.state == "Z":
            return b""
        return (b"00400000-7ffc00000000 ---p 00000000 00:00 0"
                b"                          [rollup]\n"
                b"Rss:            %d kB\nPss:            %d kB\n"
                % (proc.rss_kb, proc.rss_kb // 2))


class FakeProcSource:
    description = "SYNTHETIC_FAKE_KERNEL"

    def __init__(self, kernel):
        self.k = kernel
        self.reads = 0

    def list_pids(self):
        return tuple(sorted(self.k.procs))

    def read(self, pid, name):
        self.reads += 1
        for hook in list(self.k.on_read):
            hook(self.k, pid, name)
        if (pid, name) in self.k.read_errors:
            raise ProcReadError(pid, name, self.k.read_errors[(pid, name)])
        proc = self.k.procs.get(pid)
        if proc is None:
            raise ProcAbsent(pid, name)
        if name == "stat":
            return self.k.stat_override.get(pid, self.k.stat_bytes(proc))
        if name == "smaps_rollup":
            return self.k.rollup_bytes(proc)
        raise ProcReadError(pid, name, None, "PROC_READ_ARGUMENT")

    def read_self(self, name):
        if name == "mountinfo":
            return self.k.mountinfo
        raise ProcReadError("self", name, None, "PROC_READ_ARGUMENT")


class FakeOps:
    """Child-lifecycle effects on the fake kernel (virtual clock)."""

    def __init__(self, kernel, child_behaviour="normal", fail=None):
        self.k = kernel
        self.behaviour = child_behaviour   # normal | never_ready | ignore_stop | never_exit
        self.fail = dict(fail or {})       # op name -> exception (or callable(args))
        self.calls = []
        self.open_fds = {}
        self.next_fd = 10
        self.child = None
        self.pipes = {}                    # fd -> ("ctl"|"rdy", end)
        self.pidfds = {}                   # fd -> pid (set by SyntheticCustody)
        self.ready_buffer = b""
        self.ctl_closed = False

    def _maybe_fail(self, name, *args):
        exc = self.fail.get(name)
        if exc is not None:
            if callable(exc) and not isinstance(exc, BaseException):
                exc = exc(*args)
                if exc is None:
                    return
            raise exc

    def _new_fd(self, meaning):
        fd = self.next_fd
        self.next_fd += 1
        self.open_fds[fd] = meaning
        return fd

    def pipe(self):
        self.calls.append(("pipe",))
        self._maybe_fail("pipe")
        kind = "ctl" if not any(v[0] == "ctl" for v in self.open_fds.values()) else "rdy"
        return self._new_fd((kind, "r")), self._new_fd((kind, "w"))

    def fork(self):
        self.calls.append(("fork",))
        self._maybe_fail("fork")
        self.child = self.k.spawn(SELF_PID)
        if self.behaviour != "never_ready":
            self.ready_buffer = b"R"
        return self.child.pid

    def close(self, fd):
        self.calls.append(("close", fd))
        self._maybe_fail("close", fd)
        meaning = self.open_fds.pop(fd, None)
        if meaning is None:
            raise OSError(errno.EBADF, "fake EBADF")
        if meaning == ("ctl", "w"):
            self.ctl_closed = True
            if self.child and self.behaviour != "never_exit" and self.child.state != "Z":
                self.k.exit(self.child.pid)

    def write(self, fd, data):
        self.calls.append(("write", fd, data))
        self._maybe_fail("write", fd, data)
        if self.open_fds.get(fd) != ("ctl", "w"):
            raise OSError(errno.EBADF, "fake EBADF")
        if self.child.state == "Z":
            raise BrokenPipeError(errno.EPIPE, "fake EPIPE")
        if data == b"S" and self.behaviour == "normal":
            self.k.exit(self.child.pid)
        return len(data)

    def read(self, fd, n):
        self.calls.append(("read", fd))
        data, self.ready_buffer = self.ready_buffer[:n], self.ready_buffer[n:]
        return data

    def wait_readable(self, fd, timeout_s):
        self.calls.append(("wait_readable", fd, timeout_s))
        self._maybe_fail("wait_readable", fd)
        if fd in self.pidfds:
            ready = self.k.procs.get(self.pidfds[fd]) is None or \
                self.k.procs[self.pidfds[fd]].state == "Z"
        else:
            ready = bool(self.ready_buffer)
        if not ready:
            self.k.clock += timeout_s
        return ready

    def waitpid(self, pid, options):
        self.calls.append(("waitpid", pid))
        self._maybe_fail("waitpid", pid)
        proc = self.k.procs.get(pid)
        if proc is None or proc.ppid != SELF_PID:
            raise ChildProcessError(errno.ECHILD, "fake ECHILD")
        if proc.state != "Z":
            return 0, 0
        del self.k.procs[pid]
        return pid, (proc.exit_code & 0xff) << 8

    def getpid(self):
        return SELF_PID

    def monotonic(self):
        return self.k.clock

    def sleep(self, seconds):
        self.k.clock += seconds

    def uname(self):
        return types.SimpleNamespace(sysname="Linux", machine="x86_64",
                                     release="5.4.0-synthetic")

    def thread_count(self):
        return 1

    def child_main(self, *args):
        raise AssertionError("fake fork never returns 0")


class SyntheticCustody:
    """Custody-port test double: fake pidfd, recorded calls, no p18 objects."""

    def __init__(self, ops, fail=None, confirm=True):
        self.ops = ops
        self.fail = dict(fail or {})
        self.confirm = confirm
        self.calls = []
        self.view = None
        self.close_attempts = 0
        self.installed = False
        self.windows = 0
        self.in_window = False

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def preflight(self):
        return [{"name": "custody_synthetic_preflight", "ok": True, "observed": None}]

    def acquire(self, pid):
        self.calls.append("acquire")
        self.installed = True
        self._maybe_fail("acquire")
        proc = self.ops.k.procs[pid]
        fd = self.ops._new_fd(("pidfd", pid))
        self.ops.pidfds[fd] = pid
        self.view = {"pid": pid, "borrowed_fd": fd, "starttime_ticks": proc.starttime}
        return dict(self.view)

    def observe_window(self):
        custody = self

        class Window:
            def __enter__(self):
                assert custody.installed and not custody.in_window
                custody.in_window = True
                custody.windows += 1

            def __exit__(self, *exc):
                custody.in_window = False
        return Window()

    def close_pending(self):
        return self.view is not None and self.close_attempts == 0

    def close(self):
        self.calls.append("close")
        self.close_attempts += 1
        self._maybe_fail("close")
        fd = self.view["borrowed_fd"]
        self.ops.open_fds.pop(fd, None)
        self.ops.pidfds.pop(fd, None)
        return {"confirmed": self.confirm, "snapshot": {"synthetic": True}}

    def finish(self):
        self.calls.append("finish")
        self._maybe_fail("finish")
        self.installed = False

    def finished(self):
        return not self.installed

    def report(self):
        return {"synthetic": True, "calls": list(self.calls),
                "close_attempts": self.close_attempts, "observe_windows": self.windows}

    def evaluate(self, report, pid):
        return [{"name": "synthetic_custody_single_close",
                 "ok": report["close_attempts"] == 1 and report["calls"].count("close") == 1,
                 "observed": report}]


# ---------------------------------------------------------------------------
# Controller timeout-path doubles (no host process, no signal)
# ---------------------------------------------------------------------------

class UnboundedWaitReached(AssertionError):
    """A controller path called wait/communicate/join without a timeout."""


def advance(kernel, seconds):
    """Advance virtual time; `kernel.on_advance` hooks model ongoing effects."""
    kernel.clock += seconds
    for hook in list(getattr(kernel, "on_advance", ())):
        hook(kernel, seconds)


class FakePopen:
    """subprocess.Popen double over a FakeKernel root on virtual time.

    Root reap (wait/poll) and stdout EOF are independent: EOF needs every
    pid in `pipe_holders` to be gone or a zombie. `output` grows through
    `write()` (e.g. from an on_advance hook). `collector_error` makes
    communicate fail like a broken collector. A wait/communicate without a
    timeout that cannot complete immediately raises UnboundedWaitReached
    instead of hanging.
    """

    def __init__(self, kernel, root_pid, pipe_holders=None, collector_error=None):
        self.k, self.pid, self.returncode = kernel, root_pid, None
        self.args = ["synthetic-worker"]
        self.pipe_holders = {root_pid} if pipe_holders is None else set(pipe_holders)
        self.collector_error = collector_error
        self.output = ""
        self.stdout = types.SimpleNamespace(closed=False)
        self.stdout.close = lambda: setattr(self.stdout, "closed", True)
        self.calls = []

    def write(self, text):
        if not self.stdout.closed:
            self.output += text

    def poll(self):
        if self.returncode is None:
            proc = self.k.procs.get(self.pid)
            if proc is not None and proc.state == "Z":
                # Reap the root; init reaps its zombie orphans.
                del self.k.procs[self.pid]
                for pid, other in list(self.k.procs.items()):
                    if other.ppid == self.pid and other.state == "Z":
                        del self.k.procs[pid]
                self.returncode = -proc.exit_code if proc.exit_code else 0
        return self.returncode

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.poll() is None:
            if timeout is None:
                raise UnboundedWaitReached("Popen.wait() without timeout")
            advance(self.k, timeout)
            if self.poll() is None:
                import subprocess
                raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def eof(self):
        return all(self.k.procs.get(p) is None or self.k.procs[p].state == "Z"
                   for p in self.pipe_holders)

    def communicate(self, timeout=None):
        import subprocess
        self.calls.append(("communicate", timeout))
        if self.collector_error is not None:
            raise self.collector_error
        if not (self.eof() and self.poll() is not None):
            if timeout is None:
                raise UnboundedWaitReached("Popen.communicate() without timeout")
            advance(self.k, timeout)
            if not (self.eof() and self.poll() is not None):
                raise subprocess.TimeoutExpired(self.args, timeout,
                                                output=self.output.encode())
        self.stdout.closed = True
        return self.output, None


class ObjectHandle:
    """Simulated pidfd: names the FakeProcess object, not the number."""
    __slots__ = ("pid", "obj", "fd")

    def __init__(self, pid, obj, fd):
        self.pid, self.obj, self.fd = pid, obj, fd


class FdPool:
    """A faithful simulated descriptor table (fd number -> kernel object).

    Lowest-free-number allocation, so closed numbers are reused.  Like a real
    syscall, every lookup goes through the number only: whatever object the
    number names *now* is what an effect reaches.
    """

    def __init__(self, first=3):
        self.first, self.table = first, {}

    @property
    def used(self):
        return set(self.table)

    def alloc(self, obj=None):
        fd = self.first
        while fd in self.table:
            fd += 1
        self.table[fd] = obj
        return fd

    def lookup(self, fd):
        return self.table.get(fd)

    def free(self, fd):
        return self.table.pop(fd, None)


class SimulatedObjectSignalPort:
    """pidfd-like effects on a FakeKernel through a faithful fd table.

    open(pid) installs the current object at the lowest free fd.  signal(),
    object_present(), object_matches() and close() resolve `handle.fd`
    through the descriptor table only (handle.obj is never consulted), so a
    closed-then-reused number would reach the new object, exactly like the
    real syscall.  Gone object -> ESRCH; pids in `eperm` -> PermissionError;
    `close_errors[fd]` makes close report an error after the number is freed
    (Linux close semantics).  `before_effect(kernel, handle)` runs at the
    effect boundary, after all validation, to model late races.
    """

    def __init__(self, kernel, ignore_term=(), eperm=(), fd_pool=None,
                 before_effect=None, close_errors=None):
        self.k, self.ignore_term, self.eperm = kernel, set(ignore_term), set(eperm)
        self.fd_pool = fd_pool or FdPool()
        self.before_effect = before_effect
        self.close_errors = dict(close_errors or {})
        self.calls = []

    def open(self, pid):
        obj = self.k.procs.get(pid)
        if obj is None:
            raise ProcessLookupError(errno.ESRCH, "fake pidfd_open ESRCH")
        handle = ObjectHandle(pid, obj, self.fd_pool.alloc(obj))
        self.calls.append(("open", pid, handle.fd))
        return handle

    def _object(self, handle):
        return self.fd_pool.lookup(handle.fd)

    def object_present(self, handle):
        obj = self._object(handle)
        return obj is not None and self.k.procs.get(obj.pid) is obj

    def object_matches(self, handle, pid, starttime):
        obj = self._object(handle)
        return (obj is not None and obj.pid == pid
                and self.k.procs.get(pid) is obj and obj.starttime == starttime)

    def signal(self, handle, signum):
        import signal as _signal
        if self.before_effect is not None:
            self.before_effect(self.k, handle)
        obj = self._object(handle)
        if obj is None:
            self.calls.append(("signal", None, handle.fd, int(signum), "EBADF"))
            raise OSError(errno.EBADF, "fake closed pidfd")
        if obj.pid in self.eperm:
            self.calls.append(("signal", obj.pid, handle.fd, int(signum), "EPERM"))
            raise PermissionError(errno.EPERM, "fake EPERM")
        if self.k.procs.get(obj.pid) is not obj:
            self.calls.append(("signal", obj.pid, handle.fd, int(signum), "ESRCH"))
            raise ProcessLookupError(errno.ESRCH, "fake object gone")
        if obj.state in ("Z", "X"):
            self.calls.append(("signal", obj.pid, handle.fd, int(signum), "ZOMBIE"))
            return
        if signum == _signal.SIGKILL or obj.pid not in self.ignore_term:
            self.k.exit(obj.pid, int(signum))
        self.calls.append(("signal", obj.pid, handle.fd, int(signum), "DELIVERED"))

    def close(self, handle):
        if handle.fd not in self.fd_pool.table:
            self.calls.append(("close", None, handle.fd))
            raise OSError(errno.EBADF, "fake close EBADF")
        obj = self.fd_pool.free(handle.fd)
        self.calls.append(("close", getattr(obj, "pid", None), handle.fd))
        error = self.close_errors.pop(handle.fd, None)
        if error is not None:
            raise error

    def effects(self):
        return [c for c in self.calls if c[0] == "signal" and c[4] == "DELIVERED"]


class FakeSamplerThread:
    """Stands in for the sampler thread on virtual time.

    join(timeout) either lets the sampler finish (one final tick, like the
    real _run) or, if `stuck`, consumes the timeout and stays alive.
    """

    def __init__(self, kernel, sampler, stuck=False):
        self.k, self.sampler, self.stuck = kernel, sampler, stuck
        self.alive = True
        self.joins = []

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joins.append(timeout)
        if not self.alive:
            return
        if timeout is None:
            raise UnboundedWaitReached("thread.join() without timeout")
        if self.stuck:
            advance(self.k, timeout)
            return
        try:
            self.sampler._timed_sample(final=True)
        except Exception as error:
            self.sampler.error = "%s:%s" % (type(error).__name__, error)
        self.alive = False


class FakeGroupSignals:
    """Synthetic process-group signal effects on a FakeKernel.

    SIGTERM ends every live group member not listed in `ignore_term`;
    SIGKILL ends every live group member. Models controller logic only.
    """

    def __init__(self, kernel, ignore_term=()):
        self.k, self.ignore_term = kernel, set(ignore_term)
        self.calls = []

    def kill(self, pgid, signum):
        import signal
        self.calls.append((pgid, int(signum)))
        members = [p for p in self.k.procs.values() if p.pgid == pgid and p.state != "Z"]
        if not members:
            raise ProcessLookupError(errno.ESRCH, "fake ESRCH")
        for proc in members:
            if signum == signal.SIGKILL or proc.pid not in self.ignore_term:
                self.k.exit(proc.pid, int(signum))
