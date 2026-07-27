#!/usr/bin/env python3
"""Independently verify process-tree timeout evidence invariants."""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys


REQUIRED_COLUMNS = {
    "classification",
    "exit_status",
    "timed_out",
    "timeout_requested_seconds",
    "timeout_triggered",
    "termination_attempted",
    "termination_confirmed",
    "process_tree_kill_strategy",
    "late_completion_detected",
    "output_streams_closed_after_termination",
    "stdout_file",
    "stderr_file",
}


def fail(message: str) -> None:
    raise SystemExit(f"deep-tree evidence verification failed: {message}")


def safe_evidence_file(root: pathlib.Path, value: str) -> pathlib.Path:
    relative = pathlib.PurePosixPath(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        fail(f"unsafe evidence path: {value!r}")
    path = root / value
    if not path.is_file():
        fail(f"missing evidence file: {value}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_dir")
    args = parser.parse_args()
    root = pathlib.Path(args.evidence_dir).resolve(strict=True)
    results = root / "RESULTS.tsv"
    if not results.is_file():
        fail("RESULTS.tsv is missing")

    with results.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        columns = set(reader.fieldnames or [])
        if not REQUIRED_COLUMNS.issubset(columns):
            fail(f"missing RESULTS columns: {sorted(REQUIRED_COLUMNS - columns)}")
        rows = list(reader)
    if not rows:
        fail("RESULTS.tsv contains no cases")

    timeout_rows = 0
    for index, row in enumerate(rows, start=2):
        stdout = safe_evidence_file(root, row["stdout_file"]).read_text(
            encoding="utf-8", errors="replace"
        )
        safe_evidence_file(root, row["stderr_file"])
        timeout = row["classification"] == "TIMEOUT"
        triggered = row["timeout_triggered"] == "TRUE"
        if timeout:
            timeout_rows += 1
            required = {
                "exit_status": "124",
                "timed_out": "TRUE",
                "timeout_triggered": "TRUE",
                "termination_attempted": "TRUE",
                "termination_confirmed": "TRUE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "TRUE",
            }
            for field, expected in required.items():
                if row[field] != expected:
                    fail(
                        f"row {index} TIMEOUT has {field}={row[field]!r}, "
                        f"expected {expected!r}"
                    )
            if row["process_tree_kill_strategy"] in ("", "NOT_APPLICABLE"):
                fail(f"row {index} TIMEOUT has no process-tree kill strategy")
            if "case_status:" in stdout:
                fail(
                    f"row {index} is TIMEOUT but raw stdout contains a late "
                    "case_status"
                )
        elif triggered:
            fail(
                f"row {index} triggered a timeout but classification is "
                f"{row['classification']!r}"
            )

    summary = (root / "SUMMARY.txt").read_text(encoding="utf-8")
    required_summary = {
        "timeout_process_tree_termination_all_confirmed: TRUE",
        "late_completion_observed: FALSE",
        "overall_probe_status: PASS",
    }
    missing = sorted(line for line in required_summary if line not in summary)
    if missing:
        fail(f"summary assertions missing: {missing}")

    print(f"verified_case_rows: {len(rows)}")
    print(f"verified_timeout_rows: {timeout_rows}")
    print("timeout_stdout_late_completion_conflicts: 0")
    print("process_tree_termination_invariants: PASS")
    print("overall_status: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

