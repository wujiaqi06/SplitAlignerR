#!/usr/bin/env python3
"""Run FIX004 bounded replay and adversarial control/timing regressions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import struct
import sys
import time
import types
from pathlib import Path
from typing import Any, Dict, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    ExecutionAuthority, FrozenAssets, StopSignal, canonical_json_bytes,
    strict_json_load, write_canonical_json,
)
from run_fix002_preflight import write_tsv  # noqa: E402
from run_fix003_preflight import execute as execute_fix003  # noqa: E402
from stage_b_orchestrator import (  # noqa: E402
    REQUEST_IDENTITY_FIELDS, branch_resource, complete_execution_plan,
    execute_authorized_plan, validate_worker_result_identity,
)
from stage_b_worker import (  # noqa: E402
    ExpectedProbeOracle, block_read_sample, build_rows,
    column_extraction_sample, publish_barriers_with_prepublication_evidence,
    row_read_sample,
)
from stage_b_durable_publish import publication_evidence_hashes  # noqa: E402


SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBExecPreflightFix004Summary/v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _refresh_plan(plan: Dict[str, Any]) -> None:
    identity = [{field: request[field] for field in REQUEST_IDENTITY_FIELDS}
                for request in plan["requests"]]
    plan["request_identity_sha256"] = _sha(canonical_json_bytes(identity))
    plan["request_count"] = len(plan["requests"])
    plan["warmup_request_count"] = sum(
        request["run_phase"] == "UNTIMED_WARMUP" for request in plan["requests"]
    )
    plan["measured_request_count"] = sum(
        request["run_phase"] == "MEASURED" for request in plan["requests"]
    )


def plan_mutation_corpus(
        repo: Path, authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        resource_path: Path, durability_path: Path,
        runtime: Path, evidence: Path) -> list[Dict[str, Any]]:
    base = complete_execution_plan(
        authority, assets, resource, durability,
        runtime / "large-pass-never-created", evidence,
    )
    measured = [index for index, request in enumerate(base["requests"])
                if request["run_phase"] == "MEASURED"]
    warmups = [index for index, request in enumerate(base["requests"])
               if request["run_phase"] == "UNTIMED_WARMUP"]

    def incorrect_hash(value):
        value["request_identity_sha256"] = "0" * 64

    def duplicate_measured(value):
        value["requests"][measured[1]] = copy.deepcopy(value["requests"][measured[0]])
        _refresh_plan(value)

    def duplicate_warmup(value):
        value["requests"][warmups[1]] = copy.deepcopy(value["requests"][warmups[0]])
        _refresh_plan(value)

    def missing_row(value):
        value["requests"].pop(measured[0])
        _refresh_plan(value)

    def extra_row(value):
        request = copy.deepcopy(value["requests"][measured[0]])
        request["measured_repetition"] = 999
        request["schedule_position"] = 999
        request["schedule_row_sha256"] = "f" * 64
        request["runtime_target"] += "_extra"
        value["requests"].append(request)
        _refresh_plan(value)

    def reordered_williams(value):
        left, right = measured[0], measured[1]
        value["requests"][left], value["requests"][right] = (
            value["requests"][right], value["requests"][left]
        )
        _refresh_plan(value)

    def wrong_workload_order(value):
        value["workload_order"] = list(reversed(value["workload_order"]))

    def wrong_branch(value):
        value["workloads"][0]["compact_admission_result"] = "FAIL"
        value["workloads"][0]["selected_schedule_id"] = "THREE_FILE_CANDIDATE_WILLIAMS_6"

    def wrong_request_count(value):
        value["request_count"] += 1

    def wrong_measured_count(value):
        value["measured_request_count"] += 1

    def wrong_warmup_count(value):
        value["warmup_request_count"] += 1

    mutations = {
        "INCORRECT_REQUEST_IDENTITY_SHA256": incorrect_hash,
        "DUPLICATE_MEASURED_ROW": duplicate_measured,
        "DUPLICATE_WARMUP_ROW": duplicate_warmup,
        "MISSING_ROW": missing_row,
        "EXTRA_ROW": extra_row,
        "REORDERED_WILLIAMS_ROW": reordered_williams,
        "WRONG_WORKLOAD_ORDER": wrong_workload_order,
        "WRONG_PER_WORKLOAD_BRANCH": wrong_branch,
        "WRONG_REQUEST_COUNT": wrong_request_count,
        "WRONG_MEASURED_COUNT": wrong_measured_count,
        "WRONG_WARMUP_COUNT": wrong_warmup_count,
    }
    rows = []
    launches = {"count": 0}
    inert = types.ModuleType("stage_b_controller")

    def forbidden_launcher(*_args, **_kwargs):
        launches["count"] += 1
        raise AssertionError("malformed plan reached launcher")

    inert.launch_request = forbidden_launcher
    previous = sys.modules.get("stage_b_controller")
    sys.modules["stage_b_controller"] = inert
    try:
        for case_id, mutate in mutations.items():
            candidate = copy.deepcopy(base)
            mutate(candidate)
            before = launches["count"]
            try:
                execute_authorized_plan(
                    repo, runtime, evidence, resource_path, durability_path,
                    candidate,
                )
            except StopSignal as signal_value:
                if signal_value.stop_id != "SB_STOP_COMPLETE_PLAN_IDENTITY":
                    raise
                if launches["count"] != before:
                    raise AssertionError(f"launcher reached:{case_id}")
                rows.append({
                    "case_id": case_id,
                    "observed_stop_id": signal_value.stop_id,
                    "observed_detail": signal_value.detail,
                    "worker_launch_count": 0,
                    "physical_allocation_count": 0,
                    "status": "PASS",
                })
                continue
            raise AssertionError(f"plan mutation accepted:{case_id}")
    finally:
        if previous is None:
            del sys.modules["stage_b_controller"]
        else:
            sys.modules["stage_b_controller"] = previous
    if launches["count"]:
        raise AssertionError("plan corpus launched worker")
    return rows


def result_mutation_corpus(request: Mapping[str, Any]) -> list[Dict[str, Any]]:
    base = {field: request[field] for field in (
        "workload_id", "candidate_id", "selected_schedule_id",
        "measured_repetition", "schedule_position", "schedule_row_sha256",
        "source_commit", "source_tree",
    )}
    validate_worker_result_identity(request, base)
    mutations = {
        "WRONG_RESULT_CANDIDATE": ("candidate_id", "OTHER"),
        "WRONG_RESULT_WORKLOAD": ("workload_id", "OTHER"),
        "WRONG_REPETITION": ("measured_repetition", 999),
        "WRONG_SCHEDULE_POSITION": ("schedule_position", 999),
        "WRONG_SCHEDULE_ROW_HASH": ("schedule_row_sha256", "0" * 64),
        "WRONG_SOURCE_IDENTITY": ("source_commit", "0" * 40),
    }
    rows = []
    for case_id, (field, value) in mutations.items():
        result = dict(base)
        result[field] = value
        try:
            validate_worker_result_identity(request, result)
        except StopSignal as signal_value:
            if signal_value.stop_id != "SB_STOP_RESULT_IDENTITY":
                raise
            rows.append({
                "case_id": case_id,
                "mutated_field": field,
                "observed_stop_id": signal_value.stop_id,
                "decision_ledger_rows_assembled": 0,
                "status": "PASS",
            })
            continue
        raise AssertionError(f"result mutation accepted:{case_id}")
    return rows


class _Case:
    def __init__(self, delay_seconds: float):
        self.rows = 10
        self.primitive = 3
        self.bstar = 1
        self.numeric = 4
        self.delay_seconds = delay_seconds

    def row(self, row: int):
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        state = bytes(((row + column) % 4 for column in range(self.primitive)))
        numeric = b"".join(struct.pack("<d", row + column / 10.0)
                           for column in range(self.numeric))
        validity = bytes(((row + column) % 2 for column in range(self.numeric)))
        return state, numeric, validity


class _Plan:
    @staticmethod
    def row_indices(rows: int):
        return (0, 1, rows // 2, rows - 1)

    @staticmethod
    def column_indices(width: int):
        return tuple(sorted({0, 1, width - 1}))

    @staticmethod
    def blocks(rows: int, width: int):
        return ((0, 2, 0, min(2, width)),
                (rows - 2, 2, max(0, width - 2), min(2, width)))


class _Backend:
    def __init__(self):
        self.rows = []

    def write_row(self, row, state, numeric, validity):
        if row != len(self.rows):
            raise AssertionError("fake backend row order")
        self.rows.append((state, numeric, validity))

    def read_row(self, row):
        return self.rows[row]

    def read_column(self, component, column):
        index = {"state": 0, "numeric": 1, "validity": 2}[component]
        width = 8 if component == "numeric" else 1
        start = column * width
        return b"".join(value[index][start:start + width] for value in self.rows)

    def read_block(self, component, row_start, row_count, column_start, column_count):
        index = {"state": 0, "numeric": 1, "validity": 2}[component]
        width = 8 if component == "numeric" else 1
        start = column_start * width
        size = column_count * width
        return b"".join(self.rows[row][index][start:start + size]
                        for row in range(row_start, row_start + row_count))


def metric_boundary_corpus() -> list[Dict[str, Any]]:
    delay = 0.002
    plan = _Plan()
    fast_backend = _Backend()
    fast_case = _Case(0)
    fast_oracle = ExpectedProbeOracle(fast_case, plan)
    fast_write = build_rows(fast_backend, fast_case, fast_oracle)

    slow_backend = _Backend()
    slow_case = _Case(delay)
    slow_oracle = ExpectedProbeOracle(slow_case, plan)
    start = time.perf_counter_ns()
    slow_write = build_rows(slow_backend, slow_case, slow_oracle)
    wall = time.perf_counter_ns() - start
    injected = slow_case.rows * delay
    if wall < injected * 1e9 * 0.8 or slow_write > fast_write + 2_000_000:
        raise AssertionError("payload generation entered row_construction timing")
    rows = [{
        "metric_id": "row_construction",
        "fast_authoritative_ns": fast_write,
        "slow_authoritative_ns": slow_write,
        "slow_wall_ns": wall,
        "injected_delay_ns": int(injected * 1e9),
        "timed_operation": "BACKEND_WRITE_ROW_ONLY",
        "status": "PASS",
    }]

    def compare(metric_id, operation):
        _fast_value, fast_ns = operation(None)
        calls = {"count": 0}

        def slow_hook():
            calls["count"] += 1
            time.sleep(delay)

        start_value = time.perf_counter_ns()
        _slow_value, slow_ns = operation(slow_hook)
        wall_value = time.perf_counter_ns() - start_value
        injected_value = calls["count"] * delay
        if (
            wall_value < injected_value * 1e9 * 0.8
            or slow_ns > fast_ns + 2_000_000
        ):
            raise AssertionError(f"oracle delay entered {metric_id} timing")
        rows.append({
            "metric_id": metric_id,
            "fast_authoritative_ns": fast_ns,
            "slow_authoritative_ns": slow_ns,
            "slow_wall_ns": wall_value,
            "injected_delay_ns": int(injected_value * 1e9),
            "timed_operation": {
                "row_read_sample": "BACKEND_READ_ROW_ONLY",
                "column_extraction_sample": "BACKEND_READ_COLUMN_ONLY",
                "block_read_sample": "BACKEND_READ_BLOCK_ONLY",
            }[metric_id],
            "status": "PASS",
        })

    compare("row_read_sample", lambda hook: row_read_sample(
        slow_backend, slow_oracle, hook,
    ))
    compare("column_extraction_sample", lambda hook: column_extraction_sample(
        slow_backend, slow_oracle, hook,
    ))
    compare("block_read_sample", lambda hook: block_read_sample(
        slow_backend, slow_oracle, hook,
    ))
    return rows


def durability_timing_corpus() -> Dict[str, Any]:
    delay = 0.025
    calls = []

    def slow_hash(path: Path) -> str:
        calls.append(str(path))
        time.sleep(delay)
        return _sha(str(path).encode("utf-8"))

    def barrier(_temp: Path, _final: Path) -> Dict[str, Any]:
        return {
            "protocol": "DURABLE_PUBLISH_V1",
            "authoritative_timing_scope": "DURABLE_PUBLISH_V1_BARRIERS_ONLY",
            "status": "PUBLISHED_VALIDATED_BOUNDED_PROTOTYPE",
        }

    temp = Path("FIX004_FAKE_PRIVATE_TARGET")
    final = Path("FIX004_FAKE_FINAL_TARGET")
    start = time.perf_counter_ns()
    result, authoritative_ns, before = publish_barriers_with_prepublication_evidence(
        temp, final, barrier, slow_hash,
    )
    # Models the production ordering: attach the final-tree evidence only after
    # later decision-bearing reopen operations have completed.
    result.update(publication_evidence_hashes(before, final, slow_hash))
    result["published_tree_hash_after_reopen_metrics"] = True
    wall = time.perf_counter_ns() - start
    injected_ns = int(2 * delay * 1e9)
    expected_before = _sha(str(temp).encode("utf-8"))
    expected_after = _sha(str(final).encode("utf-8"))
    if (
        calls != [str(temp), str(final)]
        or result["prepublication_tree_sha256"] != expected_before
        or result["published_tree_sha256_with_validated"] != expected_after
        or result["evidence_hash_timing_role"] != "EVIDENCE_ONLY"
        or result["evidence_hash_decision_role"] != "NOT_DECISION_TIMING"
        or wall < injected_ns * 0.8
        or authoritative_ns > 2_000_000
    ):
        raise AssertionError("evidence hashing contaminated durability timing")
    return {
        "case_id": "SLOW_EVIDENCE_TREE_HASH",
        "hash_call_count": len(calls),
        "injected_hash_delay_ns": injected_ns,
        "observed_wall_ns": wall,
        "authoritative_barrier_ns": authoritative_ns,
        "prepublication_tree_sha256": expected_before,
        "published_tree_sha256_with_validated": expected_after,
        "evidence_hash_timing_role": result["evidence_hash_timing_role"],
        "evidence_hash_decision_role": result["evidence_hash_decision_role"],
        "published_tree_hash_after_reopen_metrics": result[
            "published_tree_hash_after_reopen_metrics"
        ],
        "status": "PASS",
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    base = execute_fix003(args)
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    authority = ExecutionAuthority(repo, args.authorized_commit, args.authorized_tree)
    assets = FrozenAssets(authority)
    durability_path = evidence / "DURABLE_PUBLISH_CAPABILITY.json"
    durability = strict_json_load(durability_path)
    pass_path = evidence / "RESOURCE_VIEW_PASS.json"
    pass_resource = strict_json_load(pass_path)
    raw_plan = complete_execution_plan(
        authority, assets, pass_resource, durability,
        runtime / "large-pass-never-created", evidence,
    )

    plan_rows = plan_mutation_corpus(
        repo, authority, assets, pass_resource, durability,
        pass_path, durability_path, runtime, evidence,
    )
    result_rows = result_mutation_corpus(raw_plan["requests"][0])
    metric_rows = metric_boundary_corpus()
    durability_result = durability_timing_corpus()
    write_tsv(evidence / "COMPLETE_PLAN_MUTATION_RESULTS.tsv", plan_rows)
    write_tsv(evidence / "WORKER_RESULT_IDENTITY_MUTATION_RESULTS.tsv", result_rows)
    write_tsv(evidence / "METRIC_BOUNDARY_DELAY_RESULTS.tsv", metric_rows)
    write_canonical_json(
        evidence / "DURABILITY_HASH_TIMING_SEPARATION.json", durability_result,
    )
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_BOUNDED_FIX004_PREFLIGHT_ONLY",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "direct_parent": args.direct_parent,
        "bounded_physical_worker_launches": base["bounded_physical_worker_launches"],
        "large_complete_plan_requests": base["large_complete_plan_requests"],
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "plan_mutation_cases": len(plan_rows),
        "result_identity_mutation_cases": len(result_rows),
        "metric_boundary_cases": len(metric_rows),
        "durability_timing_cases": 1,
        "stage_b_clock": False,
        "stage_b_execution_authorized": False,
        "large_store_constructed": False,
        "over2gib_or_over4gib_constructed": False,
        "backend_selected": False,
        "production_source_changed": False,
        "runtime_root_empty_after_cleanup": not runtime.exists() or not any(runtime.iterdir()),
    }
    write_canonical_json(evidence / "FIX004_SUMMARY.json", summary)
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
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX004_"
        f"{result['status']} PLAN_MUTATIONS={result['plan_mutation_cases']} "
        f"RESULT_MUTATIONS={result['result_identity_mutation_cases']} "
        "LARGE_WORKERS=0 LARGE_ALLOCATIONS=0"
    )


if __name__ == "__main__":
    main()
