#!/usr/bin/env python3
"""Future Stage-B worker boundary, exercised only with bounded preflight data.

EXEC-PREFLIGHT invokes this file in an explicitly non-authoritative mode.  The
decision clock helper is frozen here for later authorization, but no measured
Stage-B mode and no production MatrixStore writer are enabled by this gate.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Tuple


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from execution_contract import (  # noqa: E402
    BOUNDED_MODE,
    MAX_INT64,
    OPERATION_CONTRACT,
    WORKER_RESULT_SCHEMA,
    bounded_full_logical_scan,
    strict_json_load,
    write_canonical_json,
)


METRIC_OPERATIONS = (
    "allocation_initialization",
    "row_construction",
    "finalization",
    "bounded_validation",
    "row_read_sample",
    "column_extraction_sample",
    "block_read_sample",
    "full_logical_read",
    "physical_component_hashing",
    "logical_hash_reconstruction",
    "same_process_reopen",
    "fresh_process_reopen_internal_open",
    "fresh_process_reopen_total",
    "peak_rss",
    "temporary_physical_disk",
    "final_physical_disk",
    "publication_high_water",
    "publication_durability_barriers",
    "worker_end_to_end",
)


def authoritative_measure_ns(operation: Callable[[], Any]) -> Tuple[Any, int]:
    """Only legal future decision timer: monotonic integer nanoseconds."""
    start_ns = time.perf_counter_ns()
    value = operation()
    elapsed_ns = time.perf_counter_ns() - start_ns
    if type(elapsed_ns) is not int or not 1 <= elapsed_ns <= MAX_INT64:
        raise RuntimeError("authoritative duration escaped positive signed-int64")
    return value, elapsed_ns


def synthetic_metrics(workload_index: int, candidate_index: int,
                      repetition: int) -> Dict[str, Any]:
    """Deterministic integer probes; never decision-authoritative measurements."""
    base = 1_000_000 + workload_index * 100_000 + candidate_index * 10_000
    jitter = repetition * 101
    return {
        "lifecycle": {
            "allocation_initialization": base + jitter + 1,
            "row_construction": base + jitter + 2,
            "finalization": base + jitter + 3,
            "bounded_validation": base + jitter + 4,
        },
        "peak_rss_repetitions": 32_000_000 + candidate_index * 100_000 + repetition,
        "publication_highwater_repetitions": (
            64_000_000 + candidate_index * 100_000 + repetition
        ),
        "column_extraction_repetitions": base + jitter + 5,
        "full_logical_scan_repetitions": base + jitter + 6,
    }


def run_bounded(request_path: Path, output_path: Path) -> None:
    request = strict_json_load(request_path)
    if request.get("execution_mode") != BOUNDED_MODE:
        raise ValueError("EXEC-PREFLIGHT worker refuses non-bounded mode")
    if request.get("expected_operation_contract") != OPERATION_CONTRACT:
        raise ValueError("worker operation contract mismatch")
    scan = bounded_full_logical_scan()
    injection = request.get("bounded_injection", "NONE")
    if injection == "LOGICAL_HASH_MISMATCH":
        scan["logical_content_sha256"] = "0" * 64
    metrics = synthetic_metrics(
        int(request["workload_index"]),
        int(request["candidate_index"]),
        int(request["measured_repetition"]),
    )
    if injection == "RSS_ENVELOPE_VIOLATION":
        metrics["peak_rss_repetitions"] = int(request["injected_limit_bytes"]) + 1
    if injection == "DISK_ENVELOPE_VIOLATION":
        metrics["publication_highwater_repetitions"] = (
            int(request["injected_limit_bytes"]) + 1
        )
    result = {
        "schema": WORKER_RESULT_SCHEMA,
        "status": "BOUNDED_WORKER_PASS",
        "evidence_mode": BOUNDED_MODE,
        "decision_authority": False,
        "stage_b_measured_timing": False,
        "performance_conclusion_authorized": False,
        "physical_candidate_store_constructed": False,
        "workload_id": request["workload_id"],
        "candidate_id": request["candidate_id"],
        "selected_schedule_id": request["selected_schedule_id"],
        "measured_repetition": request["measured_repetition"],
        "schedule_position": request["schedule_position"],
        "source_commit": request["source_commit"],
        "source_tree": request["source_tree"],
        "operation_contract": OPERATION_CONTRACT,
        "controller_watchdog_start": "IMMEDIATELY_BEFORE_WORKER_SPAWN",
        "controller_watchdog_end": "POST_CLEANUP_RESULT_RECORDED",
        "cleanup_result": "PASS_NOT_APPLICABLE_BOUNDED_NO_TARGET",
        "operation_markers": [
            {"metric_id": metric, "inside_controller_watchdog": True}
            for metric in METRIC_OPERATIONS
        ],
        "bounded_full_logical_scan": scan,
        "synthetic_integer_metrics": metrics,
        "bounded_injection": injection,
    }
    write_canonical_json(output_path, result)


def _ignore_termination() -> None:
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def run_grandchild(pid_path: Path) -> None:
    _ignore_termination()
    pid_path.write_text(str(os.getpid()) + "\n", encoding="ascii")
    while True:
        time.sleep(1)


def run_timeout_tree(request_path: Path, partial_path: Path,
                     child_pid_path: Path) -> None:
    request = strict_json_load(request_path)
    _ignore_termination()
    child = subprocess.Popen([
        sys.executable,
        str(Path(__file__).resolve()),
        "--grandchild",
        "--child-pid", str(child_pid_path),
    ])
    write_canonical_json(partial_path, {
        "schema": "SplitAlignerR/ENGINE003StageBPartialWorkerEvidence/v1",
        "status": "WATCHDOG_INJECTION_RUNNING",
        "worker_pid": os.getpid(),
        "child_pid": child.pid,
        "workload_id": request["workload_id"],
        "candidate_id": request["candidate_id"],
        "last_completed_stage": "DETERMINISTIC_PAYLOAD_GENERATION",
        "raw_evidence_preserved": True,
        "decision_authority": False,
    })
    while True:
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-tree", action="store_true")
    parser.add_argument("--partial-output", type=Path)
    parser.add_argument("--child-pid", type=Path)
    parser.add_argument("--grandchild", action="store_true")
    args = parser.parse_args()
    if args.grandchild:
        if args.child_pid is None:
            parser.error("--grandchild requires --child-pid")
        run_grandchild(args.child_pid)
        return
    if args.request is None:
        parser.error("--request is required")
    if args.timeout_tree:
        if args.partial_output is None or args.child_pid is None:
            parser.error("timeout-tree requires --partial-output and --child-pid")
        run_timeout_tree(args.request, args.partial_output, args.child_pid)
        return
    if args.output is None:
        parser.error("bounded worker requires --output")
    run_bounded(args.request, args.output)


if __name__ == "__main__":
    main()
