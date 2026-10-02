"""Auxiliary test-run guard (NRP3_HARNESS_IMPL001).  MANDATORY, FAIL-CLOSED,
DEFENSE IN DEPTH, NOT A SANDBOX.

Adds blocks on top of the frozen pure_guard (a775347e...); it never unblocks a
pure_guard entry.  A blocked call records a violation in VIOLATIONS and raises
pure_guard.HostEffectViolation WITHOUT performing the effect.

Stacking contract (N-4): install(TMP) runs BEFORE run_pure.main and therefore
before pure_guard.install.  pure_guard captures the open/io.open/os.open
objects that exist at its install time, so its /proc wrappers wrap the
wrappers below; the reverse order is forbidden (stacking_report() shows it).
Wrappers accept (path, *args, **kwargs) as called by pure_guard._ProcChecked
and normalize flags/mode given positionally or by keyword.  An integer-fd
target (open/io.open/os.fdopen), any supplied dir_fd, a custom opener and
every missing or ambiguous argument is blocked (fail closed).

Blocked:
  os.open with O_WRONLY/O_RDWR/O_CREAT/O_TRUNC/O_APPEND, builtins.open/io.open
      with w/a/x/+ in the mode      -- unless target and parent realpath are
                                       TMP-internal
  os.mkdir/makedirs                 -- unless the target realpath is TMP or
                                       inside TMP
  os.fdopen, os.rmdir/remove/unlink/rename/replace/symlink/link/chmod/chown/
  truncate/utime (+ removedirs/renames/lchown/fchmod/fchown/ftruncate/mkfifo/
  mknod when present), shutil.rmtree/move/copy*      -- always
  os.fsync/fdatasync/sync                            -- always
  socket.socket/create_connection                    -- always
  os.setsid/setpgid/sched_setaffinity/nice/setpriority, resource.setrlimit
  signal.signal/siginterrupt/setitimer/alarm         -- always
  importlib.util.spec_from_file_location with an origin under WORKTREE
      -- unless the caller frame is PinnedImportSession.find_spec of the
         stage harness (code-object check; a stack-frame heuristic)
  runpy.run_path/run_module         -- always (stricter than "origin under
      WORKTREE": the origin of run_module cannot be decided without effects)
Not blocked by design: os.getpid, os.close, reads.

Not covered: C extensions calling libc, functions captured before install,
direct _io/posix access, deliberate circumvention.  The self-check after
install is a self-report, not certification.
"""
import builtins
import hashlib
import importlib.util
import io
import os
import resource
import runpy
import shutil
import signal
import socket
import sys

import pure_guard

VIOLATIONS = []
COUNTERS = {"calls": 0, "allowed_tmp_writes": 0, "passed_reads": 0, "blocked": 0}
INSTALLED = {"installed": False, "names": [], "tmp": None, "worktree": None}

_ORIG_GETCWD = os.getcwd
_REALPATH = os.path.realpath
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_STATE = {"tmp": None, "worktree": None, "harness_file": None}

ALWAYS_BLOCKED = (
    (os, ("fdopen", "rmdir", "remove", "unlink", "rename", "replace", "symlink", "link",
          "chmod", "chown", "truncate", "utime", "fsync", "fdatasync", "sync",
          "setsid", "setpgid", "sched_setaffinity", "nice", "setpriority")),
    (shutil, ("rmtree", "move", "copy", "copy2", "copyfile", "copyfileobj", "copymode",
              "copystat", "copytree")),
    (socket, ("socket", "create_connection")),
    (resource, ("setrlimit",)),
    (signal, ("signal", "siginterrupt", "setitimer", "alarm")),
    (runpy, ("run_path", "run_module")),
)
OPTIONAL_BLOCKED = (
    (os, ("removedirs", "renames", "lchown", "fchmod", "fchown", "ftruncate", "mkfifo",
          "mknod", "lchmod", "chflags", "lchflags")),
)


def _violation(what, detail=""):
    COUNTERS["blocked"] += 1
    VIOLATIONS.append({"effect": what, "detail": str(detail)[:300]})
    raise pure_guard.HostEffectViolation("AUX_HOST_EFFECT_BLOCKED:%s:%s"
                                         % (what, str(detail)[:200]))


def _text_path(path):
    """str path or None (None = undecidable -> caller blocks)."""
    if isinstance(path, (int, float)) or path is None:
        return None
    try:
        value = os.fspath(path)
    except TypeError:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    if not value.startswith("/"):
        value = os.path.join(_ORIG_GETCWD(), value)
    return value


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _write_target_in_tmp(path):
    """True only if the target, resolved, and its resolved parent are inside TMP."""
    tmp = _STATE["tmp"]
    text = _text_path(path)
    if tmp is None or text is None:
        return False
    parent = _REALPATH(os.path.dirname(text.rstrip("/") or "/"))
    return _inside(parent, tmp) and _inside(_REALPATH(text), tmp)


def _dir_target_in_tmp(path):
    tmp = _STATE["tmp"]
    text = _text_path(path)
    if tmp is None or text is None:
        return False
    return _inside(_REALPATH(text), tmp)


class _Wrapper:
    """Callable OBJECT (does not bind as a method when stored on a class)."""
    aux_guard_wrapper = True

    def __init__(self, what, original):
        self.what, self.original = what, original


class _Blocked(_Wrapper):
    def __call__(self, *args, **kwargs):
        COUNTERS["calls"] += 1
        _violation(self.what, repr(args)[:200])


class _OsOpen(_Wrapper):
    def __call__(self, path, *args, **kwargs):
        COUNTERS["calls"] += 1
        if len(args) > 2 or set(kwargs) - {"flags", "mode", "dir_fd"} \
                or (args and "flags" in kwargs) or (len(args) > 1 and "mode" in kwargs):
            _violation(self.what, "AMBIGUOUS_ARGUMENTS:%r" % (path,))
        if kwargs.get("dir_fd") is not None or "dir_fd" in kwargs:
            _violation(self.what, "DIR_FD_SUPPLIED:%r" % (path,))
        if not args and "flags" not in kwargs:
            _violation(self.what, "FLAGS_MISSING:%r" % (path,))
        flags = args[0] if args else kwargs["flags"]
        if type(flags) is not int:
            _violation(self.what, "FLAGS_TYPE:%r" % (path,))
        if isinstance(path, int) or _text_path(path) is None:
            _violation(self.what, "PATH_UNDECIDABLE:%r" % (path,))
        if flags & _WRITE_FLAGS:
            if not _write_target_in_tmp(path):
                _violation(self.what, "WRITE_OUTSIDE_TMP:%r flags=%d" % (path, flags))
            COUNTERS["allowed_tmp_writes"] += 1
        else:
            COUNTERS["passed_reads"] += 1
        return self.original(path, *args, **kwargs)


class _Open(_Wrapper):
    """builtins.open / io.open (file, mode='r', buffering, encoding, errors,
    newline, closefd, opener)."""

    def __call__(self, path, *args, **kwargs):
        COUNTERS["calls"] += 1
        allowed = {"mode", "buffering", "encoding", "errors", "newline", "closefd", "opener"}
        if len(args) > 7 or set(kwargs) - allowed or (args and "mode" in kwargs):
            _violation(self.what, "AMBIGUOUS_ARGUMENTS:%r" % (path,))
        if isinstance(path, int):
            _violation(self.what, "INTEGER_FD_TARGET:%r" % (path,))
        if len(args) > 6 or kwargs.get("opener") is not None:
            _violation(self.what, "OPENER_SUPPLIED:%r" % (path,))
        mode = args[0] if args else kwargs.get("mode", "r")
        if type(mode) is not str or not mode or set(mode) - set("rwxabt+U"):
            _violation(self.what, "MODE_UNDECIDABLE:%r" % (path,))
        if _text_path(path) is None:
            _violation(self.what, "PATH_UNDECIDABLE:%r" % (path,))
        if set(mode) & set("wax+"):
            if not _write_target_in_tmp(path):
                _violation(self.what, "WRITE_OUTSIDE_TMP:%r mode=%s" % (path, mode))
            COUNTERS["allowed_tmp_writes"] += 1
        else:
            COUNTERS["passed_reads"] += 1
        return self.original(path, *args, **kwargs)


class _Mkdir(_Wrapper):
    def __call__(self, path, *args, **kwargs):
        COUNTERS["calls"] += 1
        if "dir_fd" in kwargs:
            _violation(self.what, "DIR_FD_SUPPLIED:%r" % (path,))
        if set(kwargs) - {"mode", "exist_ok"} or len(args) > 2:
            _violation(self.what, "AMBIGUOUS_ARGUMENTS:%r" % (path,))
        if not _dir_target_in_tmp(path):
            _violation(self.what, "MKDIR_OUTSIDE_TMP:%r" % (path,))
        COUNTERS["allowed_tmp_writes"] += 1
        return self.original(path, *args, **kwargs)


class _SpecFromFileLocation(_Wrapper):
    def __call__(self, name, *args, **kwargs):
        COUNTERS["calls"] += 1
        if args and "location" in kwargs:
            _violation(self.what, "AMBIGUOUS_ARGUMENTS:%r" % (name,))
        location = args[0] if args else kwargs.get("location")
        candidates = [location] + list(kwargs.get("submodule_search_locations") or [])
        if len(args) > 1:
            _violation(self.what, "AMBIGUOUS_ARGUMENTS:%r" % (name,))
        under = False
        for item in candidates:
            if item is None:
                continue
            text = _text_path(item)
            if text is None or _inside(_REALPATH(text), _STATE["worktree"]):
                under = True
        if under and not _called_from_pinned_session(sys._getframe(1)):
            _violation(self.what, "WORKTREE_ORIGIN_OUTSIDE_PINNED_SESSION:%r" % (location,))
        return self.original(name, *args, **kwargs)


def _called_from_pinned_session(frame):
    """Caller code-object check (heuristic): the calling frame must be the
    find_spec code object of class PinnedImportSession defined in the stage
    harness file."""
    try:
        owner = type(frame.f_locals.get("self"))
        method = owner.__dict__.get("find_spec")
        return (owner.__name__ == "PinnedImportSession"
                and owner.__module__ == "nrp3_root_canary_harness"
                and getattr(method, "__code__", None) is frame.f_code
                and _REALPATH(frame.f_code.co_filename) == _STATE["harness_file"])
    except BaseException:
        return False


def own_sha256():
    with open(__file__, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def install(tmp):
    """Install every block.  Raises on any inconsistency (the launcher then
    never calls the runner).  Returns the install record."""
    if INSTALLED["installed"]:
        raise RuntimeError("AUX_GUARD_ALREADY_INSTALLED")
    if pure_guard.INSTALLED["installed"]:
        raise RuntimeError("AUX_GUARD_ORDER:pure_guard installed first")
    sha = own_sha256()
    stage = os.path.dirname(os.path.dirname(_REALPATH(__file__)))
    if type(tmp) is not str or _REALPATH(tmp) != tmp or os.path.basename(tmp) != "tmp" \
            or os.path.dirname(os.path.dirname(tmp)) != os.path.join(stage, "RUNS"):
        raise RuntimeError("AUX_GUARD_TMP_NOT_STAGE_RUN_TMP:%r" % (tmp,))
    worktree = _REALPATH(os.path.join(stage, "WORKTREE"))
    _STATE.update(tmp=tmp, worktree=worktree,
                  harness_file=os.path.join(stage, "HARNESS", "nrp3_root_canary_harness.py"))
    planned, missing = [], []
    for required, groups in ((True, ALWAYS_BLOCKED), (False, OPTIONAL_BLOCKED)):
        for obj, names in groups:
            for name in names:
                if hasattr(obj, name):
                    planned.append((obj, name, _Blocked("%s.%s" % (obj.__name__, name),
                                                        getattr(obj, name))))
                elif required:
                    missing.append("%s.%s" % (obj.__name__, name))
    if missing:
        raise RuntimeError("AUX_GUARD_REQUIRED_NAME_MISSING:" + ",".join(missing))
    planned += [
        (os, "open", _OsOpen("os.open", os.open)),
        (builtins, "open", _Open("builtins.open", builtins.open)),
        (io, "open", _Open("io.open", io.open)),
        (os, "mkdir", _Mkdir("os.mkdir", os.mkdir)),
        (os, "makedirs", _Mkdir("os.makedirs", os.makedirs)),
        (importlib.util, "spec_from_file_location",
         _SpecFromFileLocation("importlib.util.spec_from_file_location",
                               importlib.util.spec_from_file_location)),
    ]
    for obj, name, wrapper in planned:
        setattr(obj, name, wrapper)
        INSTALLED["names"].append("%s.%s" % (obj.__name__, name))
    bad = [("%s.%s" % (obj.__name__, name)) for obj, name, wrapper in planned
           if getattr(obj, name) is not wrapper]
    if bad:
        raise RuntimeError("AUX_GUARD_SELF_CHECK_FAILED:" + ",".join(bad))
    INSTALLED.update(installed=True, tmp=tmp, worktree=worktree)
    return {"installed": True, "names": list(INSTALLED["names"]), "tmp": tmp,
            "worktree": worktree, "aux_sha256": sha,
            "self_check": "ALL_LISTED_NAMES_REPLACED(self-report, not certification)"}


def stacking_report():
    """After the runner ran: pure_guard's /proc wrappers must wrap ours."""
    rows = {}
    for label, obj, name in (("builtins.open", builtins, "open"), ("io.open", io, "open"),
                             ("os.open", os, "open")):
        outer = getattr(obj, name)
        inner = getattr(outer, "original", None)
        rows[label] = {"outer": type(outer).__name__, "inner": type(inner).__name__,
                       "pure_guard_wraps_aux": type(outer).__name__ == "_ProcChecked"
                       and getattr(inner, "aux_guard_wrapper", False) is True}
    rows["all_ok"] = all(row["pure_guard_wraps_aux"] for row in list(rows.values()))
    return rows
