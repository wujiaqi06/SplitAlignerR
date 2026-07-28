#!/usr/bin/env python3
"""Verify completeness and process integrity of Windows cold-start evidence."""

from __future__ import annotations

import csv
import pathlib
import re
import sys


CASES = (
    "numeric_validator",
    "align_fixed_no_prewarm",
    "align_fixed_prewarm",
    "align_no_length_fixed",
    "align_free_no_prewarm",
    "wrapper_core_boundary",
    "standalone_numeric_policy",
    "standalone_regex_construction",
)

COMMON_R_MARKERS = (
    "SCRIPT_STARTED",
    "PACKAGE_LOADED",
    "INPUT_READY",
    "OPERATION_STARTED",
    "OPERATION_FINISHED",
)

PASS_MARKERS = {
    "numeric_validator": COMMON_R_MARKERS
    + (
        "NUMERIC_FIRST_CALL_STARTED",
        "NUMERIC_FIRST_CALL_FINISHED",
        "NUMERIC_SECOND_CALL_STARTED",
        "NUMERIC_SECOND_CALL_FINISHED",
    ),
    "align_fixed_no_prewarm": COMMON_R_MARKERS
    + ("ALIGN_FIXED_STARTED", "ALIGN_FIXED_FINISHED"),
    "align_fixed_prewarm": COMMON_R_MARKERS
    + (
        "NUMERIC_PREWARM_STARTED",
        "NUMERIC_PREWARM_FINISHED",
        "ALIGN_FIXED_AFTER_PREWARM_STARTED",
        "ALIGN_FIXED_AFTER_PREWARM_FINISHED",
    ),
    "align_no_length_fixed": COMMON_R_MARKERS
    + ("ALIGN_NO_LENGTH_FIXED_STARTED", "ALIGN_NO_LENGTH_FIXED_FINISHED"),
    "align_free_no_prewarm": COMMON_R_MARKERS
    + ("ALIGN_FREE_STARTED", "ALIGN_FREE_FINISHED"),
    "wrapper_core_boundary": COMMON_R_MARKERS
    + (
        "AS_SPECIES_NEWICK_STARTED",
        "AS_SPECIES_NEWICK_FINISHED",
        "AS_GENE_NEWICKS_STARTED",
        "AS_GENE_NEWICKS_FINISHED",
        "CPP_ALIGN_BRANCHES_STARTED",
        "CPP_ALIGN_BRANCHES_FINISHED",
    ),
    "standalone_numeric_policy": (
        "SCRIPT_STARTED",
        "OPERATION_STARTED",
        "NUMERIC_FIRST_CALL_STARTED",
        "NUMERIC_FIRST_CALL_FINISHED",
        "NUMERIC_SECOND_CALL_STARTED",
        "NUMERIC_SECOND_CALL_FINISHED",
        "OPERATION_FINISHED",
    ),
    "standalone_regex_construction": (
        "SCRIPT_STARTED",
        "OPERATION_STARTED",
        "REGEX_CONSTRUCTION_STARTED",
        "REGEX_CONSTRUCTION_FINISHED",
        "REGEX_MATCH_STARTED",
        "REGEX_MATCH_FINISHED",
        "OPERATION_FINISHED",
    ),
}


class VerificationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise VerificationError(message)


def parse_key_values(path: pathlib.Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"missing file: {path}")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            if key not in result:
                result[key] = value
    return result


def read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        fail(f"missing file: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def stage_markers(stdout: str) -> list[str]:
    return re.findall(r"^stage_marker: ([A-Z0-9_]+)$", stdout, re.MULTILINE)


def raw_timings(case_id: str, stdout: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^timing_([a-z0-9_]+)_wall_seconds: ([0-9]+(?:\.[0-9]+)?)$",
        re.MULTILINE,
    )
    return [
        {
            "case_id": case_id,
            "timing_name": match.group(1),
            "wall_seconds": match.group(2),
        }
        for match in pattern.finditer(stdout)
    ]


def verify(root: pathlib.Path) -> None:
    metadata = parse_key_values(root / "METADATA.txt")
    if metadata.get("probe_id") != "windows-cold-start-v1":
        fail("unexpected probe_id")
    if metadata.get("fresh_process_policy") != (
        "one new process tree per declared case"
    ):
        fail("fresh-process policy is missing")
    requested = tuple(metadata.get("requested_cases", "").split(","))
    if requested != CASES:
        fail(f"requested case schedule mismatch: {requested}")
    try:
        timeout = float(metadata["per_case_timeout_seconds"])
    except (KeyError, ValueError):
        fail("invalid per-case timeout metadata")
    if timeout <= 0:
        fail("per-case timeout must be positive")

    rows = read_tsv(root / "RESULTS.tsv")
    if tuple(row.get("case_id", "") for row in rows) != CASES:
        fail("RESULTS.tsv does not contain the exact declared case order")
    timing_rows = read_tsv(root / "TIMINGS.tsv")
    expected_timing_rows: list[dict[str, str]] = []
    runner_os = metadata.get("runner_os", "")

    expected_stdout = {f"{case_id}.stdout.txt" for case_id in CASES}
    expected_stderr = {f"{case_id}.stderr.txt" for case_id in CASES}
    observed_stdout = {path.name for path in root.glob("*.stdout.txt")}
    observed_stderr = {path.name for path in root.glob("*.stderr.txt")}
    if observed_stdout != expected_stdout or observed_stderr != expected_stderr:
        fail("raw stdout/stderr file inventory differs from the declared schedule")

    classifications: list[str] = []
    for row in rows:
        case_id = row["case_id"]
        if row.get("fresh_process") != "TRUE":
            fail(f"{case_id}: fresh_process is not TRUE")
        stdout_path = root / row.get("stdout_file", "")
        stderr_path = root / row.get("stderr_file", "")
        if stdout_path.name != f"{case_id}.stdout.txt" or not stdout_path.is_file():
            fail(f"{case_id}: invalid stdout path")
        if stderr_path.name != f"{case_id}.stderr.txt" or not stderr_path.is_file():
            fail(f"{case_id}: invalid stderr path")
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        markers = stage_markers(stdout)
        expected_last = markers[-1] if markers else "NONE"
        if row.get("last_stage_marker") != expected_last:
            fail(f"{case_id}: last stage marker mismatch")
        expected_timing_rows.extend(raw_timings(case_id, stdout))

        classification = row.get("classification", "")
        classifications.append(classification)
        try:
            exit_status = int(row.get("exit_status", ""))
            requested_timeout = float(row.get("timeout_requested_seconds", ""))
            elapsed = float(row.get("elapsed_orchestrator_seconds", ""))
        except ValueError:
            fail(f"{case_id}: malformed numeric result field")
        if requested_timeout != timeout or elapsed < 0:
            fail(f"{case_id}: timeout or elapsed field mismatch")

        if classification == "PASS":
            if exit_status != 0 or row.get("timed_out") != "FALSE":
                fail(f"{case_id}: PASS exit/timeout invariant failed")
            if "case_status: PASS" not in stdout:
                fail(f"{case_id}: PASS marker missing")
            missing = [
                marker for marker in PASS_MARKERS[case_id] if marker not in markers
            ]
            if missing:
                fail(f"{case_id}: missing PASS stage markers {missing}")
        elif classification == "TIMEOUT":
            required = {
                "exit_status": "124",
                "timed_out": "TRUE",
                "timeout_triggered": "TRUE",
                "termination_attempted": "TRUE",
                "termination_confirmed": "TRUE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "TRUE",
            }
            for key, value in required.items():
                if row.get(key) != value:
                    fail(f"{case_id}: TIMEOUT invariant failed for {key}")
            if "case_status:" in stdout or "OPERATION_FINISHED" in markers:
                fail(f"{case_id}: timeout contains late completion output")
            if runner_os == "Windows":
                if row.get("process_tree_kill_strategy") != (
                    "CREATE_NEW_PROCESS_GROUP+taskkill_PID_T_F"
                ):
                    fail(f"{case_id}: Windows timeout kill strategy mismatch")
                if "taskkill_exit=0" not in row.get("termination_detail", ""):
                    fail(f"{case_id}: Windows timeout lacks taskkill success")
        elif classification == "REPORTED_FAILURE":
            if exit_status == 0 or row.get("timed_out") != "FALSE":
                fail(f"{case_id}: reported failure exit invariant failed")
            if "case_status:" not in stdout:
                fail(f"{case_id}: reported failure marker missing")
        elif classification == "CRASH_OR_NONZERO":
            if exit_status == 0 or row.get("timed_out") != "FALSE":
                fail(f"{case_id}: crash/nonzero exit invariant failed")
            if "case_status:" in stdout:
                fail(f"{case_id}: crash/nonzero has a reported case status")
        elif classification == "HARNESS_FAILURE":
            fail(f"{case_id}: evidence declares HARNESS_FAILURE")
        else:
            fail(f"{case_id}: unknown classification {classification!r}")

        if classification != "TIMEOUT":
            for key, value in {
                "timeout_triggered": "FALSE",
                "termination_attempted": "FALSE",
                "termination_confirmed": "NOT_APPLICABLE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "NOT_APPLICABLE",
            }.items():
                if row.get(key) != value:
                    fail(f"{case_id}: non-timeout invariant failed for {key}")

    if timing_rows != expected_timing_rows:
        fail("TIMINGS.tsv does not exactly reproduce raw timing lines")
    for row in timing_rows:
        try:
            if float(row["wall_seconds"]) < 0:
                fail("negative wall timing")
        except (KeyError, ValueError):
            fail("invalid TIMINGS.tsv wall_seconds")

    summary_text = (root / "SUMMARY.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    counts = {
        name: sum(value == name for value in classifications)
        for name in (
            "PASS",
            "TIMEOUT",
            "REPORTED_FAILURE",
            "CRASH_OR_NONZERO",
            "HARNESS_FAILURE",
        )
    }
    required_summary = (
        "scheduled_cases: 8",
        "completed_result_rows: 8",
        f"pass_cases: {counts['PASS']}",
        f"timeout_cases: {counts['TIMEOUT']}",
        f"reported_failure_cases: {counts['REPORTED_FAILURE']}",
        f"crash_or_nonzero_cases: {counts['CRASH_OR_NONZERO']}",
        f"harness_failure_cases: {counts['HARNESS_FAILURE']}",
        "harness_integrity_status: PASS",
        "root_cause_interpretation: DEFERRED_TO_MAIN_CONSOLE_REVIEW",
    )
    for line in required_summary:
        if line not in summary_text:
            fail(f"SUMMARY.txt lacks {line!r}")
    for row in rows:
        expected = (
            f"case_result: {row['case_id']}|{row['classification']}|"
            f"last_stage={row['last_stage_marker']}|"
            f"orchestrator_seconds={row['elapsed_orchestrator_seconds']}"
        )
        if expected not in summary_text:
            fail(f"SUMMARY.txt lacks exact result for {row['case_id']}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: verify_windows_cold_start_evidence.py EVIDENCE_DIR"
        )
    root = pathlib.Path(sys.argv[1]).resolve()
    try:
        verify(root)
    except (OSError, VerificationError) as error:
        print("cold_start_evidence_integrity: FAIL", file=sys.stderr)
        print(f"verification_error: {error}", file=sys.stderr)
        return 1
    print("schedule_and_fresh_process_policy: PASS")
    print("raw_stage_and_timing_contracts: PASS")
    print("process_tree_timeout_invariants: PASS")
    print("cold_start_evidence_integrity: PASS")
    print("root_cause_interpretation: DEFERRED_TO_MAIN_CONSOLE_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
