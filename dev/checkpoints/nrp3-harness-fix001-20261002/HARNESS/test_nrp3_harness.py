"""Pure-model tests for the DISABLED NRP3 canary harness (NRP3_HARNESS_IMPL001,
repair FIX001: R1/R2/R6 extend existing ids only; no new id).

Exactly the 53 ids of PURE_TEST_MATRIX.json (39 U, 10 L, 4 B).  Every attempt
storage object (approval, marker, ledger, run dir, EVIDENCE) lives only in the
in-memory FakeOs map; nothing is written to the real filesystem.  The approval
dicts below are in-memory fixtures (approved_by says so), never an approval.
Group B reads the frozen WORKTREE bytes through RealReadFS(os) (reads only),
never compiles the p18 files, and injects FakeP18 module objects plus a
RecordingP18SysPorts subclass defined after the session loaded
native_root_port.  No test expects or provokes a real guard violation.

Bounded FIX001 subcases (fixed tables below, no generation, no fuzzing):
  HL06  SPAWN_ERRORS x SPAWN_MODES = 8 (R1)
  HL05/HL07  WAIT_ERRORS x (no later abort, later fake-clock abort) = 8 (R6),
        plus SINK_SAMPLES = 2 abort-sink samples in HL07
  HI02/HI09/HB01  the exact REFERENCE_232 list + LAZY_2 (= 234), R2
  HI02/HI03/HB01  QUALIFIED_SAMPLES / ORIGIN_SAMPLES: the small documented
        sets of qualified-name and origin-fallback probes
The Gate used with REFERENCE_232 is a test-only injected Gate; the production
constant stays None and UNIVERSE_234_SHA256 is a diagnostic, not a binding.
"""
import ast
import errno
import importlib
import importlib.machinery
import inspect
import io
import json
import os
import subprocess
import sys
import types
import unittest

_AUX = sys.modules.get("harness_guard_aux")
_AUX_CALLS_BEFORE = None if _AUX is None else _AUX.COUNTERS["calls"]
_META_BEFORE = list(sys.meta_path)
_MODULES_BEFORE = set(sys.modules)
import nrp3_root_canary_harness as H  # noqa: E402
_AUX_CALLS_AFTER = None if _AUX is None else _AUX.COUNTERS["calls"]
_META_AFTER = list(sys.meta_path)
_MODULES_AFTER = set(sys.modules)

ROOT = "/nrp3fake"
CAND = ROOT + "/cand"
LEDGER = ROOT + "/ledger"
RUNS = ROOT + "/runs"
RUN_DIR = RUNS + "/attempt1"
EVIDENCE = RUN_DIR + "/EVIDENCE.json"
APPROVAL = ROOT + "/approval/approval.json"
HARNESS_PATH = ROOT + "/harness/nrp3_root_canary_harness.py"
INTERP = ROOT + "/bin/python3"
PROTECTED = ROOT + "/protected"
ATTEMPT = "NRP3_TEST_ATTEMPT_1"
MARKER = LEDGER + "/" + ATTEMPT + ".CONSUMED"
T0 = 1790000000
FIXTURE_NAMES = ["nrp3hfx_unserved_a", "nrp3hfx_unserved_b"]
# R2 canonical DECLARED list (reference232): .py basenames + identifier-named
# directories of the pinned WORKTREE, minus the 19 served names, minus LAZY_2.
# HB01 re-derives it from the tree; HI02/HI09/HB01 use it as the exact list.
REFERENCE_232 = """
    ARCH000 ARCH000A ENGINE001 ENGINE002 R STAGEA_TIMING_001 STAGEB_PREREG001
    STAGEB_PREREG001_FIX001 STAGEB_PREREG001_FIX002 STAGEB_PREREG001_FIX003 baseline_7a90d33
    benchmark bstar_u32le_store build_stage_b_exec_fix002_fixture build_stage_b_prereg001
    check_bounded_cert_authority_fix001 check_bounded_hash_oracle check_bounded_store
    check_branch_fix001 check_capture_fix001 check_exec_preflight_fix001
    check_pretiming_gate check_runtime_activation_fix001 check_sampler_fix001
    check_sampler_fix002 check_sampler_fix003 check_sampler_fix004 check_sampler_fix005
    check_stage_a_failure_archive check_stage_a_fix001_prerun check_stage_a_fix001_source
    check_stage_a_orch_fix001_prerun check_stage_a_timing check_stage_a_timing_stop_evidence
    check_stage_b_exec_fix002 check_stage_b_exec_fix003 check_stage_b_exec_fix004
    check_stage_b_exec_fix005 check_stage_b_exec_fix006 check_stage_b_fix001_no_clock
    check_stage_b_fix002_no_clock check_stage_b_fix003_no_clock check_stage_b_prereg001
    check_stage_b_timeout_contract check_tiny_store check_validity_vectors
    check_xplat_failure_diagnostics check_xplat_newline_contract classify_fix007_trigger
    common compare_payload_manifests control_plane data deep_tree_probe descriptor_bytes_v1
    dev dev005 dev006 dev_build001 development_guard devtool direct_child_pidfd engine002
    evidence exact_256_store example_dev006_pure example_dev007_fix001_pure
    example_dev007_fix002_pure example_dev007_fix003_pure example_dev007_fix004_pure
    example_dev007_fix005_pure example_dev007_pure example_dev_phase_evidence001_pure
    exec_preflight execution_contract fix001_real_worker fix001a_compare fix001a_sha256
    fix001b fix001b_compare fix005_injected_worker fix005_journal fixtures
    future_stage_b_worker history hook_health independent inst integrated_native_adapter
    integrated_native_effects large_payload_aggregate_check ledger lifecycle linux_exec
    linuxport001 macos_local_20260807 man materialize_residual_authority multi_257_store
    native_close_smoke native_owner_controller native_syscalls_factory one_cell_store
    p18_custody p18_working package_evidence partition_differential payload_aggregate_check
    payload_manifest pilot planner_projection pro_original pro_recert
    probe_dev007_fix002_pro_corrected probe_dev007_fix003_astra_corrected
    probe_dev007_fix004_astra_regression probe_dev_phase_evidence001_fix001_astra_corrected
    probe_physical_allocation prototype pure_candidate_runner raw_ff_store recert
    reconstruct_stage_b_hashes recorded_native reference rss
    run_bounded_cert_authority_fix001 run_branch_fix001_preflight
    run_capture_fix001_preflight run_composite_consistency_cases
    run_composite_positive_cases run_descriptor_byte_cases run_descriptor_cases
    run_descriptor_read_cases run_dev006_pure run_encoder_authority_cases run_exec_preflight
    run_fix001_preflight run_fix002_preflight run_fix003_preflight run_fix004_preflight
    run_fix005_preflight run_fix006_preflight run_fixture_matrix run_negative_cases
    run_nonregular_cases run_phase_cases run_primitive_consistency_cases
    run_prototype_equivalence run_runtime_activation_fix001_preflight
    run_sampler_fix002_preflight run_sampler_fix003_preflight run_sampler_fix004_preflight
    run_sampler_fix005_preflight run_stage_a_admission_cases run_stage_a_fix001_prerun
    run_stage_a_orch_fix001_prerun run_stage_a_timing run_stage_a_timing_002
    run_stage_a_timing_003 run_stage_a_timing_worker run_stage_b_decision_cases
    run_stage_b_decision_numeric_contract_mutation_cases run_stage_b_evidence_tool_cases
    run_stage_b_hash_mutation_cases run_stage_b_numeric_boundary_cases
    run_stage_b_schedule_selection_mutation_cases run_stage_b_timeout_mutation_cases
    run_validator_memory_cases run_writer_semantic_cases run_xplat_replay runtime_bindings
    sampler_fix001_control_process sampler_fix002_timeout_control
    sampler_fix003_timeout_control sampler_fix004_churn_control schema sources spec src
    stage_a_admission_proposal stage_a_prototypes stage_a_timing_common
    stage_a_v3_descriptors stage_b stage_b_decision_rule stage_b_dispatch_journal_fix005
    stage_b_durable_publish stage_b_evidence_tools stage_b_exec_fix002 stage_b_prereg001
    stage_b_worker store_tamper synthetic test_classify_fix007_trigger
    test_controller_dispatch test_dev006 test_dev007 test_dev007_fix001 test_dev007_fix002
    test_dev007_fix003 test_dev007_fix004 test_dev007_fix005 test_dev_phase_evidence001
    test_dev_phase_evidence001_fix001 test_linux_exec test_native_close_smoke test_nrp2
    test_nrp3 test_payload_manifest_normalization test_windows_cold_start_crlf tests
    testsupport testthat tiny_store tools verify_authority verify_deep_tree_evidence
    verify_golden verify_stage_b_exec_preflight verify_stage_b_exec_preflight_review_package
    verify_stage_b_prereg_review_package verify_windows_cold_start_evidence
    verify_windows_r_hosted_evidence vignettes windows_cold_start_probe
    windows_r_hosted_probe wiring workflows xplat zero_columns_store zero_rows_store
""".split()
REFERENCE_232_SHA256 = "8f667793da6fd80638e441f80c345cb2cc42fc1bd8806b21dcc7da82d27ca9fc"
LAZY_2 = ("capture_pretiming_resources", "probe_durability_capabilities")
UNIVERSE_234_SHA256 = "35189fe328c293f4d3af2ded9aa27d26e499c255c5bf8b15e48373e3be0e43d7"
TREE_COUNTS = {"py_basenames": 192, "identifier_directories": 61, "served": 19}
NON_IDENTIFIER_DIRECTORIES = [".github", "ENGINE002-FIX001", "ENGINE002-FIX001A",
                              "ENGINE002-FIX001B", "ENGINE003-PREFLIGHT", "data-raw"]
AMBIGUOUS_BASENAMES = ("linux_proc_backend", "stage_b_controller", "termination")
# Qualified-name probes (top label decides): directory-name top with a served
# tail, nested directory names, lazy top, declared .py-basename top.
QUALIFIED_SAMPLES = ("linux_exec.termination", "testsupport.dev005.termination",
                     "exec_preflight.stage_b_controller",
                     "capture_pretiming_resources.command", "common.anything")
# R1: every type is tried before any effect and after the fake child was created.
# The OSError rows use errno values that Python does NOT map to a subclass
# (EMFILE, EIO), so the instance type is exactly the labelled one (asserted).
SPAWN_MODES = ("RAISE", "CREATE_THEN_RAISE")
SPAWN_ERRORS = (
    ("OSError", lambda: OSError(errno.EMFILE, "fake spawn failure")),
    ("ValueError", lambda: ValueError("fake bad argument")),
    ("TypeError", lambda: TypeError("fake bad type")),
    ("KeyboardInterrupt", lambda: KeyboardInterrupt("fake spawn interrupt")))
# R6: errors raised by the cleanup wait of a known, unreaped child.
WAIT_ERRORS = (
    ("TimeoutExpired", lambda: subprocess.TimeoutExpired("child", 10.0)),
    ("OSError", lambda: OSError(errno.EIO, "fake wait failure")),
    ("KeyboardInterrupt", lambda: KeyboardInterrupt("fake wait interrupt")),
    ("SystemExit", lambda: SystemExit("fake wait exit")))
SINK_SAMPLES = ("STDERR_FAILS", "BOTH_FAIL")
FAKE_PARENT_PID = 31337
FAKE_CHILD_PID = 4242
FAKE_FD = 987654
BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"
BOOT_PATH = "/proc/sys/kernel/random/boot_id"
FDINFO_PATH = "/proc/self/fdinfo/%d" % FAKE_FD
SPENT = (True, "SPENT_THIS_RUN")
NO_WRITE = (False, "UNKNOWN_NO_WRITE_BY_THIS_RUN")
U_PLAN = {"served": ("fx/nrp3hfx_u_a.py", "fx/nrp3hfx_u_port.py"),
          "lazy_refused": ("fx/nrp3hfx_u_lazy.py",),
          "port_module_relpath": "fx/nrp3hfx_u_port.py",
          "entry_imports": ("nrp3hfx_u_a",), "p18_entry_imports": (),
          "expected_sys_path_inserts": ()}
U_SOURCES = {"fx/nrp3hfx_u_a.py": b"VALUE = 1\n", "fx/nrp3hfx_u_port.py": b"PORT = 1\n",
             "fx/nrp3hfx_u_lazy.py": b"LAZY = 1\n"}
WORKTREE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "WORKTREE")
B_P18 = ("dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/parsers.py",
         "dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/pidfd_primitives.py")
# Pinned WORKTREE hashes (BEFORE_WORKTREE.json; 19 served + 2 lazy-refused).
B_PINS = {
    "dev/ENGINE003-PREFLIGHT/exec_preflight/fix001_contract.py": "2844a860f15fb7141f9c89b0eee02e16cc3d1a746f3454f05eb6c26d16dcef7d",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_authorization.py": "fa83990abf22fe06a92d701ad391b693bed803296650e2f338fc927ebdc53692",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py": "08f0d2551c96186f75f986c2d820b22a4b3cb1f632177ad1d65a3ee3110b5e58",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_dispatch_journal.py": "5ffe8f651fb746b86cefd528ac7448c9f00650b4cbf6e8ff5ddd4fb4f5ba1995",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_orchestrator.py": "21e84256a975e5eaf2395a78683614438a8357c276ceb18abbb7585b34a53cb8",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py": "35d42b1e17efd7dc631fe7e44d340b037d7480bd1d9d3c7b7e73c23764aa0678",
    "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/linux_entry.py": "34638c62458df01af03a5d9da1d04fc27703eba0b553d7592e40808af5fa5051",
    "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/linux_proc_backend.py": "6fde3709650c6e15900fc6d47916ab19b38d6672cdb5a4a6d6a2489e3636ea32",
    "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/native_root_port.py": "089bba7dd114a824bb3d15e0cce5da97c8855c8e7b67d4bb1f593197637744bf",
    "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/proc_source.py": "e404a87db7db0982b255cc9063d9d0c60f32feb285d741f23f9d6cba567c91af",
    "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec/termination.py": "5fef6ff73fed80f8ed56ae15de0149969c1fe1c2234d3b05919d0be9cafa1f7f",
    "dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/parsers.py": "4e5c4287676e0446dc0fc30a3d5aafcc51fc1e4aabb3029fbf03868e8f64c471",
    "dev/ENGINE003-PREFLIGHT/linuxport001/p18_working/pidfd_primitives.py": "6426fdd496ae1b24074361b207b5296e146d77d6c68495b5a427053419dda809",
    "dev/ENGINE003-PREFLIGHT/reference/canonical_text.py": "1ed575dfee97b2b90d74621c221b9175532bee965f82f4dfe2bf3050822db29a",
    "dev/ENGINE003-PREFLIGHT/reference/encode_boundary_fixture.py": "81f129c4bd08bd247d30c84aaaf85510333580ab19b459a3afaeb0279e6eff3b",
    "dev/ENGINE003-PREFLIGHT/reference/encode_stage_a_tiled_store.py": "cb8f2c323630000b983d853f35d917c1994743752c90fa8324886e53d9bc8f63",
    "dev/ENGINE003-PREFLIGHT/reference/encode_tiny_fixture.py": "43fe47d0202b546d0e1ff25ecd8a565c421a9f7dd06569a74940829c4f644659",
    "dev/ENGINE003-PREFLIGHT/reference/stage_a_authority_v2.py": "ae1b7bb2aca2f523ecfe3920c6571b0d59162f5ef00e96f49d039953c274566d",
    "dev/ENGINE003-PREFLIGHT/reference/stage_a_fiber_v3.py": "7e79176d9edc01b30777bbda145835987fa7a7ff283ef1f889d7fbb835bb2393",
    "dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py": "447c224894e2c47bc7b3597326d09c1df8e4ca7b15df78cd536240e1934c0b23",
    "dev/ENGINE003-PREFLIGHT/reference/probe_durability_capabilities.py": "7f6419842f6ede4c4757ea5211a6b4baa062f887a81dfd28d72cc316c0841ed6",
}
B_SERVED = tuple(rel for rel in H.PRODUCTION_PLAN["served"] if rel not in B_P18)
B_PLAN = {"served": B_SERVED,
          "lazy_refused": tuple(H.PRODUCTION_PLAN["lazy_refused"]) + B_P18,
          "port_module_relpath": H.PRODUCTION_PLAN["port_module_relpath"],
          "entry_imports": tuple(H.PRODUCTION_PLAN["entry_imports"]),
          "p18_entry_imports": (),
          "expected_sys_path_inserts": tuple(H.PRODUCTION_PLAN["expected_sys_path_inserts"])}


def sha(data):
    return H.sha256_bytes(data)


# ---------------------------------------------------------------- fakes
class FakeOsPath:
    def __init__(self, kernel):
        self.k = kernel

    def realpath(self, path):
        self.k.calls.append(("realpath", path))
        return self.k.links.get(path, path)

    def isdir(self, path):
        self.k.calls.append(("isdir", path))
        return path in self.k.dirs


class FakeOs:
    """In-memory os model (flags, modes, O_EXCL, short writes, stage-addressable
    scripted failures).  Passed into RealReadFS/RealWriteFS; never touches the
    real filesystem."""
    O_RDONLY, O_WRONLY, O_RDWR = 0, 1, 2
    O_CREAT, O_EXCL, O_DIRECTORY = 0o100, 0o200, 0o200000
    O_NOFOLLOW, O_CLOEXEC = 0o400000, 0o2000000

    def __init__(self):
        self.files, self.modes, self.dirs, self.links = {}, {}, set(), {}
        self.calls, self.failures, self.fds, self.next_fd = [], [], {}, 100
        self.short_write = None
        self.path = FakeOsPath(self)

    def fail(self, stage, suffix, error, skip=0):
        self.failures.append([stage, suffix, error, skip])

    def _maybe(self, stage, path):
        for entry in self.failures:
            if entry[0] == stage and path.endswith(entry[1]):
                if entry[3] > 0:
                    entry[3] -= 1
                    continue
                raise entry[2]

    def _fd(self, path, kind):
        fd = self.next_fd
        self.next_fd += 1
        self.fds[fd] = [path, kind, 0]
        return fd

    def names(self, path):
        prefix = path.rstrip("/") + "/"
        return sorted({p[len(prefix):].split("/")[0]
                       for p in list(self.files) + list(self.dirs) if p.startswith(prefix)})

    def open(self, path, flags, mode=0o777):
        self.calls.append(("open", path, flags, mode))
        self._maybe("OPEN", path)
        if flags & self.O_DIRECTORY:
            if path not in self.dirs:
                raise FileNotFoundError(errno.ENOENT, "no such directory", path)
            return self._fd(path, "dir")
        if flags & self.O_CREAT:
            if path in self.files or path in self.dirs:
                raise FileExistsError(errno.EEXIST, "exists", path)
            if os.path.dirname(path) not in self.dirs:
                raise FileNotFoundError(errno.ENOENT, "no parent", path)
            self.files[path], self.modes[path] = b"", mode
            self._maybe("OPEN_AFTER_CREATE", path)
            return self._fd(path, "w")
        if path not in self.files:
            raise FileNotFoundError(errno.ENOENT, "missing", path)
        return self._fd(path, "r")

    def read(self, fd, count):
        self.calls.append(("read", fd, count))
        path, _, offset = self.fds[fd]
        data = self.files[path][offset:offset + count]
        self.fds[fd][2] = offset + len(data)
        return data

    def write(self, fd, data):
        path = self.fds[fd][0]
        self.calls.append(("write", fd, len(data)))
        self._maybe("WRITE", path)
        chunk = bytes(data) if self.short_write is None else bytes(data[:self.short_write])
        self.files[path] += chunk
        return len(chunk)

    def fsync(self, fd):
        path, kind = self.fds[fd][0], self.fds[fd][1]
        self.calls.append(("fsync", fd, kind, path))
        self._maybe("DIR_FSYNC" if kind == "dir" else "FSYNC", path)

    def close(self, fd):
        path = self.fds[fd][0]
        self.calls.append(("close", fd, path))
        self._maybe("CLOSE", path)

    def mkdir(self, path, mode):
        self.calls.append(("mkdir", path, mode))
        self._maybe("MKDIR", path)
        if path in self.dirs or path in self.files:
            raise FileExistsError(errno.EEXIST, "exists", path)
        self.dirs.add(path)

    def lstat(self, path):
        self.calls.append(("lstat", path))
        self._maybe("LSTAT", path)
        if path in self.files or path in self.dirs:
            return object()
        raise FileNotFoundError(errno.ENOENT, "missing", path)

    def listdir(self, path):
        self.calls.append(("listdir", path))
        return self.names(path)

    def named(self, name, path=None):
        return [c for c in self.calls if c[0] == name and (path is None or path in c)]


class FakeReadFS:
    """In-memory read-only side.  Records every call; has NO write method."""

    def __init__(self, kernel, log):
        self.k, self.log, self.calls, self.lstat_script = kernel, log, [], {}
        self.realpath_errors = {}

    def read_bytes(self, path, limit):
        self.calls.append(("read_bytes", path, limit))
        self.log.append("rfs.read_bytes:" + path)
        if path not in self.k.files:
            raise FileNotFoundError(errno.ENOENT, "missing", path)
        data = self.k.files[path]
        return data if limit is None else data[:limit + 1]

    def lstat(self, path):
        self.calls.append(("lstat", path))
        queue = self.lstat_script.get(path)
        if queue:
            return queue.pop(0)
        present = path in self.k.files or path in self.k.dirs
        return ("PRESENT", None) if present else ("ENOENT", None)

    def realpath(self, path):
        self.calls.append(("realpath", path))
        if path in self.realpath_errors:
            raise self.realpath_errors[path]
        return self.k.links.get(path, path)

    def isdir(self, path):
        self.calls.append(("isdir", path))
        return path in self.k.dirs

    def listdir(self, path):
        self.calls.append(("listdir", path))
        return self.k.names(path)


class FakeWriteFS(H.RealWriteFS):
    """In-memory write side over the same map: the harness create_exclusive
    logic running on FakeOs.  All modeled marker/ledger/run dir/EVIDENCE live
    only here."""

    def __init__(self, kernel, log):
        H.RealWriteFS.__init__(self, kernel)
        self.kernel, self.log, self.calls, self.interrupt_after = kernel, log, [], None

    def create_exclusive(self, path, data, progress):
        self.calls.append(("create_exclusive", path))
        self.log.append("wfs.create_exclusive:" + path)
        result = H.RealWriteFS.create_exclusive(self, path, data, progress)
        if self.interrupt_after and path.endswith(self.interrupt_after):
            raise KeyboardInterrupt("fake interrupt after create returned")
        return result

    def mkdir(self, path, mode):
        self.calls.append(("mkdir", path, mode))
        self.log.append("wfs.mkdir:" + path)
        H.RealWriteFS.mkdir(self, path, mode)

    def fsync_dir(self, path):
        self.calls.append(("fsync_dir", path))
        H.RealWriteFS.fsync_dir(self, path)


class FakeStream:
    def __init__(self):
        self.text, self.error, self.flushes = "", None, 0

    def write(self, text):
        if self.error is not None:
            raise self.error
        self.text += text

    def flush(self):
        self.flushes += 1


class FakeSink(H._StdSink):
    """T0 sink double: the harness sink over scripted fake streams."""

    def __init__(self):
        self.o, self.e = FakeStream(), FakeStream()
        H._StdSink.__init__(self, self.o, self.e)

    def out(self):
        return [json.loads(line) for line in self.o.text.splitlines()]

    def err(self):
        return [json.loads(line) for line in self.e.text.splitlines()]


class ReadDepsSpy:
    def __init__(self, build):
        self.build, self.calls, self.error, self.results = build, 0, None, []

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        self.results.append(self.build())
        return self.results[-1]


class EffectDepsSpy:
    def __init__(self, build, snapshot):
        self.build, self.snapshot = build, snapshot
        self.calls, self.args, self.results, self.snapshots = 0, [], [], []

    def __call__(self, approval, read_deps):
        self.calls += 1
        self.args.append((approval, read_deps))
        self.snapshots.append(self.snapshot())
        self.results.append(self.build())
        return self.results[-1]


class FakePipe:
    def __init__(self):
        self.closed, self.close_calls = False, 0

    def close(self):
        self.close_calls += 1
        self.closed = True


class FakeProcess:
    def __init__(self, pid=FAKE_CHILD_PID):
        self.pid, self.returncode = pid, None
        self.stdin, self.stdout = FakePipe(), FakePipe()
        self.communicate_script, self.wait_script = (b"NRP3_CHILD_DONE\n", 0), 0
        self.communicate_calls, self.wait_calls, self.forbidden = [], [], 0
        self.on_wait = None

    def communicate(self, input=None, timeout=None):
        self.communicate_calls.append((input, timeout))
        script = self.communicate_script
        if isinstance(script, BaseException):
            raise script
        self.stdin.closed = self.stdout.closed = True
        self.returncode = script[1]
        return (script[0], None)

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.on_wait is not None:
            self.on_wait()
        if isinstance(self.wait_script, BaseException):
            raise self.wait_script
        self.returncode = self.wait_script
        return self.returncode

    def _forbidden(self, *args, **kwargs):
        self.forbidden += 1
        raise AssertionError("FORBIDDEN_PROCESS_CONTROL_CALL")

    kill = terminate = send_signal = _forbidden


class FakeProcessPort:
    def __init__(self, process):
        self.process, self.argvs, self.mode, self.error, self.created = process, [], "RETURN", None, []

    def spawn_child(self, argv):
        self.argvs.append(list(argv))
        if self.mode == "RAISE":
            raise self.error
        self.created.append(self.process)
        if self.mode == "CREATE_THEN_RAISE":
            raise self.error
        return self.process


class FakePopenCallable:
    def __init__(self):
        self.calls, self.result = [], object()

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class FakeNow:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def __call__(self):
        self.calls += 1
        return self.value


class FakeClock:
    def __init__(self):
        self.t, self.calls, self.armed = 100.0, 0, None

    def __call__(self):
        self.calls += 1
        if self.armed is not None:
            error, self.armed = self.armed, None
            raise error
        self.t += 0.25
        return self.t


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class FakePathFinder:
    def __init__(self):
        self.calls, self.script = [], {}

    def find_spec(self, name, path=None):
        self.calls.append((name, path))
        return self.script.get(name)


class CountingFinder:
    """Group B: delegates to the real PathFinder (locate only, never executes)
    and records every name it was asked for."""

    def __init__(self, real):
        self.real, self.calls = real, []

    def find_spec(self, name, path=None):
        self.calls.append(name)
        return self.real.find_spec(name, path)


class FakeSession:
    """U-group double of PinnedImportSession (no install into sys.meta_path)."""
    loader_lifetime = H.LOADER_LIFETIME

    def __init__(self, log):
        self.log, self.installed, self.end_calls, self.end_script = log, False, 0, {}
        self.refusals, self.factory_args = [], None

    def __call__(self, root, verified, refused, path_finder, read_fs, inserts):
        self.factory_args = (root, sorted(verified), sorted(refused))
        return self

    def install(self):
        self.installed = True
        self.log.append("session.install")

    def load_entries(self, names):
        self.log.append("session.load_entries")
        return dict((name, types.ModuleType("nrp3hfx_fake_" + name)) for name in names)

    def origin_violations(self):
        return []

    def end_check(self):
        self.end_calls += 1
        self.log.append("session.end_check#%d" % self.end_calls)
        error = self.end_script.get(self.end_calls)
        if error is not None:
            raise error
        return {"index": self.end_calls, "problems": [], "loader_at_meta_path_0": True,
                "loader_lifetime": H.LOADER_LIFETIME}

    def report(self):
        return {"installed": self.installed, "end_calls": self.end_calls,
                "loader_lifetime": H.LOADER_LIFETIME}


class ReusedSession:
    """Group B only: later cases in one process reuse the modules served by
    the one real retained session (it is never removed or re-installed)."""
    loader_lifetime = H.LOADER_LIFETIME

    def __init__(self, real):
        self.real, self.refusals = real, real.refusals

    def __call__(self, *args):
        return self

    def install(self):
        return None

    def load_entries(self, names):
        return dict((name, sys.modules[name]) for name in names)

    def origin_violations(self):
        return self.real.origin_violations()

    def end_check(self):
        return self.real.end_check()

    def report(self):
        return self.real.report()


class FakeTermination:
    def __init__(self, context):
        self.context, self.report_error = context, None

    def report(self):
        self.context.log.append("ctx.termination.report")
        if self.report_error is not None:
            raise self.report_error
        return self.context.route


class FakeContext:
    def __init__(self, log):
        self.log, self.root_authority_state = log, "NOT_ACQUIRED"
        self.closed, self.custody, self.teardown_started, self.evidence = False, None, False, []
        self.admit_error = self.attach_error = None
        self.attach_state = "ACQUIRED"
        self.close_script, self.close_calls = ["CLOSED", "ALREADY_CLOSED"], []
        self.termination = FakeTermination(self)
        self.route = {"port_counters": {"open": 1, "close": 1, "signal_refused": 0},
                      "port_custody": [{"pid": FAKE_CHILD_PID, "custody": "CLOSED",
                                        "resolved": True}]}

    def admit(self):
        self.log.append("ctx.admit")
        if self.admit_error is not None:
            raise self.admit_error

    def attach_root(self, process):
        self.log.append("ctx.attach_root")
        if self.attach_error is not None:
            raise self.attach_error
        self.root_authority_state = self.attach_state

    def close(self, lock_timeout=None):
        self.log.append("ctx.close")
        self.close_calls.append(lock_timeout)
        self.teardown_started = True
        index = len(self.close_calls) - 1
        outcome = self.close_script[index] if index < len(self.close_script) else "ALREADY_CLOSED"
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "CLOSED":
            self.closed = True
        return outcome


class FakePorts:
    def __init__(self, env):
        self.env, self.effect, self.validate_error, self.new_context_hook = env, None, None, None

    def new_context(self):
        if self.new_context_hook is not None:
            self.new_context_hook()
        return self.env.context

    def spawn_child(self, argv):
        return self.env.port.spawn_child(argv)

    def effect_evidence(self, process, context):
        if self.effect is not None:
            return self.effect
        acquired = context.root_authority_state == "ACQUIRED"
        return {"attempted_effect": "SPAWN_RETURNED_PROCESS_OBJECT",
                "observed_root": {"pid": process.pid, "returncode_at_attach": None},
                "root_authority_state": context.root_authority_state,
                "custody": "REGISTERED" if acquired else "NOT_REGISTERED",
                "identity": None, "controller_phase": "POST_SPAWN:ROOT_ACQUISITION"}

    def validate_effect(self, effect):
        if self.validate_error is not None:
            raise self.validate_error


class OverlayReadFS:
    """Group B: paths under the real candidate root go to RealReadFS(os)
    (reads only); every other path (approval, ledger, run dir, harness pin)
    stays in the in-memory FakeReadFS."""

    def __init__(self, fake, real, real_root):
        self.fake, self.real, self.real_root, self.real_calls = fake, real, real_root, []

    def _pick(self, name, path):
        if H._inside(path, self.real_root):
            self.real_calls.append((name, path))
            return self.real
        return self.fake

    def read_bytes(self, path, limit):
        return self._pick("read_bytes", path).read_bytes(path, limit)

    def lstat(self, path):
        return self._pick("lstat", path).lstat(path)

    def realpath(self, path):
        return self._pick("realpath", path).realpath(path)

    def isdir(self, path):
        return self._pick("isdir", path).isdir(path)

    def listdir(self, path):
        return self._pick("listdir", path).listdir(path)


class FakeP18:
    """Fake module objects mirroring the p18 shape used by P18SysPorts."""

    def __init__(self):
        fake = self
        self.calls, self.constructions, self.env_obj = [], 0, object()
        self.validate_error, self.fdinfo_pid, self.start = None, FAKE_CHILD_PID, 777

        class AcquisitionPolicy:
            def __init__(self, a, b, c):
                self.flags = (a, b, c)

        class PidfdError(Exception):
            def __init__(self, code, operation, error_number=None):
                Exception.__init__(self, "%s:%s" % (code, operation))
                self.code, self.operation, self.error_number = code, operation, error_number

        class ProcStat:
            def __init__(self, pid, ppid, starttime_ticks):
                self.pid, self.ppid, self.starttime_ticks = pid, ppid, starttime_ticks

        class NativeSyscalls:
            no_cldwait = 2

            def __init__(self):
                fake.constructions += 1

            def acquisition_environment(self):
                fake.calls.append(("acquisition_environment",))
                return fake.env_obj

            def open(self, pid, flags):
                fake.calls.append(("open", pid, flags))
                return FAKE_FD

        def validate_acquisition_environment(policy, env, no_cldwait):
            fake.calls.append(("validate", policy.flags, env is fake.env_obj, no_cldwait))
            if fake.validate_error is not None:
                raise fake.validate_error

        def direct_child_stat(pid):
            fake.calls.append(("child_stat", pid))
            return ProcStat(pid, FAKE_PARENT_PID, fake.start)

        def wait_without_reaping(pid):
            fake.calls.append(("wait", pid))
            return False

        def bounded_read(path, maximum):
            fake.calls.append(("bounded_read", path, maximum))
            if path == BOOT_PATH:
                return BOOT_ID.encode("ascii") + b"\n"
            if path == FDINFO_PATH:
                return ("pos:\t0\nflags:\t02000002\nmnt_id:\t15\nPid:\t%d\nNSpid:\t%d\n"
                        % (fake.fdinfo_pid, fake.fdinfo_pid)).encode("ascii")
            raise AssertionError("UNEXPECTED_FAKE_READ:" + path)

        module = types.ModuleType("nrp3hfx_fake_p18_primitives")
        module.AcquisitionPolicy, module.PidfdError = AcquisitionPolicy, PidfdError
        module.NativeSyscalls, module.ProcStat = NativeSyscalls, ProcStat
        module.validate_acquisition_environment = validate_acquisition_environment
        module.direct_child_stat, module.bounded_read = direct_child_stat, bounded_read
        module.wait_without_reaping = wait_without_reaping
        self.module = module
        self.parsers = types.ModuleType("nrp3hfx_fake_p18_parsers")

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


# ---------------------------------------------------------------- environment
class Env:
    def __init__(self, plan=None, sources=None, cand=CAND):
        self.log = []
        self.os = FakeOs()
        self.plan = U_PLAN if plan is None else plan
        self.sources = U_SOURCES if sources is None else sources
        self.cand = cand
        self.os.dirs.update([ROOT, LEDGER, RUNS, ROOT + "/approval", ROOT + "/harness",
                             ROOT + "/bin", PROTECTED])
        self.os.files[HARNESS_PATH] = b"# in-memory stand-in for the harness bytes\n"
        self.os.files[INTERP] = b""
        files = {}
        if cand == CAND:
            self.os.dirs.add(CAND)
            for rel, data in self.sources.items():
                self.os.dirs.add(os.path.dirname(CAND + "/" + rel))
                self.os.files[CAND + "/" + rel] = data
                files[rel] = sha(data)
        self.names = list(FIXTURE_NAMES)
        self.gate = H._Gate(True, H.names_sha256(self.names))         # TestGate
        self.approval = {
            "schema": H.APPROVAL_SCHEMA, "enabled": True,
            "approved_by": "IN_MEMORY_TEST_FIXTURE_NOT_AN_APPROVAL",
            "approved_utc": T0, "expires_utc": T0 + 3600, "attempt_id": ATTEMPT,
            "run_dir": RUN_DIR, "consumption_ledger_dir": LEDGER, "candidate_root": cand,
            "candidate_files": files, "candidate_manifest_sha256": H.manifest_sha256(files),
            "harness_sha256": sha(self.os.files[HARNESS_PATH]),
            "port_module_sha256": files.get(self.plan["port_module_relpath"]),
            "interpreter": INTERP, "effects": list(H.EXPECTED_EFFECTS),
            "forbidden_effects_acknowledged": list(H.FORBIDDEN_EFFECTS),
            "protected_roots": [PROTECTED], "known_unserved_candidate_names": self.names}
        self.raw_approval = None
        self.rfs = FakeReadFS(self.os, self.log)
        self.wfs = FakeWriteFS(self.os, self.log)
        self.sink = FakeSink()
        self.now, self.clock, self.sleep = FakeNow(T0 + 10), FakeClock(), FakeSleep()
        self.process = FakeProcess()
        self.port = FakeProcessPort(self.process)
        self.path_finder = FakePathFinder()
        self.session_factory = FakeSession(self.log)
        self.context = FakeContext(self.log)
        self.ports = FakePorts(self)
        self.builder_calls, self.mods = [], None
        self.builder = self._builder
        self.harness_path, self.exe = HARNESS_PATH, INTERP
        self.read_spy = ReadDepsSpy(lambda: H.ReadDeps(
            self.rfs, self.now, self.exe, self.path_finder, self.harness_path, plan=self.plan))
        self.effect_spy = EffectDepsSpy(lambda: H.EffectDeps(
            self.wfs, self.port, self.clock, self.sleep, self.builder,
            session_factory=self.session_factory),
            lambda: (len(self.os.named("open")) + len(self.os.named("mkdir")),
                     len(self.wfs.calls), len(self.sink.o.text) + len(self.sink.e.text)))

    def _builder(self, mods, p18_modules, process_port, clock, sleep):
        self.builder_calls.append((sorted(mods), tuple(p18_modules), process_port, clock, sleep))
        self.mods = mods
        return self.ports

    def repin(self):
        files = self.approval["candidate_files"]
        self.approval["candidate_manifest_sha256"] = H.manifest_sha256(files)

    def declare(self, names):
        """Declared list + a TEST-ONLY injected Gate bound to it (the
        production constant is never bound)."""
        self.names = list(names)
        self.approval["known_unserved_candidate_names"] = self.names
        self.gate = H._Gate(True, H.names_sha256(self.names))

    def argv(self):
        return ["harness", "--approval", APPROVAL, "--run-dir", RUN_DIR,
                "--attempt-id", ATTEMPT]

    def run(self, argv=None):
        raw = self.raw_approval
        self.os.files[APPROVAL] = json.dumps(self.approval).encode("utf-8") if raw is None \
            else raw
        return H._attempt(self.argv() if argv is None else argv, self.gate, self.sink,
                          self.read_spy, self.effect_spy)

    def evidence_bytes(self):
        return self.os.files.get(EVIDENCE)

    def evidence(self):
        return json.loads(self.os.files[EVIDENCE].decode("utf-8"))

    def stop_record(self):
        return [r for r in self.sink.err() if r.get("record") == "NRP3_STDERR_STOP_RECORD"][0]

    def receipt(self):
        return self.sink.out()[0]


def make_session(env, cls=None, verified=None, refused=None):
    if verified is None:
        verified = dict((rel, env.os.files[CAND + "/" + rel]) for rel in env.plan["served"])
    if refused is None:
        refused = H.refusal_universe(env.plan, env.names)      # the canonical definition
    return (cls or H.PinnedImportSession)(CAND, verified, refused, env.path_finder, env.rfs,
                                          env.plan["expected_sys_path_inserts"])


def l_env(tag, a_source=None, lazy_2=False, declared=None):
    """lazy_2: the plan also lazy-refuses in-memory stand-ins named like the two
    production lazy modules (fake one-line bodies, never the real files)."""
    names = ("nrp3hfx_%s_a" % tag, "nrp3hfx_%s_b" % tag, "nrp3hfx_%s_lazy" % tag)
    extra = tuple("ref/%s.py" % name for name in LAZY_2) if lazy_2 else ()
    plan = {"served": ("fx/%s.py" % names[0], "fx/%s.py" % names[1]),
            "lazy_refused": ("fx/%s.py" % names[2],) + extra,
            "port_module_relpath": "fx/%s.py" % names[1],
            "entry_imports": (names[0],), "p18_entry_imports": (),
            "expected_sys_path_inserts": ()}
    first = a_source if a_source is not None else (
        "import %s\nVALUE = %s.BASE + 1\n" % (names[1], names[1])).encode("ascii")
    sources = {plan["served"][0]: first, plan["served"][1]: b"BASE = 41\n"}
    for rel in plan["lazy_refused"]:
        sources[rel] = b"LAZY = 1\n"
    env = Env(plan=plan, sources=sources)
    if declared is not None:
        env.declare(declared)
    return env, names


class BEnv(Env):
    """Bound environment: candidate files are the frozen WORKTREE bytes read
    through RealReadFS(os); everything else stays in memory."""

    def __init__(self):
        self.real_rfs = H.RealReadFS(os)
        root = self.real_rfs.realpath(WORKTREE)
        Env.__init__(self, plan=B_PLAN, sources={}, cand=root)
        self.approval["candidate_files"] = dict(B_PINS)
        self.approval["port_module_sha256"] = B_PINS[B_PLAN["port_module_relpath"]]
        self.repin()
        self.declare(REFERENCE_232)                 # canonical declared list (R2)
        self.rfs = OverlayReadFS(FakeReadFS(self.os, self.log), self.real_rfs, root)
        self.path_finder = importlib.machinery.PathFinder
        self.p18, self.box = FakeP18(), {"close_fd": [], "getpid_sites": [], "close_error": None}
        self.builder = self._bound_builder
        self.session_factory = self._capture_session

    def _capture_session(self, *args):
        self.box["session"] = H.PinnedImportSession(*args)
        return self.box["session"]

    def _bound_builder(self, mods, p18_modules, process_port, clock, sleep):
        box, p18 = self.box, self.p18
        frozen = mods["native_root_port"].P18SysPorts

        class RecordingP18SysPorts(frozen):
            def close_fd(self, fd):
                box["close_fd"].append(fd)
                if box["close_error"] is not None:
                    raise box["close_error"]

            def getpid(self):
                caller = sys._getframe(1)
                box["getpid_sites"].append((caller.f_code.co_name, caller.f_lineno))
                return FAKE_PARENT_PID

        calls_before, built_before = len(p18.calls), p18.constructions
        ports = H.NativePortsBuilder(mods, (p18.module, p18.parsers), process_port, clock,
                                     sleep, RecordingP18SysPorts)
        box.update(cls=RecordingP18SysPorts, frozen=frozen, mods=mods, ports=ports,
                   passed_p18=tuple(p18_modules),
                   construction_calls=len(p18.calls) - calls_before,
                   construction_native=p18.constructions - built_before)
        return ports


def tree_names(rfs, root):
    """(py basenames, directory names) of the tree below root, listed through
    the read-only adapter (listdir/isdir only; no file is opened)."""
    py, dirs, stack = set(), set(), [root]
    while stack:
        base = stack.pop()
        for name in rfs.listdir(base):
            path = os.path.join(base, name)
            if rfs.isdir(path):
                dirs.add(name)
                stack.append(path)
            elif name.endswith(".py"):
                py.add(name[:-3])
    return py, dirs


def guard_violations():
    found = []
    for name in ("pure_guard", "harness_guard_aux"):
        module = sys.modules.get(name)
        if module is not None:
            found += list(module.VIOLATIONS)
    return found


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return "?." + ".".join(reversed(parts)) if parts else None


def harness_tree():
    return ast.parse(inspect.getsource(H))


def owned_nodes(tree):
    """(top-level owner name, node) for every node below a top-level def/class."""
    for top in tree.body:
        owner = getattr(top, "name", None)
        for node in ast.walk(top):
            yield owner, node


class Base(unittest.TestCase):
    def refused(self, env, code, state=NO_WRITE, argv=None, rc=None):
        rc = env.run(argv) if rc is None else rc
        self.assertEqual(rc, 3)
        lines = env.sink.out()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(lines[0]["refused"], code, lines[0])
        self.assertEqual((lines[0]["spent_by_this_run"], lines[0]["attempt_state"]), state)
        self.assertEqual(env.sink.e.text, "")
        return lines[0]

    def stopped(self, env, rc=None):
        rc = env.run() if rc is None else rc
        self.assertEqual(rc, 2)
        receipt = env.receipt()
        self.assertEqual(receipt["verdict"], "STOP")
        self.assertEqual((receipt["spent_by_this_run"], receipt["attempt_state"]), SPENT)
        record = env.stop_record()
        self.assertEqual(record["verdict"], "STOP")
        self.assertIsNone(record["pass_meaning"])
        return record

    def passed(self, env):
        self.assertEqual(env.run(), 0, env.sink.o.text + env.sink.e.text)
        evidence = env.evidence()
        self.assertEqual(evidence["verdict"], "PASS")
        return evidence


# ---------------------------------------------------------------- U: gate
class GateTests(Base):
    def test_hg01_import_safety(self):
        self.assertIs(H.HARNESS_ENABLED, False)
        self.assertIsNone(H.KNOWN_UNSERVED_NAMES_SHA256)
        self.assertEqual(len(_META_BEFORE), len(_META_AFTER))
        self.assertTrue(all(a is b for a, b in zip(_META_BEFORE, _META_AFTER)))
        new = _MODULES_AFTER - _MODULES_BEFORE
        candidate = set(H._module_name(rel) for rel in H.PRODUCTION_PLAN["served"]
                        + H.PRODUCTION_PLAN["lazy_refused"])
        self.assertEqual(new & candidate, set())
        for name in new:
            origin = getattr(sys.modules.get(name), "__file__", None) or ""
            self.assertFalse(H._inside(origin, WORKTREE), name)
        self.assertEqual(_AUX_CALLS_BEFORE, _AUX_CALLS_AFTER)      # zero FS/aux calls
        self.assertEqual(H.INERT_SAMPLER.label, H.INERT_SAMPLER_LABEL)

    def test_hg02_production_main_refuses_first(self):
        expected = {"refused": "HARNESS_DISABLED", "effects": "NONE",
                    "spent_by_this_run": False,
                    "attempt_state": "UNKNOWN_NO_WRITE_BY_THIS_RUN"}
        for argv in ([], Env().argv()):
            with self.subTest(argv=len(argv)):
                read_spy = ReadDepsSpy(lambda: None)
                effect_spy = EffectDepsSpy(lambda: None, lambda: None)
                saved = (H._build_read_deps, H._build_effect_deps, sys.stdout, sys.stderr)
                out, err = io.StringIO(), io.StringIO()
                try:
                    H._build_read_deps, H._build_effect_deps = read_spy, effect_spy
                    sys.stdout, sys.stderr = out, err
                    rc = H.main(argv)
                finally:
                    H._build_read_deps, H._build_effect_deps, sys.stdout, sys.stderr = saved
                self.assertEqual(rc, 3)
                text = out.getvalue()
                self.assertTrue(text.endswith("\n") and text.count("\n") == 1, text)
                self.assertEqual(json.loads(text), expected)
                self.assertEqual(err.getvalue(), "")
                self.assertEqual((read_spy.calls, effect_spy.calls), (0, 0))

    def test_hg03_gate_shape_ast(self):
        tree = harness_tree()
        main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
        self.assertEqual(len(main), 1)
        args = main[0].args
        self.assertEqual([a.arg for a in args.args], ["argv"])
        self.assertEqual((args.vararg, args.kwarg, args.kwonlyargs, args.defaults),
                         (None, None, [], []))
        self.assertEqual(getattr(args, "posonlyargs", []), [])
        want = ast.parse(
            "def f():\n    return _attempt(argv, _Gate(HARNESS_ENABLED, "
            "KNOWN_UNSERVED_NAMES_SHA256), _StdSink(sys.stdout, sys.stderr), "
            "_build_read_deps, _build_effect_deps)\n").body[0].body
        self.assertEqual([ast.dump(n) for n in main[0].body], [ast.dump(n) for n in want])
        names = set(n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)) \
            | set(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
        self.assertEqual(names & {"environ", "getenv", "environb", "putenv"}, set())
        block = ast.parse('if __name__ == "__main__":\n    sys.exit(main(sys.argv))\n').body[0]
        self.assertEqual(ast.dump(tree.body[-1]), ast.dump(block))
        self.assertEqual(sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                             and dotted(n.func) == "main"), 1)

    def test_hg04_forbidden_call_shapes_ast(self):
        tree = harness_tree()
        allow = {"RealReadFS", "RealWriteFS", "RealProcessPort", "_build_read_deps",
                 "_build_effect_deps", "_StdSink"}
        calls = [(owner, dotted(n.func), n) for owner, n in owned_nodes(tree)
                 if isinstance(n, ast.Call)]
        spawn = [(owner, name) for owner, name, _ in calls
                 if name and name.split(".")[-1] == "Popen"]
        self.assertEqual(spawn, [("RealProcessPort", "self.Popen")])
        banned_last = {"kill", "killpg", "terminate", "send_signal", "pidfd_send_signal",
                       "uninstall"}
        for owner, name, _ in calls:
            self.assertNotIn((name or "").split(".")[-1], banned_last, (owner, name))
            self.assertFalse((name or "").startswith(("signal.", "subprocess.")), (owner, name))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= set(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"errno", "hashlib", "importlib.abc", "importlib.machinery",
                                    "importlib.util", "json", "math", "os", "re",
                                    "subprocess", "sys", "time"})
        direct = set("os." + n for n in (
            "open read write fsync fdatasync close mkdir makedirs rmdir remove unlink rename "
            "replace lstat stat listdir scandir getpid kill killpg").split())
        direct |= set("os.path." + n for n in "realpath isdir isfile exists lexists islink".split())
        direct |= {"io.open", "time.time", "time.monotonic", "time.monotonic_ns", "time.sleep",
                   "sys.executable", "subprocess.Popen", "subprocess.run"}
        for owner, node in owned_nodes(tree):
            if owner in allow:
                continue
            if isinstance(node, ast.Attribute):
                self.assertNotIn(dotted(node), direct, owner)
            if isinstance(node, ast.Call):
                self.assertNotEqual(dotted(node.func), "open", owner)
        for node in tree.body:           # module level outside any def/class
            if not hasattr(node, "name"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute):
                        self.assertNotIn(dotted(sub), direct)
        lexists = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "lexists"]
        self.assertEqual(lexists, [])
        builders = [(owner, n) for owner, name, n in calls if name == "NativePortsBuilder"]
        self.assertEqual([owner for owner, _ in builders], ["_production_native_ports_builder"])
        adapter = [k.value for k in builders[0][1].keywords if k.arg == "adapter_cls"]
        want = ast.parse('mods["native_root_port"].P18SysPorts', mode="eval").body
        self.assertEqual([ast.dump(n) for n in adapter], [ast.dump(want)])
        mentions = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                    and n.attr == "P18SysPorts"]
        self.assertEqual(len(mentions), 1)
        seam = [(owner, name) for owner, name, _ in calls
                if name and name.endswith("native_ports_builder")]
        self.assertEqual(seam, [("run_lifecycle", "deps.native_ports_builder")])
        self.assertFalse(hasattr(H.PinnedImportSession, "uninstall"))
        session = [n for n in tree.body if getattr(n, "name", None) == "PinnedImportSession"][0]
        self.assertNotIn("uninstall", [getattr(n, "name", None) for n in session.body])
        literal = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                literal[node.targets[0].id] = node.value
        for name in ("HARNESS_ENABLED", "KNOWN_UNSERVED_NAMES_SHA256", "APPROVAL_SCHEMA",
                     "EVIDENCE_SCHEMA", "RECEIPT_SCHEMA", "EXPECTED_EFFECTS",
                     "FORBIDDEN_EFFECTS", "REQUIRED_APPROVAL_FIELDS", "PRODUCTION_PLAN",
                     "MAX_APPROVAL_BYTES", "MAX_WINDOW_SECONDS", "ATTEMPT_ID_PATTERN",
                     "NAME_PATTERN", "CHILD_ARGV_TAIL", "PASS_MEANING", "NOT_CERTIFIED",
                     "RECEIPT_RULE", "LOADER_LIFETIME", "ATTEMPT_STATES",
                     "REFUSAL_UNIVERSE_RULE", "ABORT_SNAPSHOT_OUTCOMES",
                     "ABORT_SNAPSHOT_RULE", "STOP_RECORD_REDUCED_KEYS"):
            self.assertEqual(ast.literal_eval(literal[name]), getattr(H, name), name)
        top = dict((getattr(n, "name", None), n) for n in tree.body)
        # R1: nothing around the spawn call can reclassify its outcome
        self.assertEqual([n for n in ast.walk(top["run_lifecycle"])
                          if isinstance(n, (ast.Try, ast.ExceptHandler))], [])
        self.assertNotIn("RAISED_NO_CHILD_OBJECT", inspect.getsource(H))
        # R6: the abort snapshot only copies already-recorded plain data
        snapshot_calls = set(dotted(n.func) for n in ast.walk(top["_abort_snapshot"])
                             if isinstance(n, ast.Call))
        self.assertEqual(snapshot_calls, {"dict", "isinstance", "ev.get"})
        abort_calls = set(dotted(n.func) for n in ast.walk(top["_lifecycle_abort"])
                          if isinstance(n, ast.Call))
        self.assertEqual(abort_calls, {
            "life.fail", "_describe", "getattr", "_abort_snapshot", "len", "_serialize",
            "sink.emit_stderr_line", "sink.emit_stdout_line"})

    def test_hg05_enabled_gate_unbound_names(self):
        env = Env()
        env.gate = H._Gate(True, None)
        self.refused(env, "KNOWN_UNSERVED_NAMES_NOT_BOUND")
        self.assertEqual((env.read_spy.calls, env.effect_spy.calls), (0, 0))


# ---------------------------------------------------------------- U: authorization
class AuthorizationTests(Base):
    def case(self, code, mutate=None, argv=None, state=NO_WRITE):
        env = Env()
        if mutate is not None:
            mutate(env)
        line = self.refused(env, code, state, argv(env) if argv is not None else None)
        self.assertEqual(env.effect_spy.calls, 0)
        self.assertEqual(env.wfs.calls, [])
        return env, line

    def test_ha01_arguments(self):
        cases = {"6 args": lambda e: e.argv()[:-1],
                 "duplicate flag": lambda e: ["harness", "--approval", APPROVAL, "--approval",
                                              APPROVAL, "--attempt-id", ATTEMPT],
                 "unknown flag": lambda e: ["harness", "--approval", APPROVAL, "--run-dir",
                                            RUN_DIR, "--attempt", ATTEMPT]}
        for label in sorted(cases):
            with self.subTest(label):
                env, _ = self.case("ARGUMENTS", argv=cases[label])
                self.assertEqual(env.rfs.calls, [])

    def test_ha02_attempt_id_regex(self):
        for label, value in (("lowercase", "nrp3_attempt"), ("65 chars", "A" * 65),
                             ("trailing newline", ATTEMPT + "\n")):
            with self.subTest(label):
                self.case("ATTEMPT_ID_INVALID", argv=lambda e, v=value: e.argv()[:-1] + [v])
        self.assertIsNotNone(H.ATTEMPT_ID_RE.fullmatch("A" * 64))

    def test_ha03_approval_path(self):
        def with_path(path):
            return lambda e: ["harness", "--approval", path, "--run-dir", RUN_DIR,
                              "--attempt-id", ATTEMPT]

        def link(env):
            env.os.links[APPROVAL] = ROOT + "/elsewhere/approval.json"

        def big(env):
            env.raw_approval = b" " * 65537
        self.case("PATH_NOT_ABSOLUTE", argv=with_path("approval/approval.json"))
        self.case("PATH_NOT_NORMALIZED_REAL",
                  argv=with_path(ROOT + "/approval/../approval/approval.json"))
        self.case("PATH_NOT_NORMALIZED_REAL", mutate=link)
        env, _ = self.case("APPROVAL_TOO_LARGE", mutate=big)
        self.assertIn(("read_bytes", APPROVAL, H.MAX_APPROVAL_BYTES), env.rfs.calls)
        for name in ("create_exclusive", "mkdir", "fsync_dir", "write"):
            self.assertFalse(hasattr(env.rfs, name))
            self.assertFalse(hasattr(env.read_spy.results[0], name))

    def test_ha04_strict_json(self):
        for label, raw in (("duplicate key", b'{"schema": 1, "schema": 2}'),
                           ("NaN", b'{"schema": NaN}'), ("Infinity", b'{"schema": Infinity}')):
            with self.subTest(label):
                self.case("APPROVAL_JSON", mutate=lambda e, r=raw: setattr(e, "raw_approval", r))

    def test_ha05_schema_fields_attempt(self):
        cases = (("APPROVAL_SCHEMA", lambda e: e.approval.update(
                      schema="SplitAlignerR/NRP3RootCanaryApproval/v2")),
                 ("APPROVAL_DISABLED", lambda e: e.approval.update(enabled=False)),
                 ("APPROVAL_FIELD_MISSING",
                  lambda e: e.approval.pop("known_unserved_candidate_names")),
                 ("ATTEMPT_ID_MISMATCH", lambda e: e.approval.update(attempt_id="OTHER")))
        for code, mutate in cases:
            with self.subTest(code):
                self.case(code, mutate=mutate)

    def test_ha06_time_window(self):
        cases = (("bool t0", lambda e: e.approval.update(approved_utc=True)),
                 ("float t1", lambda e: e.approval.update(expires_utc=float(T0 + 3600))),
                 ("window 86401", lambda e: e.approval.update(expires_utc=T0 + 86401)),
                 ("now == t1", lambda e: setattr(e.now, "value", T0 + 3600)),
                 ("now < t0", lambda e: setattr(e.now, "value", T0 - 1)))
        for label, mutate in cases:
            with self.subTest(label):
                env, _ = self.case("TIME_WINDOW", mutate=mutate)
                self.assertEqual(env.sleep.calls, [])
        env = Env()
        env.now.value = T0                              # boundary now == t0 accepted
        self.passed(env)
        self.assertEqual(env.effect_spy.calls, 1)
        self.assertGreaterEqual(env.now.calls, 1)

    def test_ha07_roots_and_run_dir(self):
        def ledger_link(env):
            env.os.links[LEDGER] = ROOT + "/other_ledger"

        def run_dir_error(env):
            env.rfs.lstat_script[RUN_DIR] = [("ERROR", errno.EACCES)]

        def harness_inside(env):
            env.harness_path = CAND + "/harness_copy.py"
        self.case("PATH_NOT_NORMALIZED_REAL", mutate=ledger_link)
        self.case("RUN_DIR_NOT_FRESH_OR_UNKNOWN", mutate=lambda e: e.os.dirs.add(RUN_DIR))
        self.case("RUN_DIR_NOT_FRESH_OR_UNKNOWN", mutate=run_dir_error)
        env, _ = self.case("PATH_INSIDE_PROTECTED_ROOT",
                           mutate=lambda e: e.approval.update(protected_roots=[RUNS]))
        self.assertIn(("isdir", RUNS), env.rfs.calls)
        self.assertIn(("listdir", RUNS), env.rfs.calls)
        self.case("ROOTS_NOT_INDEPENDENT", mutate=harness_inside)
        self.case("INTERPRETER_MISMATCH",
                  mutate=lambda e: setattr(e, "exe", ROOT + "/bin/other_python"))

    def test_ha08_effects_names_harness_pin(self):
        def effects(env):
            env.approval["effects"] = list(H.EXPECTED_EFFECTS[:-1]) + ["EXTRA"]

        def unsorted(env):
            env.approval["known_unserved_candidate_names"] = list(reversed(FIXTURE_NAMES))

        def other(env):
            env.approval["known_unserved_candidate_names"] = ["nrp3hfx_other"]

        def overlap(env):
            env.declare(sorted(FIXTURE_NAMES + ["nrp3hfx_u_a"]))

        def lazy_listed(env):                       # lazy names are never declared (R2)
            env.declare(sorted(FIXTURE_NAMES + ["nrp3hfx_u_lazy"]))
        self.case("EFFECTS_MISMATCH", mutate=effects)
        self.case("KNOWN_UNSERVED_NAMES_MISMATCH", mutate=unsorted)
        self.case("KNOWN_UNSERVED_NAMES_MISMATCH", mutate=other)
        _, line = self.case("SERVED_NAME_LISTED_AS_UNSERVED", mutate=overlap)
        self.assertEqual(line["detail"], "nrp3hfx_u_a")
        _, line = self.case("LAZY_REFUSED_NAME_LISTED_AS_DECLARED", mutate=lazy_listed)
        self.assertEqual(line["detail"], "nrp3hfx_u_lazy")
        env, _ = self.case("HARNESS_HASH_MISMATCH",
                           mutate=lambda e: e.approval.update(harness_sha256="0" * 64))
        self.assertIn(("read_bytes", HARNESS_PATH, None), env.rfs.calls)

    def test_ha09_candidate_files(self):
        def missing(env):
            env.approval["candidate_files"].pop("fx/nrp3hfx_u_lazy.py")
            env.repin()

        def changed(env):
            env.os.files[CAND + "/fx/nrp3hfx_u_port.py"] = b"PORT = 2\n"
        self.case("CANDIDATE_FILES_INCOMPLETE", mutate=missing)
        self.case("CANDIDATE_MANIFEST_MISMATCH",
                  mutate=lambda e: e.approval.update(candidate_manifest_sha256="0" * 64))
        self.case("PORT_MODULE_PIN_MISMATCH",
                  mutate=lambda e: e.approval.update(port_module_sha256="1" * 64))
        env, line = self.case("CANDIDATE_FILE_HASH_MISMATCH", mutate=changed)
        self.assertEqual(line["detail"], "fx/nrp3hfx_u_port.py")
        valid = Env()
        self.passed(valid)
        before_t2 = valid.rfs.calls[:valid.rfs.calls.index(("lstat", MARKER))]
        for rel in U_SOURCES:                       # all candidate_files re-read
            self.assertIn(("read_bytes", CAND + "/" + rel, None), before_t2)

    def test_ha10_marker_at_authorization(self):
        self.case("ATTEMPT_ALREADY_CONSUMED", state=(False, "ALREADY_SPENT_PRIOR_RUN"),
                  mutate=lambda e: e.os.files.update({MARKER: b"prior"}))

        def error(env):
            env.rfs.lstat_script[MARKER] = [("ERROR", errno.EACCES)]
        _, line = self.case("LEDGER_MARKER_STATE_UNKNOWN", mutate=error)
        self.assertEqual(line["note"], "not retryable")

    def test_ha11_order_tiers_and_positive(self):
        def two(env):
            env.approval.update(schema="bad", attempt_id="OTHER")

        def two_later(env):
            env.approval.update(effects=["X"], harness_sha256="0" * 64)
        self.case("APPROVAL_SCHEMA", mutate=two)
        self.case("EFFECTS_MISMATCH", mutate=two_later)
        env = Env()
        env.read_spy.error = RuntimeError("fake read deps failure")
        line = self.refused(env, "READ_DEPS_CONSTRUCTION_FAILED")
        self.assertIn("fake read deps failure", line["detail"])
        self.assertEqual((env.read_spy.calls, env.effect_spy.calls), (1, 0))
        env = Env()
        self.passed(env)
        self.assertEqual((env.read_spy.calls, env.effect_spy.calls), (1, 1))
        approval, read_deps = env.effect_spy.args[0]
        self.assertEqual(approval["attempt_id"], ATTEMPT)
        self.assertIn("_approval_sha256", approval)             # authorization had returned
        self.assertIs(read_deps, env.read_spy.results[0])
        self.assertEqual(env.effect_spy.snapshots, [(0, 0, 0)])  # no write/sink use before T2
        for deps in (read_deps, env.effect_spy.results[0]):
            for value in vars(deps).values():
                self.assertNotIsInstance(value, H._StdSink)
                self.assertFalse(hasattr(value, "emit_stdout_line"))


# ---------------------------------------------------------------- U: consume
class ConsumeTests(Base):
    def test_hc01_create_exclusive_success(self):
        env = Env()
        env.os.short_write = 7
        evidence = self.passed(env)
        k = env.os
        opens = k.named("open", MARKER)
        self.assertEqual(len(opens), 1)
        flags = k.O_WRONLY | k.O_CREAT | k.O_EXCL | k.O_NOFOLLOW | k.O_CLOEXEC
        self.assertEqual(opens[0], ("open", MARKER, flags, 0o444))
        self.assertEqual(k.modes[MARKER], 0o444)
        payload = json.loads(k.files[MARKER].decode("utf-8"))
        self.assertEqual(payload, {
            "attempt_id": ATTEMPT, "harness_id": H.HARNESS_ID,
            "harness_sha256": env.approval["harness_sha256"],
            "approval_sha256": sha(k.files[APPROVAL]), "consumed_unix": T0 + 10})
        marker_fd = [fd for fd, row in k.fds.items() if row[0] == MARKER][0]
        writes = [c for c in k.calls if c[0] == "write" and c[1] == marker_fd]
        self.assertGreater(len(writes), 1)                       # short writes looped
        self.assertEqual(sum(min(7, c[2]) for c in writes), len(k.files[MARKER]))
        self.assertEqual(len([c for c in k.calls if c[:2] == ("fsync", marker_fd)]), 1)
        self.assertEqual(len(k.named("close", MARKER)), 1)
        self.assertEqual(len([c for c in k.calls if c[0] == "fsync" and c[2:] == ("dir", LEDGER)]), 1)
        self.assertEqual(evidence["marker"]["progress"]["fd_obtained"], True)
        self.assertEqual(evidence["marker"]["progress"]["stage"], "DONE")

    def test_hc02_truth_table_rows_6_to_10(self):
        def row10(env):
            env.os.fail("OPEN", ".CONSUMED", OSError(errno.EIO, "fake io"))
            env.rfs.lstat_script[MARKER] = [("ENOENT", None), ("ENOENT", None),
                                            ("ERROR", errno.EIO)]
        cases = (
            ("row6", 3, (False, "ALREADY_SPENT_PRIOR_RUN"), "ATTEMPT_ALREADY_CONSUMED",
             lambda e: e.os.fail("OPEN", ".CONSUMED", FileExistsError(errno.EEXIST, "x"))),
            ("row7", 3, (False, "UNSPENT_CONFIRMED_ABSENT"), "LEDGER_UNWRITABLE_NOTHING_CREATED",
             lambda e: e.os.fail("OPEN", ".CONSUMED", PermissionError(errno.EACCES, "x"))),
            ("row8", 2, ("UNKNOWN", "POSSIBLY_SPENT_THIS_RUN"),
             "CONSUMPTION_MARKER_PRESENT_ORIGIN_UNKNOWN",
             lambda e: e.os.fail("OPEN_AFTER_CREATE", ".CONSUMED", KeyboardInterrupt("fake"))),
            ("row9 write", 2, SPENT, "CONSUMPTION_MARKER_INCOMPLETE_ATTEMPT_SPENT",
             lambda e: e.os.fail("WRITE", ".CONSUMED", OSError(errno.EIO, "fake io"))),
            ("row9 interrupt", 2, SPENT, "CONSUMPTION_MARKER_INCOMPLETE_ATTEMPT_SPENT",
             lambda e: setattr(e.wfs, "interrupt_after", ".CONSUMED")),
            ("row10", 2, ("UNKNOWN", "POSSIBLY_SPENT_THIS_RUN"),
             "CONSUMPTION_MARKER_STATE_UNKNOWN_POSSIBLY_SPENT", row10))
        for label, exit_code, state, code, mutate in cases:
            with self.subTest(label):
                env = Env()
                mutate(env)
                rc = env.run()
                self.assertEqual(rc, exit_code)
                if exit_code == 3:
                    self.refused(env, code, state, rc=rc)
                else:
                    receipt, record = env.receipt(), env.stop_record()
                    for row in (receipt, record):
                        self.assertEqual((row["spent_by_this_run"], row["attempt_state"]), state)
                        self.assertEqual(row["primary"]["code"], code)
                    self.assertEqual(receipt["verdict"], "STOP")
                self.assertEqual(len(env.os.named("open", MARKER)), 1)       # never retried
                self.assertEqual(env.wfs.calls.count(("create_exclusive", MARKER)), 1)
                self.assertEqual(set(c[0] for c in env.os.calls)
                                 - {"open", "write", "fsync", "close", "mkdir"}, set())
                self.assertNotIn(EVIDENCE, env.os.files)
                self.assertEqual(env.session_factory.installed, False)

    def test_hc03_first_error_kept_close_separate(self):
        for stage in ("WRITE", "FSYNC"):
            with self.subTest(stage):
                env = Env()
                env.os.fail(stage, ".CONSUMED", OSError(errno.EIO, "FIRST_" + stage))
                env.os.fail("CLOSE", ".CONSUMED", OSError(errno.EBADF, "CLOSE_ERROR"))
                self.assertEqual(env.run(), 2)
                record = env.stop_record()
                progress = record["marker"]["progress"]
                self.assertEqual(progress["stage"], stage)
                self.assertIn("FIRST_" + stage, progress["first_error"]["text"])
                self.assertIn("CLOSE_ERROR", progress["close_error"]["text"])
                self.assertEqual(progress["fd_state"],
                                 "CLOSE_FAILED_FD_STATE_UNCERTAIN_NOT_RETRIED")
                self.assertEqual(record["primary"]["type"], "PublishFailure")
                self.assertIn("FIRST_" + stage, record["primary"]["chain"][1])
                self.assertEqual(len(env.os.named("close", MARKER)), 1)

    def test_hc04_two_field_consistency(self):
        def row1(env):
            env.gate = H._Gate(False, None)

        def row3(env):
            env.rfs.lstat_script[MARKER] = [("ENOENT", None), ("PRESENT", None)]

        def row4(env):
            env.rfs.lstat_script[MARKER] = [("ENOENT", None), ("ERROR", errno.EACCES)]
        cases = (
            (1, row1, (False, "UNKNOWN_NO_WRITE_BY_THIS_RUN"), 3),
            (3, row3, (False, "ALREADY_SPENT_PRIOR_RUN"), 3),
            (4, row4, (False, "UNKNOWN_NO_WRITE_BY_THIS_RUN"), 3),
            (7, lambda e: e.os.fail("OPEN", ".CONSUMED", PermissionError(errno.EACCES, "x")),
             (False, "UNSPENT_CONFIRMED_ABSENT"), 3),
            (8, lambda e: e.os.fail("OPEN_AFTER_CREATE", ".CONSUMED", KeyboardInterrupt("f")),
             ("UNKNOWN", "POSSIBLY_SPENT_THIS_RUN"), 2),
            (11, lambda e: setattr(e.process, "communicate_script", (b"NRP3_CHILD_DONE\n", 1)),
             SPENT, 2),
            (12, lambda e: None, SPENT, 0))
        for row, mutate, state, exit_code in cases:
            with self.subTest(row=row):
                env = Env()
                mutate(env)
                self.assertEqual(env.run(), exit_code)
                records = env.sink.out() + env.sink.err()
                if env.evidence_bytes() is not None:
                    records.append(env.evidence())
                self.assertEqual(len(records), {3: 1, 2: 2, 0: 2}[exit_code] + (row == 11))
                for record in records:
                    self.assertEqual((record["spent_by_this_run"], record["attempt_state"]),
                                     state, record.get("record"))
                    self.assertIn(record["attempt_state"], H.ATTEMPT_STATES)


# ---------------------------------------------------------------- U: lifecycle
class LifecycleTests(Base):
    CHILD_ROW = {"resource": "child_process", "pid": FAKE_CHILD_PID,
                 "state": "NOT_REAPED_NOTHING_SENT",
                 "after_harness_exit": "REPARENTED_REAPING_UNOBSERVED"}
    PIPE_ROW = {"resource": "parent_stdout_read_end", "pid": FAKE_CHILD_PID,
                "state": "LEFT_OPEN_CHILD_UNREAPED",
                "released": "BY_KERNEL_AT_HARNESS_EXIT_UNOBSERVED"}

    def wait_case(self, make_error, abort):
        """R6 shared setup: the child is known and unreaped (communicate timed
        out), the cleanup wait raises; optionally the fake clock aborts later."""
        env = Env()
        env.process.communicate_script = subprocess.TimeoutExpired("child", 10.0)
        env.process.wait_script = make_error()
        if abort:
            env.process.on_wait = lambda: setattr(env.clock, "armed",
                                                  KeyboardInterrupt("fake outer"))
        return env, env.run()

    def wait_counts(self, env):
        """Exact call counts: one wait, one context close, stdin closed once,
        stdout never closed, one spawn, nothing sent."""
        self.assertEqual(env.process.wait_calls, [10.0])
        self.assertEqual(env.process.communicate_calls, [(b"", 10.0)])
        self.assertEqual(env.context.close_calls, [5.0])
        self.assertEqual(env.log.count("ctx.close"), 1)
        self.assertEqual((env.process.stdin.close_calls, env.process.stdout.close_calls),
                         (1, 0))
        self.assertEqual(len(env.port.argvs), 1)
        self.assertEqual(env.process.forbidden, 0)
        self.assertEqual(env.sleep.calls, [])

    def wait_ownership(self, kind, custody, unresolved):
        """Child and pipe are separate rows; the child registered at SPAWN is
        still there after the wait raised (it was never confirmed reaped)."""
        self.assertEqual(unresolved, [self.CHILD_ROW, self.PIPE_ROW])
        self.assertEqual(custody["spawn_state"], "RETURNED")
        self.assertEqual(custody["child"], {"pid": FAKE_CHILD_PID,
                                            "state": "NOT_REAPED_WAIT_RAISED:" + kind})
        self.assertEqual(custody["pipes"], {"stdin": "CLOSED_BY_CLEANUP",
                                            "stdout": "LEFT_OPEN_CHILD_UNREAPED"})
        self.assertEqual(custody["context"], "CLOSE_RETURNED:CLOSED")
        self.assertEqual(custody["wait_error"]["type"], kind)

    def test_hl01_happy_path_fake_ports(self):
        env = Env()
        evidence = self.passed(env)
        phases = [row["phase"] for row in evidence["phases"]]
        self.assertEqual(tuple(phases[:len(H.PHASE_SEQUENCE)]), H.PHASE_SEQUENCE)
        self.assertEqual(phases[len(H.PHASE_SEQUENCE):],
                         ["CLEANUP", "IMPORT_END_CHECK_1", "FINAL_DECISION", "PUBLISH",
                          "IMPORT_END_CHECK_2", "SERIALIZE_EVIDENCE"])
        self.assertEqual(evidence["outcomes"]["first_close"], "CLOSED")
        self.assertEqual(evidence["outcomes"]["second_close"], "ALREADY_CLOSED")
        self.assertTrue(evidence["checks"])
        self.assertEqual(set(evidence["checks"].values()), {True})
        self.assertEqual(env.sink.o.text.count("\n"), 1)
        self.assertEqual(env.sink.e.text, "")
        receipt = env.receipt()
        self.assertEqual(receipt["verdict"], "PASS")
        self.assertEqual(receipt["evidence_file"]["sha256"], sha(env.evidence_bytes()))
        self.assertEqual(receipt["loader_lifetime"], H.LOADER_LIFETIME)
        self.assertEqual(evidence["loader_lifetime"], "RETAINED_AT_META_PATH_0_UNTIL_PROCESS_EXIT")
        self.assertEqual(evidence["pass_meaning"], H.PASS_MEANING)
        self.assertEqual(env.session_factory.end_calls, 2)
        self.assertEqual(env.port.argvs, [[INTERP] + list(H.CHILD_ARGV_TAIL)])
        self.assertEqual(len(env.builder_calls), 1)
        self.assertIs(env.builder_calls[0][2], env.port)
        decision = H.receipt_authority_decision(0, env.sink.o.text, env.evidence_bytes())
        self.assertEqual(decision["decision"], "PASS")

    def test_hl02_root_not_acquired_effect_shape(self):
        def effect(identity, custody):
            return {"attempted_effect": "SPAWN_RETURNED_PROCESS_OBJECT",
                    "observed_root": {"pid": FAKE_CHILD_PID, "returncode_at_attach": None},
                    "root_authority_state": "ACQUIRED", "custody": custody,
                    "identity": identity, "controller_phase": "POST_SPAWN:ROOT_ACQUISITION"}
        cases = (
            ("ROOT_NOT_ACQUIRED_NO_FALLBACK",
             lambda e: setattr(e.context, "attach_state", "UNAVAILABLE:FAKE_REFUSAL")),
            ("EFFECT_NOT_OPTION_B_SHAPE", lambda e: setattr(e.ports, "effect", effect(
                {"token": "t", "provenance": "MODELED_INJECTED"}, "REGISTERED"))),
            ("EFFECT_NOT_OPTION_B_SHAPE",
             lambda e: setattr(e.ports, "effect", effect(None, "NOT_REGISTERED"))),
            (None, lambda e: setattr(e.ports, "validate_error",
                                     ValueError("EFFECT_EVIDENCE_INVALID"))))
        for index, (code, mutate) in enumerate(cases):
            with self.subTest(index=index):
                env = Env()
                mutate(env)
                record = self.stopped(env)
                self.assertEqual(record["primary"]["code"], code)
                if code is None:
                    self.assertEqual(record["primary"]["type"], "ValueError")
                self.assertEqual(len(env.context.close_calls), 1)       # cleanup once
                self.assertEqual(record["outcomes"]["cleanup_context_close"], "CLOSED")
                self.assertEqual(len(env.port.argvs), 1)                # no fallback spawn

    def test_hl03_natural_completion_timeout(self):
        env = Env()
        env.process.communicate_script = subprocess.TimeoutExpired("child", 10.0)
        env.process.wait_script = subprocess.TimeoutExpired("child", 10.0)
        record = self.stopped(env)
        self.assertEqual(record["primary"]["type"], "TimeoutExpired")
        outcomes = record["outcomes"]
        self.assertEqual(outcomes["cleanup_stdin"], "CLOSED_BY_CLEANUP")
        self.assertEqual(outcomes["cleanup_wait"], "UNRESOLVED_CHILD_NOT_REAPED:TimeoutExpired")
        self.assertEqual(outcomes["cleanup_stdout"], "LEFT_OPEN_CHILD_UNREAPED")
        resources = [row["resource"] for row in record["unresolved_ownership"]]
        self.assertIn("child_process", resources)
        self.assertEqual(env.process.forbidden, 0)
        self.assertFalse(env.process.stdout.closed)
        self.assertEqual(env.process.stdout.close_calls, 0)
        self.assertEqual(env.process.wait_calls, [10.0])

    def test_hl04_close_outcomes(self):
        env = Env()
        env.context.close_script = ["CUSTODY_UNRESOLVED:FAKE"]
        record = self.stopped(env)
        self.assertEqual(record["primary"]["code"], "FIRST_CLOSE_NOT_CLOSED")
        self.assertEqual(len(env.context.close_calls), 1)
        self.assertNotIn("second_close", record["outcomes"])
        self.assertEqual(record["outcomes"]["cleanup_context_close"],
                         "NOT_CALLED_FIRST_CLOSE_ALREADY_ATTEMPTED")
        env = Env()
        env.context.close_script = ["CLOSED", "CLOSED"]
        record = self.stopped(env)
        self.assertEqual(record["primary"]["code"], "SECOND_CLOSE_NOT_ALREADY_CLOSED")
        self.assertEqual(len(env.context.close_calls), 2)

    def test_hl05_close_once_all_paths(self):
        def abort(env):
            env.process.communicate_script = KeyboardInterrupt("fake first")
            env.process.wait_script = KeyboardInterrupt("fake second")
            env.process.on_wait = lambda: setattr(env.clock, "armed",
                                                  KeyboardInterrupt("fake outer"))
        cases = (("normal", lambda e: None, 2, 0),
                 ("before FIRST_CLOSE",
                  lambda e: setattr(e.context, "admit_error", RuntimeError("fake")), 1, 2),
                 ("in FIRST_CLOSE",
                  lambda e: setattr(e.context, "close_script", [RuntimeError("fake")]), 1, 2),
                 ("abort in cleanup", abort, 1, 2))
        for label, mutate, closes, exit_code in cases:
            with self.subTest(label):
                env = Env()
                mutate(env)
                self.assertEqual(env.run(), exit_code)
                self.assertEqual(len(env.context.close_calls), closes)
                self.assertEqual(env.log.count("ctx.close"), closes)
        for kind, make_error in WAIT_ERRORS:            # R6 bounded 8: exact counts
            for abort in (False, True):
                with self.subTest(wait=kind, abort=abort):
                    env, rc = self.wait_case(make_error, abort)
                    self.assertEqual(rc, 2)
                    self.wait_counts(env)
                    self.assertEqual(env.session_factory.end_calls, 0 if abort else 2)
                    self.assertEqual(EVIDENCE in env.os.files, not abort)

    def test_hl06_spawn_failures(self):
        row = {"resource": "possible unrecorded child", "pid": None,
               "state": "SPAWN_OUTCOME_UNKNOWN_NO_WAIT_ON_UNKNOWN_PID"}
        for kind, make_error in SPAWN_ERRORS:           # R1 bounded 8
            for mode in SPAWN_MODES:
                with self.subTest(error=kind, mode=mode):
                    env = Env()
                    env.port.mode, env.port.error = mode, make_error()
                    self.assertEqual(type(env.port.error).__name__, kind)   # exact type
                    record = self.stopped(env)
                    self.assertEqual(env.receipt()["exit"], 2)
                    primary = record["primary"]
                    self.assertEqual((primary["type"], primary["phase"]), (kind, "SPAWN"))
                    self.assertIn(str(env.port.error) or kind, primary["text"])
                    self.assertEqual(record["secondary"], [])
                    # the outcome stays unknown for every type, before or after creation
                    custody = record["custody"]
                    self.assertEqual(custody["spawn_state"], "CALLED_OUTCOME_UNKNOWN")
                    self.assertEqual(custody["child"], {"pid": None, "state": "NO_CHILD_KNOWN"})
                    self.assertEqual(custody["pipes"], {"stdin": "SPAWN_OUTCOME_UNKNOWN",
                                                        "stdout": "SPAWN_OUTCOME_UNKNOWN"})
                    self.assertEqual(record["unresolved_ownership"], [row])
                    self.assertEqual(record["checks"]["no_unresolved_ownership"], False)
                    outcomes = record["outcomes"]
                    self.assertEqual(outcomes["cleanup_stdin"], "NO_PROCESS")
                    self.assertEqual(outcomes["cleanup_wait"], "SPAWN_OUTCOME_UNKNOWN")
                    self.assertEqual(outcomes["cleanup_stdout"], "NO_OPEN_STDOUT")
                    self.assertNotIn("child_pid", outcomes)
                    # no guessed pid: nothing waited, closed, signalled or retried
                    self.assertNotIn(str(FAKE_CHILD_PID), json.dumps(record["custody"])
                                     + json.dumps(record["unresolved_ownership"]))
                    self.assertEqual(env.process.wait_calls, [])
                    self.assertEqual(env.process.communicate_calls, [])
                    self.assertEqual((env.process.stdin.close_calls,
                                      env.process.stdout.close_calls), (0, 0))
                    self.assertEqual(env.process.forbidden, 0)
                    self.assertEqual(len(env.port.argvs), 1)               # no retry
                    self.assertEqual(len(env.port.created),
                                     1 if mode == "CREATE_THEN_RAISE" else 0)
                    # close-once: the context is closed exactly once, by cleanup
                    self.assertEqual(outcomes["cleanup_context_close"], "CLOSED")
                    self.assertEqual(env.context.close_calls, [5.0])
                    self.assertEqual(custody["context"], "CLOSE_RETURNED:CLOSED")
                    self.assertEqual(env.session_factory.end_calls, 2)

    def test_hl07_interrupts(self):
        for name in ("admit_error", "attach_error"):
            with self.subTest(name):
                env = Env()
                setattr(env.context, name, KeyboardInterrupt("fake " + name))
                record = self.stopped(env)
                self.assertEqual(record["primary"]["type"], "KeyboardInterrupt")
                self.assertEqual(len(env.context.close_calls), 1)
                self.assertIn("route_report", record["outcomes"])
                self.assertEqual(env.session_factory.end_calls, 2)
        env = Env()
        env.process.communicate_script = KeyboardInterrupt("fake first")
        env.process.wait_script = KeyboardInterrupt("fake second")
        env.process.on_wait = lambda: setattr(env.clock, "armed", KeyboardInterrupt("fake outer"))
        self.assertEqual(env.run(), 2)
        self.assertEqual(env.sink.o.text, "")
        records = env.sink.err()
        self.assertEqual(len(records), 1)
        abort = records[0]
        self.assertEqual(abort["record"], "NRP3_LIFECYCLE_ABORTED")
        self.assertEqual((abort["verdict"], abort["pass_meaning"]), ("STOP", None))
        self.assertEqual((abort["spent_by_this_run"], abort["attempt_state"]), SPENT)
        self.assertEqual(abort["primary"]["type"], "KeyboardInterrupt")
        self.assertIn("fake first", abort["primary"]["text"])
        self.assertEqual([row["phase"] for row in abort["secondary"]],
                         ["GUARDED:cleanup_wait", "LIFECYCLE_ABORT"])
        self.assertTrue(env.session_factory.installed)          # never removed
        self.assertFalse(hasattr(env.session_factory, "uninstall"))
        self.assertEqual(env.process.forbidden, 0)
        self.assertEqual(abort["snapshot"]["unresolved_ownership"],
                         [self.CHILD_ROW, self.PIPE_ROW])
        for kind, make_error in WAIT_ERRORS:            # R6 bounded 8: ownership
            base = kind in ("KeyboardInterrupt", "SystemExit")
            guarded = ["GUARDED:cleanup_wait"] if base else []
            wait_outcome = "RAISED" if base else "UNRESOLVED_CHILD_NOT_REAPED:" + kind
            for later_abort in (False, True):
                with self.subTest(wait=kind, abort=later_abort):
                    env, rc = self.wait_case(make_error, later_abort)
                    self.assertEqual(type(env.process.wait_script).__name__, kind)
                    self.assertEqual(rc, 2)
                    self.wait_counts(env)
                    self.assertIn(MARKER, env.os.files)                 # spent
                    if not later_abort:
                        record = self.stopped(env, rc=rc)
                        self.wait_ownership(kind, record["custody"],
                                            record["unresolved_ownership"])
                        self.assertEqual(record["outcomes"]["cleanup_wait"], wait_outcome)
                        self.assertEqual(record["outcomes"]["cleanup_stdout"],
                                         "LEFT_OPEN_CHILD_UNREAPED")
                        self.assertEqual((record["primary"]["type"], record["primary"]["phase"]),
                                         ("TimeoutExpired", "NATURAL_COMPLETION"))
                        self.assertEqual([r["phase"] for r in record["secondary"]], guarded)
                        self.assertEqual([r["type"] for r in record["secondary"]],
                                         [kind] if base else [])
                        self.assertEqual(record["checks"]["no_unresolved_ownership"], False)
                        self.assertEqual(len(env.sink.err()), 1)
                        continue
                    self.assertEqual(env.sink.o.text, "")
                    records = env.sink.err()
                    self.assertEqual([r["record"] for r in records], ["NRP3_LIFECYCLE_ABORTED"])
                    abort = records[0]
                    self.assertEqual((abort["verdict"], abort["exit"], abort["pass_meaning"]),
                                     ("STOP", 2, None))
                    self.assertEqual((abort["spent_by_this_run"], abort["attempt_state"]), SPENT)
                    self.assertIs(abort["evidence_complete"], False)
                    self.assertEqual(abort["snapshot_rule"], H.ABORT_SNAPSHOT_RULE)
                    self.assertEqual((abort["sink"], abort["snapshot_error"]), ("STDERR", None))
                    self.assertEqual(abort["abort_error"]["type"], "KeyboardInterrupt")
                    self.assertIn("fake outer", abort["abort_error"]["text"])
                    # original error first, then the guarded one, then the abort
                    self.assertEqual((abort["primary"]["type"], abort["primary"]["phase"]),
                                     ("TimeoutExpired", "NATURAL_COMPLETION"))
                    self.assertEqual([r["phase"] for r in abort["secondary"]],
                                     guarded + ["LIFECYCLE_ABORT"])
                    self.assertEqual([r["type"] for r in abort["secondary"]],
                                     ([kind] if base else []) + ["KeyboardInterrupt"])
                    snapshot = abort["snapshot"]
                    self.wait_ownership(kind, snapshot["custody"],
                                        snapshot["unresolved_ownership"])
                    self.assertEqual(snapshot["phase"], "IMPORT_END_CHECK_1")
                    self.assertEqual(snapshot["phases"][-1], "CLEANUP")
                    recorded = snapshot["recorded_outcomes"]
                    self.assertEqual(set(recorded), {
                        "child_pid", "cleanup_stdin", "cleanup_wait", "cleanup_stdout",
                        "cleanup_context_close", "context_state", "route_report"})
                    self.assertEqual(recorded["cleanup_wait"], wait_outcome)
                    self.assertEqual(recorded["child_pid"], FAKE_CHILD_PID)
                    self.assertEqual(recorded["context_state"]["closed"], True)
                    self.assertEqual(recorded["route_report"], env.context.route)
                    self.assertEqual((snapshot["run_dir_created"],
                                      snapshot["first_close_called"]), (True, True))
                    self.assertEqual(snapshot["marker"]["progress"]["stage"], "DONE")
                    self.assertIsNone(snapshot["publish_progress"])
                    self.assertNotIn(EVIDENCE, env.os.files)
                    # the snapshot was built from recorded data: no new port/context call
                    self.assertEqual(env.log.count("ctx.termination.report"), 1)
                    self.assertEqual(env.session_factory.end_calls, 0)
        for sample in SINK_SAMPLES:                     # abort record sinks (2 samples)
            with self.subTest(sink=sample):
                env = Env()
                env.process.communicate_script = subprocess.TimeoutExpired("child", 10.0)
                env.process.wait_script = KeyboardInterrupt("fake wait interrupt")
                env.process.on_wait = lambda env=env: setattr(
                    env.clock, "armed", KeyboardInterrupt("fake outer"))
                env.sink.e.error = OSError(errno.EIO, "STDERR_GONE")
                if sample == "BOTH_FAIL":
                    env.sink.o.error = BrokenPipeError(errno.EPIPE, "STDOUT_GONE")
                self.assertEqual(env.run(), 2)                          # never raises
                self.wait_counts(env)
                self.assertEqual(env.sink.e.text, "")
                if sample == "BOTH_FAIL":
                    self.assertEqual(env.sink.o.text, "")               # no record, no claim
                    continue
                lines = env.sink.out()
                self.assertEqual(len(lines), 1)
                fallback = lines[0]
                self.assertEqual(fallback["record"], "NRP3_LIFECYCLE_ABORTED")
                self.assertEqual(fallback["sink"]["stderr"], "FAILED")
                self.assertEqual(fallback["sink"]["this_line"], "STDOUT_FALLBACK_NOT_A_RECEIPT")
                self.assertIn("STDERR_GONE", fallback["sink"]["error"]["text"])
                self.assertIs(fallback["evidence_complete"], False)
                self.assertEqual(fallback["snapshot"]["unresolved_ownership"],
                                 [self.CHILD_ROW, self.PIPE_ROW])
                self.assertEqual([r["phase"] for r in fallback["secondary"]],
                                 ["GUARDED:cleanup_wait", "LIFECYCLE_ABORT"])
                for exit_code in (2, 0):                                # never a receipt
                    self.assertEqual(H.receipt_authority_decision(
                        exit_code, env.sink.o.text, None)["decision"], "STOP")

    def test_hl08_first_cause_and_secondaries(self):
        env = Env()
        env.context.admit_error = RuntimeError("LIFECYCLE_FIRST")
        env.context.termination.report_error = RuntimeError("REPORT_SECOND")
        env.session_factory.end_script = {1: H.Stop("IMPORT_END_CHECK_FAILED", "THIRD")}
        env.os.fail("OPEN", "EVIDENCE.json", OSError(errno.ENOSPC, "FOURTH"))
        record = self.stopped(env)
        self.assertIn("LIFECYCLE_FIRST", record["primary"]["text"])
        self.assertEqual(record["primary"]["phase"], "ADMIT")
        self.assertEqual([row["phase"] for row in record["secondary"]],
                         ["GUARDED:route_report", "GUARDED:import_end_check_1",
                          "EVIDENCE_PUBLISH"])
        self.assertEqual(record["outcomes"]["route_report"], "RAISED")
        self.assertEqual(record["outcomes"]["import_end_check_1"], "RAISED")
        self.assertEqual(record["checks"]["port_open_eq_1"], False)   # final_decision ran
        self.assertEqual(record["checks"]["import_end_check_1_clean"], False)
        self.assertEqual(env.receipt()["secondary_count"], 3)
        self.assertIn("LIFECYCLE_FIRST", env.receipt()["primary"]["text"])

    def test_hl09_synthetic_check_failed(self):
        env = Env()
        env.process.communicate_script = (b"NRP3_CHILD_DONE\n", 1)
        record = self.stopped(env)
        self.assertEqual(record["primary"]["code"], "CHECK_FAILED")
        self.assertEqual(record["primary"]["text"], "Stop:CHECK_FAILED:child_returncode_0")
        self.assertEqual(record["secondary"], [])
        env = Env()
        env.context.admit_error = RuntimeError("EXISTING_FAILURE")
        record = self.stopped(env)
        codes = [record["primary"]["code"]] + [row["code"] for row in record["secondary"]]
        self.assertNotIn("CHECK_FAILED", codes)
        self.assertIn(False, record["checks"].values())

    def test_hl10_deadlines_and_bounds(self):
        env = Env()
        payload = ("é" * 5000).encode("utf-8")
        env.process.communicate_script = (payload, 0)
        record = self.stopped(env)
        self.assertEqual(env.process.communicate_calls, [(b"", 10.0)])
        self.assertEqual(env.context.close_calls, [5.0, 5.0])
        self.assertEqual(record["outcomes"]["child_stdout_len"], len(payload))
        text = record["outcomes"]["child_stdout"]
        self.assertEqual(text, payload[:4096].decode("ascii", "backslashreplace"))
        self.assertTrue(text.startswith("\\xc3\\xa9"))
        self.assertEqual(env.sleep.calls, [])
        self.assertGreater(env.clock.calls, 0)
        env = Env()
        env.process.communicate_script = subprocess.TimeoutExpired("child", 10.0)
        self.stopped(env)
        self.assertEqual(env.process.wait_calls, [10.0])
        self.assertEqual(env.context.close_calls, [5.0])
        self.assertEqual(env.sleep.calls, [])
        self.assertEqual((H.COMMUNICATE_TIMEOUT_S, H.CLEANUP_WAIT_TIMEOUT_S,
                          H.CLOSE_LOCK_TIMEOUT_S, H.STDOUT_BOUND), (10.0, 10.0, 5.0, 4096))

    def test_hl11_unresolved_port_custody(self):
        env = Env()
        env.context.route["port_custody"] = [{"pid": FAKE_CHILD_PID, "resolved": False,
                                              "custody": "CLOSE_CALLED_OUTCOME_UNKNOWN"}]
        record = self.stopped(env)
        self.assertEqual(record["checks"]["no_unresolved_ownership"], False)
        self.assertEqual(record["checks"]["port_custody_all_closed"], False)
        self.assertEqual(record["unresolved_ownership"], [{
            "resource": "port_custody", "pid": FAKE_CHILD_PID,
            "custody": "CLOSE_CALLED_OUTCOME_UNKNOWN", "state": "PORT_CUSTODY_UNRESOLVED"}])
        self.assertEqual(record["primary"]["code"], "CHECK_FAILED")
        self.assertIn("no_unresolved_ownership", record["primary"]["text"])


# ---------------------------------------------------------------- U: wiring
class WiringTests(Base):
    def test_hw01_real_process_port_fake_popen(self):
        fake = FakePopenCallable()
        port = H.RealProcessPort(fake)
        argv = [INTERP] + list(H.CHILD_ARGV_TAIL)
        self.assertIs(port.spawn_child(argv), fake.result)
        self.assertEqual(len(fake.calls), 1)
        args, kwargs = fake.calls[0]
        self.assertEqual(args, (argv,))
        self.assertEqual(argv[1:4], ["-I", "-S", "-c"])
        self.assertEqual(len(argv), 5)
        self.assertEqual(kwargs, {
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
            "text": False, "bufsize": -1, "shell": False, "start_new_session": True,
            "close_fds": True})

    def test_hw02_real_fs_adapters_fake_os(self):
        k = FakeOs()
        k.dirs.update(["/w", "/w/d"])
        writer, progress = H.RealWriteFS(k), {}
        self.assertIs(writer.create_exclusive("/w/d/file", b"abc", progress), progress)
        flags = k.O_WRONLY | k.O_CREAT | k.O_EXCL | k.O_NOFOLLOW | k.O_CLOEXEC
        dir_flags = k.O_RDONLY | k.O_DIRECTORY | k.O_CLOEXEC
        self.assertEqual(k.calls, [
            ("open", "/w/d/file", flags, 0o444), ("write", 100, 3),
            ("fsync", 100, "w", "/w/d/file"), ("close", 100, "/w/d/file"),
            ("open", "/w/d", dir_flags, 0o777), ("fsync", 101, "dir", "/w/d"),
            ("close", 101, "/w/d")])
        self.assertEqual((progress["stage"], progress["fd_obtained"], progress["fd_state"]),
                         ("DONE", True, "CLOSED"))
        del k.calls[:]
        writer.mkdir("/w/new", 0o700)
        writer.fsync_dir("/w")
        self.assertEqual(k.calls, [("mkdir", "/w/new", 0o700), ("open", "/w", dir_flags, 0o777),
                                   ("fsync", 102, "dir", "/w"), ("close", 102, "/w")])
        del k.calls[:]
        reader = H.RealReadFS(k)
        k.files["/w/big"] = b"x" * 200000
        self.assertEqual(reader.read_bytes("/w/d/file", None), b"abc")
        self.assertEqual(k.calls[0], ("open", "/w/d/file",
                                      k.O_RDONLY | k.O_NOFOLLOW | k.O_CLOEXEC, 0o777))
        self.assertEqual(k.calls[-1][0], "close")
        del k.calls[:]
        bounded = reader.read_bytes("/w/big", 10)
        self.assertTrue(10 < len(bounded) <= 65536)
        self.assertEqual(len(k.named("read")), 1)               # bounded: stops reading
        self.assertEqual(len(k.named("close")), 1)
        self.assertEqual(reader.lstat("/w/d/file"), ("PRESENT", None))
        self.assertEqual(reader.lstat("/w/absent"), ("ENOENT", None))
        k.fail("LSTAT", "/w/denied", PermissionError(errno.EACCES, "fake"))
        self.assertEqual(reader.lstat("/w/denied"), ("ERROR", errno.EACCES))
        k.links["/w/link"] = "/w/d"
        self.assertEqual(reader.realpath("/w/link"), "/w/d")
        self.assertEqual((reader.isdir("/w/d"), reader.isdir("/w/d/file")), (True, False))
        self.assertEqual(reader.listdir("/w"), ["big", "d", "new"])
        for name in ("create_exclusive", "mkdir", "fsync_dir", "write"):
            self.assertFalse(hasattr(reader, name))
        self.assertNotIn("lexists", inspect.getsource(H))


# ---------------------------------------------------------------- U: publication
class PublicationTests(Base):
    def test_hp01_publication_failure_stages(self):
        def partial(env):
            env.os.short_write = 16
            env.os.fail("WRITE", "EVIDENCE.json", OSError(errno.EIO, "fake"), skip=1)

        def inspect_error(env):
            env.os.fail("WRITE", "EVIDENCE.json", OSError(errno.EIO, "fake"))
            env.rfs.lstat_script[EVIDENCE] = [("ERROR", errno.EIO)]
        cases = (
            ("NOT_CREATED",
             lambda e: e.os.fail("OPEN", "EVIDENCE.json", OSError(errno.ENOSPC, "fake"))),
            ("PRESENT_POSSIBLY_PARTIAL", partial),
            ("PRESENT_COMPLETE_BYTES_DIR_FSYNC_FAILED",
             lambda e: e.os.fail("DIR_FSYNC", RUN_DIR, OSError(errno.EIO, "fake"))),
            ("PREEXISTING_NOT_WRITTEN_BY_THIS_RUN",
             lambda e: e.os.fail("OPEN", "EVIDENCE.json", FileExistsError(errno.EEXIST, "f"))),
            ("UNKNOWN_INSPECTION_FAILED", inspect_error),
            ("NOT_CREATED_NO_RUN_DIR",
             lambda e: e.os.fail("MKDIR", RUN_DIR, OSError(errno.EACCES, "fake"))))
        for state, mutate in cases:
            with self.subTest(state):
                env = Env()
                mutate(env)
                record = self.stopped(env)
                receipt = env.receipt()
                for row in (record, receipt):
                    self.assertEqual(row["superseded_file"]["path"], EVIDENCE)
                    self.assertEqual(row["superseded_file"]["state"], state)
                    self.assertEqual(row["superseded_file"]["attempted_sha256"] is not None,
                                     state.startswith("PRESENT"))
                self.assertEqual(receipt["evidence_file"], {"path": EVIDENCE, "state": state,
                                                            "sha256": None})
                self.assertEqual(receipt["exit"], 2)
                attempts = env.wfs.calls.count(("create_exclusive", EVIDENCE))
                self.assertEqual(attempts, 0 if state == "NOT_CREATED_NO_RUN_DIR" else 1)
                self.assertLessEqual(len(env.os.named("open", EVIDENCE)), 1)
                self.assertEqual(H.receipt_authority_decision(
                    2, env.sink.o.text, env.evidence_bytes())["decision"], "STOP")

    def test_hp02_publication_disagreement(self):
        env = Env()
        env.os.fail("DIR_FSYNC", RUN_DIR, OSError(errno.EIO, "fake dir fsync"))
        record = self.stopped(env)
        self.assertEqual(env.session_factory.end_calls, 2)             # end_check #2 passed
        self.assertEqual(record["outcomes"]["import_end_check_2"]["problems"], [])
        on_disk = env.evidence()
        self.assertEqual(on_disk["verdict"], "PASS")                   # the file says PASS
        self.assertEqual((record["verdict"], record["exit_code"], record["pass_meaning"]),
                         ("STOP", 2, None))
        self.assertEqual(record["primary"]["phase"], "EVIDENCE_PUBLISH")
        receipt = env.receipt()
        self.assertEqual(receipt["superseded_file"]["path"], EVIDENCE)
        self.assertEqual(receipt["superseded_file"]["state"],
                         "PRESENT_COMPLETE_BYTES_DIR_FSYNC_FAILED")
        self.assertEqual(receipt["superseded_file"]["attempted_sha256"],
                         sha(env.evidence_bytes()))
        for exit_code in (2, 0):
            decision = H.receipt_authority_decision(exit_code, env.sink.o.text,
                                                    env.evidence_bytes())
            self.assertEqual(decision["decision"], "STOP")

    def test_hp03_stderr_and_receipt_write_failures(self):
        env = Env()
        env.process.communicate_script = (b"NRP3_CHILD_DONE\n", 1)
        env.sink.e.error = OSError(errno.EIO, "STDERR_GONE")
        self.assertEqual(env.run(), 2)
        receipt = env.receipt()
        self.assertEqual(receipt["stderr_stop_record"]["state"], "FAILED")
        self.assertEqual(receipt["stderr_stop_record"]["error"]["type"], "OSError")
        self.assertIn("STDERR_GONE", receipt["stderr_stop_record"]["error"]["text"])
        self.assertEqual(receipt["secondary_count"], 1)
        self.assertEqual(receipt["primary"]["code"], "CHECK_FAILED")
        env = Env()
        env.sink.o.error = BrokenPipeError(errno.EPIPE, "STDOUT_GONE")
        self.assertEqual(env.run(), 2)
        self.assertEqual(env.sink.o.text, "")
        note = env.sink.err()[0]
        self.assertEqual(note["record"], "NRP3_RECEIPT_WRITE_FAILED")
        self.assertEqual(note["error"]["type"], "BrokenPipeError")
        self.assertIn("STDOUT_GONE", note["error"]["text"])
        body = note["unwritten_receipt"]
        self.assertEqual((body["verdict"], body["exit"], body["record"]),
                         ("PASS", 0, "NRP3_CANARY_FINAL_RECEIPT"))
        self.assertEqual(body["evidence_file"]["sha256"], sha(env.evidence_bytes()))
        self.assertEqual(note["evidence_file_superseded"]["path"], EVIDENCE)
        self.assertEqual(H.receipt_authority_decision(2, "", env.evidence_bytes())["decision"],
                         "STOP")
        env = Env()
        env.process.communicate_script = (b"NRP3_CHILD_DONE\n", 1)
        env.sink.e.error = OSError(errno.EIO, "STDERR_GONE")
        env.sink.o.error = BrokenPipeError(errno.EPIPE, "STDOUT_GONE")
        self.assertEqual(env.run(), 2)
        self.assertEqual(env.sink.o.text + env.sink.e.text, "")

    def test_hp04_oversized_stop_record(self):
        small = {"schema": H.EVIDENCE_SCHEMA, "attempt_id": ATTEMPT, "verdict": "STOP",
                 "exit_code": 2, "pass_meaning": None, "spent_by_this_run": True,
                 "attempt_state": "SPENT_THIS_RUN", "primary": {"code": "X"}, "secondary": [],
                 "checks": {}, "unresolved_ownership": [], "receipt_rule": H.RECEIPT_RULE,
                 "outcomes": {"small": "y"}}
        record = H.stop_record_object(small)
        self.assertEqual(record["outcomes"], {"small": "y"})
        self.assertNotIn("reduced", record)
        big = dict(small, outcomes={"big": "x" * (H.MAX_STDERR_RECORD_BYTES + 10)})
        record = H.stop_record_object(big)
        data = H._serialize(record)
        self.assertLessEqual(len(data), H.MAX_STDERR_RECORD_BYTES)
        self.assertEqual(set(record), set(H.STOP_RECORD_REDUCED_KEYS) | {"reduced"})
        self.assertEqual(json.loads(data.decode("utf-8"))["record"], "NRP3_STDERR_STOP_RECORD")
        sink = FakeSink()
        self.assertIsNone(sink.emit_stderr_line(record))
        self.assertEqual(sink.err()[0]["verdict"], "STOP")           # one valid JSON line
        self.assertTrue(sink.e.text.endswith("\n") and sink.e.text.count("\n") == 1)

    def test_hp05_receipt_authority_table(self):
        good = Env()
        self.passed(good)
        stdout, evidence = good.sink.o.text, good.evidence_bytes()
        bad = Env()
        bad.process.communicate_script = (b"NRP3_CHILD_DONE\n", 1)
        self.stopped(bad)
        cases = (("PASS", 0, stdout, evidence),
                 ("STOP", 0, bad.sink.o.text, bad.evidence_bytes()),
                 ("STOP", 0, stdout, evidence + b" "),
                 ("STOP", 0, stdout, None),
                 ("STOP", 0, stdout[:-1], evidence),
                 ("STOP", 0, stdout[:40], evidence),
                 ("STOP", 0, stdout + stdout, evidence),
                 ("STOP", 120, stdout, evidence))
        for index, (want, exit_code, text, data) in enumerate(cases):
            with self.subTest(index=index):
                decision = H.receipt_authority_decision(exit_code, text, data)
                self.assertEqual(decision["decision"], want, decision)
        self.assertEqual([c[0] for c in cases].count("PASS"), 1)

    def test_hp06_end_check_2_fails_before_publish(self):
        for early in (False, True):
            with self.subTest(early=early):
                env = Env()
                env.session_factory.end_script = {2: H.Stop("IMPORT_END_CHECK_FAILED", "FAKE2")}
                if early:
                    env.context.admit_error = RuntimeError("EARLIER_FAILURE")
                record = self.stopped(env)
                log = env.log
                self.assertLess(log.index("session.end_check#2"),
                                log.index("wfs.create_exclusive:" + EVIDENCE))
                self.assertEqual(env.wfs.calls.count(("create_exclusive", EVIDENCE)), 1)
                on_disk = env.evidence()                 # the only EVIDENCE ever written
                self.assertEqual((on_disk["verdict"], on_disk["pass_meaning"]), ("STOP", None))
                self.assertEqual(on_disk["outcomes"]["import_end_check_2"], "RAISED")
                phases = [row["phase"] for row in on_disk["phases"]]
                self.assertLess(phases.index("IMPORT_END_CHECK_2"),
                                phases.index("SERIALIZE_EVIDENCE"))
                receipt = env.receipt()
                self.assertEqual(receipt["evidence_file"]["state"], "COMPLETE_FSYNC_REQUESTED")
                self.assertEqual(receipt["evidence_file"]["sha256"], sha(env.evidence_bytes()))
                self.assertEqual((on_disk["spent_by_this_run"], on_disk["attempt_state"]), SPENT)
                if early:
                    self.assertIn("EARLIER_FAILURE", record["primary"]["text"])
                    self.assertEqual(record["secondary"][-1]["code"], "IMPORT_END_CHECK_FAILED")
                    self.assertEqual(record["secondary"][-1]["phase"],
                                     "GUARDED:import_end_check_2")
                else:
                    self.assertEqual(record["primary"]["code"], "IMPORT_END_CHECK_FAILED")
                    self.assertEqual(record["primary"]["phase"], "GUARDED:import_end_check_2")
                    self.assertEqual(set(on_disk["checks"].values()), {True})


# ---------------------------------------------------------------- L: import session
class ImportSessionTests(Base):
    def test_hi01_served_from_verified_bytes(self):
        env, names = l_env("i01")
        session = make_session(env)
        session.install()
        mods = session.load_entries((names[0],))
        self.assertEqual(mods[names[0]].VALUE, 42)
        self.assertEqual(session.executed, [names[0], names[1]])
        for index in (0, 1):
            module = sys.modules[names[index]]
            origin = CAND + "/" + env.plan["served"][index]
            self.assertEqual(module.__spec__.origin, origin)
            self.assertEqual(module.__file__, origin)
            self.assertIs(module.__spec__.loader, session)
            self.assertEqual(sha(session.sources[names[index]]),
                             env.approval["candidate_files"][env.plan["served"][index]])
        self.assertIs(sys.meta_path[0], session)
        self.assertEqual(session.end_check()["problems"], [])
        self.assertEqual(session.origin_violations(), [])

    def test_hi02_known_refused_before_finders(self):
        # exact lists first (R2): declared 232, lazy 2, universe 234, served 19
        self.assertEqual(len(REFERENCE_232), 232)
        self.assertEqual(REFERENCE_232, sorted(set(REFERENCE_232)))
        self.assertTrue(all(H.NAME_RE.fullmatch(name) for name in REFERENCE_232))
        self.assertEqual(H.names_sha256(REFERENCE_232), REFERENCE_232_SHA256)
        production = H.refusal_universe(H.PRODUCTION_PLAN, REFERENCE_232)
        self.assertEqual(len(production), 234)
        self.assertEqual(production - set(REFERENCE_232), set(LAZY_2))
        self.assertEqual(H.names_sha256(production), UNIVERSE_234_SHA256)
        self.assertEqual(tuple(sorted(H._module_name(rel)
                                      for rel in H.PRODUCTION_PLAN["lazy_refused"])), LAZY_2)
        served = set(H._module_name(rel) for rel in H.PRODUCTION_PLAN["served"])
        self.assertEqual((len(served), served & production), (19, set()))
        self.assertIsNone(H.KNOWN_UNSERVED_NAMES_SHA256)        # reported, never bound
        env, names = l_env("i02", lazy_2=True, declared=REFERENCE_232)
        session = make_session(env)
        self.assertEqual(session.refused_names, production | {names[2]})
        session.install()
        sweep = sorted(production) + [names[2]]                 # 232 + 2, + fixture lazy
        for name in sweep:
            with self.assertRaises(ImportError) as caught:
                importlib.import_module(name)
            self.assertEqual(str(caught.exception),
                             "NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + name)
            self.assertEqual(caught.exception.name, name)
            self.assertNotIn(name, sys.modules)
        self.assertEqual(env.path_finder.calls, [])             # before ANY finder lookup
        self.assertEqual(session.refusals, sweep)
        for qualified in QUALIFIED_SAMPLES + (names[0] + ".sub",):
            with self.assertRaises(ImportError) as caught:      # top label decides
                session.find_spec(qualified, [ROOT + "/outside/pkg"])
            self.assertEqual(str(caught.exception),
                             "NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + qualified)
        with self.assertRaises(ImportError) as caught:          # import system: parent first
            importlib.import_module(QUALIFIED_SAMPLES[0])
        self.assertEqual(caught.exception.name, "linux_exec")
        self.assertEqual(env.path_finder.calls, [])
        self.assertEqual(session.refusals, sweep + list(QUALIFIED_SAMPLES)
                         + [names[0] + ".sub", "linux_exec"])
        with self.assertRaises(H.Stop) as caught:
            session.end_check()
        self.assertEqual(caught.exception.code, "IMPORT_END_CHECK_FAILED")
        self.assertIn("REFUSED_IMPORTS", caught.exception.detail)
        self.assertEqual(session.executed, [])
        self.assertEqual(session.report()["refused_names_count"], 235)

    def test_hi03_unknown_names(self):
        env, names = l_env("i03")
        session = make_session(env)
        session.install()
        inside, outside = "nrp3hfx_i03_unknown_inside", "nrp3hfx_i03_unknown_outside"
        env.path_finder.script[inside] = types.SimpleNamespace(
            origin=CAND + "/other/" + inside + ".py", submodule_search_locations=None)
        env.path_finder.script[outside] = types.SimpleNamespace(
            origin=ROOT + "/outside/" + outside + ".py", submodule_search_locations=None)
        with self.assertRaises(ImportError) as caught:
            importlib.import_module(inside)
        self.assertIn("NRP3_UNKNOWN_CANDIDATE_LOCATION_REFUSED", str(caught.exception))
        self.assertEqual(session.refusals, [inside])
        self.assertIsNone(session.find_spec(outside))
        with self.assertRaises(ImportError) as caught:      # normal finders: not found
            importlib.import_module(outside)
        self.assertNotIn("NRP3_", str(caught.exception))
        self.assertEqual(session.refusals, [inside])
        self.assertIn((outside, None), env.path_finder.calls)
        # ORIGIN_SAMPLES (R2): names outside the universe are decided by the
        # located origin only -- top-level or qualified, file or namespace.
        parent = [ROOT + "/outside/pkg"]
        pkg = "nrp3hfx_i03_pkg"
        undecidable = ROOT + "/outside/undecidable.py"
        env.rfs.realpath_errors[undecidable] = OSError(errno.ELOOP, "fake realpath failure")

        def spec(origin, locations=None):
            return types.SimpleNamespace(origin=origin, submodule_search_locations=locations)
        samples = (
            ("nrp3hfx_i03_namespace", None, spec(None, [CAND + "/nsdir"]), True),
            (pkg + ".inner_inside", parent, spec(CAND + "/other/inner_inside.py"), True),
            (pkg + ".inner_outside", parent, spec(ROOT + "/outside/pkg/inner_outside.py"), False),
            (pkg + "." + FIXTURE_NAMES[0], parent,           # later label is NOT matched
             spec(ROOT + "/outside/pkg/" + FIXTURE_NAMES[0] + ".py"), False),
            (pkg + ".pkg_inside", parent,
             spec(ROOT + "/outside/pkg/pkg_inside/__init__.py", [CAND + "/pkg_inside"]), True),
            ("nrp3hfx_i03_undecidable", None, spec(undecidable), True),
            ("nrp3hfx_i03_absent", None, None, False))
        expected = [inside]
        for name, path, located, refused in samples:
            if located is not None:
                env.path_finder.script[name] = located
            if refused:
                with self.assertRaises(ImportError) as caught:
                    session.find_spec(name, path)
                self.assertEqual(str(caught.exception),
                                 "NRP3_UNKNOWN_CANDIDATE_LOCATION_REFUSED:" + name)
                expected.append(name)
            else:
                self.assertIsNone(session.find_spec(name, path))
            self.assertEqual(env.path_finder.calls[-1], (name, path))   # parent path passed on
            self.assertEqual(session.refusals, expected)
        self.assertEqual(session.executed, [])

    def test_hi04_preloaded_and_collisions(self):
        env, names = l_env("i04")
        before = list(sys.meta_path)

        def unchanged():
            self.assertEqual(len(sys.meta_path), len(before))
            self.assertTrue(all(a is b for a, b in zip(sys.meta_path, before)))
        sys.modules[names[0]] = types.ModuleType(names[0])
        try:
            with self.assertRaises(H.Stop) as caught:
                make_session(env).install()
        finally:
            del sys.modules[names[0]]
        self.assertEqual(caught.exception.code, "CANDIDATE_MODULE_PRELOADED")
        unchanged()
        foreign = types.ModuleType("nrp3hfx_i04_foreign")
        foreign.__file__ = CAND + "/zz/nrp3hfx_i04_foreign.py"
        sys.modules[foreign.__name__] = foreign
        try:
            with self.assertRaises(H.Stop) as caught:
                make_session(env).install()
        finally:
            del sys.modules[foreign.__name__]
        self.assertEqual(caught.exception.code, "CANDIDATE_ORIGIN_MODULE_PRELOADED")
        unchanged()
        with self.assertRaises(H.Stop) as caught:
            make_session(env, verified={"fx/%s.py" % names[0]: b"A = 1\n",
                                        "gx/%s.py" % names[0]: b"A = 2\n"})
        self.assertEqual(caught.exception.code, "CANDIDATE_BASENAME_COLLISION")
        with self.assertRaises(H.Stop) as caught:
            make_session(env, refused={names[0]})
        self.assertEqual(caught.exception.code, "SERVED_AND_REFUSED_OVERLAP")
        unchanged()
        self.assertNotIn(names[0], sys.modules)
        sys.modules[names[2]] = types.ModuleType(names[2])      # a refused name preloaded
        try:
            with self.assertRaises(H.Stop) as caught:
                make_session(env).install()
        finally:
            del sys.modules[names[2]]
        self.assertEqual((caught.exception.code, caught.exception.detail),
                         ("CANDIDATE_MODULE_PRELOADED", names[2]))
        unchanged()
        # R2 set semantics: served / declared / lazy pairwise disjoint, one file per name
        production = H.PRODUCTION_PLAN
        served = sorted(H._module_name(rel) for rel in production["served"])
        for name in AMBIGUOUS_BASENAMES:        # tree-ambiguous basenames are served names:
            self.assertIn(name, served)         # resolved by the pinned relpath, not by search
            self.assertNotIn(name, REFERENCE_232)
        both = dict(production, lazy_refused=production["lazy_refused"] + production["served"][:1])
        twice = dict(production, served=production["served"] + ("other/termination.py",))
        cases = (
            ("SERVED_NAME_LISTED_AS_UNSERVED", "termination", production,
             sorted(REFERENCE_232 + ["termination"])),
            ("LAZY_REFUSED_NAME_LISTED_AS_DECLARED", LAZY_2[0], production,
             sorted(REFERENCE_232 + [LAZY_2[0]])),
            ("LAZY_REFUSED_NAME_LISTED_AS_DECLARED", ",".join(LAZY_2), production,
             sorted(REFERENCE_232 + list(LAZY_2))),          # the union234 reading is refused
            ("PLAN_SERVED_AND_LAZY_REFUSED_OVERLAP", "fix001_contract", both, REFERENCE_232),
            ("PLAN_BASENAME_COLLISION", "", twice, REFERENCE_232))
        for code, detail, plan, declared in cases:
            with self.subTest(code=code, detail=detail):
                with self.assertRaises(H.Stop) as caught:
                    H.refusal_universe(plan, declared)
                self.assertEqual((caught.exception.code, caught.exception.detail),
                                 (code, detail))
        self.assertEqual(len(H.refusal_universe(production, REFERENCE_232)), 234)
        unchanged()

    def test_hi05_bytes_changed_after_authorization(self):
        env, names = l_env("i05")
        approval = dict(env.approval, _approval_sha256="0" * 64)
        read_deps = H.ReadDeps(env.rfs, env.now, INTERP, env.path_finder, HARNESS_PATH,
                               plan=env.plan)
        deps = H.EffectDeps(env.wfs, env.port, env.clock, env.sleep, env.builder)
        self.assertIs(deps.session_factory, H.PinnedImportSession)
        life = H.Lifecycle(ATTEMPT, approval, read_deps, deps, env.sink, RUN_DIR)
        env.os.files[CAND + "/" + env.plan["served"][1]] = b"BASE = 666\n"   # after pinning
        before = list(sys.meta_path)
        with self.assertRaises(H.Stop) as caught:
            H.load_candidate_modules(life)
        self.assertEqual(caught.exception.code, "CANDIDATE_FILE_HASH_MISMATCH")
        self.assertEqual(caught.exception.detail, env.plan["served"][1])
        self.assertIsNone(life.session)                                # nothing compiled
        self.assertTrue(all(a is b for a, b in zip(sys.meta_path, before)))
        self.assertEqual(len(sys.meta_path), len(before))
        self.assertNotIn(names[0], sys.modules)
        self.assertNotIn(names[1], sys.modules)

    def test_hi06_end_check_failures(self):
        env, names = l_env("i06")
        marker_entry = ROOT + "/syspath_present_at_install"
        sys.path.append(marker_entry)
        session = make_session(env)
        session.install()
        session.load_entries((names[0],))
        self.assertEqual(session.end_check()["problems"], [])

        def failing(problem):
            with self.assertRaises(H.Stop) as caught:
                session.end_check()
            self.assertEqual(caught.exception.code, "IMPORT_END_CHECK_FAILED")
            self.assertIn(problem, caught.exception.detail)
            self.assertTrue(any(p.startswith(problem) for p in session.end_reports[-1]["problems"]))
        foreign_finder = types.SimpleNamespace(find_spec=lambda name, path=None, target=None: None)
        sys.meta_path.insert(0, foreign_finder)
        try:
            failing("LOADER_NOT_AT_META_PATH_0")
        finally:
            sys.meta_path.remove(foreign_finder)
        sys.path.remove(marker_entry)
        try:
            failing("SYS_PATH_ENTRY_REMOVED")
        finally:
            sys.path.append(marker_entry)
        sys.path.append(ROOT + "/unexpected_insert")
        try:
            failing("SYS_PATH_UNEXPECTED_INSERT")
        finally:
            sys.path.remove(ROOT + "/unexpected_insert")
        foreign = types.ModuleType("nrp3hfx_i06_foreign")
        foreign.__file__ = CAND + "/zz/nrp3hfx_i06_foreign.py"
        sys.modules[foreign.__name__] = foreign
        try:
            failing("UNPINNED_CANDIDATE_ORIGIN")
        finally:
            del sys.modules[foreign.__name__]
        self.assertEqual(session.end_check()["problems"], [])
        self.assertEqual(len(session.end_reports), 6)                  # every report kept
        self.assertIs(sys.meta_path[0], session)
        sys.path.remove(marker_entry)

    def test_hi07_retention_and_end_check_order(self):
        env, names = l_env("i07")
        log, box = env.log, {}

        class LoggingSession(H.PinnedImportSession):
            def end_check(self):
                box["count"] = box.get("count", 0) + 1
                log.append("session.end_check#%d" % box["count"])
                return H.PinnedImportSession.end_check(self)

        def factory(*args):
            box["session"] = LoggingSession(*args)
            return box["session"]
        env.session_factory = factory
        evidence = self.passed(env)
        session = box["session"]
        self.assertIs(sys.meta_path[0], session)                       # retained
        self.assertEqual(box["count"], 2)
        self.assertEqual(env.mods[names[0]].VALUE, 42)
        first, second = log.index("session.end_check#1"), log.index("session.end_check#2")
        cleanup_report = log.index("ctx.termination.report")
        final_pins = [i for i, entry in enumerate(log)
                      if entry == "rfs.read_bytes:" + HARNESS_PATH][-1]
        publish_write = log.index("wfs.create_exclusive:" + EVIDENCE)
        self.assertTrue(cleanup_report < first < final_pins < second < publish_write, log)
        phases = [row["phase"] for row in evidence["phases"]]
        order = [phases.index(p) for p in ("CLEANUP", "IMPORT_END_CHECK_1", "FINAL_DECISION",
                                           "PUBLISH", "IMPORT_END_CHECK_2",
                                           "SERIALIZE_EVIDENCE")]
        self.assertEqual(order, sorted(order))
        outcomes = evidence["outcomes"]
        self.assertEqual(outcomes["import_end_check_1"]["index"], 1)
        self.assertEqual(outcomes["import_end_check_2"]["index"], 2)   # serialized after #2
        self.assertEqual(len(outcomes["import_report"]["end_reports"]), 2)
        self.assertEqual(evidence["loader_lifetime"],
                         "RETAINED_AT_META_PATH_0_UNTIL_PROCESS_EXIT")
        self.assertFalse(hasattr(session, "uninstall"))
        self.assertTrue(session.installed)
        abort = Env()                                                  # abort path, FakeSession
        abort.process.communicate_script = KeyboardInterrupt("fake first")
        abort.process.wait_script = KeyboardInterrupt("fake second")
        abort.process.on_wait = lambda: setattr(abort.clock, "armed",
                                                KeyboardInterrupt("fake outer"))
        self.assertEqual(abort.run(), 2)
        self.assertEqual(abort.sink.err()[0]["record"], "NRP3_LIFECYCLE_ABORTED")
        self.assertIs(sys.meta_path[0], session)                       # still retained
        self.assertTrue(abort.session_factory.installed)

    def test_hi08_import_caches(self):
        env, names = l_env("i08")
        session = make_session(env)
        session.install()
        stale = types.SimpleNamespace(invalidations=[], lookups=[])
        stale.invalidate_caches = lambda: stale.invalidations.append(1)
        stale.find_spec = lambda name, target=None: stale.lookups.append(name)
        sys.path_importer_cache[CAND + "/fx"] = stale
        try:
            importlib.invalidate_caches()
            module = importlib.import_module(names[0])
            with self.assertRaises(ImportError) as caught:
                importlib.import_module(names[2])
        finally:
            del sys.path_importer_cache[CAND + "/fx"]
        self.assertEqual(module.VALUE, 42)
        self.assertIs(module.__spec__.loader, session)
        self.assertEqual(session.executed, [names[0], names[1]])
        self.assertIn("NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED", str(caught.exception))
        self.assertEqual(stale.lookups, [])
        self.assertEqual(len(stale.invalidations), 1)
        self.assertIs(sys.meta_path[0], session)

    def test_hi09_lazy_refused_during_lifecycle(self):
        # canonical declared list (232, no lazy name in it) + the two lazy names
        # enforced from the plan; in-memory one-line stand-ins, never the real files
        env, names = l_env("i09", (
            "SEEN = []\n"
            "def trigger():\n"
            "    try:\n"
            "        import %s\n"
            "    except ImportError as error:\n"
            "        SEEN.append(str(error))\n"
            "    import %s\n" % LAZY_2).encode("ascii"), lazy_2=True, declared=REFERENCE_232)
        self.assertEqual(set(LAZY_2) & set(env.names), set())
        box = {}

        def factory(*args):
            box["session"] = H.PinnedImportSession(*args)
            return box["session"]
        env.session_factory = factory
        env.ports.new_context_hook = lambda: env.mods[names[0]].trigger()
        record = self.stopped(env)
        self.assertEqual(record["primary"]["type"], "ImportError")     # first cause preserved
        self.assertIn("NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + LAZY_2[1],
                      record["primary"]["text"])
        self.assertEqual(record["primary"]["phase"], "NEW_CONTEXT")
        self.assertEqual([(row["code"], row["phase"]) for row in record["secondary"]],
                         [("IMPORT_END_CHECK_FAILED", "GUARDED:import_end_check_1"),
                          ("IMPORT_END_CHECK_FAILED", "GUARDED:import_end_check_2")])
        session = box["session"]
        self.assertEqual(session.refusals, list(LAZY_2))               # both, in order
        self.assertEqual(env.mods[names[0]].SEEN,
                         ["NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + LAZY_2[0]])
        for lazy in LAZY_2:
            self.assertNotIn(lazy, sys.modules)
            self.assertNotIn(lazy, session.executed)
        self.assertEqual([c for c in env.path_finder.calls if c[0] in LAZY_2], [])
        self.assertIs(sys.meta_path[0], session)
        universe = H.refusal_universe(env.plan, REFERENCE_232)
        self.assertEqual(session.refused_names, universe)
        self.assertTrue(H.refusal_universe(H.PRODUCTION_PLAN, REFERENCE_232) <= universe)
        self.assertEqual(record["pins"]["refusal_universe"], {
            "declared_count": 232, "declared_sha256": REFERENCE_232_SHA256,
            "lazy_refused_names": sorted(LAZY_2 + (names[2],)), "total_count": 235,
            "rule": H.REFUSAL_UNIVERSE_RULE})
        report = record["outcomes"]["import_report"]
        self.assertEqual((report["refused_names_count"], report["refused_names_sha256"]),
                         (235, H.names_sha256(universe)))
        self.assertEqual(record["custody"]["context"], "NEW_CONTEXT_CALLED_OUTCOME_UNKNOWN")
        self.assertEqual(record["unresolved_ownership"], [])

    def test_hi10_single_session(self):
        env, names = l_env("i10")
        first = make_session(env)
        first.install()
        other, _ = l_env("i10x")
        second = make_session(other)
        with self.assertRaises(H.Stop) as caught:
            second.install()
        self.assertEqual(caught.exception.code, "IMPORT_SESSION_ALREADY_INSTALLED")
        self.assertIs(sys.meta_path[0], first)
        self.assertEqual([f for f in sys.meta_path if f is second], [])
        self.assertFalse(second.installed)
        self.assertEqual(len([f for f in sys.meta_path
                              if getattr(f, "nrp3_pinned_session", False)]), 1)


# ---------------------------------------------------------------- B: bound
class BoundTests(Base):
    def bound_pass(self):
        env = BEnv()
        evidence = self.passed(env)
        return env, evidence

    def test_hb01_real_non_p18_subset_via_session(self):
        env = BEnv()
        root = env.cand
        self.assertEqual(len(B_SERVED), 17)
        pins = dict((rel, B_PINS[rel]) for rel in B_SERVED)
        verified = H.verify_files(env.rfs, root, pins, H.Stop)        # RealReadFS(os) reads
        self.assertEqual(sorted(p for n, p in env.rfs.real_calls if n == "read_bytes"),
                         sorted(os.path.join(root, rel) for rel in B_SERVED))
        self.assertEqual(dict((rel, sha(data)) for rel, data in verified.items()), pins)
        # R2: re-derive the declared list from the pinned tree (listing only)
        py, dirs = tree_names(env.real_rfs, root)
        served19 = set(H._module_name(rel) for rel in H.PRODUCTION_PLAN["served"])
        identifier_dirs = set(name for name in dirs if H.NAME_RE.fullmatch(name))
        self.assertTrue(all(H.NAME_RE.fullmatch(name) for name in py))
        self.assertEqual({"py_basenames": len(py), "identifier_directories": len(identifier_dirs),
                          "served": len(served19)}, TREE_COUNTS)
        self.assertEqual(sorted(dirs - identifier_dirs), NON_IDENTIFIER_DIRECTORIES)
        self.assertEqual(py & identifier_dirs, set())
        self.assertTrue(served19 | set(LAZY_2) <= py)
        self.assertEqual(sorted((py | identifier_dirs) - served19 - set(LAZY_2)), REFERENCE_232)
        self.assertEqual(len(identifier_dirs & set(REFERENCE_232)), 61)    # reference-only 61
        self.assertEqual(env.names, REFERENCE_232)
        self.assertEqual(H.names_sha256(env.names), REFERENCE_232_SHA256)
        self.assertEqual(env.gate.known_names_sha256, REFERENCE_232_SHA256)   # test Gate only
        self.assertIsNone(H.KNOWN_UNSERVED_NAMES_SHA256)
        production = H.refusal_universe(H.PRODUCTION_PLAN, env.names)
        self.assertEqual((len(production), H.names_sha256(production)),
                         (234, UNIVERSE_234_SHA256))
        self.assertEqual(production | served19, py | identifier_dirs)      # nothing uncovered
        refused = H.refusal_universe(B_PLAN, env.names)
        self.assertEqual(refused, production | {"parsers", "pidfd_primitives"})
        finder = CountingFinder(importlib.machinery.PathFinder)
        session = H.PinnedImportSession(root, verified, refused, finder,
                                        env.rfs, B_PLAN["expected_sys_path_inserts"])
        path_before = list(sys.path)
        session.install()
        mods = session.load_entries(B_PLAN["entry_imports"])
        self.assertEqual(sorted(mods), sorted(["stage_b_controller", "stage_b_dispatch_journal",
                                               "termination", "linux_entry",
                                               "native_root_port"]))
        self.assertEqual(session.origin_violations(), [])             # origin sweep clean
        report = session.end_check()
        self.assertEqual(report["problems"], [])
        expected = [os.path.join(root, rel) for rel in B_PLAN["expected_sys_path_inserts"]]
        delta = [p for p in sys.path if p not in path_before]
        self.assertEqual(sorted(delta), sorted(expected))
        self.assertEqual([p for p in path_before if p not in sys.path], [])
        self.assertEqual([os.path.basename(p) for p in sorted(expected)],
                         ["exec_preflight", "pilot", "reference"])
        served_names = set(H._module_name(rel) for rel in B_SERVED)
        self.assertTrue(set(B_PLAN["entry_imports"]) <= set(session.executed))
        self.assertTrue(set(session.executed) <= served_names)
        for name in session.executed:
            self.assertIs(sys.modules[name].__spec__.loader, session)
        for name in ("pidfd_primitives", "parsers"):
            self.assertNotIn(name, session.executed)
            self.assertNotIn(name, sys.modules)
        with self.assertRaises(ImportError) as caught:                # refused if requested
            importlib.import_module("pidfd_primitives")
        self.assertIn("NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED", str(caught.exception))
        self.assertNotIn("pidfd_primitives", sys.modules)
        self.assertNotIn("pidfd_primitives", session.executed)
        self.assertEqual(session.refusals, ["pidfd_primitives"])
        self.assertIs(sys.meta_path[0], session)
        self.assertEqual(guard_violations(), [])
        # R2 denial route for the exact 232 + 2 (+ the two p18 names of this tier):
        # refused by name before any finder lookup, nothing executed or loaded
        executed, sweep = list(session.executed), sorted(refused)
        self.assertEqual(set(finder.calls) & refused, set())
        for name in sweep:
            with self.assertRaises(ImportError) as caught:
                session.find_spec(name)
            self.assertEqual(str(caught.exception),
                             "NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + name)
            self.assertNotIn(name, sys.modules)
        linux_exec = os.path.join(root, "dev/ENGINE003-PREFLIGHT/linuxport001/linux_exec")
        qualified = QUALIFIED_SAMPLES + ("termination.anything",)   # served name as a package
        for name in qualified:
            with self.assertRaises(ImportError) as caught:
                session.find_spec(name, [linux_exec])
            self.assertEqual(str(caught.exception),
                             "NRP3_UNSERVED_CANDIDATE_MODULE_REFUSED:" + name)
        self.assertEqual(set(finder.calls) & (refused | set(qualified)), set())
        self.assertEqual(session.refusals, ["pidfd_primitives"] + sweep + list(qualified))
        # origin fallback with the real PathFinder (locate only): stdlib names
        # resolve outside the tree and are left to the normal finders
        before = len(finder.calls)
        self.assertIsNone(session.find_spec("json"))
        self.assertIsNone(session.find_spec("json.decoder", list(json.__path__)))
        self.assertIsNone(session.find_spec("nrp3hfx_b01_absent"))
        self.assertEqual(finder.calls[before:], ["json", "json.decoder", "nrp3hfx_b01_absent"])
        # collisions: no universe name is located outside the tree by this
        # interpreter's finder (-I -S: stdlib only; site-packages not on sys.path)
        collisions = []
        for name in sweep:
            located = importlib.machinery.PathFinder.find_spec(name)
            where = [] if located is None else (
                [located.origin] if isinstance(located.origin, str) else []) + list(
                    located.submodule_search_locations or [])
            if name in sys.builtin_module_names or [p for p in where
                                                    if not H._inside(p, root)]:
                collisions.append(name)
        self.assertEqual(collisions, [])
        self.assertEqual(session.executed, executed)
        self.assertEqual(session.origin_violations(), [])
        self.assertEqual(guard_violations(), [])

    def test_hb02_bound_lifecycle_recording_ports(self):
        env, evidence = self.bound_pass()
        box, p18 = env.box, env.p18
        frozen = sys.modules["native_root_port"].P18SysPorts
        self.assertIs(box["frozen"], frozen)
        self.assertTrue(issubclass(box["cls"], frozen) and box["cls"] is not frozen)
        own = set(n for n in vars(box["cls"]) if not n.startswith("__"))
        self.assertEqual(own, {"close_fd", "getpid"})
        self.assertEqual(box["passed_p18"], ())                 # no real p18 module loaded
        self.assertEqual((box["construction_calls"], box["construction_native"]), (0, 0))
        self.assertEqual(p18.constructions, 1)                  # lazily, exactly once
        self.assertEqual(p18.named("validate"), [("validate", (True, True, True), True, 2)] * 3)
        self.assertEqual(p18.named("open"), [("open", FAKE_CHILD_PID, 0)])
        self.assertEqual(len(p18.named("child_stat")), 3)
        self.assertEqual(len(p18.named("wait")), 2)
        self.assertEqual(p18.named("bounded_read"), [
            ("bounded_read", BOOT_PATH, 64), ("bounded_read", FDINFO_PATH, 8192),
            ("bounded_read", BOOT_PATH, 64)])
        self.assertEqual(box["getpid_sites"], [("acquire_root", 193), ("open", 99),
                                               ("_owner", 112)])
        context = box["ports"].entry.contexts[0]
        self.assertEqual(len(box["ports"].entry.contexts), 1)
        handle = context.termination.port.handles[0]
        self.assertEqual((handle.owner_pid, handle.fd, handle.custody),
                         (FAKE_PARENT_PID, FAKE_FD, "CLOSED"))
        self.assertIs(context.native_backend, H.INERT_SAMPLER)
        outcomes = evidence["outcomes"]
        route = outcomes["route_report"]
        self.assertEqual(route["native_identity"]["identity"], [BOOT_ID, FAKE_CHILD_PID, 777])
        self.assertEqual(route["native_identity"]["journal_identity"], None)
        self.assertEqual(route["port_counters"], {"open": 1, "close": 1, "signal_refused": 0})
        self.assertEqual(outcomes["context_state"]["root_authority_state"], "ACQUIRED")
        effect = outcomes["effect"]
        self.assertEqual((effect["identity"], effect["custody"]), (None, "REGISTERED"))
        journal = sys.modules["stage_b_dispatch_journal"]
        self.assertEqual(journal.validate_effect_evidence(effect), effect)
        self.assertEqual(outcomes["first_close"], "CLOSED")
        self.assertEqual(box["close_fd"], [FAKE_FD])            # frozen os.close never reached
        self.assertEqual(outcomes["second_close"], "ALREADY_CLOSED")
        self.assertEqual(set(evidence["checks"].values()), {True})
        self.assertEqual(env.receipt()["verdict"], "PASS")
        self.assertEqual(H.receipt_authority_decision(
            0, env.sink.o.text, env.evidence_bytes())["decision"], "PASS")
        self.assertIs(sys.meta_path[0], box["session"])
        self.assertEqual(len(box["session"].end_reports), 2)
        for name in ("pidfd_primitives", "parsers"):
            self.assertNotIn(name, sys.modules)
            self.assertNotIn(name, box["session"].executed)
        self.assertEqual(env.process.forbidden, 0)
        self.assertEqual(guard_violations(), [])

    def test_hb03_inert_sampler_untouched(self):
        env, evidence = self.bound_pass()
        self.assertEqual(H.INERT_SAMPLER.accessed, [])
        self.assertEqual(evidence["checks"]["inert_sampler_untouched"], True)
        self.assertEqual(evidence["inert_sampler"],
                         "NRP3_CANARY_INERT_SAMPLER_FIXTURE_NOT_A_BACKEND")
        self.assertIs(env.box["ports"].entry.contexts[0].native_backend, H.INERT_SAMPLER)
        scripted = Env()

        def touch():
            try:
                H.INERT_SAMPLER.sample
            except AttributeError as error:
                scripted.touch_error = str(error)
        scripted.ports.new_context_hook = touch
        record = self.stopped(scripted)
        self.assertEqual(record["checks"]["inert_sampler_untouched"], False)
        self.assertEqual(record["primary"]["text"], "Stop:CHECK_FAILED:inert_sampler_untouched")
        self.assertEqual(H.INERT_SAMPLER.accessed, ["sample"])
        self.assertIn("NO_BACKEND_SURFACE", scripted.touch_error)
        self.assertEqual(guard_violations(), [])

    def test_hb04_bound_refusals(self):
        env = BEnv()
        env.p18.validate_error = env.p18.module.PidfdError("FAKE_ENVIRONMENT_REFUSED", "validate")
        record = self.stopped(env)
        self.assertEqual(record["primary"]["type"], "GroupSignalRefused")
        self.assertEqual(record["primary"]["phase"], "ADMIT")
        self.assertIn("NATIVE_ROOT_ACQUISITION_REFUSED:FAKE_ENVIRONMENT_REFUSED",
                      record["primary"]["text"])
        self.assertEqual(env.box["close_fd"], [])
        self.assertEqual(env.p18.named("open"), [])
        self.assertEqual(env.port.argvs, [])                    # refused before any spawn
        session = env.box["session"]

        env = BEnv()
        env.session_factory = ReusedSession(session)
        env.p18.fdinfo_pid = 9999                               # V4 mismatch
        record = self.stopped(env)
        self.assertEqual(record["primary"]["code"], "ROOT_NOT_ACQUIRED_NO_FALLBACK")
        self.assertIn("UNAVAILABLE:PIDFD_PID_BINDING", record["primary"]["text"])
        self.assertEqual(env.box["close_fd"], [FAKE_FD])        # rollback close exactly once
        self.assertEqual(record["outcomes"]["route_report"]["port_counters"]["close"], 1)
        self.assertEqual(record["outcomes"]["cleanup_context_close"], "CLOSED")
        self.assertEqual(len(env.port.argvs), 1)

        env = BEnv()
        env.session_factory = ReusedSession(session)
        env.box["close_error"] = OSError(errno.EBADF, "fake close failure")
        record = self.stopped(env)
        self.assertEqual(record["primary"]["code"], "FIRST_CLOSE_NOT_CLOSED")
        self.assertIn("CUSTODY_UNRESOLVED", record["primary"]["text"])
        self.assertEqual(env.box["close_fd"], [FAKE_FD])        # never retried
        self.assertNotIn("second_close", record["outcomes"])
        self.assertEqual(record["outcomes"]["cleanup_context_close"],
                         "NOT_CALLED_FIRST_CLOSE_ALREADY_ATTEMPTED")
        rows = [row for row in record["unresolved_ownership"]
                if row["resource"] == "port_custody"]
        self.assertEqual(rows, [{"resource": "port_custody", "pid": FAKE_CHILD_PID,
                                 "custody": "CLOSE_CALLED_OUTCOME_UNKNOWN",
                                 "state": "PORT_CUSTODY_UNRESOLVED"}])
        self.assertIs(sys.meta_path[0], session)
        self.assertEqual(env.process.forbidden, 0)
        self.assertEqual(guard_violations(), [])
