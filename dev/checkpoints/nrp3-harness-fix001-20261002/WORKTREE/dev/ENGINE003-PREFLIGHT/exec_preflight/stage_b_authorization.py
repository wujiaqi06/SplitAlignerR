#!/usr/bin/env python3
"""Cryptographic external authorization boundary for Stage-B execution.

The artifact is deliberately external to the execution source tree.  Its exact
canonical bytes, not a caller supplied digest string, authorize a frozen set of
workload/schedule/candidate tuples on one exact host and execution root.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping

from fix001_contract import (
    ALL_CANDIDATES,
    FROZEN_PREREG_COMMIT,
    FROZEN_PREREG_TREE,
    WORKLOADS,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_loads,
)


AUTHORIZATION_SCHEMA = "SplitAlignerR/ENGINE003StageBExecAuthorization/v2"
AUTHORIZATION_SCOPE = "ENGINE003-STAGEB-EXEC001"
STOP_POLICY = "GLOBAL_STOP_ON_FIRST_NON_PASS_NO_LATER_LARGER_WORKLOAD"
CAPTURE_PROCEDURE_PATH = (
    "dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py"
)
DARWIN_PHYSICAL_MEMORY_AUTHORITY = "DARWIN_SYSCTLBYNAME_HW_MEMSIZE_V1"
RESOURCE_ADMISSION_POLICY = {
    "memory_ceiling_arithmetic": "physical_memory_bytes//2",
    "candidate_memory_rule": "fresh_ceiling>=memory_admission_required_bytes",
    "file_disk_rule": "fresh_disk>=disk_admission_required_bytes",
    "workload_branch_cadence": "IMMEDIATELY_BEFORE_EACH_WORKLOAD_BRANCH_SELECTION",
    "candidate_series_cadence": "IMMEDIATELY_BEFORE_EACH_CANDIDATE_WORKLOAD_SERIES",
    "capture_preservation": "CANONICAL_BYTES_SHA256_AND_REQUEST_BINDING",
}
CAPTURE_COMMANDS = [
    DARWIN_PHYSICAL_MEMORY_AUTHORITY, "memory_pressure -Q", "shutil.disk_usage",
    "os.statvfs", "sw_vers", "platform", "socket.gethostname",
    "df -Pk", "mount", "os.stat(destination).st_dev",
]
RUNTIME_RESOURCE_CAPTURE_FIELDS = {
    "status", "capture_time", "host_id", "platform_system",
    "platform_release", "platform_machine", "os_build", "filesystem",
    "destination", "destination_device_id", "target_volume_device",
    "target_volume_mount_point", "target_volume_mount_entry",
    "target_volume_df_pk", "physical_memory_bytes",
    "physical_memory_authority", "observed_memory_free_percent",
    "observed_available_memory_bytes",
    "observed_available_memory_proxy_bytes",
    "observed_available_memory_proxy_basis",
    "admission_memory_ceiling_policy", "admission_memory_ceiling_bytes",
    "available_local_disk_bytes", "disk_total_bytes", "disk_used_bytes",
    "allocation_unit_bytes", "capture_commands", "timing_executed",
    "backend_allocation_executed",
}
MAX_RUNTIME_RESOURCE_CAPTURE_BYTES = 1024 * 1024

AUTHORIZATION_FIELDS = {
    "schema", "authorization_id", "authorization_scope", "state",
    "physical_allocation_authorized", "authorized_execution_commit",
    "authorized_execution_tree", "frozen_prereg_commit",
    "frozen_prereg_tree", "host_profile", "allowed_workload_ids",
    "allowed_candidate_ids", "workload_authorizations",
    "candidate_set_sha256", "schedule_selection_sha256",
    "execution_schedule_sha256", "warmup_schedule_sha256",
    "timeout_contract_sha256", "metric_contract_sha256",
    "resource_capture_procedure_sha256", "resource_admission_policy",
    "durability_capability_evidence_id",
    "stop_policy", "evidence_root", "execution_root",
}

WORKLOAD_AUTHORIZATION_FIELDS = {
    "workload_id", "compact_memory_required_bytes", "admission_branches",
}
BRANCH_AUTHORIZATION_FIELDS = {
    "compact_admission_result", "selected_schedule_id",
    "expected_measured_repetitions", "allowed_candidate_ids",
    "warmup_candidate_ids", "measured_launch_tuple_sha256",
    "warmup_launch_tuple_sha256",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _resource_file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns,
    )


def load_exact_runtime_resource_capture(
        path: Path, expected_sha256: Any) -> tuple[Dict[str, Any], bytes]:
    """Load one exact canonical runtime capture without following a file link."""
    if not _valid_sha(expected_sha256):
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "expected_sha256")
    try:
        before = os.lstat(path)
    except OSError as error:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "unreadable") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "not_regular_nonsymlink")
    if before.st_size > MAX_RUNTIME_RESOURCE_CAPTURE_BYTES:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "file_size_ceiling")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "open_failed") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _resource_file_identity(opened) != _resource_file_identity(before)
        ):
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "open_identity_changed")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RUNTIME_RESOURCE_CAPTURE_BYTES:
                raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "read_size_ceiling")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _resource_file_identity(after) != _resource_file_identity(opened):
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "read_identity_changed")
        try:
            path_after = os.lstat(path)
        except OSError as error:
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "path_changed") from error
        if (
            stat.S_ISLNK(path_after.st_mode)
            or not stat.S_ISREG(path_after.st_mode)
            or _resource_file_identity(path_after) != _resource_file_identity(opened)
        ):
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "path_changed")
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if _sha256(raw) != expected_sha256:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "exact_bytes_sha256")
    try:
        value = strict_json_loads(raw)
    except Exception as error:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "strict_json") from error
    if not isinstance(value, dict) or set(value) != RUNTIME_RESOURCE_CAPTURE_FIELDS:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "field_set")
    if raw != canonical_json_bytes(value):
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "noncanonical_bytes")
    return value, raw


def _tuple_digest(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> str:
    payload = [{key: row[key] for key in keys} for row in rows]
    return _sha256(canonical_json_bytes(payload))


def _branch_authorization(
        assets: FrozenAssets, workload: str, admission: str) -> Dict[str, Any]:
    selection = assets.schedule_selection.get((workload, admission))
    if selection is None:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "authorization_selection")
    schedule_id = selection["selected_schedule_id"]
    measured = assets.schedule_rows(workload, schedule_id)
    warmups = assets.warmup_rows(workload, admission)
    expected_repetitions = int(selection["expected_measured_repetitions"])
    allowed = list(ALL_CANDIDATES if admission == "PASS" else ALL_CANDIDATES[1:])
    if len(measured) != expected_repetitions * len(allowed):
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "authorization_cardinality")
    return {
        "compact_admission_result": admission,
        "selected_schedule_id": schedule_id,
        "expected_measured_repetitions": expected_repetitions,
        "allowed_candidate_ids": allowed,
        "warmup_candidate_ids": [row["backend"] for row in warmups],
        "measured_launch_tuple_sha256": _tuple_digest(
            measured,
            ("measured_repetition", "position", "backend", "fresh_process", "fresh_target"),
        ),
        "warmup_launch_tuple_sha256": _tuple_digest(
            warmups,
            ("warmup_position", "backend", "fresh_process", "fresh_target", "measured"),
        ),
    }


def workload_authorization(
        assets: FrozenAssets, workload: str) -> Dict[str, Any]:
    """Authorize both frozen branches without selecting either one early."""
    return {
        "workload_id": workload,
        "compact_memory_required_bytes": int(
            assets.projections[(workload, "COMPACT_IN_MEMORY")][
                "memory_admission_required_bytes"
            ]
        ),
        "admission_branches": {
            admission: _branch_authorization(assets, workload, admission)
            for admission in ("PASS", "FAIL")
        },
    }


def _execution_object_sha256(assets: FrozenAssets, relative: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(assets.authority.repo_root), "show",
         f"{assets.authority.commit}:{relative}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise StopSignal(
            "SB_STOP_AUTHORIZATION_OBJECT", f"execution_object:{relative}",
        )
    return _sha256(process.stdout)


def validate_runtime_resource_capture(
        artifact: Mapping[str, Any], resource: Mapping[str, Any]) -> None:
    """Validate a not-yet-known capture under the frozen authorization policy."""
    if set(resource) != RUNTIME_RESOURCE_CAPTURE_FIELDS:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "field_set")
    if (
        resource["status"] != "FRESH_PRETIMING_RESOURCE_CAPTURE_PASS"
        or not isinstance(resource["capture_time"], str)
        or not resource["capture_time"]
        or resource["platform_system"] != "Darwin"
        or resource["admission_memory_ceiling_policy"]
        != "50_PERCENT_OF_PHYSICAL_MEMORY"
        or type(resource["physical_memory_bytes"]) is not int
        or resource["physical_memory_authority"]
        != DARWIN_PHYSICAL_MEMORY_AUTHORITY
        or resource["physical_memory_bytes"] <= 0
        or type(resource["admission_memory_ceiling_bytes"]) is not int
        or resource["admission_memory_ceiling_bytes"]
        != resource["physical_memory_bytes"] // 2
        or type(resource["available_local_disk_bytes"]) is not int
        or resource["available_local_disk_bytes"] < 0
        or resource["capture_commands"] != CAPTURE_COMMANDS
        or resource["timing_executed"] is not False
        or resource["backend_allocation_executed"] is not False
    ):
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "capture_policy")
    observed_host = {
        key: resource[key] for key in (
            "host_id", "platform_system", "platform_release",
            "platform_machine", "os_build", "filesystem",
            "destination_device_id", "target_volume_device",
            "target_volume_mount_point",
        )
    }
    if observed_host != artifact["host_profile"]:
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "authorized_host_volume")
    if artifact["resource_admission_policy"] != RESOURCE_ADMISSION_POLICY:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "resource_policy")


def make_authorization_artifact(
        assets: FrozenAssets, execution_commit: str, execution_tree: str,
        host_profile: Mapping[str, Any],
        durability_evidence_id: str, evidence_root: Path, execution_root: Path,
        authorization_id: str,
        physical_allocation_authorized: bool = False) -> Dict[str, Any]:
    """Build a trust root for future captures, never a stale branch choice."""
    if not authorization_id:
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "authorization_id")
    rows = [workload_authorization(assets, workload) for workload in WORKLOADS]
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "authorization_id": authorization_id,
        "authorization_scope": AUTHORIZATION_SCOPE,
        "state": (
            "AUTHORIZED_TO_RUN" if physical_allocation_authorized
            else "NOT_AUTHORIZED_PREFLIGHT_ARTIFACT"
        ),
        "physical_allocation_authorized": physical_allocation_authorized,
        "authorized_execution_commit": execution_commit,
        "authorized_execution_tree": execution_tree,
        "frozen_prereg_commit": FROZEN_PREREG_COMMIT,
        "frozen_prereg_tree": FROZEN_PREREG_TREE,
        "host_profile": dict(host_profile),
        "allowed_workload_ids": list(WORKLOADS),
        "allowed_candidate_ids": list(ALL_CANDIDATES),
        "workload_authorizations": rows,
        "candidate_set_sha256": _sha256(assets.raw["candidate_set"]),
        "schedule_selection_sha256": _sha256(assets.raw["schedule_selection"]),
        "execution_schedule_sha256": _sha256(assets.raw["execution_schedule"]),
        "warmup_schedule_sha256": _sha256(assets.raw["warmup_schedule"]),
        "timeout_contract_sha256": _sha256(assets.raw["timeout_contract"]),
        "metric_contract_sha256": _sha256(assets.raw["metric_contract"]),
        "resource_capture_procedure_sha256": _execution_object_sha256(
            assets, CAPTURE_PROCEDURE_PATH,
        ),
        "resource_admission_policy": dict(RESOURCE_ADMISSION_POLICY),
        "durability_capability_evidence_id": durability_evidence_id,
        "stop_policy": STOP_POLICY,
        "evidence_root": str(evidence_root.resolve()),
        "execution_root": str(execution_root.resolve()),
    }


def load_exact_authorization(path: Path, expected_sha256: str) -> tuple[Dict[str, Any], bytes]:
    """Read one nonsymlink regular file and bind its exact canonical bytes."""
    try:
        observed = os.lstat(path)
    except OSError as error:
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "unreadable") from error
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "not_regular_nonsymlink")
    raw = path.read_bytes()
    if not _valid_sha(expected_sha256) or _sha256(raw) != expected_sha256:
        raise StopSignal("SB_STOP_AUTHORIZATION_HASH", "exact_bytes_sha256")
    try:
        value = strict_json_loads(raw)
    except Exception as error:
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "strict_json") from error
    if not isinstance(value, dict) or set(value) != AUTHORIZATION_FIELDS:
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "field_set")
    if raw != canonical_json_bytes(value):
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "noncanonical_bytes")
    return value, raw


def validate_authorization_for_request(
        assets: FrozenAssets, request: Mapping[str, Any], runtime_root: Path,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        branch_resource: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Validate the external object against every live launch dimension."""
    activation = request["activation"]
    path = Path(activation["authorization_artifact_path"])
    artifact, raw = load_exact_authorization(
        path, activation["authorization_sha256"],
    )
    if (
        activation["authorization_id"] != artifact["authorization_id"]
        or artifact["schema"] != AUTHORIZATION_SCHEMA
        or artifact["authorization_scope"] != AUTHORIZATION_SCOPE
        or artifact["state"] != "AUTHORIZED_TO_RUN"
        or artifact["physical_allocation_authorized"] is not True
        or activation["physical_allocation_authorized"] is not True
    ):
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "state_id_scope")
    exact = {
        "authorized_execution_commit": request["source_commit"],
        "authorized_execution_tree": request["source_tree"],
        "frozen_prereg_commit": FROZEN_PREREG_COMMIT,
        "frozen_prereg_tree": FROZEN_PREREG_TREE,
        "host_profile": request["host_profile"],
        "allowed_workload_ids": list(WORKLOADS),
        "allowed_candidate_ids": list(ALL_CANDIDATES),
        "candidate_set_sha256": _sha256(assets.raw["candidate_set"]),
        "schedule_selection_sha256": _sha256(assets.raw["schedule_selection"]),
        "execution_schedule_sha256": _sha256(assets.raw["execution_schedule"]),
        "warmup_schedule_sha256": _sha256(assets.raw["warmup_schedule"]),
        "timeout_contract_sha256": _sha256(assets.raw["timeout_contract"]),
        "metric_contract_sha256": _sha256(assets.raw["metric_contract"]),
        "resource_capture_procedure_sha256": _execution_object_sha256(
            assets, CAPTURE_PROCEDURE_PATH,
        ),
        "resource_admission_policy": RESOURCE_ADMISSION_POLICY,
        "durability_capability_evidence_id": _sha256(
            canonical_json_bytes(dict(durability))
        ),
        "stop_policy": STOP_POLICY,
        "evidence_root": request["evidence_root"],
        "execution_root": str(runtime_root.resolve()),
    }
    for field, expected in exact.items():
        if artifact[field] != expected:
            raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", field)
    validate_runtime_resource_capture(artifact, resource)
    selected_branch_resource = (
        branch_resource if branch_resource is not None else resource
    )
    validate_runtime_resource_capture(artifact, selected_branch_resource)
    for capture in (resource, selected_branch_resource):
        if str(Path(capture["destination"]).resolve()) != str(runtime_root.resolve()):
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "execution_destination")
    if artifact["evidence_root"] != str(Path(artifact["evidence_root"]).resolve()):
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "evidence_root_canonical")
    if artifact["execution_root"] != str(runtime_root.resolve()):
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "execution_root")
    workload_rows = artifact["workload_authorizations"]
    if not isinstance(workload_rows, list) or len(workload_rows) != len(WORKLOADS):
        raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "workload_authorizations")
    by_workload: Dict[str, Mapping[str, Any]] = {}
    for row in workload_rows:
        if not isinstance(row, dict) or set(row) != WORKLOAD_AUTHORIZATION_FIELDS:
            raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "workload_field_set")
        workload = row["workload_id"]
        if workload in by_workload:
            raise StopSignal("SB_STOP_AUTHORIZATION_OBJECT", "duplicate_workload")
        by_workload[workload] = row
    if tuple(by_workload) != WORKLOADS:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "workload_order")
    workload = request["workload_id"]
    expected_row = workload_authorization(assets, workload)
    if by_workload[workload] != expected_row:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "workload_policy")
    admission = request["compact_admission_result"]
    branch = expected_row["admission_branches"].get(admission)
    if not isinstance(branch, dict) or set(branch) != BRANCH_AUTHORIZATION_FIELDS:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "admission_branch")
    if request["candidate_id"] not in branch["allowed_candidate_ids"]:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "candidate")
    if request["selected_schedule_id"] != branch["selected_schedule_id"]:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "schedule")
    if request["expected_measured_repetitions"] != branch["expected_measured_repetitions"]:
        raise StopSignal("SB_STOP_AUTHORIZATION_BINDING", "repetition_count")
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "authorization_id": artifact["authorization_id"],
        "authorization_sha256": _sha256(raw),
        "authorization_scope": AUTHORIZATION_SCOPE,
        "exact_bytes_recomputed": True,
        "request_binding": "PASS",
    }
