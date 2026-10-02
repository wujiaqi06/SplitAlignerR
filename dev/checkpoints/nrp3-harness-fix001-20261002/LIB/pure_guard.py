"""Test-run host-effect guard (NRP2 FIX001 RESUME001).  DEFENSE IN DEPTH, NOT
A SANDBOX: it replaces the Python-level entry points of real host effects with
functions that record a violation and raise, WITHOUT performing the effect.
Mocks installed by tests (mock.patch of the same names) still take precedence
inside their scope, which is intended: mocked operations are allowed.

Guarded (real call => violation, effect NOT executed):
  process creation : os.fork/forkpty/posix_spawn(p)/system/popen/exec*/spawn*,
                     subprocess.Popen._execute_child (real Popen spawn)
  signals          : os.kill/killpg, signal.pthread_kill/pidfd_send_signal
  pidfd / wait     : os.pidfd_open (if present), os.wait/waitpid/wait3/wait4/waitid
  pipes            : os.pipe/pipe2
  native loading   : ctypes.CDLL / LibraryLoader.LoadLibrary (syscall shims)
  /proc            : builtins.open/io.open/os.open/os.stat/os.lstat/os.listdir/
                     os.scandir on any path under /proc (even self)
  FileStorage      : every class named FileStorage created after install
                     (builtins.__build_class__ hook) and any already imported
                     one: __init__/list/read/create_new raise
  os.link          : allowed only when both paths are inside the stage temp
                     root (acceptance envelope publication to stage fixtures)
Not covered: C extensions calling libc directly, code that captured the
original functions before install (install happens before any candidate
import), deliberate circumvention.
"""
from __future__ import annotations

import builtins
import io
import os
import signal
import subprocess
import sys

VIOLATIONS: list = []
INSTALLED = {"installed": False, "names": []}


class HostEffectViolation(BaseException):
    """BaseException so a broad `except Exception` in code under test cannot
    silently absorb it; the runner also fails on any recorded violation."""


def _violation(what: str, detail: str = ""):
    VIOLATIONS.append({"effect": what, "detail": detail[:300]})
    raise HostEffectViolation(f"HOST_EFFECT_BLOCKED:{what}:{detail[:200]}")


class _Blocked:
    """Callable OBJECT, not a function: it does not bind as a method when
    the stdlib stores it as a class attribute (e.g. pathlib accessors)."""

    def __init__(self, what):
        self.what = what

    def __call__(self, *args, **kwargs):
        _violation(self.what, repr(args)[:200])


class _Link:
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *a, **k):
        return self.fn(*a, **k)


class _ProcChecked:
    def __init__(self, what, original):
        self.what, self.original = what, original

    def __call__(self, path, *args, **kwargs):
        if _is_proc(path):
            _violation(self.what, str(path))
        return self.original(path, *args, **kwargs)


def _blocker(what):
    return _Blocked(what)


def _is_proc(path) -> bool:
    if isinstance(path, int):
        return False
    try:
        p = os.fspath(path)
    except TypeError:
        return False
    if isinstance(p, bytes):
        p = p.decode("utf-8", "replace")
    p = os.path.normpath(p if p.startswith("/") else os.path.join(_ORIG_GETCWD(), p))
    return p == "/proc" or p.startswith("/proc/")


def _proc_checked(what, original):
    return _ProcChecked(what, original)


def _filestorage_block(cls):
    for name in ("__init__", "list", "read", "create_new"):
        if name in cls.__dict__:
            setattr(cls, name, _blocker(f"{cls.__module__}.FileStorage.{name}"))
    cls._pure_guard_blocked = True


_ORIG_GETCWD = os.getcwd


def install(stage_tmp_root: str) -> None:
    if INSTALLED["installed"]:
        return
    stage_tmp_root = os.path.realpath(stage_tmp_root)
    names = INSTALLED["names"]

    def put(obj, name, value):
        if hasattr(obj, name):
            setattr(obj, name, value)
            names.append(f"{getattr(obj, '__name__', obj)}.{name}")

    for n in ("fork", "forkpty", "posix_spawn", "posix_spawnp", "system", "popen",
              "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp",
              "execvpe", "spawnv", "spawnve", "spawnl", "spawnle", "spawnvp",
              "spawnvpe", "spawnlp", "spawnlpe", "kill", "killpg", "pidfd_open",
              "wait", "waitpid", "wait3", "wait4", "waitid", "pipe", "pipe2"):
        put(os, n, _blocker(f"os.{n}"))
    for n in ("pthread_kill", "pidfd_send_signal", "sigqueue"):
        put(signal, n, _blocker(f"signal.{n}"))
    put(subprocess.Popen, "_execute_child", _blocker("subprocess.Popen._execute_child"))

    import ctypes

    class _BlockedCDLL:
        def __init__(self, *a, **k):
            _violation("ctypes.CDLL", repr(a)[:200])
    put(ctypes, "CDLL", _BlockedCDLL)
    put(ctypes, "PyDLL", _BlockedCDLL)
    put(ctypes.LibraryLoader, "LoadLibrary", _blocker("ctypes.LoadLibrary"))

    put(builtins, "open", _proc_checked("open", builtins.open))
    put(io, "open", _proc_checked("io.open", io.open))
    for n in ("open", "stat", "lstat", "listdir", "scandir"):
        put(os, n, _proc_checked(f"os.{n}", getattr(os, n)))

    orig_link = os.link

    def _link(src, dst, *a, **k):
        for p in (src, dst):
            real = os.path.realpath(os.path.dirname(os.path.abspath(os.fspath(p))))
            if not (real == stage_tmp_root or real.startswith(stage_tmp_root + os.sep)):
                _violation("os.link", f"{src}->{dst} outside stage temp root")
        return orig_link(src, dst, *a, **k)
    put(os, "link", _Link(_link))

    orig_build = builtins.__build_class__

    def build_class(func, name, *bases, **kw):
        cls = orig_build(func, name, *bases, **kw)
        if name == "FileStorage":
            _filestorage_block(cls)
        return cls
    builtins.__build_class__ = build_class
    names.append("builtins.__build_class__(FileStorage hook)")
    rescan_filestorage()
    INSTALLED["installed"] = True
    INSTALLED["stage_tmp_root"] = stage_tmp_root


def rescan_filestorage() -> int:
    n = 0
    for mod in list(sys.modules.values()):
        cls = getattr(mod, "FileStorage", None)
        if isinstance(cls, type) and not getattr(cls, "_pure_guard_blocked", False):
            _filestorage_block(cls)
            n += 1
    return n
