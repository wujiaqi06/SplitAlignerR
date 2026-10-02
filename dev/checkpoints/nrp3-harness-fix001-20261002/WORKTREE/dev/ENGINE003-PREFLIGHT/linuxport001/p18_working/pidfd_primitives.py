"""DEVELOPMENT_ONLY direct-owned-child primitives, not process-tree authority.
Import reads no host files, opens no native library and creates no processes.
"""
from dataclasses import dataclass
from pathlib import Path
import ctypes
import errno
import hashlib
import os
import platform
import re
import select
import signal
import threading
from parsers import ProcStat, parse_proc_stat

class PidfdError(RuntimeError):
    def __init__(self, code, operation='', error_number=None):
        self.code, self.operation, self.errno = code, operation, error_number
        super().__init__('%s:%s:errno=%s' % (code, operation, error_number))

def require(ok, code):
    if not ok: raise PidfdError(code)

class SigSet(ctypes.Structure):
    _fields_ = [('words', ctypes.c_ulong * 16)]

class SigAction(ctypes.Structure):
    _fields_ = [('handler', ctypes.c_void_p), ('mask', SigSet),
                ('flags', ctypes.c_int), ('restorer', ctypes.c_void_p)]

@dataclass(frozen=True)
class AcquisitionPolicy:
    exclusive_wait_owner: bool
    no_other_reaper: bool
    child_unreaped_since_fork: bool

@dataclass(frozen=True)
class AcquisitionEnvironment:
    handler: int
    flags: int
    task_count: int
    python_threads: int

def validate_acquisition_environment(policy, observed, no_cldwait):
    require(type(policy) is AcquisitionPolicy and all(type(v) is bool and v for v in (
        policy.exclusive_wait_owner, policy.no_other_reaper, policy.child_unreaped_since_fork)), 'UNPROVEN_WAIT_OWNERSHIP')
    require(type(observed) is AcquisitionEnvironment and all(type(v) is int for v in (observed.handler, observed.flags, observed.task_count, observed.python_threads)), 'ACQUISITION_ENVIRONMENT_TYPE')
    require(type(no_cldwait) is int and no_cldwait == 2, 'UNSUPPORTED_SIGNAL_FLAG')
    require(observed.handler == 0, 'SIGCHLD_MUST_BE_DEFAULT')
    require(observed.flags & no_cldwait == 0, 'SA_NOCLDWAIT_UNSUPPORTED')
    require(observed.task_count == 1 and observed.python_threads == 1, 'CONCURRENT_REAPER_UNSUPPORTED')
    return True

class NativeSyscalls:
    def __init__(self):
        require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'UNSUPPORTED_ARCH')
        require(ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(ctypes.c_long) == 8
                and ctypes.sizeof(ctypes.c_int) == 4 and ctypes.sizeof(SigAction) == 152
                and SigAction.flags.offset == 136 and SigAction.restorer.offset == 144, 'UNSUPPORTED_ABI')
        files = ['/usr/include/x86_64-linux-gnu/asm/unistd_64.h',
                 '/usr/include/x86_64-linux-gnu/bits/sigaction.h',
                 '/usr/include/x86_64-linux-gnu/bits/types/__sigset_t.h']
        raw = {}
        for path in files:
            try: value = Path(path).read_bytes()
            except OSError as e: raise PidfdError('HEADER_UNAVAILABLE', path, e.errno)
            require(0 < len(value) <= 128 * 1024, 'HEADER_LENGTH')
            raw[path] = value
        def macro(data, name):
            matches = re.findall(rb'^\s*#\s*define\s+' + name + rb'\s+(0x[0-9a-fA-F]+|[0-9]+)\b', data, re.M)
            require(len(matches) == 1, 'HEADER_CONSTANT_AMBIGUOUS')
            return int(matches[0], 0)
        self.open_number = macro(raw[files[0]], b'__NR_pidfd_open')
        self.signal_number = macro(raw[files[0]], b'__NR_pidfd_send_signal')
        self.no_cldwait = macro(raw[files[1]], b'SA_NOCLDWAIT')
        require((self.open_number, self.signal_number, self.no_cldwait) == (434, 424, 2), 'UNSUPPORTED_HEADER_ABI')
        self.provenance = dict(platform='Linux-x86_64-LP64', header_files=[dict(path=k,bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in raw.items()],
          pidfd_open=self.open_number, pidfd_send_signal=self.signal_number, SA_NOCLDWAIT=self.no_cldwait,
          sizeof_sigaction=ctypes.sizeof(SigAction), flags_offset=SigAction.flags.offset,
          restorer_offset=SigAction.restorer.offset, flags_supported=0)
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.syscall.argtypes = (ctypes.c_long,)
        self.libc.syscall.restype = ctypes.c_long
        self.libc.sigaction.argtypes = (ctypes.c_int, ctypes.POINTER(SigAction), ctypes.POINTER(SigAction))
        self.libc.sigaction.restype = ctypes.c_int

    @staticmethod
    def checked(rc, operation):
        if rc == -1:
            code = ctypes.get_errno()
            raise PidfdError('ENOSYS_UNSUPPORTED' if code == errno.ENOSYS else 'SYSCALL_ERROR', operation, code)
        return rc

    def open(self, pid, flags=0):
        require(type(pid) is int and 0 < pid < 2**31 and type(flags) is int and flags == 0, 'PIDFD_OPEN_ARGUMENT')
        ctypes.set_errno(0)
        return self.checked(self.libc.syscall(ctypes.c_long(self.open_number),ctypes.c_int(pid),ctypes.c_uint(0)), 'pidfd_open')

    def send(self, fd, sig):
        require(type(fd) is int and 0 <= fd < 2**31 and type(sig) in (int, signal.Signals) and sig in (0, int(signal.SIGTERM), int(signal.SIGKILL)), 'PIDFD_SIGNAL_ARGUMENT')
        ctypes.set_errno(0)
        return self.checked(self.libc.syscall(ctypes.c_long(self.signal_number),ctypes.c_int(fd),ctypes.c_int(sig),ctypes.c_void_p(0),ctypes.c_uint(0)), 'pidfd_send_signal')

    def acquisition_environment(self):
        current = SigAction(); ctypes.set_errno(0)
        self.checked(self.libc.sigaction(ctypes.c_int(signal.SIGCHLD),None,ctypes.byref(current)), 'sigaction_query')
        try: task_count = len(os.listdir('/proc/self/task'))
        except OSError as e: raise PidfdError('TASK_COUNT_UNAVAILABLE', '/proc/self/task', e.errno)
        return AcquisitionEnvironment(int(current.handler or 0), current.flags, task_count, threading.active_count())

class PidfdHandle:
    def __init__(self, native, fd, pid, kind, proof):
        self.native, self.fd, self.pid, self.kind, self.proof = native, fd, pid, kind, proof
        self.owner_pid = os.getpid(); self.closed = False

    def _live_handle(self):
        require(not self.closed, 'PIDFD_CLOSED')
        require(os.getpid() == self.owner_pid, 'HANDLE_OWNER_PROCESS_CHANGED')

    def send(self, sig=0):
        self._live_handle()
        require(self.kind == 'direct_child' or sig == 0, 'SELF_NONZERO_SIGNAL_FORBIDDEN')
        return self.native.send(self.fd, sig)

    def ready(self, timeout_ms=0):
        self._live_handle()
        require(type(timeout_ms) is int and 0 <= timeout_ms <= 10000, 'POLL_DEADLINE')
        try:
            poller = select.poll(); poller.register(self.fd, select.POLLIN | select.POLLHUP)
            events = poller.poll(timeout_ms)
        except OSError as e:
            raise PidfdError('PIDFD_POLL_SYSCALL_ERROR', 'poll', e.errno)
        if not events: return False
        require(len(events) == 1 and events[0][0] == self.fd and not events[0][1] & (select.POLLNVAL | select.POLLERR), 'PIDFD_POLL_ERROR')
        return bool(events[0][1] & (select.POLLIN | select.POLLHUP))

    def close(self):
        if self.closed: return
        self._live_handle(); self.closed = True
        try: os.close(self.fd)
        except OSError as e: raise PidfdError('PIDFD_CLOSE_ERROR', 'close', e.errno)

    def __enter__(self): self._live_handle(); return self
    def __exit__(self, *args): self.close()

def bounded_read(path, maximum):
    try:
        with open(path, 'rb') as f: raw = f.read(maximum + 1)
    except OSError as e: raise PidfdError('PROC_READ_ERROR', path, e.errno)
    require(len(raw) <= maximum, 'PROC_READ_BOUND')
    return raw

def direct_child_stat(pid):
    require(type(pid) is int and 0 < pid < 2**31, 'CHILD_PID_ARGUMENT')
    value = parse_proc_stat(bounded_read('/proc/%d/stat' % pid, 16384))
    require(value.pid == pid and value.ppid == os.getpid(), 'NOT_DIRECT_OWN_CHILD')
    return value

def wait_without_reaping(pid):
    require(type(pid) is int and 0 < pid < 2**31, 'CHILD_PID_ARGUMENT')
    try:
        result = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError as e: raise PidfdError('CHILD_ALREADY_REAPED_OR_NOT_OWNED', 'waitid', e.errno)
    except OSError as e: raise PidfdError('WAITID_ERROR', 'waitid', e.errno)
    if result is not None: require(result.si_pid == pid, 'WAITID_PID_CONFLICT')
    return result is not None

def open_self(native):
    fd = native.open(os.getpid(), 0)
    return PidfdHandle(native, fd, os.getpid(), 'self', {'self_only':True})

def acquire_direct_child(native, pid, expected, policy):
    """Requires caller's exclusive unreaped direct-child ownership since fork.
    The explicit declaration is not derived merely from a numeric PID.
    """
    validate_acquisition_environment(policy, native.acquisition_environment(), native.no_cldwait)
    require(type(pid) is int and 0 < pid < 2**31 and type(expected) is ProcStat, 'EXPECTED_CHILD_TYPE')
    require(expected.pid == pid and expected.ppid == os.getpid(), 'EXPECTED_CHILD_IDENTITY')
    zombie_before = wait_without_reaping(pid)
    before = direct_child_stat(pid)
    require((before.pid,before.ppid,before.starttime_ticks) == (expected.pid,expected.ppid,expected.starttime_ticks), 'CHILD_IDENTITY_CHANGED')
    fd = native.open(pid, 0)
    try:
        after = direct_child_stat(pid)
        require((after.pid,after.ppid,after.starttime_ticks) == (before.pid,before.ppid,before.starttime_ticks), 'CHILD_IDENTITY_CHANGED')
        zombie_after = wait_without_reaping(pid)
        validate_acquisition_environment(policy, native.acquisition_environment(), native.no_cldwait)
        info = bounded_read('/proc/self/fdinfo/%d' % fd, 8192)
        values = re.findall(rb'^Pid:\s+([0-9]+)\s*$', info, re.M)
        require(len(values) == 1 and int(values[0]) == pid, 'PIDFD_PID_BINDING')
        return PidfdHandle(native, fd, pid, 'direct_child', dict(pid=pid,ppid=before.ppid,starttime_ticks=before.starttime_ticks,
          zombie_before=zombie_before,zombie_after=zombie_after,fdinfo_pid=pid,
          acquisition_preconditions='default SIGCHLD; SA_NOCLDWAIT absent; one native/Python thread; caller exclusively owns unreaped child since fork; no other reaper',
          scope='P01_DIRECT_CHILD_PRIMITIVE_ONLY_NOT_CENSUS_AUTHORITY'))
    except BaseException:
        os.close(fd)
        raise
