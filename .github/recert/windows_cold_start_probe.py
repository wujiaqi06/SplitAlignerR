#!/usr/bin/env python3
"""Capture bounded Windows cold-start evidence in fresh processes."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
import pathlib
import platform
import re
import shutil
import signal
import subprocess
import sys
import time


R_CASES = (
    "numeric_validator",
    "align_fixed_no_prewarm",
    "align_fixed_prewarm",
    "align_no_length_fixed",
    "align_free_no_prewarm",
    "wrapper_core_boundary",
)
MICROPROBE_CASES = (
    "standalone_numeric_policy",
    "standalone_regex_construction",
)
ALL_CASES = R_CASES + MICROPROBE_CASES


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: pathlib.Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def one_line(value: str) -> str:
    return " | ".join(
        value.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    )


def run_text(command: list[str]) -> str:
    result = subprocess.run(
        command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout = decode_output(result.stdout).strip()
    stderr = decode_output(result.stderr).strip()
    return stdout if stdout else stderr


def terminate_process_tree(
    process: subprocess.Popen[bytes],
) -> tuple[str, bool, str]:
    if os.name == "nt":
        strategy = "CREATE_NEW_PROCESS_GROUP+taskkill_PID_T_F"
        taskkill = shutil.which("taskkill")
        if not taskkill:
            return strategy, False, "taskkill executable not found"
        try:
            killed = subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return strategy, False, "taskkill did not finish within 30 seconds"
        detail = one_line(
            decode_output(killed.stdout) + " " + decode_output(killed.stderr)
        ).strip()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            return strategy, False, f"anchor did not exit; taskkill={detail}"
        confirmed = killed.returncode == 0 and process.poll() is not None
        return strategy, confirmed, f"taskkill_exit={killed.returncode}; {detail}"

    strategy = "start_new_session+SIGKILL_process_group"
    try:
        process_group = os.getpgid(process.pid)
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return strategy, False, "process group disappeared before termination"
    except OSError as error:
        return strategy, False, f"process-group kill failed: {error}"
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        return strategy, False, "process-group anchor did not exit within 15 seconds"
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return strategy, True, "process group absent after SIGKILL"
    except PermissionError:
        return strategy, False, "process group remains but cannot be inspected"
    return strategy, False, "process group still exists after SIGKILL"


def run_case(command: list[str], timeout_seconds: float) -> dict[str, object]:
    spawn_command = command
    popen_options: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        command_shell = os.environ.get("ComSpec", "cmd.exe")
        spawn_command = [
            command_shell,
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    started = time.monotonic()
    process = subprocess.Popen(spawn_command, **popen_options)
    timeout_triggered = False
    termination_attempted = False
    termination_confirmed = False
    kill_strategy = "NOT_APPLICABLE"
    termination_detail = "NOT_APPLICABLE"
    output_streams_closed = False
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds)
        output_streams_closed = True
        exit_status = process.returncode
    except subprocess.TimeoutExpired as error:
        timeout_triggered = True
        termination_attempted = True
        kill_strategy, termination_confirmed, termination_detail = (
            terminate_process_tree(process)
        )
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=15)
            output_streams_closed = True
        except subprocess.TimeoutExpired:
            stdout_bytes = error.stdout
            stderr_bytes = error.stderr
            termination_confirmed = False
            termination_detail += "; output pipes remained open after termination"
        exit_status = 124

    stdout = decode_output(stdout_bytes)
    stderr = decode_output(stderr_bytes)
    late_completion = timeout_triggered and "case_status:" in stdout
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_status": exit_status,
        "timeout_triggered": timeout_triggered,
        "termination_attempted": termination_attempted,
        "termination_confirmed": termination_confirmed,
        "process_tree_kill_strategy": kill_strategy,
        "termination_detail": termination_detail,
        "late_completion_detected": late_completion,
        "output_streams_closed_after_termination": (
            output_streams_closed if timeout_triggered else "NOT_APPLICABLE"
        ),
        "elapsed_orchestrator_seconds": time.monotonic() - started,
    }


def parse_timeout() -> float:
    raw = os.environ.get("SPLITALIGNERR_COLD_START_TIMEOUT_SECONDS", "900")
    try:
        value = float(raw)
    except ValueError as error:
        raise SystemExit(
            "SPLITALIGNERR_COLD_START_TIMEOUT_SECONDS must be positive"
        ) from error
    if value <= 0:
        raise SystemExit(
            "SPLITALIGNERR_COLD_START_TIMEOUT_SECONDS must be positive"
        )
    return value


def last_stage(stdout: str) -> str:
    markers = re.findall(r"^stage_marker: ([A-Z0-9_]+)$", stdout, re.MULTILINE)
    return markers[-1] if markers else "NONE"


def parse_timings(case_id: str, stdout: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"^timing_([a-z0-9_]+)_wall_seconds: ([0-9]+(?:\.[0-9]+)?)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(stdout):
        rows.append(
            {
                "case_id": case_id,
                "timing_name": match.group(1),
                "wall_seconds": match.group(2),
            }
        )
    return rows


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: windows_cold_start_probe.py SOURCE_ROOT OUTPUT_DIR"
        )
    source_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
    output_dir = pathlib.Path(sys.argv[2])
    if output_dir.exists():
        raise SystemExit("refusing to overwrite existing cold-start output")
    output_dir.mkdir(parents=True)

    rscript = shutil.which("Rscript")
    git = shutil.which("git")
    microprobe_raw = os.environ.get("SPLITALIGNERR_COLD_START_MICROPROBE", "")
    microprobe = pathlib.Path(microprobe_raw).resolve()
    if not rscript or not git or not microprobe.is_file():
        raise SystemExit("Rscript, git, and the standalone microprobe are required")

    timeout_seconds = parse_timeout()
    case_script = source_root / ".github/recert/windows_cold_start_case.R"
    source_commit = run_text([git, "-C", str(source_root), "rev-parse", "HEAD"])
    metadata = [
        "probe_id: windows-cold-start-v1",
        f"source_commit: {source_commit}",
        "fresh_process_policy: one new process tree per declared case",
        f"requested_cases: {','.join(ALL_CASES)}",
        f"per_case_timeout_seconds: {timeout_seconds:g}",
        f"runner_os: {os.environ.get('RUNNER_OS', platform.system())}",
        f"runner_arch: {os.environ.get('RUNNER_ARCH', platform.machine())}",
        f"workflow: {os.environ.get('GITHUB_WORKFLOW', 'local')}",
        f"run_id: {os.environ.get('GITHUB_RUN_ID', 'NOT_AVAILABLE')}",
        f"run_attempt: {os.environ.get('GITHUB_RUN_ATTEMPT', 'NOT_AVAILABLE')}",
        f"runner_name: {os.environ.get('RUNNER_NAME', 'NOT_AVAILABLE')}",
        f"os: {platform.platform()}",
        f"R: {run_text([rscript, '--version']).splitlines()[0]}",
        f"microprobe_sha256: {sha256(microprobe)}",
        "root_cause_interpretation: DEFERRED_TO_MAIN_CONSOLE_REVIEW",
        "windows_timeout_strategy: CREATE_NEW_PROCESS_GROUP anchored by cmd.exe "
        "plus taskkill /PID /T /F",
        "unix_local_harness_strategy: start_new_session plus SIGKILL process group",
        f"started_utc: {utc_now()}",
    ]
    write_text(output_dir / "METADATA.txt", "\n".join(metadata) + "\n")

    result_rows: list[dict[str, object]] = []
    timing_rows: list[dict[str, str]] = []
    harness_failure = False
    for case_id in ALL_CASES:
        if case_id in R_CASES:
            command = [rscript, str(case_script), case_id]
        elif case_id == "standalone_numeric_policy":
            command = [str(microprobe), "numeric_policy"]
        else:
            command = [str(microprobe), "regex_construction"]

        execution = run_case(command, timeout_seconds)
        stdout = str(execution["stdout"])
        stderr = str(execution["stderr"])
        exit_status = int(execution["exit_status"])
        timed_out = bool(execution["timeout_triggered"])
        termination_confirmed = bool(execution["termination_confirmed"])
        late_completion = bool(execution["late_completion_detected"])
        if timed_out and (not termination_confirmed or late_completion):
            classification = "HARNESS_FAILURE"
            harness_failure = True
        elif timed_out:
            classification = "TIMEOUT"
        elif exit_status == 0 and "case_status: PASS" in stdout:
            classification = "PASS"
        elif "case_status:" in stdout:
            classification = "REPORTED_FAILURE"
        else:
            classification = "CRASH_OR_NONZERO"

        stdout_file = output_dir / f"{case_id}.stdout.txt"
        stderr_file = output_dir / f"{case_id}.stderr.txt"
        write_text(stdout_file, stdout)
        write_text(stderr_file, stderr)
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
                        execution["output_streams_closed_after_termination"], str
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
        classification: sum(
            row["classification"] == classification for row in result_rows
        )
        for classification in (
            "PASS",
            "TIMEOUT",
            "REPORTED_FAILURE",
            "CRASH_OR_NONZERO",
            "HARNESS_FAILURE",
        )
    }
    summary = [
        "probe_id: windows-cold-start-v1",
        f"scheduled_cases: {len(ALL_CASES)}",
        f"completed_result_rows: {len(result_rows)}",
        f"pass_cases: {counts['PASS']}",
        f"timeout_cases: {counts['TIMEOUT']}",
        f"reported_failure_cases: {counts['REPORTED_FAILURE']}",
        f"crash_or_nonzero_cases: {counts['CRASH_OR_NONZERO']}",
        f"harness_failure_cases: {counts['HARNESS_FAILURE']}",
        "harness_integrity_status: " + ("FAIL" if harness_failure else "PASS"),
        "root_cause_interpretation: DEFERRED_TO_MAIN_CONSOLE_REVIEW",
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
