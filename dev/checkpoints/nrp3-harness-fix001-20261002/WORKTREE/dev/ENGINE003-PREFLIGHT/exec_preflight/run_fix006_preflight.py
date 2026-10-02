#!/usr/bin/env python3
"""Run FIX006 bounded P16 cadence and P17 whole-tree certification."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    WORKLOADS, ExecutionAuthority, FrozenAssets, StopSignal,
    _schedule_row_sha, canonical_json_bytes, strict_json_load,
    write_canonical_json,
)
from run_fix002_preflight import write_tsv  # noqa: E402
from run_fix005_preflight import (  # noqa: E402
    INJECTED_WORKER, _capture_with_ceiling, _pid_is_live_non_zombie,
    execute as execute_fix005,
)
from stage_b_controller import (  # noqa: E402
    TIMEOUT_COOPERATIVE_GRACE_SECONDS, launch_request,
)
import stage_b_controller as controller  # noqa: E402
from stage_b_orchestrator import (  # noqa: E402
    REQUEST_IDENTITY_FIELDS, complete_execution_plan,
    execute_authorized_plan, execute_runtime_bound_workload,
    materialize_fresh_workload_plan,
)
from stage_b_runtime_contract import (  # noqa: E402
    make_bounded_request, prelaunch_guard,
)


SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBExecPreflightFix006Summary/v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _activation() -> Dict[str, Any]:
    return {
        "state": "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED",
        "authorization_id": "FIX003_PREFLIGHT_DRY_RUN_ONLY",
        "authorization_sha256": "0" * 64,
        "authorization_artifact_path": "NOT_SUPPLIED",
        "physical_allocation_authorized": False,
    }


def _result_identity(request: Mapping[str, Any]) -> Dict[str, Any]:
    fields = (
        "workload_id", "candidate_id", "selected_schedule_id",
        "measured_repetition", "schedule_position", "schedule_row_sha256",
        "source_commit", "source_tree",
    )
    return {field: request[field] for field in fields}


def candidate_series_cadence_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        base_resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path) -> Dict[str, Any]:
    """Run the production ordering loop with zero-allocation callbacks."""
    workload_index = 0
    workload = WORKLOADS[workload_index]
    activation = _activation()
    maximum_memory = max(
        int(value["memory_admission_required_bytes"])
        for (workload_id, _candidate), value in assets.projections.items()
        if workload_id == workload
    ) + 65536
    maximum_disk = max(
        int(value["disk_admission_required_bytes"])
        for (workload_id, _candidate), value in assets.projections.items()
        if workload_id == workload
    ) + 65536
    branch_resource = _capture_with_ceiling(
        base_resource, maximum_memory, "FIX006_STATIC_BRANCH",
    )
    branch_resource["available_local_disk_bytes"] = maximum_disk

    run_outputs = []
    binding_evidence_rows = []
    for run_id, post_first_delta in (("A", 8192), ("B", 16384)):
        run_evidence = evidence / f"P16_RUN_{run_id}"
        state = {
            "first_launch_seen": False, "launches": [], "captures": [],
            "guards": [],
        }

        def provider(scope: str, _workload: str, candidate: str | None):
            if candidate is None:
                value = dict(branch_resource)
            else:
                delta = post_first_delta if state["first_launch_seen"] else 0
                value = _capture_with_ceiling(
                    base_resource, maximum_memory - delta,
                    f"FIX006_{run_id}_{scope}_{int(state['first_launch_seen'])}",
                )
                value["available_local_disk_bytes"] = maximum_disk - delta
            state["captures"].append({
                "scope_id": scope,
                "candidate_id": candidate or "NOT_APPLICABLE",
                "after_first_candidate_launch": state["first_launch_seen"],
                "admission_memory_ceiling_bytes": value[
                    "admission_memory_ceiling_bytes"
                ],
                "available_local_disk_bytes": value[
                    "available_local_disk_bytes"
                ],
                "capture_sha256": _sha(canonical_json_bytes(value)),
            })
            return value

        plan = materialize_fresh_workload_plan(
            authority, assets, durability, workload_index, runtime,
            run_evidence, provider, activation, 0,
        )

        def guard(request, _resource_path, resource,
                  _branch_resource_path, exact_branch_resource):
            state["guards"].append({
                "request_index": next(
                    row["request_index"] for row in plan["static_launch_rows"]
                    if row["request_identity"]["runtime_target"]
                    == request["runtime_target"]
                ),
                "candidate_id": request["candidate_id"],
            })
            try:
                prelaunch_guard(
                    authority, assets, request, runtime, resource, durability,
                    exact_branch_resource,
                )
            except StopSignal as signal_value:
                if signal_value.stop_id != "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
                    raise
                return {"status": "EXPECTED_NONAUTH_STOP_AFTER_EXACT_PREFLIGHT"}
            raise AssertionError("FIX006 bounded cadence unexpectedly authorized")

        def launch(request, request_index, _resource_path, _branch_path):
            state["launches"].append({
                "request_index": request_index,
                "candidate_id": request["candidate_id"],
                "run_phase": request["run_phase"],
                "selected_schedule_id": request["selected_schedule_id"],
                "measured_repetition": request["measured_repetition"],
                "schedule_position": request["schedule_position"],
                "schedule_row_sha256": request["schedule_row_sha256"],
                "timeout_seconds": request["timeout_seconds"],
                "metric_contract_sha256": request["metric_contract_sha256"],
            })
            if len(state["launches"]) == 1:
                state["first_launch_seen"] = True
            return _result_identity(request)

        execution = execute_runtime_bound_workload(
            authority, assets, durability, plan, run_evidence, provider,
            plan["next_capture_ordinal"], activation, guard, launch,
        )
        write_canonical_json(
            evidence / f"P16_STATIC_WORKLOAD_PLAN_{run_id}.json", plan,
        )
        write_tsv(
            evidence / f"P16_EVENT_ORDER_{run_id}.tsv",
            execution["event_rows"],
        )
        candidate_captures = [
            row for row in state["captures"]
            if row["candidate_id"] != "NOT_APPLICABLE"
        ]
        first_order = plan["candidate_first_launch_order"]
        if [row["candidate_id"] for row in candidate_captures] != first_order:
            raise AssertionError("candidate capture order differs from frozen warmups")
        if not candidate_captures[0]["after_first_candidate_launch"] is False:
            raise AssertionError("first candidate capture did not precede launch")
        if not all(
                row["after_first_candidate_launch"] is True
                for row in candidate_captures[1:]):
            raise AssertionError("later candidates did not recapture after A launch")

        events = execution["event_rows"]
        for candidate in first_order:
            capture = next(
                row for row in events
                if row["event"] == "CANDIDATE_SERIES_CAPTURE"
                and row["candidate_id"] == candidate
            )
            guard_event = next(
                row for row in events
                if row["event"] == "CANDIDATE_SERIES_PRELAUNCH_GUARD"
                and row["candidate_id"] == candidate
            )
            first_launch = next(
                row for row in events
                if row["event"] == "CANDIDATE_SERIES_FIRST_WORKER_LAUNCH"
                and row["candidate_id"] == candidate
            )
            if not capture["ordinal"] < guard_event["ordinal"] < first_launch["ordinal"]:
                raise AssertionError(f"candidate event order:{candidate}")
            between = [
                row for row in events
                if capture["ordinal"] < row["ordinal"] < first_launch["ordinal"]
                and row["event"].endswith("WORKER_LAUNCH")
                and row["candidate_id"] != candidate
            ]
            if between:
                raise AssertionError(f"different candidate launch before boundary:{candidate}")
        if len(execution["results"]) != plan["request_count"]:
            raise AssertionError("bounded callback launch cardinality")
        expected_rows = [
            (row, "UNTIMED_WARMUP")
            for row in assets.warmup_rows(
                workload, plan["compact_admission_result"]
            )
        ]
        expected_rows.extend(
            (row, "MEASURED")
            for row in assets.schedule_rows(
                workload, plan["selected_schedule_id"]
            )
        )
        expected_launches = []
        for request_index, (row, phase) in enumerate(expected_rows):
            expected_launches.append({
                "request_index": request_index,
                "candidate_id": row["backend"],
                "run_phase": phase,
                "selected_schedule_id": plan["selected_schedule_id"],
                "measured_repetition": (
                    0 if phase == "UNTIMED_WARMUP"
                    else int(row["measured_repetition"])
                ),
                "schedule_position": int(
                    row[
                        "warmup_position" if phase == "UNTIMED_WARMUP"
                        else "position"
                    ]
                ),
                "schedule_row_sha256": _schedule_row_sha(row),
                "timeout_seconds": int(assets.timeouts[(
                    workload, row["backend"]
                )]["timeout_seconds"]),
                "metric_contract_sha256": plan["static_launch_rows"][
                    request_index
                ]["request_identity"]["metric_contract_sha256"],
            })
        if state["launches"] != expected_launches:
            raise AssertionError("launch trace differs from frozen Williams authority")
        if len(state["guards"]) != plan["request_count"]:
            raise AssertionError("candidate-series guard cardinality")
        for candidate in first_order:
            expected_count = sum(
                row["candidate_id"] == candidate
                for row in plan["static_launch_rows"]
            )
            observed_count = sum(
                row["candidate_id"] == candidate for row in state["guards"]
            )
            if observed_count != expected_count:
                raise AssertionError(f"candidate guard count:{candidate}")
        run_outputs.append({
            "run_id": run_id,
            "plan": plan,
            "execution": execution,
            "candidate_captures": candidate_captures,
            "launches": state["launches"],
        })
        capture_by_candidate = {
            row["candidate_id"]: row for row in candidate_captures
        }
        for row in execution["dynamic_binding_rows"]:
            binding_evidence_rows.append({
                "run_id": run_id,
                "workload_id": row["workload_id"],
                "candidate_id": row["candidate_id"],
                "after_first_candidate_launch": capture_by_candidate[
                    row["candidate_id"]
                ]["after_first_candidate_launch"],
                "capture_sha256": row["capture_sha256"],
                "request_count": row["request_count"],
                "guard_callback_count": sum(
                    guard_row["candidate_id"] == row["candidate_id"]
                    for guard_row in state["guards"]
                ),
                "request_capture_sha256_exact": row[
                    "request_capture_sha256_exact"
                ],
                "fresh_available_memory_bytes": row[
                    "fresh_available_memory_bytes"
                ],
                "fresh_available_disk_bytes": row[
                    "fresh_available_disk_bytes"
                ],
            })

    first, second = run_outputs
    if (
        len(first["plan"]["allowed_candidate_ids"]) != 4
        or first["plan"]["request_count"] != 36
    ):
        raise AssertionError("FIX006 PASS-branch cadence cardinality drift")
    if first["plan"]["request_identity_sha256"] != second["plan"][
            "request_identity_sha256"]:
        raise AssertionError("dynamic resources changed static plan identity")
    if [row["capture_sha256"] for row in first["candidate_captures"]] == [
            row["capture_sha256"] for row in second["candidate_captures"]]:
        raise AssertionError("dynamic resource variants did not differ")
    if [
            row["request_identity"] for row in first["plan"]["static_launch_rows"]
            ] != [
            row["request_identity"] for row in second["plan"]["static_launch_rows"]
            ]:
        raise AssertionError("static launch tuple drift")
    write_tsv(
        evidence / "P16_DYNAMIC_CAPTURE_BINDING.tsv", binding_evidence_rows,
    )

    stop_state = {"first_launch_seen": False, "launches": []}

    def stop_provider(scope: str, _workload: str, candidate: str | None):
        if candidate is None:
            return dict(branch_resource)
        ceiling = maximum_memory if not stop_state["first_launch_seen"] else 1
        value = _capture_with_ceiling(
            base_resource, ceiling,
            f"FIX006_STOP_{scope}_{int(stop_state['first_launch_seen'])}",
        )
        value["available_local_disk_bytes"] = (
            maximum_disk if not stop_state["first_launch_seen"] else 1
        )
        return value

    stop_evidence = evidence / "P16_STOP_RUN"
    stop_plan = materialize_fresh_workload_plan(
        authority, assets, durability, workload_index, runtime, stop_evidence,
        stop_provider, activation, 0,
    )

    def stop_guard(request, _resource_path, resource,
                   _branch_resource_path, exact_branch_resource):
        try:
            return prelaunch_guard(
                authority, assets, request, runtime, resource, durability,
                exact_branch_resource,
            )
        except StopSignal as signal_value:
            if signal_value.stop_id == "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
                return {"status": "EXPECTED_NONAUTH_STOP_AFTER_EXACT_PREFLIGHT"}
            raise

    def stop_launch(request, request_index, _resource_path, _branch_path):
        stop_state["launches"].append({
            "request_index": request_index,
            "candidate_id": request["candidate_id"],
        })
        stop_state["first_launch_seen"] = True
        return _result_identity(request)

    try:
        execute_runtime_bound_workload(
            authority, assets, durability, stop_plan, stop_evidence,
            stop_provider, stop_plan["next_capture_ordinal"], activation,
            stop_guard, stop_launch,
        )
    except StopSignal as signal_value:
        if signal_value.stop_id != "SB_STOP_ADMISSION_MEMORY":
            raise
        observed_stop = signal_value.stop_id
    else:
        raise AssertionError("resource change did not stop before candidate B")
    if (
        len(stop_state["launches"]) != 1
        or stop_state["launches"][0]["candidate_id"]
        != stop_plan["candidate_first_launch_order"][0]
    ):
        raise AssertionError("resource STOP launched candidate B or later")
    stop_result = {
        "schema": "SplitAlignerR/ENGINE003StageBCandidateSeriesFreshStopEvidence/v1",
        "status": "PASS",
        "static_plan_identity_sha256": stop_plan["request_identity_sha256"],
        "matches_success_static_plan_identity": (
            stop_plan["request_identity_sha256"]
            == first["plan"]["request_identity_sha256"]
        ),
        "resource_changed_after_candidate_a": True,
        "candidate_a_id": stop_plan["candidate_first_launch_order"][0],
        "candidate_b_id": stop_plan["candidate_first_launch_order"][1],
        "candidate_b_observed_stop_id": observed_stop,
        "candidate_a_launch_count": 1,
        "candidate_b_launch_count": 0,
        "later_launch_count": 0,
        "physical_worker_launch_count": 0,
        "physical_allocation_count": 0,
    }
    stop_captures = sorted(
        (stop_evidence / "FRESH_RESOURCE_CAPTURES").glob("*.json")
    )
    if len(stop_captures) != 3:
        raise AssertionError("resource STOP capture lineage")
    candidate_a_capture = strict_json_load(stop_captures[1])
    candidate_b_capture = strict_json_load(stop_captures[2])
    stop_result.update({
        "candidate_a_capture_sha256": _sha(stop_captures[1].read_bytes()),
        "candidate_b_capture_sha256": _sha(stop_captures[2].read_bytes()),
        "candidate_a_memory_bytes": candidate_a_capture[
            "admission_memory_ceiling_bytes"
        ],
        "candidate_b_memory_bytes": candidate_b_capture[
            "admission_memory_ceiling_bytes"
        ],
        "candidate_a_disk_bytes": candidate_a_capture[
            "available_local_disk_bytes"
        ],
        "candidate_b_disk_bytes": candidate_b_capture[
            "available_local_disk_bytes"
        ],
    })
    if stop_result["matches_success_static_plan_identity"] is not True:
        raise AssertionError("resource STOP changed static plan")
    write_canonical_json(
        evidence / "P16_RESOURCE_CHANGE_PRELAUNCH_STOP.json", stop_result,
    )

    result = {
        "schema": "SplitAlignerR/ENGINE003StageBCandidateSeriesCadenceEvidence/v1",
        "status": "PASS",
        "workload_id": workload,
        "candidate_first_launch_order": first["plan"][
            "candidate_first_launch_order"
        ],
        "static_plan_identity_sha256": first["plan"][
            "request_identity_sha256"
        ],
        "static_plan_identical_across_dynamic_resources": True,
        "dynamic_capture_hashes_differ_across_runs": True,
        "resource_changed_after_candidate_a_before_candidate_b_capture": True,
        "resource_drop_stopped_candidate_b_before_launch": True,
        "candidate_series_capture_immediately_before_first_launch": True,
        "different_candidate_launch_between_capture_and_first_launch": False,
        "williams_launch_order_preserved": True,
        "request_count_per_run": first["plan"]["request_count"],
        "candidate_count": len(first["plan"]["allowed_candidate_ids"]),
        "physical_worker_launch_count": 0,
        "physical_allocation_count": 0,
    }
    write_canonical_json(evidence / "P16_CANDIDATE_SERIES_CADENCE.json", result)
    return result


def whole_tree_survivor_corpus(
        repo: Path, authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        resource_path: Path, durability_path: Path, runtime: Path,
        evidence: Path) -> list[Dict[str, Any]]:
    case_id = "ROOT_EXITS_GRANDCHILD_IGNORES"
    root = evidence / "P17_WHOLE_TREE_SURVIVOR" / case_id
    target = runtime / "p17-timeout" / case_id
    request = make_bounded_request(
        authority, assets, resource, durability, "COMPACT_IN_MEMORY", 1,
        target, evidence,
    )
    output = root / "worker.result.json"
    partial = output.with_suffix(".partial.json")
    pid_evidence = root / "pids.json"
    command = [
        sys.executable, "-B", str(INJECTED_WORKER),
        "--mode", "root-exits-grandchild-ignores",
        "--partial", str(partial), "--target", str(target),
        "--pid-evidence", str(pid_evidence),
        "--partial-state", "present", "--target-state", "absent",
    ]
    grace_values = []

    def bounded_waiter(process, seconds):
        grace_values.append(seconds)
        try:
            process.wait(timeout=0.50)
            return True
        except Exception as error:
            if type(error).__name__ != "TimeoutExpired":
                raise
            return False

    started = time.monotonic()
    try:
        launch_request(
            repo, runtime, resource_path, durability_path, request,
            root / "worker.request.json", output, root / "controller.log.txt",
            resource_path, bounded_waiter, command, 0.20,
        )
    except StopSignal as signal_value:
        if signal_value.stop_id != "SB_STOP_TIMEOUT":
            raise
    else:
        raise AssertionError("root-exits survivor case returned PASS")
    elapsed = time.monotonic() - started
    stop = strict_json_load(output)
    termination = stop["termination"]
    pids = strict_json_load(pid_evidence)
    descendant_live = _pid_is_live_non_zombie(pids["child_pid"])
    deadline = time.monotonic() + 2
    while descendant_live and time.monotonic() < deadline:
        time.sleep(0.02)
        descendant_live = _pid_is_live_non_zombie(pids["child_pid"])
    if (
        grace_values != [TIMEOUT_COOPERATIVE_GRACE_SECONDS]
        or termination["root_exited_during_grace"] is not True
        or termination["descendant_survived_grace"] is not True
        or termination["force_terminate_process_tree_executed"] is not True
        or termination["whole_process_tree_quiescent"] is not True
        or termination["survivor_pids_after_force"] != []
        or descendant_live
    ):
        raise AssertionError("whole-tree survivor completion")
    row = {
        "case_id": case_id,
        "root_pid": pids["parent_pid"],
        "grandchild_pid": pids["child_pid"],
        "root_exited_during_grace": termination["root_exited_during_grace"],
        "grandchild_survived_grace": termination["descendant_survived_grace"],
        "force_tree_kill": termination["force_terminate_process_tree_executed"],
        "survivors_after_force": len(termination["survivor_pids_after_force"]),
        "whole_tree_quiescent": termination["whole_process_tree_quiescent"],
        "grandchild_live_after_final_kill": descendant_live,
        "timeout_stop_object_written": stop["status"] == "SB_STOP_TIMEOUT",
        "controller_log_preserved": stop["controller_log_preserved"],
        "partial_evidence_status": stop["partial_evidence_status"],
        "decision_ledger_rows": 0,
        "later_request_launch_count": 0,
        "bounded_elapsed_milliseconds": int(elapsed * 1000),
        "status": "PASS",
    }
    write_tsv(evidence / "P17_WHOLE_TREE_SURVIVOR_CORPUS.tsv", [row])
    if target.exists() and target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    for path in sorted((runtime / "p17-timeout").glob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return [row]


def timeout_failure_mutation_corpus(evidence: Path) -> list[Dict[str, Any]]:
    """Prove probe and post-force uncertainty never returns quiescent PASS."""
    rows = []

    def expect_stop(case_id: str, callback) -> None:
        try:
            callback()
        except StopSignal as signal_value:
            if signal_value.stop_id != "SB_STOP_TIMEOUT_TERMINATION":
                raise
            rows.append({
                "case_id": case_id,
                "observed_stop_id": signal_value.stop_id,
                "observed_detail": signal_value.detail,
                "returned_quiescent": False,
                "decision_ledger_rows": 0,
                "later_request_launch_count": 0,
                "status": "PASS",
            })
            return
        raise AssertionError(f"timeout failure mutation returned:{case_id}")

    with mock.patch.object(
            controller.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("process-probe", 0.01)):
        expect_stop(
            "PROCESS_STATE_PROBE_TIMEOUT",
            lambda: controller._process_state_table(0.01),
        )
    with mock.patch.object(
            controller.subprocess, "run",
            return_value=subprocess.CompletedProcess(
                ["process-probe"], 1, stdout="", stderr="injected failure",
            )):
        expect_stop(
            "PROCESS_STATE_PROBE_NONZERO",
            lambda: controller._process_state_table(0.01),
        )
    with mock.patch.object(
            controller.subprocess, "run",
            return_value=subprocess.CompletedProcess(
                ["process-probe"], 0, stdout="malformed\n", stderr="",
            )):
        expect_stop(
            "PROCESS_STATE_PROBE_MALFORMED",
            lambda: controller._process_state_table(0.01),
        )

    class WindowsFakeProcess:
        pid = 434343

    windows_identity = {WindowsFakeProcess.pid: "123456789"}
    with (
        mock.patch.object(controller.os, "name", "nt"),
        mock.patch.object(
            controller, "_owned_tree_survivors",
            return_value=({WindowsFakeProcess.pid}, dict(windows_identity)),
        ),
        mock.patch.object(
            controller.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("taskkill", 0.01),
        ),
    ):
        expect_stop(
            "TASKKILL_TIMEOUT",
            lambda: controller._force_live_processes(
                WindowsFakeProcess(), {WindowsFakeProcess.pid},
                dict(windows_identity), 0.01,
            ),
        )

    class FakeProcess:
        pid = 424242

        @staticmethod
        def wait(timeout):
            return 0

    survivor = {FakeProcess.pid}
    identity = {FakeProcess.pid: "INJECTED_STABLE_IDENTITY"}
    with (
        mock.patch.object(
            controller, "_owned_tree_survivors",
            return_value=(set(survivor), dict(identity)),
        ),
        mock.patch.object(
            controller, "_force_live_processes",
            side_effect=lambda _process, _live, owned, _timeout: owned,
        ),
        mock.patch.object(controller, "PROCESS_TREE_FORCE_VERIFY_SECONDS", 0.03),
    ):
        expect_stop(
            "POST_FORCE_SURVIVOR_PERSISTS",
            lambda: controller._force_terminate_tree(
                FakeProcess(), dict(identity),
            ),
        )
    write_tsv(evidence / "P17_TIMEOUT_FAILURE_MUTATIONS.tsv", rows)
    return rows


def windows_pid_reuse_identity_corpus(evidence: Path) -> Dict[str, Any]:
    """Prove a reused historical parent PID cannot acquire a new child."""
    root_pid = 434340
    unrelated_child_pid = 434341

    class ExitedProcess:
        pid = root_pid

        @staticmethod
        def poll():
            return 0

    table = {
        root_pid: (1, 0, "LIVE", "NEW_ROOT_IDENTITY"),
        unrelated_child_pid: (
            root_pid, 0, "LIVE", "UNRELATED_CHILD_IDENTITY",
        ),
    }
    historical = {root_pid: "OLD_ROOT_IDENTITY"}
    with (
        mock.patch.object(controller.os, "name", "nt"),
        mock.patch.object(controller, "_process_state_table", return_value=table),
    ):
        live, owned = controller._owned_tree_survivors(
            ExitedProcess(), historical, 0.01,
        )
    if live or unrelated_child_pid in owned:
        raise AssertionError("Windows reused PID transferred process ownership")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBWindowsPidReuseSafety/v1",
        "status": "PASS",
        "historical_root_identity": historical[root_pid],
        "current_reused_root_identity": table[root_pid][3],
        "unrelated_child_identity": table[unrelated_child_pid][3],
        "unrelated_child_added_to_owned_set": unrelated_child_pid in owned,
        "unrelated_child_returned_live": unrelated_child_pid in live,
        "taskkill_invocation_count": 0,
        "decision_ledger_rows": 0,
        "later_request_launch_count": 0,
    }
    write_canonical_json(evidence / "P17_WINDOWS_PID_REUSE_SAFETY.json", result)
    return result


def legacy_execution_path_corpus(
        repo: Path, authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        resource_path: Path, durability_path: Path, runtime: Path,
        evidence: Path) -> Dict[str, Any]:
    """Prove the pre-FIX006 single-capture physical entry is retired."""
    legacy_runtime = runtime / "legacy-entry-never-created"
    plan = complete_execution_plan(
        authority, assets, resource, durability,
        legacy_runtime, evidence,
    )
    try:
        execute_authorized_plan(
            repo, legacy_runtime, evidence, resource_path, durability_path,
            plan,
        )
    except StopSignal as signal_value:
        if signal_value.stop_id != "SB_STOP_LEGACY_EXECUTION_PATH":
            raise
        result = {
            "schema": "SplitAlignerR/ENGINE003StageBLegacyExecutionStop/v1",
            "status": "PASS",
            "observed_stop_id": signal_value.stop_id,
            "observed_detail": signal_value.detail,
            "worker_launch_count": 0,
            "physical_allocation_count": 0,
            "decision_ledger_rows": 0,
            "fresh_protocol_required": True,
        }
        write_canonical_json(
            evidence / "P16_LEGACY_EXECUTION_PATH_STOP.json", result,
        )
        return result
    raise AssertionError("legacy single-capture execution path returned")


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    base = execute_fix005(args)
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    authority = ExecutionAuthority(repo, args.authorized_commit, args.authorized_tree)
    assets = FrozenAssets(authority)
    resource_path = evidence / "FRESH_RESOURCE_CAPTURE.json"
    durability_path = evidence / "DURABLE_PUBLISH_CAPABILITY.json"
    resource = strict_json_load(resource_path)
    durability = strict_json_load(durability_path)
    p16 = candidate_series_cadence_corpus(
        authority, assets, resource, durability, runtime, evidence,
    )
    p17 = whole_tree_survivor_corpus(
        repo, authority, assets, resource, durability, resource_path,
        durability_path, runtime, evidence,
    )
    p17_mutations = timeout_failure_mutation_corpus(evidence)
    p17_pid_reuse = windows_pid_reuse_identity_corpus(evidence)
    legacy_stop = legacy_execution_path_corpus(
        repo, authority, assets, resource, durability, resource_path,
        durability_path, runtime, evidence,
    )
    for path in sorted(runtime.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if any(runtime.iterdir()):
        raise StopSignal("SB_STOP_CLEANUP", "fix006_runtime_not_empty")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_BOUNDED_FIX006_PREFLIGHT_ONLY",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "direct_parent": args.direct_parent,
        "p09_p15_regression_status": base["status"],
        "p16_candidate_series_cadence_cases": p16["candidate_count"],
        "p17_whole_tree_survivor_cases": len(p17),
        "p17_failure_mutation_cases": len(p17_mutations),
        "p17_windows_pid_reuse_safety_cases": int(
            p17_pid_reuse["status"] == "PASS"
        ),
        "p16_legacy_execution_path_stop_cases": int(
            legacy_stop["status"] == "PASS"
        ),
        "large_complete_plan_requests": base["large_complete_plan_requests"],
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_clock": False,
        "stage_b_execution_authorized": False,
        "large_store_constructed": False,
        "over2gib_or_over4gib_constructed": False,
        "backend_selected": False,
        "production_source_changed": False,
        "runtime_root_empty_after_cleanup": True,
    }
    write_canonical_json(evidence / "FIX006_SUMMARY.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--authorized-commit", required=True)
    parser.add_argument("--authorized-tree", required=True)
    parser.add_argument("--direct-parent", required=True)
    args = parser.parse_args()
    result = execute(args)
    print(
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX006_"
        f"{result['status']} P16=PASS P17=PASS "
        "LARGE_WORKERS=0 LARGE_ALLOCATIONS=0"
    )


if __name__ == "__main__":
    main()
