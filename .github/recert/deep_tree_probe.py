#!/usr/bin/env python3
"""Run deterministic comb-tree cases in isolated R subprocesses."""

from __future__ import annotations

import csv
import datetime as dt
import os
import pathlib
import platform
import re
import signal
import shutil
import subprocess
import sys
import time


DEFAULT_SIZES = "50,200,302,500,750,1000,1500,2000,3000,5000"
OPERATIONS = ("validate_species_tree", "align_branches")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def run_text(command: list[str]) -> str:
    result = subprocess.run(
        command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    return stdout if stdout else stderr


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
    return " | ".join(value.replace("\r\n", "\n").replace("\r", "\n").splitlines())


def terminate_process_tree(
    process: subprocess.Popen[bytes],
) -> tuple[str, bool, str]:
    """Kill the complete per-case process tree and confirm the anchor exited."""
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
            return strategy, False, f"anchor process did not exit; taskkill={detail}"
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


def run_case(
    command: list[str], timeout_seconds: float
) -> dict[str, object]:
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


def cpu_model() -> str:
    system = platform.system()
    if system == "Darwin":
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            value = result.stdout.decode("utf-8", errors="replace").strip()
            return value or "UNKNOWN"
        return "UNAVAILABLE"
    if system == "Linux" and pathlib.Path("/proc/cpuinfo").is_file():
        for line in pathlib.Path("/proc/cpuinfo").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or "UNKNOWN"


def parse_sizes() -> list[int]:
    text = os.environ.get("SPLITALIGNERR_DEEP_TREE_SIZES", DEFAULT_SIZES)
    try:
        sizes = [int(item) for item in text.split(",")]
    except ValueError as error:
        raise SystemExit(
            "SPLITALIGNERR_DEEP_TREE_SIZES must be increasing integers >= 2"
        ) from error
    if not sizes or any(size < 2 for size in sizes) or sizes != sorted(sizes):
        raise SystemExit(
            "SPLITALIGNERR_DEEP_TREE_SIZES must be increasing integers >= 2"
        )
    return sizes


def parse_timeout() -> float:
    text = os.environ.get("SPLITALIGNERR_DEEP_TREE_TIMEOUT_SECONDS", "60")
    try:
        timeout = float(text)
    except ValueError as error:
        raise SystemExit(
            "SPLITALIGNERR_DEEP_TREE_TIMEOUT_SECONDS must be positive"
        ) from error
    if timeout <= 0:
        raise SystemExit(
            "SPLITALIGNERR_DEEP_TREE_TIMEOUT_SECONDS must be positive"
        )
    return timeout


def parse_operations() -> tuple[str, ...]:
    text = os.environ.get(
        "SPLITALIGNERR_DEEP_TREE_OPERATIONS", ",".join(OPERATIONS)
    )
    operations = tuple(item.strip() for item in text.split(",") if item.strip())
    if (
        not operations
        or len(set(operations)) != len(operations)
        or any(operation not in OPERATIONS for operation in operations)
    ):
        raise SystemExit(
            "SPLITALIGNERR_DEEP_TREE_OPERATIONS must be a unique subset of "
            + ",".join(OPERATIONS)
        )
    return operations


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: deep_tree_probe.py SOURCE_ROOT OUTPUT_DIR")

    source_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
    output_dir = pathlib.Path(sys.argv[2])
    if output_dir.exists():
        raise SystemExit("refusing to overwrite existing deep-tree output directory")
    output_dir.mkdir(parents=True)

    rscript = shutil.which("Rscript")
    r_command = shutil.which("R")
    git = shutil.which("git")
    if not rscript or not r_command or not git:
        raise SystemExit("R, Rscript, and git are required")

    case_script = source_root / ".github" / "recert" / "deep_tree_case.R"
    sizes = parse_sizes()
    timeout_seconds = parse_timeout()
    operations = parse_operations()
    source_commit = run_text([git, "-C", str(source_root), "rev-parse", "HEAD"])
    compiler = run_text([r_command, "CMD", "config", "CXX17"])
    r_version = run_text([r_command, "--version"]).splitlines()[0]
    r_platform = run_text(
        [rscript, "-e", 'cat(R.version$platform, "\\n", sep = "")']
    )

    metadata = [
        "probe_id: recursive-depth-comb-v1",
        f"source_commit: {source_commit}",
        "generator: deterministic_left_comb_v1",
        "generator_definition: start=(t000001:1,t000002:1):1; "
        "append=(previous,tNNNNNN:1):1; terminate=;",
        "probe_sequence: ascending taxa; requested operations in declared order "
        "at each size; stop after first non-PASS case",
        f"requested_operations: {','.join(operations)}",
        f"requested_sizes: {','.join(str(size) for size in sizes)}",
        f"per_case_timeout_seconds: {timeout_seconds:g}",
        f"runner_os: {os.environ.get('RUNNER_OS', platform.system())}",
        f"runner_arch: {os.environ.get('RUNNER_ARCH', platform.machine())}",
        f"hardware_logical_cores: {os.cpu_count() or 'UNKNOWN'}",
        f"cpu_model: {cpu_model()}",
        f"os: {platform.platform()}",
        f"R: {r_version}",
        f"R_platform: {r_platform}",
        f"compiler: {compiler}",
        f"orchestrator: Python {platform.python_version()} subprocess.Popen",
        "unix_timeout_strategy: start_new_session plus SIGKILL process group",
        "windows_timeout_strategy: CREATE_NEW_PROCESS_GROUP anchored by cmd.exe "
        "plus taskkill /PID /T /F",
        f"started_utc: {utc_now()}",
    ]
    write_text(output_dir / "METADATA.txt", "\n".join(metadata) + "\n")

    rows: list[dict[str, object]] = []
    direct_nonzero_failure = False
    unexpected_graceful_failure_observed = False
    timeout_boundary_observed = False
    timeout_termination_failure_observed = False
    late_completion_observed = False
    stopped_after_first_nonpass = False

    for taxa in sizes:
        for operation in operations:
            label = f"{operation}_taxa_{taxa:06d}"
            command = [rscript, str(case_script), operation, str(taxa)]
            execution = run_case(command, timeout_seconds)
            stdout = str(execution["stdout"])
            stderr = str(execution["stderr"])
            exit_status = int(execution["exit_status"])
            timed_out = bool(execution["timeout_triggered"])
            termination_confirmed = bool(execution["termination_confirmed"])
            late_completion = bool(execution["late_completion_detected"])

            stdout_file = output_dir / f"{label}.stdout.txt"
            stderr_file = output_dir / f"{label}.stderr.txt"
            write_text(stdout_file, stdout)
            write_text(stderr_file, stderr)

            graceful = "case_status: GRACEFUL_FAILURE" in stdout
            passed = exit_status == 0 and "case_status: PASS" in stdout
            if timed_out and (not termination_confirmed or late_completion):
                classification = "HARNESS_FAILURE"
            elif timed_out:
                classification = "TIMEOUT"
            elif passed:
                classification = "PASS"
            elif graceful:
                classification = "GRACEFUL_FAILURE"
            else:
                classification = "CRASH_OR_NONZERO"

            expected_depth_guard = (
                classification == "GRACEFUL_FAILURE"
                and "safe recursion depth" in stdout
            )
            unexpected_graceful = (
                classification == "GRACEFUL_FAILURE" and not expected_depth_guard
            )
            direct_nonzero_failure |= classification == "CRASH_OR_NONZERO"
            unexpected_graceful_failure_observed |= unexpected_graceful
            timeout_boundary_observed |= classification == "TIMEOUT"
            timeout_termination_failure_observed |= (
                timed_out and not termination_confirmed
            )
            late_completion_observed |= late_completion
            byte_match = re.search(r"newick_bytes: ([0-9]+)", stdout)
            rows.append(
                {
                    "operation": operation,
                    "taxa": taxa,
                    "depth": taxa - 1,
                    "newick_bytes": byte_match.group(1) if byte_match else "",
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
                    "late_completion_detected": str(late_completion).upper(),
                    "output_streams_closed_after_termination": execution[
                        "output_streams_closed_after_termination"
                    ] if isinstance(
                        execution["output_streams_closed_after_termination"], str
                    ) else str(
                        execution["output_streams_closed_after_termination"]
                    ).upper(),
                    "termination_detail": execution["termination_detail"],
                    "elapsed_orchestrator_seconds": (
                        f"{float(execution['elapsed_orchestrator_seconds']):.6f}"
                    ),
                    "stdout_file": stdout_file.name,
                    "stderr_file": stderr_file.name,
                }
            )
            if classification != "PASS":
                stopped_after_first_nonpass = True
                break
        if stopped_after_first_nonpass:
            break

    fieldnames = [
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
    with (output_dir / "RESULTS.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    summary: list[str] = []
    for operation in operations:
        selected = [row for row in rows if row["operation"] == operation]
        passed_rows = [row for row in selected if row["classification"] == "PASS"]
        graceful_rows = [
            row for row in selected if row["classification"] == "GRACEFUL_FAILURE"
        ]
        crash_timeout_rows = [
            row
            for row in selected
            if row["classification"] in (
                "CRASH_OR_NONZERO", "TIMEOUT", "HARNESS_FAILURE"
            )
        ]
        summary.extend(
            [
                f"operation: {operation}",
                "maximum_passing_taxa: "
                + (str(max(row["taxa"] for row in passed_rows)) if passed_rows else "NONE"),
                "first_graceful_failure_taxa: "
                + (str(graceful_rows[0]["taxa"]) if graceful_rows else "NONE"),
                "first_crash_or_timeout_taxa: "
                + (str(crash_timeout_rows[0]["taxa"]) if crash_timeout_rows else "NONE"),
                "first_crash_or_timeout_class: "
                + (
                    str(crash_timeout_rows[0]["classification"])
                    if crash_timeout_rows
                    else "NONE"
                ),
            ]
        )

    failed = (
        direct_nonzero_failure
        or unexpected_graceful_failure_observed
        or timeout_termination_failure_observed
        or late_completion_observed
    )
    summary.extend(
        [
            "direct_crash_or_unclassified_nonzero_observed: "
            + str(direct_nonzero_failure).upper(),
            "timeout_boundary_observed: "
            + str(timeout_boundary_observed).upper(),
            "timeout_process_tree_termination_all_confirmed: "
            + str(not timeout_termination_failure_observed).upper(),
            "late_completion_observed: "
            + str(late_completion_observed).upper(),
            "unexpected_graceful_failure_observed: "
            + str(unexpected_graceful_failure_observed).upper(),
            "stopped_after_first_nonpass: "
            + str(stopped_after_first_nonpass).upper(),
            "overall_probe_status: " + ("FAIL" if failed else "PASS"),
            f"finished_utc: {utc_now()}",
        ]
    )
    write_text(output_dir / "SUMMARY.txt", "\n".join(summary) + "\n")
    if failed:
        print("deep_tree_probe: FAIL", file=sys.stderr)
        return 1
    print("deep_tree_probe: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
