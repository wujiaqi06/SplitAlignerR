#!/usr/bin/env python3
"""Produce bounded BRANCH-FIX001 evidence without large Stage-B execution."""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Dict, Mapping
from unittest import mock


sys.dont_write_bytecode = True


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REFERENCE = ENGINE / "reference"
for value in (HERE, REFERENCE):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from capture_pretiming_resources import capture  # noqa: E402
from fix001_contract import (  # noqa: E402
    ALL_CANDIDATES,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_load,
    strict_json_loads,
    write_canonical_json,
)
import stage_b_controller as controller_module  # noqa: E402
from stage_b_controller import (  # noqa: E402
    DarwinLibprocSamplerBackend,
    NativeSamplerCapabilityError,
    ProcessTreeRssSampler,
    _process_table_mechanism,
    _sampler_capability_backend,
    evaluate_resource_hard_gate,
    launch_request,
    process_group_options,
)
import stage_b_orchestrator as orchestrator_module  # noqa: E402
from stage_b_orchestrator import (  # noqa: E402
    REQUEST_IDENTITY_FIELDS,
    execute_runtime_bound_workload,
)
from stage_b_runtime_contract import (  # noqa: E402
    BOUNDED_WORKLOAD,
    make_bounded_request,
    prelaunch_guard,
)
from stage_b_authorization import (  # noqa: E402
    RESOURCE_ADMISSION_POLICY,
    load_exact_runtime_resource_capture,
    validate_runtime_resource_capture,
)


BASE_COMMIT = "63ef4fba4c51aeb913f316151755d6e2f1f4e938"
BASE_TREE = "31404be181b823853794fc15455ffd435971b42b"
ATTEMPT002_AUTHORIZATION_SHA256 = (
    "77125a497572cd733faffd136d6d4389e4be662f1fd90b482061a6d8913227a4"
)
EXPECTED_DURABILITY_SHA256 = (
    "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
)
ATTEMPT002_ROOTS = (
    Path(
        "/Users/jiaqiwu/Documents/Codex/2026-07-24/zhe/"
        "ENGINE003_STAGEB_EXEC001_ATTEMPT002_RUNTIME_a747424"
    ),
    Path(
        "/Users/jiaqiwu/Documents/Codex/2026-07-24/zhe/"
        "ENGINE003_STAGEB_EXEC001_ATTEMPT002_EVIDENCE_a747424"
    ),
)
SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBSamplerFix001Summary/v1"
SUMMARY_STATUS = "PASS_SAMPLER_FIX001_BOUNDED_PREFLIGHT_ONLY"
MUTATION_CASE_IDS = (
    "TRUE_BRANCH_TRUE_SERIES",
    "BRANCH_OMITTED",
    "BRANCH_REPLACED_BY_SERIES",
    "SERIES_REPLACED_BY_BRANCH",
    "WRONG_BRANCH_BYTES_RECOMPUTED_SHA",
    "WRONG_SERIES_BYTES",
    "HOST_VOLUME_MISMATCH",
)
CAPTURE_DISTINCTION_RETRY_WAIT_NANOSECONDS = 1_100_000_000
CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS = 3_000_000_000
CAPTURE_DISTINCTION_MAX_SERIES_ATTEMPTS = 3


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def write_raw(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short_write")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def git_bytes(repo: Path, *arguments: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=30,
    )
    if process.returncode:
        raise AssertionError(
            f"git {' '.join(arguments)}:{process.returncode}:"
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    return process.stdout


def git_text(repo: Path, *arguments: str) -> str:
    return git_bytes(repo, *arguments).decode("utf-8").strip()


def same_or_descendant(path: Path, root: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    fixed = Path(os.path.abspath(root))
    return absolute == fixed or fixed in absolute.parents


def lexical_absolute(path: Path) -> Path:
    """Make an absolute path without dereferencing its final symlink."""
    return Path(os.path.abspath(os.fspath(path)))


def require_fresh_root(path: Path, label: str) -> Dict[str, Any]:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise AssertionError(f"{label} is not an ordinary directory")
    entries = list(path.iterdir())
    if entries:
        raise AssertionError(f"{label} is not initially empty:{entries}")
    if any(same_or_descendant(path, old) for old in ATTEMPT002_ROOTS):
        raise AssertionError(f"{label} reuses an Attempt002 root")
    return {
        "path": str(path), "st_dev": observed.st_dev, "st_ino": observed.st_ino,
        "ordinary_directory": True, "symlink": False, "initial_entry_count": 0,
    }


def source_checkpoint(repo: Path) -> Dict[str, Any]:
    branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
    )
    if branch.returncode not in (0, 1):
        raise AssertionError("source branch inspection failed")
    full = git_bytes(repo, "status", "--porcelain=v1", "--untracked-files=all")
    protected = git_bytes(
        repo, "status", "--porcelain=v1", "--untracked-files=all", "--",
        "dev/ENGINE003-PREFLIGHT",
    )
    return {
        "head": git_text(repo, "rev-parse", "HEAD"),
        "tree": git_text(repo, "rev-parse", "HEAD^{tree}"),
        "branch_stdout": branch.stdout.decode("utf-8").strip(),
        "full_status_stdout": full.decode("utf-8").strip(),
        "protected_status_stdout": protected.decode("utf-8").strip(),
    }


def assert_source(repo: Path) -> tuple[str, str, Dict[str, Any]]:
    pre = source_checkpoint(repo)
    commit = pre["head"]
    tree = pre["tree"]
    parents = git_text(repo, "show", "-s", "--format=%P", commit).split()
    if parents != [BASE_COMMIT] or commit == BASE_COMMIT:
        raise AssertionError(f"ordinary child identity:{commit}:{parents}")
    if git_text(repo, "rev-parse", f"{BASE_COMMIT}^{{tree}}") != BASE_TREE:
        raise AssertionError("frozen base tree")
    if pre["branch_stdout"] or pre["full_status_stdout"] or pre["protected_status_stdout"]:
        raise AssertionError("official producer checkout must be detached and clean")
    executed = Path(__file__).read_bytes()
    git_runner = git_bytes(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/"
        "run_branch_fix001_preflight.py",
    )
    if executed != git_runner:
        raise AssertionError("executed runner differs from child Git object")
    return commit, tree, pre


def host_profile(resource: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: resource[key] for key in (
        "host_id", "platform_system", "platform_release", "platform_machine",
        "os_build", "filesystem", "destination_device_id",
        "target_volume_device", "target_volume_mount_point",
    )}


def validate_capture(resource: Mapping[str, Any]) -> None:
    validate_runtime_resource_capture({
        "host_profile": host_profile(resource),
        "resource_admission_policy": RESOURCE_ADMISSION_POLICY,
    }, resource)


def run_raw_command(
        evidence: Path, command_id: str, argv: list[str]) -> Dict[str, Any]:
    process = subprocess.run(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    root = evidence / "RAW_PS"
    stdout_path = root / f"{command_id}.stdout.bin"
    stderr_path = root / f"{command_id}.stderr.bin"
    write_raw(stdout_path, process.stdout)
    write_raw(stderr_path, process.stderr)
    return {
        "command_id": command_id,
        "argv": argv,
        "resolved_executable": shutil.which(argv[0]),
        "cwd": str(Path.cwd().resolve()),
        "operational_timeout_nanoseconds": 30_000_000_000,
        "return_code": process.returncode,
        "stdout_path": stdout_path.relative_to(evidence).as_posix(),
        "stdout_bytes": len(process.stdout),
        "stdout_sha256": sha256(process.stdout),
        "stderr_path": stderr_path.relative_to(evidence).as_posix(),
        "stderr_bytes": len(process.stderr),
        "stderr_sha256": sha256(process.stderr),
    }


def external_ps_independence_regression(evidence: Path) -> Dict[str, Any]:
    calls = []

    def forbidden_creation(*args, **kwargs):
        calls.append({"args": repr(args), "kwargs": repr(kwargs)})
        raise PermissionError(1, "Operation not permitted", "ps")

    backend = _sampler_capability_backend()
    if not isinstance(backend, DarwinLibprocSamplerBackend):
        raise AssertionError("Darwin native backend required")
    sampler = ProcessTreeRssSampler(os.getpid(), native_backend=backend)
    with (
        mock.patch.object(
            controller_module.subprocess, "run", forbidden_creation,
        ),
        mock.patch.object(
            controller_module.subprocess, "Popen", forbidden_creation,
        ),
    ):
        sampler._sample()
    status = "PASS" if (
        not calls and sampler.sample_count == 1
        and sampler.maximum_bytes > 0 and sampler.maximum_root_bytes > 0
    ) else "FAIL"
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBNativeSamplerExternalPsIndependence/v1",
        "status": status,
        "mechanism_id": _process_table_mechanism()["mechanism_id"],
        "external_ps_forced_unavailable": True,
        "forced_unavailable_argv": [
            ["ps", "-axo", "pid=,ppid=,rss="],
            ["/bin/ps", "-axo", "pid=,ppid=,rss="],
        ],
        "external_process_table_call_count": len(calls),
        "native_sample_count": sampler.sample_count,
        "native_root_rss_bytes": sampler.maximum_root_bytes,
        "native_whole_tree_rss_bytes": sampler.maximum_bytes,
        "stage_b_worker_invoked": False,
        "stage_b_measured_clock": False,
    }
    write_canonical_json(evidence / "EXTERNAL_PS_INDEPENDENCE.json", value)
    if status != "PASS":
        raise StopSignal("SB_STOP_SAMPLER_DIAG", "external_ps_independence")
    return value


def controlled_sampler_diagnostic(
        repo: Path, evidence: Path, controller_source_sha256: str) -> Dict[str, Any]:
    control = evidence / "SAMPLER_DIAG" / "control"
    control.mkdir(parents=True, exist_ok=False)
    stdout_path = evidence / "SAMPLER_DIAG" / "controlled_tree.stdout.bin"
    command = [
        sys.executable, "-B", str(HERE / "sampler_fix001_control_process.py"),
        "--role", "root", "--control-dir", str(control),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        **process_group_options(),
    )
    backend = _sampler_capability_backend()
    if not isinstance(backend, DarwinLibprocSamplerBackend):
        raise AssertionError("Darwin native backend required")
    sampler = ProcessTreeRssSampler(process.pid, native_backend=backend)
    timed_out = False
    graceful_signal_sent = False
    force_signal_sent = False
    stdout = b""
    phase_samples = []

    def wait_file(path: Path, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while not path.is_file():
            if process.poll() is not None:
                raise AssertionError(f"controlled root exited before:{path.name}")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(0.01)

    def read_pid(name: str) -> int:
        raw = (control / name).read_bytes()
        if not raw.endswith(b"\n") or not raw[:-1].isdigit():
            raise AssertionError(f"controlled PID bytes:{name}")
        value = int(raw)
        if value <= 0:
            raise AssertionError(f"controlled PID value:{name}")
        return value

    def wait_absent(pid: int, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                backend.identity(pid)
            except controller_module.NativeSamplerProcessAbsent:
                return
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(["native_identity_absent", pid], timeout)
            time.sleep(0.01)

    def signal_file(name: str) -> None:
        write_raw(control / name, b"SIGNAL\n")

    try:
        wait_file(control / "root.ready")
        root_pid = read_pid("root.pid")
        child_pid = read_pid("child.pid")
        grandchild_pid = read_pid("grandchild.pid")
        if root_pid != process.pid or len({root_pid, child_pid, grandchild_pid}) != 3:
            raise AssertionError("controlled topology PID identity")
        sampler.start()
        deadline = time.monotonic() + 10
        while (
            sampler.sample_count < 2
            or not {root_pid, child_pid, grandchild_pid}.issubset(sampler.owned_pids)
        ):
            if sampler.error != "NONE":
                raise AssertionError(f"native sampler error:{sampler.error}")
            if time.monotonic() >= deadline:
                raise AssertionError("native sampler did not observe full topology")
            time.sleep(0.01)
        phase_samples.append({
            "phase": "FULL_TREE", "sample_count": sampler.sample_count,
            "owned_pids": sorted(sampler.owned_pids),
            "maximum_root_bytes": sampler.maximum_root_bytes,
            "maximum_bytes": sampler.maximum_bytes,
        })
        signal_file("exit-grandchild.signal")
        wait_absent(grandchild_pid)
        deadline = time.monotonic() + 5
        while grandchild_pid not in sampler.identity_aware_exit_pids:
            if time.monotonic() >= deadline:
                raise AssertionError("grandchild identity-aware exit not observed")
            time.sleep(0.01)
        phase_samples.append({
            "phase": "AFTER_GRANDCHILD_EXIT", "sample_count": sampler.sample_count,
            "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
        })
        signal_file("exit-child.signal")
        wait_absent(child_pid)
        deadline = time.monotonic() + 5
        while child_pid not in sampler.identity_aware_exit_pids:
            if time.monotonic() >= deadline:
                raise AssertionError("child identity-aware exit not observed")
            time.sleep(0.01)
        phase_samples.append({
            "phase": "AFTER_CHILD_EXIT", "sample_count": sampler.sample_count,
            "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
        })
        signal_file("exit-root.signal")
        stdout, _ = process.communicate(timeout=30)
        wait_absent(root_pid)
        sampler.stop()
        phase_samples.append({
            "phase": "AFTER_ROOT_EXIT", "sample_count": sampler.sample_count,
            "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
        })
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            graceful_signal_sent = True
        except (ProcessLookupError, OSError):
            pass
        try:
            stdout, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                force_signal_sent = True
            except (ProcessLookupError, OSError):
                pass
            stdout, _ = process.communicate()
    finally:
        if sampler._thread.is_alive():
            sampler.stop()
    process_group_alive = False
    if os.name != "nt":
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            process_group_alive = True
        else:
            process_group_alive = True
    if process_group_alive:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            force_signal_sent = True
        except (ProcessLookupError, OSError):
            pass
        time.sleep(0.05)
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            process_group_alive = False
        except PermissionError:
            process_group_alive = True
        else:
            process_group_alive = True
    write_raw(stdout_path, stdout or b"")
    pid_files = {
        name: {
            "path": (control / name).relative_to(evidence).as_posix(),
            "sha256": file_sha256(control / name),
            "pid": read_pid(name),
        }
        for name in ("root.pid", "child.pid", "grandchild.pid")
    }
    root_pid = pid_files["root.pid"]["pid"]
    child_pid = pid_files["child.pid"]["pid"]
    grandchild_pid = pid_files["grandchild.pid"]["pid"]
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBControlledProcessTreeSampler/v1",
        "status": "PASS",
        "non_stage_b_control": True,
        "worker_invoked": False,
        "stage_b_clock": False,
        "sampler_algorithm_changed_from_parent_by_order": True,
        "controller_source_sha256": controller_source_sha256,
        "command": command,
        "process_return_code": process.returncode,
        "process_operational_timeout_nanoseconds": 30_000_000_000,
        "process_timeout_observed": timed_out,
        "timeout_graceful_signal_sent": graceful_signal_sent,
        "timeout_force_signal_sent": force_signal_sent,
        "process_group_alive_after_cleanup": process_group_alive,
        "process_group_cleanup_pass": not process_group_alive,
        "stdout_path": stdout_path.relative_to(evidence).as_posix(),
        "stdout_bytes": stdout_path.stat().st_size,
        "stdout_sha256": file_sha256(stdout_path),
        "pid_files": pid_files,
        "root_pid": root_pid,
        "child_pid": child_pid,
        "grandchild_pid": grandchild_pid,
        "controlled_topology": [root_pid, child_pid, grandchild_pid],
        "phase_samples": phase_samples,
        "descendant_allocation_bytes": 48 * 1024 * 1024,
        "error": sampler.error,
        "sample_count": sampler.sample_count,
        "maximum_bytes": sampler.maximum_bytes,
        "maximum_root_bytes": sampler.maximum_root_bytes,
        "owned_pids": sorted(sampler.owned_pids),
        "owned_process_identities": [
            {"pid": pid, "identity": identity}
            for pid, identity in sorted(sampler.owned_process_identities.items())
        ],
        "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
        "sampling_interval_nanoseconds": int(sampler.interval * 1_000_000_000),
        "process_table_mechanism": _process_table_mechanism(),
        "sampler_thread_alive_after_stop": sampler._thread.is_alive(),
        "sampler_valid": (
            not timed_out and not process_group_alive
            and process.returncode == 0 and sampler.error == "NONE"
            and sampler.sample_count >= 2 and sampler.maximum_root_bytes > 0
            and sampler.maximum_bytes > sampler.maximum_root_bytes
            and {root_pid, child_pid, grandchild_pid}.issubset(sampler.owned_pids)
            and {root_pid, child_pid, grandchild_pid}.issubset(
                sampler.identity_aware_exit_pids
            )
            and not sampler._thread.is_alive()
        ),
    }
    if value["sampler_valid"] is not True:
        value["status"] = "STOP_SAMPLER_DIAGNOSTIC"
    write_canonical_json(evidence / "CONTROLLED_PROCESS_TREE_SAMPLER.json", value)
    if value["status"] != "PASS":
        raise StopSignal("SB_STOP_SAMPLER_DIAG", "controlled_process_tree")
    return value


class _FakeNativeBackend:
    def __init__(
            self, children: Mapping[int, tuple[int, ...]],
            identities: Mapping[int, tuple[int, tuple[int, int, int]]],
            rss: Mapping[int, int]) -> None:
        self.children_map = dict(children)
        self.identities = dict(identities)
        self.rss_map = dict(rss)
        self.fail_children_pid: int | None = None
        self.fail_identity_pid: int | None = None
        self.fail_rss_pid: int | None = None

    def children(self, pid: int) -> tuple[int, ...]:
        if pid == self.fail_children_pid:
            raise NativeSamplerCapabilityError("INJECTED_ENUMERATION_FAILURE")
        return self.children_map.get(pid, ())

    def identity(self, pid: int) -> tuple[int, tuple[int, int, int]]:
        if pid == self.fail_identity_pid:
            raise NativeSamplerCapabilityError("INJECTED_BSD_FAILURE")
        try:
            return self.identities[pid]
        except KeyError as error:
            raise controller_module.NativeSamplerProcessAbsent(
                f"INJECTED_PROCESS_ABSENT:{pid}"
            ) from error

    def rss(self, pid: int) -> int:
        if pid == self.fail_rss_pid:
            raise NativeSamplerCapabilityError("INJECTED_RSS_FAILURE")
        try:
            return self.rss_map[pid]
        except KeyError as error:
            raise controller_module.NativeSamplerProcessAbsent(
                f"INJECTED_RSS_ABSENT:{pid}"
            ) from error


def native_sampler_failure_corpus(evidence: Path) -> Dict[str, Any]:
    identities = {
        100: (1, (100, 10, 1)),
        101: (100, (101, 11, 1)),
        102: (101, (102, 12, 1)),
    }

    def positive(case_id: str, children, rss, expected_owned) -> Dict[str, Any]:
        backend = _FakeNativeBackend(children, identities, rss)
        sampler = ProcessTreeRssSampler(100, native_backend=backend)
        sampler._sample()
        if sampler.owned_pids != set(expected_owned):
            raise AssertionError(f"native owned set:{case_id}")
        if sampler.maximum_bytes != sum(rss[pid] for pid in expected_owned):
            raise AssertionError(f"native exact sum:{case_id}")
        return {
            "case_id": case_id,
            "status": "PASS",
            "owned_pids": sorted(sampler.owned_pids),
            "root_rss_bytes": sampler.maximum_root_bytes,
            "whole_tree_rss_bytes": sampler.maximum_bytes,
        }

    rows = [
        positive("ROOT_PROCESS", {100: ()}, {100: 10}, {100}),
        positive(
            "DIRECT_CHILD", {100: (101,), 101: ()},
            {100: 10, 101: 20}, {100, 101},
        ),
        positive(
            "GRANDCHILD", {100: (101,), 101: (102,), 102: ()},
            {100: 10, 101: 20, 102: 30}, {100, 101, 102},
        ),
        positive(
            "EXTRA_DESCENDANT_MEMORY", {100: (101,), 101: (102,), 102: ()},
            {100: 10, 101: 20, 102: 500}, {100, 101, 102},
        ),
    ]

    def exit_case(case_id: str, exit_pid: int) -> Dict[str, Any]:
        children = {100: (101,), 101: (102,), 102: ()}
        rss = {100: 10, 101: 20, 102: 30}
        if exit_pid == 101:
            children = {100: (101,), 101: ()}
            rss = {100: 10, 101: 20}
        elif exit_pid == 100:
            children = {100: ()}
            rss = {100: 10}
        backend = _FakeNativeBackend(children, identities, rss)
        sampler = ProcessTreeRssSampler(100, native_backend=backend)
        sampler._sample()
        if exit_pid == 102:
            backend.children_map[101] = ()
        elif exit_pid == 101:
            backend.children_map[100] = ()
        del backend.identities[exit_pid]
        del backend.rss_map[exit_pid]
        sampler._sample()
        if exit_pid not in sampler.identity_aware_exit_pids:
            raise AssertionError(f"identity-aware exit not recorded:{case_id}")
        return {
            "case_id": case_id, "status": "PASS",
            "identity_aware_exit_pid": exit_pid,
            "sample_count": sampler.sample_count,
        }

    rows.extend([
        exit_case("GRANDCHILD_EXIT", 102),
        exit_case("CHILD_EXIT", 101),
        exit_case("ROOT_EXIT", 100),
    ])

    reuse_backend = _FakeNativeBackend(
        {100: (101,), 101: ()}, identities, {100: 10, 101: 20},
    )
    reuse_sampler = ProcessTreeRssSampler(100, native_backend=reuse_backend)
    reuse_sampler._sample()
    reuse_backend.identities[101] = (100, (101, 99, 99))
    try:
        reuse_sampler._sample()
    except NativeSamplerCapabilityError as error:
        reuse_error = str(error)
    else:
        raise AssertionError("PID reuse accepted")
    rows.append({
        "case_id": "PID_REUSE_REJECTION", "status": "PASS",
        "typed_error": reuse_error,
    })

    for case_id, failure_field, failure_pid, expected in (
        ("CHILD_ENUMERATION_FAILURE", "fail_children_pid", 100,
         "INJECTED_ENUMERATION_FAILURE"),
        ("BSD_INFO_FAILURE", "fail_identity_pid", 101,
         "INJECTED_BSD_FAILURE"),
        ("RSS_FAILURE", "fail_rss_pid", 101, "INJECTED_RSS_FAILURE"),
    ):
        backend = _FakeNativeBackend(
            {100: (101,), 101: ()}, identities, {100: 10, 101: 20},
        )
        setattr(backend, failure_field, failure_pid)
        try:
            sampler = ProcessTreeRssSampler(100, native_backend=backend)
            sampler._sample()
        except NativeSamplerCapabilityError as error:
            observed = str(error)
        else:
            raise AssertionError(f"failure injection accepted:{case_id}")
        if expected not in observed:
            raise AssertionError(f"wrong typed error:{case_id}:{observed}")
        rows.append({
            "case_id": case_id, "status": "PASS", "typed_error": observed,
        })

    mismatched = dict(controller_module.DARWIN_EXPECTED_ABI)
    mismatched["sizeof_proc_taskinfo"] += 1
    with mock.patch.object(
            controller_module, "DARWIN_EXPECTED_ABI", mismatched):
        try:
            DarwinLibprocSamplerBackend()
        except NativeSamplerCapabilityError as error:
            abi_error = str(error)
        else:
            raise AssertionError("ABI mismatch accepted")
    if "ABI_MISMATCH" not in abi_error:
        raise AssertionError(f"wrong ABI typed error:{abi_error}")
    rows.append({
        "case_id": "ABI_MISMATCH", "status": "PASS",
        "typed_error": abi_error,
    })

    expected_ids = [
        "ROOT_PROCESS", "DIRECT_CHILD", "GRANDCHILD",
        "EXTRA_DESCENDANT_MEMORY", "GRANDCHILD_EXIT", "CHILD_EXIT",
        "ROOT_EXIT",
        "PID_REUSE_REJECTION", "CHILD_ENUMERATION_FAILURE",
        "BSD_INFO_FAILURE", "RSS_FAILURE", "ABI_MISMATCH",
    ]
    if [row["case_id"] for row in rows] != expected_ids:
        raise AssertionError("native corpus order")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBNativeSamplerFailureCorpus/v1",
        "status": "PASS",
        "case_count": len(rows),
        "cases": rows,
        "external_process_table_call_count": 0,
        "stage_b_worker_launch_count": 0,
    }
    write_canonical_json(evidence / "NATIVE_SAMPLER_FAILURE_CORPUS.json", value)
    return value


def whole_tree_hard_gate_corpus(evidence: Path) -> Dict[str, Any]:
    request = {
        "memory_admission_required_bytes": 100,
        "disk_admission_required_bytes": 1_000,
        "publication_high_water_bound_bytes": 1_000,
    }
    result = {
        "operation_integer_values": {
            "peak_rss": 40,
            "temporary_physical_disk": 0,
            "final_physical_disk": 0,
            "publication_high_water": 0,
        },
        "integer_metrics": {"peak_rss_repetitions": 40},
        "operation_status": {"peak_rss": "INJECTED_BOUNDED_CONTROL"},
    }
    gate = evaluate_resource_hard_gate(
        request, result, 120,
        {"mechanism_id": controller_module.DARWIN_SAMPLER_MECHANISM_ID},
    )
    if (
        gate["status"] != "STOP"
        or gate["worker_monotonic_peak_rss_bytes"] >= 100
        or gate["controller_process_tree_peak_rss_bytes"] <= 100
        or gate["authoritative_peak_rss_bytes"] != 120
        or gate["violations"] != ["PEAK_RSS_EXCEEDS_MEMORY_ADMISSION"]
        or gate["decision_ledger_eligible"] is not False
    ):
        raise AssertionError(f"whole-tree hard gate:{gate}")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBNativeSamplerHardGateCorpus/v1",
        "status": "PASS",
        "case_id": "ROOT_BELOW_WHOLE_TREE_ABOVE",
        "resource_gate": gate,
        "observed_stop_id": "SB_STOP_MEASURED_RESOURCE",
        "later_request_launch_count": 0,
        "decision_ledger_eligible": False,
    }
    write_canonical_json(evidence / "WHOLE_TREE_HARD_GATE_CORPUS.json", value)
    return value


def preserve_exact_durability(source: Path, evidence: Path) -> tuple[Path, Dict[str, Any]]:
    observed = os.lstat(source)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise AssertionError("durability input must be regular nonsymlink")
    raw = source.read_bytes()
    if sha256(raw) != EXPECTED_DURABILITY_SHA256:
        raise AssertionError("durability input SHA")
    value = strict_json_loads(raw)
    if raw != canonical_json_bytes(value):
        raise AssertionError("durability input canonical bytes")
    target = evidence / "DURABILITY_INPUT.json"
    write_raw(target, raw)
    return target, value


def preserve_capture(path: Path, value: Mapping[str, Any]) -> tuple[bytes, str]:
    write_canonical_json(path, dict(value))
    raw = path.read_bytes()
    return raw, sha256(raw)


def capture_pair(
        runtime: Path, evidence: Path) -> tuple[Path, Path, Dict[str, Any], Dict[str, Any], str, str]:
    branch = dict(capture(runtime))
    validate_capture(branch)
    branch_path = evidence / "FRESH_RESOURCE_CAPTURES" / "WORKLOAD_BRANCH.json"
    series_path = evidence / "FRESH_RESOURCE_CAPTURES" / "CANDIDATE_SERIES.json"
    branch_raw, branch_sha = preserve_capture(branch_path, branch)
    loaded_branch, loaded_branch_raw = load_exact_runtime_resource_capture(
        branch_path, branch_sha,
    )
    if loaded_branch != branch or loaded_branch_raw != branch_raw:
        raise AssertionError("branch capture exact-loader round trip")

    started_ns = time.monotonic_ns()
    total_wait_ns = 0
    attempts = []
    for attempt in range(1, CAPTURE_DISTINCTION_MAX_SERIES_ATTEMPTS + 1):
        series = dict(capture(runtime))
        validate_capture(series)
        series_raw = canonical_json_bytes(series)
        series_sha = sha256(series_raw)
        collision = branch_raw == series_raw or branch_sha == series_sha
        row = {
            "attempt": attempt,
            "capture_time": series["capture_time"],
            "capture_sha256": series_sha,
            "exact_byte_collision_with_branch": collision,
            "bounded_operational_wait_after_nanoseconds": 0,
        }
        if not collision:
            write_raw(series_path, series_raw)
            loaded_series, loaded_series_raw = (
                load_exact_runtime_resource_capture(series_path, series_sha)
            )
            if loaded_series != series or loaded_series_raw != series_raw:
                raise AssertionError("series capture exact-loader round trip")
            row["preserved_path"] = series_path.relative_to(evidence).as_posix()
            attempts.append(row)
            if host_profile(branch) != host_profile(series):
                raise StopSignal(
                    "SB_STOP_RUNTIME_CAPTURE", "branch_series_host_volume",
                )
            operational_elapsed_ns = time.monotonic_ns() - started_ns
            diagnostic_status = (
                "PASS"
                if operational_elapsed_ns <= CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS
                else "STOP_CAPTURE_DISTINCTION_TIMEOUT"
            )
            diagnostic = {
                "schema": (
                    "SplitAlignerR/"
                    "ENGINE003StageBFreshCapturePairDistinction/v1"
                ),
                "status": diagnostic_status,
                "capture_helper_invocation_count": 1 + attempt,
                "series_capture_attempt_count": attempt,
                "collision_retry_count": attempt - 1,
                "configured_retry_wait_nanoseconds": (
                    CAPTURE_DISTINCTION_RETRY_WAIT_NANOSECONDS
                ),
                "configured_timeout_nanoseconds": (
                    CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS
                ),
                "operational_wait_nanoseconds": total_wait_ns,
                "operational_elapsed_nanoseconds": operational_elapsed_ns,
                "stage_b_worker_invoked": False,
                "stage_b_measured_clock": False,
                "synthetic_capture_mutation_used": False,
                "branch_capture_time": branch["capture_time"],
                "candidate_series_capture_time": series["capture_time"],
                "branch_capture_sha256": branch_sha,
                "candidate_series_capture_sha256": series_sha,
                "captures_distinct_exact_bytes": branch_raw != series_raw,
                "captures_distinct_sha256": branch_sha != series_sha,
                "attempts": attempts,
            }
            write_canonical_json(
                evidence / "FRESH_RESOURCE_CAPTURES" / "PAIR_DIAGNOSTIC.json",
                diagnostic,
            )
            if diagnostic_status != "PASS":
                raise StopSignal(
                    "SB_STOP_RUNTIME_CAPTURE",
                    "fresh_capture_pair_distinction_timeout",
                )
            return (
                branch_path, series_path, branch, series,
                branch_sha, series_sha,
            )

        rejected_path = (
            evidence / "FRESH_RESOURCE_CAPTURES" / "DISTINCTION_RETRIES" /
            f"SERIES_ATTEMPT_{attempt:02d}.json"
        )
        write_raw(rejected_path, series_raw)
        row["preserved_path"] = rejected_path.relative_to(evidence).as_posix()
        attempts.append(row)
        elapsed_ns = time.monotonic_ns() - started_ns
        if (
            attempt == CAPTURE_DISTINCTION_MAX_SERIES_ATTEMPTS
            or elapsed_ns >= CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS
        ):
            write_canonical_json(
                evidence / "FRESH_RESOURCE_CAPTURES" / "PAIR_DIAGNOSTIC.json",
                {
                    "schema": (
                        "SplitAlignerR/"
                        "ENGINE003StageBFreshCapturePairDistinction/v1"
                    ),
                    "status": "STOP_CAPTURE_DISTINCTION",
                    "capture_helper_invocation_count": 1 + attempt,
                    "series_capture_attempt_count": attempt,
                    "collision_retry_count": attempt,
                    "configured_retry_wait_nanoseconds": (
                        CAPTURE_DISTINCTION_RETRY_WAIT_NANOSECONDS
                    ),
                    "configured_timeout_nanoseconds": (
                        CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS
                    ),
                    "operational_wait_nanoseconds": total_wait_ns,
                    "operational_elapsed_nanoseconds": elapsed_ns,
                    "stage_b_worker_invoked": False,
                    "stage_b_measured_clock": False,
                    "synthetic_capture_mutation_used": False,
                    "branch_capture_time": branch["capture_time"],
                    "branch_capture_sha256": branch_sha,
                    "attempts": attempts,
                },
            )
            raise StopSignal(
                "SB_STOP_RUNTIME_CAPTURE", "fresh_capture_pair_not_distinct",
            )
        remaining_ns = CAPTURE_DISTINCTION_TIMEOUT_NANOSECONDS - elapsed_ns
        wait_ns = min(
            CAPTURE_DISTINCTION_RETRY_WAIT_NANOSECONDS, remaining_ns,
        )
        row["bounded_operational_wait_after_nanoseconds"] = wait_ns
        time.sleep(wait_ns / 1_000_000_000)
        total_wait_ns += wait_ns

    raise AssertionError("unreachable capture-pair distinction loop")


def make_request(
        authority: ExecutionAuthority, assets: FrozenAssets,
        branch_sha: str, series: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path, target_name: str) -> Dict[str, Any]:
    request = make_bounded_request(
        authority, assets, series, durability, "COLUMN_MAJOR_DISK",
        ALL_CANDIDATES.index("COLUMN_MAJOR_DISK") + 1,
        runtime / target_name, evidence,
    )
    request["workload_branch_resource_capture_sha256"] = branch_sha
    return request


def mutation_row(
        case_id: str, authority: ExecutionAuthority, assets: FrozenAssets,
        request: Mapping[str, Any], runtime: Path,
        series_path: Path, durability: Mapping[str, Any],
        branch_path: Path | None, expected: str) -> Dict[str, Any]:
    presented_series_sha = file_sha256(series_path)
    presented_branch_sha = (
        "OMITTED" if branch_path is None else file_sha256(branch_path)
    )
    stop_id = "NONE"
    stop_detail = "NONE"
    observed = "PASS"
    guard = None
    worker_guard = None
    duplicate_guard_invocation_count = 0
    series_exact_loader_pass = False
    branch_exact_loader_pass = False
    try:
        series, _series_raw = load_exact_runtime_resource_capture(
            series_path, request["fresh_resource_capture_sha256"],
        )
        series_exact_loader_pass = True
        if branch_path is None:
            raise StopSignal(
                "SB_STOP_RUNTIME_CAPTURE", "workload_branch_resource_omitted",
            )
        branch, _branch_raw = load_exact_runtime_resource_capture(
            branch_path, request["workload_branch_resource_capture_sha256"],
        )
        branch_exact_loader_pass = True
        guard = prelaunch_guard(
            authority, assets, request, runtime, series, durability, branch,
        )
        worker_series, _worker_series_raw = load_exact_runtime_resource_capture(
            series_path, request["fresh_resource_capture_sha256"],
        )
        worker_branch, _worker_branch_raw = load_exact_runtime_resource_capture(
            branch_path, request["workload_branch_resource_capture_sha256"],
        )
        worker_guard = prelaunch_guard(
            authority, assets, request, runtime,
            worker_series, durability, worker_branch,
        )
        duplicate_guard_invocation_count = 1
    except StopSignal as error:
        observed = "REJECT"
        stop_id = error.stop_id
        stop_detail = error.detail
    if observed != expected:
        raise AssertionError(f"mutation case:{case_id}:{observed}!={expected}")
    presented_series = strict_json_load(series_path)
    presented_branch = (
        None if branch_path is None else strict_json_load(branch_path)
    )
    presented_host_volume_match = (
        False if presented_branch is None
        else host_profile(presented_series) == host_profile(presented_branch)
    )
    target_exists = Path(request["runtime_target"]).exists()
    if target_exists:
        raise AssertionError(f"mutation target unexpectedly exists:{case_id}")
    return {
        "case_id": case_id,
        "status": "PASS",
        "observed_outcome": observed,
        "observed_stop_id": stop_id,
        "observed_stop_detail": stop_detail,
        "request_candidate_series_sha256": request[
            "fresh_resource_capture_sha256"
        ],
        "request_workload_branch_sha256": request[
            "workload_branch_resource_capture_sha256"
        ],
        "presented_candidate_series_sha256": presented_series_sha,
        "presented_workload_branch_sha256": presented_branch_sha,
        "mutated_file_sha256_recomputed": (
            case_id == "WRONG_BRANCH_BYTES_RECOMPUTED_SHA"
        ),
        "presented_host_volume_match": presented_host_volume_match,
        "candidate_series_exact_loader_pass": series_exact_loader_pass,
        "workload_branch_exact_loader_pass": branch_exact_loader_pass,
        "rejection_stage": (
            "PRELAUNCH_GUARD_PASS" if guard is not None
            else "CANDIDATE_SERIES_EXACT_LOADER"
            if not series_exact_loader_pass
            else "WORKLOAD_BRANCH_EXACT_LOADER"
            if not branch_exact_loader_pass
            else "SEVEN_ARGUMENT_PRELAUNCH_GUARD"
        ),
        "controller_guard_pass": guard is not None,
        "worker_guard_pass": worker_guard is not None,
        "duplicate_guard_invocation_count": duplicate_guard_invocation_count,
        "pretarget_rejection": observed == "REJECT",
        "physical_worker_launch_count": 0,
        "physical_allocation_count": 0,
        "backend_target_binding_count": 0,
    }


def branch_binding_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        runtime: Path, evidence: Path, durability: Mapping[str, Any],
        branch: Mapping[str, Any], series: Mapping[str, Any],
        branch_sha: str, series_sha: str) -> Dict[str, Any]:
    base = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "mutation-never-created",
    )
    mutation_root = evidence / "MUTATION_RESOURCES"
    wrong_branch = dict(branch)
    wrong_branch["capture_time"] = branch["capture_time"] + "-WRONG-BRANCH"
    wrong_branch_path = mutation_root / "WRONG_BRANCH.json"
    _, wrong_branch_sha = preserve_capture(wrong_branch_path, wrong_branch)
    wrong_series = dict(series)
    wrong_series["capture_time"] = series["capture_time"] + "-WRONG-SERIES"
    wrong_series_path = mutation_root / "WRONG_SERIES.json"
    _, wrong_series_sha = preserve_capture(wrong_series_path, wrong_series)
    host_mismatch = dict(branch)
    host_mismatch["target_volume_device"] = "/dev/BRANCH_FIX001_MISMATCH"
    host_mismatch_path = mutation_root / "HOST_VOLUME_MISMATCH.json"
    _, host_mismatch_sha = preserve_capture(host_mismatch_path, host_mismatch)
    host_request = copy.deepcopy(base)
    host_request["workload_branch_resource_capture_sha256"] = host_mismatch_sha
    branch_path = evidence / "FRESH_RESOURCE_CAPTURES" / "WORKLOAD_BRANCH.json"
    series_path = evidence / "FRESH_RESOURCE_CAPTURES" / "CANDIDATE_SERIES.json"

    rows = [
        mutation_row(
            "TRUE_BRANCH_TRUE_SERIES", authority, assets, base, runtime,
            series_path, durability, branch_path, "PASS",
        ),
        mutation_row(
            "BRANCH_OMITTED", authority, assets, base, runtime,
            series_path, durability, None, "REJECT",
        ),
        mutation_row(
            "BRANCH_REPLACED_BY_SERIES", authority, assets, base, runtime,
            series_path, durability, series_path, "REJECT",
        ),
        mutation_row(
            "SERIES_REPLACED_BY_BRANCH", authority, assets, base, runtime,
            branch_path, durability, branch_path, "REJECT",
        ),
        mutation_row(
            "WRONG_BRANCH_BYTES_RECOMPUTED_SHA", authority, assets, base, runtime,
            series_path, durability, wrong_branch_path, "REJECT",
        ),
        mutation_row(
            "WRONG_SERIES_BYTES", authority, assets, base, runtime,
            wrong_series_path, durability, branch_path, "REJECT",
        ),
        mutation_row(
            "HOST_VOLUME_MISMATCH", authority, assets, host_request, runtime,
            series_path, durability, host_mismatch_path, "REJECT",
        ),
    ]
    if len(rows) != 7:
        raise AssertionError("mutation binding cardinality")
    if tuple(row["case_id"] for row in rows) != MUTATION_CASE_IDS:
        raise AssertionError("mutation preregistered order")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBBranchBindingMutationCorpus/v1",
        "status": "PASS",
        "workload_branch_capture_sha256": branch_sha,
        "candidate_series_capture_sha256": series_sha,
        "wrong_branch_recomputed_sha256": wrong_branch_sha,
        "wrong_series_recomputed_sha256": wrong_series_sha,
        "host_mismatch_recomputed_sha256": host_mismatch_sha,
        "cases": rows,
    }
    write_canonical_json(evidence / "BRANCH_BINDING_MUTATION_CORPUS.json", value)
    return value


def worker_cli_omission(
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, durability_path: Path, request: Mapping[str, Any]) -> Dict[str, Any]:
    root = evidence / "CLI_OMISSION"
    request_path = root / "worker.request.json"
    output_path = root / "worker.result.json"
    write_canonical_json(request_path, dict(request))
    command = [
        sys.executable, "-B", str(HERE / "stage_b_worker.py"),
        "--repo-root", str(repo), "--runtime-root", str(runtime),
        "--resource", str(series_path), "--durability", str(durability_path),
        "--request", str(request_path), "--output", str(output_path),
    ]
    process = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    stdout_path = root / "worker.stdout.bin"
    stderr_path = root / "worker.stderr.bin"
    write_raw(stdout_path, process.stdout)
    write_raw(stderr_path, process.stderr)
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBWorkerCliBranchOmission/v1",
        "status": "PASS" if process.returncode != 0 and not output_path.exists() else "FAIL",
        "argv": command,
        "branch_resource_argument_present": False,
        "cli_rejected": process.returncode != 0,
        "exit_code": process.returncode,
        "stdout_path": stdout_path.relative_to(evidence).as_posix(),
        "stdout_sha256": file_sha256(stdout_path),
        "stderr_path": stderr_path.relative_to(evidence).as_posix(),
        "stderr_sha256": file_sha256(stderr_path),
        "worker_process_invocation_count": 1,
        "stage_b_live_worker_entry_count": 0,
        "worker_launch_count": 0,
        "physical_allocation_count": 0,
        "backend_target_binding_count": 0,
    }
    write_canonical_json(evidence / "WORKER_CLI_BRANCH_OMISSION.json", value)
    if value["status"] != "PASS":
        raise AssertionError("worker CLI accepted missing branch resource")
    return value


def sampler_capability_prelaunch_stop(
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        request: Mapping[str, Any]) -> Dict[str, Any]:
    root = evidence / "SAMPLER_CAPABILITY_STOP"
    worker_marker = root / "worker-process-started.marker"
    worker_command = [
        sys.executable, "-B", "-c",
        "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('STARTED\\n')",
        str(worker_marker),
    ]

    def rejected_backend():
        raise NativeSamplerCapabilityError("INJECTED_ABI_MISMATCH")

    try:
        launch_request(
            repo, runtime, series_path, durability_path, request,
            root / "worker.request.json", root / "worker.result.json",
            root / "controller.log.txt", branch_path,
            worker_command=worker_command,
            sampler_backend_factory=rejected_backend,
        )
    except StopSignal as error:
        observed = error.stop_id
        detail = str(error)
    else:
        raise AssertionError("sampler capability failure was accepted")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerCapabilityStop/v1",
        "status": "PASS",
        "observed_stop_id": observed,
        "typed_detail": detail,
        "worker_popen_call_count": 0 if not worker_marker.exists() else 1,
        "worker_marker_path": str(worker_marker),
        "worker_marker_exists": worker_marker.exists(),
        "worker_launch_count": 0,
        "runtime_target_exists": Path(request["runtime_target"]).exists(),
        "decision_ledger_eligible": False,
    }
    if (
        observed != "SB_STOP_SAMPLER_CAPABILITY"
        or "INJECTED_ABI_MISMATCH" not in detail
        or worker_marker.exists() or value["runtime_target_exists"]
    ):
        raise AssertionError(f"sampler capability stop:{value}")
    write_canonical_json(evidence / "SAMPLER_CAPABILITY_PRELAUNCH_STOP.json", value)
    return value


def preserved_record(
        evidence: Path, path: Path, source: str,
        allow_absent: bool = False) -> Dict[str, Any]:
    if not path.is_file():
        if allow_absent:
            return {
                "source": source, "relative_path": path.relative_to(evidence).as_posix(),
                "preserved": False, "bytes": 0, "sha256": "NOT_AVAILABLE",
            }
        raise AssertionError(f"required preserved file absent:{path}")
    raw = path.read_bytes()
    return {
        "source": source, "relative_path": path.relative_to(evidence).as_posix(),
        "preserved": True, "bytes": len(raw), "sha256": sha256(raw),
    }


def normalize_controller_preserved_record(
        evidence: Path, record: Mapping[str, Any], expected_path: Path,
        label: str, allow_absent: bool = False) -> Dict[str, Any]:
    required = {"path", "preserved", "bytes", "sha256", "source"}
    if not isinstance(record, Mapping) or set(record) != required:
        raise AssertionError(f"controller preserved record field set:{label}")
    if record["path"] != str(expected_path):
        raise AssertionError(f"controller preserved record path:{label}")
    observed = preserved_record(
        evidence, expected_path, str(record["source"]), allow_absent,
    )
    for field in ("preserved", "bytes", "sha256"):
        if observed[field] != record[field]:
            raise AssertionError(
                f"controller preserved record mismatch:{label}:{field}"
            )
    return observed


class _StoppedThread:
    def is_alive(self) -> bool:
        return False


class _InjectedInvalidSampler:
    def __init__(
            self, root_pid: int, interval: int = 0,
            native_backend: Any | None = None) -> None:
        self.root_pid = root_pid
        self.interval = 0.01
        self.maximum_bytes = 0
        self.maximum_root_bytes = 0
        self.sample_count = 0
        self.owned_pids = {root_pid}
        self.active_owned_pids = set()
        self.owned_process_identities = {}
        self.identity_aware_exit_pids = set()
        self.error = "INJECTED_SAMPLER_DIAGNOSTIC_FAILURE"
        self._thread = _StoppedThread()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def owned_identity_snapshot(self) -> Dict[int, str]:
        return {self.root_pid: ""}


def injected_worker_command(partial_path: Path, exit_code: int) -> list[str]:
    program = (
        "import json,pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);"
        "p.write_text(json.dumps({'schema':'SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1',"
        "'last_completed_phase':'NONE','current_phase':'INJECTED_PRELAUNCH'},"
        "sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8');"
        "raise SystemExit(int(sys.argv[2]))"
    )
    return [sys.executable, "-B", "-c", program, str(partial_path), str(exit_code)]


def delayed_same_pid_exec_command(
        command: list[str], operational_delay_nanoseconds: int) -> list[str]:
    program = (
        "import os,sys,time;"
        "time.sleep(int(sys.argv[1])/1000000000);"
        "os.execv(sys.argv[2],sys.argv[2:])"
    )
    return [
        sys.executable, "-B", "-c", program,
        str(operational_delay_nanoseconds), *command,
    ]


def precedence_case(
        case_id: str, repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        request: Mapping[str, Any], command: list[str],
        expected_stop: str, sampler_class: Any | None = None,
        pre_worker_operational_delay_nanoseconds: int = 0,
        real_worker_exec_same_pid: bool = False) -> Dict[str, Any]:
    root = evidence / "STOP_PRECEDENCE" / case_id
    request_path = root / "worker.request.json"
    output_path = root / "worker.result.json"
    log_path = root / "controller.log.txt"
    context = (
        mock.patch.object(controller_module, "ProcessTreeRssSampler", sampler_class)
        if sampler_class is not None else mock.patch.object(
            controller_module, "ProcessTreeRssSampler",
            controller_module.ProcessTreeRssSampler,
        )
    )
    try:
        with context:
            launch_request(
                repo, runtime, series_path, durability_path, request,
                request_path, output_path, log_path, branch_path,
                worker_command=command, watchdog_timeout_seconds=30,
            )
    except StopSignal as error:
        if error.stop_id != expected_stop:
            raise
        observed_stop = error.stop_id
    else:
        raise AssertionError(f"precedence case unexpectedly passed:{case_id}")
    sampler_path = output_path.with_suffix(".sampler.json")
    sampler = strict_json_load(sampler_path)
    if (
        case_id == "WORKER_NONZERO_SAMPLER_VALID"
        and sampler.get("sampler_valid") is not True
    ):
        raise AssertionError("worker-nonzero valid-sampler control invalid")
    failure_path = output_path.with_suffix(".worker-failure.json")
    if failure_path.is_file():
        failure = strict_json_load(failure_path)
        if (
            failure.get("status") != "SB_STOP_VALIDATION"
            or failure.get("classification")
            != "WORKER_FAILURE_PRECEDES_SAMPLER_INTERPRETATION"
            or failure.get("worker_return_code")
            != sampler["worker_return_code"]
            or failure.get("sampler_diagnostic") != sampler
        ):
            raise AssertionError("controller worker-failure sidecar identity")
        eligible = failure["sampler_interpretation_eligible"]
        failure_relative = failure_path.relative_to(evidence).as_posix()
        failure_sha = file_sha256(failure_path)
        controller_preserved = failure.get("preserved_files")
        if not isinstance(controller_preserved, Mapping):
            raise AssertionError("controller preserved map absent")
        expected_paths = {
            "worker_log": (log_path, False),
            "partial_worker_evidence": (
                output_path.with_suffix(".partial.json"), True,
            ),
            "request": (request_path, False),
            "candidate_series_resource": (series_path, False),
            "workload_branch_resource": (branch_path, False),
            "sampler_diagnostic": (sampler_path, False),
        }
        preserved = {
            name: normalize_controller_preserved_record(
                evidence, controller_preserved[name], path,
                name, allow_absent,
            )
            for name, (path, allow_absent) in expected_paths.items()
        }
        controller_preserved_map_verified = True
    else:
        if sampler["worker_return_code"] != 0:
            raise AssertionError("nonzero worker missing failure sidecar")
        eligible = expected_stop == "SB_STOP_MEASURED_RESOURCE"
        failure_relative = "ABSENT"
        failure_sha = "NOT_AVAILABLE"
        preserved = {
            "worker_log": preserved_record(evidence, log_path, "controller_log"),
            "partial_worker_evidence": preserved_record(
                evidence, output_path.with_suffix(".partial.json"),
                "worker_partial", allow_absent=True,
            ),
            "request": preserved_record(evidence, request_path, "request"),
            "candidate_series_resource": preserved_record(
                evidence, series_path, "candidate_series_resource",
            ),
            "workload_branch_resource": preserved_record(
                evidence, branch_path, "workload_branch_resource",
            ),
            "sampler_diagnostic": preserved_record(
                evidence, sampler_path, "sampler_diagnostic",
            ),
        }
        controller_preserved_map_verified = "NOT_APPLICABLE_WORKER_ZERO"
    return {
        "case_id": case_id,
        "status": "PASS",
        "observed_primary_stop_id": observed_stop,
        "worker_return_code": sampler["worker_return_code"],
        "sampler_interpretation_eligible": eligible,
        "sampler_diagnostic": sampler,
        "worker_command": command,
        "pre_worker_operational_delay_nanoseconds": (
            pre_worker_operational_delay_nanoseconds
        ),
        "pre_worker_delay_stage_b_clock": False,
        "real_worker_exec_same_pid": real_worker_exec_same_pid,
        "worker_failure_stop_path": failure_relative,
        "worker_failure_stop_sha256": failure_sha,
        "controller_preserved_map_verified": controller_preserved_map_verified,
        "preserved_files": preserved,
        "decision_ledger_rows": 0,
        "later_request_launch_count": 0,
        "physical_allocation_count": 0,
    }


def stop_precedence_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        durability: Mapping[str, Any], branch_sha: str,
        series: Mapping[str, Any]) -> Dict[str, Any]:
    cases = []
    actual_request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "precedence-valid-sampler-never-bound",
    )
    wrong_branch = evidence / "MUTATION_RESOURCES" / "WRONG_BRANCH.json"
    actual_root = evidence / "STOP_PRECEDENCE" / "WORKER_NONZERO_SAMPLER_VALID"
    real_worker_command = [
        sys.executable, "-B", str(HERE / "stage_b_worker.py"),
        "--repo-root", str(repo), "--runtime-root", str(runtime),
        "--resource", str(series_path), "--branch-resource", str(wrong_branch),
        "--durability", str(durability_path),
        "--request", str(actual_root / "worker.request.json"),
        "--output", str(actual_root / "worker.result.json"),
    ]
    valid_sampler_delay_nanoseconds = 300_000_000
    actual_command = delayed_same_pid_exec_command(
        real_worker_command, valid_sampler_delay_nanoseconds,
    )
    cases.append(precedence_case(
        "WORKER_NONZERO_SAMPLER_VALID", repo, runtime, evidence,
        series_path, branch_path, durability_path, actual_request,
        actual_command, "SB_STOP_VALIDATION", None,
        valid_sampler_delay_nanoseconds, True,
    ))

    invalid_request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "precedence-invalid-sampler-never-bound",
    )
    invalid_partial = (
        evidence / "STOP_PRECEDENCE" / "WORKER_NONZERO_SAMPLER_INVALID" /
        "worker.result.partial.json"
    )
    cases.append(precedence_case(
        "WORKER_NONZERO_SAMPLER_INVALID", repo, runtime, evidence,
        series_path, branch_path, durability_path, invalid_request,
        injected_worker_command(invalid_partial, 17),
        "SB_STOP_VALIDATION", _InjectedInvalidSampler,
    ))

    zero_request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "precedence-zero-invalid-sampler-never-bound",
    )
    zero_partial = (
        evidence / "STOP_PRECEDENCE" / "WORKER_ZERO_SAMPLER_INVALID" /
        "worker.result.partial.json"
    )
    cases.append(precedence_case(
        "WORKER_ZERO_SAMPLER_INVALID", repo, runtime, evidence,
        series_path, branch_path, durability_path, zero_request,
        injected_worker_command(zero_partial, 0),
        "SB_STOP_MEASURED_RESOURCE", _InjectedInvalidSampler,
    ))
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBStopPrecedenceCorpus/v1",
        "status": "PASS",
        "cases": cases,
    }
    write_canonical_json(evidence / "STOP_PRECEDENCE_CORPUS.json", value)
    return value


def bounded_e2e(
        authority: ExecutionAuthority, assets: FrozenAssets,
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        series: Mapping[str, Any], branch: Mapping[str, Any],
        durability: Mapping[str, Any], branch_sha: str, series_sha: str) -> Dict[str, Any]:
    target = runtime / "branch-fix001-bounded-column-major"
    request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, target.name,
    )
    identity = {field: request[field] for field in REQUEST_IDENTITY_FIELDS}
    plan = {
        "workload_id": BOUNDED_WORKLOAD,
        "branch_capture_path": str(branch_path),
        "branch_capture_sha256": branch_sha,
        "compact_admission_result": "PASS",
        "capture_rows": [{
            "scope_id": "BRANCH_FIX001_BOUNDED_WORKLOAD_BRANCH",
            "workload_id": BOUNDED_WORKLOAD,
            "candidate_id": "NOT_APPLICABLE",
            "capture_path": str(branch_path),
            "capture_sha256": branch_sha,
            "capture_role": "WORKLOAD_BRANCH_SELECTION",
            "compact_admission_result": "PASS",
        }],
        "static_launch_rows": [{
            "request_index": 0, "candidate_id": "COLUMN_MAJOR_DISK",
            "run_phase": request["run_phase"], "request_identity": identity,
        }],
        "allowed_candidate_ids": ["COLUMN_MAJOR_DISK"],
        "candidate_first_launch_order": ["COLUMN_MAJOR_DISK"],
        "request_identity_sha256": sha256(canonical_json_bytes([identity])),
    }

    def binder(
            observed_authority, observed_assets, observed_durability,
            observed_plan, candidate, observed_evidence, _capture_provider,
            ordinal, observed_activation, observed_branch):
        if (
            observed_authority.commit != authority.commit
            or observed_assets.authority.tree != assets.authority.tree
            or observed_durability != durability
            or observed_plan is not plan
            or candidate != "COLUMN_MAJOR_DISK"
            or observed_evidence != evidence
            or observed_activation != request["activation"]
            or observed_branch != branch
        ):
            raise AssertionError("bounded orchestrator binder identity")
        return {
            "capture_row": {
                "scope_id": "BRANCH_FIX001_BOUNDED_CANDIDATE_SERIES",
                "workload_id": BOUNDED_WORKLOAD,
                "candidate_id": candidate,
                "capture_path": str(series_path),
                "capture_sha256": series_sha,
                "capture_role": "CANDIDATE_WORKLOAD_SERIES",
                "compact_admission_result": "PASS",
            },
            "resource": dict(series), "resource_path": series_path,
            "requests": {0: request}, "next_capture_ordinal": ordinal + 1,
        }

    def guard_callback(
            observed_request, observed_series_path, observed_series,
            observed_branch_path, observed_branch):
        if observed_series_path != series_path or observed_branch_path != branch_path:
            raise AssertionError("orchestrator exact resource paths")
        return prelaunch_guard(
            authority, assets, observed_request, runtime,
            observed_series, durability, observed_branch,
        )

    replay_root = evidence / "BOUNDED_REPLAY"

    def launch_callback(
            observed_request, index, observed_series_path, observed_branch_path):
        if index != 0:
            raise AssertionError("bounded launch index")
        return launch_request(
            repo, runtime, observed_series_path, durability_path,
            observed_request, replay_root / "worker.request.json",
            replay_root / "worker.result.json", replay_root / "controller.log.txt",
            observed_branch_path,
        )

    with mock.patch.object(orchestrator_module, "bind_candidate_series", binder):
        result = execute_runtime_bound_workload(
            authority, assets, durability, plan, evidence, None, 2,
            request["activation"], guard_callback, launch_callback,
        )
    if len(result["results"]) != 1:
        raise AssertionError("bounded E2E result cardinality")
    worker = strict_json_load(replay_root / "worker.result.json")
    sampler = strict_json_load(replay_root / "worker.result.sampler.json")
    gate = worker.get("measured_resource_gate", {})
    adapter_source_sha256 = sha256(canonical_json_bytes({
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "adapter_function": "bounded_e2e.binder",
        "patched_symbol": "stage_b_orchestrator.bind_candidate_series",
    }))
    e2e = {
        "schema": "SplitAlignerR/ENGINE003StageBBoundedDistinctCaptureE2E/v1",
        "status": "PASS",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "execution_path": ["orchestrator", "controller", "worker"],
        "orchestrator_execution_loop": "execute_runtime_bound_workload",
        "candidate_binder_mode": "BOUNDED_TEST_ADAPTER_ONLY",
        "production_bind_candidate_series_invoked": False,
        "production_orchestrator_source_changed": False,
        "adapter_scope": "CANDIDATE_SERIES_BINDING_ONLY",
        "adapter_source_sha256": adapter_source_sha256,
        "authority_sized_request_count": 0,
        "large_store_count": 0,
        "workload_branch_capture_sha256": branch_sha,
        "candidate_series_capture_sha256": series_sha,
        "captures_distinct": branch_sha != series_sha,
        "orchestrator_branch_binding_pass": (
            result["dynamic_binding_rows"][0]["request_capture_sha256_exact"] is True
        ),
        "controller_prelaunch_guard_pass": (
            worker.get("controller_prelaunch_status")
            == "PRELAUNCH_PASS_BOUNDED_PHYSICAL_ALLOWED"
        ),
        "worker_prelaunch_guard_pass": (
            worker.get("worker_prelaunch_status")
            == "PRELAUNCH_PASS_BOUNDED_PHYSICAL_ALLOWED"
        ),
        "controller_sampler_pass": sampler.get("sampler_valid") is True,
        "logical_correctness_pass": (
            worker.get("bounded_validator", {}).get("status") == "PASS"
        ),
        "resource_hard_gate_pass": gate.get("status") == "PASS",
        "bounded_store_cleanup_pass": (
            worker.get("cleanup_result") == "PASS_TARGET_REMOVED"
            and not target.exists()
        ),
        "worker_launch_count": 1,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_measured_timing": worker.get("stage_b_measured_timing"),
        "decision_engine_invocation_count": 0,
        "performance_conclusion_authorized": worker.get(
            "performance_conclusion_authorized"
        ),
        "runtime_target_exists_after_cleanup": target.exists(),
        "worker_result_path": "BOUNDED_REPLAY/worker.result.json",
        "worker_result_sha256": file_sha256(replay_root / "worker.result.json"),
        "sampler_diagnostic_path": "BOUNDED_REPLAY/worker.result.sampler.json",
        "sampler_diagnostic_sha256": file_sha256(
            replay_root / "worker.result.sampler.json"
        ),
        "sampler_diagnostic": sampler,
    }
    if not all(e2e[field] is True for field in (
            "orchestrator_branch_binding_pass", "controller_prelaunch_guard_pass",
            "worker_prelaunch_guard_pass", "controller_sampler_pass",
            "logical_correctness_pass", "resource_hard_gate_pass",
            "bounded_store_cleanup_pass")):
        raise AssertionError(f"bounded E2E gate:{e2e}")
    if e2e["stage_b_measured_timing"] is not False:
        raise AssertionError("bounded replay mislabeled Stage-B timing")
    write_canonical_json(evidence / "BOUNDED_DISTINCT_CAPTURE_E2E.json", e2e)
    return e2e


def write_zero_proof(runtime: Path, evidence: Path) -> Dict[str, Any]:
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix001ZeroExecutionProof/v1",
        "status": "PASS_BOUNDED_PREFLIGHT_ONLY",
        "authorized_stage_b_worker_launch_count": 0,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "large_backend_target_binding_count": 0,
        "large_store_open_count": 0,
        "stage_b_measured_clock_count": 0,
        "stage_b_measured_result_count": 0,
        "decision_engine_invocation_count": 0,
        "performance_decision_count": 0,
        "stage_b_execution_authorized": False,
        "bounded_e2e_worker_launch_count": 1,
        "precedence_control_process_launch_count": 3,
        "precedence_real_worker_live_entry_count": 1,
        "precedence_injected_control_process_count": 2,
        "worker_cli_parser_process_count": 1,
        "worker_cli_live_entry_count": 0,
        "controlled_sampler_root_process_count": 1,
        "controlled_sampler_descendant_process_count": 1,
        "controlled_sampler_descendant_allocation_bytes": 48 * 1024 * 1024,
        "external_ps_command_invocation_count": 0,
        "live_native_libproc_sampler_instance_count": 4,
        "synthetic_native_sampler_instance_count": 11,
        "native_backend_capability_only_instance_count": 2,
        "native_failure_injection_case_count": 12,
        "bounded_or_diagnostic_stage_b_worker_live_entry_count": 2,
        "bounded_candidate_store_construction_count": 1,
        "bounded_candidate_store_cleaned": True,
        "attempt002_authorization_reused": False,
        "attempt002_runtime_root_reused": False,
        "attempt002_evidence_root_reused": False,
        "retired_attempt002_authorization_sha256": ATTEMPT002_AUTHORIZATION_SHA256,
        "retired_attempt002_roots": [str(path) for path in ATTEMPT002_ROOTS],
        "branch_fix_runtime_root": str(runtime),
        "branch_fix_evidence_root": str(evidence),
        "runtime_root_final_entry_count": len(list(runtime.iterdir())),
    }
    if value["runtime_root_final_entry_count"] != 0:
        raise AssertionError("bounded runtime root not clean")
    write_canonical_json(evidence / "ZERO_LARGE_EXECUTION_PROOF.json", value)
    return value


def evidence_hashes(evidence: Path) -> Dict[str, str]:
    result = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "SAMPLER_FIX001_SUMMARY.json":
            result[path.relative_to(evidence).as_posix()] = file_sha256(path)
    return result


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = args.repo_root.resolve()
    runtime_input = lexical_absolute(args.runtime_root)
    evidence_input = lexical_absolute(args.evidence_root)
    durability_input = lexical_absolute(args.durability)
    runtime_identity = require_fresh_root(runtime_input, "runtime root")
    evidence_identity = require_fresh_root(evidence_input, "evidence root")
    runtime = runtime_input.resolve(strict=True)
    evidence = evidence_input.resolve(strict=True)
    if runtime == evidence or runtime in evidence.parents or evidence in runtime.parents:
        raise AssertionError("BRANCH-FIX roots overlap")
    commit, tree, pre = assert_source(repo)
    authority = ExecutionAuthority(repo, commit, tree)
    assets = FrozenAssets(authority)

    durability_path, durability = preserve_exact_durability(
        durability_input, evidence,
    )
    external_ps_independence_regression(evidence)
    controller_sha = sha256(git_bytes(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    ))
    controlled_sampler_diagnostic(repo, evidence, controller_sha)
    native_sampler_failure_corpus(evidence)
    whole_tree_hard_gate_corpus(evidence)
    branch_path, series_path, branch, series, branch_sha, series_sha = capture_pair(
        runtime, evidence,
    )
    branch_binding_corpus(
        authority, assets, runtime, evidence, durability,
        branch, series, branch_sha, series_sha,
    )
    omission_request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "cli-omission-never-created",
    )
    worker_cli_omission(
        repo, runtime, evidence, series_path, durability_path, omission_request,
    )
    capability_request = make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "sampler-capability-never-created",
    )
    sampler_capability_prelaunch_stop(
        repo, runtime, evidence, series_path, branch_path,
        durability_path, capability_request,
    )
    stop_precedence_corpus(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        durability, branch_sha, series,
    )
    bounded_e2e(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        series, branch, durability, branch_sha, series_sha,
    )
    zero = write_zero_proof(runtime, evidence)
    post = source_checkpoint(repo)
    if post != pre:
        raise AssertionError("source changed during bounded evidence run")
    source = {
        "schema": "SplitAlignerR/ENGINE003StageBBranchFix001SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_identity, "evidence_root": evidence_identity,
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    checker_sha = sha256(git_bytes(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix001.py",
    ))
    runner_sha = sha256(Path(__file__).read_bytes())
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": SUMMARY_STATUS,
        "source_commit": commit, "source_tree": tree, "direct_parent": BASE_COMMIT,
        "runner_sha256": runner_sha, "checker_sha256": checker_sha,
        "workload_branch_capture_sha256": branch_sha,
        "candidate_series_capture_sha256": series_sha,
        "mutation_case_count": 7,
        "native_sampler_failure_case_count": 12,
        "external_ps_command_invocation_count": 0,
        "sampler_capability_prelaunch_worker_launch_count": 0,
        "whole_tree_hard_gate_stop_count": 1,
        "worker_first_precedence_case_count": 2,
        "sampler_primary_case_count": 1,
        "bounded_e2e_worker_launch_count": 1,
        "diagnostic_worker_live_entry_count": 1,
        "bounded_or_diagnostic_stage_b_worker_live_entry_count": 2,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_measured_clock_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": zero["runtime_root_final_entry_count"],
        "claim_ceiling": "BOUNDED_SAMPLER_AND_BRANCH_FIX_PREFLIGHT_ONLY_NO_STAGEB_PERFORMANCE_CLAIM",
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "SAMPLER_FIX001_SUMMARY.json", summary)
    return summary


def self_test() -> None:
    if len(MUTATION_CASE_IDS) != 7 or len(set(MUTATION_CASE_IDS)) != 7:
        raise AssertionError("mutation case contract")
    if any(same_or_descendant(ATTEMPT002_ROOTS[0], root)
           for root in ATTEMPT002_ROOTS[1:]):
        raise AssertionError("retired root contract")
    print(
        "PASS_SAMPLER_FIX001_RUNNER_SELF_TEST MUTATIONS=7 "
        "NATIVE_CASES=12 PHYSICAL_EXECUTION=0"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-bounded-evidence", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.print_plan:
        print(
            "SAMPLER_FIX001_PLAN EXTERNAL_PS=0 CONTROLLED_SAMPLER=1 "
            "NATIVE_CASES=12 MUTATIONS=7 "
            "BOUNDED_E2E_WORKERS=1 LARGE_WORKERS=0 STAGEB_MEASURED=0"
        )
        return
    if None in (args.repo_root, args.runtime_root, args.evidence_root, args.durability):
        parser.error("execution paths and durability are required")
    summary = execute(args)
    print(
        "ENGINE003_STAGEB_SAMPLER_FIX001_BOUNDED_EVIDENCE_PASS "
        f"COMMIT={summary['source_commit']} NATIVE_CASES=12 "
        "MUTATIONS=7 SAMPLER=PASS "
        "BOUNDED_E2E=PASS LARGE_WORKERS=0 STAGEB_MEASURED=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
