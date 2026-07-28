#!/usr/bin/env python3
"""Verify Fix007 R-hosted DLL/package isolation evidence."""

from __future__ import annotations

import csv
import pathlib
import re
import sys


CASES = (
    "dll_locale",
    "dll_noop",
    "dll_strtod",
    "dll_ascii_marker",
    "dll_regex_automatic",
    "dll_regex_static",
    "dll_frozen_numeric",
    "package_core_info",
    "package_numeric_validator",
)


class VerificationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise VerificationError(message)


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def raw_text(path: pathlib.Path) -> str:
    if not path.is_file():
        fail(f"missing file: {path}")
    return path.read_bytes().decode("utf-8", errors="replace")


def key_values(path: pathlib.Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in normalize_text(raw_text(path)).splitlines():
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


def markers(text: str) -> list[str]:
    return re.findall(
        r"^stage_marker: ([A-Z0-9_]+)$",
        normalize_text(text),
        re.MULTILINE,
    )


def timings(case_id: str, text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^timing_([a-z0-9_]+)_wall_seconds: "
        r"([0-9]+(?:\.[0-9]+)?)$",
        re.MULTILINE,
    )
    return [
        {
            "case_id": case_id,
            "timing_name": match.group(1),
            "wall_seconds": match.group(2),
        }
        for match in pattern.finditer(normalize_text(text))
    ]


def required_pass_markers(case_id: str) -> tuple[str, ...]:
    upper = case_id.upper()
    boundary = (
        ("DLL_LOAD_STARTED", "DLL_LOAD_FINISHED")
        if case_id.startswith("dll_")
        else ("PACKAGE_LOADED",)
    )
    return (
        "SCRIPT_STARTED",
        "LOCALE_RECORDED",
        *boundary,
        "OPERATION_STARTED",
        f"{upper}_FIRST_CALL_STARTED",
        f"{upper}_FIRST_CALL_FINISHED",
        f"{upper}_SECOND_CALL_STARTED",
        f"{upper}_SECOND_CALL_FINISHED",
        "OPERATION_FINISHED",
    )


def verify(root: pathlib.Path, expected_commit: str) -> None:
    metadata = key_values(root / "METADATA.txt")
    if metadata.get("probe_id") != "windows-r-hosted-numeric-v1":
        fail("unexpected probe id")
    if metadata.get("source_commit") != expected_commit:
        fail("source commit metadata mismatch")
    if metadata.get("fresh_process_policy") != (
        "one new R process tree per declared operation"
    ):
        fail("fresh-process policy mismatch")
    if tuple(metadata.get("requested_cases", "").split(",")) != CASES:
        fail("requested operation schedule mismatch")
    if re.fullmatch(
        r"[0-9a-f]{64}", metadata.get("diagnostic_dll_sha256", "")
    ) is None:
        fail("diagnostic DLL SHA-256 metadata is invalid")
    try:
        timeout = float(metadata["per_case_timeout_seconds"])
    except (KeyError, ValueError):
        fail("invalid timeout metadata")
    if timeout <= 0:
        fail("nonpositive timeout metadata")

    rows = read_tsv(root / "RESULTS.tsv")
    if tuple(row.get("case_id", "") for row in rows) != CASES:
        fail("RESULTS.tsv schedule mismatch")
    expected_timings: list[dict[str, str]] = []
    classifications: list[str] = []
    runner_os = metadata.get("runner_os", "")

    for row in rows:
        case_id = row["case_id"]
        if row.get("fresh_process") != "TRUE":
            fail(f"{case_id}: fresh-process flag differs")
        stdout_path = root / row.get("stdout_file", "")
        stderr_path = root / row.get("stderr_file", "")
        if stdout_path.name != f"{case_id}.stdout.txt":
            fail(f"{case_id}: stdout name differs")
        if stderr_path.name != f"{case_id}.stderr.txt":
            fail(f"{case_id}: stderr name differs")
        stdout = raw_text(stdout_path)
        raw_text(stderr_path)
        normalized = normalize_text(stdout)
        observed_markers = markers(stdout)
        expected_last = observed_markers[-1] if observed_markers else "NONE"
        if row.get("last_stage_marker") != expected_last:
            fail(f"{case_id}: last-stage mismatch")
        expected_timings.extend(timings(case_id, stdout))

        for locale_key in ("R_version", "R_platform", "locale_evidence_case"):
            if f"{locale_key}: " not in normalized:
                fail(f"{case_id}: missing {locale_key}")
        if case_id == "dll_locale":
            for locale_key in ("LC_CTYPE", "LC_COLLATE", "LC_NUMERIC"):
                if f"{locale_key}: " not in normalized:
                    fail(f"{case_id}: missing effective {locale_key}")
        elif "locale_values: see fresh dll_locale case" not in normalized:
            fail(f"{case_id}: missing locale evidence reference")
        for marker in ("SCRIPT_STARTED", "LOCALE_RECORDED"):
            if marker not in observed_markers:
                fail(f"{case_id}: missing base marker {marker}")
        if case_id.startswith("dll_"):
            for key in (
                "diagnostic_dll_path: ",
                "loaded_dll_name: ",
                "loaded_dll_path: ",
                "loaded_dll_dynamic_lookup: ",
            ):
                if key not in normalized:
                    fail(f"{case_id}: missing runtime DLL identity {key}")

        classification = row.get("classification", "")
        classifications.append(classification)
        try:
            status = int(row.get("exit_status", ""))
            requested = float(row.get("timeout_requested_seconds", ""))
            elapsed = float(row.get("elapsed_orchestrator_seconds", ""))
        except ValueError:
            fail(f"{case_id}: malformed numeric field")
        if requested != timeout or elapsed < 0:
            fail(f"{case_id}: timeout/elapsed mismatch")

        if classification == "PASS":
            if status != 0 or row.get("timed_out") != "FALSE":
                fail(f"{case_id}: PASS status mismatch")
            if "case_status: PASS" not in normalized:
                fail(f"{case_id}: PASS marker missing")
            missing = [
                marker
                for marker in required_pass_markers(case_id)
                if marker not in observed_markers
            ]
            if missing:
                fail(f"{case_id}: missing PASS markers {missing}")
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
            if any(row.get(key) != value for key, value in required.items()):
                fail(f"{case_id}: timeout invariant differs")
            if "case_status:" in normalized or "OPERATION_FINISHED" in observed_markers:
                fail(f"{case_id}: timeout contains late completion")
            if runner_os == "Windows":
                if row.get("process_tree_kill_strategy") != (
                    "CREATE_NEW_PROCESS_GROUP+taskkill_PID_T_F"
                ):
                    fail(f"{case_id}: Windows kill strategy differs")
                if "taskkill_exit=0" not in row.get("termination_detail", ""):
                    fail(f"{case_id}: Windows taskkill success absent")
        elif classification in {"REPORTED_FAILURE", "CRASH_OR_NONZERO"}:
            if status == 0 or row.get("timed_out") != "FALSE":
                fail(f"{case_id}: nonzero classification invariant differs")
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
                    fail(f"{case_id}: non-timeout invariant differs for {key}")

    if read_tsv(root / "TIMINGS.tsv") != expected_timings:
        fail("TIMINGS.tsv differs from normalized raw stdout")
    summary = normalize_text(raw_text(root / "SUMMARY.txt"))
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
    for line in (
        f"scheduled_cases: {len(CASES)}",
        f"completed_result_rows: {len(CASES)}",
        f"pass_cases: {counts['PASS']}",
        f"timeout_cases: {counts['TIMEOUT']}",
        f"reported_failure_cases: {counts['REPORTED_FAILURE']}",
        f"crash_or_nonzero_cases: {counts['CRASH_OR_NONZERO']}",
        f"harness_failure_cases: {counts['HARNESS_FAILURE']}",
        "harness_integrity_status: PASS",
        "root_cause_interpretation: DEFERRED_TO_TRIGGER_CLASSIFIER",
    ):
        if line not in summary:
            fail(f"SUMMARY.txt lacks {line!r}")
    for row in rows:
        line = (
            f"case_result: {row['case_id']}|{row['classification']}|"
            f"last_stage={row['last_stage_marker']}|"
            f"orchestrator_seconds={row['elapsed_orchestrator_seconds']}"
        )
        if line not in summary:
            fail(f"SUMMARY.txt lacks exact row for {row['case_id']}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: verify_windows_r_hosted_evidence.py "
            "EVIDENCE_DIR EXPECTED_COMMIT"
        )
    expected_commit = sys.argv[2]
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise SystemExit("EXPECTED_COMMIT must be a lowercase 40-hex commit")
    try:
        verify(pathlib.Path(sys.argv[1]).resolve(), expected_commit)
    except (OSError, VerificationError) as error:
        print("r_hosted_evidence_integrity: FAIL", file=sys.stderr)
        print(f"verification_error: {error}", file=sys.stderr)
        return 1
    print("r_hosted_schedule_and_fresh_process_policy: PASS")
    print("r_hosted_raw_stage_and_timing_contracts: PASS")
    print("r_hosted_process_tree_timeout_invariants: PASS")
    print("r_hosted_evidence_integrity: PASS")
    print("root_cause_interpretation: DEFERRED_TO_TRIGGER_CLASSIFIER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
