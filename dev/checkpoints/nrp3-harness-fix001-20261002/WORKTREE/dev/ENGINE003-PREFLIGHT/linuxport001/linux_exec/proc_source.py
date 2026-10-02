"""Read-only /proc port for the Linux process-tree backend (development only).

RealProcSource does exactly two kinds of host operation: one listing of /proc
and bounded read-only opens of /proc/<pid>/stat, /proc/<pid>/smaps_rollup and
/proc/self/mountinfo. It never signals, never opens a pidfd, never writes and
never follows a path outside /proc. Absolute paths and builtin open() are used
deliberately: the development guard audits exactly those opens, and closing a
file object does not go through os.close.
"""
import errno
import os
import re

MAX_PROC_ENTRIES = 1 << 22          # pid_max ceiling on x86_64 Linux
READ_LIMITS = {"stat": 16384, "smaps_rollup": 65536}
SELF_READ_LIMITS = {"mountinfo": 1024 * 1024}
ABSENT_ERRNOS = frozenset((errno.ENOENT, errno.ESRCH))


class ProcAbsent(Exception):
    """The /proc entry does not exist (process gone or never existed)."""

    def __init__(self, pid, name):
        self.pid, self.name = pid, name
        super().__init__("PROC_ABSENT:%s:%s" % (pid, name))


class ProcReadError(Exception):
    """Any other read failure: never interpreted as absence."""

    def __init__(self, pid, name, error_number, code="PROC_READ_ERROR"):
        self.pid, self.name, self.errno, self.code = pid, name, error_number, code
        super().__init__("%s:%s:%s:errno=%s" % (code, pid, name, error_number))


class RollupParseError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _bounded_file_read(path, limit):
    with open(path, "rb", buffering=0) as fh:
        data = fh.read(limit + 1)
    return data


class RealProcSource:
    description = "LINUX_PROCFS_ABSOLUTE_PATH_READ_ONLY"

    def list_pids(self):
        try:
            entries = os.listdir("/proc")
        except OSError as exc:
            raise ProcReadError(None, "listdir", exc.errno, "PROC_LIST_ERROR")
        if len(entries) > MAX_PROC_ENTRIES:
            raise ProcReadError(None, "listdir", None, "PROC_LIST_BOUND")
        pids = []
        for name in entries:
            if name.isdigit() and name[0] != "0" and name.isascii():
                pids.append(int(name))
        return tuple(sorted(pids))

    def read(self, pid, name):
        if type(pid) is not int or pid <= 0 or name not in READ_LIMITS:
            raise ProcReadError(pid, name, None, "PROC_READ_ARGUMENT")
        limit = READ_LIMITS[name]
        try:
            data = _bounded_file_read("/proc/%d/%s" % (pid, name), limit)
        except OSError as exc:
            if exc.errno in ABSENT_ERRNOS:
                raise ProcAbsent(pid, name)
            raise ProcReadError(pid, name, exc.errno)
        if len(data) > limit:
            raise ProcReadError(pid, name, None, "PROC_READ_BOUND")
        return data

    def read_self(self, name):
        if name not in SELF_READ_LIMITS:
            raise ProcReadError("self", name, None, "PROC_READ_ARGUMENT")
        limit = SELF_READ_LIMITS[name]
        try:
            data = _bounded_file_read("/proc/self/" + name, limit)
        except OSError as exc:
            raise ProcReadError("self", name, exc.errno)
        if len(data) > limit:
            raise ProcReadError("self", name, None, "PROC_READ_BOUND")
        return data


_ROLLUP_HEADER = re.compile(
    rb"[0-9a-f]{1,16}-[0-9a-f]{1,16} [-r][-w][-x][-sp] [0-9a-f]{1,16} "
    rb"[0-9a-f]{2,}:[0-9a-f]{2,} [0-9]+ +\[rollup\]\Z")
_ROLLUP_FIELD = re.compile(rb"([A-Za-z][A-Za-z_]*):[ \t]+(0|[1-9][0-9]{0,19}) kB\Z")


def parse_smaps_rollup_rss_bytes(raw):
    """Strict Linux 5.4 smaps_rollup: header line, unique `Key: N kB` rows.

    Returns Rss in bytes. Empty input (a zombie or kernel thread has no mm)
    raises SMAPS_ROLLUP_EMPTY so the caller must decide what it means.
    """
    if type(raw) is not bytes:
        raise RollupParseError("SMAPS_ROLLUP_TYPE")
    if raw == b"":
        raise RollupParseError("SMAPS_ROLLUP_EMPTY")
    if len(raw) > READ_LIMITS["smaps_rollup"] or b"\0" in raw or not raw.endswith(b"\n"):
        raise RollupParseError("SMAPS_ROLLUP_FRAMING")
    lines = raw[:-1].split(b"\n")
    if not _ROLLUP_HEADER.match(lines[0]):
        raise RollupParseError("SMAPS_ROLLUP_HEADER")
    fields = {}
    for line in lines[1:]:
        match = _ROLLUP_FIELD.match(line)
        if match is None:
            raise RollupParseError("SMAPS_ROLLUP_FIELD")
        if match.group(1) in fields:
            raise RollupParseError("SMAPS_ROLLUP_DUPLICATE_FIELD")
        fields[match.group(1)] = int(match.group(2))
    if b"Rss" not in fields:
        raise RollupParseError("SMAPS_ROLLUP_RSS_MISSING")
    return fields[b"Rss"] * 1024
