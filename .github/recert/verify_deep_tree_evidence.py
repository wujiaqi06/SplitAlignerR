#!/usr/bin/env python3
"""Independently verify deep-tree scheduling and process evidence invariants."""

from __future__ import annotations

import argparse
import csv
import math
import pathlib
import re
import sys


OPERATIONS = ("validate_species_tree", "align_branches")
RESULT_COLUMNS = [
    "operation",
    "taxa",
    "depth",
    "newick_bytes",
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
    "termination_detail",
    "elapsed_orchestrator_seconds",
    "stdout_file",
    "stderr_file",
]
PRE_STATUS_MARKERS = (
    "SCRIPT_STARTED",
    "PACKAGE_LOADED",
    "INPUT_READY",
    "OPERATION_STARTED",
    "OPERATION_FINISHED",
)
PASS_MARKERS = PRE_STATUS_MARKERS + (
    "RESULT_SERIALIZATION_STARTED",
    "CASE_FINISHED",
)
CONTINUE_POLICY = (
    "continue requested sizes after a passing case even if a later case "
    "is non-PASS; stop immediately if no passing case has been observed"
)
STOP_POLICY = "stop after first non-PASS case"
PROBE_SEQUENCE = (
    "ascending taxa; requested operations in declared order at each size"
)


def fail(message: str) -> None:
    raise SystemExit(f"deep-tree evidence verification failed: {message}")


def read_required(path: pathlib.Path) -> str:
    if not path.is_file():
        fail(f"missing evidence file: {path.name}")
    return path.read_text(encoding="utf-8", errors="replace")


def safe_evidence_file(root: pathlib.Path, value: str) -> pathlib.Path:
    relative = pathlib.PurePosixPath(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        fail(f"unsafe evidence path: {value!r}")
    path = root / value
    if not path.is_file():
        fail(f"missing evidence file: {value}")
    return path


def single_text_value(text: str, key: str, source: str) -> str:
    values = re.findall(
        rf"^{re.escape(key)}: (.*)$", text, flags=re.MULTILINE
    )
    if len(values) != 1:
        fail(
            f"{source} must contain exactly one {key!r} field; "
            f"observed {len(values)}"
        )
    return values[0].strip()


def parse_metadata(
    text: str,
) -> tuple[tuple[str, ...], tuple[int, ...], str, bool]:
    operations_text = single_text_value(
        text, "requested_operations", "METADATA.txt"
    )
    operations = tuple(operations_text.split(","))
    if (
        not operations
        or any(not operation for operation in operations)
        or len(set(operations)) != len(operations)
        or any(operation not in OPERATIONS for operation in operations)
    ):
        fail(
            "metadata requested_operations must be a unique nonempty subset "
            f"of {','.join(OPERATIONS)}"
        )

    sizes_text = single_text_value(text, "requested_sizes", "METADATA.txt")
    size_items = sizes_text.split(",")
    if not size_items or any(
        re.fullmatch(r"[0-9]+", item) is None for item in size_items
    ):
        fail("metadata requested_sizes must contain decimal integers")
    sizes = tuple(int(item) for item in size_items)
    if (
        any(size < 2 for size in sizes)
        or any(left >= right for left, right in zip(sizes, sizes[1:]))
    ):
        fail(
            "metadata requested_sizes must be strictly increasing unique "
            "integers >= 2"
        )

    timeout_text = single_text_value(
        text, "per_case_timeout_seconds", "METADATA.txt"
    )
    try:
        timeout = float(timeout_text)
    except ValueError:
        fail("metadata per_case_timeout_seconds is not numeric")
    if not math.isfinite(timeout) or timeout <= 0:
        fail("metadata per_case_timeout_seconds must be finite and positive")

    continue_text = single_text_value(
        text, "continue_after_nonpass", "METADATA.txt"
    )
    if continue_text not in ("TRUE", "FALSE"):
        fail("metadata continue_after_nonpass must be TRUE or FALSE")
    continue_after_nonpass = continue_text == "TRUE"

    expected_policy = CONTINUE_POLICY if continue_after_nonpass else STOP_POLICY
    if single_text_value(text, "sampling_policy", "METADATA.txt") != expected_policy:
        fail("metadata sampling_policy disagrees with continue_after_nonpass")
    if single_text_value(text, "probe_sequence", "METADATA.txt") != PROBE_SEQUENCE:
        fail("metadata probe_sequence is not the frozen nested-loop order")

    return operations, sizes, timeout_text, continue_after_nonpass


def decimal_integer(value: str, field: str, row_number: int) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        fail(f"row {row_number} has invalid {field}={value!r}")
    return int(value)


def raw_values(text: str, key: str) -> list[str]:
    return re.findall(rf"^{re.escape(key)}: (.*)$", text, flags=re.MULTILINE)


def require_raw_value(
    text: str, key: str, expected: str, row_number: int
) -> None:
    values = raw_values(text, key)
    if values != [expected]:
        fail(
            f"row {row_number} stdout has {key} values {values!r}; "
            f"expected [{expected!r}]"
        )


def validate_stage_markers(
    stdout: str, classification: str, row_number: int
) -> tuple[str, ...]:
    stage_lines = [
        line for line in stdout.splitlines() if line.startswith("stage_marker:")
    ]
    markers: list[str] = []
    for line in stage_lines:
        match = re.fullmatch(r"stage_marker: ([A-Z_]+)", line)
        if not match:
            fail(f"row {row_number} has malformed stage marker: {line!r}")
        markers.append(match.group(1))

    observed = tuple(markers)
    if classification == "PASS":
        expected = PASS_MARKERS
        if observed != expected:
            fail(
                f"row {row_number} PASS stage markers are {observed!r}; "
                f"expected {expected!r}"
            )
    elif classification == "GRACEFUL_FAILURE":
        expected = PRE_STATUS_MARKERS
        if observed != expected:
            fail(
                f"row {row_number} GRACEFUL_FAILURE stage markers are "
                f"{observed!r}; expected {expected!r}"
            )
    elif classification == "TIMEOUT":
        if observed != PRE_STATUS_MARKERS[: len(observed)]:
            fail(
                f"row {row_number} TIMEOUT stage markers are not a valid "
                f"execution prefix: {observed!r}"
            )
    return observed


def validate_raw_identity(
    stdout: str,
    operation: str,
    taxa: int,
    row_newick_bytes: str,
    row_number: int,
    required: bool,
) -> None:
    expected = {
        "operation": operation,
        "taxa": str(taxa),
        "comb_depth": str(taxa - 1),
    }
    for key, value in expected.items():
        values = raw_values(stdout, key)
        if required or values:
            if values != [value]:
                fail(
                    f"row {row_number} stdout has {key} values {values!r}; "
                    f"expected [{value!r}]"
                )

    byte_values = raw_values(stdout, "newick_bytes")
    if required or byte_values:
        if len(byte_values) != 1 or re.fullmatch(
            r"0|[1-9][0-9]*", byte_values[0]
        ) is None:
            fail(f"row {row_number} stdout has invalid newick_bytes")
        if row_newick_bytes != byte_values[0]:
            fail(
                f"row {row_number} RESULTS newick_bytes disagrees with stdout"
            )
    elif row_newick_bytes:
        fail(
            f"row {row_number} RESULTS has newick_bytes without raw stdout value"
        )


def require_fields(
    row: dict[str, str], expected: dict[str, str], row_number: int
) -> None:
    for field, value in expected.items():
        if row[field] != value:
            fail(
                f"row {row_number} has {field}={row[field]!r}; "
                f"expected {value!r}"
            )


def validate_case_row(
    root: pathlib.Path,
    row: dict[str, str],
    operation: str,
    taxa: int,
    timeout_text: str,
    row_number: int,
    used_paths: set[str],
) -> str:
    if row["operation"] != operation or row["taxa"] != str(taxa):
        fail(
            f"row {row_number} schedule is {row['operation']!r}/{row['taxa']!r}; "
            f"expected {operation!r}/{taxa}"
        )
    if decimal_integer(row["depth"], "depth", row_number) != taxa - 1:
        fail(f"row {row_number} depth disagrees with taxa")
    if row["timeout_requested_seconds"] != timeout_text:
        fail(f"row {row_number} timeout disagrees with METADATA.txt")
    try:
        elapsed = float(row["elapsed_orchestrator_seconds"])
    except ValueError:
        fail(f"row {row_number} elapsed_orchestrator_seconds is not numeric")
    if not math.isfinite(elapsed) or elapsed < 0:
        fail(
            f"row {row_number} elapsed_orchestrator_seconds must be finite "
            "and nonnegative"
        )

    label = f"{operation}_taxa_{taxa:06d}"
    expected_stdout = f"{label}.stdout.txt"
    expected_stderr = f"{label}.stderr.txt"
    if row["stdout_file"] != expected_stdout or row["stderr_file"] != expected_stderr:
        fail(f"row {row_number} raw evidence filenames disagree with schedule")
    for field in ("stdout_file", "stderr_file"):
        if row[field] in used_paths:
            fail(f"row {row_number} reuses evidence path {row[field]!r}")
        used_paths.add(row[field])
    stdout = safe_evidence_file(root, row["stdout_file"]).read_text(
        encoding="utf-8", errors="replace"
    )
    safe_evidence_file(root, row["stderr_file"])

    classification = row["classification"]
    if classification in ("CRASH_OR_NONZERO", "HARNESS_FAILURE"):
        fail(f"row {row_number} contains hard failure {classification}")
    if classification not in ("PASS", "TIMEOUT", "GRACEFUL_FAILURE"):
        fail(f"row {row_number} has unknown classification {classification!r}")

    markers = validate_stage_markers(stdout, classification, row_number)
    if classification == "PASS":
        require_fields(
            row,
            {
                "exit_status": "0",
                "timed_out": "FALSE",
                "timeout_triggered": "FALSE",
                "termination_attempted": "FALSE",
                "termination_confirmed": "NOT_APPLICABLE",
                "process_tree_kill_strategy": "NOT_APPLICABLE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "NOT_APPLICABLE",
                "termination_detail": "NOT_APPLICABLE",
            },
            row_number,
        )
        require_raw_value(stdout, "case_status", "PASS", row_number)
        validate_raw_identity(
            stdout,
            operation,
            taxa,
            row["newick_bytes"],
            row_number,
            required=True,
        )
        require_raw_value(stdout, "result_tips", str(taxa), row_number)
    elif classification == "GRACEFUL_FAILURE":
        require_fields(
            row,
            {
                "exit_status": "2",
                "timed_out": "FALSE",
                "timeout_triggered": "FALSE",
                "termination_attempted": "FALSE",
                "termination_confirmed": "NOT_APPLICABLE",
                "process_tree_kill_strategy": "NOT_APPLICABLE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "NOT_APPLICABLE",
                "termination_detail": "NOT_APPLICABLE",
            },
            row_number,
        )
        require_raw_value(stdout, "case_status", "GRACEFUL_FAILURE", row_number)
        errors = raw_values(stdout, "error_message")
        if len(errors) != 1 or "safe recursion depth" not in errors[0]:
            fail(
                f"row {row_number} is not the expected safe-depth "
                "GRACEFUL_FAILURE"
            )
        validate_raw_identity(
            stdout,
            operation,
            taxa,
            row["newick_bytes"],
            row_number,
            required=True,
        )
    else:
        require_fields(
            row,
            {
                "exit_status": "124",
                "timed_out": "TRUE",
                "timeout_triggered": "TRUE",
                "termination_attempted": "TRUE",
                "termination_confirmed": "TRUE",
                "late_completion_detected": "FALSE",
                "output_streams_closed_after_termination": "TRUE",
            },
            row_number,
        )
        if row["process_tree_kill_strategy"] in ("", "NOT_APPLICABLE"):
            fail(f"row {row_number} TIMEOUT has no process-tree kill strategy")
        if row["termination_detail"] in ("", "NOT_APPLICABLE"):
            fail(f"row {row_number} TIMEOUT has no termination detail")
        if raw_values(stdout, "case_status"):
            fail(f"row {row_number} TIMEOUT stdout contains a late case_status")
        validate_raw_identity(
            stdout,
            operation,
            taxa,
            row["newick_bytes"],
            row_number,
            required="OPERATION_STARTED" in markers,
        )

    return classification


def verify_schedule(
    root: pathlib.Path,
    rows: list[dict[str, str]],
    operations: tuple[str, ...],
    sizes: tuple[int, ...],
    timeout_text: str,
    continue_after_nonpass: bool,
) -> bool:
    row_index = 0
    passing_observed = {operation: False for operation in operations}
    stopped_after_nonpass = False
    used_paths: set[str] = set()

    for taxa in sizes:
        for operation in operations:
            if row_index >= len(rows):
                fail(
                    "RESULTS.tsv ended before scheduled case "
                    f"{operation}/{taxa}"
                )
            row = rows[row_index]
            classification = validate_case_row(
                root,
                row,
                operation,
                taxa,
                timeout_text,
                row_index + 2,
                used_paths,
            )
            row_index += 1
            if classification == "PASS":
                passing_observed[operation] = True
            elif not continue_after_nonpass or not passing_observed[operation]:
                stopped_after_nonpass = True
                if row_index != len(rows):
                    fail(
                        "RESULTS.tsv contains cases after the required "
                        "non-PASS stop"
                    )
                return stopped_after_nonpass

    if row_index != len(rows):
        fail("RESULTS.tsv contains cases beyond the requested schedule")
    return stopped_after_nonpass


def expected_summary_lines(
    rows: list[dict[str, str]],
    operations: tuple[str, ...],
    stopped_after_nonpass: bool,
) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    missing_passing_cases: list[str] = []
    for operation in operations:
        selected = [row for row in rows if row["operation"] == operation]
        passed = [row for row in selected if row["classification"] == "PASS"]
        graceful = [
            row
            for row in selected
            if row["classification"] == "GRACEFUL_FAILURE"
        ]
        timeout = [
            row for row in selected if row["classification"] == "TIMEOUT"
        ]
        if not passed:
            missing_passing_cases.append(operation)
        coverage = (
            "PASSING_CASE_OBSERVED"
            if passed
            else "INCONCLUSIVE_NO_PASSING_CASE"
        )
        lines.extend(
            [
                f"operation: {operation}",
                f"operation_coverage_status: {coverage}",
                "maximum_passing_taxa: "
                + (
                    str(max(int(row["taxa"]) for row in passed))
                    if passed
                    else "NONE"
                ),
                "first_graceful_failure_taxa: "
                + (graceful[0]["taxa"] if graceful else "NONE"),
                "first_crash_or_timeout_taxa: "
                + (timeout[0]["taxa"] if timeout else "NONE"),
                "first_crash_or_timeout_class: "
                + ("TIMEOUT" if timeout else "NONE"),
            ]
        )

    aggregate_coverage = (
        "INCONCLUSIVE_NO_PASSING_CASE"
        if missing_passing_cases
        else "PASSING_CASE_OBSERVED"
    )
    aggregate_overall = (
        "INCONCLUSIVE_NO_PASSING_CASE" if missing_passing_cases else "PASS"
    )
    lines.extend(
        [
            "direct_crash_or_unclassified_nonzero_observed: FALSE",
            "timeout_boundary_observed: "
            + str(
                any(row["classification"] == "TIMEOUT" for row in rows)
            ).upper(),
            "timeout_process_tree_termination_all_confirmed: TRUE",
            "late_completion_observed: FALSE",
            "unexpected_graceful_failure_observed: FALSE",
            "stopped_after_nonpass: "
            + str(stopped_after_nonpass).upper(),
            "harness_integrity_status: PASS",
            "operation_coverage_status: " + aggregate_coverage,
            "overall_probe_status: " + aggregate_overall,
        ]
    )
    return lines, missing_passing_cases


def verify_summary(
    text: str,
    rows: list[dict[str, str]],
    operations: tuple[str, ...],
    stopped_after_nonpass: bool,
) -> list[str]:
    expected, missing_passing_cases = expected_summary_lines(
        rows, operations, stopped_after_nonpass
    )
    observed = text.splitlines()
    if len(observed) != len(expected) + 1:
        fail(
            "SUMMARY.txt has an unexpected number of lines: "
            f"observed {len(observed)}, expected {len(expected) + 1}"
        )
    for index, (actual, wanted) in enumerate(
        zip(observed[:-1], expected), start=1
    ):
        if actual != wanted:
            fail(
                f"SUMMARY.txt line {index} is {actual!r}; expected {wanted!r}"
            )
    if re.fullmatch(
        r"finished_utc: [0-9]{4}-[0-9]{2}-[0-9]{2} "
        r"[0-9]{2}:[0-9]{2}:[0-9]{2} UTC",
        observed[-1],
    ) is None:
        fail("SUMMARY.txt has an invalid finished_utc field")
    return missing_passing_cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_dir")
    args = parser.parse_args()
    root = pathlib.Path(args.evidence_dir).resolve(strict=True)

    metadata = read_required(root / "METADATA.txt")
    operations, sizes, timeout_text, continue_after_nonpass = parse_metadata(
        metadata
    )

    results = root / "RESULTS.tsv"
    if not results.is_file():
        fail("RESULTS.tsv is missing")
    with results.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != RESULT_COLUMNS:
            fail(
                "RESULTS.tsv columns or column order disagree with the "
                "frozen evidence schema"
            )
        rows = list(reader)
    if not rows:
        fail("RESULTS.tsv contains no cases")
    for row_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            fail(f"row {row_number} has too many or too few TSV fields")

    stopped_after_nonpass = verify_schedule(
        root,
        rows,
        operations,
        sizes,
        timeout_text,
        continue_after_nonpass,
    )
    missing_passing_cases = verify_summary(
        read_required(root / "SUMMARY.txt"),
        rows,
        operations,
        stopped_after_nonpass,
    )

    timeout_rows = sum(
        row["classification"] == "TIMEOUT" for row in rows
    )
    graceful_rows = sum(
        row["classification"] == "GRACEFUL_FAILURE" for row in rows
    )
    print(f"verified_case_rows: {len(rows)}")
    print(f"verified_timeout_rows: {timeout_rows}")
    print(f"verified_expected_safe_depth_rows: {graceful_rows}")
    print("schedule_and_stop_policy: PASS")
    print("raw_case_contracts: PASS")
    print("process_tree_termination_invariants: PASS")
    print("harness_integrity_status: PASS")
    if missing_passing_cases:
        print("operation_coverage_status: INCONCLUSIVE_NO_PASSING_CASE")
        print(
            "operations_without_passing_case: "
            + ",".join(missing_passing_cases)
        )
        print("overall_status: INCONCLUSIVE_NO_PASSING_CASE")
        return 2
    print("operation_coverage_status: PASSING_CASE_OBSERVED")
    print("overall_status: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
