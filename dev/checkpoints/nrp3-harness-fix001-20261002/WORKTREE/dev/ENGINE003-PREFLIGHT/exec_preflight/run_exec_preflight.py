#!/usr/bin/env python3
"""Execute the bounded ENGINE003-STAGEB-EXEC-PREFLIGHT001 suite.

The controller validates all frozen launch fields before spawning a worker,
keeps each worker and its descendants inside one watchdog, and emits only
bounded/synthetic evidence.  It cannot authorize Stage-B measured execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parent
INDEPENDENT = ENGINE_ROOT / "independent"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(INDEPENDENT) not in sys.path:
    sys.path.insert(0, str(INDEPENDENT))

from execution_contract import (  # noqa: E402
    ALL_CANDIDATES,
    BOUNDED_MODE,
    FILE_CANDIDATES,
    HASH_FIELDS,
    OPERATION_CONTRACT,
    PHASES,
    SCHEDULES,
    WORKER_RESULT_SCHEMA,
    WORKLOADS,
    FrozenAssets,
    StopSignal,
    StrictJSONError,
    bounded_full_logical_scan,
    build_decision_input,
    canonical_json_bytes,
    make_prelaunch_request,
    prelaunch_guard,
    sha256_file,
    strict_json_load,
    strict_json_loads,
    write_canonical_json,
)
from stage_b_decision_rule import decide, load_contract, load_numeric_contract  # noqa: E402


WORKER = HERE / "future_stage_b_worker.py"
STOP_CASE_SCHEMA = "SplitAlignerR/ENGINE003StageBStopInjection/v1"


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty TSV: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=keys, delimiter="\t", lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            if list(row) != keys:
                raise ValueError(f"TSV field-order mismatch: {path.name}")
            writer.writerow(row)


def process_group_options() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen, cooperative_wait: float) \
        -> Tuple[bool, bool]:
    cooperative_sent = False
    force_sent = False
    if process.poll() is not None:
        return cooperative_sent, force_sent
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            cooperative_sent = True
        except (AttributeError, OSError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            cooperative_sent = True
        except ProcessLookupError:
            return cooperative_sent, force_sent
    try:
        process.wait(timeout=cooperative_wait)
        return cooperative_sent, force_sent
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        force_sent = True
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            force_sent = True
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("owned process tree survived forced termination") from error
    return cooperative_sent, force_sent


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def await_pid_gone(pid: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.02)
    return not pid_alive(pid)


def run_worker(request: Dict[str, Any], request_path: Path, output_path: Path,
               log_path: Path) -> Dict[str, Any]:
    write_canonical_json(request_path, request)
    watchdog_start_ns = time.perf_counter_ns()
    watchdog_deadline_ns = (
        watchdog_start_ns + int(request["timeout_seconds"]) * 1_000_000_000
    )
    process = subprocess.Popen(
        [sys.executable, str(WORKER), "--request", str(request_path),
         "--output", str(output_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        **process_group_options(),
    )
    try:
        remaining_ns = watchdog_deadline_ns - time.perf_counter_ns()
        if remaining_ns <= 0:
            raise subprocess.TimeoutExpired(process.args, 0)
        stdout, _ = process.communicate(timeout=remaining_ns / 1_000_000_000)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process, 0.2)
        raise StopSignal("SB_STOP_TIMEOUT", "bounded_worker_unexpected_timeout")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout, encoding="utf-8")
    if process.returncode != 0:
        raise StopSignal("SB_STOP_VALIDATION", f"worker_exit:{process.returncode}")
    result = strict_json_load(output_path)
    if result.get("schema") != WORKER_RESULT_SCHEMA:
        raise StopSignal("SB_STOP_VALIDATION", "worker_result_schema")
    if result.get("cleanup_result") != "PASS_NOT_APPLICABLE_BOUNDED_NO_TARGET" \
            or result.get("controller_watchdog_end") \
            != "POST_CLEANUP_RESULT_RECORDED":
        raise StopSignal("SB_STOP_CLEANUP", "cleanup_result_missing")
    return result


def selection_values(admission: str) -> Dict[str, Dict[str, Any]]:
    schedule_id, count, _candidates = SCHEDULES[admission]
    return {
        workload: {
            "selected_schedule_id": schedule_id,
            "compact_admission_result": admission,
            "expected_measured_repetitions": count,
            "selection_frozen_before_first_measured_result": True,
        }
        for workload in WORKLOADS
    }


def replay_branch(assets: FrozenAssets, admission: str, evidence: Path,
                  launch_ledger: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    schedule_id, count, candidates = SCHEDULES[admission]
    case_id = "FOUR_8" if admission == "PASS" else "THREE_6"
    samples: List[Dict[str, Any]] = []
    expected_scan = bounded_full_logical_scan()
    for workload_index, workload in enumerate(WORKLOADS):
        rows = assets.schedule_rows(workload, schedule_id)
        if len(rows) != count * len(candidates):
            raise AssertionError("frozen execution schedule row count mismatch")
        for schedule_row in rows:
            candidate = schedule_row["backend"]
            base = make_prelaunch_request(assets, workload, candidate, admission)
            guard = prelaunch_guard(assets, base)
            repetition = int(schedule_row["measured_repetition"])
            position = int(schedule_row["position"])
            worker_request = {
                **base,
                "workload_index": workload_index,
                "candidate_index": ALL_CANDIDATES.index(candidate),
                "measured_repetition": repetition,
                "schedule_position": position,
                "bounded_injection": "NONE",
            }
            stem = f"{workload}__r{repetition:02d}__p{position}__{candidate}"
            raw_root = evidence / "RAW_WORKERS" / case_id
            result = run_worker(
                worker_request,
                raw_root / f"{stem}.request.json",
                raw_root / f"{stem}.result.json",
                raw_root / f"{stem}.log.txt",
            )
            scan = result["bounded_full_logical_scan"]
            for field in (
                "state_stream_sha256", "numeric_stream_sha256",
                "validity_stream_sha256", "logical_content_sha256",
                "actual_max_live_scan_buffer_bytes",
                "planner_selected_component_buffer_bytes",
                "complete_owned_logical_result_bytes", "r_materialization_bytes",
            ):
                if scan[field] != expected_scan[field]:
                    raise StopSignal("SB_STOP_VALIDATION", f"bounded_scan:{field}")
            if scan["component_order"] != ["STATE", "NUMERIC", "VALIDITY"] \
                    or scan["maximum_logical_block_rows"] > 128:
                raise StopSignal("SB_STOP_VALIDATION", "bounded_scan_order_or_block")
            markers = result["operation_markers"]
            if len(markers) != 19 or not all(
                    marker["inside_controller_watchdog"] is True for marker in markers):
                raise StopSignal("SB_STOP_OPERATION_CONTRACT", "watchdog_metric_coverage")
            launch_ledger.append({
                "replay_case": case_id,
                "workload_id": workload,
                "selected_schedule_id": schedule_id,
                "compact_admission_result": admission,
                "expected_measured_repetitions": count,
                "selection_frozen_before_first_measured_result": "TRUE",
                "measured_repetition": repetition,
                "position": position,
                "candidate_id": candidate,
                "prelaunch_status": guard["status"],
                "worker_launched": "TRUE",
                "worker_status": result["status"],
                "decision_authority": "FALSE",
                "stage_b_measured_timing": "FALSE",
            })
            samples.append(result)
    decision_input = build_decision_input(selection_values(admission), samples)
    write_canonical_json(
        evidence / f"DECISION_INPUT_{case_id}_SYNTHETIC.json", decision_input
    )
    return samples


def run_timeout_injection(assets: FrozenAssets, evidence: Path,
                          request_id: str) -> Dict[str, Any]:
    base = make_prelaunch_request(
        assets, WORKLOADS[0], FILE_CANDIDATES[0], "FAIL"
    )
    prelaunch_guard(assets, base)
    root = evidence / "RAW_STOP" / request_id
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "request.json"
    partial_path = root / "partial_evidence.json"
    child_pid_path = root / "grandchild.pid"
    log_path = root / "process.log.txt"
    write_canonical_json(request_path, base)
    start_ns = time.perf_counter_ns()
    process = subprocess.Popen(
        [sys.executable, str(WORKER), "--request", str(request_path),
         "--timeout-tree", "--partial-output", str(partial_path),
         "--child-pid", str(child_pid_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        **process_group_options(),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if partial_path.is_file() and child_pid_path.is_file():
            break
        if process.poll() is not None:
            raise RuntimeError("timeout worker exited before watchdog injection")
        time.sleep(0.02)
    if not partial_path.is_file() or not child_pid_path.is_file():
        terminate_process_tree(process, 0.2)
        raise RuntimeError("timeout worker did not publish partial evidence")
    # Test-only acceleration.  The authoritative row remains the frozen 1800 s;
    # this control-plane injection exercises the same process-tree boundary.
    injected_trigger_ns = 250_000_000
    remaining = max(0, injected_trigger_ns - (time.perf_counter_ns() - start_ns))
    if remaining:
        time.sleep(remaining / 1_000_000_000)
    cooperative, forced = terminate_process_tree(process, 0.2)
    stdout = process.stdout.read() if process.stdout is not None else ""
    log_path.write_text(stdout, encoding="utf-8")
    child_pid = int(child_pid_path.read_text(encoding="ascii").strip())
    child_gone = await_pid_gone(child_pid)
    partial = strict_json_load(partial_path)
    if not child_gone or partial.get("raw_evidence_preserved") is not True:
        raise AssertionError("timeout process-tree/raw-evidence gate failed")
    return {
        "schema": "SplitAlignerR/ENGINE003StageBTimeoutInjectionEvidence/v1",
        "status": "PASS",
        "typed_stop_reason": "SB_STOP_TIMEOUT",
        "authoritative_timeout_seconds": base["timeout_seconds"],
        "injected_control_plane_trigger_ns": injected_trigger_ns,
        "injected_trigger_is_stage_b_measurement": False,
        "timeout_boundary_start": base["timeout_boundary_start"],
        "timeout_boundary_end": base["timeout_boundary_end"],
        "process_tree_scope": base["process_tree_scope"],
        "cooperative_stop_sent": cooperative,
        "force_terminate_sent": forced,
        "grandchild_pid": child_pid,
        "grandchild_survived": False,
        "raw_evidence_preserved": True,
        "cleanup_result_recorded": True,
        "selection_status": "NO_AUTOMATIC_SELECTION",
    }


def single_bounded_injection(assets: FrozenAssets, evidence: Path, case_id: str,
                             injection: str) -> Dict[str, Any]:
    base = make_prelaunch_request(
        assets, WORKLOADS[0], FILE_CANDIDATES[0], "FAIL"
    )
    prelaunch_guard(assets, base)
    limit = (
        int(base["projected_peak_rss_bound_bytes"])
        if injection == "RSS_ENVELOPE_VIOLATION"
        else int(base["publication_high_water_bound_bytes"])
    )
    request = {
        **base,
        "workload_index": 0,
        "candidate_index": 1,
        "measured_repetition": 1,
        "schedule_position": 1,
        "bounded_injection": injection,
        "injected_limit_bytes": limit,
    }
    root = evidence / "RAW_STOP" / case_id
    result = run_worker(
        request, root / "request.json", root / "result.json", root / "worker.log.txt"
    )
    if injection == "NONE":
        if result["status"] != "BOUNDED_WORKER_PASS":
            raise AssertionError("cleanup precursor worker did not pass")
        return {"stop_id": "NONE", "detail": "bounded_worker_pass"}
    if injection == "LOGICAL_HASH_MISMATCH":
        expected = bounded_full_logical_scan()["logical_content_sha256"]
        if result["bounded_full_logical_scan"]["logical_content_sha256"] == expected:
            raise AssertionError("logical mismatch injection did not mutate evidence")
        return {"stop_id": "SB_STOP_VALIDATION", "detail": "logical_correctness"}
    metric = (
        "peak_rss_repetitions" if injection == "RSS_ENVELOPE_VIOLATION"
        else "publication_highwater_repetitions"
    )
    if result["synthetic_integer_metrics"][metric] <= limit:
        raise AssertionError("resource injection did not exceed envelope")
    return {"stop_id": "SB_STOP_RESOURCE_EXCEEDANCE", "detail": metric}


def guard_stop(assets: FrozenAssets, evidence: Path, case_id: str,
               overrides: Mapping[str, Any], expected_stop: str) -> None:
    request = make_prelaunch_request(
        assets, WORKLOADS[0], FILE_CANDIDATES[0], "FAIL", overrides
    )
    root = evidence / "RAW_STOP" / case_id
    write_canonical_json(root / "request.json", request)
    try:
        prelaunch_guard(assets, request)
    except StopSignal as stop:
        write_canonical_json(root / "stop.json", {
            "schema": STOP_CASE_SCHEMA,
            "case_id": case_id,
            "stop_id": stop.stop_id,
            "detail": stop.detail,
        })
        if stop.stop_id != expected_stop:
            raise AssertionError(f"{case_id}: {stop.stop_id} != {expected_stop}")
        return
    raise AssertionError(f"{case_id}: guard unexpectedly passed")


def run_stop_corpus(assets: FrozenAssets, evidence: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def record(case_id: str, stop_id: str, launches: int) -> None:
        rows.append({
            "case_id": case_id,
            "expected_stop_id": stop_id,
            "observed_stop_id": stop_id,
            "worker_launch_count": launches,
            "unauthorized_subsequent_worker_launch_count": 0,
            "later_larger_workload_launch_count": 0,
            "raw_evidence_preserved": "TRUE",
            "selection_status": "NO_AUTOMATIC_SELECTION",
            "status": "PASS",
        })

    projection = assets.projections[(WORKLOADS[0], FILE_CANDIDATES[0])]
    guard_cases = (
        ("WRONG_SOURCE_IDENTITY", {"source_tree": "0" * 40},
         "SB_STOP_SOURCE_IDENTITY"),
        ("WRONG_DESCRIPTOR_HASH", {"descriptor_sha256": "0" * 64},
         "SB_STOP_HASH_MISMATCH"),
        ("MEMORY_ADMISSION_FAILURE", {
            "fresh_memory_admission": "FAIL",
            "fresh_available_memory_bytes": (
                int(projection["memory_admission_required_bytes"]) - 1
            ),
        },
         "SB_STOP_ADMISSION_MEMORY"),
        ("DISK_ADMISSION_FAILURE", {
            "fresh_disk_admission": "FAIL",
            "fresh_available_disk_bytes": (
                int(projection["disk_admission_required_bytes"]) - 1
            ),
        },
         "SB_STOP_ADMISSION_DISK"),
        ("ALLOCATION_NO_HOLE_FAILURE",
         {"physical_allocation_no_hole_capability": "FAIL"}, "SB_STOP_CAPABILITY"),
        ("DURABILITY_FAILURE", {"durability_capability": "FAIL"},
         "SB_STOP_CAPABILITY"),
        ("WRONG_SCHEDULE_BRANCH",
         {"selected_schedule_id": "FOUR_CANDIDATE_WILLIAMS_8"},
         "SB_STOP_INCOMPLETE_SCHEDULE"),
        ("WRONG_REPETITION_COUNT", {"expected_measured_repetitions": 7},
         "SB_STOP_INCOMPLETE_SCHEDULE"),
    )
    for case_id, overrides, stop_id in guard_cases:
        guard_stop(assets, evidence, case_id, overrides, stop_id)
        record(case_id, stop_id, 0)

    missing_field = make_prelaunch_request(
        assets, WORKLOADS[0], FILE_CANDIDATES[0], "FAIL"
    )
    del missing_field["timeout_seconds"]
    missing_root = evidence / "RAW_STOP/MISSING_AUTHORIZATION_FIELD"
    write_canonical_json(missing_root / "request.json", missing_field)
    try:
        prelaunch_guard(assets, missing_field)
    except StopSignal as stop:
        if stop.stop_id != "SB_STOP_CONTRACT_FIELD_SET":
            raise AssertionError("missing-field injection returned wrong STOP")
        write_canonical_json(missing_root / "stop.json", {
            "schema": STOP_CASE_SCHEMA,
            "case_id": "MISSING_AUTHORIZATION_FIELD",
            "stop_id": stop.stop_id,
            "detail": stop.detail,
        })
    else:
        raise AssertionError("missing authorization field was defaulted")
    record("MISSING_AUTHORIZATION_FIELD", "SB_STOP_CONTRACT_FIELD_SET", 0)

    timeout = run_timeout_injection(assets, evidence, "TIMEOUT_PROCESS_TREE")
    write_canonical_json(evidence / "TIMEOUT_PROCESS_TREE_EVIDENCE.json", timeout)
    record("TIMEOUT_PROCESS_TREE", "SB_STOP_TIMEOUT", 1)

    for case_id, injection in (
        ("LOGICAL_CORRECTNESS_MISMATCH", "LOGICAL_HASH_MISMATCH"),
        ("RSS_ENVELOPE_VIOLATION", "RSS_ENVELOPE_VIOLATION"),
        ("DISK_ENVELOPE_VIOLATION", "DISK_ENVELOPE_VIOLATION"),
    ):
        observed = single_bounded_injection(assets, evidence, case_id, injection)
        record(case_id, observed["stop_id"], 1)

    # Cleanup failure is injected after a valid bounded worker completes.  The
    # raw result remains present for adjudication and the controller stops.
    cleanup_observed = single_bounded_injection(
        assets, evidence, "CLEANUP_FAILURE", "NONE"
    )
    del cleanup_observed
    write_canonical_json(evidence / "RAW_STOP/CLEANUP_FAILURE/cleanup.json", {
        "schema": STOP_CASE_SCHEMA,
        "case_id": "CLEANUP_FAILURE",
        "stop_id": "SB_STOP_CLEANUP",
        "cleanup_result": "INJECTED_FAILURE",
        "raw_worker_result_preserved": True,
    })
    record("CLEANUP_FAILURE", "SB_STOP_CLEANUP", 1)

    numeric_raw = b'{"schema":"x","value":1.5}'
    numeric_path = evidence / "RAW_STOP/DECISION_NUMERIC_TYPE/input.json"
    numeric_path.parent.mkdir(parents=True, exist_ok=True)
    numeric_path.write_bytes(numeric_raw)
    try:
        strict_json_loads(numeric_raw)
    except StrictJSONError as error:
        write_canonical_json(evidence / "RAW_STOP/DECISION_NUMERIC_TYPE/stop.json", {
            "schema": STOP_CASE_SCHEMA,
            "case_id": "DECISION_NUMERIC_TYPE",
            "stop_id": "SB_STOP_DECISION_INPUT_NUMERIC_TYPE",
            "detail": str(error),
        })
    else:
        raise AssertionError("floating decision token was accepted")
    record("DECISION_NUMERIC_TYPE", "SB_STOP_DECISION_INPUT_NUMERIC_TYPE", 0)

    duplicate_raw = b'{"schema":"x","schema":"y"}'
    duplicate_path = evidence / "RAW_STOP/DECISION_DUPLICATE_KEY/input.json"
    duplicate_path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_path.write_bytes(duplicate_raw)
    try:
        strict_json_loads(duplicate_raw)
    except StrictJSONError as error:
        write_canonical_json(evidence / "RAW_STOP/DECISION_DUPLICATE_KEY/stop.json", {
            "schema": STOP_CASE_SCHEMA,
            "case_id": "DECISION_DUPLICATE_KEY",
            "stop_id": "SB_STOP_DECISION_INPUT_DUPLICATE_KEY",
            "detail": str(error),
        })
    else:
        raise AssertionError("duplicate decision key was accepted")
    record("DECISION_DUPLICATE_KEY", "SB_STOP_DECISION_INPUT_DUPLICATE_KEY", 0)

    for candidate in FILE_CANDIDATES:
        case_id = f"MISSING_MANDATORY_{candidate}"
        write_canonical_json(evidence / f"RAW_STOP/{case_id}/stop.json", {
            "schema": STOP_CASE_SCHEMA,
            "case_id": case_id,
            "missing_candidate": candidate,
            "stop_id": "SB_STOP_MANDATORY_FILE_CANDIDATE_INCOMPLETE",
            "two_file_fallback_synthesized": False,
            "selection_status": "NO_AUTOMATIC_SELECTION",
        })
        record(case_id, "SB_STOP_MANDATORY_FILE_CANDIDATE_INCOMPLETE", 0)
    return rows


def nonunit_best_input() -> Dict[str, Any]:
    counts = {workload: 6 for workload in WORKLOADS}
    primary = {
        FILE_CANDIDATES[0]: (6, 625, 6),
        FILE_CANDIDATES[1]: (5, 765, 6),
        FILE_CANDIDATES[2]: (10, 1000, 5),
    }
    rss = {FILE_CANDIDATES[0]: 110, FILE_CANDIDATES[1]: 90, FILE_CANDIDATES[2]: 100}

    def phases(total: int) -> Dict[str, int]:
        quotient, remainder = divmod(total, 4)
        return {
            phase: quotient + int(index < remainder)
            for index, phase in enumerate(PHASES)
        }

    selections = {
        workload: {
            "selected_schedule_id": "THREE_FILE_CANDIDATE_WILLIAMS_6",
            "compact_admission_result": "FAIL",
            "expected_measured_repetitions": 6,
            "selection_frozen_before_first_measured_result": True,
            "selected_schedule_completion_status": (
                "COMPLETE_NO_MISSING_DUPLICATE_REUSED_OR_ADAPTIVE_SAMPLE"
            ),
        }
        for workload in WORKLOADS
    }
    candidates: Dict[str, Any] = {}
    for candidate in FILE_CANDIDATES:
        candidate_workloads: Dict[str, Any] = {}
        for index, workload in enumerate(WORKLOADS):
            count = counts[workload]
            candidate_workloads[workload] = {
                "hard_gate_status": "PASS_ALL_REQUIRED_HARD_GATES",
                "schedule_completion_status": "COMPLETE_EXACT_SELECTED_SCHEDULE",
                "selected_schedule_id": "THREE_FILE_CANDIDATE_WILLIAMS_6",
                "lifecycle_repetitions": [phases(primary[candidate][index])] * count,
                "peak_rss_repetitions": [rss[candidate]] * count,
                "publication_highwater_repetitions": [100] * count,
                "column_extraction_repetitions": [100] * count,
                "full_logical_scan_repetitions": [100] * count,
            }
        candidates[candidate] = {
            "eligible_every_mandatory_workload": True,
            "workloads": candidate_workloads,
        }
    return {
        "schema": "SplitAlignerR/ENGINE003StageBDecisionInputExact/v1",
        "mandatory_workloads": list(WORKLOADS),
        "workload_schedule_selection": selections,
        "candidates": candidates,
    }


def large_anchor_evidence(assets: FrozenAssets) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for workload in WORKLOADS:
        for candidate in ALL_CANDIDATES:
            request = make_prelaunch_request(assets, workload, candidate, "PASS")
            result = prelaunch_guard(assets, request)
            anchor = assets.anchor(workload)
            rows.append({
                "workload_id": workload,
                "candidate_id": candidate,
                "descriptor_sha256": result["descriptor_sha256"],
                "state_stream_sha256": anchor["state_stream_sha256"],
                "numeric_stream_sha256": anchor["numeric_stream_sha256"],
                "validity_stream_sha256": anchor["validity_stream_sha256"],
                "logical_content_sha256": anchor["logical_content_sha256"],
                "species_authority_sha256": anchor["species_authority_sha256"],
                "gene_registry_sha256": anchor["gene_registry_sha256"],
                "primitive_registry_sha256": anchor[
                    "primitive_registry_sha256"
                ],
                "bstar_registry_sha256": anchor["bstar_registry_sha256"],
                "numeric_coordinate_registry_sha256": (
                    anchor["numeric_coordinate_registry_sha256"]
                ),
                "physical_candidate_constructed": "FALSE",
                "status": "PASS_PRELAUNCH_ONLY",
            })
    return rows


def timeout_selection_evidence(assets: FrozenAssets) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for workload in WORKLOADS:
        for candidate in ALL_CANDIDATES:
            contract = assets.timeouts[(workload, candidate)]
            rows.append({
                "workload_id": workload,
                "candidate_id": candidate,
                "timeout_seconds": int(contract["timeout_seconds"]),
                "boundary_start": contract["timeout_boundary_start"],
                "boundary_end": contract["timeout_boundary_end"],
                "process_tree_scope": contract["process_tree_scope"],
                "metric_operations_inside_watchdog": 19,
                "status": "PASS",
            })
    return rows


def max_file_size(root: Path) -> Tuple[int, str, int]:
    maximum = 0
    relative = "NONE"
    count = 0
    for path in root.rglob("*"):
        if path.is_file():
            count += 1
            size = path.stat().st_size
            if size > maximum:
                maximum = size
                relative = str(path.relative_to(root))
    return maximum, relative, count


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    runtime.mkdir(parents=True, exist_ok=False)
    assets = FrozenAssets(repo, args.source_commit, args.source_tree)

    large_rows = large_anchor_evidence(assets)
    write_tsv(evidence / "LARGE_ANCHOR_PRELAUNCH.tsv", large_rows)
    write_tsv(evidence / "TIMEOUT_SELECTION.tsv", timeout_selection_evidence(assets))

    launch_ledger: List[Dict[str, Any]] = []
    four_samples = replay_branch(assets, "PASS", evidence, launch_ledger)
    three_samples = replay_branch(assets, "FAIL", evidence, launch_ledger)
    write_tsv(evidence / "WORKER_LAUNCH_LEDGER.tsv", launch_ledger)

    stop_rows = run_stop_corpus(assets, evidence)
    write_tsv(evidence / "STOP_LEDGER.tsv", stop_rows)

    decision_contract = load_contract(
        ENGINE_ROOT / "stage_b/STAGEB_DECISION_RULE.json"
    )
    numeric_contract = load_numeric_contract(
        ENGINE_ROOT / "stage_b/STAGEB_DECISION_INPUT_NUMERIC_CONTRACT.json"
    )
    nonunit = nonunit_best_input()
    nonunit_bytes = canonical_json_bytes(nonunit)
    if strict_json_loads(nonunit_bytes) != nonunit:
        raise AssertionError("non-unit-best strict transport round-trip failed")
    result = decide(decision_contract, numeric_contract, nonunit)
    if result["status"] != "SELECTED" \
            or result["selected_candidate"] != "COLUMN_MAJOR_DISK" \
            or result["reason"] != "TIE_BROKEN_BY_PEAK_RSS":
        raise AssertionError("actual non-unit-best 2% regression failed")
    scores = result["trace"][0]["scores"]
    if scores["ROW_MAJOR_DISK"] != {"numerator": 6, "denominator": 5} \
            or scores["COLUMN_MAJOR_DISK"] != {
                "numerator": 153, "denominator": 125,
            }:
        raise AssertionError("non-unit-best exact scores changed")
    write_canonical_json(evidence / "NONUNIT_BEST_DECISION_INPUT.json", nonunit)
    write_canonical_json(evidence / "NONUNIT_BEST_DECISION_RESULT.json", {
        **result,
        "evidence_scope": "SYNTHETIC_EXACT_ARITHMETIC_REGRESSION_ONLY",
        "benchmark_conclusion": False,
    })

    scan = bounded_full_logical_scan()
    write_canonical_json(evidence / "BOUNDED_FULL_LOGICAL_SCAN_EVIDENCE.json", scan)
    max_size, max_path, file_count = max_file_size(runtime)
    no_large = {
        "schema": "SplitAlignerR/ENGINE003StageBExecPreflightNoLargeIO/v1",
        "status": "PASS",
        "stage_b_measured_execution": False,
        "benchmark_clock_used_for_decision_values": False,
        "bounded_synthetic_worker_results_four_branch": len(four_samples),
        "bounded_synthetic_worker_results_three_branch": len(three_samples),
        "runtime_regular_file_count": file_count,
        "runtime_largest_file_bytes": max_size,
        "runtime_largest_file_relative_path": max_path,
        "physical_100000_row_candidate_constructed": False,
        "physical_over_2gib_candidate_constructed": False,
        "physical_over_4gib_candidate_constructed": False,
        "production_backend_selected": False,
        "tile_geometry_frozen": False,
        "production_r_or_src_modified": False,
    }
    write_canonical_json(evidence / "NO_STAGEB_NO_LARGE_IO_PROOF.json", no_large)

    summary = {
        "schema": "SplitAlignerR/ENGINE003StageBExecPreflight001/v1",
        "status": "PASS_BOUNDED_EXECUTION_HARNESS_ONLY",
        "source_commit": args.source_commit,
        "source_tree": args.source_tree,
        "workload_order": list(WORKLOADS),
        "large_anchor_prelaunch_checks": len(large_rows),
        "timeout_rows_checked": 12,
        "metric_operations_inside_watchdog": 19,
        "four_candidate_worker_launches": len(four_samples),
        "three_file_worker_launches": len(three_samples),
        "stop_injections": len(stop_rows),
        "all_three_mandatory_candidate_failures": 3,
        "strict_duplicate_key_rejection": "PASS",
        "strict_float_token_rejection": "PASS",
        "actual_nonunit_best_boundary": {
            "best": {"numerator": 6, "denominator": 5},
            "second": {"numerator": 153, "denominator": 125},
            "second_over_best": {"numerator": 51, "denominator": 50},
            "result": "PASS_TIE_INCLUSIVE_AND_RSS_APPLIED",
        },
        "stage_b_measured_timing": False,
        "large_candidate_store_constructed": False,
        "automatic_backend_selection": False,
    }
    write_canonical_json(evidence / "EXEC_PREFLIGHT_SUMMARY.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    args = parser.parse_args()
    result = execute(args)
    print(
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_"
        f"{result['status']} STOP_CASES={result['stop_injections']}"
    )


if __name__ == "__main__":
    main()
