#!/usr/bin/env python3
"""Run CAPTURE-FIX001 native capture and zero-clock resource regressions."""

from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Mapping
from unittest import mock


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REFERENCE = ENGINE / "reference"
for value in (HERE, REFERENCE):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import capture_pretiming_resources as capture_module  # noqa: E402
from capture_pretiming_resources import (  # noqa: E402
    DARWIN_PHYSICAL_MEMORY_AUTHORITY,
    ResourceCaptureError,
    capture,
    darwin_sysctlbyname_hw_memsize,
)
from fix001_contract import (  # noqa: E402
    ExecutionAuthority, FrozenAssets, StopSignal, canonical_json_bytes,
    strict_json_load, write_canonical_json,
)
from run_fix005_preflight import (  # noqa: E402
    authorization_v2_evidence, resource_hard_gate_corpus,
)
from run_fix006_preflight import (  # noqa: E402
    _activation, _result_identity, candidate_series_cadence_corpus,
)
from stage_b_authorization import (  # noqa: E402
    CAPTURE_COMMANDS, validate_runtime_resource_capture,
)
from stage_b_orchestrator import (  # noqa: E402
    execute_runtime_bound_workload, materialize_fresh_workload_plan,
)
from stage_b_runtime_contract import prelaunch_guard  # noqa: E402
import stage_b_controller as controller_module  # noqa: E402
from stage_b_controller import evaluate_resource_hard_gate  # noqa: E402
import stage_b_worker as worker_module  # noqa: E402
import run_fix005_preflight as fix005_module  # noqa: E402
import run_fix006_preflight as fix006_module  # noqa: E402


SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBCaptureFix001Summary/v1"
OLD_HELPER_SHA256 = "89da3d80038b3962ad7d05bbe0519d26cb51fa7c6bc817da8f4dc63ffd968b84"
OLD_STOPPED_AUTHORIZATION_SHA256 = (
    "62b68ed1c57684b3be89a184ff757a79ddbc090e2cad74a01d7a1a18ac2ef9e7"
)
STOPPED_EXEC001_SOURCE_COMMIT = "35fb90913b1eabe7af0adb36534c22d8aad25882"
EXPECTED_PHYSICAL_MEMORY = 38654705664
EXTERNAL_SYSCTL_RESTRICTED_STDERR = (
    "sysctl: sysctl fmt -1 1024 1: Operation not permitted"
)
ALLOWED_CHANGED_FILES = {
    "dev/ENGINE003-PREFLIGHT/ENGINE003_STAGEB_CAPTURE_FIX001_CHANGELOG.md",
    "dev/ENGINE003-PREFLIGHT/ENGINE003_STAGEB_CAPTURE_FIX001_CONTRACT.md",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_capture_fix001_preflight.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_authorization.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_capture_fix001.py",
    "dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_raw(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def run_raw(evidence: Path, label: str, argv: list[str]) -> Dict[str, Any]:
    result = subprocess.run(
        argv, check=False, capture_output=True, timeout=30,
    )
    stdout = evidence / "RAW" / f"{label}.stdout.bin"
    stderr = evidence / "RAW" / f"{label}.stderr.bin"
    write_raw(stdout, result.stdout)
    write_raw(stderr, result.stderr)
    return {
        "label": label,
        "argv": argv,
        "cwd": os.getcwd(),
        "resolved_executable": shutil.which(argv[0]),
        "operational_timeout_seconds": 30,
        "return_code": result.returncode,
        "stdout_file": str(stdout.relative_to(evidence)),
        "stderr_file": str(stderr.relative_to(evidence)),
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "stdout_sha256": sha256(result.stdout),
        "stderr_sha256": sha256(result.stderr),
    }


def source_identity(repo: Path, commit: str, tree: str, phase: str) -> Dict[str, Any]:
    def git(*argv: str) -> str:
        result = subprocess.run(
            ["git", *argv], cwd=repo, check=True,
            capture_output=True, text=True,
        )
        return result.stdout

    parent_line = git("rev-list", "--parents", "-n", "1", commit).split()
    observed = {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001SourceIdentity/v1",
        "phase": phase,
        "checkout": str(repo.resolve()),
        "head": git("rev-parse", "HEAD").strip(),
        "tree": git("rev-parse", "HEAD^{tree}").strip(),
        "branch": git("branch", "--show-current").strip(),
        "commit_object_type": git("cat-file", "-t", commit).strip(),
        "direct_parents": parent_line[1:],
        "full_status_stdout": git(
            "status", "--porcelain=v1", "--untracked-files=all",
        ),
        "protected_status_stdout": git(
            "status", "--porcelain=v1", "--untracked-files=all", "--",
            "dev/ENGINE003-PREFLIGHT",
        ),
    }
    passed = (
        observed["head"] == commit
        and observed["tree"] == tree
        and observed["branch"] == "engine003-stageb-capture-fix001"
        and observed["commit_object_type"] == "commit"
        and observed["direct_parents"] == [STOPPED_EXEC001_SOURCE_COMMIT]
        and observed["full_status_stdout"] == ""
        and observed["protected_status_stdout"] == ""
    )
    observed["status"] = (
        "PASS_EXACT_CHILD_BRANCH_FULL_AND_PROTECTED_CLEAN"
        if passed else "FAIL_SOURCE_IDENTITY"
    )
    if not passed:
        raise AssertionError(f"source identity:{phase}:{observed}")
    return observed


def _fake_sysctlbyname(
        return_code: int, observed_errno: int, returned_size: int,
        value: int, calls: list[Dict[str, Any]]):
    def function(name, old_value, old_size, new_value, new_size):
        queried = (
            bytes(name) if isinstance(name, (bytes, bytearray))
            else ctypes.cast(name, ctypes.c_char_p).value
        )
        ctypes.cast(old_size, ctypes.POINTER(ctypes.c_size_t)).contents.value = (
            returned_size
        )
        ctypes.cast(old_value, ctypes.POINTER(ctypes.c_uint64)).contents.value = value
        ctypes.set_errno(observed_errno)
        calls.append({
            "name": queried.decode("ascii") if queried else None,
            "new_value_is_null": new_value is None,
            "new_size": int(new_size),
        })
        return return_code
    return function


def _raising_sysctlbyname(calls: list[Dict[str, Any]]):
    def function(name, _old_value, _old_size, _new_value, _new_size):
        queried = (
            bytes(name) if isinstance(name, (bytes, bytearray))
            else ctypes.cast(name, ctypes.c_char_p).value
        )
        calls.append({"name": queried.decode("ascii") if queried else None})
        raise OSError("injected native call exception")
    return function


def failure_injection_corpus(
        evidence: Path, runtime: Path) -> list[Dict[str, Any]]:
    cases = [
        ("NONZERO_NATIVE_RETURN", 1, 1, 8, 123456789,
         "NONZERO_NATIVE_RETURN"),
        ("NONZERO_ERRNO_ON_SUCCESS", 0, 13, 8, 123456789,
         "NONZERO_ERRNO_ON_SUCCESS"),
        ("WRONG_RETURNED_BYTE_COUNT", 0, 0, 4, 123456789,
         "WRONG_RETURNED_BYTE_COUNT"),
        ("ZERO_PHYSICAL_MEMORY", 0, 0, 8, 0,
         "NONPOSITIVE_PHYSICAL_MEMORY"),
        ("NATIVE_CALL_EXCEPTION", None, None, None, None,
         "NATIVE_CALL_EXCEPTION"),
    ]
    rows = []
    for case_id, rc, errno_value, size, value, expected_reason in cases:
        direct_calls: list[Dict[str, Any]] = []
        direct_function = (
            _raising_sysctlbyname(direct_calls)
            if case_id == "NATIVE_CALL_EXCEPTION"
            else _fake_sysctlbyname(
                int(rc), int(errno_value), int(size), int(value), direct_calls,
            )
        )
        try:
            darwin_sysctlbyname_hw_memsize(direct_function)
        except ResourceCaptureError as error:
            if error.reason != expected_reason:
                raise AssertionError(f"wrong typed failure:{case_id}:{error}")
            direct_error = error
        else:
            raise AssertionError(f"native failure injection returned:{case_id}")

        full_calls: list[Dict[str, Any]] = []
        full_function = (
            _raising_sysctlbyname(full_calls)
            if case_id == "NATIVE_CALL_EXCEPTION"
            else _fake_sysctlbyname(
                int(rc), int(errno_value), int(size), int(value), full_calls,
            )
        )
        fallback_calls: list[list[str]] = []

        def poison_command(argv: list[str]) -> str:
            fallback_calls.append(list(argv))
            raise AssertionError(f"fallback command attempted:{argv}")

        with mock.patch.object(
                capture_module, "_load_darwin_sysctlbyname",
                return_value=full_function):
            with mock.patch.object(
                    capture_module.platform, "system", return_value="Darwin"):
                with mock.patch.object(
                        capture_module, "command", side_effect=poison_command):
                    try:
                        capture(runtime)
                    except ResourceCaptureError as error:
                        if error.reason != expected_reason:
                            raise AssertionError(
                                f"wrong full-path typed failure:{case_id}:{error}"
                            )
                        full_error = error
                    else:
                        raise AssertionError(f"full capture returned:{case_id}")
        if fallback_calls:
            raise AssertionError(f"fallback attempted:{case_id}:{fallback_calls}")
        if len(direct_calls) != 1 or len(full_calls) != 1:
            raise AssertionError(
                f"native call cardinality:{case_id}:{direct_calls}:{full_calls}"
            )
        for call in (direct_calls[0], full_calls[0]):
            if call["name"] != "hw.memsize":
                raise AssertionError(f"native query name:{case_id}:{call}")
            if case_id != "NATIVE_CALL_EXCEPTION" and (
                    call["new_value_is_null"] is not True
                    or call["new_size"] != 0):
                raise AssertionError(f"native read-only ABI:{case_id}:{call}")
        rows.append({
            "case_id": case_id,
            "injected_return_code": rc,
            "injected_errno": errno_value,
            "injected_returned_byte_count": size,
            "injected_uint64_value": value,
            "direct_exception_type": type(direct_error).__name__,
            "full_capture_exception_type": type(full_error).__name__,
            "observed_capture_stage": full_error.capture_stage,
            "observed_reason": full_error.reason,
            "queried_name": full_calls[0]["name"],
            "native_call_count": len(full_calls),
            "new_value_is_null": full_calls[0].get("new_value_is_null"),
            "new_size": full_calls[0].get("new_size"),
            "full_capture_returned_successfully": False,
            "fallback_command_call_count": len(fallback_calls),
            "fallback_attempted": bool(fallback_calls),
            "status": "PASS_FULL_CAPTURE_PATH_TYPED_FAIL_CLOSED_NO_FALLBACK",
        })
    write_canonical_json(evidence / "NATIVE_FAILURE_INJECTION_CORPUS.json", rows)
    return rows


def real_native_call_evidence(evidence: Path) -> Dict[str, Any]:
    function = capture_module._load_darwin_sysctlbyname()
    observed: Dict[str, Any] = {}

    def recording(name, old_value, old_size, new_value, new_size):
        result = int(function(name, old_value, old_size, new_value, new_size))
        observed_errno = int(ctypes.get_errno())
        queried = (
            bytes(name) if isinstance(name, (bytes, bytearray))
            else ctypes.cast(name, ctypes.c_char_p).value
        )
        observed.update({
            "queried_name": queried.decode("ascii"),
            "return_code": result,
            "errno": observed_errno,
            "returned_byte_count": int(
                ctypes.cast(
                    old_size, ctypes.POINTER(ctypes.c_size_t),
                ).contents.value
            ),
            "returned_uint64_value": int(
                ctypes.cast(
                    old_value, ctypes.POINTER(ctypes.c_uint64),
                ).contents.value
            ),
            "new_value_is_null": new_value is None,
            "new_size": int(new_size),
        })
        return result

    value = darwin_sysctlbyname_hw_memsize(recording)
    if (
        observed != {
            "queried_name": "hw.memsize",
            "return_code": 0,
            "errno": 0,
            "returned_byte_count": 8,
            "returned_uint64_value": EXPECTED_PHYSICAL_MEMORY,
            "new_value_is_null": True,
            "new_size": 0,
        }
        or value != EXPECTED_PHYSICAL_MEMORY
    ):
        raise AssertionError(f"native positive contract:{observed}:{value}")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001NativePositive/v1",
        "status": "PASS_NATIVE_SYSCTLBYNAME_HW_MEMSIZE",
        "authority": DARWIN_PHYSICAL_MEMORY_AUTHORITY,
        **observed,
        "typed_failure_not_triggered": True,
    }
    write_canonical_json(evidence / "NATIVE_POSITIVE_RAW_EVIDENCE.json", result)
    return result


def actual_fresh_cadence(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], runtime: Path,
        evidence: Path) -> Dict[str, Any]:
    activation = _activation()
    capture_calls = []

    def provider(scope: str, workload: str, candidate: str | None):
        value = capture(runtime)
        capture_calls.append({
            "scope_id": scope,
            "workload_id": workload,
            "candidate_id": candidate or "NOT_APPLICABLE",
            "physical_memory_bytes": value["physical_memory_bytes"],
            "physical_memory_authority": value["physical_memory_authority"],
            "admission_memory_ceiling_bytes": value[
                "admission_memory_ceiling_bytes"
            ],
            "capture_sha256": sha256(canonical_json_bytes(value)),
        })
        return value

    plan = materialize_fresh_workload_plan(
        authority, assets, durability, 0, runtime,
        evidence / "ACTUAL_FRESH_CADENCE", provider, activation, 0,
    )
    guard_count = 0
    logical_callback_count = 0

    def guard(request, _resource_path, resource,
              _branch_path, branch_resource):
        nonlocal guard_count
        guard_count += 1
        try:
            prelaunch_guard(
                authority, assets, request, runtime, resource,
                durability, branch_resource,
            )
        except StopSignal as signal_value:
            if signal_value.stop_id != "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
                raise
            return {"status": "PASS_RESOURCE_GATES_THEN_EXPECTED_NONAUTH_STOP"}
        raise AssertionError("CAPTURE-FIX001 unexpectedly authorized Stage-B")

    def logical_callback(request, _index, _resource_path, _branch_path):
        nonlocal logical_callback_count
        logical_callback_count += 1
        return _result_identity(request)

    execution = execute_runtime_bound_workload(
        authority, assets, durability, plan,
        evidence / "ACTUAL_FRESH_CADENCE", provider,
        plan["next_capture_ordinal"], activation, guard, logical_callback,
    )
    expected_capture_count = 1 + len(plan["allowed_candidate_ids"])
    if (
        len(capture_calls) != expected_capture_count
        or plan["compact_admission_result"] != "PASS"
        or guard_count != plan["request_count"]
        or logical_callback_count != plan["request_count"]
        or execution["candidate_series_capture_count"]
        != len(plan["allowed_candidate_ids"])
    ):
        raise AssertionError("actual fresh cadence boundary")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ActualCadence/v1",
        "status": "PASS_ACTUAL_NATIVE_FRESH_BRANCH_AND_CANDIDATE_SERIES",
        "workload_id": plan["workload_id"],
        "compact_admission_result": plan["compact_admission_result"],
        "workload_branch_capture_count": 1,
        "candidate_series_capture_count": execution[
            "candidate_series_capture_count"
        ],
        "resource_prelaunch_guard_count": guard_count,
        "in_process_logical_callback_count": logical_callback_count,
        "physical_worker_launch_count": 0,
        "stage_b_measured_clock_count": 0,
        "candidate_store_count": 0,
        "physical_allocation_count": 0,
        "capture_rows": capture_calls,
    }
    write_canonical_json(evidence / "ACTUAL_FRESH_CAPTURE_CADENCE.json", result)
    return result


def resource_hard_gate_positive(evidence: Path) -> Dict[str, Any]:
    """Exercise the measured-resource PASS boundary without a worker or clock."""
    request = {
        "memory_admission_required_bytes": 1024,
        "disk_admission_required_bytes": 2048,
        "publication_high_water_bound_bytes": 2048,
    }
    measured = {
        "operation_integer_values": {
            "peak_rss": 512,
            "temporary_physical_disk": 1024,
            "final_physical_disk": 1024,
            "publication_high_water": 1024,
        },
        "integer_metrics": {"peak_rss_repetitions": 512},
        "operation_status": {"peak_rss": "MEASURED_INTEGER_BYTES"},
    }
    process_tree_peak = 768
    gate = evaluate_resource_hard_gate(request, measured, process_tree_peak)
    if (
        gate["status"] != "PASS"
        or gate["violations"]
        or gate["authoritative_peak_rss_bytes"] != process_tree_peak
    ):
        raise AssertionError(f"synthetic measured-resource hard-gate PASS:{gate}")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ResourceHardGate/v1",
        "status": "PASS_SYNTHETIC_MEASURED_VALUES_WITHIN_ADMISSION",
        "evidence_kind": "SYNTHETIC_CONTROL_PLANE_VALUES_NO_WORKER_NO_CLOCK",
        "request": request,
        "measured_result": measured,
        "process_tree_peak_rss_bytes": process_tree_peak,
        "gate_result": gate,
        "physical_worker_launch_count": 0,
        "stage_b_measured_clock_count": 0,
    }
    write_canonical_json(evidence / "RESOURCE_HARD_GATE_POSITIVE.json", result)
    return result


def changed_file_proof(
        repo: Path, parent: str, commit: str, evidence: Path) -> Dict[str, Any]:
    ancestry = subprocess.check_output(
        ["git", "rev-list", "--parents", "-n", "1", commit],
        cwd=repo, text=True,
    ).split()
    if ancestry != [commit, STOPPED_EXEC001_SOURCE_COMMIT]:
        raise AssertionError(f"ordinary-child ancestry:{ancestry}")
    if parent != STOPPED_EXEC001_SOURCE_COMMIT:
        raise AssertionError(f"caller parent differs from stopped source:{parent}")
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r",
         parent, commit],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    changed = [line for line in result.stdout.splitlines() if line]
    if set(changed) != ALLOWED_CHANGED_FILES:
        raise AssertionError(f"changed-file scope:{changed}")
    core = []
    for path in sorted(
            value for value in subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", parent,
                 "dev/ENGINE003-PREFLIGHT/exec_preflight"],
                cwd=repo, text=True,
            ).splitlines() if value not in ALLOWED_CHANGED_FILES):
        before = subprocess.check_output(
            ["git", "rev-parse", f"{parent}:{path}"], cwd=repo, text=True,
        ).strip()
        after = subprocess.check_output(
            ["git", "rev-parse", f"{commit}:{path}"], cwd=repo, text=True,
        ).strip()
        if before != after:
            raise AssertionError(f"non-resource core changed:{path}")
        core.append({"path": path, "parent_blob": before, "child_blob": after})
    proof = {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ScopeProof/v1",
        "status": "PASS_NARROW_CHANGED_FILES_AND_NONRESOURCE_CORE_IDENTICAL",
        "parent": parent,
        "child": commit,
        "actual_parent_vector": ancestry[1:],
        "ordinary_single_parent_child": True,
        "changed_files": changed,
        "changed_file_count": len(changed),
        "production_R_changed": False,
        "production_src_changed": False,
        "scientific_authority_changed": False,
        "nonresource_exec_preflight_blob_count": len(core),
        "nonresource_exec_preflight_all_byte_identical": True,
        "nonresource_exec_preflight_blobs": core,
    }
    write_canonical_json(evidence / "CHANGED_FILE_AND_CORE_IDENTITY_PROOF.json", proof)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--durability", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--parent", required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    if (
        args.runtime_root.is_symlink()
        or args.evidence_dir.is_symlink()
        or not args.runtime_root.is_dir()
        or not args.evidence_dir.is_dir()
    ):
        raise AssertionError("CAPTURE-FIX001 roots must be existing nonsymlink directories")
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    if (
        evidence == runtime
        or evidence in runtime.parents
        or runtime in evidence.parents
    ):
        raise AssertionError("CAPTURE-FIX001 roots must be distinct and nonnested")
    if args.parent != STOPPED_EXEC001_SOURCE_COMMIT:
        raise AssertionError("CAPTURE-FIX001 must be an ordinary child of stopped EXEC001")
    if any(runtime.iterdir()) or any(evidence.iterdir()):
        raise AssertionError("CAPTURE-FIX001 roots must start empty")
    stopped = {
        Path("/Users/jiaqiwu/Documents/Codex/2026-07-24/zhe/ENGINE003_STAGEB_EXEC001_RUNTIME_35fb909").resolve(),
        Path("/Users/jiaqiwu/Documents/Codex/2026-07-24/zhe/ENGINE003_STAGEB_EXEC001_EVIDENCE_35fb909").resolve(),
    }
    if any(
            path == root or root in path.parents
            for path in (runtime, evidence) for root in stopped):
        raise AssertionError("stopped EXEC001 root reuse")
    durability_path = args.durability.resolve(strict=True)
    if (
        args.durability.is_symlink()
        or not durability_path.is_file()
        or any(durability_path == root or root in durability_path.parents
               for root in stopped)
    ):
        raise AssertionError("durability input must be a regular source outside stopped roots")

    pre = source_identity(repo, args.commit, args.tree, "PRE_CAPTURE_FIX001")
    write_canonical_json(evidence / "PRE_SOURCE_IDENTITY.json", pre)
    authority = ExecutionAuthority(repo, args.commit, args.tree)
    assets = FrozenAssets(authority)
    durability_raw = durability_path.read_bytes()
    durability = strict_json_load(durability_path)
    durability_canonical = canonical_json_bytes(durability)
    if durability_raw != durability_canonical:
        raise AssertionError("durability input must be exact canonical JSON")
    durability_copy = evidence / "INPUTS" / "DURABILITY_CAPABILITY.canonical.json"
    write_raw(durability_copy, durability_raw)
    durability_sha = sha256(durability_raw)
    write_canonical_json(evidence / "DURABILITY_INPUT_BINDING.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001DurabilityInput/v1",
        "status": "PASS_EXACT_CANONICAL_INPUT_PRESERVED",
        "source_path": str(durability_path),
        "source_is_outside_stopped_exec001_roots": True,
        "copied_evidence_path": str(durability_copy.relative_to(evidence)),
        "source_sha256": durability_sha,
        "copied_sha256": sha256(durability_copy.read_bytes()),
        "byte_identical": durability_copy.read_bytes() == durability_raw,
    })

    native_positive = real_native_call_evidence(evidence)
    external_rows = [
        run_raw(evidence, "sysctl_unqualified", ["sysctl", "-n", "hw.memsize"]),
        run_raw(evidence, "sysctl_absolute", ["/usr/sbin/sysctl", "-n", "hw.memsize"]),
    ]
    for row in external_rows:
        stdout = (evidence / row["stdout_file"]).read_bytes()
        stderr = (evidence / row["stderr_file"]).read_bytes()
        if (
            row["return_code"] != 1
            or stdout != b""
            or stderr.decode("utf-8").strip()
            != EXTERNAL_SYSCTL_RESTRICTED_STDERR
        ):
            raise AssertionError(f"external sysctl classification changed:{row}")
    write_canonical_json(evidence / "EXTERNAL_SYSCTL_RESTRICTED_RAW.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ExternalSysctl/v1",
        "status": "PASS_EXTERNAL_COMMAND_FAILURE_PRESERVED_DIAGNOSTIC_ONLY",
        "rows": external_rows,
        "authorization_critical_dependency": False,
    })
    failures = failure_injection_corpus(evidence, runtime)
    fresh = capture(runtime)
    if (
        fresh["physical_memory_bytes"] != EXPECTED_PHYSICAL_MEMORY
        or fresh["physical_memory_authority"]
        != DARWIN_PHYSICAL_MEMORY_AUTHORITY
        or fresh["admission_memory_ceiling_bytes"]
        != EXPECTED_PHYSICAL_MEMORY // 2
        or fresh["capture_commands"] != CAPTURE_COMMANDS
    ):
        raise AssertionError("fresh native resource capture")
    write_canonical_json(evidence / "FRESH_NATIVE_RESOURCE_CAPTURE.json", fresh)
    native_positive_raw = canonical_json_bytes(native_positive)
    fresh_raw = canonical_json_bytes(fresh)
    write_canonical_json(evidence / "NATIVE_POSITIVE_TO_FRESH_CAPTURE_BINDING.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001NativeFreshBinding/v1",
        "status": "PASS_SAME_AUTHORITY_AND_VALUE_BOUND",
        "native_positive_sha256": sha256(native_positive_raw),
        "fresh_capture_sha256": sha256(fresh_raw),
        "native_authority": native_positive["authority"],
        "fresh_authority": fresh["physical_memory_authority"],
        "native_value": native_positive["returned_uint64_value"],
        "fresh_value": fresh["physical_memory_bytes"],
        "exact_authority_and_value_equal": (
            native_positive["authority"] == fresh["physical_memory_authority"]
            and native_positive["returned_uint64_value"]
            == fresh["physical_memory_bytes"]
        ),
    })
    validate_runtime_resource_capture({
        "host_profile": {key: fresh[key] for key in (
            "host_id", "platform_system", "platform_release",
            "platform_machine", "os_build", "filesystem",
            "destination_device_id", "target_volume_device",
            "target_volume_mount_point",
        )},
        "resource_admission_policy": copy.deepcopy(
            __import__("stage_b_authorization").RESOURCE_ADMISSION_POLICY
        ),
    }, fresh)

    pressure_row = run_raw(
        evidence, "memory_pressure_consistency", ["/usr/bin/memory_pressure", "-Q"],
    )
    pressure_stdout = (evidence / pressure_row["stdout_file"]).read_text()
    total_match = re.search(r"The system has (\d+)", pressure_stdout)
    if pressure_row["return_code"] or not total_match:
        raise AssertionError("memory_pressure total unavailable")
    pressure_total = int(total_match.group(1))
    if pressure_total != fresh["physical_memory_bytes"]:
        raise AssertionError("native/memory_pressure total mismatch")
    write_canonical_json(evidence / "CROSS_EVIDENCE_CONSISTENCY.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001CrossEvidence/v1",
        "status": "PASS_DIAGNOSTIC_TOTAL_CONSISTENCY",
        "authoritative_source": DARWIN_PHYSICAL_MEMORY_AUTHORITY,
        "native_physical_memory_bytes": fresh["physical_memory_bytes"],
        "memory_pressure_reported_total_bytes": pressure_total,
        "memory_pressure_is_alternate_authority": False,
        "raw_command": pressure_row,
    })

    forbidden_execution_events: list[str] = []

    def trip_forbidden(label: str):
        def call(*_args, **_kwargs):
            forbidden_execution_events.append(label)
            raise AssertionError(f"prohibited CAPTURE-FIX001 call:{label}")
        return call

    canary_targets = [
        (controller_module, "launch_request", "stage_b_controller.launch_request"),
        (fix005_module, "launch_request", "run_fix005_preflight.launch_request"),
        (fix006_module, "launch_request", "run_fix006_preflight.launch_request"),
        (worker_module, "execute_live", "stage_b_worker.execute_live"),
        (worker_module.time, "perf_counter_ns", "time.perf_counter_ns"),
    ]
    with ExitStack() as stack:
        for module, attribute, label in canary_targets:
            stack.enter_context(mock.patch.object(
                module, attribute, side_effect=trip_forbidden(label),
            ))
        actual = actual_fresh_cadence(
            authority, assets, durability, runtime, evidence,
        )
        p16 = candidate_series_cadence_corpus(
            authority, assets, fresh, durability, runtime, evidence,
        )
        hard_gate_rows = resource_hard_gate_corpus(evidence)
        hard_gate_positive = resource_hard_gate_positive(evidence)
        auth = authorization_v2_evidence(
            authority, assets, fresh, durability, runtime, evidence,
        )
    if forbidden_execution_events:
        raise AssertionError(f"prohibited execution event:{forbidden_execution_events}")
    write_canonical_json(evidence / "FORBIDDEN_EXECUTION_CANARY.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ForbiddenCanary/v1",
        "status": "PASS_NO_PHYSICAL_WORKER_OR_STAGEB_MEASURED_CLOCK",
        "patched_entrypoints": [row[2] for row in canary_targets],
        "observed_forbidden_event_count": len(forbidden_execution_events),
        "observed_forbidden_events": forbidden_execution_events,
        "logical_schedule_callbacks_are_not_physical_workers": True,
    })
    p16_capture_files = sorted(
        list(evidence.glob("P16_RUN_*/FRESH_RESOURCE_CAPTURES/*.json"))
        + list(evidence.glob("P16_STOP_RUN/FRESH_RESOURCE_CAPTURES/*.json"))
    )
    if not p16_capture_files or not all(
            strict_json_load(path).get("fix005_bounded_resource_injection") is True
            for path in p16_capture_files):
        raise AssertionError("P16 synthetic resource evidence marker")
    write_canonical_json(evidence / "P16_SYNTHETIC_RESOURCE_BOUNDARY.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001P16Synthetic/v1",
        "status": "PASS_SYNTHETIC_BOUNDED_INJECTION_EXPLICIT",
        "synthetic_capture_file_count": len(p16_capture_files),
        "all_carry_fix005_bounded_resource_injection_marker": True,
        "live_fresh_capture_carries_injection_marker": (
            "fix005_bounded_resource_injection" in fresh
        ),
        "synthetic_resources_are_native_capture_evidence": False,
    })
    if "fix005_bounded_resource_injection" in fresh:
        raise AssertionError("live fresh capture mislabeled as synthetic")
    artifact = strict_json_load(evidence / "P14_AUTHORIZATION_V2_EXAMPLE.json")
    artifact_file_sha = sha256(
        (evidence / "P14_AUTHORIZATION_V2_EXAMPLE.json").read_bytes()
    )
    helper_raw = subprocess.check_output(
        ["git", "show", f"{args.commit}:dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py"],
        cwd=repo,
    )
    helper_sha = sha256(helper_raw)
    if (
        artifact["resource_capture_procedure_sha256"] != helper_sha
        or artifact["durability_capability_evidence_id"] != durability_sha
        or artifact_file_sha != auth["authorization_sha256"]
        or artifact_file_sha == OLD_STOPPED_AUTHORIZATION_SHA256
        or helper_sha == OLD_HELPER_SHA256
        or artifact["state"] != "NOT_AUTHORIZED_PREFLIGHT_ARTIFACT"
        or artifact["physical_allocation_authorized"] is not False
    ):
        raise AssertionError("authorization-v2 new procedure binding")
    write_canonical_json(evidence / "NEW_CAPTURE_PROCEDURE_BINDING.json", {
        "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ProcedureBinding/v1",
        "status": "PASS_AUTHORIZATION_V2_BINDS_NEW_CAPTURE_PROCEDURE",
        "old_historical_helper_sha256": OLD_HELPER_SHA256,
        "new_capture_helper_sha256": helper_sha,
        "artifact_resource_capture_procedure_sha256": artifact[
            "resource_capture_procedure_sha256"
        ],
        "old_historical_hash_differs_from_new_bound_hash": (
            OLD_HELPER_SHA256 != helper_sha
        ),
        "artifact_state": artifact["state"],
        "physical_allocation_authorized": artifact[
            "physical_allocation_authorized"
        ],
        "old_stopped_authorization_sha256": (
            OLD_STOPPED_AUTHORIZATION_SHA256
        ),
        "candidate_authorization_sha256": auth["authorization_sha256"],
        "candidate_authorization_file_sha256": artifact_file_sha,
        "candidate_authorization_differs_from_stopped_authorization": (
            artifact_file_sha != OLD_STOPPED_AUTHORIZATION_SHA256
        ),
        "old_authorization_reused": False,
        "durability_capability_evidence_id": artifact[
            "durability_capability_evidence_id"
        ],
        "runtime_authorization_created": False,
    })
    scope = changed_file_proof(
        repo, args.parent, args.commit, evidence,
    )
    if any(runtime.iterdir()):
        raise AssertionError("CAPTURE-FIX001 runtime root not empty")
    post = source_identity(repo, args.commit, args.tree, "POST_CAPTURE_FIX001")
    write_canonical_json(evidence / "POST_SOURCE_IDENTITY.json", post)
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_CAPTURE_FIX001_NO_CLOCK_RESOURCE_PREFLIGHT",
        "source_commit": args.commit,
        "source_tree": args.tree,
        "direct_parent": args.parent,
        "capture_helper_sha256": helper_sha,
        "durability_input_sha256": durability_sha,
        "old_stopped_authorization_sha256": (
            OLD_STOPPED_AUTHORIZATION_SHA256
        ),
        "candidate_authorization_sha256": artifact_file_sha,
        "old_authorization_reused": False,
        "physical_memory_authority": DARWIN_PHYSICAL_MEMORY_AUTHORITY,
        "native_positive_status": native_positive["status"],
        "external_sysctl_return_codes": [
            row["return_code"] for row in external_rows
        ],
        "external_sysctl_is_authorization_critical": False,
        "external_sysctl_evidence_sha256": sha256(canonical_json_bytes({
            "schema": "SplitAlignerR/ENGINE003StageBCaptureFix001ExternalSysctl/v1",
            "status": "PASS_EXTERNAL_COMMAND_FAILURE_PRESERVED_DIAGNOSTIC_ONLY",
            "rows": external_rows,
            "authorization_critical_dependency": False,
        })),
        "failure_injection_case_count": len(failures),
        "full_capture_fail_closed_case_count": len(failures),
        "fallback_command_call_count": sum(
            row["fallback_command_call_count"] for row in failures
        ),
        "native_positive_sha256": sha256(native_positive_raw),
        "fresh_native_capture_sha256": sha256(fresh_raw),
        "fresh_physical_memory_bytes": fresh["physical_memory_bytes"],
        "fresh_admission_memory_ceiling_bytes": fresh[
            "admission_memory_ceiling_bytes"
        ],
        "actual_fresh_branch_capture_count": actual[
            "workload_branch_capture_count"
        ],
        "actual_fresh_candidate_series_capture_count": actual[
            "candidate_series_capture_count"
        ],
        "resource_change_stop_status": p16["status"],
        "resource_change_stop_evidence_kind": "SYNTHETIC_BOUNDED_INJECTION",
        "measured_resource_hard_gate_stop_case_count": len(hard_gate_rows),
        "measured_resource_hard_gate_pass_case_count": 1,
        "measured_resource_hard_gate_total_case_count": (
            len(hard_gate_rows) + 1
        ),
        "measured_resource_hard_gate_positive_status": hard_gate_positive[
            "status"
        ],
        "authorization_v2_binding_status": auth["status"],
        "changed_file_count": scope["changed_file_count"],
        "stage_b_physical_worker_count": 0,
        "stage_b_measured_clock_count": 0,
        "forbidden_execution_canary_event_count": len(
            forbidden_execution_events
        ),
        "candidate_store_count": 0,
        "mandatory_large_allocation_count": 0,
        "over2gib_or_over4gib_candidate_count": 0,
        "backend_selected": False,
        "authorized_to_run_artifact_created": False,
        "stopped_exec001_root_reused": False,
        "runtime_root_empty_after_regression": True,
        "source_pre_post_exact_clean": True,
    }
    write_canonical_json(evidence / "CAPTURE_FIX001_SUMMARY.json", summary)
    print(
        "ENGINE003_STAGEB_CAPTURE_FIX001_PASS "
        f"NATIVE={fresh['physical_memory_bytes']} FAILURES={len(failures)} "
        "WORKERS=0 CLOCK=0 LARGE_ALLOCATIONS=0"
    )


if __name__ == "__main__":
    main()
