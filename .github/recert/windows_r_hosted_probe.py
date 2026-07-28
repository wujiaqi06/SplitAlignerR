#!/usr/bin/env python3
"""Run Fix007 R-hosted DLL/package isolation cases in fresh processes."""

from __future__ import annotations

import csv
import os
import pathlib
import platform
import re
import shutil
import sys

from windows_cold_start_probe import (
    has_case_completion,
    last_stage,
    normalize_text,
    parse_timeout,
    parse_timings,
    raw_output,
    run_case,
    run_text,
    sha256,
    utc_now,
    write_text,
)


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


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: windows_r_hosted_probe.py "
            "SOURCE_ROOT OUTPUT_DIR EXPECTED_COMMIT DLL_PATH"
        )
    source_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
    output_dir = pathlib.Path(sys.argv[2])
    expected_commit = sys.argv[3]
    dll_path = pathlib.Path(sys.argv[4]).resolve(strict=True)
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise SystemExit("EXPECTED_COMMIT must be a lowercase 40-hex commit")
    if output_dir.exists():
        raise SystemExit("refusing to overwrite existing R-hosted output")
    output_dir.mkdir(parents=True)

    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("Rscript is required")
    timeout_seconds = parse_timeout()
    case_script = source_root / ".github/recert/windows_r_hosted_case.R"
    metadata = [
        "probe_id: windows-r-hosted-numeric-v1",
        f"source_commit: {expected_commit}",
        "fresh_process_policy: one new R process tree per declared operation",
        f"requested_cases: {','.join(CASES)}",
        f"per_case_timeout_seconds: {timeout_seconds:g}",
        f"runner_os: {os.environ.get('RUNNER_OS', platform.system())}",
        f"runner_arch: {os.environ.get('RUNNER_ARCH', platform.machine())}",
        f"workflow: {os.environ.get('GITHUB_WORKFLOW', 'local')}",
        f"run_id: {os.environ.get('GITHUB_RUN_ID', 'NOT_AVAILABLE')}",
        f"run_attempt: {os.environ.get('GITHUB_RUN_ATTEMPT', 'NOT_AVAILABLE')}",
        f"runner_name: {os.environ.get('RUNNER_NAME', 'NOT_AVAILABLE')}",
        f"os: {platform.platform()}",
        f"R: {run_text([rscript, '--version']).splitlines()[0]}",
        f"diagnostic_dll_name: {dll_path.name}",
        f"diagnostic_dll_sha256: {sha256(dll_path)}",
        "root_cause_interpretation: DEFERRED_TO_TRIGGER_CLASSIFIER",
        f"started_utc: {utc_now()}",
    ]
    write_text(output_dir / "METADATA.txt", "\n".join(metadata) + "\n")

    result_rows: list[dict[str, object]] = []
    timing_rows: list[dict[str, str]] = []
    harness_failure = False
    for case_id in CASES:
        command = [rscript, str(case_script), case_id, str(dll_path)]
        execution = run_case(command, timeout_seconds)
        stdout = str(execution["stdout"])
        normalized_stdout = normalize_text(stdout)
        exit_status = int(execution["exit_status"])
        timed_out = bool(execution["timeout_triggered"])
        termination_confirmed = bool(execution["termination_confirmed"])
        late_completion = bool(execution["late_completion_detected"])
        if timed_out and (not termination_confirmed or late_completion):
            classification = "HARNESS_FAILURE"
            harness_failure = True
        elif timed_out:
            classification = "TIMEOUT"
        elif exit_status == 0 and "case_status: PASS" in normalized_stdout:
            classification = "PASS"
        elif has_case_completion(stdout):
            classification = "REPORTED_FAILURE"
        else:
            classification = "CRASH_OR_NONZERO"

        stdout_file = output_dir / f"{case_id}.stdout.txt"
        stderr_file = output_dir / f"{case_id}.stderr.txt"
        stdout_file.write_bytes(raw_output(execution["stdout_bytes"]))
        stderr_file.write_bytes(raw_output(execution["stderr_bytes"]))
        timing_rows.extend(parse_timings(case_id, stdout))
        result_rows.append(
            {
                "case_id": case_id,
                "fresh_process": "TRUE",
                "classification": classification,
                "exit_status": exit_status,
                "timed_out": str(timed_out).upper(),
                "timeout_requested_seconds": f"{timeout_seconds:g}",
                "timeout_triggered": str(timed_out).upper(),
                "termination_attempted": str(
                    execution["termination_attempted"]
                ).upper(),
                "termination_confirmed": (
                    str(termination_confirmed).upper()
                    if timed_out
                    else "NOT_APPLICABLE"
                ),
                "process_tree_kill_strategy": execution[
                    "process_tree_kill_strategy"
                ],
                "termination_detail": execution["termination_detail"],
                "late_completion_detected": str(late_completion).upper(),
                "output_streams_closed_after_termination": (
                    execution["output_streams_closed_after_termination"]
                    if isinstance(
                        execution["output_streams_closed_after_termination"],
                        str,
                    )
                    else str(
                        execution["output_streams_closed_after_termination"]
                    ).upper()
                ),
                "elapsed_orchestrator_seconds": (
                    f"{float(execution['elapsed_orchestrator_seconds']):.6f}"
                ),
                "last_stage_marker": last_stage(stdout),
                "stdout_file": stdout_file.name,
                "stderr_file": stderr_file.name,
            }
        )

    result_fields = [
        "case_id",
        "fresh_process",
        "classification",
        "exit_status",
        "timed_out",
        "timeout_requested_seconds",
        "timeout_triggered",
        "termination_attempted",
        "termination_confirmed",
        "process_tree_kill_strategy",
        "termination_detail",
        "late_completion_detected",
        "output_streams_closed_after_termination",
        "elapsed_orchestrator_seconds",
        "last_stage_marker",
        "stdout_file",
        "stderr_file",
    ]
    with (output_dir / "RESULTS.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=result_fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(result_rows)
    with (output_dir / "TIMINGS.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("case_id", "timing_name", "wall_seconds"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(timing_rows)

    counts = {
        name: sum(row["classification"] == name for row in result_rows)
        for name in (
            "PASS",
            "TIMEOUT",
            "REPORTED_FAILURE",
            "CRASH_OR_NONZERO",
            "HARNESS_FAILURE",
        )
    }
    summary = [
        "probe_id: windows-r-hosted-numeric-v1",
        f"scheduled_cases: {len(CASES)}",
        f"completed_result_rows: {len(result_rows)}",
        f"pass_cases: {counts['PASS']}",
        f"timeout_cases: {counts['TIMEOUT']}",
        f"reported_failure_cases: {counts['REPORTED_FAILURE']}",
        f"crash_or_nonzero_cases: {counts['CRASH_OR_NONZERO']}",
        f"harness_failure_cases: {counts['HARNESS_FAILURE']}",
        "harness_integrity_status: " + ("FAIL" if harness_failure else "PASS"),
        "root_cause_interpretation: DEFERRED_TO_TRIGGER_CLASSIFIER",
        f"finished_utc: {utc_now()}",
    ]
    for row in result_rows:
        summary.append(
            "case_result: "
            f"{row['case_id']}|{row['classification']}|"
            f"last_stage={row['last_stage_marker']}|"
            f"orchestrator_seconds={row['elapsed_orchestrator_seconds']}"
        )
    write_text(output_dir / "SUMMARY.txt", "\n".join(summary) + "\n")
    return 1 if harness_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
