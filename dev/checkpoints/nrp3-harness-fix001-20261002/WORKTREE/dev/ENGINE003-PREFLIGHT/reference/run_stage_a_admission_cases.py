#!/usr/bin/env python3
"""Fail-closed Stage-A execution-admission boundary corpus; no timing."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from planner_projection import U64_MAX, charge_backend, construction_projection, project_format
from stage_a_admission_proposal import declared_terms, evaluate_execution_admission, mib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    format_row = project_format(
        "tiny_admission_boundary", 3, 5, 2, "EXACT_ADMISSION_TEST_VECTOR"
    )
    terms = declared_terms()
    compact_memory = int(charge_backend(
        "tiny_compact_admission", format_row, "COMPACT_IN_MEMORY",
        "EXACT_ADMISSION_TEST_VECTOR", "BACKEND_ONLY", terms, True,
    )["admission_required_bytes"])
    tiled_memory = int(charge_backend(
        "tiny_tiled_admission", format_row, "TILED_DISK",
        "EXACT_ADMISSION_TEST_VECTOR", "BACKEND_ONLY", terms, True,
    )["admission_required_bytes"])
    tiled_disk = int(construction_projection(
        format_row,
        allocation_unit=4096,
        temp_directory_metadata_bound=mib(1),
        final_directory_metadata_bound=mib(1),
        disk_safety_reserve=mib(64),
    )["admission_free_space_bytes"])

    cases = [
        ("compact_memory_exact", "COMPACT_IN_MEMORY", compact_memory,
         compact_memory, 0, 0, True, "PASS", "PASS"),
        ("compact_memory_required_minus_1", "COMPACT_IN_MEMORY", compact_memory,
         compact_memory - 1, 0, 0, True, "NOT_ADMITTED_MEMORY",
         "NOT_ADMITTED_MEMORY"),
        ("tiled_memory_disk_exact", "TILED_DISK", tiled_memory, tiled_memory,
         tiled_disk, tiled_disk, True, "PASS", "PASS"),
        ("tiled_disk_required_minus_1", "TILED_DISK", tiled_memory,
         tiled_memory, tiled_disk, tiled_disk - 1, True, "NOT_ADMITTED_DISK",
         "NOT_ADMITTED_DISK"),
        ("tiled_memory_required_minus_1", "TILED_DISK", tiled_memory,
         tiled_memory - 1, tiled_disk, tiled_disk, True, "NOT_ADMITTED_MEMORY",
         "NOT_ADMITTED_MEMORY"),
        ("tiled_memory_and_disk_insufficient", "TILED_DISK", tiled_memory,
         tiled_memory - 1, tiled_disk, tiled_disk - 1, True,
         "NOT_ADMITTED_MEMORY_AND_DISK", "NOT_ADMITTED_MEMORY_AND_DISK"),
        ("tiled_durability_not_available", "TILED_DISK", tiled_memory,
         tiled_memory, tiled_disk, tiled_disk, False, "PASS",
         "NOT_ADMITTED_DURABILITY"),
    ]
    rows = []
    failures = []
    for (case_id, backend, required_memory, memory_ceiling, required_disk,
         available_disk, durability_ok, expected_resource,
         expected_execution) in cases:
        observed = evaluate_execution_admission(
            backend, required_memory, memory_ceiling, required_disk,
            available_disk, durability_ok,
        )
        passed = (
            observed["execution_resource_admission"] == expected_resource
            and observed["execution_admission"] == expected_execution
            and not (
                (int(observed["memory_margin_bytes"]) < 0
                 or int(observed["disk_margin_bytes"]) < 0)
                and observed["execution_resource_admission"] == "PASS"
            )
        )
        rows.append({
            "case_id": case_id,
            "backend": backend,
            "required_memory_bytes": required_memory,
            "memory_ceiling_bytes": memory_ceiling,
            "required_disk_bytes": required_disk,
            "available_disk_bytes": available_disk,
            "durability_capabilities_pass": str(durability_ok).upper(),
            "memory_margin_bytes": observed["memory_margin_bytes"],
            "disk_margin_bytes": observed["disk_margin_bytes"],
            "expected_resource_admission": expected_resource,
            "observed_resource_admission":
                observed["execution_resource_admission"],
            "expected_execution_admission": expected_execution,
            "observed_execution_admission": observed["execution_admission"],
            "result": "PASS" if passed else "FAIL",
        })
        if not passed:
            failures.append(case_id)

    overflow_case = "u64_required_memory_overflow"
    try:
        evaluate_execution_admission(
            "COMPACT_IN_MEMORY", U64_MAX + 1, U64_MAX, 0, 0, True
        )
    except (OverflowError, ValueError):
        overflow_observed = "REJECT"
    else:
        overflow_observed = "ACCEPT"
    overflow_passed = overflow_observed == "REJECT"
    rows.append({
        "case_id": overflow_case,
        "backend": "COMPACT_IN_MEMORY",
        "required_memory_bytes": U64_MAX + 1,
        "memory_ceiling_bytes": U64_MAX,
        "required_disk_bytes": 0,
        "available_disk_bytes": 0,
        "durability_capabilities_pass": "TRUE",
        "memory_margin_bytes": "NOT_COMPUTED",
        "disk_margin_bytes": "NOT_COMPUTED",
        "expected_resource_admission": "REJECT",
        "observed_resource_admission": overflow_observed,
        "expected_execution_admission": "REJECT",
        "observed_execution_admission": overflow_observed,
        "result": "PASS" if overflow_passed else "FAIL",
    })
    if not overflow_passed:
        failures.append(overflow_case)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    if failures:
        raise SystemExit("Stage-A admission case failures: " + ",".join(failures))
    print(f"STAGE_A_ADMISSION_CASES_PASS {len(rows)}/{len(rows)} NO_TIMING")


if __name__ == "__main__":
    main()
