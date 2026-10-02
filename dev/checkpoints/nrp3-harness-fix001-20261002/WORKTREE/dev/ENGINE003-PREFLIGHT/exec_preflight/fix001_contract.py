#!/usr/bin/env python3
"""Object-bound contracts for ENGINE003-STAGEB-EXEC-PREFLIGHT001-FIX001.

The module deliberately has no package or third-party dependencies.  It binds
the executing checkout to an authorized Git commit/tree, reads every accepted
Stage-B preregistration artifact from the frozen Git object (never from the
working tree), validates a complete launch tuple before process creation, and
builds decision input only from an exact frozen schedule replay.

This is a bounded control-plane contract.  It does not authorize Stage-B
timing, large allocation, backend selection, or production package changes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


FROZEN_PREREG_COMMIT = "cb19320b9d07f8b96dc5339f7df4e3e855d92d89"
FROZEN_PREREG_TREE = "915e9062329a36e1c6de9443460a5471504d5737"
PROTECTED_ROOT = "dev/ENGINE003-PREFLIGHT"

WORKLOADS = (
    "authority_current_2275x1086",
    "stress_projected_100000x4913",
    "stress_all_layouts_over4gib_102500x4913",
)
FILE_CANDIDATES = (
    "ROW_MAJOR_DISK", "COLUMN_MAJOR_DISK", "TILED_DISK",
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
    "allocation_initialization", "row_construction", "finalization",
    "bounded_validation",
)
HASH_FIELDS = (
    "complete_descriptor_sha256", "species_authority_sha256",
    "gene_registry_sha256", "primitive_registry_sha256",
    "bstar_registry_sha256", "numeric_coordinate_registry_sha256",
    "state_stream_sha256", "numeric_stream_sha256",
    "validity_stream_sha256", "logical_content_sha256",
)

LIVE_SCHEMA = "SplitAlignerR/ENGINE003StageBLiveLaunchRequest/v2"
TEST_SCHEMA = "SplitAlignerR/ENGINE003StageBTestFaultRequest/v1"
WORKER_RESULT_SCHEMA = "SplitAlignerR/ENGINE003StageBBoundedRealWorkerResult/v2"
DECISION_INPUT_SCHEMA = "SplitAlignerR/ENGINE003StageBDecisionInputExact/v1"
BOUNDED_MODE = "BOUNDED_REAL_BACKEND_EXEC_PREFLIGHT_NO_BENCHMARK"
FIXTURE_ID = "EXEC_PREFLIGHT_REAL_129x7x4_V1"
OPERATION_CONTRACT = "STAGEB_SAMPLE_ALL_19_METRICS_REAL_BOUNDED_BACKEND_V2"
MAX_INT64 = 2 ** 63 - 1

AUTHORITY_PATHS = {
    "workload_ledger": "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_WORKLOAD_LEDGER.tsv",
    "candidate_projections": "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_CANDIDATE_PROJECTIONS.tsv",
    "candidate_set": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_CANDIDATE_SET.tsv",
    "schedule_selection": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_WORKLOAD_SCHEDULE_SELECTION_CONTRACT.tsv",
    "execution_schedule": "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_EXECUTION_SCHEDULE.tsv",
    "warmup_schedule": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_WARMUP_SCHEDULE.tsv",
    "timeout_contract": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_TIMEOUT_CONTRACT.tsv",
    "metric_contract": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_METRIC_CONTRACT.tsv",
    "decision_rule": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_DECISION_RULE.json",
    "numeric_contract": "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_DECISION_INPUT_NUMERIC_CONTRACT.json",
    "authority_descriptor": "dev/ENGINE003-PREFLIGHT/fixtures/stage_a_v3_descriptors/authority_shape.json",
    "stress_descriptor": "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_prereg001/stress_projected_100000x4913.json",
    "over4gib_descriptor": "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_prereg001/stress_all_layouts_over4gib_102500x4913.json",
}
AUTHORITY_SHA256 = {
    "workload_ledger": "95d61f21f334d8374c66839aeb76d0f4ffbcd4af9f38fb57b9279c760005e686",
    "candidate_projections": "a7c4f8512d0237ef43ff81bd074443cf4137c1a36bab6412877ecc23ae56a7f4",
    "candidate_set": "2a6972f473b9f2314a663feac175674cc48d41c204e2d1b78fb27728033c622e",
    "schedule_selection": "5d254a057d6d43414e0c48502f69583cc2a5131e61864675c73e490b927620d2",
    "execution_schedule": "790dab786a246e7425ed4b3d7ba8c5eef3e264b64d07033158d1067805b33ddd",
    "warmup_schedule": "0c28acb6775185fc3b43c5362a1a809fdda271dc95e6d318430c583c959f6818",
    "timeout_contract": "7329d6beede77345e1d7b74631e11afa1b26d008c6bc858b649c233b4fe2363a",
    "metric_contract": "b0885cbd355af6fb200e8ae05669ba90e2c245653701813eb22b5bfceb8dc4c1",
    "decision_rule": "22543d5c344aff46309a03842473ba569153875914637b50e942daee775d7a3d",
    "numeric_contract": "551d3574527ced99c15088c66921d784a0e52f562e9a76db816f416d7cb16d0d",
    "authority_descriptor": "3d2b5b5ff45e053d463978684df16633ad540ee225edc47ab0fbd7510a188fed",
    "stress_descriptor": "e54c733e4d1c07e2aee001c1c5d8effeba516279ae602c0e29f85536bad2f7a1",
    "over4gib_descriptor": "1b22c00a360ca420c347fa81869d0ba3c7f53c7b5c33356c6dc4e5127ef79291",
}


class StrictJSONError(ValueError):
    pass


class ContractError(ValueError):
    pass


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
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text, object_pairs_hook=_unique_object,
            parse_float=_reject_float, parse_constant=_reject_constant,
        )
    except StrictJSONError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise StrictJSONError(f"invalid JSON transport: {error}") from error


def strict_json_load(path: Path) -> Any:
    return strict_json_loads(path.read_bytes())


def _validate_json_tree(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, str) or type(value) in (bool, int):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_tree(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictJSONError(f"non-string key at {path}")
            _validate_json_tree(item, f"{path}.{key}")
        return
    raise StrictJSONError(f"non-integer/non-JSON scalar at {path}")


def canonical_json_bytes(value: Any) -> bytes:
    _validate_json_tree(value)
    return (json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ) + "\n").encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def positive_int64(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_INT64


def _git(repo: Path, *arguments: str, binary: bool = False) -> Any:
    process = subprocess.run(
        ["git", "-C", str(repo), *arguments], capture_output=True,
        text=not binary, check=False,
    )
    if process.returncode != 0:
        stderr = process.stderr if isinstance(process.stderr, str) else process.stderr.decode("utf-8", "replace")
        raise ContractError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
    return process.stdout


def _valid_oid(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


class ExecutionAuthority:
    """Observed Git identity and tracked-clean proof for the actual checkout."""

    def __init__(self, repo_root: Path, authorized_commit: str, authorized_tree: str):
        self.repo_root = repo_root.resolve()
        if not _valid_oid(authorized_commit) or not _valid_oid(authorized_tree):
            raise StopSignal("SB_STOP_SOURCE_IDENTITY", "authorization_oid_format")
        try:
            actual_commit = _git(self.repo_root, "rev-parse", "--verify", "HEAD").strip()
            actual_tree = _git(self.repo_root, "rev-parse", "--verify", "HEAD^{tree}").strip()
            prereg_tree = _git(
                self.repo_root, "rev-parse", "--verify",
                f"{FROZEN_PREREG_COMMIT}^{{tree}}",
            ).strip()
        except ContractError as error:
            raise StopSignal("SB_STOP_SOURCE_IDENTITY", str(error)) from error
        if prereg_tree != FROZEN_PREREG_TREE:
            raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "prereg_commit_tree_mismatch")
        if actual_commit != authorized_commit or actual_tree != authorized_tree:
            raise StopSignal(
                "SB_STOP_SOURCE_IDENTITY",
                f"actual={actual_commit}/{actual_tree};authorized={authorized_commit}/{authorized_tree}",
            )
        try:
            dirty = _git(
                self.repo_root, "status", "--porcelain=v1",
                "--untracked-files=no", "--", PROTECTED_ROOT,
            ).strip()
        except ContractError as error:
            raise StopSignal("SB_STOP_SOURCE_IDENTITY", str(error)) from error
        if dirty:
            first = dirty.splitlines()[0]
            raise StopSignal("SB_STOP_EXECUTION_SOURCE_DIRTY", first)
        self.commit = actual_commit
        self.tree = actual_tree
        self.prereg_commit = FROZEN_PREREG_COMMIT
        self.prereg_tree = prereg_tree

    def frozen_bytes(self, key: str) -> bytes:
        path = AUTHORITY_PATHS[key]
        try:
            raw = _git(
                self.repo_root, "show", f"{FROZEN_PREREG_COMMIT}:{path}",
                binary=True,
            )
        except ContractError as error:
            raise StopSignal("SB_STOP_FROZEN_AUTHORITY", f"{key}:{error}") from error
        observed = hashlib.sha256(raw).hexdigest()
        if observed != AUTHORITY_SHA256[key]:
            raise StopSignal(
                "SB_STOP_FROZEN_AUTHORITY",
                f"{key}:sha256:{observed}!={AUTHORITY_SHA256[key]}",
            )
        return raw

    def proof(self) -> Dict[str, Any]:
        return {
            "actual_execution_commit": self.commit,
            "actual_execution_tree": self.tree,
            "tracked_execution_contract_clean": True,
            "protected_root": PROTECTED_ROOT,
            "frozen_prereg_commit": self.prereg_commit,
            "frozen_prereg_tree": self.prereg_tree,
            "authority_load_mode": "GIT_SHOW_EXACT_FROZEN_OBJECT_PLUS_SHA256_MANIFEST",
        }


def _tsv(raw: bytes) -> List[Dict[str, str]]:
    text = raw.decode("utf-8", errors="strict")
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter="\t"))


def _unique(rows: Iterable[Dict[str, str]], key: str) -> Dict[str, Dict[str, str]]:
    output: Dict[str, Dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value or value in output:
            raise ContractError(f"missing/duplicate TSV key {key}={value!r}")
        output[value] = row
    return output


def _unique_pair(rows: Iterable[Dict[str, str]], left: str, right: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    output: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        key = (row.get(left, ""), row.get(right, ""))
        if not all(key) or key in output:
            raise ContractError(f"missing/duplicate TSV pair {key!r}")
        output[key] = row
    return output


class FrozenAssets:
    """Accepted preregistration data read only from cb19320's object tree."""

    def __init__(self, authority: ExecutionAuthority):
        self.authority = authority
        self.repo_root = authority.repo_root
        self.source_commit = authority.commit
        self.source_tree = authority.tree
        self.raw = {key: authority.frozen_bytes(key) for key in AUTHORITY_PATHS}
        self.workloads = _unique(_tsv(self.raw["workload_ledger"]), "workload_id")
        self.projections = _unique_pair(
            _tsv(self.raw["candidate_projections"]), "workload_id", "backend",
        )
        self.candidates = _unique(_tsv(self.raw["candidate_set"]), "candidate_id")
        self.schedule_selection = _unique_pair(
            _tsv(self.raw["schedule_selection"]), "workload_id",
            "compact_admission_result",
        )
        self.execution_schedule = _tsv(self.raw["execution_schedule"])
        self.warmup_schedule = _tsv(self.raw["warmup_schedule"])
        self.timeouts = _unique_pair(
            _tsv(self.raw["timeout_contract"]), "workload_id", "candidate_id",
        )
        self.metrics = _unique(_tsv(self.raw["metric_contract"]), "metric_id")
        self.decision_rule = strict_json_loads(self.raw["decision_rule"])
        self.numeric_contract = strict_json_loads(self.raw["numeric_contract"])
        self._validate()

    def _validate(self) -> None:
        if tuple(self.workloads) != WORKLOADS:
            raise ContractError("frozen workload order mismatch")
        if set(self.candidates) != set(ALL_CANDIDATES):
            raise ContractError("frozen candidate set mismatch")
        if len(self.projections) != 12 or len(self.timeouts) != 12 or len(self.metrics) != 19:
            raise ContractError("frozen projection/timeout/metric cardinality mismatch")
        if len(self.execution_schedule) != 150:
            raise ContractError("frozen execution schedule cardinality mismatch")
        if len(self.warmup_schedule) != 21:
            raise ContractError("frozen warmup schedule cardinality mismatch")
        seen = set()
        for row in self.execution_schedule:
            key = (
                row["workload_id"], row["schedule_id"],
                int(row["measured_repetition"]), int(row["position"]),
            )
            if key in seen:
                raise ContractError(f"duplicate frozen schedule tuple {key}")
            seen.add(key)
        for workload in WORKLOADS:
            descriptor_path = self.workloads[workload]["complete_descriptor_path"]
            descriptor_key = {
                AUTHORITY_PATHS["authority_descriptor"]: "authority_descriptor",
                AUTHORITY_PATHS["stress_descriptor"]: "stress_descriptor",
                AUTHORITY_PATHS["over4gib_descriptor"]: "over4gib_descriptor",
            }.get(descriptor_path)
            if descriptor_key is None:
                raise ContractError(f"unbound descriptor path {descriptor_path}")
            if hashlib.sha256(self.raw[descriptor_key]).hexdigest() != self.workloads[workload]["complete_descriptor_sha256"]:
                raise ContractError(f"descriptor hash/ledger mismatch {workload}")

    def anchor(self, workload: str) -> Dict[str, str]:
        return {field: self.workloads[workload][field] for field in HASH_FIELDS}

    def schedule_rows(self, workload: str, schedule_id: str) -> List[Dict[str, str]]:
        return sorted([
            row for row in self.execution_schedule
            if row["workload_id"] == workload and row["schedule_id"] == schedule_id
        ], key=lambda row: (int(row["measured_repetition"]), int(row["position"])))

    def schedule_row(self, workload: str, schedule_id: str, repetition: int, position: int) -> Dict[str, str]:
        matches = [row for row in self.execution_schedule if (
            row["workload_id"] == workload
            and row["schedule_id"] == schedule_id
            and int(row["measured_repetition"]) == repetition
            and int(row["position"]) == position
        )]
        if len(matches) != 1:
            raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "missing_or_duplicate_schedule_row")
        return matches[0]

    def warmup_rows(self, workload: str, compact_admission: str) -> List[Dict[str, str]]:
        condition = {
            "PASS": "COMPACT_PASSES_FRESH_ADMISSION",
            "FAIL": "COMPACT_FAILS_FRESH_ADMISSION",
        }.get(compact_admission)
        if condition is None:
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "warmup_admission")
        rows = sorted([
            row for row in self.warmup_schedule
            if row["workload_id"] == workload
            and row["selection_condition"] == condition
        ], key=lambda row: int(row["warmup_position"]))
        expected = 4 if compact_admission == "PASS" else 3
        if len(rows) != expected or [int(row["warmup_position"]) for row in rows] != list(range(1, expected + 1)):
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "warmup_rows")
        return rows


LIVE_FIELDS = {
    "schema", "execution_mode", "workload_id", "candidate_id", "layout_id",
    "source_commit", "source_tree", "frozen_prereg_commit",
    "frozen_prereg_tree", "descriptor_relative_path", "descriptor_sha256",
    "anchor", "fresh_memory_admission", "fresh_available_memory_bytes",
    "memory_admission_required_bytes", "projected_peak_rss_bound_bytes",
    "fresh_compact_available_memory_bytes",
    "compact_memory_admission_required_bytes", "fresh_disk_admission",
    "fresh_available_disk_bytes", "disk_admission_required_bytes",
    "publication_high_water_bound_bytes", "fresh_resource_capture_id",
    "physical_allocation_no_hole_capability", "allocation_capability_evidence_id",
    "durability_capability", "durability_capability_evidence_id",
    "compact_admission_result", "selected_schedule_id",
    "expected_measured_repetitions", "selection_frozen_before_first_measured_result",
    "measured_repetition", "schedule_position", "schedule_row_sha256",
    "timeout_seconds", "timeout_boundary_start", "timeout_boundary_end",
    "process_tree_scope", "expected_operation_contract", "bounded_fixture_id",
    "runtime_target",
}


def _schedule_row_sha(row: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest()


def make_live_request(
        assets: FrozenAssets, workload_id: str, candidate_id: str,
        compact_admission_result: str, repetition: int, position: int,
        runtime_target: Path) -> Dict[str, Any]:
    selection = assets.schedule_selection[(workload_id, compact_admission_result)]
    schedule_id = selection["selected_schedule_id"]
    row = assets.schedule_row(workload_id, schedule_id, repetition, position)
    if row["backend"] != candidate_id:
        raise ContractError("builder candidate does not match frozen schedule row")
    timeout = assets.timeouts[(workload_id, candidate_id)]
    workload = assets.workloads[workload_id]
    projection = assets.projections[(workload_id, candidate_id)]
    compact_projection = assets.projections[(workload_id, "COMPACT_IN_MEMORY")]
    memory_required = int(projection["memory_admission_required_bytes"])
    compact_required = int(compact_projection["memory_admission_required_bytes"])
    disk_required = int(projection["disk_admission_required_bytes"])
    compact = candidate_id == "COMPACT_IN_MEMORY"
    return {
        "schema": LIVE_SCHEMA,
        "execution_mode": BOUNDED_MODE,
        "workload_id": workload_id,
        "candidate_id": candidate_id,
        "layout_id": LAYOUTS[candidate_id],
        "source_commit": assets.source_commit,
        "source_tree": assets.source_tree,
        "frozen_prereg_commit": FROZEN_PREREG_COMMIT,
        "frozen_prereg_tree": FROZEN_PREREG_TREE,
        "descriptor_relative_path": workload["complete_descriptor_path"],
        "descriptor_sha256": workload["complete_descriptor_sha256"],
        "anchor": assets.anchor(workload_id),
        "fresh_memory_admission": "PASS",
        "fresh_available_memory_bytes": memory_required,
        "memory_admission_required_bytes": memory_required,
        "projected_peak_rss_bound_bytes": int(projection["projected_peak_rss_before_reserve_bytes"]),
        "fresh_compact_available_memory_bytes": compact_required if compact_admission_result == "PASS" else compact_required - 1,
        "compact_memory_admission_required_bytes": compact_required,
        "fresh_disk_admission": "NOT_APPLICABLE" if compact else "PASS",
        "fresh_available_disk_bytes": 0 if compact else disk_required,
        "disk_admission_required_bytes": disk_required,
        "publication_high_water_bound_bytes": int(projection["publication_high_water_bytes"]),
        "fresh_resource_capture_id": "BOUNDED_REAL_RESOURCE_CAPTURE_V2",
        "physical_allocation_no_hole_capability": "NOT_APPLICABLE" if compact else "PASS",
        "allocation_capability_evidence_id": "NOT_APPLICABLE" if compact else "BOUNDED_REAL_NO_HOLE_V2",
        "durability_capability": "NOT_APPLICABLE" if compact else "PASS",
        "durability_capability_evidence_id": "NOT_APPLICABLE" if compact else "BOUNDED_REAL_DURABLE_PUBLISH_V2",
        "compact_admission_result": compact_admission_result,
        "selected_schedule_id": schedule_id,
        "expected_measured_repetitions": int(selection["expected_measured_repetitions"]),
        "selection_frozen_before_first_measured_result": True,
        "measured_repetition": repetition,
        "schedule_position": position,
        "schedule_row_sha256": _schedule_row_sha(row),
        "timeout_seconds": int(timeout["timeout_seconds"]),
        "timeout_boundary_start": timeout["timeout_boundary_start"],
        "timeout_boundary_end": timeout["timeout_boundary_end"],
        "process_tree_scope": timeout["process_tree_scope"],
        "expected_operation_contract": OPERATION_CONTRACT,
        "bounded_fixture_id": FIXTURE_ID,
        "runtime_target": str(runtime_target.resolve()),
    }


def validate_live_request_shape(request: Mapping[str, Any]) -> None:
    if set(request) != LIVE_FIELDS:
        extra = sorted(set(request) - LIVE_FIELDS)
        missing = sorted(LIVE_FIELDS - set(request))
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", f"extra={extra};missing={missing}")
    if request["schema"] != LIVE_SCHEMA or request["execution_mode"] != BOUNDED_MODE:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "schema_or_mode")


def prelaunch_guard(assets: FrozenAssets, request: Mapping[str, Any], runtime_root: Path) -> Dict[str, Any]:
    validate_live_request_shape(request)
    if request["source_commit"] != assets.source_commit or request["source_tree"] != assets.source_tree:
        raise StopSignal("SB_STOP_SOURCE_IDENTITY", "request_source_mismatch")
    if request["frozen_prereg_commit"] != FROZEN_PREREG_COMMIT or request["frozen_prereg_tree"] != FROZEN_PREREG_TREE:
        raise StopSignal("SB_STOP_FROZEN_AUTHORITY", "request_prereg_identity_mismatch")
    workload = request["workload_id"]
    candidate = request["candidate_id"]
    if workload not in assets.workloads or candidate not in assets.candidates:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "unknown_workload_or_candidate")
    if type(request["measured_repetition"]) is not int or type(request["schedule_position"]) is not int:
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "non_integer_repetition_or_position")
    schedule_row = assets.schedule_row(
        workload, request["selected_schedule_id"],
        request["measured_repetition"], request["schedule_position"],
    )
    if schedule_row["backend"] != candidate or request["schedule_row_sha256"] != _schedule_row_sha(schedule_row):
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "candidate_or_row_hash_mismatch")
    if schedule_row["fresh_process"] != "TRUE" or schedule_row["fresh_target"] != "TRUE":
        raise StopSignal("SB_STOP_SCHEDULE_TUPLE", "fresh_process_or_target_contract")
    if request["layout_id"] != LAYOUTS[candidate]:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "candidate_layout_mismatch")
    if not isinstance(request["runtime_target"], str):
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "runtime_target_type")
    target = Path(request["runtime_target"])
    try:
        target.resolve().relative_to(runtime_root.resolve())
    except (ValueError, OSError) as error:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "runtime_target_escape") from error
    if target.exists():
        raise StopSignal("SB_STOP_CLEANUP", "fresh_target_already_exists")
    workload_row = assets.workloads[workload]
    if request["descriptor_relative_path"] != workload_row["complete_descriptor_path"] or request["descriptor_sha256"] != workload_row["complete_descriptor_sha256"]:
        raise StopSignal("SB_STOP_HASH_MISMATCH", "descriptor_identity")
    if request["anchor"] != assets.anchor(workload):
        raise StopSignal("SB_STOP_HASH_MISMATCH", "anchor_identity")
    projection = assets.projections[(workload, candidate)]
    memory_required = int(projection["memory_admission_required_bytes"])
    if request["memory_admission_required_bytes"] != memory_required or request["projected_peak_rss_bound_bytes"] != int(projection["projected_peak_rss_before_reserve_bytes"]):
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "memory_projection")
    if type(request["fresh_available_memory_bytes"]) is not int or request["fresh_available_memory_bytes"] < memory_required or request["fresh_memory_admission"] != "PASS":
        raise StopSignal("SB_STOP_ADMISSION_MEMORY", "fresh_memory_admission")
    compact = candidate == "COMPACT_IN_MEMORY"
    expected_capability = "NOT_APPLICABLE" if compact else "PASS"
    disk_required = int(projection["disk_admission_required_bytes"])
    if request["disk_admission_required_bytes"] != disk_required or request["publication_high_water_bound_bytes"] != int(projection["publication_high_water_bytes"]):
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "disk_projection")
    if compact:
        if request["fresh_disk_admission"] != "NOT_APPLICABLE" or request["fresh_available_disk_bytes"] != 0:
            raise StopSignal("SB_STOP_ADMISSION_DISK", "compact_disk_contract")
    elif type(request["fresh_available_disk_bytes"]) is not int or request["fresh_available_disk_bytes"] < disk_required or request["fresh_disk_admission"] != "PASS":
        raise StopSignal("SB_STOP_ADMISSION_DISK", "fresh_disk_admission")
    if request["fresh_resource_capture_id"] != "BOUNDED_REAL_RESOURCE_CAPTURE_V2":
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "resource_capture_identity")
    if request["physical_allocation_no_hole_capability"] != expected_capability or request["durability_capability"] != expected_capability:
        raise StopSignal("SB_STOP_CAPABILITY", "allocation_or_durability")
    expected_allocation = "NOT_APPLICABLE" if compact else "BOUNDED_REAL_NO_HOLE_V2"
    expected_durability = "NOT_APPLICABLE" if compact else "BOUNDED_REAL_DURABLE_PUBLISH_V2"
    if request["allocation_capability_evidence_id"] != expected_allocation or request["durability_capability_evidence_id"] != expected_durability:
        raise StopSignal("SB_STOP_CAPABILITY", "capability_evidence_identity")
    admission = request["compact_admission_result"]
    if admission not in SCHEDULES or candidate not in SCHEDULES[admission][2]:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "branch_candidate")
    compact_required = int(assets.projections[(workload, "COMPACT_IN_MEMORY")]["memory_admission_required_bytes"])
    if type(request["fresh_compact_available_memory_bytes"]) is not int:
        raise StopSignal("SB_STOP_PROJECTION_DRIFT", "compact_available_memory_type")
    observed_compact = "PASS" if request["fresh_compact_available_memory_bytes"] >= compact_required else "FAIL"
    selection = assets.schedule_selection.get((workload, admission))
    if request["compact_memory_admission_required_bytes"] != compact_required or observed_compact != admission or selection is None:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "compact_branch_derivation")
    if request["selected_schedule_id"] != selection["selected_schedule_id"] or request["expected_measured_repetitions"] != int(selection["expected_measured_repetitions"]) or request["selection_frozen_before_first_measured_result"] is not True:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "schedule_selection")
    timeout = assets.timeouts[(workload, candidate)]
    for field in ("timeout_seconds", "timeout_boundary_start", "timeout_boundary_end", "process_tree_scope"):
        expected: Any = int(timeout[field]) if field == "timeout_seconds" else timeout[field]
        if request[field] != expected:
            raise StopSignal("SB_STOP_TIMEOUT_CONTRACT", field)
    if request["expected_operation_contract"] != OPERATION_CONTRACT or request["bounded_fixture_id"] != FIXTURE_ID:
        raise StopSignal("SB_STOP_OPERATION_CONTRACT", "operation_or_fixture")
    return {
        "status": "PRELAUNCH_PASS", "source": assets.authority.proof(),
        "schedule_tuple": {
            "workload_id": workload, "candidate_id": candidate,
            "schedule_id": request["selected_schedule_id"],
            "measured_repetition": request["measured_repetition"],
            "schedule_position": request["schedule_position"],
            "schedule_row_sha256": request["schedule_row_sha256"],
        },
    }


def make_test_fault_request(live_request: Mapping[str, Any], fault_id: str, fault_value: Any) -> Dict[str, Any]:
    return {
        "schema": TEST_SCHEMA, "live_request": dict(live_request),
        "fault_id": fault_id, "fault_value": fault_value,
    }


def validate_test_fault_request(value: Mapping[str, Any]) -> None:
    if set(value) != {"schema", "live_request", "fault_id", "fault_value"} or value.get("schema") != TEST_SCHEMA:
        raise StrictJSONError("invalid test-only fault envelope")


def selection_values(admission: str) -> Dict[str, Dict[str, Any]]:
    schedule_id, count, _ = SCHEDULES[admission]
    return {workload: {
        "selected_schedule_id": schedule_id,
        "compact_admission_result": admission,
        "expected_measured_repetitions": count,
        "selection_frozen_before_first_measured_result": True,
    } for workload in WORKLOADS}


def build_decision_input(assets: FrozenAssets, workload_selections: Mapping[str, Mapping[str, Any]], samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if set(workload_selections) != set(WORKLOADS):
        raise StrictJSONError("decision workload-selection key set mismatch")
    expected_tuples = set()
    selections: Dict[str, Dict[str, Any]] = {}
    expected_counts: Dict[str, int] = {}
    for workload in WORKLOADS:
        value = workload_selections[workload]
        required = {"selected_schedule_id", "compact_admission_result", "expected_measured_repetitions", "selection_frozen_before_first_measured_result"}
        if set(value) != required:
            raise StrictJSONError(f"decision selection fields:{workload}")
        admission = value["compact_admission_result"]
        if admission not in SCHEDULES:
            raise StrictJSONError(f"decision admission:{workload}")
        schedule_id, count, candidates = SCHEDULES[admission]
        frozen = assets.schedule_selection[(workload, admission)]
        if value["selected_schedule_id"] != schedule_id or schedule_id != frozen["selected_schedule_id"] or value["expected_measured_repetitions"] != count or count != int(frozen["expected_measured_repetitions"]) or value["selection_frozen_before_first_measured_result"] is not True:
            raise StrictJSONError(f"decision schedule mismatch:{workload}")
        rows = assets.schedule_rows(workload, schedule_id)
        if len(rows) != count * len(candidates):
            raise StrictJSONError(f"decision frozen schedule incomplete:{workload}")
        for row in rows:
            expected_tuples.add((workload, schedule_id, int(row["measured_repetition"]), int(row["position"]), row["backend"], _schedule_row_sha(row)))
        selections[workload] = {**dict(value), "selected_schedule_completion_status": "COMPLETE_EXACT_FROZEN_SCHEDULE"}
        expected_counts[workload] = count

    observed_tuples = []
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for sample in samples:
        if sample.get("schema") != WORKER_RESULT_SCHEMA or sample.get("evidence_mode") != BOUNDED_MODE or sample.get("decision_authority") is not False:
            raise StrictJSONError("decision worker-result identity")
        value = (
            sample.get("workload_id"), sample.get("selected_schedule_id"),
            sample.get("measured_repetition"), sample.get("schedule_position"),
            sample.get("candidate_id"), sample.get("schedule_row_sha256"),
        )
        observed_tuples.append(value)
        candidate = sample.get("candidate_id")
        workload = sample.get("workload_id")
        if candidate in FILE_CANDIDATES and workload in WORKLOADS:
            grouped.setdefault((candidate, workload), []).append(sample)
    if len(observed_tuples) != len(set(observed_tuples)):
        raise StrictJSONError("decision duplicate schedule row")
    if set(observed_tuples) != expected_tuples:
        missing = len(expected_tuples - set(observed_tuples))
        extra = len(set(observed_tuples) - expected_tuples)
        raise StrictJSONError(f"decision schedule tuple mismatch:missing={missing};extra={extra}")

    candidates: Dict[str, Any] = {}
    for candidate in FILE_CANDIDATES:
        workload_values: Dict[str, Any] = {}
        for workload in WORKLOADS:
            values = sorted(grouped[(candidate, workload)], key=lambda item: item["measured_repetition"])
            count = expected_counts[workload]
            if len(values) != count or [item["measured_repetition"] for item in values] != list(range(1, count + 1)):
                raise StrictJSONError(f"decision incomplete series:{candidate}:{workload}")
            lifecycle = []
            for item in values:
                phases = item.get("integer_metrics", {}).get("lifecycle")
                if not isinstance(phases, dict) or set(phases) != set(PHASES) or not all(positive_int64(value) for value in phases.values()):
                    raise StrictJSONError(f"decision lifecycle integer:{candidate}:{workload}")
                lifecycle.append({phase: phases[phase] for phase in PHASES})
            def series(field: str) -> List[int]:
                output = [item.get("integer_metrics", {}).get(field) for item in values]
                if not all(positive_int64(value) for value in output):
                    raise StrictJSONError(f"decision integer:{candidate}:{workload}:{field}")
                return output
            workload_values[workload] = {
                "hard_gate_status": "PASS_ALL_REQUIRED_HARD_GATES",
                "schedule_completion_status": "COMPLETE_EXACT_SELECTED_SCHEDULE",
                "selected_schedule_id": selections[workload]["selected_schedule_id"],
                "lifecycle_repetitions": lifecycle,
                "peak_rss_repetitions": series("peak_rss_repetitions"),
                "publication_highwater_repetitions": series("publication_highwater_repetitions"),
                "column_extraction_repetitions": series("column_extraction_repetitions"),
                "full_logical_scan_repetitions": series("full_logical_scan_repetitions"),
            }
        candidates[candidate] = {"eligible_every_mandatory_workload": True, "workloads": workload_values}
    output = {
        "schema": DECISION_INPUT_SCHEMA,
        "mandatory_workloads": list(WORKLOADS),
        "workload_schedule_selection": selections,
        "candidates": candidates,
    }
    if strict_json_loads(canonical_json_bytes(output)) != output:
        raise StrictJSONError("decision canonical round trip")
    return output
