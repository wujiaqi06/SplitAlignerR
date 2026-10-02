#!/usr/bin/env python3
"""Complete frozen Stage-B launch-plan and fresh-admission orchestrator.

The legacy complete-plan object remains a ``NO_LARGE_ALLOCATION_DRY_RUN`` and
validation authority.  Physical execution may use only the fresh-admission
protocol, which freezes the same static tuple set and binds runtime resources
at each candidate-series boundary.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from fix001_contract import (
    ALL_CANDIDATES,
    FILE_CANDIDATES,
    WORKLOADS,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_load,
    write_canonical_json,
)
from stage_b_authorization import workload_authorization
from stage_b_runtime_contract import make_large_request, prelaunch_guard


REFERENCE = Path(__file__).resolve().parent.parent / "reference"
if str(REFERENCE) not in sys.path:
    sys.path.insert(0, str(REFERENCE))


PLAN_SCHEMA = "SplitAlignerR/ENGINE003StageBCompleteExecutionPlan/v1"
DRY_RUN_MODE = "NO_LARGE_ALLOCATION_DRY_RUN"
AUTHORIZED_MODE = "EXTERNALLY_AUTHORIZED_PHYSICAL_EXECUTION"
ADAPTIVE_PROTOCOL_SCHEMA = (
    "SplitAlignerR/ENGINE003StageBFreshAdmissionExecutionProtocol/v1"
)
STATIC_WORKLOAD_PLAN_SCHEMA = (
    "SplitAlignerR/ENGINE003StageBStaticWorkloadLaunchPlan/v1"
)

PLAN_FIELDS = {
    "schema", "status", "workload_order", "workloads", "requests",
    "request_identity_sha256", "request_count", "warmup_request_count",
    "measured_request_count", "decision_input_ledger_assembled",
    "global_stop_policy",
}
REQUEST_IDENTITY_FIELDS = (
    "workload_id", "run_phase", "selected_schedule_id",
    "measured_repetition", "schedule_position", "candidate_id",
    "schedule_row_sha256", "runtime_target",
)
STATIC_REQUEST_IDENTITY_FIELDS = REQUEST_IDENTITY_FIELDS + (
    "timeout_seconds", "timeout_boundary_start", "timeout_boundary_end",
    "process_tree_scope", "metric_contract_sha256",
    "expected_operation_contract",
)
REQUEST_TUPLE_FIELDS = (
    "workload_id", "run_phase", "selected_schedule_id",
    "measured_repetition", "schedule_position", "candidate_id",
    "schedule_row_sha256",
)
RESULT_IDENTITY_FIELDS = (
    "workload_id", "candidate_id", "selected_schedule_id",
    "measured_repetition", "schedule_position", "schedule_row_sha256",
    "source_commit", "source_tree",
)


def adaptive_execution_protocol(
        authority: ExecutionAuthority, assets: FrozenAssets,
        activation: Mapping[str, Any]) -> Dict[str, Any]:
    """Close every legal schedule before launch without freezing resources.

    P09 remains a prelaunch identity gate.  P14 changes its future physical
    form from one stale request list into an exact adaptive protocol containing
    both legal branches.  Runtime captures materialize one workload at a time.
    """
    policies = [workload_authorization(assets, workload) for workload in WORKLOADS]
    identity = {
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "frozen_prereg_commit": authority.prereg_commit,
        "frozen_prereg_tree": authority.prereg_tree,
        "workload_order": list(WORKLOADS),
        "workload_policies": policies,
        "activation": dict(activation),
        "capture_cadence": {
            "workload_branch": "FRESH_IMMEDIATELY_BEFORE_EACH_WORKLOAD_BRANCH_SELECTION",
            "candidate_series": "FRESH_IMMEDIATELY_BEFORE_EACH_CANDIDATE_WORKLOAD_SERIES",
            "preservation": "CANONICAL_JSON_SHA256_REQUEST_BOUND",
        },
        "global_stop_policy": "FIRST_NON_PASS_STOPS_ALL_LATER_REQUESTS_AND_WORKLOADS",
    }
    return {
        "schema": ADAPTIVE_PROTOCOL_SCHEMA,
        "status": "COMPLETE_ADAPTIVE_PROTOCOL_FROZEN_NOT_EXECUTED",
        **identity,
        "protocol_identity_sha256": hashlib.sha256(
            canonical_json_bytes(identity)
        ).hexdigest(),
    }


def validate_adaptive_execution_protocol(
        authority: ExecutionAuthority, assets: FrozenAssets,
        protocol: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(protocol, Mapping):
        _plan_stop("adaptive_protocol_not_object")
    activation = protocol.get("activation")
    if not isinstance(activation, Mapping):
        _plan_stop("adaptive_activation")
    expected = adaptive_execution_protocol(authority, assets, activation)
    if dict(protocol) != expected:
        _plan_stop("adaptive_protocol_exact_equality")
    return expected


def _preserve_resource_capture(
        evidence_root: Path, ordinal: int, scope_id: str,
        resource: Mapping[str, Any]) -> tuple[Path, str]:
    capture_root = evidence_root / "FRESH_RESOURCE_CAPTURES"
    safe_scope = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in scope_id
    )
    path = capture_root / f"c{ordinal:04d}_{safe_scope}.json"
    if path.exists():
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "capture_path_exists")
    write_canonical_json(path, dict(resource))
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != hashlib.sha256(canonical_json_bytes(dict(resource))).hexdigest():
        raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "preserved_hash")
    return path, digest


def _materialize_fix005_batched_evidence_plan(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], workload_index: int,
        runtime_root: Path, evidence_root: Path,
        capture_provider: Any, activation: Mapping[str, Any],
        capture_ordinal_start: int = 0) -> Dict[str, Any]:
    """Reproduce historical FIX005 evidence; never used for physical launch.

    This deliberately preserves the reviewed FIX005 batch-capture artifact so
    its P12/P13/P14 regression can remain byte-semantically interpretable.
    FIX006 production execution uses ``materialize_fresh_workload_plan`` below,
    which contains no candidate-series capture.
    """
    workload = WORKLOADS[workload_index]
    ordinal = capture_ordinal_start
    branch_scope = f"WORKLOAD_BRANCH_{workload}"
    branch_resource = dict(capture_provider(branch_scope, workload, None))
    branch_path, branch_sha = _preserve_resource_capture(
        evidence_root, ordinal, branch_scope, branch_resource,
    )
    ordinal += 1
    admission = resolve_compact_admission_once(assets, branch_resource, workload)
    selection = assets.schedule_selection[(workload, admission)]
    schedule_id = selection["selected_schedule_id"]
    allowed = ALL_CANDIDATES if admission == "PASS" else FILE_CANDIDATES
    series: Dict[str, Dict[str, Any]] = {}
    capture_rows = [{
        "scope_id": branch_scope, "workload_id": workload,
        "candidate_id": "NOT_APPLICABLE", "capture_path": str(branch_path),
        "capture_sha256": branch_sha, "capture_role": "WORKLOAD_BRANCH_SELECTION",
        "compact_admission_result": admission,
    }]
    for candidate in allowed:
        scope = f"CANDIDATE_SERIES_{workload}_{candidate}"
        resource = dict(capture_provider(scope, workload, candidate))
        path, digest = _preserve_resource_capture(
            evidence_root, ordinal, scope, resource,
        )
        ordinal += 1
        series[candidate] = {"resource": resource, "path": path, "sha256": digest}
        capture_rows.append({
            "scope_id": scope, "workload_id": workload,
            "candidate_id": candidate, "capture_path": str(path),
            "capture_sha256": digest, "capture_role": "CANDIDATE_WORKLOAD_SERIES",
            "compact_admission_result": admission,
        })

    warmups = assets.warmup_rows(workload, admission)
    measured = assets.schedule_rows(workload, schedule_id)
    rows = [(row, "UNTIMED_WARMUP") for row in warmups]
    rows.extend((row, "MEASURED") for row in measured)
    requests = []
    for request_index, (row, phase) in enumerate(rows):
        candidate = row["backend"]
        request = make_large_request(
            authority, assets, series[candidate]["resource"], durability,
            workload, candidate,
            runtime_root / f"w{workload_index:02d}" /
            f"q{request_index:04d}_{candidate}",
            row, phase, evidence_root, activation, branch_resource,
        )
        if request["fresh_resource_capture_sha256"] != series[candidate]["sha256"]:
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "series_request_binding")
        if request["workload_branch_resource_capture_sha256"] != branch_sha:
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "branch_request_binding")
        requests.append(request)
    identities = _request_identity_rows(requests)
    tuples = [_request_tuple(request) for request in requests]
    if len(tuples) != len(set(tuples)):
        _plan_stop("fresh_workload_duplicate_request")
    expected_repetitions = int(selection["expected_measured_repetitions"])
    if (
        len(warmups) != len(allowed)
        or len(measured) != expected_repetitions * len(allowed)
    ):
        _plan_stop("fresh_workload_cardinality")
    return {
        "schema": "SplitAlignerR/ENGINE003StageBFreshWorkloadPlan/v1",
        "status": "FRESH_WORKLOAD_PLAN_CLOSED_NOT_EXECUTED",
        "workload_id": workload,
        "compact_admission_result": admission,
        "selected_schedule_id": schedule_id,
        "allowed_candidate_ids": list(allowed),
        "branch_capture_path": str(branch_path),
        "branch_capture_sha256": branch_sha,
        "capture_rows": capture_rows,
        "requests": requests,
        "request_count": len(requests),
        "request_identity_sha256": hashlib.sha256(
            canonical_json_bytes(identities)
        ).hexdigest(),
        "next_capture_ordinal": ordinal,
        "worker_launch_count": 0,
        "physical_allocation_count": 0,
    }


def _static_launch_rows(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], workload_index: int,
        runtime_root: Path, evidence_root: Path,
        activation: Mapping[str, Any], branch_resource: Mapping[str, Any],
        admission: str, schedule_id: str) -> list[Dict[str, Any]]:
    """Freeze launch tuples without retaining candidate admission state."""
    workload = WORKLOADS[workload_index]
    warmups = assets.warmup_rows(workload, admission)
    measured = assets.schedule_rows(workload, schedule_id)
    allowed = ALL_CANDIDATES if admission == "PASS" else FILE_CANDIDATES
    if (
        len(warmups) != len(allowed)
        or [row["backend"] for row in warmups] != list(dict.fromkeys(
            row["backend"] for row in warmups
        ))
        or {row["backend"] for row in warmups} != set(allowed)
    ):
        _plan_stop("static_warmup_candidate_boundary")
    selection = assets.schedule_selection[(workload, admission)]
    expected_repetitions = int(selection["expected_measured_repetitions"])
    if (
        len(measured) != expected_repetitions * len(allowed)
        or {row["backend"] for row in measured} != set(allowed)
    ):
        _plan_stop("static_measured_cardinality")
    rows = [(row, "UNTIMED_WARMUP") for row in warmups]
    rows.extend((row, "MEASURED") for row in measured)
    output = []
    for request_index, (row, phase) in enumerate(rows):
        candidate = row["backend"]
        runtime_target = (
            runtime_root / f"w{workload_index:02d}" /
            f"q{request_index:04d}_{candidate}"
        )
        # This prototype is discarded after extracting fields that are wholly
        # independent of candidate-series resource values.  Runtime admission
        # is bound only at the candidate's first launch boundary.
        prototype = make_large_request(
            authority, assets, branch_resource, durability, workload,
            candidate, runtime_target, row, phase, evidence_root, activation,
            branch_resource,
        )
        identity = {
            field: prototype[field] for field in STATIC_REQUEST_IDENTITY_FIELDS
        }
        output.append({
            "request_index": request_index,
            "run_phase": phase,
            "candidate_id": candidate,
            "schedule_row": dict(row),
            "request_identity": identity,
        })
    tuples = [
        tuple(row["request_identity"].get(field) for field in REQUEST_TUPLE_FIELDS)
        for row in output
    ]
    if len(tuples) != len(set(tuples)):
        _plan_stop("static_workload_duplicate_request")
    return output


def materialize_fresh_workload_plan(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], workload_index: int,
        runtime_root: Path, evidence_root: Path,
        capture_provider: Any, activation: Mapping[str, Any],
        capture_ordinal_start: int = 0) -> Dict[str, Any]:
    """Freeze one branch-selected plan; defer every series capture to launch."""
    workload = WORKLOADS[workload_index]
    branch_scope = f"WORKLOAD_BRANCH_{workload}"
    branch_resource = dict(capture_provider(branch_scope, workload, None))
    branch_path, branch_sha = _preserve_resource_capture(
        evidence_root, capture_ordinal_start, branch_scope, branch_resource,
    )
    admission = resolve_compact_admission_once(assets, branch_resource, workload)
    selection = assets.schedule_selection[(workload, admission)]
    schedule_id = selection["selected_schedule_id"]
    allowed = ALL_CANDIDATES if admission == "PASS" else FILE_CANDIDATES
    launch_rows = _static_launch_rows(
        authority, assets, durability, workload_index, runtime_root,
        evidence_root, activation, branch_resource, admission, schedule_id,
    )
    identities = [row["request_identity"] for row in launch_rows]
    return {
        "schema": STATIC_WORKLOAD_PLAN_SCHEMA,
        "status": "STATIC_WORKLOAD_PLAN_FROZEN_AWAITING_SERIES_BINDING",
        "workload_id": workload,
        "compact_admission_result": admission,
        "selected_schedule_id": schedule_id,
        "allowed_candidate_ids": list(allowed),
        "candidate_first_launch_order": [
            row["candidate_id"] for row in launch_rows
            if row["run_phase"] == "UNTIMED_WARMUP"
        ],
        "branch_capture_path": str(branch_path),
        "branch_capture_sha256": branch_sha,
        "capture_rows": [{
            "scope_id": branch_scope, "workload_id": workload,
            "candidate_id": "NOT_APPLICABLE",
            "capture_path": str(branch_path),
            "capture_sha256": branch_sha,
            "capture_role": "WORKLOAD_BRANCH_SELECTION",
            "compact_admission_result": admission,
        }],
        "static_launch_rows": launch_rows,
        "request_count": len(launch_rows),
        "request_identity_sha256": hashlib.sha256(
            canonical_json_bytes(identities)
        ).hexdigest(),
        "next_capture_ordinal": capture_ordinal_start + 1,
        "candidate_series_capture_count": 0,
        "worker_launch_count": 0,
        "physical_allocation_count": 0,
    }


def bind_candidate_series(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], workload_plan: Mapping[str, Any],
        candidate: str, evidence_root: Path, capture_provider: Any,
        capture_ordinal: int, activation: Mapping[str, Any],
        branch_resource: Mapping[str, Any]) -> Dict[str, Any]:
    """Capture and bind one candidate's frozen rows at its first boundary."""
    workload = workload_plan["workload_id"]
    if candidate not in workload_plan["allowed_candidate_ids"]:
        _plan_stop("series_candidate_not_allowed")
    scope = f"CANDIDATE_SERIES_{workload}_{candidate}"
    resource = dict(capture_provider(scope, workload, candidate))
    path, digest = _preserve_resource_capture(
        evidence_root, capture_ordinal, scope, resource,
    )
    requests: Dict[int, Dict[str, Any]] = {}
    for launch_row in workload_plan["static_launch_rows"]:
        if launch_row["candidate_id"] != candidate:
            continue
        identity = launch_row["request_identity"]
        request = make_large_request(
            authority, assets, resource, durability, workload, candidate,
            Path(identity["runtime_target"]), launch_row["schedule_row"],
            launch_row["run_phase"], evidence_root, activation,
            branch_resource,
        )
        observed_identity = {
            field: request[field] for field in STATIC_REQUEST_IDENTITY_FIELDS
        }
        if observed_identity != identity:
            _plan_stop(f"dynamic_binding_changed_static_identity:{candidate}")
        if request["fresh_resource_capture_sha256"] != digest:
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "series_request_binding")
        if (
            request["workload_branch_resource_capture_sha256"]
            != workload_plan["branch_capture_sha256"]
        ):
            raise StopSignal("SB_STOP_RUNTIME_CAPTURE", "branch_request_binding")
        requests[launch_row["request_index"]] = request
    if not requests:
        _plan_stop("series_without_requests")
    return {
        "capture_row": {
            "scope_id": scope, "workload_id": workload,
            "candidate_id": candidate, "capture_path": str(path),
            "capture_sha256": digest,
            "capture_role": "CANDIDATE_WORKLOAD_SERIES",
            "compact_admission_result": workload_plan["compact_admission_result"],
        },
        "resource": resource,
        "resource_path": path,
        "requests": requests,
        "next_capture_ordinal": capture_ordinal + 1,
    }


def _plan_stop(detail: str) -> None:
    raise StopSignal("SB_STOP_COMPLETE_PLAN_IDENTITY", detail)


def _request_identity_rows(requests: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    rows = []
    for index, request in enumerate(requests):
        if not isinstance(request, Mapping):
            _plan_stop(f"request_not_object:{index}")
        missing = [field for field in REQUEST_IDENTITY_FIELDS if field not in request]
        if missing:
            _plan_stop(f"request_identity_fields:{index}:{','.join(missing)}")
        rows.append({field: request[field] for field in REQUEST_IDENTITY_FIELDS})
    return rows


def _request_tuple(request: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(request.get(field) for field in REQUEST_TUPLE_FIELDS)


def resolve_compact_admission_once(
        assets: FrozenAssets, resource: Mapping[str, Any], workload: str) -> str:
    available = resource["admission_memory_ceiling_bytes"]
    required = int(assets.projections[(workload, "COMPACT_IN_MEMORY")][
        "memory_admission_required_bytes"
    ])
    return "PASS" if available >= required else "FAIL"


def branch_resource(
        assets: FrozenAssets, resource: Mapping[str, Any], admission: str) -> Dict[str, Any]:
    """Produce a no-clock resource view that deterministically selects a branch."""
    if admission not in {"PASS", "FAIL"}:
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "branch_resource")
    output = dict(resource)
    compact_requirements = [
        int(assets.projections[(workload, "COMPACT_IN_MEMORY")][
            "memory_admission_required_bytes"
        ]) for workload in WORKLOADS
    ]
    file_requirements = [
        int(assets.projections[(workload, candidate)][
            "memory_admission_required_bytes"
        ]) for workload in WORKLOADS for candidate in FILE_CANDIDATES
    ]
    if admission == "PASS":
        output["admission_memory_ceiling_bytes"] = max(
            output["admission_memory_ceiling_bytes"], *compact_requirements,
            *file_requirements,
        )
    else:
        upper = min(compact_requirements) - 1
        lower = max(file_requirements)
        if lower > upper:
            raise StopSignal("SB_STOP_ADMISSION_MEMORY", "no_legal_three_file_branch_fixture")
        output["admission_memory_ceiling_bytes"] = lower
    output["stage_b_fix003_resource_view"] = (
        f"DERIVED_NO_ALLOCATION_{admission}_BRANCH"
    )
    return output


def _plan_rows(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime_root: Path, evidence_root: Path,
        activation: Mapping[str, Any] | None = None) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    requests: list[Dict[str, Any]] = []
    workload_summary: list[Dict[str, Any]] = []
    last_rows = -1
    for workload_index, workload in enumerate(WORKLOADS):
        rows = int(assets.workloads[workload]["G"])
        if rows < last_rows:
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "workload_order")
        last_rows = rows
        admission = resolve_compact_admission_once(assets, resource, workload)
        selection = assets.schedule_selection[(workload, admission)]
        schedule_id = selection["selected_schedule_id"]
        expected_repetitions = int(selection["expected_measured_repetitions"])
        allowed = ALL_CANDIDATES if admission == "PASS" else FILE_CANDIDATES
        warmups = assets.warmup_rows(workload, admission)
        measured = assets.schedule_rows(workload, schedule_id)
        if len(warmups) != len(allowed):
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "warmup_cardinality")
        if len(measured) != expected_repetitions * len(allowed):
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "measured_cardinality")
        if {row["backend"] for row in measured} != set(allowed):
            raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "candidate_set")
        start = len(requests)
        for warmup in warmups:
            candidate = warmup["backend"]
            request_index = len(requests)
            requests.append(make_large_request(
                authority, assets, resource, durability, workload, candidate,
                runtime_root / f"w{workload_index:02d}" / f"q{request_index:04d}_{candidate}",
                warmup, "UNTIMED_WARMUP", evidence_root, activation,
            ))
        for row in measured:
            candidate = row["backend"]
            request_index = len(requests)
            requests.append(make_large_request(
                authority, assets, resource, durability, workload, candidate,
                runtime_root / f"w{workload_index:02d}" / f"q{request_index:04d}_{candidate}",
                row, "MEASURED", evidence_root, activation,
            ))
        workload_summary.append({
            "workload_id": workload,
            "compact_admission_result": admission,
            "selected_schedule_id": schedule_id,
            "expected_measured_repetitions": expected_repetitions,
            "warmup_request_count": len(warmups),
            "measured_request_count": len(measured),
            "total_request_count": len(requests) - start,
            "allowed_candidate_ids": list(allowed),
            "selection_resolved_once_before_first_measured_result": True,
        })
    return requests, workload_summary


def complete_execution_plan(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime_root: Path, evidence_root: Path,
        activation: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    requests, workloads = _plan_rows(
        authority, assets, resource, durability, runtime_root, evidence_root,
        activation,
    )
    identity_rows = _request_identity_rows(requests)
    return {
        "schema": PLAN_SCHEMA,
        "status": "COMPLETE_PLAN_FROZEN_NOT_EXECUTED",
        "workload_order": list(WORKLOADS),
        "workloads": workloads,
        "requests": requests,
        "request_identity_sha256": hashlib.sha256(
            canonical_json_bytes(identity_rows)
        ).hexdigest(),
        "request_count": len(requests),
        "warmup_request_count": sum(
            value["warmup_request_count"] for value in workloads
        ),
        "measured_request_count": sum(
            value["measured_request_count"] for value in workloads
        ),
        "decision_input_ledger_assembled": False,
        "global_stop_policy": "FIRST_NON_PASS_STOPS_ALL_LATER_WORKLOADS",
    }


def validate_complete_execution_plan_structure(
        repo: Path, runtime_root: Path, evidence_root: Path,
        resource_path: Path, durability_path: Path,
        plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Reconstruct and exactly close a complete plan before any launch.

    This pure control-plane phase deliberately precedes external authorization
    validation and worker import.  Consequently every malformed complete plan
    stops with zero worker launches and zero physical allocations, including a
    plan made only of individually valid but duplicated schedule rows.
    """
    if not isinstance(plan, Mapping) or set(plan) != PLAN_FIELDS:
        observed = sorted(plan) if isinstance(plan, Mapping) else [type(plan).__name__]
        _plan_stop(f"plan_field_set:{observed}")
    if plan.get("schema") != PLAN_SCHEMA:
        _plan_stop("schema")
    if plan.get("status") != "COMPLETE_PLAN_FROZEN_NOT_EXECUTED":
        _plan_stop("status")
    if plan.get("decision_input_ledger_assembled") is not False:
        _plan_stop("decision_input_ledger_state")
    if plan.get("global_stop_policy") != "FIRST_NON_PASS_STOPS_ALL_LATER_WORKLOADS":
        _plan_stop("global_stop_policy")
    requests = plan.get("requests")
    if not isinstance(requests, list) or not requests:
        _plan_stop("requests_nonempty_list")
    first = requests[0]
    if not isinstance(first, Mapping):
        _plan_stop("first_request_object")
    source_commit = first.get("source_commit")
    source_tree = first.get("source_tree")
    if not isinstance(source_commit, str) or not isinstance(source_tree, str):
        _plan_stop("execution_source_identity")
    activation = first.get("activation")
    if not isinstance(activation, Mapping):
        _plan_stop("external_authorization_object")

    # ExecutionAuthority independently binds the request's claimed identity to
    # the current checkout and frozen preregistration tree without checkout.
    authority = ExecutionAuthority(repo, source_commit, source_tree)
    assets = FrozenAssets(authority)
    resource = strict_json_load(resource_path)
    durability = strict_json_load(durability_path)
    expected = complete_execution_plan(
        authority, assets, resource, durability, runtime_root, evidence_root,
        activation,
    )

    identity_rows = _request_identity_rows(requests)
    request_tuples = [_request_tuple(request) for request in requests]
    if len(request_tuples) != len(set(request_tuples)):
        _plan_stop("duplicate_request_tuple")
    observed_identity = hashlib.sha256(
        canonical_json_bytes(identity_rows)
    ).hexdigest()
    if plan.get("request_identity_sha256") != observed_identity:
        _plan_stop("request_identity_sha256_recomputation")

    observed_warmups = sum(
        request.get("run_phase") == "UNTIMED_WARMUP" for request in requests
    )
    observed_measured = sum(
        request.get("run_phase") == "MEASURED" for request in requests
    )
    cardinalities = {
        "request_count": len(requests),
        "warmup_request_count": observed_warmups,
        "measured_request_count": observed_measured,
    }
    for field, observed in cardinalities.items():
        if type(plan.get(field)) is not int or plan[field] != observed:
            _plan_stop(f"{field}_self_consistency")
        if plan[field] != expected[field]:
            _plan_stop(f"{field}_frozen_expected")
    if plan.get("workload_order") != expected["workload_order"]:
        _plan_stop("workload_order")
    if plan.get("workloads") != expected["workloads"]:
        _plan_stop("workload_summaries_or_branch")
    if requests != expected["requests"]:
        _plan_stop("ordered_request_set")
    if plan.get("request_identity_sha256") != expected["request_identity_sha256"]:
        _plan_stop("branch_specific_plan_identity")
    if dict(plan) != expected:
        _plan_stop("complete_plan_exact_equality")
    return {
        "authority": authority,
        "assets": assets,
        "resource": resource,
        "durability": durability,
        "expected_plan": expected,
        "request_tuple_count": len(request_tuples),
        "status": "PASS_COMPLETE_PLAN_STRUCTURE_EXACT",
    }


def validate_complete_execution_plan(
        repo: Path, runtime_root: Path, evidence_root: Path,
        resource_path: Path, durability_path: Path,
        plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Exact structure plus exact external authorization, before launch one."""
    context = validate_complete_execution_plan_structure(
        repo, runtime_root, evidence_root, resource_path, durability_path, plan,
    )
    authority = context["authority"]
    assets = context["assets"]
    resource = context["resource"]
    durability = context["durability"]
    expected = context["expected_plan"]
    for index, request in enumerate(expected["requests"]):
        try:
            guard = prelaunch_guard(
                authority, assets, request, runtime_root, resource, durability,
            )
        except StopSignal:
            # Still before importing or invoking the physical launcher.
            raise
        if (
            guard.get("worker_launch_authorized") is not True
            or guard.get("physical_allocation_authorized") is not True
        ):
            _plan_stop(f"external_authorization:{index}")
    context["status"] = "PASS_COMPLETE_PLAN_AND_AUTHORIZATION_EXACT"
    context["authorization_request_count"] = len(expected["requests"])
    return context


def validate_worker_result_identity(
        request: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    """Keep a worker result out of every ledger until identity is exact."""
    if not isinstance(result, Mapping):
        raise StopSignal("SB_STOP_RESULT_IDENTITY", "result_not_object")
    mismatches = [
        field for field in RESULT_IDENTITY_FIELDS
        if result.get(field) != request.get(field)
    ]
    if mismatches:
        raise StopSignal(
            "SB_STOP_RESULT_IDENTITY", ",".join(mismatches),
        )


def dry_run_plan(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime_root: Path, evidence_root: Path) -> Dict[str, Any]:
    plan = complete_execution_plan(
        authority, assets, resource, durability, runtime_root, evidence_root,
    )
    observed = []
    for index, request in enumerate(plan["requests"]):
        try:
            prelaunch_guard(
                authority, assets, request, runtime_root, resource, durability,
            )
        except StopSignal as signal_value:
            if signal_value.stop_id != "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
                raise
            observed.append({
                "request_index": index,
                "workload_id": request["workload_id"],
                "run_phase": request["run_phase"],
                "candidate_id": request["candidate_id"],
                "measured_repetition": request["measured_repetition"],
                "schedule_position": request["schedule_position"],
                "schedule_row_sha256": request["schedule_row_sha256"],
                "stop_id": signal_value.stop_id,
                "worker_launch_count": 0,
                "physical_allocation_count": 0,
                "status": "PASS_DRY_RUN_STOPPED",
            })
            continue
        raise AssertionError(f"large request activated during FIX003 dry run:{index}")
    plan["mode"] = DRY_RUN_MODE
    plan["status"] = "PASS_COMPLETE_PLAN_DRY_RUN_ZERO_ALLOCATION"
    plan["dry_run_results"] = observed
    plan["worker_launch_count"] = 0
    plan["physical_allocation_count"] = 0
    plan["decision_input_ledger_assembled"] = True
    plan["decision_input_ledger"] = [{
        key: value[key] for key in (
            "request_index", "workload_id", "run_phase", "candidate_id",
            "measured_repetition", "schedule_position", "schedule_row_sha256",
            "status",
        )
    } for value in observed]
    return plan


def assert_global_stop_prefix(
        statuses: Sequence[str], workload_indices: Sequence[int]) -> int:
    """Pure control-plane rule used by the future authorized runner."""
    if len(statuses) != len(workload_indices):
        raise StopSignal("SB_STOP_INCOMPLETE_SCHEDULE", "status_cardinality")
    first_nonpass = next(
        (index for index, status in enumerate(statuses) if status != "PASS"),
        len(statuses),
    )
    if any(status == "PASS" for status in statuses[first_nonpass + 1:]):
        raise StopSignal("SB_STOP_GLOBAL", "launch_after_nonpass")
    if first_nonpass < len(statuses):
        failed_workload = workload_indices[first_nonpass]
        if any(value > failed_workload for value in workload_indices[first_nonpass + 1:]):
            raise StopSignal("SB_STOP_GLOBAL", "later_larger_workload_after_stop")
    return first_nonpass


def execute_authorized_plan(
        repo: Path, runtime_root: Path, evidence_root: Path,
        resource_path: Path, durability_path: Path,
        plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the legacy complete plan, then fail closed before launch.

    FIX004 mutation regressions still enter here so malformed plans are stopped
    before any launcher import.  A structurally valid legacy plan is also
    stopped: it carries only one resource snapshot and therefore cannot satisfy
    FIX006 candidate-series admission cadence.  The sole future physical entry
    is ``execute_fresh_authorized_protocol()``.
    """
    # This complete-plan and authorization gate must finish before the launcher
    # module is even imported.  No individually valid duplicate/missing/extra
    # schedule row can therefore reach launch dispatch.
    validate_complete_execution_plan_structure(
        repo, runtime_root, evidence_root, resource_path, durability_path, plan,
    )
    try:
        validate_complete_execution_plan(
            repo, runtime_root, evidence_root, resource_path, durability_path,
            plan,
        )
    except StopSignal as signal_value:
        if signal_value.stop_id != "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
            raise
        # The historical dry activation is a fully closed structural fixture,
        # not an authorization candidate.  Retire it at the same explicit gate
        # used for any externally authorized legacy plan.
    raise StopSignal(
        "SB_STOP_LEGACY_EXECUTION_PATH",
        "use_execute_fresh_authorized_protocol",
    )


def execute_runtime_bound_workload(
        authority: ExecutionAuthority, assets: FrozenAssets,
        durability: Mapping[str, Any], workload_plan: Mapping[str, Any],
        evidence_root: Path, capture_provider: Any,
        capture_ordinal_start: int, activation: Mapping[str, Any],
        guard_callback: Any, launch_callback: Any,
        event_ordinal_start: int = 0) -> Dict[str, Any]:
    """Execute frozen rows while lazily binding each candidate series.

    The externally authorized entrypoint below supplies the frozen capture,
    real prelaunch guard and real launcher.  FIX006 bounded evidence supplies
    non-allocating callbacks to exercise this identical ordering loop.
    """
    branch_resource_path = Path(workload_plan["branch_capture_path"])
    branch_resource = strict_json_load(branch_resource_path)
    bindings: Dict[str, Dict[str, Any]] = {}
    captures = list(workload_plan["capture_rows"])
    results = []
    events = [{
        "ordinal": event_ordinal_start + 1,
        "event": "WORKLOAD_BRANCH_CAPTURE",
        "workload_id": workload_plan["workload_id"],
        "candidate_id": "NOT_APPLICABLE",
        "request_index": -1,
        "capture_sha256": workload_plan["branch_capture_sha256"],
        "bound_request_count": 0,
        "guarded_request_count": 0,
    }]
    event_ordinal = event_ordinal_start + 1
    capture_ordinal = capture_ordinal_start
    for launch_row in workload_plan["static_launch_rows"]:
        request_index = launch_row["request_index"]
        candidate = launch_row["candidate_id"]
        if candidate not in bindings:
            binding = bind_candidate_series(
                authority, assets, durability, workload_plan, candidate,
                evidence_root, capture_provider, capture_ordinal, activation,
                branch_resource,
            )
            capture_ordinal = binding["next_capture_ordinal"]
            bindings[candidate] = binding
            captures.append(binding["capture_row"])
            event_ordinal += 1
            events.append({
                "ordinal": event_ordinal,
                "event": "CANDIDATE_SERIES_CAPTURE",
                "workload_id": workload_plan["workload_id"],
                "candidate_id": candidate,
                "request_index": request_index,
                "capture_sha256": binding["capture_row"]["capture_sha256"],
                "bound_request_count": 0,
                "guarded_request_count": 0,
            })
            event_ordinal += 1
            events.append({
                "ordinal": event_ordinal,
                "event": "CANDIDATE_SERIES_BINDING",
                "workload_id": workload_plan["workload_id"],
                "candidate_id": candidate,
                "request_index": request_index,
                "capture_sha256": binding["capture_row"]["capture_sha256"],
                "bound_request_count": len(binding["requests"]),
                "guarded_request_count": 0,
            })
            # Close the whole candidate series against the one fresh capture.
            # launch_request repeats the same guard for each actual spawn.
            for series_index in sorted(binding["requests"]):
                guard_callback(
                    binding["requests"][series_index], binding["resource_path"],
                    binding["resource"], branch_resource_path, branch_resource,
                )
            event_ordinal += 1
            events.append({
                "ordinal": event_ordinal,
                "event": "CANDIDATE_SERIES_PRELAUNCH_GUARD",
                "workload_id": workload_plan["workload_id"],
                "candidate_id": candidate,
                "request_index": request_index,
                "capture_sha256": binding["capture_row"]["capture_sha256"],
                "bound_request_count": len(binding["requests"]),
                "guarded_request_count": len(binding["requests"]),
            })
        binding = bindings[candidate]
        request = binding["requests"][request_index]
        event_ordinal += 1
        event_name = (
            "CANDIDATE_SERIES_FIRST_WORKER_LAUNCH"
            if launch_row["run_phase"] == "UNTIMED_WARMUP"
            else "WORKER_LAUNCH"
        )
        events.append({
            "ordinal": event_ordinal,
            "event": event_name,
            "workload_id": workload_plan["workload_id"],
            "candidate_id": candidate,
            "request_index": request_index,
            "capture_sha256": binding["capture_row"]["capture_sha256"],
            "bound_request_count": len(binding["requests"]),
            "guarded_request_count": len(binding["requests"]),
        })
        result = launch_callback(
            request, request_index, binding["resource_path"],
            branch_resource_path,
        )
        validate_worker_result_identity(request, result)
        results.append(result)
    if len(bindings) != len(workload_plan["allowed_candidate_ids"]):
        _plan_stop("dynamic_binding_candidate_cardinality")
    identities = [
        row["request_identity"] for row in workload_plan["static_launch_rows"]
    ]
    if hashlib.sha256(canonical_json_bytes(identities)).hexdigest() != (
            workload_plan["request_identity_sha256"]):
        _plan_stop("static_plan_identity_changed_during_execution")
    binding_rows = []
    for candidate in workload_plan["candidate_first_launch_order"]:
        binding = bindings[candidate]
        request_values = list(binding["requests"].values())
        binding_rows.append({
            "workload_id": workload_plan["workload_id"],
            "candidate_id": candidate,
            "capture_sha256": binding["capture_row"]["capture_sha256"],
            "request_count": len(request_values),
            "request_capture_sha256_exact": all(
                request["fresh_resource_capture_sha256"]
                == binding["capture_row"]["capture_sha256"]
                for request in request_values
            ),
            "fresh_available_memory_bytes": request_values[0][
                "fresh_available_memory_bytes"
            ],
            "fresh_available_disk_bytes": request_values[0][
                "fresh_available_disk_bytes"
            ],
        })
    return {
        "results": results,
        "capture_rows": captures,
        "event_rows": events,
        "next_capture_ordinal": capture_ordinal,
        "static_plan_identity_sha256": workload_plan["request_identity_sha256"],
        "candidate_series_capture_count": len(bindings),
        "dynamic_binding_rows": binding_rows,
    }


DISPATCH_RUN_LABEL = "STAGEB_REQUEST"   # display label, not a binding key


def journaled_exact_launch(
        launcher: Any, dispatch_journal: Any, repo: Path, runtime_root: Path,
        resource_path: Path, durability_path: Path, request: Mapping[str, Any],
        request_path: Path, output_path: Path, log_path: Path,
        branch_resource_path: Path, stop_detail: str) -> Dict[str, Any]:
    """DEV007_FIX005 coordinator (the one transaction owner of this call).

    1. Pure admission + caller-bound reservation (reserve_current_dispatch):
       a refusal writes nothing and calls no launcher.
    2. The launcher receives ONLY the ticket of that reserved dispatch; the
       lower layer checks the actual request against it before spawn and
       returns prepared evidence (never FINAL ACCEPTED).
    3. commit_current_dispatch verifies the prepared evidence against the
       caller's ticket and this request's result-identity rule, then writes
       the envelope + FINAL ACCEPTED; only then does the result reach the
       ledger.
    Any refusal after step 1 leaves a durable STOP (or the non-terminal
    IN_FLIGHT if that write fails): a reconstructed scope refuses new work.
    Raw worker PASS, an unverifiable/unbound return or a journal refusal is
    a global STOP (no later launch, no ledger row)."""
    from stage_b_controller import raw_worker_output_path
    from stage_b_dispatch_journal import (
        CrashCut, commit_current_dispatch, refuse_current_dispatch,
        reserve_current_dispatch,
    )
    try:
        ticket = reserve_current_dispatch(
            dispatch_journal, run_id=DISPATCH_RUN_LABEL,
            request_sha256=hashlib.sha256(
                canonical_json_bytes(dict(request))).hexdigest(),
            raw_path=raw_worker_output_path(output_path, DISPATCH_RUN_LABEL),
            output_path=output_path,
        )
    except Exception as error:           # zero effects: nothing reserved
        raise StopSignal(
            "SB_STOP_GLOBAL",
            f"{stop_detail};later_launches=0;cause={error}",
        ) from error
    try:
        returned = launcher(
            repo, runtime_root, resource_path, durability_path, request,
            request_path, output_path, log_path, branch_resource_path,
            dispatch_ticket=ticket,
        )
        envelope = commit_current_dispatch(
            dispatch_journal, ticket, returned,
            result_check=lambda result: validate_worker_result_identity(
                request, result),
        )
        return dict(envelope["accepted_result"])
    except CrashCut:
        raise                             # process death: nothing more runs
    except BaseException as error:
        # Authority was handed out: durable STOP (never over an existing
        # FINAL, so a committed result is not relabelled), else IN_FLIGHT.
        secondary = getattr(error, "stop_failures", None)
        if secondary is None:
            secondary = refuse_current_dispatch(
                dispatch_journal, ticket, "COORDINATOR_REFUSED",
                f"{type(error).__name__}:{error}")
        if not isinstance(error, Exception):
            raise
        stop = StopSignal(
            "SB_STOP_GLOBAL",
            f"{stop_detail};later_launches=0;cause={error}",
        )
        stop.cleanup = {"ticket": dict(ticket.binding),
                        "secondary_failures": list(secondary),
                        "primary": f"{type(error).__name__}:{error}"}
        raise stop from error


def execute_fresh_authorized_protocol(
        repo: Path, runtime_root: Path, evidence_root: Path,
        durability_path: Path, protocol: Mapping[str, Any],
        capture_provider: Any | None = None,
        dispatch_journal: Any = None) -> Dict[str, Any]:
    """Future P14 entrypoint with workload/series recapture and global STOP.

    The adaptive policy is exactly closed before launch one. Each workload is
    branch-captured into a frozen static tuple plan. Candidate requests are
    then lazily captured, bound and preflighted as a complete series at that
    candidate's first untimed warm-up. A later workload can change branch
    without changing the frozen schedule policy.
    """
    source_commit = protocol.get("source_commit")
    source_tree = protocol.get("source_tree")
    authority = ExecutionAuthority(repo, source_commit, source_tree)
    assets = FrozenAssets(authority)
    frozen_protocol = validate_adaptive_execution_protocol(
        authority, assets, protocol,
    )
    durability = strict_json_load(durability_path)
    activation = frozen_protocol["activation"]
    if capture_provider is not None:
        raise StopSignal(
            "SB_STOP_RUNTIME_CAPTURE",
            "externally_authorized_execution_requires_frozen_capture_procedure",
        )
    # DEV007_FIX003: one stable dispatch journal scope for the whole protocol;
    # without it (or with an unresolved scope) nothing is captured or spawned.
    if dispatch_journal is None:
        raise StopSignal("SB_STOP_DISPATCH_JOURNAL", "journal_required")
    journal_state = dispatch_journal.state()
    if journal_state.get("ready") is not True:
        raise StopSignal(
            "SB_STOP_DISPATCH_JOURNAL", str(journal_state.get("reason")),
        )
    from capture_pretiming_resources import capture as frozen_capture

    def exact_capture_provider(_scope: str, _workload: str, _candidate: str | None):
        return frozen_capture(runtime_root)

    results = []
    captures = []
    execution_events = []
    ordinal = 0
    launcher = None
    for workload_index, workload in enumerate(WORKLOADS):
        workload_plan = materialize_fresh_workload_plan(
            authority, assets, durability, workload_index, runtime_root,
            evidence_root, exact_capture_provider, activation, ordinal,
        )
        if workload_plan["workload_id"] != workload:
            _plan_stop("fresh_workload_order")
        ordinal = workload_plan["next_capture_ordinal"]

        def exact_guard(request, _resource_path, resource,
                        _branch_resource_path, branch_resource):
            guard = prelaunch_guard(
                authority, assets, request, runtime_root, resource,
                durability, branch_resource,
            )
            if (
                guard.get("worker_launch_authorized") is not True
                or guard.get("physical_allocation_authorized") is not True
            ):
                _plan_stop(
                    f"fresh_external_authorization:{workload}:"
                    f"{request['candidate_id']}"
                )
            return guard

        if launcher is None:
            from stage_b_controller import launch_request
            launcher = launch_request

        def exact_launch(request, index, resource_path, branch_resource_path):
            stem = (
                f"w{workload_index:02d}_q{index:04d}_"
                f"{request['candidate_id']}"
            )
            return journaled_exact_launch(
                launcher, dispatch_journal, repo, runtime_root, resource_path,
                durability_path, request,
                evidence_root / "AUTHORIZED_REQUESTS" / f"{stem}.request.json",
                evidence_root / "AUTHORIZED_RESULTS" / f"{stem}.result.json",
                evidence_root / "AUTHORIZED_LOGS" / f"{stem}.log.txt",
                branch_resource_path,
                f"first_nonpass={workload}:{index}",
            )

        workload_execution = execute_runtime_bound_workload(
            authority, assets, durability, workload_plan, evidence_root,
            exact_capture_provider, ordinal, activation, exact_guard,
            exact_launch, len(execution_events),
        )
        ordinal = workload_execution["next_capture_ordinal"]
        results.extend(workload_execution["results"])
        captures.extend(workload_execution["capture_rows"])
        execution_events.extend(workload_execution["event_rows"])
    measured = [result for result in results if result["measured_repetition"] > 0]
    ledger = [{
        "workload_id": result["workload_id"],
        "candidate_id": result["candidate_id"],
        "selected_schedule_id": result["selected_schedule_id"],
        "measured_repetition": result["measured_repetition"],
        "schedule_position": result["schedule_position"],
        "schedule_row_sha256": result["schedule_row_sha256"],
        "integer_metrics": result["integer_metrics"],
        "operation_integer_values": result["operation_integer_values"],
        "status": "PASS",
    } for result in measured]
    return {
        "schema": "SplitAlignerR/ENGINE003StageBFreshAdmissionExecutionResult/v1",
        "status": "PASS_COMPLETE_FRESH_AUTHORIZED_EXECUTION",
        "protocol_identity_sha256": frozen_protocol["protocol_identity_sha256"],
        "resource_capture_count": len(captures),
        "resource_captures": captures,
        "candidate_series_event_rows": execution_events,
        "request_count": len(results),
        "measured_result_count": len(measured),
        "global_stop_policy_enforced": True,
        "decision_input_ledger_assembled": True,
        "decision_input_ledger": ledger,
    }
