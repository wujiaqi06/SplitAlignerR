#!/usr/bin/env python3
"""Shared descriptor, metric and activation contract for Stage-B execution.

The same code path accepts the small bounded certification descriptor and the
three frozen Stage-B workload descriptors.  FIX002 executes only the former.
Large requests are completely validated and then stopped before worker launch
or physical allocation unless an exact external authorization artifact and its
four-field activation authorize that transition.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REFERENCE = ENGINE / "reference"
PILOT = ENGINE / "pilot"
for value in (HERE, REFERENCE, PILOT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from encode_stage_a_tiled_store import row_vectors  # noqa: E402
from encode_tiny_fixture import (  # noqa: E402
    bstar_registry_digest,
    canonical_bstar_members,
    gene_registry_digest,
    numeric_registry_digest,
    species_authority_digest,
)
from fix001_contract import (  # noqa: E402
    ALL_CANDIDATES,
    AUTHORITY_PATHS,
    FROZEN_PREREG_COMMIT,
    FROZEN_PREREG_TREE,
    HASH_FIELDS,
    LAYOUTS,
    MAX_INT64,
    PROTECTED_ROOT,
    SCHEDULES,
    WORKLOADS,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    _schedule_row_sha,
    canonical_json_bytes,
    strict_json_loads,
)
from stage_b_authorization import validate_authorization_for_request  # noqa: E402


FORMULA = "ENGINE003_STAGE_A_FIBER_CONSISTENT_BITS_V3"
LIVE_SCHEMA = "SplitAlignerR/ENGINE003StageBParameterizedLaunchRequest/v3"
WORKER_RESULT_SCHEMA = "SplitAlignerR/ENGINE003StageBParameterizedWorkerResult/v3"
BOUNDED_MODE = "BOUNDED_DESCRIPTOR_CERTIFICATION_NO_BENCHMARK"
LARGE_MODE = "FROZEN_STAGEB_WORKLOAD"
BOUNDED_WORKLOAD = "exec_preflight_bounded_129x7x4"
BOUNDED_DESCRIPTOR_PATH = (
    "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_exec_fix002/bounded_129x7x4.json"
)
BOUNDED_AUTHORITY_PATH = (
    "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_exec_fix002/BOUNDED_AUTHORITY.json"
)
OPERATION_CONTRACT = "STAGEB_ALL_FROZEN_19_METRICS_MULTIPASS_V4"
FULL_SCAN_ALGORITHM = "BOUNDED_FULL_LOGICAL_SCAN_V1"
FULL_SCAN_BLOCK_ROWS = 128
ZERO_SHA256 = "0" * 64
EXTERNAL_LARGE_ACTIVATION_FIELDS = {
    "authorization_id", "authorization_sha256",
    "authorization_artifact_path", "physical_allocation_authorized",
}
LEGACY_LARGE_DRY_ACTIVATION = {
    "state": "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED",
    "authorization_id": "FIX003_PREFLIGHT_DRY_RUN_ONLY",
    "authorization_sha256": ZERO_SHA256,
    "authorization_artifact_path": "NOT_SUPPLIED",
    "physical_allocation_authorized": False,
}


METRIC_HANDLERS = {
    "allocation_initialization": "allocate_candidate",
    "row_construction": "write_descriptor_payload_rows",
    "finalization": "finalize_candidate",
    "bounded_validation": "frozen_complete_bounded_validator",
    "row_read_sample": "contract_row_read_sample",
    "column_extraction_sample": "contract_column_extraction_sample",
    "block_read_sample": "contract_block_read_sample",
    "full_logical_read": "bounded_full_logical_scan_v1",
    "physical_component_hashing": "physical_components_in_manifest_order",
    "logical_hash_reconstruction": "matrix_logical_content_v1_reconstruction",
    "same_process_reopen": "same_process_open_validated_readonly",
    "fresh_process_reopen_internal_open": "fresh_process_internal_open",
    "fresh_process_reopen_total": "controller_launch_through_successful_exit",
    "peak_rss": "monotonic_worker_peak_rss",
    "temporary_physical_disk": "unpublished_target_allocated_bytes",
    "final_physical_disk": "published_target_allocated_bytes",
    "publication_high_water": "publication_transition_allocated_high_water",
    "publication_durability_barriers": "durable_publish_v1",
    "worker_end_to_end": "worker_entry_through_cleanup_ready",
}


REQUEST_FIELDS = {
    "schema", "execution_mode", "workload_id", "candidate_id", "layout_id",
    "source_commit", "source_tree", "frozen_prereg_commit",
    "frozen_prereg_tree", "descriptor_origin", "descriptor_source_commit",
    "descriptor_relative_path", "descriptor_sha256", "payload_formula",
    "dimensions", "anchor", "metric_contract_sha256",
    "fresh_resource_capture_sha256", "workload_branch_resource_capture_sha256",
    "host_profile",
    "fresh_available_memory_bytes", "memory_admission_required_bytes",
    "fresh_available_disk_bytes", "disk_admission_required_bytes",
    "projected_peak_rss_bound_bytes", "publication_high_water_bound_bytes",
    "physical_allocation_no_hole_capability",
    "allocation_capability_evidence_id", "durability_capability",
    "durability_capability_evidence_id", "compact_admission_result",
    "selected_schedule_id", "expected_measured_repetitions",
    "selection_frozen_before_first_measured_result", "measured_repetition",
    "schedule_position", "schedule_row_sha256", "timeout_seconds",
    "timeout_boundary_start", "timeout_boundary_end", "process_tree_scope",
    "expected_operation_contract", "activation", "runtime_target",
    "evidence_root", "run_phase", "warmup_position",
}


def _git_object_bytes(repo: Path, commit: str, relative: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{relative}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if process.returncode != 0:
        raise StopSignal(
            "SB_STOP_SOURCE_IDENTITY",
            f"git_object_unreadable:{relative}:{process.stderr.decode('utf-8', 'replace').strip()}",
        )
    return process.stdout


def assert_protected_source_clean(authority: ExecutionAuthority) -> None:
    process = subprocess.run(
        ["git", "-C", str(authority.repo_root), "status", "--porcelain=v1",
         "--untracked-files=all", "--", PROTECTED_ROOT],
        capture_output=True, text=True, check=False,
    )
    if process.returncode != 0:
        raise StopSignal("SB_STOP_SOURCE_IDENTITY", "protected_status_failed")
    if process.stdout.strip():
        raise StopSignal(
            "SB_STOP_EXECUTION_SOURCE_DIRTY",
            process.stdout.strip().splitlines()[0],
        )


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _positive_int(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_INT64


def numeric_row(row: int, columns: int, validity: bytes) -> bytes:
    output = bytearray(columns * 8)
    for column, available in enumerate(validity):
        if available not in (0, 1):
            raise ValueError("descriptor payload validity is not binary")
        if available:
            linear = row * columns + column
            bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
            struct.pack_into("<Q", output, column * 8, bits)
    return bytes(output)


@dataclass(frozen=True)
class DescriptorCase:
    workload_id: str
    raw: bytes
    descriptor: Mapping[str, Any]
    rows: int
    primitive: int
    bstar: int
    numeric: int
    terminals: Tuple[bool, ...]
    authorities: Tuple[bytes, bytes, bytes, bytes, bytes]
    anchor: Mapping[str, str]

    def row(self, row: int) -> Tuple[bytes, bytes, bytes]:
        if not 0 <= row < self.rows:
            raise IndexError("descriptor row outside bounds")
        state, validity = row_vectors(self.descriptor, self.terminals, row)
        return state, numeric_row(row, self.numeric, validity), validity

    def structural_probe(self) -> Dict[str, Any]:
        indices = []
        for value in (0, 1, self.rows // 2, self.rows - 1):
            if 0 <= value < self.rows and value not in indices:
                indices.append(value)
        rows = []
        for row in indices:
            state, numeric, validity = self.row(row)
            rows.append({
                "row": row,
                "state_sha256": hashlib.sha256(state).hexdigest(),
                "numeric_sha256": hashlib.sha256(numeric).hexdigest(),
                "validity_sha256": hashlib.sha256(validity).hexdigest(),
            })
        return {
            "probe_rows": rows,
            "maximum_single_row_payload_bytes": (
                self.primitive + self.numeric * 8 + self.numeric
            ),
            "complete_store_allocated": False,
        }


def descriptor_case(
        workload_id: str, raw: bytes, dimensions: Mapping[str, Any],
        anchor: Mapping[str, str]) -> DescriptorCase:
    if set(dimensions) != {"G", "B", "B_star", "C"} or not all(
            _positive_int(value) for value in dimensions.values()):
        raise StopSignal("SB_STOP_DESCRIPTOR", "dimension_contract")
    descriptor = strict_json_loads(raw)
    if not isinstance(descriptor, dict):
        raise StopSignal("SB_STOP_DESCRIPTOR", "descriptor_not_object")
    required = {
        "descriptor_schema", "taxon_label_bytes_hex", "primitive_entries",
        "gene_ids", "bstar_members",
    }
    if set(descriptor) != required:
        raise StopSignal("SB_STOP_DESCRIPTOR", "descriptor_field_set")
    rows = len(descriptor["gene_ids"])
    primitive = len(descriptor["primitive_entries"])
    bstar = len(descriptor["bstar_members"])
    numeric = primitive + bstar
    observed_dimensions = {"G": rows, "B": primitive, "B_star": bstar, "C": numeric}
    if observed_dimensions != dict(dimensions):
        raise StopSignal("SB_STOP_DESCRIPTOR", "descriptor_dimension_mismatch")
    if set(anchor) != set(HASH_FIELDS) or not all(_valid_sha(value) for value in anchor.values()):
        raise StopSignal("SB_STOP_HASH_MISMATCH", "anchor_field_set")
    descriptor_sha = hashlib.sha256(raw).hexdigest()
    if descriptor_sha != anchor["complete_descriptor_sha256"]:
        raise StopSignal("SB_STOP_HASH_MISMATCH", "descriptor_sha256")
    try:
        species = species_authority_digest(descriptor)
        genes = gene_registry_digest(descriptor["gene_ids"])
        encoded = canonical_bstar_members(descriptor["bstar_members"], primitive)
        bstar_digest = bstar_registry_digest(species, encoded)
        numeric_digest = numeric_registry_digest(
            species, primitive, bstar_digest, encoded,
        )
    except (TypeError, ValueError, IndexError, KeyError) as error:
        raise StopSignal("SB_STOP_DESCRIPTOR", str(error)) from error
    authorities = (species, genes, species, bstar_digest, numeric_digest)
    observed = {
        "species_authority_sha256": species.hex(),
        "gene_registry_sha256": genes.hex(),
        "primitive_registry_sha256": species.hex(),
        "bstar_registry_sha256": bstar_digest.hex(),
        "numeric_coordinate_registry_sha256": numeric_digest.hex(),
    }
    for field, value in observed.items():
        if anchor[field] != value:
            raise StopSignal("SB_STOP_HASH_MISMATCH", f"descriptor_registry:{field}")
    terminals = tuple(bool(value["terminal"]) for value in descriptor["primitive_entries"])
    return DescriptorCase(
        workload_id, raw, descriptor, rows, primitive, bstar, numeric,
        terminals, authorities, dict(anchor),
    )


def bounded_authority(authority: ExecutionAuthority) -> Dict[str, Any]:
    raw = _git_object_bytes(
        authority.repo_root, authority.commit, BOUNDED_AUTHORITY_PATH,
    )
    value = strict_json_loads(raw)
    if value.get("schema") != "SplitAlignerR/ENGINE003StageBExecFix002BoundedAuthority/v1":
        raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "bounded_authority_schema")
    return value


def request_descriptor_bytes(
        authority: ExecutionAuthority, assets: FrozenAssets,
        request: Mapping[str, Any]) -> bytes:
    origin = request["descriptor_origin"]
    if origin == "EXECUTION_SOURCE_OBJECT":
        if request["descriptor_source_commit"] != authority.commit:
            raise StopSignal("SB_STOP_SOURCE_IDENTITY", "descriptor_source_commit")
        raw = _git_object_bytes(
            authority.repo_root, authority.commit,
            request["descriptor_relative_path"],
        )
    elif origin == "FROZEN_PREREG_OBJECT":
        if request["descriptor_source_commit"] != FROZEN_PREREG_COMMIT:
            raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "descriptor_source_commit")
        path = request["descriptor_relative_path"]
        key = next(
            (name for name, relative in AUTHORITY_PATHS.items() if relative == path),
            None,
        )
        if key not in {"authority_descriptor", "stress_descriptor", "over4gib_descriptor"}:
            raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "descriptor_path")
        raw = assets.raw[key]
    else:
        raise StopSignal("SB_STOP_DESCRIPTOR", "descriptor_origin")
    if hashlib.sha256(raw).hexdigest() != request["descriptor_sha256"]:
        raise StopSignal("SB_STOP_HASH_MISMATCH", "descriptor_request_sha256")
    return raw


class FrozenMetricPlan:
    """Derive all probes from the exact frozen metric TSV loaded by Git OID."""

    def __init__(self, assets: FrozenAssets):
        if set(assets.metrics) != set(METRIC_HANDLERS):
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "metric_id_set")
        if len(set(METRIC_HANDLERS.values())) != len(METRIC_HANDLERS):
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "handler_not_one_to_one")
        self.rows = assets.metrics
        self.metric_contract_sha256 = hashlib.sha256(
            assets.raw["metric_contract"]
        ).hexdigest()
        self._validate_probe_language()

    def _validate_probe_language(self) -> None:
        if "rows 0,1,floor(G/2),G-1 in that order" not in self.rows["row_read_sample"]["measurement boundary"]:
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "row_probe_language")
        column = self.rows["column_extraction_sample"]["measurement boundary"]
        if "0,1,7,255,256,B-1" not in column or "0,1,7,255,256,C-1" not in column:
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "column_probe_language")
        block = self.rows["block_read_sample"]["measurement boundary"]
        for phrase in ("rows 0:min(2,G),cols 0:min(3,width)", "tail 2x3 block", "boundary 2x2 block at 255"):
            if phrase not in block:
                raise StopSignal("SB_STOP_OPERATION_CONTRACT", "block_probe_language")
        full = self.rows["full_logical_read"]["measurement boundary"]
        for phrase in (FULL_SCAN_ALGORITHM, "128-row maximum live block", "STATE,NUMERIC,VALIDITY"):
            if phrase not in full:
                raise StopSignal("SB_STOP_OPERATION_CONTRACT", "full_scan_language")

    def row_indices(self, rows: int) -> Tuple[int, ...]:
        output = []
        for value in (0, 1, rows // 2, rows - 1):
            if 0 <= value < rows and value not in output:
                output.append(value)
        return tuple(output)

    def column_indices(self, width: int) -> Tuple[int, ...]:
        return tuple(sorted({
            value for value in (0, 1, 7, 255, 256, width - 1)
            if 0 <= value < width
        }))

    def blocks(self, rows: int, width: int) -> Tuple[Tuple[int, int, int, int], ...]:
        output = [
            (0, min(2, rows), 0, min(3, width)),
            (max(0, rows - 2), min(2, rows), max(0, width - 3), min(3, width)),
        ]
        if rows > 255 and width > 255:
            output.append((255, min(2, rows - 255), 255, min(2, width - 255)))
        return tuple(value for value in output if value[1] and value[3])

    def binding_rows(self) -> list[Dict[str, Any]]:
        return [{
            "metric_id": metric_id,
            "treatment": self.rows[metric_id]["treatment"],
            "measurement_boundary": self.rows[metric_id]["measurement boundary"],
            "decision_role": self.rows[metric_id]["decision role"],
            "operation_handler": METRIC_HANDLERS[metric_id],
            "operation_cardinality": 1,
            "source": "FROZEN_METRIC_CONTRACT_GIT_OBJECT",
        } for metric_id in self.rows]


def _host_profile(resource: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "host_id": resource["host_id"],
        "platform_system": resource["platform_system"],
        "platform_release": resource["platform_release"],
        "platform_machine": resource["platform_machine"],
        "os_build": resource["os_build"],
        "filesystem": resource["filesystem"],
        "destination_device_id": resource["destination_device_id"],
        "target_volume_device": resource["target_volume_device"],
        "target_volume_mount_point": resource["target_volume_mount_point"],
    }


def _common_request(
        authority: ExecutionAuthority, metric_plan: FrozenMetricPlan,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        candidate: str, runtime_target: Path, evidence_root: Path,
        branch_resource: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    compact = candidate == "COMPACT_IN_MEMORY"
    durable_pass = (
        durability.get("durable_publish_v1_supported") is True
        and resource.get("platform_system") == "Darwin"
        and str(resource.get("filesystem", "")).lower() == "apfs"
    )
    branch_capture = resource if branch_resource is None else branch_resource
    return {
        "schema": LIVE_SCHEMA,
        "candidate_id": candidate,
        "layout_id": LAYOUTS[candidate],
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "frozen_prereg_commit": FROZEN_PREREG_COMMIT,
        "frozen_prereg_tree": FROZEN_PREREG_TREE,
        "payload_formula": FORMULA,
        "metric_contract_sha256": metric_plan.metric_contract_sha256,
        "fresh_resource_capture_sha256": hashlib.sha256(
            canonical_json_bytes(dict(resource))
        ).hexdigest(),
        "workload_branch_resource_capture_sha256": hashlib.sha256(
            canonical_json_bytes(dict(branch_capture))
        ).hexdigest(),
        "host_profile": _host_profile(resource),
        "fresh_available_memory_bytes": resource["admission_memory_ceiling_bytes"],
        "fresh_available_disk_bytes": resource["available_local_disk_bytes"],
        "physical_allocation_no_hole_capability": (
            "NOT_APPLICABLE" if compact else "PASS_PROVED_BY_BOUNDED_WORKER"
        ),
        "allocation_capability_evidence_id": (
            "NOT_APPLICABLE" if compact else "FIX002_ACTUAL_BACKEND_NO_HOLE"
        ),
        "durability_capability": (
            "NOT_APPLICABLE" if compact else ("PASS" if durable_pass else "UNSUPPORTED")
        ),
        "durability_capability_evidence_id": (
            "NOT_APPLICABLE" if compact else hashlib.sha256(
                canonical_json_bytes(dict(durability))
            ).hexdigest()
        ),
        "selection_frozen_before_first_measured_result": True,
        "expected_operation_contract": OPERATION_CONTRACT,
        "runtime_target": str(runtime_target.resolve()),
        "evidence_root": str(evidence_root.resolve()),
    }


def make_bounded_request(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        candidate: str, position: int, runtime_target: Path,
        evidence_root: Path | None = None) -> Dict[str, Any]:
    metric_plan = FrozenMetricPlan(assets)
    bounded = bounded_authority(authority)
    compact = candidate == "COMPACT_IN_MEMORY"
    schedule_row = {
        "workload_id": BOUNDED_WORKLOAD,
        "schedule_id": bounded["bounded_schedule_id"],
        "measured_repetition": "1", "position": str(position),
        "backend": candidate, "fresh_process": "TRUE", "fresh_target": "TRUE",
    }
    output = _common_request(
        authority, metric_plan, resource, durability, candidate, runtime_target,
        evidence_root or runtime_target.parent,
    )
    output.update({
        "execution_mode": BOUNDED_MODE,
        "workload_id": BOUNDED_WORKLOAD,
        "descriptor_origin": "EXECUTION_SOURCE_OBJECT",
        "descriptor_source_commit": authority.commit,
        "descriptor_relative_path": BOUNDED_DESCRIPTOR_PATH,
        "descriptor_sha256": bounded["anchor"]["complete_descriptor_sha256"],
        "dimensions": bounded["dimensions"],
        "anchor": bounded["anchor"],
        "memory_admission_required_bytes": bounded["memory_admission_required_bytes"],
        "disk_admission_required_bytes": (
            0 if compact else bounded["file_disk_admission_required_bytes"]
        ),
        "projected_peak_rss_bound_bytes": bounded["memory_admission_required_bytes"],
        "publication_high_water_bound_bytes": (
            0 if compact else bounded["file_disk_admission_required_bytes"]
        ),
        "compact_admission_result": "PASS",
        "selected_schedule_id": bounded["bounded_schedule_id"],
        "expected_measured_repetitions": 1,
        "measured_repetition": 1,
        "schedule_position": position,
        "schedule_row_sha256": _schedule_row_sha(schedule_row),
        "run_phase": "MEASURED",
        "warmup_position": 0,
        "timeout_seconds": bounded["timeout_seconds"],
        "timeout_boundary_start": "CONTROLLER_IMMEDIATELY_BEFORE_WORKER_SPAWN",
        "timeout_boundary_end": "POST_CLEANUP_RESULT_RECORDED",
        "process_tree_scope": "CONTROLLER_OWNED_WORKER_AND_ALL_DESCENDANTS",
        "activation": {
            "state": "BOUNDED_CERTIFICATION_AUTHORIZED",
            "authorization_id": "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX003_BOUNDED",
            "authorization_sha256": ZERO_SHA256,
            "authorization_artifact_path": "NOT_APPLICABLE_BOUNDED",
            "physical_allocation_authorized": True,
        },
    })
    return output


def make_large_request(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        workload: str, candidate: str, runtime_target: Path,
        schedule_row: Mapping[str, str], run_phase: str,
        evidence_root: Path, activation: Mapping[str, Any] | None = None,
        branch_resource: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    metric_plan = FrozenMetricPlan(assets)
    selection_resource = resource if branch_resource is None else branch_resource
    memory_available = selection_resource["admission_memory_ceiling_bytes"]
    compact_required = int(
        assets.projections[(workload, "COMPACT_IN_MEMORY")]["memory_admission_required_bytes"]
    )
    admission = "PASS" if memory_available >= compact_required else "FAIL"
    if candidate not in SCHEDULES[admission][2]:
        # FIX002 must validate all four candidate requests.  The local profile
        # is expected to admit compact; fail closed rather than invent a row.
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "compact_candidate_not_admitted")
    selection = assets.schedule_selection[(workload, admission)]
    schedule_id = selection["selected_schedule_id"]
    if run_phase == "MEASURED":
        required_row_fields = {
            "workload_id", "schedule_id", "selection_condition", "seed",
            "measured_repetition", "position", "backend", "fresh_process",
            "fresh_target", "warmup_policy", "cache_policy",
        }
        if set(schedule_row) != required_row_fields or schedule_row.get("schedule_id") != schedule_id:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "measured_row_shape")
        measured_repetition = int(schedule_row["measured_repetition"])
        schedule_position = int(schedule_row["position"])
        warmup_position = 0
    elif run_phase == "UNTIMED_WARMUP":
        required_row_fields = {
            "workload_id", "schedule_id", "selection_condition",
            "warmup_position", "backend", "fresh_process", "fresh_target",
            "measured",
        }
        if set(schedule_row) != required_row_fields:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "warmup_row_shape")
        measured_repetition = 0
        schedule_position = int(schedule_row["warmup_position"])
        warmup_position = schedule_position
    else:
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "run_phase")
    if schedule_row.get("workload_id") != workload or schedule_row.get("backend") != candidate:
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "row_workload_candidate")
    projection = assets.projections[(workload, candidate)]
    timeout = assets.timeouts[(workload, candidate)]
    workload_row = assets.workloads[workload]
    compact = candidate == "COMPACT_IN_MEMORY"
    output = _common_request(
        authority, metric_plan, resource, durability, candidate, runtime_target,
        evidence_root, selection_resource,
    )
    output.update({
        "execution_mode": LARGE_MODE,
        "workload_id": workload,
        "descriptor_origin": "FROZEN_PREREG_OBJECT",
        "descriptor_source_commit": FROZEN_PREREG_COMMIT,
        "descriptor_relative_path": workload_row["complete_descriptor_path"],
        "descriptor_sha256": workload_row["complete_descriptor_sha256"],
        "dimensions": {
            "G": int(workload_row["G"]), "B": int(workload_row["B"]),
            "B_star": int(workload_row["B_star"]), "C": int(workload_row["C"]),
        },
        "anchor": assets.anchor(workload),
        "memory_admission_required_bytes": int(projection["memory_admission_required_bytes"]),
        "disk_admission_required_bytes": int(projection["disk_admission_required_bytes"]),
        "projected_peak_rss_bound_bytes": int(projection["projected_peak_rss_before_reserve_bytes"]),
        "publication_high_water_bound_bytes": int(projection["publication_high_water_bytes"]),
        "compact_admission_result": admission,
        "selected_schedule_id": schedule_id,
        "expected_measured_repetitions": int(selection["expected_measured_repetitions"]),
        "measured_repetition": measured_repetition,
        "schedule_position": schedule_position,
        "schedule_row_sha256": _schedule_row_sha(schedule_row),
        "run_phase": run_phase,
        "warmup_position": warmup_position,
        "timeout_seconds": int(timeout["timeout_seconds"]),
        "timeout_boundary_start": timeout["timeout_boundary_start"],
        "timeout_boundary_end": timeout["timeout_boundary_end"],
        "process_tree_scope": timeout["process_tree_scope"],
        "activation": dict(activation or LEGACY_LARGE_DRY_ACTIVATION),
    })
    if compact and output["disk_admission_required_bytes"] != 0:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "compact_disk_projection")
    return output


def _expected_host_profile(resource: Mapping[str, Any]) -> Dict[str, Any]:
    return _host_profile(resource)


def prelaunch_guard(
        authority: ExecutionAuthority, assets: FrozenAssets,
        request: Mapping[str, Any], runtime_root: Path,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        branch_resource: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    if set(request) != REQUEST_FIELDS or request.get("schema") != LIVE_SCHEMA:
        extra = sorted(set(request) - REQUEST_FIELDS)
        missing = sorted(REQUEST_FIELDS - set(request))
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", f"extra={extra};missing={missing}")
    assert_protected_source_clean(authority)
    if request["source_commit"] != authority.commit or request["source_tree"] != authority.tree:
        raise StopSignal("SB_STOP_SOURCE_IDENTITY", "request_source")
    if request["frozen_prereg_commit"] != FROZEN_PREREG_COMMIT or request["frozen_prereg_tree"] != FROZEN_PREREG_TREE:
        raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "request_prereg")
    if request["candidate_id"] not in ALL_CANDIDATES or request["layout_id"] != LAYOUTS[request["candidate_id"]]:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "candidate_layout")
    if request["payload_formula"] != FORMULA or request["expected_operation_contract"] != OPERATION_CONTRACT:
        raise StopSignal("SB_STOP_OPERATION_CONTRACT", "payload_or_operation")
    plan = FrozenMetricPlan(assets)
    if request["metric_contract_sha256"] != plan.metric_contract_sha256:
        raise StopSignal("SB_STOP_OPERATION_CONTRACT", "metric_contract_sha256")
    if request["fresh_resource_capture_sha256"] != hashlib.sha256(canonical_json_bytes(dict(resource))).hexdigest():
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "resource_capture_identity")
    selection_resource = resource if branch_resource is None else branch_resource
    if request["workload_branch_resource_capture_sha256"] != hashlib.sha256(
            canonical_json_bytes(dict(selection_resource))).hexdigest():
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "workload_branch_capture_identity")
    if request["host_profile"] != _expected_host_profile(resource):
        raise StopSignal("SB_STOP_CAPABILITY", "host_filesystem_profile")
    if _expected_host_profile(selection_resource) != _expected_host_profile(resource):
        raise StopSignal("SB_STOP_CAPABILITY", "branch_series_host_volume")
    if request["fresh_available_memory_bytes"] != resource["admission_memory_ceiling_bytes"]:
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "fresh_memory_value")
    if request["fresh_available_disk_bytes"] != resource["available_local_disk_bytes"]:
        raise StopSignal("SB_STOP_ADMISSION_DISK", "fresh_disk_value")
    if request["fresh_available_memory_bytes"] < request["memory_admission_required_bytes"]:
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "insufficient")
    compact = request["candidate_id"] == "COMPACT_IN_MEMORY"
    if not compact and request["fresh_available_disk_bytes"] < request["disk_admission_required_bytes"]:
        raise StopSignal("SB_STOP_ADMISSION_DISK", "insufficient")
    expected_capability = "NOT_APPLICABLE" if compact else "PASS"
    if request["durability_capability"] != expected_capability:
        raise StopSignal("SB_STOP_CAPABILITY", "durability")
    expected_allocation = (
        "NOT_APPLICABLE" if compact else "PASS_PROVED_BY_BOUNDED_WORKER"
    )
    expected_allocation_evidence = (
        "NOT_APPLICABLE" if compact else "FIX002_ACTUAL_BACKEND_NO_HOLE"
    )
    if (
        request["physical_allocation_no_hole_capability"] != expected_allocation
        or request["allocation_capability_evidence_id"] != expected_allocation_evidence
    ):
        raise StopSignal("SB_STOP_CAPABILITY", "allocation_evidence")
    if compact and request["durability_capability_evidence_id"] != "NOT_APPLICABLE":
        raise StopSignal("SB_STOP_CAPABILITY", "compact_durability_evidence")
    if not compact:
        if durability.get("durable_publish_v1_supported") is not True:
            raise StopSignal("SB_STOP_CAPABILITY", "durable_publish_v1")
        if request["host_profile"]["platform_system"] != "Darwin" or str(
                request["host_profile"]["filesystem"]).lower() != "apfs":
            raise StopSignal(
                "SB_STOP_CAPABILITY", "FIX002_REAL_BACKEND_REPLAY_REQUIRES_MACOS_APFS",
            )
        if request["durability_capability_evidence_id"] != hashlib.sha256(canonical_json_bytes(dict(durability))).hexdigest():
            raise StopSignal("SB_STOP_CAPABILITY", "durability_evidence")
        if request["physical_allocation_no_hole_capability"] != "PASS_PROVED_BY_BOUNDED_WORKER":
            raise StopSignal("SB_STOP_CAPABILITY", "allocation_no_hole")
    target = Path(request["runtime_target"])
    try:
        target.resolve().relative_to(runtime_root.resolve())
    except (ValueError, OSError) as error:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "runtime_target_escape") from error
    if target.exists():
        raise StopSignal("SB_STOP_CLEANUP", "fresh_target_exists")
    evidence_root = Path(request["evidence_root"])
    if str(evidence_root.resolve()) != request["evidence_root"]:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "evidence_root_canonical")

    raw = request_descriptor_bytes(authority, assets, request)
    case = descriptor_case(
        request["workload_id"], raw, request["dimensions"], request["anchor"],
    )
    probe = case.structural_probe()

    mode = request["execution_mode"]
    if mode == BOUNDED_MODE:
        bounded = bounded_authority(authority)
        if request["workload_id"] != BOUNDED_WORKLOAD or request["descriptor_relative_path"] != BOUNDED_DESCRIPTOR_PATH:
            raise StopSignal("SB_STOP_DESCRIPTOR", "bounded_identity")
        for field in (
                "dimensions", "anchor", "memory_admission_required_bytes",
                "timeout_seconds"):
            if request[field] != bounded[field]:
                raise StopSignal("SB_STOP_PROJECTION_DRIFT", f"bounded:{field}")
        expected_disk = 0 if compact else bounded["file_disk_admission_required_bytes"]
        if request["disk_admission_required_bytes"] != expected_disk:
            raise StopSignal("SB_STOP_PROJECTION_DRIFT", "bounded:disk")
        if (
            request["projected_peak_rss_bound_bytes"]
            != bounded["memory_admission_required_bytes"]
            or request["publication_high_water_bound_bytes"] != expected_disk
        ):
            raise StopSignal("SB_STOP_PROJECTION_DRIFT", "bounded:projection")
        if (
            request["timeout_boundary_start"]
            != "CONTROLLER_IMMEDIATELY_BEFORE_WORKER_SPAWN"
            or request["timeout_boundary_end"] != "POST_CLEANUP_RESULT_RECORDED"
            or request["process_tree_scope"]
            != "CONTROLLER_OWNED_WORKER_AND_ALL_DESCENDANTS"
        ):
            raise StopSignal("SB_STOP_TIMEOUT_CONTRACT", "bounded_boundary")
        position = ALL_CANDIDATES.index(request["candidate_id"]) + 1
        schedule_row = {
            "workload_id": BOUNDED_WORKLOAD,
            "schedule_id": bounded["bounded_schedule_id"],
            "measured_repetition": "1", "position": str(position),
            "backend": request["candidate_id"], "fresh_process": "TRUE",
            "fresh_target": "TRUE",
        }
        if (
            request["compact_admission_result"] != "PASS"
            or request["selected_schedule_id"] != bounded["bounded_schedule_id"]
            or request["expected_measured_repetitions"] != 1
            or request["selection_frozen_before_first_measured_result"] is not True
            or request["measured_repetition"] != 1
            or request["schedule_position"] != position
            or request["schedule_row_sha256"] != _schedule_row_sha(schedule_row)
            or request["run_phase"] != "MEASURED"
            or request["warmup_position"] != 0
        ):
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "bounded_schedule")
        activation = request["activation"]
        if activation != {
            "state": "BOUNDED_CERTIFICATION_AUTHORIZED",
            "authorization_id": "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX003_BOUNDED",
            "authorization_sha256": ZERO_SHA256,
            "authorization_artifact_path": "NOT_APPLICABLE_BOUNDED",
            "physical_allocation_authorized": True,
        }:
            raise StopSignal("SB_STOP_ACTIVATION", "bounded_activation")
        return {
            "status": "PRELAUNCH_PASS_BOUNDED_PHYSICAL_ALLOWED",
            "case": case, "descriptor_probe": probe,
            "worker_launch_authorized": True,
            "physical_allocation_authorized": True,
            "last_completed_stage": "ACTIVATION_GATE_PASS",
        }

    if mode != LARGE_MODE or request["workload_id"] not in WORKLOADS:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "execution_mode")
    workload = request["workload_id"]
    candidate = request["candidate_id"]
    workload_row = assets.workloads[workload]
    expected_dimensions = {
        "G": int(workload_row["G"]), "B": int(workload_row["B"]),
        "B_star": int(workload_row["B_star"]), "C": int(workload_row["C"]),
    }
    if request["dimensions"] != expected_dimensions or request["anchor"] != assets.anchor(workload):
        raise StopSignal("SB_STOP_HASH_MISMATCH", "large_dimension_or_anchor")
    projection = assets.projections[(workload, candidate)]
    expected_projection = {
        "memory_admission_required_bytes": int(projection["memory_admission_required_bytes"]),
        "disk_admission_required_bytes": int(projection["disk_admission_required_bytes"]),
        "projected_peak_rss_bound_bytes": int(projection["projected_peak_rss_before_reserve_bytes"]),
        "publication_high_water_bound_bytes": int(projection["publication_high_water_bytes"]),
    }
    for field, value in expected_projection.items():
        if request[field] != value:
            raise StopSignal("SB_STOP_PROJECTION_DRIFT", field)
    admission = request["compact_admission_result"]
    compact_required = int(
        assets.projections[(workload, "COMPACT_IN_MEMORY")][
            "memory_admission_required_bytes"
        ]
    )
    observed_admission = (
        "PASS" if selection_resource["admission_memory_ceiling_bytes"] >= compact_required
        else "FAIL"
    )
    if admission != observed_admission:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "compact_branch_derivation")
    selection = assets.schedule_selection.get((workload, admission))
    if selection is None:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "compact_branch")
    if (
        request["selected_schedule_id"] != selection["selected_schedule_id"]
        or request["expected_measured_repetitions"] != int(selection["expected_measured_repetitions"])
        or request["selection_frozen_before_first_measured_result"] is not True
    ):
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "schedule_selection")
    if request["run_phase"] == "MEASURED":
        if request["warmup_position"] != 0:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "measured_warmup_position")
        row = assets.schedule_row(
            workload, request["selected_schedule_id"],
            request["measured_repetition"], request["schedule_position"],
        )
    elif request["run_phase"] == "UNTIMED_WARMUP":
        if request["measured_repetition"] != 0 or request["warmup_position"] != request["schedule_position"]:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "warmup_indices")
        matches = [
            value for value in assets.warmup_rows(workload, admission)
            if int(value["warmup_position"]) == request["warmup_position"]
        ]
        if len(matches) != 1:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "warmup_row")
        row = matches[0]
    else:
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "run_phase")
    if row["backend"] != candidate or request["schedule_row_sha256"] != _schedule_row_sha(row):
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "large_schedule_row")
    timeout = assets.timeouts[(workload, candidate)]
    for field in (
            "timeout_seconds", "timeout_boundary_start", "timeout_boundary_end",
            "process_tree_scope"):
        expected: Any = int(timeout[field]) if field == "timeout_seconds" else timeout[field]
        if request[field] != expected:
            raise StopSignal("SB_STOP_TIMEOUT_CONTRACT", field)

    activation = request["activation"]
    if activation == LEGACY_LARGE_DRY_ACTIVATION:
        raise StopSignal(
            "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED",
            "ALL_PRELAUNCH_DECISIONS_COMPLETE;WORKER_LAUNCH=0;PHYSICAL_ALLOCATION=0",
        )
    if (
            not isinstance(activation, dict)
            or set(activation) != EXTERNAL_LARGE_ACTIVATION_FIELDS):
        raise StopSignal("SB_STOP_ACTIVATION", "field_set")
    authorization = validate_authorization_for_request(
        assets, request, runtime_root, resource, durability, selection_resource,
    )
    return {
        "status": "PRELAUNCH_PASS_LARGE_EXTERNALLY_AUTHORIZED",
        "case": case, "descriptor_probe": probe,
        "external_authorization": authorization,
        "worker_launch_authorized": True,
        "physical_allocation_authorized": True,
        "last_completed_stage": "ACTIVATION_GATE_PASS",
    }
