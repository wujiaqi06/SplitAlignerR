"""NRP3 native root-capability canary harness -- DISABLED (NRP3_HARNESS_IMPL001,
repair FIX001: R1/R2/R6).

Not an accepted implementation and not an authorization.  It cannot act:
HARNESS_ENABLED is False and KNOWN_UNSERVED_NAMES_SHA256 is None; main()
refuses through the T0 sink before either dependency factory is called.  No
environment variable, CLI flag or file can enable the gate.  Enabling is NOT
a two-constant edit to be made from this text: any enabled object would be a
separately authorized, separately reviewed and separately hashed copy (not
this stage), and the bytes here carry no such authority.

Exit codes: 0 PASS (narrow, see PASS_MEANING; consumable only together with a
matching stdout receipt, see receipt_authority_decision); 2 STOP; 3 REFUSED.
No path sends a signal, kills, terminates or reaps anything but the one owned
child via the injected process port.

Three bootstrap tiers, built in this order, no circular dependency:
  T0 _StdSink            before the gate check; the only output path
  T1 _build_read_deps    after the gate passes, before authorization (reads)
  T2 _build_effect_deps  only after authorization returned an approval
Every refusal before T2 exists goes through T0 only.  Python-level callers
can reach _attempt (reviewed injection seam): a stated limit, not a
protection.

Order: gate -> T1 -> authorization (reads only) -> T2 -> consume attempt
(first write; create boundary) -> lifecycle (RUN_DIR ... SECOND_CLOSE_
IDEMPOTENCE) -> one ownership-aware signal-free cleanup -> end_check #1 ->
final decision -> publish (end_check #2 FIRST, then serialize, EVIDENCE.json,
stderr STOP record (STOP only), stdout receipt).

First-failure rule: the chronologically first failure in ANY phase is the
primary; every later failure is secondary.  A synthetic CHECK_FAILED primary
is created only when no failure record exists at all.

Loader lifetime: PinnedImportSession has no removal path; it stays at
sys.meta_path[0] until process exit.  See NOT_CERTIFIED for what the two
end-checks do not cover.  The pinned loader is not a sandbox; the origin sweep
is detection after execution.

Ownership (R1/R6): a resource is registered as unresolved BEFORE the call
that could lose track of it and is dropped only on a confirmed release.  A
spawn_child call that raises -- any exception type -- leaves the outcome
unknown; nothing here infers "no child" from an exception class.  Catching
an error in a guarded step is not ownership completion.  On an outer abort
the handler emits a finite snapshot of state ALREADY recorded by this
harness (no host query, no cleanup, nothing blocking); it is best effort and
is never complete evidence.

Unserved names (R2): see refusal_universe().  The approval declares the
known-but-unserved names (hash-bound to the gate); the plan's lazy-refused
names are enforced separately; the union is the total refusal universe.

Honest limits: an uncatchable termination of the harness, an interrupt
between guarded steps (the outer handler records what it can), a kernel call
that blocks indefinitely, power-loss durability and the child's reaction to
closed pipe ends are not handled or observed here.
"""
import errno
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time

HARNESS_ENABLED = False          # never changed in this stage
# sha256 of "".join(name + "\n" for name in sorted(declared)), where `declared`
# is the approval's known_unserved_candidate_names: the canonical DECLARED set
# (served names and lazy-refused names excluded; see refusal_universe()).
# None = not bound: refused.  The re-derived list and hash are REPORTED in
# BUILD/IMPORT_CLOSURE_HARNESS.json, never written here in this stage.
KNOWN_UNSERVED_NAMES_SHA256 = None
APPROVAL_SCHEMA = "SplitAlignerR/NRP3RootCanaryApproval/v5"
EVIDENCE_SCHEMA = "SplitAlignerR/NRP3RootCanaryEvidence/v4"
RECEIPT_SCHEMA = "SplitAlignerR/NRP3RootCanaryReceipt/v2"
HARNESS_ID = "NRP3_ROOT_CANARY_HARNESS_IMPL001_FIX001_DISABLED"
EXIT_PASS = 0
EXIT_STOP = 2
EXIT_REFUSED = 3
ATTEMPT_ID_PATTERN = "[A-Z0-9_]{1,64}"
NAME_PATTERN = "[A-Za-z_][A-Za-z0-9_]*"
MAX_APPROVAL_BYTES = 65536
MAX_WINDOW_SECONDS = 86400
MAX_STDERR_RECORD_BYTES = 1048576
COMMUNICATE_TIMEOUT_S = 10.0
CLEANUP_WAIT_TIMEOUT_S = 10.0
CLOSE_LOCK_TIMEOUT_S = 5.0
STDOUT_BOUND = 4096
CREATE_MODE = 0o444
RUN_DIR_MODE = 0o700
CHILD_ARGV_TAIL = ("-I", "-S", "-c",
                   "import sys; sys.stdin.read(); sys.stdout.write('NRP3_CHILD_DONE\\n')")
NATIVE_RUN_ID = "NRP3_ROOT_CANARY"
NATIVE_OWNER = "NRP3_ROOT_CANARY_HARNESS"
NATIVE_GENERATION = 1
LOADER_LIFETIME = "RETAINED_AT_META_PATH_0_UNTIL_PROCESS_EXIT"
INERT_SAMPLER_LABEL = "NRP3_CANARY_INERT_SAMPLER_FIXTURE_NOT_A_BACKEND"
# Production load plan (pure literal).  served: the 19-file eager closure,
# verified at load, served from those bytes for the whole lifecycle and
# re-verified at the final decision.  lazy_refused: pinned, never served.
PRODUCTION_PLAN = {
    "served": (
        "dev/ENGINE003-PREFLIGHT/exec_preflight/fix001_contract.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_authorization.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_dispatch_journal.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_orchestrator.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/linux_entry.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/linux_proc_backend.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/native_root_port.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/proc_source.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/termination.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/parsers.py",
        "dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/pidfd_primitives.py",
        "dev/ENGINE003-PREFLIGHT/reference/canonical_text.py",
        "dev/ENGINE003-PREFLIGHT/reference/encode_boundary_fixture.py",
        "dev/ENGINE003-PREFLIGHT/reference/encode_stage_a_tiled_store.py",
        "dev/ENGINE003-PREFLIGHT/reference/encode_tiny_fixture.py",
        "dev/ENGINE003-PREFLIGHT/reference/stage_a_authority_v2.py",
        "dev/ENGINE003-PREFLIGHT/reference/stage_a_fiber_v3.py",
    ),
    "lazy_refused": (
        "dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py",
        "dev/ENGINE003-PREFLIGHT/reference/probe_durability_capabilities.py",
    ),
    "port_module_relpath": "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/native_root_port.py",
    "entry_imports": ("stage_b_controller", "stage_b_dispatch_journal", "termination",
                      "linux_entry", "native_root_port"),
    "p18_entry_imports": ("pidfd_primitives", "parsers"),
    # Import-time sys.path inserts made by accepted closure modules
    # (stage_b_controller.py:28-30, stage_b_orchestrator.py:32-34,
    # stage_b_runtime_contract.py:25-30).  Any other sys.path delta is a STOP.
    "expected_sys_path_inserts": ("dev/ENGINE003-PREFLIGHT/exec_preflight",
                                  "dev/ENGINE003-PREFLIGHT/reference",
                                  "dev/ENGINE003-PREFLIGHT/pilot"),
}
PHASE_SEQUENCE = ("RUN_DIR", "LOAD_MODULES", "BUILD_PORTS", "NEW_CONTEXT", "ADMIT", "SPAWN",
                  "ATTACH_ROOT", "EFFECT_EVIDENCE", "NATURAL_COMPLETION", "FIRST_CLOSE",
                  "SECOND_CLOSE_IDEMPOTENCE")
ATTEMPT_STATES = ("UNKNOWN_NO_WRITE_BY_THIS_RUN", "ALREADY_SPENT_PRIOR_RUN",
                  "UNSPENT_CONFIRMED_ABSENT", "SPENT_THIS_RUN", "POSSIBLY_SPENT_THIS_RUN")
REQUIRED_APPROVAL_FIELDS = (
    "approved_by", "approved_utc", "expires_utc", "attempt_id", "run_dir",
    "consumption_ledger_dir", "candidate_root", "candidate_files",
    "candidate_manifest_sha256", "harness_sha256", "port_module_sha256", "interpreter",
    "effects", "forbidden_effects_acknowledged", "protected_roots",
    "known_unserved_candidate_names")
EXPECTED_EFFECTS = (
    "SPAWN_ONE_DIRECT_CHILD:{INTERPRETER} -I -S -c <STDIN_EOF_READER>;start_new_session=True;close_fds=True",
    "PIPES_CREATED:2(child_stdin,child_stdout;stderr=STDOUT;binary bytes mode)+1 Popen internal exec-error pipe(CLOEXEC, closed by Popen)",
    "PIPE_CLOSES:parent_stdin<=1(communicate entry or cleanup),parent_stdout<=1(communicate, or cleanup only after the child is reaped; otherwise left open until harness exit)",
    "PIDFD_OPEN:<=1(child pid, flags=0)",
    "PIDFD_CLOSE:<=1(table CLOSING claimant only)",
    "WAITID_WNOWAIT:2(WEXITED|WNOHANG|WNOWAIT; never reaps)",
    "REAP:<=1(own child only; Popen.communicate or bounded Popen.wait)",
    "PROC_READS:/proc/<child>/stat x3,/proc/self/fdinfo/<pidfd> x1,/proc/self/task listdir x3,/proc/sys/kernel/random/boot_id x2",
    "SIGACTION_QUERY:SIGCHLD read-only x3",
    "HEADER_READS:/usr/include/x86_64-linux-gnu/{asm/unistd_64.h,bits/sigaction.h,bits/types/__sigset_t.h} x1",
    "CTYPES_LIBC_LOAD:CDLL(None) x1",
    "HOST_FACTS:sys.version,sys.executable realpath",
    "SOURCE_READS:harness x3,approval x1,all candidate_files (authorization),served set (load, final)",
    "IMPORT_RESOLUTION:pinned loader at sys.meta_path[0] until process exit (never removed);PathFinder location lookups (stat/listdir of sys.path entries, or of the parent package path for a qualified name) for names outside the refusal universe;import-time sys.path inserts exec_preflight,reference,pilot by accepted modules",
    "LOADED_UNREACHED_SPAWN_KILL_SITES:7 subprocess.run + 1 Popen + 2 os.killpg + 1 Darwin ctypes.CDLL in served non-p18 bytes;expected reach 0;origin sweep cannot detect a reach;static call graph only",
    "FILES_CREATED:ledger/<attempt>.CONSUMED x1(O_EXCL),run_dir x1(mkdir),run_dir/EVIDENCE.json x1(O_EXCL)",
    "FSYNC:marker x1,ledger dir x1,run_dir parent x1,EVIDENCE.json x1,run_dir x1",
    "STDOUT_STDERR:one JSON receipt line on stdout; stderr STOP record on every STOP, abort or receipt write failure",
)
FORBIDDEN_EFFECTS = ("ANY_SIGNAL", "KILL", "KILLPG", "TERMINATE", "GROUP_SIGNAL",
                     "PR_SET_CHILD_SUBREAPER", "CGROUP", "ROOT", "NETWORK", "INSTALL",
                     "JOURNAL_FILESTORAGE", "STAGEB_WORKER", "LAUNCH_REQUEST_DISPATCH",
                     "BENCHMARK", "AFFINITY", "SIGNAL_HANDLER_CHANGE")
PASS_MEANING = ("PASS_NARROW: one owned direct child was pidfd-acquired with a sampled, "
                "verified identity, completed naturally, was reaped by Popen, and its pidfd "
                "was closed exactly once. No controller dispatch path (launch_request, "
                "ticket, latch commit) was exercised; no StageB worker; no journal storage; "
                "no termination, descendant, storage, cadence or recovery claim. Grants no "
                "dispatch or native-activation permission.")
NOT_EXERCISED = ("launch_request", "dispatch_ticket", "dispatch_latch_commit",
                 "journal_FileStorage", "StageB_worker", "any_signal")
NOT_CERTIFIED = (
    "Anything after end_check #2: evidence serialization, the RealFS write, the stderr record, "
    "the receipt write and flush, atexit, interpreter finalization, finalizers/__del__ during GC "
    "or shutdown. The loader stays installed, but finalization tears import state down, so "
    "served/refused/failed imports in this window are not observed.",
    "Code that bypasses sys.meta_path.",
    "Effects of code that already ran (origin sweep = detection after execution).",
    "Whether meta_path[0] stayed in place between checks if code removed and re-inserted it.",
)
RECEIPT_RULE = ("Authority: the stdout receipt line plus the process exit code.  A PASS is "
                "consumable only if exit code == 0 AND stdout is exactly one complete "
                "newline-terminated JSON object AND the receipt verdict is PASS AND the "
                "receipt evidence_file.state is COMPLETE_FSYNC_REQUESTED AND sha256(EVIDENCE.json "
                "bytes) equals receipt evidence_file.sha256 AND that file says PASS.  Any "
                "disagreement, a missing or incomplete receipt or a missing file is STOP.  "
                "EVIDENCE.json alone is PRELIMINARY until matched by the receipt; a STOP "
                "receipt/stderr record that names it as superseded overrides its verdict, "
                "never its recorded observations.")
STOP_RECORD_REDUCED_KEYS = (
    "record", "schema", "attempt_id", "verdict", "exit_code", "pass_meaning",
    "spent_by_this_run", "attempt_state", "primary", "secondary", "checks",
    "superseded_file", "unresolved_ownership", "custody", "receipt_rule")
REFUSAL_UNIVERSE_RULE = (
    "declared = approval known_unserved_candidate_names (sorted, unique, hash-bound to the "
    "gate; excludes served and lazy-refused names); lazy = basenames of plan lazy_refused "
    "(enforced from the plan, never from the approval); refusal universe = declared | lazy; "
    "served, declared and lazy are pairwise disjoint; a name outside the universe is "
    "refused by its located origin (top-level or qualified) when that lies under "
    "candidate_root")
# Outcomes copied into the abort snapshot when a guarded step ALREADY recorded
# them (plain data; nothing is re-read from a live object).
ABORT_SNAPSHOT_OUTCOMES = (
    "child_pid", "child_returncode", "first_close", "second_close", "cleanup_stdin",
    "cleanup_wait", "cleanup_stdout", "cleanup_context_close", "context_state",
    "route_report")
ABORT_SNAPSHOT_RULE = (
    "BEST_EFFORT_NOT_COMPLETE_EVIDENCE: a finite copy of state this harness had already "
    "recorded when the abort was caught; no host query, no cleanup and no blocking call "
    "was made to build it; a row may be stale; absence of a row proves nothing; if both "
    "sinks fail no record exists and nothing is claimed")

ATTEMPT_ID_RE = re.compile(ATTEMPT_ID_PATTERN)
NAME_RE = re.compile(NAME_PATTERN)


class Refused(Exception):
    def __init__(self, code, detail="", attempt_state="UNKNOWN_NO_WRITE_BY_THIS_RUN",
                 note=None):
        super().__init__("%s:%s" % (code, detail))
        self.code, self.detail = code, detail
        self.attempt_state, self.note = attempt_state, note


class Stop(Exception):
    """A controlled STOP inside the lifecycle (never a PASS)."""
    def __init__(self, code, detail=""):
        super().__init__("%s:%s" % (code, detail))
        self.code, self.detail = code, detail


class PublishFailure(Exception):
    """create_exclusive failed after the descriptor was obtained.  `progress`
    keeps the FIRST error, the stage reached and a separate close-failure
    record."""
    def __init__(self, progress):
        super().__init__("PUBLISH_FAILED:%s" % progress.get("stage"))
        self.code, self.progress = "PUBLISH_FAILED", progress


class InertSamplerFixture:
    """Inert sampler fixture: NOT a backend selection.  No methods; any
    attribute access is recorded and refused (check inert_sampler_untouched)."""

    def __init__(self, label):
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "accessed", [])

    def __getattr__(self, name):
        self.accessed.append(name)
        raise AttributeError("NRP3_INERT_SAMPLER_FIXTURE_HAS_NO_BACKEND_SURFACE:%s" % name)


INERT_SAMPLER = InertSamplerFixture(INERT_SAMPLER_LABEL)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _serialize(obj):
    return json.dumps(obj, sort_keys=True, default=repr).encode("utf-8")


def _annotate(error, key, value):
    try:
        setattr(error, key, value)
    except BaseException:
        pass


def _describe(error):
    try:
        chain, seen, cur = [], set(), error
        while cur is not None and id(cur) not in seen and len(chain) < 8:
            seen.add(id(cur))
            chain.append("%s:%s" % (type(cur).__name__, cur))
            cur = cur.__cause__ or cur.__context__
        code = getattr(error, "code", None)
        out = {"type": type(error).__name__, "text": chain[0], "chain": chain,
               "code": code if isinstance(code, str) else None}
        for key in ("progress", "nrp3_publish"):
            value = getattr(error, key, None)
            if isinstance(value, dict):
                out[key] = dict(value)
        return out
    except BaseException:
        return {"type": "UNDESCRIBABLE", "text": "", "chain": [], "code": None}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _raise_first(first, progress):
    progress["first_error"] = _describe(first)
    if isinstance(first, Exception):
        raise PublishFailure(progress) from first
    _annotate(first, "nrp3_publish", dict(progress))   # e.g. KeyboardInterrupt keeps its type
    raise first


def manifest_sha256(files):
    """'<sha>  <relpath>\\n' sorted by relpath."""
    return sha256_bytes("".join("%s  %s\n" % (files[rel], rel)
                                for rel in sorted(files)).encode("utf-8"))


def names_sha256(names):
    return sha256_bytes("".join(n + "\n" for n in sorted(names)).encode("utf-8"))


def _module_name(rel):
    return os.path.basename(rel)[:-3]


def refusal_universe(plan, declared):
    """R2: the single definition of the set semantics, used at authorization
    and at load.  `declared` is the approval list (hash-bound to the gate):
    every candidate name that is neither served nor lazy-refused.  For the
    production tree that is reference232 = the .py basenames plus the
    identifier-named directories (namespace-importable) under candidate_root,
    minus the 19 served names, minus the 2 lazy-refused names.  The
    lazy-refused names come from the plan, never from the approval, and are
    enforced separately; the total refusal universe is declared | lazy (234).
    Served, declared and lazy must be pairwise disjoint and the plan must not
    map two files to one module name; otherwise Stop."""
    served = [_module_name(rel) for rel in plan["served"]]
    lazy = [_module_name(rel) for rel in plan["lazy_refused"]]
    declared = set(declared)
    if len(set(served)) != len(served) or len(set(lazy)) != len(lazy):
        raise Stop("PLAN_BASENAME_COLLISION")
    for code, overlap in (
            ("SERVED_NAME_LISTED_AS_UNSERVED", set(served) & declared),
            ("LAZY_REFUSED_NAME_LISTED_AS_DECLARED", set(lazy) & declared),
            ("PLAN_SERVED_AND_LAZY_REFUSED_OVERLAP", set(served) & set(lazy))):
        if overlap:
            raise Stop(code, ",".join(sorted(overlap)))
    return frozenset(declared | set(lazy))


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _safe_relpath(rel):
    return (type(rel) is str and bool(rel) and not os.path.isabs(rel)
            and os.path.normpath(rel) == rel and ".." not in rel.split("/"))


def _strict_json(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_KEY")
        return dict(items)

    def constant(name):
        raise ValueError("NON_FINITE_NUMBER:" + name)
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


# ---------------------------------------------------------------- T0 sink
class _Gate:
    __slots__ = ("enabled", "known_names_sha256")

    def __init__(self, enabled, known_names_sha256):
        self.enabled, self.known_names_sha256 = enabled, known_names_sha256


class _StdSink:
    """T0 pre-effects sink.  Each method returns None or the caught exception,
    never a bare boolean."""

    def __init__(self, out, err):
        self._out, self._err = out, err

    def _emit(self, stream, obj):
        try:
            stream.write(_serialize(obj).decode("utf-8", "replace") + "\n")
            stream.flush()
            return None
        except BaseException as error:
            return error

    def emit_stdout_line(self, obj):
        return self._emit(self._out, obj)

    def emit_stderr_line(self, obj):
        return self._emit(self._err, obj)


# ---------------------------------------------------------------- T1 / T2 adapters
class RealReadFS:
    """Read-only adapter over an injected os module (reads, lstat, listing)."""

    def __init__(self, os_module):
        self._os = os_module

    def read_bytes(self, path, limit):
        """Whole regular file (O_NOFOLLOW).  With a limit, reading stops as
        soon as more than `limit` bytes were seen; the caller rejects the
        over-long result."""
        o = self._os
        fd = o.open(path, o.O_RDONLY | o.O_NOFOLLOW | o.O_CLOEXEC)
        first, chunks, total = None, [], 0
        try:
            while limit is None or total <= limit:
                chunk = o.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        except BaseException as error:
            first = error
        try:
            o.close(fd)                           # exactly once, never retried
        except BaseException as error:
            if first is None:
                first = error
        if first is not None:
            raise first
        return b"".join(chunks)

    def lstat(self, path):
        """Tri-state: ("PRESENT", None) | ("ENOENT", None) | ("ERROR", errno)."""
        try:
            self._os.lstat(path)
        except OSError as error:
            if error.errno == errno.ENOENT:
                return ("ENOENT", None)
            return ("ERROR", error.errno)
        return ("PRESENT", None)

    def realpath(self, path):
        return self._os.path.realpath(path)

    def isdir(self, path):
        return self._os.path.isdir(path)

    def listdir(self, path):
        return self._os.listdir(path)


class RealWriteFS:
    """Write adapter over an injected os module.  Never retries, never
    unlinks, never overwrites."""

    def __init__(self, os_module):
        self._os = os_module

    def create_exclusive(self, path, data, progress):
        """O_EXCL create, full write, fsync file, close (once), fsync directory.
        `progress` is the caller-owned record (stage, fd_obtained, ...) stored
        by the caller BEFORE this call.  A failure of the open is raised
        unchanged with fd_obtained False (the caller decides by lstat); any
        later failure raises PublishFailure (or re-raises a BaseException)
        carrying the FIRST error and, separately, a close failure."""
        o = self._os
        progress.update(path=path, stage="OPEN", fd_obtained=False, fd_state="NO_FD",
                        close_error=None, first_error=None)
        fd = o.open(path, o.O_WRONLY | o.O_CREAT | o.O_EXCL | o.O_NOFOLLOW | o.O_CLOEXEC,
                    CREATE_MODE)
        progress["fd_obtained"] = True
        progress.update(stage="WRITE", fd_state="OPEN")
        first = None
        try:
            view = memoryview(data)
            while view:
                written = o.write(fd, view)
                if written <= 0:
                    raise OSError("SHORT_WRITE")
                view = view[written:]
            progress["stage"] = "FSYNC"
            o.fsync(fd)
            progress["stage"] = "CLOSE"
        except BaseException as error:
            first = error
        try:
            o.close(fd)                           # exactly once, never retried
            progress["fd_state"] = "CLOSED"
        except BaseException as error:
            progress["fd_state"] = "CLOSE_FAILED_FD_STATE_UNCERTAIN_NOT_RETRIED"
            progress["close_error"] = _describe(error)
            if first is None:
                first = error
        if first is not None:
            _raise_first(first, progress)
        progress["stage"] = "DIR_FSYNC"           # complete bytes written and closed
        try:
            self.fsync_dir(os.path.dirname(path))
        except BaseException as error:
            _raise_first(error, progress)
        progress["stage"] = "DONE"
        return progress

    def mkdir(self, path, mode):
        self._os.mkdir(path, mode)

    def fsync_dir(self, path):
        o = self._os
        dfd = o.open(path, o.O_RDONLY | o.O_DIRECTORY | o.O_CLOEXEC)
        first = None
        try:
            o.fsync(dfd)
        except BaseException as error:
            first = error
        try:
            o.close(dfd)
        except BaseException as error:
            if first is None:
                first = error
        if first is not None:
            raise first


class RealProcessPort:
    """The only spawn site.  Binary pipes, own session, no shell."""

    def __init__(self, popen):
        self.Popen = popen

    def spawn_child(self, argv):
        return self.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=False, bufsize=-1, shell=False,
                          start_new_session=True, close_fds=True)


class ReadDeps:
    """T1: read fs, wall `now`, two values, the PathFinder and the load plan
    (pure data).  No write/mkdir/fsync method, no process port, no builder."""

    def __init__(self, read_fs, now, executable_realpath, path_finder, harness_path,
                 plan=None):
        self.read_fs, self.now = read_fs, now
        self.executable_realpath, self.path_finder = executable_realpath, path_finder
        self.harness_path = harness_path
        self.plan = PRODUCTION_PLAN if plan is None else plan


class EffectDeps:
    """T2: write fs, process port, monotonic clock, sleep, the native ports
    builder callable and the import-session class.  No sink, no refusal path."""

    def __init__(self, write_fs, process_port, clock, sleep, native_ports_builder,
                 session_factory=None):
        self.write_fs, self.process_port = write_fs, process_port
        self.clock, self.sleep = clock, sleep
        self.native_ports_builder = native_ports_builder
        self.session_factory = PinnedImportSession if session_factory is None \
            else session_factory


def _build_read_deps():
    return ReadDeps(RealReadFS(os), time.time, os.path.realpath(sys.executable),
                    importlib.machinery.PathFinder, os.path.realpath(__file__))


def _build_effect_deps(approval, read_deps):
    return EffectDeps(RealWriteFS(os), RealProcessPort(subprocess.Popen), time.monotonic,
                      time.sleep, _production_native_ports_builder)


# ---------------------------------------------------------------- native ports seam
class NativePortsBuilder:
    """Binds the reviewed port through its public build_native_entry.
    `adapter_cls` is the sys_ports class (constructor argument: no frozen byte
    changes, no monkeypatching).  Construction builds no sys_ports object and
    makes no p18 call: the factory runs inside run_context_factory."""

    def __init__(self, mods, p18_modules, process_port, clock, sleep, adapter_cls):
        self.controller = mods["stage_b_controller"]
        self.journal = mods["stage_b_dispatch_journal"]
        self.process_port, self.adapter_cls = process_port, adapter_cls
        linux_entry = mods["linux_entry"]
        p18 = tuple(p18_modules)
        self.entry = mods["native_root_port"].build_native_entry(
            self.controller, mods["termination"], linux_entry, lambda: adapter_cls(*p18),
            INERT_SAMPLER, clock, sleep, opt_in=linux_entry.OPT_IN, run_id=NATIVE_RUN_ID,
            generation=NATIVE_GENERATION, owner=NATIVE_OWNER)

    def new_context(self):
        return self.entry.run_context_factory(INERT_SAMPLER)

    def spawn_child(self, argv):
        return self.process_port.spawn_child(argv)

    def effect_evidence(self, process, context):
        return self.controller._effect_evidence(process, context)

    def validate_effect(self, effect):
        return self.journal.validate_effect_evidence(effect)   # pure validator, no storage


def _production_native_ports_builder(mods, p18_modules, process_port, clock, sleep):
    """The sole production NativePortsBuilder construction."""
    return NativePortsBuilder(mods, p18_modules, process_port, clock, sleep,
                              adapter_cls=mods["native_root_port"].P18SysPorts)


# ---------------------------------------------------------------- authorization
def _real_abs(rfs, value, field, must_exist_dir=False):
    if type(value) is not str or not value or not os.path.isabs(value):
        raise Refused("PATH_NOT_ABSOLUTE", field)
    if os.path.normpath(value) != value or rfs.realpath(value) != value:
        raise Refused("PATH_NOT_NORMALIZED_REAL", field)
    if must_exist_dir and not rfs.isdir(value):
        raise Refused("PATH_NOT_EXISTING_DIRECTORY", field)
    return value


def verify_files(rfs, root, files, error_cls):
    """Re-reads every pinned file; returns {relpath: bytes}.  Used at
    authorization (all candidate_files), at load (served set: the bytes that
    are compiled) and at the final decision (served set)."""
    verified = {}
    for rel in sorted(files):
        data = rfs.read_bytes(os.path.join(root, rel), None)
        if sha256_bytes(data) != files[rel]:
            raise error_cls("CANDIDATE_FILE_HASH_MISMATCH", rel)
        verified[rel] = data
    return verified


def check_authorization(argv, gate, read_deps):
    """Checks 1-21 in this fixed order.  Reads only (T1); raises Refused
    before any write or effect.  Returns (approval, attempt_id, run_dir)."""
    rfs, plan = read_deps.read_fs, read_deps.plan
    # 1 arguments
    flags, values = list(argv[1::2]), list(argv[2::2])
    if len(argv) != 7 or len(set(flags)) != 3 \
            or set(flags) != {"--approval", "--run-dir", "--attempt-id"}:
        raise Refused("ARGUMENTS")
    args = dict(zip(flags, values))
    attempt_id, run_dir = args["--attempt-id"], args["--run-dir"]
    # 2 attempt id (fullmatch)
    if type(attempt_id) is not str or not ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise Refused("ATTEMPT_ID_INVALID")
    # 3-4 approval path, 5 bounded read, 6 strict JSON
    approval_path = _real_abs(rfs, args["--approval"], "--approval")
    try:
        approval_bytes = rfs.read_bytes(approval_path, MAX_APPROVAL_BYTES)
    except Exception as error:
        raise Refused("APPROVAL_UNREADABLE", _describe(error)["text"])
    if len(approval_bytes) > MAX_APPROVAL_BYTES:
        raise Refused("APPROVAL_TOO_LARGE")
    try:
        approval = _strict_json(approval_bytes)
    except Exception as error:
        raise Refused("APPROVAL_JSON", _describe(error)["text"])
    # 7-10 schema, enabled, fields, attempt
    if type(approval) is not dict or approval.get("schema") != APPROVAL_SCHEMA:
        raise Refused("APPROVAL_SCHEMA")
    if approval.get("enabled") is not True:
        raise Refused("APPROVAL_DISABLED")
    for field in REQUIRED_APPROVAL_FIELDS:
        if approval.get(field) in (None, "", [], {}):
            raise Refused("APPROVAL_FIELD_MISSING", field)
    if approval["attempt_id"] != attempt_id:
        raise Refused("ATTEMPT_ID_MISMATCH")
    # 11 time window: integer UTC unix seconds, bounded, finite injected wall clock
    t0, t1 = approval["approved_utc"], approval["expires_utc"]
    if type(t0) is not int or type(t1) is not int or not 0 < t0 < t1 \
            or t1 - t0 > MAX_WINDOW_SECONDS:
        raise Refused("TIME_WINDOW", "FIELDS")
    now = read_deps.now()
    if type(now) not in (int, float) or not math.isfinite(now) or not t0 <= now < t1:
        raise Refused("TIME_WINDOW", "STALE_OR_NOT_YET_VALID")
    # 12 paths: absolute, normalized, symlink-free; fresh run dir; independent roots
    ledger = _real_abs(rfs, approval["consumption_ledger_dir"], "consumption_ledger_dir", True)
    cand = _real_abs(rfs, approval["candidate_root"], "candidate_root", True)
    interp = _real_abs(rfs, approval["interpreter"], "interpreter")
    if type(run_dir) is not str or not os.path.isabs(run_dir) \
            or os.path.normpath(run_dir) != run_dir or run_dir != approval["run_dir"]:
        raise Refused("RUN_DIR_MISMATCH")
    parent = _real_abs(rfs, os.path.dirname(run_dir), "run_dir_parent", True)
    if rfs.lstat(run_dir)[0] != "ENOENT" or os.path.basename(run_dir) in rfs.listdir(parent):
        raise Refused("RUN_DIR_NOT_FRESH_OR_UNKNOWN", run_dir)
    protected = approval["protected_roots"]
    if type(protected) is not list:
        raise Refused("PROTECTED_ROOTS_TYPE")
    protected = [_real_abs(rfs, p, "protected_roots", True) for p in protected]
    for name, path in (("run_dir", run_dir), ("ledger", ledger)):
        for root in protected:
            if _inside(path, root):
                raise Refused("PATH_INSIDE_PROTECTED_ROOT", "%s:%s" % (name, root))
    harness_path = read_deps.harness_path
    if (_inside(run_dir, ledger) or _inside(ledger, run_dir) or _inside(run_dir, cand)
            or _inside(ledger, cand) or _inside(cand, run_dir) or _inside(cand, ledger)
            or _inside(parent, ledger) or _inside(harness_path, cand)):
        raise Refused("ROOTS_NOT_INDEPENDENT")
    # 13 interpreter, 14 effects
    if read_deps.executable_realpath != interp:
        raise Refused("INTERPRETER_MISMATCH")
    if approval["effects"] != list(EXPECTED_EFFECTS):
        raise Refused("EFFECTS_MISMATCH")
    if approval["forbidden_effects_acknowledged"] != list(FORBIDDEN_EFFECTS):
        raise Refused("FORBIDDEN_EFFECTS_NOT_ACKNOWLEDGED")
    # 15 declared known-but-unserved names: exact list hash-bound to the gate,
    # then the canonical set semantics (served / declared / lazy disjoint)
    names = approval["known_unserved_candidate_names"]
    if type(names) is not list or not all(type(n) is str and NAME_RE.fullmatch(n)
                                          for n in names) \
            or names != sorted(set(names)) or names_sha256(names) != gate.known_names_sha256:
        raise Refused("KNOWN_UNSERVED_NAMES_MISMATCH")
    try:
        refusal_universe(plan, names)
    except Stop as error:
        raise Refused(error.code, error.detail)
    # 16 harness self-hash, 17-20 candidate pins
    if sha256_bytes(rfs.read_bytes(harness_path, None)) != approval["harness_sha256"]:
        raise Refused("HARNESS_HASH_MISMATCH")
    files = approval["candidate_files"]
    if type(files) is not dict or not all(_safe_relpath(r) for r in files) \
            or not set(plan["served"]) | set(plan["lazy_refused"]) <= set(files):
        raise Refused("CANDIDATE_FILES_INCOMPLETE")
    if manifest_sha256(files) != approval["candidate_manifest_sha256"]:
        raise Refused("CANDIDATE_MANIFEST_MISMATCH")
    if files[plan["port_module_relpath"]] != approval["port_module_sha256"]:
        raise Refused("PORT_MODULE_PIN_MISMATCH")
    verify_files(rfs, cand, files, Refused)
    # 21 marker inspection (tri-state lstat only)
    _marker_precheck(rfs, os.path.join(ledger, attempt_id + ".CONSUMED"), attempt_id)
    approval["_approval_sha256"] = sha256_bytes(approval_bytes)
    return approval, attempt_id, run_dir


def _marker_precheck(rfs, marker, attempt_id):
    state, error_number = rfs.lstat(marker)
    if state == "PRESENT":
        raise Refused("ATTEMPT_ALREADY_CONSUMED", attempt_id, "ALREADY_SPENT_PRIOR_RUN")
    if state != "ENOENT":
        raise Refused("LEDGER_MARKER_STATE_UNKNOWN", "errno=%s" % error_number,
                      note="not retryable")


# ---------------------------------------------------------------- consume
class _AttemptRecord:
    """Caller-owned create-boundary record: `progress` is stored here BEFORE
    create_exclusive is called."""

    def __init__(self):
        self.marker_path, self.progress, self.boundary_crossed = None, None, False


def consume_attempt(record, approval, attempt_id, read_deps, deps):
    marker = os.path.join(approval["consumption_ledger_dir"], attempt_id + ".CONSUMED")
    _marker_precheck(read_deps.read_fs, marker, attempt_id)        # pre-create re-check
    payload = _serialize({"attempt_id": attempt_id, "harness_id": HARNESS_ID,
                          "harness_sha256": approval["harness_sha256"],
                          "approval_sha256": approval["_approval_sha256"],
                          "consumed_unix": int(read_deps.now())})
    record.marker_path = marker
    record.progress = {"stage": "NOT_STARTED", "fd_obtained": False}
    record.boundary_crossed = True        # create boundary: decided by progress + lstat
    deps.write_fs.create_exclusive(marker, payload, record.progress)
    return marker


def _after_boundary(sink, record, read_deps, error, attempt_id):
    """Rows 6-10 of the attempt-state table.  Never retries, never deletes."""
    progress = record.progress
    if progress.get("fd_obtained") is True:                                    # row 9
        return _stop_without_lifecycle(sink, attempt_id, record, error, True, "SPENT_THIS_RUN",
                                       "CONSUMPTION_MARKER_INCOMPLETE_ATTEMPT_SPENT")
    if isinstance(error, FileExistsError):                                     # row 6
        return _refuse(sink, "ATTEMPT_ALREADY_CONSUMED", attempt_id, "ALREADY_SPENT_PRIOR_RUN",
                       effects="MARKER_CREATE_ATTEMPTED_O_EXCL_NOTHING_CREATED_BY_THIS_RUN")
    try:
        state = read_deps.read_fs.lstat(record.marker_path)[0]
    except BaseException:
        state = "ERROR"
    if state == "ENOENT":                                                      # row 7
        return _refuse(sink, "LEDGER_UNWRITABLE_NOTHING_CREATED", _describe(error)["text"],
                       "UNSPENT_CONFIRMED_ABSENT", note="not retried",
                       effects="MARKER_CREATE_ATTEMPTED_NOTHING_CREATED")
    if state == "PRESENT":                                                     # row 8
        return _stop_without_lifecycle(sink, attempt_id, record, error, "UNKNOWN",
                                       "POSSIBLY_SPENT_THIS_RUN",
                                       "CONSUMPTION_MARKER_PRESENT_ORIGIN_UNKNOWN")
    return _stop_without_lifecycle(sink, attempt_id, record, error, "UNKNOWN",        # row 10
                                   "POSSIBLY_SPENT_THIS_RUN",
                                   "CONSUMPTION_MARKER_STATE_UNKNOWN_POSSIBLY_SPENT")


def _refuse(sink, code, detail, attempt_state, note=None, effects="NONE"):
    line = {"refused": code, "effects": effects, "spent_by_this_run": False,
            "attempt_state": attempt_state}
    if detail:
        line["detail"] = str(detail)
    if note:
        line["note"] = note
    sink.emit_stdout_line(line)
    return EXIT_REFUSED


def _stop_without_lifecycle(sink, attempt_id, record, error, spent, attempt_state, code):
    primary = dict(_describe(error), phase="CONSUME", code=code)
    stop = {"record": "NRP3_STDERR_STOP_RECORD", "schema": EVIDENCE_SCHEMA,
            "attempt_id": attempt_id, "verdict": "STOP", "exit_code": EXIT_STOP,
            "pass_meaning": None, "spent_by_this_run": spent, "attempt_state": attempt_state,
            "primary": primary, "secondary": [],
            "marker": {"path": record.marker_path, "progress": dict(record.progress)},
            "receipt_rule": RECEIPT_RULE}
    stderr_error = sink.emit_stderr_line(stop)
    receipt = {"schema": RECEIPT_SCHEMA, "record": "NRP3_CANARY_FINAL_RECEIPT",
               "attempt_id": attempt_id, "verdict": "STOP", "exit": EXIT_STOP,
               "spent_by_this_run": spent, "attempt_state": attempt_state,
               "evidence_file": {"path": None, "state": "NOT_ATTEMPTED", "sha256": None},
               "superseded_file": None,
               "stderr_stop_record": "WRITTEN" if stderr_error is None
               else {"state": "FAILED", "error": _describe(stderr_error)},
               "primary": primary, "secondary_count": 0,
               "loader_lifetime": "NO_LOADER_INSTALLED",
               "authority": "THIS_RECEIPT_PLUS_EXIT_CODE"}
    _emit_receipt(sink, receipt, None, "NOT_ATTEMPTED", None)
    return EXIT_STOP


def _emit_receipt(sink, receipt, path, file_state, attempted_sha):
    """Returns None or the receipt write error.  On failure: one best-effort
    stderr note carrying the full unwritten receipt body; nothing more."""
    error = sink.emit_stdout_line(receipt)
    if error is not None:
        sink.emit_stderr_line({
            "record": "NRP3_RECEIPT_WRITE_FAILED", "verdict": "STOP", "exit": EXIT_STOP,
            "error": _describe(error), "unwritten_receipt": receipt,
            "spent_by_this_run": receipt["spent_by_this_run"],
            "attempt_state": receipt["attempt_state"],
            "evidence_file_superseded": {"path": path, "state": file_state,
                                         "attempted_sha256": attempted_sha}})
    return error


# ---------------------------------------------------------------- pinned import session
class PinnedImportSession(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Lifetime owner of the pinned loader.  install() puts it at
    sys.meta_path[0] before the first candidate import; it is never removed
    (there is no removal method) and candidate modules stay in sys.modules
    until process exit.

    find_spec order: (1) served name -> spec over the verified bytes;
    (2) a name whose TOP label is in the refusal universe (declared list +
    lazy-refused, see refusal_universe()) or is a served name used as a
    package ("served.sub") -> ImportError raised BEFORE any normal finder
    runs, recorded in refusals; (3) any other name, top-level or qualified:
    the injected path_finder locates it WITHOUT executing (sys.path for a
    top-level name, the parent package path for a qualified one); an origin
    or search location under candidate_root, or one that cannot be decided,
    is refused the same way; (4) otherwise None (stdlib).  A later label of
    a qualified name is NOT matched against the universe (stdlib submodules
    may share such names); that case is covered by (3) only.  Not a sandbox."""
    nrp3_pinned_session = True
    loader_lifetime = LOADER_LIFETIME

    def __init__(self, root, verified, refused_names, path_finder, read_fs,
                 expected_sys_path_inserts):
        self.root, self.path_finder, self.read_fs = root, path_finder, read_fs
        self.expected_inserts = [os.path.join(root, rel) for rel in expected_sys_path_inserts]
        self.sources, self.origins = {}, {}
        for rel in sorted(verified):
            name = _module_name(rel)
            if name in self.sources:
                raise Stop("CANDIDATE_BASENAME_COLLISION", name)
            self.sources[name], self.origins[name] = verified[rel], os.path.join(root, rel)
        overlap = sorted(set(self.sources) & set(refused_names))
        if overlap:
            raise Stop("SERVED_AND_REFUSED_OVERLAP", ",".join(overlap))
        self.refused_names = frozenset(refused_names)
        self.installed, self.executed, self.refusals = False, [], []
        self.sys_path_before = self.sys_path_after = self.meta_path_before = None
        self.end_reports = []

    def install(self):
        if any(getattr(finder, "nrp3_pinned_session", False) for finder in sys.meta_path):
            raise Stop("IMPORT_SESSION_ALREADY_INSTALLED")
        preloaded = sorted((set(self.sources) | self.refused_names) & set(sys.modules))
        if preloaded:
            raise Stop("CANDIDATE_MODULE_PRELOADED", ",".join(preloaded))
        foreign = self.origin_violations()
        if foreign:
            raise Stop("CANDIDATE_ORIGIN_MODULE_PRELOADED", ",".join(foreign))
        self.sys_path_before = list(sys.path)
        self.meta_path_before = [type(f).__name__ for f in sys.meta_path]
        sys.meta_path.insert(0, self)
        self.installed = True

    def load_entries(self, names):
        """Import the entry modules through sys.meta_path (this session first)."""
        mods = {}
        for name in names:
            mods[name] = importlib.import_module(name)
        return mods

    def _under_root(self, filename):
        try:
            return _inside(self.read_fs.realpath(filename), self.root)
        except BaseException:
            return True                               # undecidable: treated as candidate

    def _refuse(self, name, code):
        self.refusals.append(name)
        raise ImportError("%s:%s" % (code, name), name=name)

    def find_spec(self, name, path=None, target=None):
        if name in self.sources:
            return importlib.util.spec_from_file_location(name, self.origins[name], loader=self)
        top = name.partition(".")[0]
        if top in self.refused_names or top in self.sources:
            self._refuse(name, "NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED")
        spec = self.path_finder.find_spec(name, path)     # locate only, never execute
        where = []
        if spec is not None:
            where = [spec.origin] if isinstance(spec.origin, str) else []
            where += list(spec.submodule_search_locations or [])
        if any(self._under_root(p) for p in where):
            self._refuse(name, "NRP3_UNKNOWN_CANDIDATE_LOCATION_REFUSED")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        self.executed.append(name)
        exec(compile(self.sources[name], self.origins[name], "exec", dont_inherit=True),
             module.__dict__)

    def origin_violations(self):
        """Every sys.modules entry whose file/origin realpath lies under
        candidate_root must have been served by THIS session from its pinned
        origin.  Detection after execution only."""
        bad = []
        for name, mod in list(sys.modules.items()):
            spec = getattr(mod, "__spec__", None)
            filename = getattr(mod, "__file__", None) or getattr(spec, "origin", None)
            if not isinstance(filename, str) or not self._under_root(filename):
                continue
            if getattr(spec, "loader", None) is not self or name not in self.sources \
                    or filename != self.origins[name]:
                bad.append(name)
        return sorted(bad)

    def end_check(self):
        """Complete end-check (position, refusals, origin sweep, sys.path delta).
        Raises Stop on any problem; every report is kept."""
        self.sys_path_after = list(sys.path)
        new = [p for p in self.sys_path_after if p not in self.sys_path_before]
        removed = [p for p in self.sys_path_before if p not in self.sys_path_after]
        at_zero = bool(sys.meta_path) and sys.meta_path[0] is self
        problems = []
        if not at_zero:
            problems.append("LOADER_NOT_AT_META_PATH_0")
        if self.refusals:
            problems.append("REFUSED_IMPORTS:" + ",".join(self.refusals))
        bad = self.origin_violations()
        if bad:
            problems.append("UNPINNED_CANDIDATE_ORIGIN:" + ",".join(bad))
        if removed:
            problems.append("SYS_PATH_ENTRY_REMOVED")
        if [p for p in new if p not in self.expected_inserts]:
            problems.append("SYS_PATH_UNEXPECTED_INSERT")
        report = {"index": len(self.end_reports) + 1, "problems": problems,
                  "loader_at_meta_path_0": at_zero, "sys_path_new": new,
                  "sys_path_removed": removed, "origin_violations": bad,
                  "loader_lifetime": LOADER_LIFETIME,
                  "meaning": "DETECTION_AFTER_EXECUTION_NOT_PREVENTION"}
        self.end_reports.append(report)
        if problems:
            raise Stop("IMPORT_END_CHECK_FAILED", ";".join(problems))
        return report

    def report(self):
        return {"installed": self.installed, "executed": list(self.executed),
                "refusals": list(self.refusals), "served": sorted(self.sources),
                "refused_names_count": len(self.refused_names),
                "refused_names_sha256": names_sha256(self.refused_names),
                "sys_path_before": self.sys_path_before,
                "sys_path_after": self.sys_path_after,
                "meta_path_before": self.meta_path_before,
                "end_reports": list(self.end_reports), "loader_lifetime": LOADER_LIFETIME}


def load_candidate_modules(life):
    """Re-verify the harness and the served set, own + install the session,
    import the entry modules through it, sweep origins once (detection)."""
    a, rd = life.approval, life.read_deps
    plan = rd.plan
    if sha256_bytes(rd.read_fs.read_bytes(rd.harness_path, None)) != a["harness_sha256"]:
        raise Stop("HARNESS_HASH_MISMATCH_AT_LOAD")
    files = {rel: a["candidate_files"][rel] for rel in plan["served"]}
    verified = verify_files(rd.read_fs, a["candidate_root"], files, Stop)
    refused = refusal_universe(plan, a["known_unserved_candidate_names"])
    life.session = life.deps.session_factory(
        a["candidate_root"], verified, refused, rd.path_finder, rd.read_fs,
        plan["expected_sys_path_inserts"])
    life.session.install()
    mods = life.session.load_entries(tuple(plan["entry_imports"])
                                     + tuple(plan["p18_entry_imports"]))
    bad = life.session.origin_violations()
    if bad or life.session.refusals:
        raise Stop("CANDIDATE_MODULE_ORIGIN", ",".join(bad + list(life.session.refusals)))
    return mods


# ---------------------------------------------------------------- lifecycle
class Lifecycle:
    """Ownership record for one consumed attempt.  primary is the first failure
    recorded in ANY phase and is never overwritten; later ones are secondary."""

    def __init__(self, attempt_id, approval, read_deps, deps, sink, run_dir):
        self.attempt_id, self.approval = attempt_id, approval
        self.read_deps, self.deps, self.sink, self.run_dir = read_deps, deps, sink, run_dir
        self.phase, self.primary, self.secondary = "START", None, []
        self.run_dir_created = False
        self.ports = self.context = self.process = self.session = None
        self.first_close_called = False
        self.child_row = self.context_row = None
        # Finite record of what this harness itself did/observed (R6): written
        # in the statement where the knowledge changes, never by inspection.
        self.custody = {"spawn_state": "NOT_CALLED",
                        "child": {"pid": None, "state": "NO_CHILD_KNOWN"},
                        "pipes": {"stdin": "NOT_CREATED", "stdout": "NOT_CREATED"},
                        "context": "NOT_CREATED", "wait_error": None}
        self.publish_progress = None
        self.inert_baseline = len(INERT_SAMPLER.accessed)
        plan = read_deps.plan
        declared = approval["known_unserved_candidate_names"]
        self.ev = {"schema": EVIDENCE_SCHEMA, "harness_id": HARNESS_ID,
                   "attempt_id": attempt_id, "phases": [], "outcomes": {},
                   "checks": {}, "not_exercised": list(NOT_EXERCISED),
                   "not_certified": list(NOT_CERTIFIED),
                   "unresolved_ownership": [], "custody": self.custody,
                   "spent_by_this_run": True, "attempt_state": "SPENT_THIS_RUN",
                   "loader_lifetime": LOADER_LIFETIME,
                   "inert_sampler": INERT_SAMPLER_LABEL,
                   "dispatch_permission": "NONE", "init_reaping_observed": False,
                   "receipt_rule": RECEIPT_RULE,
                   "pins": {"approval_sha256": approval["_approval_sha256"],
                            "harness_sha256": approval["harness_sha256"],
                            "candidate_manifest_sha256": approval["candidate_manifest_sha256"],
                            "port_module_sha256": approval["port_module_sha256"],
                            "served_set": list(plan["served"]),
                            "lazy_refused": list(plan["lazy_refused"]),
                            "refusal_universe": {
                                "declared_count": len(declared),
                                "declared_sha256": names_sha256(declared),
                                "lazy_refused_names": sorted(
                                    _module_name(rel) for rel in plan["lazy_refused"]),
                                "total_count": len(declared) + len(plan["lazy_refused"]),
                                "rule": REFUSAL_UNIVERSE_RULE}}}

    def enter(self, phase):
        self.phase = phase
        self.ev["phases"].append({"phase": phase, "mono": self.deps.clock()})

    def failures(self):
        return (0 if self.primary is None else 1) + len(self.secondary)

    def fail(self, error, phase=None):
        record = dict(_describe(error), phase=phase or self.phase)
        if self.primary is None:
            self.primary = record
        else:
            self.secondary.append(record)

    def own(self, resource, **fields):
        """Register an unresolved-ownership row BEFORE the call that could
        lose track of the resource.  Returns the row (refined in place)."""
        row = dict(fields, resource=resource)
        self.ev["unresolved_ownership"].append(row)
        return row

    def release(self, row):
        """Drop a row (identity match) -- only on a confirmed release."""
        rows = self.ev["unresolved_ownership"]
        rows[:] = [r for r in rows if r is not row]

    def reaped(self, returncode, how):
        """Confirmed reap = a non-None returncode produced by a call that
        RETURNED.  Anything else leaves the child row registered."""
        if returncode is None:
            return False
        self.custody["child"]["state"] = "%s:%s" % (how, returncode)
        self.release(self.child_row)
        self.child_row = None
        return True

    def context_closed(self, outcome):
        """Refine the context row only on a RETURNED close outcome; release
        it only on "CLOSED"."""
        self.custody["context"] = "CLOSE_RETURNED:%s" % (outcome,)
        if outcome == "CLOSED":
            self.release(self.context_row)
            self.context_row = None
        elif self.context_row is not None:
            self.context_row["state"] = "CLOSE_RETURNED_NOT_CLOSED:%s" % (outcome,)
        return outcome

    def guarded(self, name, fn):
        """One cleanup/report/finish step.  Any BaseException goes through
        fail(): primary if it is the first failure anywhere, secondary
        otherwise.  Catching it here completes no ownership: rows registered
        before the step stay registered."""
        try:
            self.ev["outcomes"][name] = fn()
        except BaseException as error:
            self.ev["outcomes"][name] = "RAISED"
            self.fail(error, "GUARDED:" + name)


def run_lifecycle(life):
    """Normal path.  Every acquired resource is stored on `life` in the same
    statement that obtains it, so cleanup sees it even if the next statement
    raises."""
    a, deps = life.approval, life.deps
    life.enter("RUN_DIR")
    deps.write_fs.mkdir(life.run_dir, RUN_DIR_MODE)
    life.run_dir_created = True
    deps.write_fs.fsync_dir(os.path.dirname(life.run_dir))
    life.enter("LOAD_MODULES")
    mods = load_candidate_modules(life)
    life.enter("BUILD_PORTS")
    p18_modules = tuple(mods[name] for name in life.read_deps.plan["p18_entry_imports"])
    life.ports = deps.native_ports_builder(mods, p18_modules, deps.process_port,
                                           deps.clock, deps.sleep)
    life.enter("NEW_CONTEXT")
    life.custody["context"] = "NEW_CONTEXT_CALLED_OUTCOME_UNKNOWN"
    life.context = life.ports.new_context()
    life.custody["context"] = "CREATED_CLOSE_NOT_CALLED"
    life.context_row = life.own("native_context", state="CREATED_CLOSE_NOT_CONFIRMED")
    life.enter("ADMIT")
    life.context.admit()
    life.enter("SPAWN")
    # R1: from here until spawn_child RETURNS a process object the outcome is
    # unknown.  No exception type (OSError, ValueError, TypeError, ...) is
    # taken as proof that no child exists: the port offers no operation-bound
    # no-effect evidence, so the row below is refined only by a returned object.
    custody = life.custody
    custody["spawn_state"] = "CALLED_OUTCOME_UNKNOWN"
    custody["pipes"] = {"stdin": "SPAWN_OUTCOME_UNKNOWN", "stdout": "SPAWN_OUTCOME_UNKNOWN"}
    life.child_row = life.own("possible unrecorded child", pid=None,
                              state="SPAWN_OUTCOME_UNKNOWN_NO_WAIT_ON_UNKNOWN_PID")
    life.process = life.ports.spawn_child([a["interpreter"]] + list(CHILD_ARGV_TAIL))
    custody["spawn_state"] = "RETURNED"
    custody["pipes"] = {"stdin": "OPEN_HELD_BY_PARENT", "stdout": "OPEN_HELD_BY_PARENT"}
    life.child_row.update(resource="child_process", state="NOT_REAPED_NOTHING_SENT",
                          after_harness_exit="REPARENTED_REAPING_UNOBSERVED")
    custody["child"]["state"] = "NOT_REAPED_NOTHING_SENT"
    pid = life.process.pid
    life.child_row["pid"] = custody["child"]["pid"] = pid
    life.ev["outcomes"]["child_pid"] = pid
    life.enter("ATTACH_ROOT")
    life.context.attach_root(life.process)
    if life.context.root_authority_state != "ACQUIRED":
        raise Stop("ROOT_NOT_ACQUIRED_NO_FALLBACK", life.context.root_authority_state)
    life.enter("EFFECT_EVIDENCE")
    effect = life.ports.effect_evidence(life.process, life.context)
    life.ev["outcomes"]["effect"] = effect
    life.ports.validate_effect(effect)
    if effect.get("identity") is not None or effect.get("custody") != "REGISTERED":
        raise Stop("EFFECT_NOT_OPTION_B_SHAPE")
    life.enter("NATURAL_COMPLETION")
    custody["pipes"] = {"stdin": "COMMUNICATE_CALLED_OUTCOME_UNKNOWN",
                        "stdout": "COMMUNICATE_CALLED_OUTCOME_UNKNOWN"}
    out, _ = life.process.communicate(input=b"", timeout=COMMUNICATE_TIMEOUT_S)
    custody["pipes"] = {"stdin": "CLOSED_BY_COMMUNICATE", "stdout": "CLOSED_BY_COMMUNICATE"}
    life.reaped(life.process.returncode, "REAPED_BY_COMMUNICATE")
    life.ev["outcomes"]["stdin"] = "CLOSED_BY_COMMUNICATE"
    life.ev["outcomes"]["child_returncode"] = life.process.returncode
    life.ev["outcomes"]["child_stdout_len"] = len(out or b"")
    life.ev["outcomes"]["child_stdout"] = (out or b"")[:STDOUT_BOUND].decode(
        "ascii", "backslashreplace")
    life.enter("FIRST_CLOSE")
    life.first_close_called = True                 # cleanup never closes again
    custody["context"] = "CLOSE_CALLED_OUTCOME_UNKNOWN"
    first = life.context_closed(life.context.close(lock_timeout=CLOSE_LOCK_TIMEOUT_S))
    life.ev["outcomes"]["first_close"] = first
    if first != "CLOSED":
        raise Stop("FIRST_CLOSE_NOT_CLOSED", first)
    life.enter("SECOND_CLOSE_IDEMPOTENCE")         # only after a successful first close
    second = life.context.close(lock_timeout=CLOSE_LOCK_TIMEOUT_S)
    life.ev["outcomes"]["second_close"] = second
    if second != "ALREADY_CLOSED":
        raise Stop("SECOND_CLOSE_NOT_ALREADY_CLOSED", second)


def cleanup(life):
    """Single ownership-aware cleanup.  Signal-free: only the owned child is
    waited, with a bound.  The parent stdout read end is closed only after the
    child is reaped.  The child row was registered at SPAWN (before any
    interruptible call) and is released only by a wait that RETURNED a
    returncode; no step here guesses a pid, retries or sends anything."""
    proc, ctx = life.process, life.context
    custody = life.custody
    pipes = custody["pipes"]
    life.enter("CLEANUP")

    def close_stdin():
        if proc is None:
            return "NO_PROCESS"
        if proc.stdin is None or proc.stdin.closed:
            return "ALREADY_CLOSED"
        pipes["stdin"] = "CLOSE_CALLED_OUTCOME_UNKNOWN"
        proc.stdin.close()
        pipes["stdin"] = "CLOSED_BY_CLEANUP"
        return "CLOSED_BY_CLEANUP"

    def bounded_wait():
        if proc is None:
            if custody["spawn_state"] == "CALLED_OUTCOME_UNKNOWN":
                return "SPAWN_OUTCOME_UNKNOWN"     # row registered before the call (R1)
            return "NO_PROCESS"
        if proc.returncode is not None:
            if life.child_row is not None:          # not already confirmed earlier
                life.reaped(proc.returncode, "REAPED")
            return "REAPED:%s" % proc.returncode
        custody["child"]["state"] = "CLEANUP_WAIT_CALLED_OUTCOME_UNKNOWN"
        try:
            code = proc.wait(timeout=CLEANUP_WAIT_TIMEOUT_S)
        except BaseException as error:  # the row registered at SPAWN stays; nothing sent
            custody["wait_error"] = _describe(error)
            custody["child"]["state"] = "NOT_REAPED_WAIT_RAISED:%s" % type(error).__name__
            if not isinstance(error, Exception):
                raise                   # guarded() records it: not an ownership completion
            return "UNRESOLVED_CHILD_NOT_REAPED:%s" % type(error).__name__
        if not life.reaped(code, "REAPED_BY_CLEANUP_WAIT"):
            custody["child"]["state"] = "NOT_REAPED_WAIT_RETURNED_NONE"
            return "UNRESOLVED_CHILD_WAIT_RETURNED_NONE"
        return "REAPED_BY_CLEANUP_WAIT:%s" % code

    def close_stdout():
        if proc is None or proc.stdout is None or proc.stdout.closed:
            return "NO_OPEN_STDOUT"
        if proc.returncode is None:    # not reaped: no explicit close
            pipes["stdout"] = "LEFT_OPEN_CHILD_UNREAPED"
            life.own("parent_stdout_read_end", pid=proc.pid,
                     state="LEFT_OPEN_CHILD_UNREAPED",
                     released="BY_KERNEL_AT_HARNESS_EXIT_UNOBSERVED")
            return "LEFT_OPEN_CHILD_UNREAPED"
        pipes["stdout"] = "CLOSE_CALLED_OUTCOME_UNKNOWN"
        proc.stdout.close()
        pipes["stdout"] = "CLOSED_BY_CLEANUP"
        return "CLOSED_BY_CLEANUP"

    def close_context_once():
        if ctx is None:
            return "NO_CONTEXT"
        if life.first_close_called:
            return "NOT_CALLED_FIRST_CLOSE_ALREADY_ATTEMPTED"
        life.first_close_called = True
        custody["context"] = "CLOSE_CALLED_OUTCOME_UNKNOWN"
        return life.context_closed(ctx.close(lock_timeout=CLOSE_LOCK_TIMEOUT_S))

    life.guarded("cleanup_stdin", close_stdin)
    life.guarded("cleanup_wait", bounded_wait)
    life.guarded("cleanup_stdout", close_stdout)
    life.guarded("cleanup_context_close", close_context_once)
    life.guarded("context_state", lambda: None if ctx is None else {
        "root_authority_state": ctx.root_authority_state, "closed": ctx.closed,
        "custody": ctx.custody, "teardown_started": ctx.teardown_started,
        "evidence": list(ctx.evidence)})
    life.guarded("route_report", lambda: None if ctx is None
                 else ctx.termination.report())
    life.guarded("host_facts", lambda: {
        "sys_version": sys.version,
        "executable_realpath": life.read_deps.executable_realpath,
        "approved_interpreter": life.approval["interpreter"]})


def import_end_check_1(life):
    """end_check #1: after cleanup, immediately before final_decision."""
    session = life.session
    life.enter("IMPORT_END_CHECK_1")
    life.guarded("import_end_check_1", lambda: "NO_IMPORT_SESSION" if session is None
                 else session.end_check())


def final_decision(life):
    """PASS only if no failure record exists, every check is True and the
    harness + served-set pins still verify.  Every read of a guarded outcome is
    type-guarded: a 'RAISED' sentinel can never make this function fail."""
    life.enter("FINAL_DECISION")
    o, ev = life.ev["outcomes"], life.ev
    route = _dict(o.get("route_report"))
    counters = _dict(route.get("port_counters"))
    custody = _list(route.get("port_custody"))
    state = _dict(o.get("context_state"))
    effect = _dict(o.get("effect"))
    end1 = _dict(o.get("import_end_check_1"))
    for row in custody:
        if not isinstance(row, dict) or row.get("resolved") is not True:
            ev["unresolved_ownership"].append({
                "resource": "port_custody", "pid": _dict(row).get("pid"),
                "custody": _dict(row).get("custody"), "state": "PORT_CUSTODY_UNRESOLVED"})
    ev["checks"] = {
        "root_acquired": state.get("root_authority_state") == "ACQUIRED",
        "child_returncode_0": o.get("child_returncode") == 0
        and type(o.get("child_returncode")) is int,
        "stdout_marker": "NRP3_CHILD_DONE" in str(o.get("child_stdout", "")),
        "first_close_CLOSED": o.get("first_close") == "CLOSED",
        "second_close_ALREADY_CLOSED": o.get("second_close") == "ALREADY_CLOSED",
        "port_open_eq_1": counters.get("open") == 1,
        "port_close_eq_1": counters.get("close") == 1,
        "port_signal_refused_eq_0": counters.get("signal_refused") == 0,
        "port_custody_all_closed": bool(custody) and all(
            isinstance(r, dict) and r.get("custody") == "CLOSED" for r in custody),
        "effect_identity_none_custody_registered": "identity" in effect
        and effect.get("identity") is None and effect.get("custody") == "REGISTERED",
        "import_end_check_1_clean": bool(end1) and end1.get("problems") == [],
        "loader_retained_at_meta_path_0": end1.get("loader_at_meta_path_0") is True,
        "inert_sampler_untouched": not INERT_SAMPLER.accessed[life.inert_baseline:],
        "no_unresolved_ownership": not ev["unresolved_ownership"],
    }
    failed = [k for k in sorted(ev["checks"]) if ev["checks"][k] is not True]
    if life.primary is None and failed:            # only when no failure record exists
        life.fail(Stop("CHECK_FAILED", ",".join(failed)), "FINAL_DECISION")
    try:                                           # always recorded, PASS or STOP
        rd, a = life.read_deps, life.approval
        if sha256_bytes(rd.read_fs.read_bytes(rd.harness_path, None)) != a["harness_sha256"]:
            raise Stop("HARNESS_HASH_MISMATCH_AT_FINAL")
        verify_files(rd.read_fs, a["candidate_root"], {
            rel: a["candidate_files"][rel] for rel in rd.plan["served"]}, Stop)
        ev["final_pins_verified"] = True
    except BaseException as error:
        ev["final_pins_verified"] = False
        life.fail(error, "FINAL_PINS")
    passed = life.primary is None and not life.secondary
    ev["verdict"] = "PASS" if passed else "STOP"
    ev["pass_meaning"] = PASS_MEANING if passed else None
    ev["primary"], ev["secondary"] = life.primary, list(life.secondary)
    ev["exit_code"] = EXIT_PASS if passed else EXIT_STOP
    return ev["exit_code"]


def _to_stop(life):
    ev = life.ev
    ev["verdict"], ev["exit_code"], ev["pass_meaning"] = "STOP", EXIT_STOP, None
    ev["primary"], ev["secondary"] = life.primary, list(life.secondary)


def _evidence_file_state(rfs, path, error, progress, run_dir_created):
    if not run_dir_created:
        return "NOT_CREATED_NO_RUN_DIR"
    if isinstance(error, FileExistsError) and _dict(progress).get("fd_obtained") is not True:
        return "PREEXISTING_NOT_WRITTEN_BY_THIS_RUN"
    try:
        state = rfs.lstat(path)[0]
    except BaseException:
        state = "ERROR"
    if state == "ENOENT":
        return "NOT_CREATED"
    if state != "PRESENT":
        return "UNKNOWN_INSPECTION_FAILED"
    if _dict(progress).get("stage") == "DIR_FSYNC":
        return "PRESENT_COMPLETE_BYTES_DIR_FSYNC_FAILED"
    return "PRESENT_POSSIBLY_PARTIAL"


def stop_record_object(ev):
    """The stderr STOP record: the full evidence, or (above 1 MiB) a reduced
    fixed key set.  Always one valid JSON document, never cut mid-JSON."""
    record = dict(ev, record="NRP3_STDERR_STOP_RECORD")
    if len(_serialize(record)) > MAX_STDERR_RECORD_BYTES:
        record = {k: record.get(k) for k in STOP_RECORD_REDUCED_KEYS}
        record["reduced"] = True
        if len(_serialize(record)) > MAX_STDERR_RECORD_BYTES:
            record = {k: record.get(k) for k in (
                "record", "schema", "attempt_id", "verdict", "exit_code", "pass_meaning",
                "spent_by_this_run", "attempt_state", "receipt_rule")}
            record["reduced"] = "MINIMAL"
    return record


def publish(life):
    """Fixed order: end_check #2 -> (failure => STOP under the first-failure
    rule) -> serialize evidence -> create_exclusive(EVIDENCE.json) once (never
    overwritten, deleted or retried) -> stderr STOP record (STOP only) ->
    stdout receipt.  A PASS evidence file is never written when end_check #2
    fails."""
    ev, session = life.ev, life.session
    path = os.path.join(life.run_dir, "EVIDENCE.json")
    attempted_sha, file_state = None, "NOT_ATTEMPTED"
    life.enter("PUBLISH")
    life.enter("IMPORT_END_CHECK_2")
    before = life.failures()
    life.guarded("import_end_check_2", lambda: "NO_IMPORT_SESSION" if session is None
                 else session.end_check())
    life.guarded("import_report", lambda: None if session is None else session.report())
    if life.failures() != before:
        _to_stop(life)
    life.enter("SERIALIZE_EVIDENCE")
    progress = {"stage": "NOT_STARTED", "fd_obtained": False}
    life.publish_progress = progress
    try:
        data = _serialize(ev)
        attempted_sha = sha256_bytes(data)
        if not life.run_dir_created:
            raise Stop("NO_RUN_DIR")
        life.deps.write_fs.create_exclusive(path, data, progress)
        file_state = "COMPLETE_FSYNC_REQUESTED"
    except BaseException as error:
        life.fail(error, "EVIDENCE_PUBLISH")
        file_state = _evidence_file_state(life.read_deps.read_fs, path, error, progress,
                                          life.run_dir_created)
    if file_state != "COMPLETE_FSYNC_REQUESTED":
        _to_stop(life)
        ev["superseded_file"] = {
            "path": path, "state": file_state,
            "attempted_sha256": attempted_sha if file_state.startswith("PRESENT") else None,
            "rule": "any EVIDENCE.json at this path is PRELIMINARY and SUPERSEDED (it may say "
                    "PASS); this STOP record and the stdout receipt are authoritative"}
    stderr_record = "NOT_NEEDED"
    if ev["verdict"] != "PASS":
        stderr_error = life.sink.emit_stderr_line(stop_record_object(ev))
        stderr_record = "WRITTEN"
        if stderr_error is not None:
            stderr_record = {"state": "FAILED", "error": _describe(stderr_error)}
            life.fail(stderr_error, "STDERR_STOP_RECORD")
    receipt = {"schema": RECEIPT_SCHEMA, "record": "NRP3_CANARY_FINAL_RECEIPT",
               "attempt_id": life.attempt_id, "verdict": ev["verdict"],
               "exit": ev["exit_code"], "spent_by_this_run": True,
               "attempt_state": "SPENT_THIS_RUN",
               "evidence_file": {"path": path, "state": file_state,
                                 "sha256": attempted_sha
                                 if file_state == "COMPLETE_FSYNC_REQUESTED" else None},
               "superseded_file": ev.get("superseded_file"),
               "stderr_stop_record": stderr_record,
               "primary": life.primary, "secondary_count": len(life.secondary),
               "loader_lifetime": LOADER_LIFETIME,
               "authority": "THIS_RECEIPT_PLUS_EXIT_CODE"}
    if _emit_receipt(life.sink, receipt, path, file_state, attempted_sha) is not None:
        return EXIT_STOP                      # no receipt: never a consumable PASS
    return ev["exit_code"]


def receipt_authority_decision(exit_code, stdout_text, evidence_bytes):
    """Reader rule (pure).  A stdout that is not exactly one complete
    newline-terminated JSON object = no receipt = STOP."""
    def stop(reason):
        return {"decision": "STOP", "reason": reason}
    if type(stdout_text) is not str or not stdout_text.endswith("\n") \
            or "\n" in stdout_text[:-1]:
        return stop("NO_COMPLETE_SINGLE_RECEIPT_LINE")
    try:
        receipt = _strict_json(stdout_text[:-1].encode("utf-8"))
    except Exception:
        return stop("RECEIPT_NOT_JSON")
    if type(receipt) is not dict or receipt.get("record") != "NRP3_CANARY_FINAL_RECEIPT":
        return stop("NOT_A_RECEIPT")
    if exit_code != 0 or type(exit_code) is not int:
        return stop("EXIT_CODE_NOT_0")
    if receipt.get("verdict") != "PASS" or receipt.get("exit") != 0:
        return stop("RECEIPT_NOT_PASS")
    target = _dict(receipt.get("evidence_file"))
    if target.get("state") != "COMPLETE_FSYNC_REQUESTED":
        return stop("EVIDENCE_FILE_NOT_COMPLETE")
    if type(evidence_bytes) is not bytes:
        return stop("EVIDENCE_FILE_MISSING")
    if sha256_bytes(evidence_bytes) != target.get("sha256"):
        return stop("EVIDENCE_SHA_MISMATCH")
    try:
        evidence = _strict_json(evidence_bytes)
    except Exception:
        return stop("EVIDENCE_NOT_JSON")
    if _dict(evidence).get("verdict") != "PASS":
        return stop("EVIDENCE_NOT_PASS")
    return {"decision": "PASS", "reason": "RECEIPT_EXIT_AND_EVIDENCE_AGREE"}


# ---------------------------------------------------------------- entry
def _attempt(argv, gate, sink, read_deps_factory, effect_deps_factory):
    """The reviewed injection seam.  Both factories arrive uncalled."""
    if gate.enabled is not True:
        return _refuse(sink, "HARNESS_DISABLED", "", "UNKNOWN_NO_WRITE_BY_THIS_RUN")
    if gate.known_names_sha256 is None:
        return _refuse(sink, "KNOWN_UNSERVED_NAMES_NOT_BOUND", "",
                       "UNKNOWN_NO_WRITE_BY_THIS_RUN")
    record = _AttemptRecord()
    read_deps, attempt_id = None, None
    try:
        try:
            read_deps = read_deps_factory()                         # T1
        except Exception as error:
            raise Refused("READ_DEPS_CONSTRUCTION_FAILED", _describe(error)["text"])
        approval, attempt_id, run_dir = check_authorization(argv, gate, read_deps)
        deps = effect_deps_factory(approval, read_deps)             # T2, after authorization
        consume_attempt(record, approval, attempt_id, read_deps, deps)
    except Refused as refused:
        return _refuse(sink, refused.code, refused.detail, refused.attempt_state,
                       note=refused.note)
    except BaseException as error:
        if not record.boundary_crossed:
            return _refuse(sink, "PRE_CONSUMPTION_ABORT", _describe(error)["text"],
                           "UNKNOWN_NO_WRITE_BY_THIS_RUN", note="not retried")
        return _after_boundary(sink, record, read_deps, error, attempt_id)
    life = None
    try:
        life = Lifecycle(attempt_id, approval, read_deps, deps, sink, run_dir)
        life.ev["marker"] = {"path": record.marker_path, "progress": dict(record.progress)}
        try:
            run_lifecycle(life)
        except BaseException as error:
            life.fail(error)                 # first failure: primary
        finally:
            cleanup(life)
        import_end_check_1(life)
        final_decision(life)
        return publish(life)
    except BaseException as error:           # e.g. repeated interrupt between steps
        return _lifecycle_abort(sink, life, attempt_id, error)


def _abort_snapshot(life):
    """R6: finite copy of state ALREADY recorded on `life` by this harness.
    Reads plain attributes, dicts and lists only: no process, context, port,
    session, filesystem, clock or sink access, no cleanup, nothing blocking.
    Best effort; never complete evidence (ABORT_SNAPSHOT_RULE)."""
    ev, custody = life.ev, life.custody
    outcomes = ev["outcomes"]
    progress = life.publish_progress
    return {
        "phase": life.phase,
        "phases": [row["phase"] for row in ev["phases"]],
        "custody": {"spawn_state": custody["spawn_state"],
                    "child": dict(custody["child"]), "pipes": dict(custody["pipes"]),
                    "context": custody["context"], "wait_error": custody["wait_error"]},
        "unresolved_ownership": [dict(row) for row in ev["unresolved_ownership"]],
        "recorded_outcomes": {key: outcomes[key] for key in ABORT_SNAPSHOT_OUTCOMES
                              if key in outcomes},
        "run_dir_created": life.run_dir_created,
        "first_close_called": life.first_close_called,
        "marker": ev.get("marker"),
        "publish_progress": dict(progress) if isinstance(progress, dict) else None}


def _lifecycle_abort(sink, life, attempt_id, error):
    """Outer abort.  The abort error is recorded AFTER every earlier failure
    (primary only if nothing failed before); earlier records keep their
    order.  One record: stderr first; stdout only as a fallback when the
    stderr write failed (that line is not a receipt).  If both sinks fail
    nothing more is attempted and nothing is claimed.  No cleanup, no retry,
    no host query."""
    try:
        if life is not None:
            life.fail(error, "LIFECYCLE_ABORT")
        record = {"record": "NRP3_LIFECYCLE_ABORTED", "verdict": "STOP", "exit": EXIT_STOP,
                  "pass_meaning": None, "attempt_id": attempt_id,
                  "spent_by_this_run": True, "attempt_state": "SPENT_THIS_RUN",
                  "abort_error": _describe(error),
                  "primary": getattr(life, "primary", None),
                  "secondary": getattr(life, "secondary", None),
                  "snapshot": None, "snapshot_error": None,
                  "evidence_complete": False, "snapshot_rule": ABORT_SNAPSHOT_RULE,
                  "sink": "STDERR",
                  "loader_lifetime": LOADER_LIFETIME,
                  "evidence_file_rule": "any EVIDENCE.json is not authoritative without a "
                                        "matching stdout receipt and exit code 0"}
        if life is not None:
            try:
                record["snapshot"] = _abort_snapshot(life)
                if len(_serialize(record)) > MAX_STDERR_RECORD_BYTES:
                    record["snapshot"]["recorded_outcomes"] = "OMITTED_OVER_SIZE_BOUND"
            except BaseException as snapshot_error:
                record["snapshot"] = None
                record["snapshot_error"] = _describe(snapshot_error)
        stderr_error = sink.emit_stderr_line(record)
        if stderr_error is not None:
            record["sink"] = {"stderr": "FAILED", "error": _describe(stderr_error),
                              "this_line": "STDOUT_FALLBACK_NOT_A_RECEIPT"}
            sink.emit_stdout_line(record)     # result unused: both failed = no record
    except BaseException:
        pass
    return EXIT_STOP


def main(argv):
    return _attempt(argv, _Gate(HARNESS_ENABLED, KNOWN_UNSERVED_NAMES_SHA256),
                    _StdSink(sys.stdout, sys.stderr), _build_read_deps, _build_effect_deps)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
