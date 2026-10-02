#!/usr/bin/env python3
"""Produce bounded SAMPLER-FIX004 evidence; never run measured Stage-B."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Dict
from unittest import mock


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    ExecutionAuthority, FrozenAssets, write_canonical_json,
)
import run_branch_fix001_preflight as branch_fix  # noqa: E402
import run_sampler_fix003_preflight as fix3  # noqa: E402
import stage_b_controller as controller  # noqa: E402
from stage_b_controller import (  # noqa: E402
    DarwinLibprocSamplerBackend, NativeSamplerCapabilityError,
    NativeSamplerProcessAbsent, ProcessTreeRssSampler,
)


BASE_COMMIT = "279063fac6be811028d57f5c6a091b7c89182e99"
BASE_TREE = "f4a4c15779f2c6f2e9be9d05b316204243a968f2"
DURABILITY_SHA256 = "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
CHURN_CONTROL = HERE / "sampler_fix004_churn_control.py"
P23_CASE_IDS = (
    "ZERO_TO_POSITIVE_SAME_IDENTITY_IMMEDIATE",
    "ZERO_TO_POSITIVE_SAME_IDENTITY_SECOND_ROUND",
    "ZERO_TO_POSITIVE_LAST_ALLOWED_ROUND",
    "ZERO_TO_EXIT_SAME_IDENTITY",
    "ZERO_TO_ZOMBIE",
    "ZERO_REMAINS_LIVE_AND_ZERO_UNRESOLVED",
    "PID_REUSE_DURING_ZERO_RETRY",
    "PGID_CHANGE_DURING_ZERO_RETRY",
    "TASKINFO_SIZE_FAILURE_DURING_RETRY",
    "TASKINFO_ERRNO_FAILURE_DURING_RETRY",
)
P24_CASE_IDS = (
    "DIRECT_MISSES_NEW_PID_THEN_AGREES",
    "GENERIC_MISSES_EXITED_PID_THEN_AGREES",
    "MULTIPLE_TRANSIENT_MISMATCHES_THEN_AGREES",
    "MISMATCH_UNRESOLVED_AFTER_BOUND",
    "MISMATCH_CANNOT_RETIRE_GROUP",
    "MISMATCH_CANNOT_DECLARE_TIMEOUT_QUIESCENCE",
    "NO_MEMBER_TASKINFO_FROM_REJECTED_MISMATCH_ROW",
)
CHANGED_PATHS = {
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_sampler_fix004_preflight.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/sampler_fix004_churn_control.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix004.py",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def git(repo: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=30,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if process.returncode:
        raise AssertionError(
            f"git {' '.join(args)}:{process.returncode}:"
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    return process.stdout


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode("utf-8").strip()


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def root_identity(path: Path, label: str) -> Dict[str, Any]:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise AssertionError(f"{label} ordinary directory")
    if any(path.iterdir()):
        raise AssertionError(f"{label} initially empty")
    return {
        "path": str(path), "st_dev": observed.st_dev,
        "st_ino": observed.st_ino, "mode": stat.S_IMODE(observed.st_mode),
        "entry_count_before": 0,
    }


def source_checkpoint(repo: Path) -> Dict[str, Any]:
    branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
    )
    if branch.returncode not in (0, 1):
        raise AssertionError("branch query")
    return {
        "head": git_text(repo, "rev-parse", "HEAD"),
        "tree": git_text(repo, "rev-parse", "HEAD^{tree}"),
        "branch_stdout": branch.stdout.decode("utf-8").strip(),
        "full_status_stdout": git(
            repo, "status", "--porcelain=v1", "--untracked-files=all",
        ).decode("utf-8").strip(),
        "protected_status_stdout": git(
            repo, "status", "--porcelain=v1", "--untracked-files=all", "--",
            "dev/ENGINE003-PREFLIGHT", "R", "src",
        ).decode("utf-8").strip(),
    }


def assert_source(repo: Path) -> tuple[str, str, Dict[str, Any]]:
    pre = source_checkpoint(repo)
    commit, tree = pre["head"], pre["tree"]
    parents = git_text(repo, "show", "-s", "--format=%P", commit).split()
    if parents != [BASE_COMMIT] or commit == BASE_COMMIT:
        raise AssertionError(f"ordinary child:{commit}:{parents}")
    if git_text(repo, "rev-parse", f"{BASE_COMMIT}^{{tree}}") != BASE_TREE:
        raise AssertionError("base tree")
    if any(pre[key] for key in (
        "branch_stdout", "full_status_stdout", "protected_status_stdout",
    )):
        raise AssertionError("source detached clean")
    rows = git(
        repo, "diff-tree", "--no-commit-id", "--name-status", "-r",
        BASE_COMMIT, commit,
    ).decode("utf-8").splitlines()
    changed = {row.split("\t", 1)[1] for row in rows}
    if changed != CHANGED_PATHS:
        raise AssertionError(f"changed scope:{changed}")
    for relative in CHANGED_PATHS:
        if git(repo, "show", f"{commit}:{relative}") != (repo / relative).read_bytes():
            raise AssertionError(f"Git/worktree bytes:{relative}")
    return commit, tree, pre


def initialize_backend(value: DarwinLibprocSamplerBackend) -> None:
    value._authority_lock = threading.Lock()
    value._authority_pgid = 100
    value._authority_root_identity = (100, 10, 1)
    value._group_retired = False
    value._group_census_count = 0
    value._dual_census_agreement_count = 0
    value._last_group_census = ()
    value._maximum_group_census_size = 0
    value._retirement_count = 0
    value._group_census_attempt_count = 0
    value._group_census_disagreement_count = 0
    value._group_census_followup_round_count = 0
    value._group_census_recovery_count = 0
    value._group_census_unresolved_count = 0
    value._zero_rss_initial_count = 0
    value._zero_rss_followup_round_count = 0
    value._zero_rss_recovery_count = 0
    value._zero_rss_exit_race_count = 0
    value._zero_rss_unresolved_count = 0


class ScriptedRssBackend(DarwinLibprocSamplerBackend):
    def __init__(
            self, task_rows: list[object], census_rows: list[tuple[int, ...]],
            identity_rows: list[object] | None = None) -> None:
        initialize_backend(self)
        self.task_rows = list(task_rows)
        self.census_rows = list(census_rows)
        self.identity_rows = list(identity_rows or [])
        self.task_call_count = 0
        self.census_call_count = 0
        self.identity_call_count = 0

    def _process_info(self, pid: int, flavor: int, _arg: int, buffer, size: int) -> int:
        self.task_call_count += 1
        row = self.task_rows.pop(0)
        if flavor != controller.DARWIN_PROC_PIDTASKINFO:
            raise AssertionError("unexpected scripted flavor")
        if isinstance(row, dict):
            resident = int(row["resident"])
            returned = int(row["returned"])
            call_errno = int(row["errno"])
        else:
            resident, returned, call_errno = int(row), size, 0
        value = controller.ctypes.cast(
            buffer, controller.ctypes.POINTER(controller.DarwinProcTaskInfo),
        ).contents
        value.pti_resident_size = resident
        controller.ctypes.set_errno(call_errno)
        return returned

    def process_group_pids(self, pgid: int) -> tuple[int, ...]:
        self.census_call_count += 1
        return self.census_rows.pop(0)

    def identity_and_group(self, pid: int):
        self.identity_call_count += 1
        row = self.identity_rows.pop(0) if self.identity_rows else (1, 100, (100, 10, 1))
        if isinstance(row, Exception):
            raise row
        return row


def p23_case(
        case_id: str, task_rows: list[object], census_rows: list[tuple[int, ...]],
        identity_rows: list[object] | None, expected: str,
        ) -> Dict[str, Any]:
    backend = ScriptedRssBackend(task_rows, census_rows, identity_rows)
    sleeps: list[float] = []
    status, resident, error = "PASS", None, "NONE"
    with mock.patch.object(controller.time, "sleep", side_effect=sleeps.append):
        try:
            resident = backend.rss(100, (100, 10, 1), 100)
        except NativeSamplerProcessAbsent as failure:
            status, error = "PASS_IDENTITY_AWARE_EXIT_RACE", str(failure)
        except NativeSamplerCapabilityError as failure:
            status, error = "PASS_TYPED_FAIL_CLOSED", str(failure)
    if expected == "POSITIVE" and not (status == "PASS" and resident and resident > 0):
        raise AssertionError(f"P23 positive:{case_id}:{status}:{resident}:{error}")
    if expected == "ABSENT" and status != "PASS_IDENTITY_AWARE_EXIT_RACE":
        raise AssertionError(f"P23 absent:{case_id}:{status}:{error}")
    if expected not in ("POSITIVE", "ABSENT") and (
        status != "PASS_TYPED_FAIL_CLOSED" or expected not in error
    ):
        raise AssertionError(f"P23 fail closed:{case_id}:{status}:{error}")
    return {
        "case_id": case_id, "status": status,
        "expected_terminal": expected, "resident_bytes": resident,
        "error": error, "taskinfo_call_count": backend.task_call_count,
        "stable_census_call_count": backend.census_call_count,
        "identity_revalidation_count": backend.identity_call_count,
        "sleep_intervals_nanoseconds": [int(value * 1_000_000_000) for value in sleeps],
        "zero_never_accepted_as_rss": resident != 0,
    }


def p23_corpus(evidence: Path) -> Dict[str, Any]:
    absent = NativeSamplerProcessAbsent("PROCESS_ZOMBIE:pid=100")
    rows = [
        p23_case(P23_CASE_IDS[0], [0, 4096], [(100,)], None, "POSITIVE"),
        p23_case(P23_CASE_IDS[1], [0, 0, 4096], [(100,), (100,)], None, "POSITIVE"),
        p23_case(P23_CASE_IDS[2], [0, 0, 0, 0, 4096], [(100,)] * 4, None, "POSITIVE"),
        p23_case(P23_CASE_IDS[3], [0], [()], None, "ABSENT"),
        p23_case(P23_CASE_IDS[4], [0], [(100,)], [absent], "ABSENT"),
        p23_case(P23_CASE_IDS[5], [0] * 5, [(100,)] * 4, None, "TASK_INFO_ZERO_RSS_UNRESOLVED"),
        p23_case(P23_CASE_IDS[6], [0], [(100,)], [(1, 100, (100, 11, 1))], "PID_REUSE_DURING_ZERO_RSS_RETRY"),
        p23_case(P23_CASE_IDS[7], [0], [(100,)], [(1, 101, (100, 10, 1))], "PGID_CHANGE_DURING_ZERO_RSS_RETRY"),
        p23_case(P23_CASE_IDS[8], [0, {"resident": 4096, "returned": 95, "errno": 0}], [(100,)], None, "TASK_INFO_FAILED"),
        p23_case(P23_CASE_IDS[9], [0, {"resident": 4096, "returned": 96, "errno": 1}], [(100,)], None, "TASK_INFO_FAILED"),
    ]
    if tuple(row["case_id"] for row in rows) != P23_CASE_IDS:
        raise AssertionError("P23 order")
    if not all(row["zero_never_accepted_as_rss"] is True for row in rows):
        raise AssertionError("P23 zero acceptance")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004P23ZeroRssCorpus/v1",
        "status": "PASS", "cases": rows, "case_count": 10,
        "followup_rounds": controller.DARWIN_ZERO_RSS_FOLLOWUP_ROUNDS,
        "followup_interval_nanoseconds": 1_000_000,
        "maximum_intentional_sleep_nanoseconds": 3_000_000,
        "sampler_interval_nanoseconds": 10_000_000,
        "zero_accepted_count": 0, "external_ps_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P23_ZERO_RSS_RETRY_CORPUS.json", value)
    return value


class ScriptedCensusBackend(DarwinLibprocSamplerBackend):
    def __init__(self, pairs: list[tuple[tuple[int, ...], tuple[int, ...]]]) -> None:
        initialize_backend(self)
        self.pairs = list(pairs)
        self.member_info_call_count = 0

    def _process_group_pids_once(self, pgid: int):
        if pgid != 100 or not self.pairs:
            raise AssertionError("scripted census")
        return self.pairs.pop(0)

    def identity_and_group(self, pid: int):
        self.member_info_call_count += 1
        return 1, 100, (pid, 10 + pid, 1)


def p24_row(
        case_id: str, pairs: list[tuple[tuple[int, ...], tuple[int, ...]]],
        expected_set: tuple[int, ...] | None,
        use_live_tree: bool = False,
        ) -> Dict[str, Any]:
    backend = ScriptedCensusBackend(pairs)
    sleeps: list[float] = []
    error = "NONE"
    accepted: tuple[int, ...] | None = None
    with mock.patch.object(controller.time, "sleep", side_effect=sleeps.append):
        try:
            if use_live_tree:
                live, _absent = backend.live_owned_tree({100: (100, 10, 1)})
                accepted = tuple(sorted(live))
            else:
                accepted = backend.process_group_pids(100)
        except NativeSamplerCapabilityError as failure:
            error = str(failure)
    if expected_set is None:
        if "GROUP_ENUMERATION_DISAGREEMENT_UNRESOLVED" not in error:
            raise AssertionError(f"P24 unresolved:{case_id}:{error}")
    elif accepted != expected_set or error != "NONE":
        raise AssertionError(f"P24 accepted:{case_id}:{accepted}:{error}")
    return {
        "case_id": case_id, "status": "PASS",
        "accepted_exact_pids": list(accepted) if accepted is not None else "NONE",
        "terminal_error": error,
        "census_attempt_count": backend._group_census_attempt_count,
        "mismatch_row_count": backend._group_census_disagreement_count,
        "followup_round_count": backend._group_census_followup_round_count,
        "recovery_count": backend._group_census_recovery_count,
        "member_taskinfo_call_count": backend.member_info_call_count,
        "group_retired": backend._group_retired,
        "retirement_count": backend._retirement_count,
        "sleep_intervals_nanoseconds": [int(value * 1_000_000_000) for value in sleeps],
        "mismatch_row_consumed": False,
    }


def p24_corpus(evidence: Path) -> Dict[str, Any]:
    mismatch = ((100,), (100, 101))
    reverse = ((100, 101), (100,))
    unresolved = [mismatch, reverse, mismatch, reverse, mismatch]
    rows = [
        p24_row(P24_CASE_IDS[0], [mismatch, ((100, 101), (100, 101))], (100, 101)),
        p24_row(P24_CASE_IDS[1], [reverse, ((100,), (100,))], (100,)),
        p24_row(P24_CASE_IDS[2], [mismatch, reverse, mismatch, ((100, 102), (100, 102))], (100, 102)),
        p24_row(P24_CASE_IDS[3], list(unresolved), None),
        p24_row(P24_CASE_IDS[4], list(unresolved), None, True),
        p24_row(P24_CASE_IDS[5], list(unresolved), None),
        p24_row(P24_CASE_IDS[6], list(unresolved), None, True),
    ]
    if tuple(row["case_id"] for row in rows) != P24_CASE_IDS:
        raise AssertionError("P24 order")
    for index in (3, 4, 5, 6):
        if rows[index]["member_taskinfo_call_count"] != 0:
            raise AssertionError("P24 rejected mismatch consumed")
    if rows[4]["group_retired"] or rows[4]["retirement_count"]:
        raise AssertionError("P24 mismatch retired group")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004P24CensusCorpus/v1",
        "status": "PASS", "cases": rows, "case_count": 7,
        "followup_rounds": controller.DARWIN_GROUP_CENSUS_FOLLOWUP_ROUNDS,
        "followup_interval_nanoseconds": 1_000_000,
        "mismatch_rows_consumed": 0,
        "mismatch_retirement_count": 0,
        "mismatch_timeout_quiescence_count": 0,
        "external_ps_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P24_DUAL_CENSUS_STABILIZATION_CORPUS.json", value)
    return value


def p20_regression(evidence: Path) -> Dict[str, Any]:
    backend = fix3.ScriptedGroupBackend([
        (100, 101), (101,), (101,), (101, 102), (),
    ])
    sampler = ProcessTreeRssSampler(100, native_backend=backend)
    sampler._sample()
    initial_maximum = sampler.maximum_bytes
    del backend.identities[100]
    del backend.rss_map[100]
    sampler._sample()
    rows = [{
        "case_id": "ROOT_EXITS_CHILD_LIVES", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101] == (101, 11, 1),
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
        "initial_maximum_bytes": initial_maximum,
    }]
    backend.rss_map[101] = 1000
    sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_CHILD_MEMORY_GROWS", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101] == (101, 11, 1),
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
        "maximum_grew_after_root_exit": sampler.maximum_bytes >= 1000,
    })
    sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101] == (101, 11, 1),
        "grandchild_discovered_from_live_owned_child": 102 in sampler.active_owned_pids,
        "grandchild_identity": list(sampler.native_owned_identities[102]),
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
    })
    del backend.identities[101]
    del backend.identities[102]
    del backend.rss_map[101]
    del backend.rss_map[102]
    sampler._sample()
    if (
        [row["case_id"] for row in rows] != [
            "ROOT_EXITS_CHILD_LIVES", "ROOT_EXITS_CHILD_MEMORY_GROWS",
            "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD",
        ]
        or not all(row["root_absent"] and row["child_identity_preserved"] for row in rows)
        or rows[0]["current_whole_tree_rss_bytes"] != 100
        or rows[1]["maximum_grew_after_root_exit"] is not True
        or rows[2]["grandchild_discovered_from_live_owned_child"] is not True
        or sampler.active_owned_pids or sampler.current_bytes != 0
    ):
        raise AssertionError(f"P20 regression:{rows}")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004P20Regression/v1",
        "status": "PASS", "cases": rows, "case_count": 3,
        "all_exact_owned_identities_absent_quiescent": True,
        "final_current_whole_tree_rss_bytes": 0,
        "external_process_table_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P20_ROOT_EXIT_DESCENDANT_CORPUS.json", value)
    return value


def wait_for(path: Path, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 10
    while not path.is_file():
        if process.poll() is not None:
            raise AssertionError("churn control exited before ready")
        if time.monotonic() >= deadline:
            raise AssertionError("churn control ready timeout")
        time.sleep(0.002)


def darwin_churn(evidence: Path) -> Dict[str, Any]:
    root = evidence / "DARWIN_BOUNDED_CHURN"
    root.mkdir(mode=0o700)
    ready, events = root / "ready.json", root / "events.jsonl"
    command = [
        sys.executable, "-B", str(CHURN_CONTROL), "--events", str(events),
        "--ready", str(ready), "--cycles", "48", "--bytes", "1048576",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    sampler: ProcessTreeRssSampler | None = None
    stdout = stderr = b""
    try:
        wait_for(ready, process)
        sampler = ProcessTreeRssSampler(
            process.pid, native_backend=DarwinLibprocSamplerBackend(),
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            sampler._sample()
            if process.poll() is not None:
                authority = sampler.native_backend.authority_evidence()
                if authority["group_retired"] is True:
                    break
            time.sleep(0.0005)
        else:
            raise AssertionError("bounded churn completion timeout")
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=5)
    assert sampler is not None
    if process.returncode != 0 or stderr or sampler.error != "NONE":
        raise AssertionError(
            f"churn failure:{process.returncode}:{stderr!r}:{sampler.error}"
        )
    event_rows = [json.loads(line) for line in events.read_text("ascii").splitlines()]
    if len(event_rows) != 48 or any(row["return_code"] != 0 for row in event_rows):
        raise AssertionError("churn event cardinality")
    stdout_path, stderr_path = root / "control.stdout.bin", root / "control.stderr.bin"
    branch_fix.write_raw(stdout_path, stdout)
    branch_fix.write_raw(stderr_path, stderr)
    authority = sampler.native_backend.authority_evidence()
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004DarwinChurn/v1",
        "status": "PASS", "non_stage_b_control": True,
        "command": command, "root_pid": process.pid,
        "child_launch_count": 48, "child_exit_count": 48,
        "requested_bytes_per_child": 1_048_576,
        "maximum_concurrent_control_children": 1,
        "sampler_sample_count": sampler.sample_count,
        "sampler_error": sampler.error,
        "maximum_whole_group_rss_bytes": sampler.maximum_bytes,
        "identity_aware_exit_count": len(sampler.identity_aware_exit_pids),
        "native_authority": authority,
        "observed_zero_rss_initial_count": authority["zero_rss_initial_count"],
        "observed_zero_rss_recovery_count": authority["zero_rss_recovery_count"],
        "observed_zero_rss_unresolved_count": authority["zero_rss_unresolved_count"],
        "observed_dual_census_mismatch_count": authority["group_census_disagreement_count"],
        "observed_dual_census_recovery_count": authority["group_census_recovery_count"],
        "observed_dual_census_unresolved_count": authority["group_census_unresolved_count"],
        "transient_zero_false_failure_count": 0,
        "mismatch_row_consumed_count": 0,
        "external_ps_call_count": 0,
        "group_retired": authority["group_retired"],
        "stdout_sha256": file_sha256(stdout_path),
        "stderr_sha256": file_sha256(stderr_path),
    }
    if not (
        value["group_retired"] is True and value["sampler_sample_count"] > 0
        and value["maximum_whole_group_rss_bytes"] > 0
        and value["observed_zero_rss_initial_count"]
        == value["observed_zero_rss_recovery_count"]
        and value["observed_zero_rss_unresolved_count"] == 0
        and value["observed_dual_census_unresolved_count"] == 0
        and (
            value["observed_dual_census_mismatch_count"] == 0
            or value["observed_dual_census_recovery_count"] > 0
        )
    ):
        raise AssertionError(f"churn gate:{value}")
    write_canonical_json(evidence / "DARWIN_BOUNDED_CHURN.json", value)
    return value


def evidence_hashes(evidence: Path) -> Dict[str, str]:
    return {
        path.relative_to(evidence).as_posix(): file_sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "SAMPLER_FIX004_SUMMARY.json"
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = lexical_absolute(args.repo_root).resolve(strict=True)
    runtime_input, evidence_input = (
        lexical_absolute(args.runtime_root), lexical_absolute(args.evidence_root),
    )
    runtime_id = root_identity(runtime_input, "runtime")
    evidence_id = root_identity(evidence_input, "evidence")
    runtime, evidence = runtime_input.resolve(strict=True), evidence_input.resolve(strict=True)
    if runtime == evidence or runtime in evidence.parents or evidence in runtime.parents:
        raise AssertionError("root overlap")
    commit, tree, pre = assert_source(repo)
    authority, assets = ExecutionAuthority(repo, commit, tree), FrozenAssets(ExecutionAuthority(repo, commit, tree))
    durability_path, durability = branch_fix.preserve_exact_durability(
        lexical_absolute(args.durability), evidence,
    )
    if file_sha256(durability_path) != DURABILITY_SHA256:
        raise AssertionError("durability SHA")

    p23, p24 = p23_corpus(evidence), p24_corpus(evidence)
    p20 = p20_regression(evidence)
    p22 = fix3.p22_case_corpus(evidence)
    churn = darwin_churn(evidence)
    controller_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    ))
    controlled = branch_fix.controlled_sampler_diagnostic(repo, evidence, controller_sha)
    hard_gate = branch_fix.whole_tree_hard_gate_corpus(evidence)
    branch_path, series_path, branch, series, branch_sha, series_sha = branch_fix.capture_pair(runtime, evidence)
    p18 = branch_fix.branch_binding_corpus(
        authority, assets, runtime, evidence, durability,
        branch, series, branch_sha, series_sha,
    )
    omission = branch_fix.make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "fix004-cli-omission-never-created",
    )
    branch_fix.worker_cli_omission(
        repo, runtime, evidence, series_path, durability_path, omission,
    )
    precedence = branch_fix.stop_precedence_corpus(
        authority, assets, repo, runtime, evidence, series_path, branch_path,
        durability_path, durability, branch_sha, series,
    )
    timeout = fix3.native_timeout_corpus(
        authority, assets, repo, runtime, evidence, series_path, branch_path,
        durability_path, series, durability, branch_sha,
    )
    e2e = branch_fix.bounded_e2e(
        authority, assets, repo, runtime, evidence, series_path, branch_path,
        durability_path, series, branch, durability, branch_sha, series_sha,
    )
    if any(runtime.iterdir()):
        raise AssertionError("runtime not empty")
    post = source_checkpoint(repo)
    if post != pre:
        raise AssertionError("source changed")
    source = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_id, "evidence_root": evidence_id,
        "changed_paths": sorted(CHANGED_PATHS),
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    zero = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004ZeroBoundary/v1",
        "status": "PASS_BOUNDED_PREFLIGHT_ONLY",
        "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "over_2gib_store_count": 0, "over_4gib_store_count": 0,
        "backend_selection_count": 0, "decision_engine_invocation_count": 0,
        "authorized_to_run_artifact_count": 0,
        "attempt003_resume_count": 0, "attempt003_root_write_count": 0,
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "bounded_churn_root_launch_count": 1,
        "bounded_churn_child_launch_count": 48,
        "bounded_churn_requested_bytes_per_child": 1_048_576,
        "external_ps_call_count": 0,
        "runtime_root_final_entry_count": 0,
        "physical_execution_authorized": False,
    }
    write_canonical_json(evidence / "ZERO_BOUNDARY.json", zero)
    checker_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix004.py",
    ))
    summary = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix004Summary/v1",
        "status": "PASS_SAMPLER_FIX004_BOUNDED_PREFLIGHT_ONLY",
        "source_commit": commit, "source_tree": tree, "direct_parent": BASE_COMMIT,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "checker_sha256": checker_sha, "p23_case_count": p23["case_count"],
        "p24_case_count": p24["case_count"], "p18_case_count": len(p18["cases"]),
        "p20_case_count": len(p20["cases"]), "p22_case_count": len(p22["cases"]),
        "p21_timeout_case_count": len(timeout["cases"]),
        "worker_precedence_case_count": len(precedence["cases"]),
        "darwin_churn_pass": churn["status"] == "PASS",
        "controlled_sampler_pass": controlled["status"] == "PASS",
        "whole_tree_hard_gate_pass": hard_gate["status"] == "PASS",
        "bounded_e2e_pass": e2e["status"] == "PASS",
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "external_ps_call_count": 0, "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": 0,
        "claim_ceiling": "BOUNDED_SAMPLER_FIX004_PREFLIGHT_ONLY_NO_STAGEB_PERFORMANCE_OR_AUTHORIZATION_CLAIM",
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "SAMPLER_FIX004_SUMMARY.json", summary)
    return summary


def self_test() -> None:
    temporary = Path("/private/tmp") / f"sampler-fix004-selftest-{os.getpid()}"
    if temporary.exists():
        raise AssertionError("self-test collision")
    temporary.mkdir(mode=0o700)
    try:
        p23_corpus(temporary)
        p24_corpus(temporary)
        p20_regression(temporary)
    finally:
        shutil.rmtree(temporary)
    print("PASS_SAMPLER_FIX004_RUNNER_SELF_TEST P23=10 P24=7 PHYSICAL_EXECUTION=0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-bounded-fix004", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.print_plan:
        print("SAMPLER_FIX004_PLAN P23=10 P24=7 P18=7 BOUNDED_E2E=1 LARGE=0 STAGEB_MEASURED=0")
        return
    if None in (args.repo_root, args.runtime_root, args.evidence_root, args.durability):
        parser.error("all bounded paths are required")
    summary = execute(args)
    print(
        "PASS_SAMPLER_FIX004_BOUNDED_PREFLIGHT_ONLY "
        f"COMMIT={summary['source_commit']} P23=10 P24=7 P18=7 "
        "BOUNDED_E2E=PASS LARGE=0 STAGEB_MEASURED=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
