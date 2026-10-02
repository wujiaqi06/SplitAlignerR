#!/usr/bin/env python3
"""Frozen-contract helpers for ENGINE003 Stage-B execution preflight.

This module is deliberately standard-library only.  It validates future
worker launch requests against the accepted preregistration artifacts, builds
the exact decision-input transport from bounded synthetic worker evidence, and
implements the canonical bounded logical stream used by the preflight worker.
It does not allocate a Stage-B MatrixStore or collect benchmark timings.
"""

from __future__ import annotations

import csv
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


WORKLOADS = (
    "authority_current_2275x1086",
    "stress_projected_100000x4913",
    "stress_all_layouts_over4gib_102500x4913",
)
FILE_CANDIDATES = (
    "ROW_MAJOR_DISK",
    "COLUMN_MAJOR_DISK",
    "TILED_DISK",
)
ALL_CANDIDATES = ("COMPACT_IN_MEMORY",) + FILE_CANDIDATES
LAYOUTS = {
    "COMPACT_IN_MEMORY": "COMPACT_CONTIGUOUS_V1",
    "ROW_MAJOR_DISK": "ROW_MAJOR_FILE_V1",
    "COLUMN_MAJOR_DISK": "COLUMN_MAJOR_FILE_V1",
    "TILED_DISK": "TILED_ROW_MAJOR_PROVISIONAL_256X256",
}
SCHEDULES = {
    "PASS": ("FOUR_CANDIDATE_WILLIAMS_8", 8, ALL_CANDIDATES),
    "FAIL": ("THREE_FILE_CANDIDATE_WILLIAMS_6", 6, FILE_CANDIDATES),
}
PHASES = (
    "allocation_initialization",
    "row_construction",
    "finalization",
    "bounded_validation",
)
SECONDARY_FIELDS = (
    "peak_rss_repetitions",
    "publication_highwater_repetitions",
    "column_extraction_repetitions",
    "full_logical_scan_repetitions",
)
HASH_FIELDS = (
    "complete_descriptor_sha256",
    "species_authority_sha256",
    "gene_registry_sha256",
    "primitive_registry_sha256",
    "bstar_registry_sha256",
    "numeric_coordinate_registry_sha256",
    "state_stream_sha256",
    "numeric_stream_sha256",
    "validity_stream_sha256",
    "logical_content_sha256",
)
MAX_INT64 = 2 ** 63 - 1
PRELAUNCH_SCHEMA = "SplitAlignerR/ENGINE003StageBPrelaunchRequest/v1"
DECISION_INPUT_SCHEMA = "SplitAlignerR/ENGINE003StageBDecisionInputExact/v1"
WORKER_RESULT_SCHEMA = "SplitAlignerR/ENGINE003StageBBoundedWorkerResult/v1"
OPERATION_CONTRACT = "STAGEB_SAMPLE_ALL_19_METRICS_WITH_BOUNDED_FULL_LOGICAL_SCAN_V1"
BOUNDED_MODE = "BOUNDED_EXEC_PREFLIGHT_SYNTHETIC_NO_BENCHMARK"
FULL_SCAN_BLOCK_ROWS = 128
HASH_CONTEXT_CHARGE_BYTES = 256
VALIDITY_CARRY_CHARGE_BYTES = 1


class StrictJSONError(ValueError):
    """The JSON transport is ambiguous or violates the integer-only gate."""


class ContractError(ValueError):
    """A frozen contract artifact is malformed."""


@dataclass
class StopSignal(Exception):
    stop_id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.stop_id}:{self.detail}"


def _reject_float(value: str) -> Any:
    raise StrictJSONError(f"floating JSON number is prohibited: {value}")


def _reject_constant(value: str) -> Any:
    raise StrictJSONError(f"non-finite JSON constant is prohibited: {value}")


def _unique_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise StrictJSONError(f"duplicate JSON object key: {key}")
        output[key] = value
    return output


def strict_json_loads(raw: bytes) -> Any:
    """Decode unambiguous UTF-8 JSON while refusing float/duplicate tokens."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise StrictJSONError("JSON transport is not valid UTF-8") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except StrictJSONError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StrictJSONError(f"invalid JSON transport: {error}") from error


def strict_json_load(path: Path) -> Any:
    return strict_json_loads(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical transport: UTF-8, stable structure, no NaN and integer tokens."""
    _validate_json_tree(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    ).encode("utf-8")


def _validate_json_tree(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, str):
        return
    if type(value) is bool:
        return
    if type(value) is int:
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_tree(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictJSONError(f"non-string JSON object key at {path}")
            _validate_json_tree(item, f"{path}.{key}")
        return
    raise StrictJSONError(f"non-integer/non-JSON scalar at {path}: {type(value).__name__}")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def valid_git_oid(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def positive_int64(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_INT64


def safe_repo_path(repo_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ContractError("missing repository-relative path")
    pure = Path(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ContractError("unsafe repository-relative path")
    root = repo_root.resolve()
    resolved = (root / pure).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ContractError("repository-relative path escapes source root") from error
    return resolved


class FrozenAssets:
    """Parsed accepted preregistration assets, keyed without defaults."""

    def __init__(self, repo_root: Path, source_commit: str, source_tree: str):
        if not valid_git_oid(source_commit) or not valid_git_oid(source_tree):
            raise ContractError("explicit 40-hex source commit/tree are required")
        self.repo_root = repo_root.resolve()
        self.source_commit = source_commit
        self.source_tree = source_tree
        engine = self.repo_root / "dev/ENGINE003-PREFLIGHT"
        evidence = engine / "evidence/STAGEB_PREREG001"
        contracts = engine / "stage_b"
        self.workloads = self._unique(
            read_tsv(evidence / "STAGEB_WORKLOAD_LEDGER.tsv"), "workload_id"
        )
        self.projections = self._unique_pair(
            read_tsv(evidence / "STAGEB_CANDIDATE_PROJECTIONS.tsv"),
            "workload_id", "backend",
        )
        self.candidates = self._unique(
            read_tsv(contracts / "STAGEB_CANDIDATE_SET.tsv"), "candidate_id"
        )
        self.schedule_selection = self._unique_pair(
            read_tsv(contracts / "STAGEB_WORKLOAD_SCHEDULE_SELECTION_CONTRACT.tsv"),
            "workload_id", "compact_admission_result",
        )
        self.execution_schedule = read_tsv(
            evidence / "STAGEB_EXECUTION_SCHEDULE.tsv"
        )
        self.timeouts = self._unique_pair(
            read_tsv(contracts / "STAGEB_TIMEOUT_CONTRACT.tsv"),
            "workload_id", "candidate_id",
        )
        self.metrics = self._unique(
            read_tsv(contracts / "STAGEB_METRIC_CONTRACT.tsv"), "metric_id"
        )
        if tuple(self.workloads) != WORKLOADS:
            raise ContractError("frozen workload order mismatch")
        if set(self.candidates) != set(ALL_CANDIDATES):
            raise ContractError("frozen candidate set mismatch")
        if len(self.timeouts) != 12 or len(self.metrics) != 19:
            raise ContractError("timeout/metric contract cardinality mismatch")

    @staticmethod
    def _unique(rows: Iterable[Dict[str, str]], key: str) -> Dict[str, Dict[str, str]]:
        output: Dict[str, Dict[str, str]] = {}
        for row in rows:
            value = row.get(key, "")
            if not value or value in output:
                raise ContractError(f"missing/duplicate TSV key: {key}={value!r}")
            output[value] = row
        return output

    @staticmethod
    def _unique_pair(rows: Iterable[Dict[str, str]], left: str, right: str) \
            -> Dict[Tuple[str, str], Dict[str, str]]:
        output: Dict[Tuple[str, str], Dict[str, str]] = {}
        for row in rows:
            key = (row.get(left, ""), row.get(right, ""))
            if not all(key) or key in output:
                raise ContractError(f"missing/duplicate TSV pair: {key!r}")
            output[key] = row
        return output

    def schedule_rows(self, workload: str, schedule_id: str) \
            -> List[Dict[str, str]]:
        rows = [
            row for row in self.execution_schedule
            if row["workload_id"] == workload and row["schedule_id"] == schedule_id
        ]
        return sorted(
            rows,
            key=lambda row: (int(row["measured_repetition"]), int(row["position"])),
        )

    def anchor(self, workload: str) -> Dict[str, str]:
        row = self.workloads[workload]
        return {field: row[field] for field in HASH_FIELDS}


def make_prelaunch_request(
        assets: FrozenAssets,
        workload_id: str,
        candidate_id: str,
        compact_admission_result: str,
        overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build a complete request for tests; no field is defaulted by the guard."""
    selection = assets.schedule_selection[(workload_id, compact_admission_result)]
    timeout = assets.timeouts[(workload_id, candidate_id)]
    workload = assets.workloads[workload_id]
    projection = assets.projections[(workload_id, candidate_id)]
    compact_projection = assets.projections[(workload_id, "COMPACT_IN_MEMORY")]
    is_compact = candidate_id == "COMPACT_IN_MEMORY"
    memory_required = int(projection["memory_admission_required_bytes"])
    compact_memory_required = int(
        compact_projection["memory_admission_required_bytes"]
    )
    disk_required = int(projection["disk_admission_required_bytes"])
    request: Dict[str, Any] = {
        "schema": PRELAUNCH_SCHEMA,
        "execution_mode": BOUNDED_MODE,
        "workload_id": workload_id,
        "candidate_id": candidate_id,
        "layout_id": LAYOUTS[candidate_id],
        "source_commit": assets.source_commit,
        "source_tree": assets.source_tree,
        "descriptor_relative_path": workload["complete_descriptor_path"],
        "descriptor_sha256": workload["complete_descriptor_sha256"],
        "anchor": assets.anchor(workload_id),
        "fresh_memory_admission": "PASS",
        "fresh_available_memory_bytes": memory_required,
        "memory_admission_required_bytes": memory_required,
        "projected_peak_rss_bound_bytes": int(
            projection["projected_peak_rss_before_reserve_bytes"]
        ),
        "fresh_compact_available_memory_bytes": (
            compact_memory_required if compact_admission_result == "PASS"
            else compact_memory_required - 1
        ),
        "compact_memory_admission_required_bytes": compact_memory_required,
        "fresh_disk_admission": "NOT_APPLICABLE" if is_compact else "PASS",
        "fresh_available_disk_bytes": 0 if is_compact else disk_required,
        "disk_admission_required_bytes": disk_required,
        "publication_high_water_bound_bytes": int(
            projection["publication_high_water_bytes"]
        ),
        "fresh_resource_capture_id": "BOUNDED_INJECTED_RESOURCE_CAPTURE_V1",
        "physical_allocation_no_hole_capability": (
            "NOT_APPLICABLE" if is_compact else "PASS"
        ),
        "allocation_capability_evidence_id": (
            "NOT_APPLICABLE" if is_compact
            else "BOUNDED_INJECTED_NO_HOLE_CAPABILITY_V1"
        ),
        "durability_capability": "NOT_APPLICABLE" if is_compact else "PASS",
        "durability_capability_evidence_id": (
            "NOT_APPLICABLE" if is_compact
            else "BOUNDED_INJECTED_DURABILITY_CAPABILITY_V1"
        ),
        "compact_admission_result": compact_admission_result,
        "selected_schedule_id": selection["selected_schedule_id"],
        "expected_measured_repetitions": int(
            selection["expected_measured_repetitions"]
        ),
        "selection_frozen_before_first_measured_result": True,
        "timeout_seconds": int(timeout["timeout_seconds"]),
        "timeout_boundary_start": timeout["timeout_boundary_start"],
        "timeout_boundary_end": timeout["timeout_boundary_end"],
        "process_tree_scope": timeout["process_tree_scope"],
        "expected_operation_contract": OPERATION_CONTRACT,
    }
    if overrides:
        request.update(overrides)
    return request


def prelaunch_guard(assets: FrozenAssets, request: Mapping[str, Any]) \
        -> Dict[str, Any]:
    required = {
        "schema", "execution_mode", "workload_id", "candidate_id", "layout_id",
        "source_commit", "source_tree", "descriptor_relative_path",
        "descriptor_sha256", "anchor", "fresh_memory_admission",
        "fresh_available_memory_bytes", "memory_admission_required_bytes",
        "projected_peak_rss_bound_bytes",
        "fresh_compact_available_memory_bytes",
        "compact_memory_admission_required_bytes", "fresh_disk_admission",
        "fresh_available_disk_bytes", "disk_admission_required_bytes",
        "publication_high_water_bound_bytes", "fresh_resource_capture_id",
        "physical_allocation_no_hole_capability",
        "allocation_capability_evidence_id", "durability_capability",
        "durability_capability_evidence_id", "compact_admission_result",
        "selected_schedule_id", "expected_measured_repetitions",
        "selection_frozen_before_first_measured_result", "timeout_seconds",
        "timeout_boundary_start", "timeout_boundary_end", "process_tree_scope",
        "expected_operation_contract",
    }
    if set(request) != required:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "missing_or_extra_field")
    if request["schema"] != PRELAUNCH_SCHEMA or request["execution_mode"] != BOUNDED_MODE:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "schema_or_mode")
    workload = request["workload_id"]
    candidate = request["candidate_id"]
    if workload not in assets.workloads:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "unknown_workload")
    if candidate not in assets.candidates:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "unknown_candidate")
    if request["source_commit"] != assets.source_commit \
            or request["source_tree"] != assets.source_tree:
        raise StopSignal("SB_STOP_SOURCE_IDENTITY", "commit_or_tree_mismatch")
    if request["layout_id"] != LAYOUTS[candidate]:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "candidate_layout_mismatch")

    workload_row = assets.workloads[workload]
    if request["descriptor_relative_path"] != workload_row["complete_descriptor_path"]:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "descriptor_path_mismatch")
    descriptor = safe_repo_path(assets.repo_root, request["descriptor_relative_path"])
    if not descriptor.is_file():
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "descriptor_missing")
    observed_descriptor_hash = sha256_file(descriptor)
    if request["descriptor_sha256"] != workload_row["complete_descriptor_sha256"] \
            or observed_descriptor_hash != workload_row["complete_descriptor_sha256"]:
        raise StopSignal("SB_STOP_HASH_MISMATCH", "descriptor_sha256")
    if request["anchor"] != assets.anchor(workload):
        raise StopSignal("SB_STOP_HASH_MISMATCH", "anchor_or_registry_identity")

    projection = assets.projections[(workload, candidate)]
    memory_required = int(projection["memory_admission_required_bytes"])
    if request["memory_admission_required_bytes"] != memory_required \
            or request["projected_peak_rss_bound_bytes"] != int(
                projection["projected_peak_rss_before_reserve_bytes"]
            ):
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "memory_projection")
    if type(request["fresh_available_memory_bytes"]) is not int:
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "available_memory_type")
    derived_memory = (
        "PASS" if request["fresh_available_memory_bytes"] >= memory_required
        else "FAIL"
    )
    if request["fresh_memory_admission"] != derived_memory \
            or derived_memory != "PASS":
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "fresh_memory_admission")
    compact = candidate == "COMPACT_IN_MEMORY"
    expected_na = "NOT_APPLICABLE" if compact else "PASS"
    disk_required = int(projection["disk_admission_required_bytes"])
    if request["disk_admission_required_bytes"] != disk_required \
            or request["publication_high_water_bound_bytes"] != int(
                projection["publication_high_water_bytes"]
            ):
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "disk_projection")
    if compact:
        derived_disk = "NOT_APPLICABLE"
        if request["fresh_available_disk_bytes"] != 0:
            raise StopSignal("SB_STOP_ADMISSION_DISK", "compact_disk_value")
    else:
        if type(request["fresh_available_disk_bytes"]) is not int:
            raise StopSignal("SB_STOP_ADMISSION_DISK", "available_disk_type")
        derived_disk = (
            "PASS" if request["fresh_available_disk_bytes"] >= disk_required
            else "FAIL"
        )
    if request["fresh_disk_admission"] != derived_disk \
            or derived_disk != expected_na:
        raise StopSignal("SB_STOP_ADMISSION_DISK", "fresh_disk_admission")
    if request["fresh_resource_capture_id"] \
            != "BOUNDED_INJECTED_RESOURCE_CAPTURE_V1":
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "resource_capture_identity")
    if request["physical_allocation_no_hole_capability"] != expected_na:
        raise StopSignal("SB_STOP_CAPABILITY", "allocation_no_hole")
    expected_allocation_id = (
        "NOT_APPLICABLE" if compact
        else "BOUNDED_INJECTED_NO_HOLE_CAPABILITY_V1"
    )
    if request["allocation_capability_evidence_id"] != expected_allocation_id:
        raise StopSignal("SB_STOP_CAPABILITY", "allocation_evidence_identity")
    if request["durability_capability"] != expected_na:
        raise StopSignal("SB_STOP_CAPABILITY", "durability")
    expected_durability_id = (
        "NOT_APPLICABLE" if compact
        else "BOUNDED_INJECTED_DURABILITY_CAPABILITY_V1"
    )
    if request["durability_capability_evidence_id"] != expected_durability_id:
        raise StopSignal("SB_STOP_CAPABILITY", "durability_evidence_identity")

    admission = request["compact_admission_result"]
    if admission not in SCHEDULES:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "compact_admission_result")
    compact_required = int(
        assets.projections[(workload, "COMPACT_IN_MEMORY")][
            "memory_admission_required_bytes"
        ]
    )
    if request["compact_memory_admission_required_bytes"] != compact_required \
            or type(request["fresh_compact_available_memory_bytes"]) is not int:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "compact_memory_projection")
    derived_compact_admission = (
        "PASS"
        if request["fresh_compact_available_memory_bytes"] >= compact_required
        else "FAIL"
    )
    if admission != derived_compact_admission:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "compact_branch_derivation")
    selection = assets.schedule_selection.get((workload, admission))
    if selection is None:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "selection_row_missing")
    if request["selected_schedule_id"] != selection["selected_schedule_id"]:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "schedule_id")
    if type(request["expected_measured_repetitions"]) is not int \
            or request["expected_measured_repetitions"] != int(
                selection["expected_measured_repetitions"]
            ):
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "repetition_count")
    if request["selection_frozen_before_first_measured_result"] is not True:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "selection_not_frozen")
    if candidate not in SCHEDULES[admission][2]:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "candidate_not_in_branch")

    timeout = assets.timeouts[(workload, candidate)]
    for field in (
        "timeout_seconds", "timeout_boundary_start", "timeout_boundary_end",
        "process_tree_scope",
    ):
        expected: Any = timeout[field]
        if field == "timeout_seconds":
            expected = int(expected)
        if request[field] != expected:
            raise StopSignal("SB_STOP_TIMEOUT_CONTRACT", f"timeout_field:{field}")
    if request["expected_operation_contract"] != OPERATION_CONTRACT:
        raise StopSignal("SB_STOP_OPERATION_CONTRACT", "operation_contract")

    return {
        "status": "PRELAUNCH_PASS",
        "workload_id": workload,
        "candidate_id": candidate,
        "selected_schedule_id": request["selected_schedule_id"],
        "expected_measured_repetitions": request["expected_measured_repetitions"],
        "timeout_seconds": request["timeout_seconds"],
        "descriptor_sha256": observed_descriptor_hash,
        "source_commit": assets.source_commit,
        "source_tree": assets.source_tree,
    }


def _state_cell(row: int, column: int) -> int:
    return (row + 2 * column + 1) % 4


def _valid_cell(row: int, column: int) -> bool:
    return (row * 3 + column * 5 + 1) % 7 not in (0, 3)


def _numeric_cell(row: int, column: int) -> bytes:
    if not _valid_cell(row, column):
        return bytes(8)
    linear = row * 11 + column
    bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
    return struct.pack("<Q", bits)


class ContinuousBitDigest:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.current = 0
        self.used = 0
        self.byte_count = 0

    def feed(self, value: bool) -> None:
        if value:
            self.current |= 1 << self.used
        self.used += 1
        if self.used == 8:
            self.digest.update(bytes([self.current]))
            self.byte_count += 1
            self.current = 0
            self.used = 0

    def finish(self) -> Tuple[str, int]:
        if self.used:
            self.digest.update(bytes([self.current]))
            self.byte_count += 1
            self.current = 0
            self.used = 0
        return self.digest.hexdigest(), self.byte_count


def bounded_full_logical_scan(
        rows: int = 129,
        primitive: int = 7,
        bstar: int = 4,
        authorities: Optional[Sequence[bytes]] = None) -> Dict[str, Any]:
    """Reconstruct the exact logical SHA with one <=128-row buffer live."""
    numeric = primitive + bstar
    if (rows, primitive, bstar, numeric) != (129, 7, 4, 11):
        raise ValueError("EXEC-PREFLIGHT bounded fixture dimensions are frozen")
    if authorities is None:
        authorities = tuple(
            hashlib.sha256(f"exec-preflight-authority-{index}".encode("ascii")).digest()
            for index in range(5)
        )
    if len(authorities) != 5 or any(len(value) != 32 for value in authorities):
        raise ValueError("five 32-byte bounded authorities required")

    state_digest = hashlib.sha256()
    numeric_digest = hashlib.sha256()
    validity_digest = ContinuousBitDigest()
    component_order: List[str] = []
    block_rows_seen: List[int] = []
    max_buffer = 0

    component_order.append("STATE")
    for start in range(0, rows, FULL_SCAN_BLOCK_ROWS):
        count = min(FULL_SCAN_BLOCK_ROWS, rows - start)
        block = bytes(
            _state_cell(row, column)
            for row in range(start, start + count)
            for column in range(primitive)
        )
        max_buffer = max(max_buffer, len(block))
        block_rows_seen.append(count)
        state_digest.update(block)
        del block

    component_order.append("NUMERIC")
    for start in range(0, rows, FULL_SCAN_BLOCK_ROWS):
        count = min(FULL_SCAN_BLOCK_ROWS, rows - start)
        block = bytearray(count * numeric * 8)
        cell = 0
        for row in range(start, start + count):
            for column in range(numeric):
                if _valid_cell(row, column):
                    linear = row * 11 + column
                    bits = (
                        0x3FF0000000000000
                        | (linear & 0x000FFFFFFFFFFFFF)
                    )
                    struct.pack_into("<Q", block, cell * 8, bits)
                cell += 1
        max_buffer = max(max_buffer, len(block))
        numeric_digest.update(block)
        del block

    component_order.append("VALIDITY")
    validity_block_max = 0
    for start in range(0, rows, FULL_SCAN_BLOCK_ROWS):
        count = min(FULL_SCAN_BLOCK_ROWS, rows - start)
        # Feed directly into the continuous packer.  No unpacked full component
        # and no complete owned logical result are created.
        before = validity_digest.byte_count
        for row in range(start, start + count):
            for column in range(numeric):
                validity_digest.feed(_valid_cell(row, column))
        emitted = validity_digest.byte_count - before
        validity_block_max = max(validity_block_max, emitted + int(validity_digest.used > 0))
    validity_sha, validity_bytes = validity_digest.finish()
    max_buffer = max(max_buffer, validity_block_max)

    state_sha = state_digest.hexdigest()
    numeric_sha = numeric_digest.hexdigest()
    logical = hashlib.sha256()
    logical.update(b"SplitAlignerR/MatrixLogicalContent/v1\0")
    logical.update(struct.pack("<HHQQQQ", 1, 0, rows, primitive, bstar, numeric))
    for value in authorities:
        logical.update(value)
    lengths = (
        rows * primitive,
        rows * numeric * 8,
        (rows * numeric + 7) // 8,
    )
    for length, digest_hex in zip(
            lengths, (state_sha, numeric_sha, validity_sha)):
        logical.update(struct.pack("<Q", length))
        logical.update(bytes.fromhex(digest_hex))
    selected_buffer = max(
        min(rows, FULL_SCAN_BLOCK_ROWS) * primitive,
        min(rows, FULL_SCAN_BLOCK_ROWS) * numeric * 8,
        (min(rows, FULL_SCAN_BLOCK_ROWS) * numeric + 7) // 8,
    )
    return {
        "algorithm": "BOUNDED_FULL_LOGICAL_SCAN_V1",
        "rows": rows,
        "primitive_count": primitive,
        "bstar_count": bstar,
        "numeric_coordinate_count": numeric,
        "component_order": component_order,
        "maximum_logical_block_rows": max(block_rows_seen),
        "logical_block_row_sequence": block_rows_seen,
        "state_stream_sha256": state_sha,
        "numeric_stream_sha256": numeric_sha,
        "validity_stream_sha256": validity_sha,
        "validity_stream_bytes": validity_bytes,
        "logical_content_sha256": logical.hexdigest(),
        "actual_max_live_scan_buffer_bytes": max_buffer,
        "planner_selected_component_buffer_bytes": selected_buffer,
        "planner_validity_carry_bytes": VALIDITY_CARRY_CHARGE_BYTES,
        "planner_hash_context_bytes": HASH_CONTEXT_CHARGE_BYTES,
        "planner_live_scan_bytes": (
            selected_buffer + VALIDITY_CARRY_CHARGE_BYTES
            + HASH_CONTEXT_CHARGE_BYTES
        ),
        "complete_owned_logical_result_bytes": 0,
        "r_materialization_bytes": 0,
    }


def build_decision_input(
        workload_selections: Mapping[str, Mapping[str, Any]],
        samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build exact integer-token input from complete file-candidate samples."""
    if set(workload_selections) != set(WORKLOADS):
        raise StrictJSONError("decision builder workload-selection key set mismatch")
    selections: Dict[str, Dict[str, Any]] = {}
    expected_counts: Dict[str, int] = {}
    for workload in WORKLOADS:
        value = workload_selections[workload]
        required = {
            "selected_schedule_id", "compact_admission_result",
            "expected_measured_repetitions",
            "selection_frozen_before_first_measured_result",
        }
        if set(value) != required:
            raise StrictJSONError(f"decision builder selection field set: {workload}")
        admission = value["compact_admission_result"]
        if admission not in SCHEDULES:
            raise StrictJSONError(f"decision builder compact branch: {workload}")
        schedule_id, count, _candidates = SCHEDULES[admission]
        if value["selected_schedule_id"] != schedule_id \
                or value["expected_measured_repetitions"] != count \
                or value["selection_frozen_before_first_measured_result"] is not True:
            raise StrictJSONError(f"decision builder schedule mismatch: {workload}")
        selections[workload] = {
            **dict(value),
            "selected_schedule_completion_status": (
                "COMPLETE_NO_MISSING_DUPLICATE_REUSED_OR_ADAPTIVE_SAMPLE"
            ),
        }
        expected_counts[workload] = count

    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for sample in samples:
        if sample.get("schema") != WORKER_RESULT_SCHEMA:
            raise StrictJSONError("worker-result schema mismatch")
        if sample.get("evidence_mode") != BOUNDED_MODE \
                or sample.get("decision_authority") is not False:
            raise StrictJSONError("bounded sample was presented as decision authority")
        candidate = sample.get("candidate_id")
        workload = sample.get("workload_id")
        if candidate not in FILE_CANDIDATES or workload not in WORKLOADS:
            continue
        grouped.setdefault((candidate, workload), []).append(sample)

    candidates: Dict[str, Any] = {}
    for candidate in FILE_CANDIDATES:
        workload_values: Dict[str, Any] = {}
        for workload in WORKLOADS:
            values = sorted(
                grouped.get((candidate, workload), []),
                key=lambda item: item["measured_repetition"],
            )
            count = expected_counts[workload]
            if len(values) != count \
                    or [item["measured_repetition"] for item in values] \
                    != list(range(1, count + 1)):
                raise StrictJSONError(
                    f"decision builder incomplete series: {candidate}:{workload}"
                )
            schedule_id = selections[workload]["selected_schedule_id"]
            if any(item["selected_schedule_id"] != schedule_id for item in values):
                raise StrictJSONError(
                    f"decision builder sample schedule mismatch: {candidate}:{workload}"
                )
            lifecycle = []
            for item in values:
                phases = item.get("synthetic_integer_metrics", {}).get("lifecycle")
                if not isinstance(phases, dict) or set(phases) != set(PHASES) \
                        or not all(positive_int64(value) for value in phases.values()):
                    raise StrictJSONError(
                        f"decision builder invalid lifecycle integer: {candidate}:{workload}"
                    )
                lifecycle.append({phase: phases[phase] for phase in PHASES})
            def series(field: str) -> List[int]:
                output = [
                    item.get("synthetic_integer_metrics", {}).get(field)
                    for item in values
                ]
                if not all(positive_int64(value) for value in output):
                    raise StrictJSONError(
                        f"decision builder invalid raw integer: {candidate}:{workload}:{field}"
                    )
                return output
            workload_values[workload] = {
                "hard_gate_status": "PASS_ALL_REQUIRED_HARD_GATES",
                "schedule_completion_status": "COMPLETE_EXACT_SELECTED_SCHEDULE",
                "selected_schedule_id": schedule_id,
                "lifecycle_repetitions": lifecycle,
                "peak_rss_repetitions": series("peak_rss_repetitions"),
                "publication_highwater_repetitions": series(
                    "publication_highwater_repetitions"
                ),
                "column_extraction_repetitions": series(
                    "column_extraction_repetitions"
                ),
                "full_logical_scan_repetitions": series(
                    "full_logical_scan_repetitions"
                ),
            }
        candidates[candidate] = {
            "eligible_every_mandatory_workload": True,
            "workloads": workload_values,
        }
    output = {
        "schema": DECISION_INPUT_SCHEMA,
        "mandatory_workloads": list(WORKLOADS),
        "workload_schedule_selection": selections,
        "candidates": candidates,
    }
    # A canonical round-trip proves integer tokens survive transport and that
    # the strict verifier accepts exactly what the builder emits.
    if strict_json_loads(canonical_json_bytes(output)) != output:
        raise StrictJSONError("canonical decision-input round-trip mismatch")
    return output
