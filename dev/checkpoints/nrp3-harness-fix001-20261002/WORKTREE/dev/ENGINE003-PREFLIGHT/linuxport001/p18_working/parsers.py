"""DEVELOPMENT_ONLY Linux5.4/x86_64 bounded bytes parsers. Import is pure."""
from dataclasses import dataclass
import re
from typing import Tuple, Optional

U64 = (1 << 64) - 1
U32 = (1 << 32) - 1
I32 = (1 << 31) - 1
I64 = (1 << 63) - 1
STATES = frozenset(b'RSDZTtXI')

class ParseError(ValueError):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, detail
        super().__init__(code + (':' + detail if detail else ''))

def need(ok, code, detail=''):
    if not ok:
        raise ParseError(code, detail)

def bounded(raw, limit):
    need(type(raw) is bytes, 'INPUT_TYPE')
    need(0 < len(raw) <= limit, 'BYTE_LIMIT')
    need(b'\0' not in raw, 'NUL')
    need(raw.endswith(b'\n'), 'TRUNCATED_LINE')
    return raw

def number(token, low=0, high=U64):
    need(type(token) is bytes and len(token) <= 20, 'INTEGER_LENGTH')
    pattern = rb'-?(0|[1-9][0-9]*)' if low < 0 else rb'(0|[1-9][0-9]*)'
    need(re.fullmatch(pattern, token) is not None and token != b'-0', 'INTEGER_GRAMMAR')
    value = int(token)
    need(low <= value <= high, 'INTEGER_RANGE')
    return value

@dataclass(frozen=True)
class BootId:
    uuid: str

def parse_boot_id(raw):
    bounded(raw, 37)
    need(len(raw) == 37 and re.fullmatch(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\n', raw) is not None, 'BOOT_ID_FORMAT')
    need(raw[:-1] != b'00000000-0000-0000-0000-000000000000', 'BOOT_ID_ZERO')
    return BootId(raw[:-1].decode('ascii'))

@dataclass(frozen=True)
class ProcStat:
    pid: int
    comm: bytes
    state: str
    ppid: int
    pgrp: int
    session: int
    starttime_ticks: int
    threads: int
    values: Tuple[int, ...]  # ordered fields4..52, signedness preserved

# Documented scanf signed fields; the remaining4..52 are unsigned ulong/u64.
_SIGNED32 = frozenset((4, 5, 6, 7, 8, 38, 39, 52))
_SIGNED64 = frozenset((16, 17, 18, 19, 20, 21, 24, 44))
_UNSIGNED32 = frozenset((9, 40, 41))

def parse_proc_stat(raw):
    bounded(raw, 16384)
    first = raw.find(b' ('); last = raw.rfind(b') ')
    need(first > 0 and last > first + 1, 'STAT_COMM_DELIMITER')
    pid = number(raw[:first], 1, I32)
    comm = raw[first + 2:last]
    need(len(comm) <= 15, 'STAT_COMM_LENGTH')
    tail = raw[last + 2:-1]
    need(b'\n' not in tail and b'\r' not in tail, 'STAT_TRAILING_RECORD')
    fields = tail.split(b' ')
    need(len(fields) == 50 and all(fields), 'STAT_FIELD_COUNT')
    need(len(fields[0]) == 1 and fields[0][0] in STATES, 'STAT_STATE')
    values = []
    for field, token in enumerate(fields[1:], 4):
        if field in _SIGNED32:
            value = number(token, -I32 - 1, I32)
        elif field in _SIGNED64:
            value = number(token, -I64 - 1, I64)
        else:
            value = number(token, 0, U32 if field in _UNSIGNED32 else U64)
        values.append(value)
    def get(n): return values[n - 4]
    need(get(4) >= 0 and get(5) >= 0 and get(6) >= 0 and get(20) >= 1, 'STAT_IDENTITY_RANGE')
    need(get(22) > 0, 'STAT_STARTTIME_ZERO')
    return ProcStat(pid, comm, fields[0].decode('ascii'), get(4), get(5), get(6), get(22), get(20), tuple(values))

def field_lines(raw, limit):
    bounded(raw, limit)
    rows = raw[:-1].split(b'\n')
    need(len(rows) <= 256, 'FIELD_COUNT_LIMIT')
    result = {}
    for line in rows:
        need(len(line) <= 8192 and b':' in line, 'FIELD_LINE')
        key, value = line.split(b':', 1)
        need(re.fullmatch(rb'[A-Za-z][A-Za-z0-9_()]*', key) is not None, 'FIELD_NAME')
        need(key not in result, 'DUPLICATE_FIELD', key.decode('ascii'))
        need(value.startswith((b' ', b'\t')), 'FIELD_SEPARATOR')
        # Name has one formatting separator; remaining whitespace is data.
        value = value[1:] if key == b'Name' else value.strip(b' \t')
        need(b'\r' not in value, 'FIELD_VALUE')
        result[key] = value
    return result

@dataclass(frozen=True)
class ProcStatus:
    name: bytes
    state: str
    pid: int
    tgid: int
    ppid: int
    tracer_pid: int
    uid: Tuple[int, ...]
    gid: Tuple[int, ...]
    threads: Optional[int]
    namespace_fields: Tuple[Tuple[str, Tuple[int, ...]], ...]
    extra_fields: Tuple[Tuple[bytes, bytes], ...]

def parse_proc_status(raw):
    data = field_lines(raw, 65536)
    required = (b'Name', b'State', b'Pid', b'Tgid', b'PPid', b'TracerPid', b'Uid', b'Gid')
    need(all(k in data for k in required), 'STATUS_REQUIRED_FIELD')
    name = data[b'Name']; need(len(name) <= 256, 'STATUS_NAME_LENGTH')
    state = data[b'State']
    need(re.fullmatch(rb'[RSDZTtXI] \([^()\r\n]+\)', state) is not None, 'STATUS_STATE')
    pid = number(data[b'Pid'], 1, I32); tgid = number(data[b'Tgid'], 1, I32)
    need(pid == tgid, 'STATUS_NOT_PROCESS_LEADER')
    ppid = number(data[b'PPid'], 0, I32); tracer = number(data[b'TracerPid'], 0, I32)
    def ids(key):
        values = data[key].split()
        need(len(values) == 4, 'STATUS_CREDENTIAL_COUNT')
        return tuple(number(v, 0, U32) for v in values)
    namespaces = []
    for key in (b'NStgid', b'NSpid', b'NSpgid', b'NSsid'):
        if key not in data: continue
        tokens = data[key].split(); need(1 <= len(tokens) <= 32, 'NAMESPACE_DEPTH')
        numbers = tuple(number(v, 1, I32) for v in tokens)
        if key in (b'NStgid', b'NSpid'): need(numbers[0] == pid, 'NAMESPACE_PID_CONFLICT')
        namespaces.append((key.decode('ascii'), numbers))
    need(len({len(v) for _, v in namespaces}) <= 1, 'NAMESPACE_DEPTH_CONFLICT')
    ns = dict(namespaces)
    if 'NSpid' in ns and 'NStgid' in ns:
        need(ns['NSpid'] == ns['NStgid'], 'NAMESPACE_LEADER_CONFLICT')
    threads = number(data[b'Threads'], 1, I32) if b'Threads' in data else None
    known = set(required) | {b'Threads', b'NStgid', b'NSpid', b'NSpgid', b'NSsid'}
    return ProcStatus(name, chr(state[0]), pid, tgid, ppid, tracer, ids(b'Uid'), ids(b'Gid'), threads, tuple(namespaces), tuple((k, v) for k, v in data.items() if k not in known))

def check_stat_status(stat, status):
    need(type(stat) is ProcStat and type(status) is ProcStatus, 'RECORD_TYPE')
    need(stat.pid == status.pid and stat.ppid == status.ppid and stat.state == status.state, 'STAT_STATUS_CONFLICT')
    if status.threads is not None: need(stat.threads == status.threads, 'STAT_STATUS_THREADS')
    for key, values in status.namespace_fields:
        if key == 'NSpgid': need(values[0] == stat.pgrp, 'STAT_STATUS_PGRP')
        if key == 'NSsid': need(values[0] == stat.session, 'STAT_STATUS_SESSION')
    return True

@dataclass(frozen=True)
class MemTotal:
    kibibytes: int
    bytes: int

def parse_memtotal(raw):
    fields = field_lines(raw, 65536)
    need(b'MemTotal' in fields, 'MEMTOTAL_MISSING')
    tokens = fields[b'MemTotal'].split()
    need(len(tokens) == 2 and tokens[1] == b'kB', 'MEMTOTAL_UNIT')
    kib = number(tokens[0], 1, U64 // 1024)
    return MemTotal(kib, kib * 1024)

_ESCAPES = {b'040': b' ', b'011': b'\t', b'012': b'\n', b'134': b'\\'}
def unescape_mount(token):
    output = bytearray(); i = 0
    while i < len(token):
        if token[i] != 92:
            need(token[i] > 32 and token[i] != 127, 'MOUNT_LITERAL_CONTROL')
            output.append(token[i]); i += 1
        else:
            code = token[i + 1:i + 4]
            need(code in _ESCAPES, 'MOUNT_ESCAPE')
            output.extend(_ESCAPES[code]); i += 4
    return bytes(output)

def options(token):
    values = tuple(token.split(b','))
    need(all(values) and len(values) == len(set(values)), 'MOUNT_OPTIONS')
    need(not (b'ro' in values and b'rw' in values), 'MOUNT_MODE_CONFLICT')
    need(sum(v in (b'ro', b'rw') for v in values) == 1, 'MOUNT_MODE_MISSING')
    keys = [v.split(b'=', 1)[0] for v in values]
    need(all(keys), 'MOUNT_OPTION_EMPTY_KEY')
    need(len(keys) == len(set(keys)), 'MOUNT_OPTION_DUPLICATE_KEY')
    return tuple(unescape_mount(v) for v in values)

@dataclass(frozen=True)
class MountInfo:
    mount_id: int
    parent_id: int
    major: int
    minor: int
    root: bytes
    mount_point: bytes
    mount_options: Tuple[bytes, ...]
    optional: Tuple[Tuple[str, Optional[int]], ...]
    fs_type: str
    source: bytes
    super_options: Tuple[bytes, ...]

def parse_mountinfo(raw):
    bounded(raw, 1024 * 1024)
    lines = raw[:-1].split(b'\n'); need(len(lines) <= 4096, 'MOUNT_COUNT')
    result = []; seen = set()
    for line in lines:
        need(len(line) <= 16384 and line.count(b' - ') == 1, 'MOUNT_SEPARATOR')
        left, right = line.split(b' - ')
        a = left.split(b' '); b = right.split(b' ')
        need(len(a) >= 6 and len(b) == 3 and all(a + b), 'MOUNT_FIELDS')
        mount_id = number(a[0], 1, U32); parent = number(a[1], 1, U32)
        need(mount_id not in seen, 'MOUNT_DUPLICATE_ID'); seen.add(mount_id)
        device = a[2].split(b':'); need(len(device) == 2, 'MOUNT_DEVICE')
        major, minor = (number(v, 0, U32) for v in device)
        root, mount_point = unescape_mount(a[3]), unescape_mount(a[4])
        need(root.startswith(b'/') and mount_point.startswith(b'/'), 'MOUNT_ABSOLUTE')
        optional = []; optional_seen = set()
        for item in a[6:]:
            parts = item.split(b':'); key = parts[0]
            need(key in (b'shared', b'master', b'propagate_from', b'unbindable') and key not in optional_seen, 'MOUNT_OPTIONAL')
            optional_seen.add(key)
            if key == b'unbindable': need(len(parts) == 1, 'MOUNT_OPTIONAL_VALUE'); val = None
            else: need(len(parts) == 2, 'MOUNT_OPTIONAL_VALUE'); val = number(parts[1], 1, U32)
            optional.append((key.decode('ascii'), val))
        need(not (b'unbindable' in optional_seen and optional_seen.intersection((b'shared', b'master', b'propagate_from'))), 'MOUNT_PROPAGATION_CONFLICT')
        need(b'propagate_from' not in optional_seen or b'master' in optional_seen, 'MOUNT_MASTER_MISSING')
        need(re.fullmatch(rb'[A-Za-z0-9_.-]+', b[0]) is not None, 'MOUNT_FS_TYPE')
        result.append(MountInfo(mount_id, parent, major, minor, root, mount_point, options(a[5]), tuple(optional), b[0].decode('ascii'), unescape_mount(b[1]), options(b[2])))
    by_id = {v.mount_id: v for v in result}
    for row in result:
        visited = set(); current = row
        while current.parent_id in by_id:
            need(current.mount_id not in visited, 'MOUNT_PARENT_CYCLE')
            visited.add(current.mount_id); current = by_id[current.parent_id]
    return tuple(result)
