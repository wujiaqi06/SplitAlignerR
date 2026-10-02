#!/usr/bin/env python3
"""Run FIX005 P12-P15 bounded control-plane certification."""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
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
    ALL_CANDIDATES, FILE_CANDIDATES, WORKLOADS, ExecutionAuthority,
    FrozenAssets, StopSignal, canonical_json_bytes, strict_json_load,
    write_canonical_json,
)
from run_fix002_preflight import write_tsv  # noqa: E402
from run_fix004_preflight import execute as execute_fix004  # noqa: E402
from stage_b_authorization import (  # noqa: E402
    AUTHORIZATION_SCHEMA, make_authorization_artifact,
)
from stage_b_controller import (  # noqa: E402
    ProcessTreeRssSampler, TIMEOUT_COOPERATIVE_GRACE_SECONDS,
    evaluate_resource_hard_gate, launch_request, process_group_options,
)
from stage_b_durable_publish import (  # noqa: E402
    TREE_HASH_CHUNK_BYTES, tree_sha256,
)
from stage_b_orchestrator import (  # noqa: E402
    adaptive_execution_protocol, _materialize_fix005_batched_evidence_plan,
    validate_adaptive_execution_protocol,
)
from stage_b_runtime_contract import (  # noqa: E402
    make_bounded_request, prelaunch_guard,
)


SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBExecPreflightFix005Summary/v1"
INJECTED_WORKER = HERE / "fix005_injected_worker.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def legacy_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "little"))
        digest.update(relative)
        digest.update(len(raw).to_bytes(8, "little"))
        digest.update(raw)
    return digest.hexdigest()


class TrackingReader:
    def __init__(self, path: Path, requests: list[int]):
        self.handle = path.open("rb")
        self.requests = requests

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.handle.close()

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        if size < 0:
            raise AssertionError("unbounded read request")
        return self.handle.read(size)


def streaming_hash_corpus(runtime: Path, evidence: Path) -> Dict[str, Any]:
    root = runtime / "p12-streaming-hash"
    root.mkdir(parents=True, exist_ok=False)
    (root / "a.txt").write_bytes(b"tiny\x00payload\n")
    nested = root / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(bytes(range(251)) * 17)
    large = nested / "large.bin"
    with large.open("wb") as handle:
        chunk = bytes((value % 251 for value in range(64 * 1024)))
        for _ in range(49):
            handle.write(chunk)
        handle.write(b"bounded-tail")
    legacy = legacy_tree_sha256(root)
    requests: list[int] = []

    def open_tracking(path: Path):
        return TrackingReader(path, requests)

    with mock.patch.object(
            Path, "read_bytes",
            side_effect=AssertionError("Path.read_bytes must not be called")):
        streamed = tree_sha256(
            root, TREE_HASH_CHUNK_BYTES, open_tracking,
        )
        repeated = tree_sha256(
            root, TREE_HASH_CHUNK_BYTES, open_tracking,
        )
    if not requests or min(requests) < 0 or max(requests) > TREE_HASH_CHUNK_BYTES:
        raise AssertionError("streaming tree hash escaped frozen chunk")
    if streamed != legacy or repeated != legacy:
        raise AssertionError("streaming tree digest changed grammar")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBStreamingTreeHashEvidence/v1",
        "status": "PASS",
        "tree_hash_chunk_bytes": TREE_HASH_CHUNK_BYTES,
        "legacy_tree_sha256": legacy,
        "streaming_tree_sha256": streamed,
        "repeated_streaming_tree_sha256": repeated,
        "tiny_and_multicomponent_exact_equality": True,
        "large_test_file_bytes": large.stat().st_size,
        "maximum_read_request_bytes": max(requests),
        "read_request_count": len(requests),
        "path_read_bytes_call_count": 0,
        "digest_grammar": "U64LE_PATH_LENGTH;PATH;U64LE_FILE_LENGTH;FILE_BYTES",
    }
    write_canonical_json(evidence / "P12_STREAMING_TREE_HASH.json", result)
    shutil.rmtree(root)
    return result


def _minimal_result(peak: int, temporary: int, final: int, publication: int) -> Dict[str, Any]:
    return {
        "operation_integer_values": {
            "peak_rss": peak,
            "temporary_physical_disk": temporary,
            "final_physical_disk": final,
            "publication_high_water": publication,
        },
        "integer_metrics": {"peak_rss_repetitions": peak},
        "operation_status": {"peak_rss": "MEASURED_INTEGER_BYTES"},
    }


def _minimal_request(memory: int = 64 * 1024 * 1024,
                     disk: int = 16 * 1024 * 1024) -> Dict[str, Any]:
    return {
        "memory_admission_required_bytes": memory,
        "disk_admission_required_bytes": disk,
        "publication_high_water_bound_bytes": disk,
    }


def resource_hard_gate_corpus(evidence: Path) -> list[Dict[str, Any]]:
    cases = [
        ("MEASURED_RSS_EXCEEDS_ADMISSION", 8 * 1024 * 1024,
         512 * 1024 * 1024, 1, 1, 1, "PEAK_RSS_EXCEEDS_MEMORY_ADMISSION"),
        ("TEMPORARY_DISK_EXCEEDS_ADMISSION", 8 * 1024 * 1024,
         9 * 1024 * 1024, 32 * 1024 * 1024, 1, 1,
         "TEMPORARY_PHYSICAL_DISK_EXCEEDS_DISK_ADMISSION"),
        ("FINAL_DISK_EXCEEDS_ADMISSION", 8 * 1024 * 1024,
         9 * 1024 * 1024, 1, 32 * 1024 * 1024, 1,
         "FINAL_PHYSICAL_DISK_EXCEEDS_DISK_ADMISSION"),
        ("PUBLICATION_HIGH_WATER_EXCEEDS_ADMISSION", 8 * 1024 * 1024,
         9 * 1024 * 1024, 1, 1, 32 * 1024 * 1024,
         "PUBLICATION_HIGH_WATER_EXCEEDS_DISK_ADMISSION"),
    ]
    rows = []
    for (case_id, worker_peak, tree_peak, temporary, final, publication,
         expected) in cases:
        request = _minimal_request()
        result = _minimal_result(worker_peak, temporary, final, publication)
        gate = evaluate_resource_hard_gate(request, result, tree_peak)
        if gate["status"] != "STOP" or expected not in gate["violations"]:
            raise AssertionError(f"resource violation accepted:{case_id}")
        rows.append({
            "case_id": case_id,
            "worker_peak_rss_bytes": worker_peak,
            "process_tree_peak_rss_bytes": tree_peak,
            "authoritative_peak_rss_bytes": gate["authoritative_peak_rss_bytes"],
            "temporary_physical_disk_bytes": temporary,
            "final_physical_disk_bytes": final,
            "publication_high_water_bytes": publication,
            "observed_stop": expected,
            "decision_ledger_rows": 0,
            "later_request_launch_count": 0,
            "status": "PASS",
        })
    write_tsv(evidence / "P13_RESOURCE_HARD_STOP_CORPUS.tsv", rows)
    return rows


def process_tree_rss_injection(evidence: Path) -> Dict[str, Any]:
    pid_evidence = evidence / "P13_CHILD_MEMORY_PIDS.json"
    command = [
        sys.executable, "-B", str(INJECTED_WORKER),
        "--mode", "memory-parent", "--megabytes", "48",
        "--seconds", "1.2", "--pid-evidence", str(pid_evidence),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        **process_group_options(),
    )
    sampler = ProcessTreeRssSampler(process.pid)
    sampler.start()
    stdout, _ = process.communicate(timeout=10)
    sampler.stop()
    if process.returncode != 0 or sampler.error != "NONE":
        raise AssertionError(f"child memory injection failed:{stdout}:{sampler.error}")
    if sampler.maximum_bytes <= sampler.maximum_root_bytes + 16 * 1024 * 1024:
        raise AssertionError("process-tree sampler did not capture child memory")
    gate_result = _minimal_result(sampler.maximum_root_bytes, 0, 0, 0)
    gate = evaluate_resource_hard_gate(
        _minimal_request(memory=sampler.maximum_bytes + 1024, disk=0),
        gate_result, sampler.maximum_bytes,
    )
    if (
        gate["status"] != "PASS"
        or gate["authoritative_peak_rss_bytes"] != sampler.maximum_bytes
    ):
        raise AssertionError("authoritative RSS did not use process-tree maximum")
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBProcessTreeRssEvidence/v1",
        "status": "PASS",
        "worker_root_peak_rss_bytes": sampler.maximum_root_bytes,
        "controller_process_tree_peak_rss_bytes": sampler.maximum_bytes,
        "authoritative_peak_rss_bytes": gate["authoritative_peak_rss_bytes"],
        "child_excess_over_worker_bytes": (
            sampler.maximum_bytes - sampler.maximum_root_bytes
        ),
        "sample_count": sampler.sample_count,
        "owned_pids": sorted(sampler.owned_pids),
        "child_memory_injection_bytes": 48 * 1024 * 1024,
        "worker_stdout": stdout.strip(),
    }
    write_canonical_json(evidence / "P13_PROCESS_TREE_RSS.json", result)
    return result


def _capture_with_ceiling(
        base: Mapping[str, Any], ceiling: int, capture_id: str) -> Dict[str, Any]:
    output = dict(base)
    output["capture_time"] = f"FIX005_BOUNDED_INJECTION_{capture_id}"
    output["physical_memory_bytes"] = ceiling * 2
    output["admission_memory_ceiling_bytes"] = ceiling
    output["fix005_bounded_resource_injection"] = True
    return output


def fresh_capture_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        base_resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path) -> Dict[str, Any]:
    activation = {
        "state": "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED",
        "authorization_id": "FIX003_PREFLIGHT_DRY_RUN_ONLY",
        "authorization_sha256": "0" * 64,
        "authorization_artifact_path": "NOT_SUPPLIED",
        "physical_allocation_authorized": False,
    }
    protocol = adaptive_execution_protocol(authority, assets, activation)
    validate_adaptive_execution_protocol(authority, assets, protocol)
    write_canonical_json(evidence / "P14_ADAPTIVE_EXECUTION_PROTOCOL.json", protocol)
    call_rows = []
    workload_branch_targets = {WORKLOADS[0]: "PASS", WORKLOADS[1]: "FAIL"}

    def provider(scope: str, workload: str, candidate: str | None):
        compact_required = int(assets.projections[(
            workload, "COMPACT_IN_MEMORY")]["memory_admission_required_bytes"])
        file_required = max(int(assets.projections[(workload, value)][
            "memory_admission_required_bytes"]) for value in FILE_CANDIDATES)
        if candidate is None:
            branch = workload_branch_targets[workload]
            ceiling = max(compact_required, file_required) + 4096
            if branch == "FAIL":
                ceiling = max(file_required, 1)
                if ceiling >= compact_required:
                    raise AssertionError("no synthetic FAIL branch interval")
        else:
            ceiling = int(assets.projections[(workload, candidate)][
                "memory_admission_required_bytes"]) + 4096
        value = _capture_with_ceiling(
            base_resource, ceiling, f"{len(call_rows):03d}_{scope}",
        )
        call_rows.append({
            "ordinal": len(call_rows), "scope_id": scope,
            "workload_id": workload,
            "candidate_id": candidate or "NOT_APPLICABLE",
            "admission_memory_ceiling_bytes": ceiling,
            "capture_sha256": sha(canonical_json_bytes(value)),
        })
        return value

    plans = []
    ordinal = 0
    for workload_index in (0, 1):
        plan = _materialize_fix005_batched_evidence_plan(
            authority, assets, durability, workload_index,
            runtime / "p14-never-created", evidence,
            provider, activation, ordinal,
        )
        ordinal = plan["next_capture_ordinal"]
        plans.append(plan)
        write_canonical_json(
            evidence / f"P14_FRESH_WORKLOAD_PLAN_{workload_index + 1}.json",
            plan,
        )
    if [plan["compact_admission_result"] for plan in plans] != ["PASS", "FAIL"]:
        raise AssertionError("later workload did not select its own fresh branch")
    for plan in plans:
        if len(plan["capture_rows"]) != 1 + len(plan["allowed_candidate_ids"]):
            raise AssertionError("per-workload/per-series capture cadence")
        for request in plan["requests"]:
            series = next(
                row for row in plan["capture_rows"]
                if row["candidate_id"] == request["candidate_id"]
            )
            if (
                request["fresh_resource_capture_sha256"] != series["capture_sha256"]
                or request["workload_branch_resource_capture_sha256"]
                != plan["branch_capture_sha256"]
            ):
                raise AssertionError("runtime capture/request binding")
    binding_rows = []
    base_request = plans[0]["requests"][0]
    base_candidate = base_request["candidate_id"]
    series_path = Path(next(
        row["capture_path"] for row in plans[0]["capture_rows"]
        if row["candidate_id"] == base_candidate
    ))
    branch_path = Path(plans[0]["branch_capture_path"])
    series_resource = strict_json_load(series_path)
    branch_resource = strict_json_load(branch_path)
    for case_id, field, expected_stop in (
        ("EXACT_DUAL_CAPTURE_BINDING", None,
         "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED"),
        ("MUTATED_SERIES_CAPTURE_HASH", "fresh_resource_capture_sha256",
         "SB_STOP_ADMISSION_MEMORY"),
        ("MUTATED_BRANCH_CAPTURE_HASH", "workload_branch_resource_capture_sha256",
         "SB_STOP_ADMISSION_MEMORY"),
    ):
        request = copy.deepcopy(base_request)
        if field:
            request[field] = "f" * 64
        try:
            prelaunch_guard(
                authority, assets, request, runtime / "p14-never-created",
                series_resource, durability, branch_resource,
            )
        except StopSignal as signal_value:
            if signal_value.stop_id != expected_stop:
                raise
            binding_rows.append({
                "case_id": case_id, "mutated_field": field or "NONE",
                "observed_stop_id": signal_value.stop_id,
                "worker_launch_count": 0, "physical_allocation_count": 0,
                "status": "PASS",
            })
            continue
        raise AssertionError(f"capture binding case did not stop:{case_id}")
    write_tsv(evidence / "P14_CAPTURE_REQUEST_BINDING.tsv", binding_rows)
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBFreshCaptureCadenceEvidence/v1",
        "status": "PASS",
        "protocol_identity_sha256": protocol["protocol_identity_sha256"],
        "workload_1_branch": plans[0]["compact_admission_result"],
        "workload_2_branch": plans[1]["compact_admission_result"],
        "resource_state_changed_between_workloads": True,
        "workload_2_used_own_capture": True,
        "workload_capture_count": 2,
        "candidate_series_capture_count": sum(
            len(plan["allowed_candidate_ids"]) for plan in plans
        ),
        "capture_request_binding_cases": len(binding_rows),
        "capture_rows": call_rows,
        "worker_launch_count": 0,
        "physical_allocation_count": 0,
    }
    write_canonical_json(evidence / "P14_FRESH_CAPTURE_CADENCE.json", result)
    return result


def authorization_v2_evidence(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path) -> Dict[str, Any]:
    host = {key: resource[key] for key in (
        "host_id", "platform_system", "platform_release", "platform_machine",
        "os_build", "filesystem", "destination_device_id",
        "target_volume_device", "target_volume_mount_point",
    )}
    artifact = make_authorization_artifact(
        assets, authority.commit, authority.tree, host,
        sha(canonical_json_bytes(dict(durability))), evidence, runtime,
        "FIX005_SCHEMA_EXAMPLE_NOT_PHYSICALLY_AUTHORIZED", False,
    )
    if (
        artifact["schema"] != AUTHORIZATION_SCHEMA
        or "fresh_resource_capture_sha256" in artifact
        or any("compact_admission_result" in row for row in artifact["workload_authorizations"])
        or any(set(row["admission_branches"]) != {"PASS", "FAIL"}
               for row in artifact["workload_authorizations"])
    ):
        raise AssertionError("authorization v2 still predetermines runtime branch")
    write_canonical_json(evidence / "P14_AUTHORIZATION_V2_EXAMPLE.json", artifact)
    result = {
        "schema": "SplitAlignerR/ENGINE003StageBAuthorizationV2Evidence/v1",
        "status": "PASS",
        "authorization_schema": AUTHORIZATION_SCHEMA,
        "authorization_sha256": sha(canonical_json_bytes(artifact)),
        "exact_execution_commit": artifact["authorized_execution_commit"],
        "exact_execution_tree": artifact["authorized_execution_tree"],
        "exact_host_volume_bound": True,
        "capture_procedure_bound": True,
        "resource_admission_policy_bound": True,
        "schedule_selection_policy_bound": True,
        "both_branches_permitted_without_preselection": True,
        "single_stale_capture_hash_absent": True,
        "physical_allocation_authorized": False,
    }
    write_canonical_json(evidence / "P14_AUTHORIZATION_TRUST_ROOT.json", result)
    return result


def _pid_is_live_non_zombie(pid: int) -> bool:
    if os.name == "nt":
        process = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
            text=True, check=False,
        )
        return str(pid) in process.stdout
    process = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
        text=True, check=False,
    )
    state = process.stdout.strip()
    return bool(state) and not state.startswith("Z")


def timeout_corpus(
        repo: Path, authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        resource_path: Path, durability_path: Path,
        runtime: Path, evidence: Path) -> list[Dict[str, Any]]:
    cases = [
        ("COOPERATIVE_PARTIAL_SAFE", "cooperative", "present", "safe", False),
        ("FORCED_PARTIAL_ABSENT_UNSAFE", "uncooperative", "absent", "unsafe", True),
        ("FORCED_GRANDCHILD_TREE", "grandchild", "present", "absent", True),
    ]
    rows = []
    for case_index, (case_id, mode, partial_state, target_state, expect_force) in enumerate(cases):
        target = runtime / "p15-timeout" / case_id
        request = make_bounded_request(
            authority, assets, resource, durability, "COMPACT_IN_MEMORY", 1,
            target, evidence,
        )
        root = evidence / "P15_TIMEOUT_CORPUS" / case_id
        output = root / "worker.result.json"
        partial = output.with_suffix(".partial.json")
        pid_evidence = root / "pids.json"
        command = [
            sys.executable, "-B", str(INJECTED_WORKER), "--mode", mode,
            "--partial", str(partial), "--target", str(target),
            "--pid-evidence", str(pid_evidence),
            "--partial-state", partial_state, "--target-state", target_state,
        ]
        grace_values = []

        def bounded_waiter(process, seconds):
            grace_values.append(seconds)
            try:
                process.wait(timeout=0.25)
                return True
            except subprocess.TimeoutExpired:
                return False

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
            raise AssertionError(f"timeout injection returned PASS:{case_id}")
        stop = strict_json_load(output)
        termination = stop["termination"]
        if (
            grace_values != [TIMEOUT_COOPERATIVE_GRACE_SECONDS]
            or termination["production_grace_seconds"] != 60
            or termination["force_terminate_process_tree_executed"] is not expect_force
            or stop["decision_ledger_eligible"] is not False
            or stop["no_later_request_launch"] is not True
        ):
            raise AssertionError(f"timeout state machine:{case_id}")
        expected_partial = "PRESERVED" if partial_state == "present" else "ABSENT"
        if stop["partial_evidence_status"] != expected_partial:
            raise AssertionError(f"timeout partial evidence:{case_id}")
        decisions = {value["decision"] for value in stop["target_dispositions"]}
        if target_state == "safe" and "PRESERVE_TARGET_IF_SAFE_IN_PLACE" not in decisions:
            raise AssertionError("safe timeout target not preserved")
        if target_state == "unsafe" and "UNSAFE_TARGET_CLEANED" not in decisions:
            raise AssertionError("unsafe timeout target not cleaned")
        descendant_live = False
        if mode == "grandchild":
            pids = strict_json_load(pid_evidence)
            deadline = time.monotonic() + 2
            descendant_live = _pid_is_live_non_zombie(pids["child_pid"])
            while descendant_live and time.monotonic() < deadline:
                time.sleep(0.02)
                descendant_live = _pid_is_live_non_zombie(pids["child_pid"])
            if descendant_live:
                raise AssertionError("grandchild survived final process-tree kill")
        rows.append({
            "case_id": case_id,
            "cooperative_stop_emitted": termination["cooperative_stop_request_emitted"],
            "cooperative_outcome": termination["cooperative_outcome"],
            "production_grace_seconds": termination["production_grace_seconds"],
            "force_tree_kill": termination["force_terminate_process_tree_executed"],
            "partial_evidence_status": stop["partial_evidence_status"],
            "target_decisions": ",".join(sorted(decisions)),
            "grandchild_live_after_final_kill": descendant_live,
            "controller_log_preserved": stop["controller_log_preserved"],
            "timeout_stop_object_written": True,
            "decision_ledger_rows": 0,
            "later_request_launch_count": 0,
            "status": "PASS",
        })
        if target.exists() and target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        parent = target.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    write_tsv(evidence / "P15_TIMEOUT_STATE_MACHINE_CORPUS.tsv", rows)
    return rows


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    base = execute_fix004(args)
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    authority = ExecutionAuthority(repo, args.authorized_commit, args.authorized_tree)
    assets = FrozenAssets(authority)
    resource_path = evidence / "FRESH_RESOURCE_CAPTURE.json"
    durability_path = evidence / "DURABLE_PUBLISH_CAPABILITY.json"
    resource = strict_json_load(resource_path)
    durability = strict_json_load(durability_path)

    p12 = streaming_hash_corpus(runtime, evidence)
    resource_rows = resource_hard_gate_corpus(evidence)
    rss = process_tree_rss_injection(evidence)
    p14 = fresh_capture_corpus(
        authority, assets, resource, durability, runtime, evidence,
    )
    auth = authorization_v2_evidence(
        authority, assets, resource, durability, runtime, evidence,
    )
    timeout_rows = timeout_corpus(
        repo, authority, assets, resource, durability,
        resource_path, durability_path, runtime, evidence,
    )
    for path in sorted(runtime.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if any(runtime.iterdir()):
        raise StopSignal("SB_STOP_CLEANUP", "fix005_runtime_not_empty")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_BOUNDED_FIX005_PREFLIGHT_ONLY",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "direct_parent": args.direct_parent,
        "p09_p11_regression_status": base["status"],
        "p12_streaming_hash_cases": 4,
        "p12_tree_hash_chunk_bytes": p12["tree_hash_chunk_bytes"],
        "p13_resource_hard_stop_cases": len(resource_rows),
        "p13_process_tree_rss_cases": 1,
        "p14_fresh_capture_cases": p14["workload_capture_count"] + p14["candidate_series_capture_count"],
        "p14_authorization_schema": auth["authorization_schema"],
        "p15_timeout_cases": len(timeout_rows),
        "bounded_physical_worker_launches": base["bounded_physical_worker_launches"],
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
    write_canonical_json(evidence / "FIX005_SUMMARY.json", summary)
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
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX005_"
        f"{result['status']} P12=PASS P13=PASS P14=PASS P15=PASS "
        "LARGE_WORKERS=0 LARGE_ALLOCATIONS=0"
    )


if __name__ == "__main__":
    main()
