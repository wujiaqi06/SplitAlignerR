#!/usr/bin/env python3
"""Produce bounded SAMPLER-FIX003 evidence; never run measured Stage-B."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Mapping
from unittest import mock


sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    strict_json_load,
    write_canonical_json,
)
import run_branch_fix001_preflight as branch_fix  # noqa: E402
import stage_b_controller as controller  # noqa: E402
from stage_b_controller import (  # noqa: E402
    DarwinLibprocSamplerBackend,
    NativeSamplerCapabilityError,
    NativeSamplerProcessAbsent,
    ProcessTreeRssSampler,
    launch_request,
)


BASE_COMMIT = "94804e31c50f67edd5a16b01da485c8a0d638cac"
BASE_TREE = "ca437c799b4e5e79f70b1b5124a370cab3f18e34"
PGRP_DIAG_ZIP_SHA256 = (
    "1fbcc9d078e708326e171db3b7c022770610cf9a32c029ca9ae623c2ae293ed5"
)
EXPECTED_DURABILITY_SHA256 = (
    "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
)
TIMEOUT_CONTROL = HERE / "sampler_fix003_timeout_control.py"
P22_CASE_IDS = (
    "ROOT_SAMPLED_ONLY",
    "ROOT_EXITS_UNSEEN_CHILD_LIVES",
    "ROOT_EXITS_UNSEEN_CHILD_MEMORY_GROWS",
    "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
    "ROOT_EXITS_KNOWN_CHILD_LIVES",
    "ROOT_EXITS_KNOWN_CHILD_MEMORY_GROWS",
    "GROUP_EVENTUALLY_EMPTY",
    "NONEMPTY_AFTER_GROUP_RETIRED",
)
TIMEOUT_CASE_IDS = (
    "ROOT_ONLY_COOPERATIVE_EXIT",
    "ROOT_AND_CHILD_COOPERATIVE_EXIT",
    "ROOT_EXITS_UNSEEN_CHILD_IGNORES",
    "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
    "ROOT_AND_DESCENDANTS_REQUIRE_FORCE",
    "PID_REUSE_OR_AMBIGUITY",
    "NATIVE_GROUP_ENUMERATION_FAILURE",
    "NATIVE_IDENTITY_FAILURE",
)
CHANGED_PATHS = {
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_sampler_fix003_preflight.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/sampler_fix003_timeout_control.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix003.py",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def git(repo: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=30, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
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


def require_empty_root(path: Path, label: str) -> Dict[str, Any]:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise AssertionError(f"{label} must be ordinary directory")
    if any(path.iterdir()):
        raise AssertionError(f"{label} must start empty")
    return {
        "path": str(path), "st_dev": observed.st_dev,
        "st_ino": observed.st_ino, "mode": stat.S_IMODE(observed.st_mode),
        "entry_count_before": 0,
    }


def source_checkpoint(repo: Path) -> Dict[str, Any]:
    branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=30,
    )
    if branch.returncode not in (0, 1):
        raise AssertionError("source branch query")
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
    commit = pre["head"]
    tree = pre["tree"]
    parents = git_text(repo, "show", "-s", "--format=%P", commit).split()
    if parents != [BASE_COMMIT] or commit == BASE_COMMIT:
        raise AssertionError(f"ordinary child:{commit}:{parents}")
    if git_text(repo, "rev-parse", f"{BASE_COMMIT}^{{tree}}") != BASE_TREE:
        raise AssertionError("base tree mismatch")
    if any(pre[field] for field in (
        "branch_stdout", "full_status_stdout", "protected_status_stdout",
    )):
        raise AssertionError("source must be detached and clean")
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
    if Path(__file__).read_bytes() != git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/"
        "run_sampler_fix003_preflight.py",
    ):
        raise AssertionError("executed runner not child Git object")
    return commit, tree, pre


class ScriptedGroupBackend(DarwinLibprocSamplerBackend):
    """In-process bounded V2 authority model; no process is launched."""

    def __init__(self, census: list[tuple[int, ...]]) -> None:
        self._authority_lock = threading.Lock()
        self._authority_pgid = None
        self._authority_root_identity = None
        self._group_retired = False
        self._group_census_count = 0
        self._dual_census_agreement_count = 0
        self._last_group_census = ()
        self._maximum_group_census_size = 0
        self._retirement_count = 0
        self.census = list(census)
        self.census_index = 0
        self.identities: Dict[int, tuple[int, int, tuple[int, int, int]]] = {
            100: (1, 100, (100, 10, 1)),
            101: (1, 100, (101, 11, 1)),
            102: (101, 100, (102, 12, 1)),
        }
        self.rss_map = {100: 10, 101: 100, 102: 500}

    def process_group_pids(self, pgid: int) -> tuple[int, ...]:
        if pgid != 100:
            raise NativeSamplerCapabilityError("SCRIPTED_PGID_MISMATCH")
        index = min(self.census_index, len(self.census) - 1)
        self.census_index += 1
        value = tuple(sorted(set(self.census[index])))
        if any(pid <= 0 for pid in value):
            raise NativeSamplerCapabilityError("SCRIPTED_NONPOSITIVE_PID")
        self._group_census_count += 1
        self._dual_census_agreement_count += 1
        self._last_group_census = value
        self._maximum_group_census_size = max(
            self._maximum_group_census_size, len(value),
        )
        return value

    def identity_and_group(
            self, pid: int,
            ) -> tuple[int, int, tuple[int, int, int]]:
        try:
            return self.identities[pid]
        except KeyError as error:
            raise NativeSamplerProcessAbsent(f"SCRIPTED_ABSENT:{pid}") from error

    def identity(self, pid: int) -> tuple[int, tuple[int, int, int]]:
        ppid, _pgid, identity = self.identity_and_group(pid)
        return ppid, identity

    def rss(self, pid: int) -> int:
        try:
            return self.rss_map[pid]
        except KeyError as error:
            raise NativeSamplerProcessAbsent(
                f"SCRIPTED_RSS_ABSENT:{pid}"
            ) from error


def p22_case_corpus(evidence: Path) -> Dict[str, Any]:
    rows = []

    root_only = ScriptedGroupBackend([(100,)])
    root_sampler = ProcessTreeRssSampler(100, native_backend=root_only)
    root_sampler._sample()
    rows.append({
        "case_id": "ROOT_SAMPLED_ONLY", "status": "PASS",
        "previous_owned_pids": [],
        "current_owned_pids": sorted(root_sampler.active_owned_pids),
        "root_rss_bytes": root_sampler.current_root_bytes,
        "whole_tree_rss_bytes": root_sampler.current_bytes,
    })

    unseen = ScriptedGroupBackend([(100,), (101,), (101,), (101, 102)])
    unseen_sampler = ProcessTreeRssSampler(100, native_backend=unseen)
    unseen_sampler._sample()
    before_unseen = sorted(unseen_sampler.owned_pids)
    unseen.identities.pop(100)
    unseen.rss_map.pop(100)
    unseen_sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_UNSEEN_CHILD_LIVES", "status": "PASS",
        "previous_owned_pids": before_unseen,
        "root_absent": 100 in unseen_sampler.identity_aware_exit_pids,
        "child_discovered_solely_by_group_census": 101 not in before_unseen,
        "child_exact_identity": list(unseen_sampler.native_owned_identities[101]),
        "child_rss_included": unseen_sampler.current_bytes == 100,
        "maximum_whole_tree_rss_bytes": unseen_sampler.maximum_bytes,
    })
    unseen.rss_map[101] = 1000
    prior_maximum = unseen_sampler.maximum_bytes
    unseen_sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_UNSEEN_CHILD_MEMORY_GROWS", "status": "PASS",
        "root_absent": 100 in unseen_sampler.identity_aware_exit_pids,
        "child_rss_bytes": 1000,
        "previous_maximum_bytes": prior_maximum,
        "maximum_whole_tree_rss_bytes": unseen_sampler.maximum_bytes,
        "maximum_updated": unseen_sampler.maximum_bytes == 1000,
    })
    before_grandchild = sorted(unseen_sampler.owned_pids)
    unseen_sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
        "status": "PASS", "root_absent": True,
        "previous_owned_pids": before_grandchild,
        "grandchild_discovered_solely_by_group_census": (
            102 not in before_grandchild and 102 in unseen_sampler.active_owned_pids
        ),
        "grandchild_exact_identity": list(
            unseen_sampler.native_owned_identities[102]
        ),
        "grandchild_rss_included": unseen_sampler.current_bytes == 1500,
    })

    known = ScriptedGroupBackend([
        (100, 101), (101,), (101,),
    ])
    known_sampler = ProcessTreeRssSampler(100, native_backend=known)
    known_sampler._sample()
    known_before = sorted(known_sampler.owned_pids)
    known.identities.pop(100)
    known.rss_map.pop(100)
    known_sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_KNOWN_CHILD_LIVES", "status": "PASS",
        "previous_owned_pids": known_before,
        "root_absent": 100 in known_sampler.identity_aware_exit_pids,
        "known_child_preserved": 101 in known_sampler.active_owned_pids,
        "whole_tree_rss_bytes": known_sampler.current_bytes,
    })
    known.rss_map[101] = 1200
    known_prior_maximum = known_sampler.maximum_bytes
    known_sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_KNOWN_CHILD_MEMORY_GROWS", "status": "PASS",
        "root_absent": True, "child_rss_bytes": 1200,
        "previous_maximum_bytes": known_prior_maximum,
        "maximum_whole_tree_rss_bytes": known_sampler.maximum_bytes,
        "maximum_updated": known_sampler.maximum_bytes == 1200,
    })

    retire = ScriptedGroupBackend([(100,), (), (101,)])
    retire_sampler = ProcessTreeRssSampler(100, native_backend=retire)
    retire_sampler._sample()
    retire.identities.pop(100)
    retire.rss_map.pop(100)
    retire_sampler._sample()
    rows.append({
        "case_id": "GROUP_EVENTUALLY_EMPTY", "status": "PASS",
        "group_retired": retire._group_retired,
        "retirement_count": retire._retirement_count,
        "current_owned_pids": sorted(retire_sampler.active_owned_pids),
        "current_whole_tree_rss_bytes": retire_sampler.current_bytes,
    })
    try:
        retire_sampler._sample()
    except NativeSamplerCapabilityError as error:
        reuse_error = str(error)
    else:
        raise AssertionError("retired group was reacquired")
    rows.append({
        "case_id": "NONEMPTY_AFTER_GROUP_RETIRED", "status": "PASS",
        "group_retired": retire._group_retired,
        "observed_typed_error": reuse_error,
        "fail_closed": reuse_error.startswith("PGID_REUSE_OR_AMBIGUITY:"),
    })

    if tuple(row["case_id"] for row in rows) != P22_CASE_IDS:
        raise AssertionError("P22 case order")
    if not all(row["status"] == "PASS" for row in rows):
        raise AssertionError("P22 case status")
    for index in (1, 2, 3, 4, 5):
        if rows[index].get("root_absent") is not True:
            raise AssertionError(f"P22 root absence:{rows[index]}")
    if rows[1]["child_discovered_solely_by_group_census"] is not True:
        raise AssertionError("unseen child not recovered")
    if rows[3]["grandchild_discovered_solely_by_group_census"] is not True:
        raise AssertionError("unseen grandchild not recovered")
    if rows[6]["group_retired"] is not True or rows[7]["fail_closed"] is not True:
        raise AssertionError("group retirement contract")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003P22Corpus/v1",
        "status": "PASS", "cases": rows, "case_count": len(rows),
        "completeness_authority": controller.DARWIN_SAMPLER_MECHANISM_ID,
        "dual_native_census_required": True,
        "external_process_table_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P22_PROCESS_GROUP_CORPUS.json", value)
    return value


class ArmedNativeBackend(DarwinLibprocSamplerBackend):
    def __init__(self) -> None:
        super().__init__()
        self.failure = "NONE"

    def process_group_pids(self, pgid: int) -> tuple[int, ...]:
        if self.failure == "ENUMERATION":
            raise NativeSamplerCapabilityError(
                "INJECTED_NATIVE_GROUP_ENUMERATION_FAILURE"
            )
        return super().process_group_pids(pgid)

    def identity_and_group(
            self, pid: int,
            ) -> tuple[int, int, tuple[int, int, int]]:
        if self.failure == "IDENTITY":
            raise NativeSamplerCapabilityError(
                "INJECTED_NATIVE_IDENTITY_FAILURE"
            )
        return super().identity_and_group(pid)

    def arm_retired_group_ambiguity(self) -> None:
        with self._authority_lock:
            self._group_retired = True
            self._retirement_count = 1


def wait_for_ready(path: Path, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 10
    while not path.is_file():
        if process.poll() is not None:
            raise AssertionError("timeout control exited before ready")
        if time.monotonic() >= deadline:
            raise AssertionError("timeout control readiness timeout")
        time.sleep(0.01)


def timeout_case(
        case_id: str, authority: ExecutionAuthority, assets: FrozenAssets,
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        series: Mapping[str, Any], durability: Mapping[str, Any],
        branch_sha: str) -> Dict[str, Any]:
    root = evidence / "P22_NATIVE_TIMEOUT_CORPUS" / case_id
    root.mkdir(parents=True, exist_ok=False)
    request = branch_fix.make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, f"fix003-timeout-{case_id.lower()}",
    )
    output = root / "worker.result.json"
    partial = output.with_suffix(".partial.json")
    pids = root / "pids.json"
    ready = root / "ready.json"
    control_case = (
        case_id if case_id in TIMEOUT_CASE_IDS[:5]
        else "ROOT_AND_DESCENDANTS_REQUIRE_FORCE"
    )
    command = [
        sys.executable, "-B", str(TIMEOUT_CONTROL),
        "--case-id", control_case, "--partial", str(partial),
        "--pid-evidence", str(pids), "--ready", str(ready),
    ]
    backend = ArmedNativeBackend()
    grace_calls = []

    def bounded_waiter(process: subprocess.Popen, seconds: int) -> bool:
        grace_calls.append(seconds)
        wait_for_ready(ready, process)
        if case_id == "PID_REUSE_OR_AMBIGUITY":
            backend.arm_retired_group_ambiguity()
        elif case_id == "NATIVE_GROUP_ENUMERATION_FAILURE":
            backend.failure = "ENUMERATION"
        elif case_id == "NATIVE_IDENTITY_FAILURE":
            backend.failure = "IDENTITY"
        try:
            process.wait(timeout=0.6)
            return True
        except subprocess.TimeoutExpired:
            return False

    def forbidden_external_table(*_args, **_kwargs):
        raise AssertionError("Darwin timeout attempted external process table")

    expected_stop = (
        "SB_STOP_TIMEOUT_TERMINATION"
        if case_id in TIMEOUT_CASE_IDS[-3:] else "SB_STOP_TIMEOUT"
    )
    try:
        with mock.patch.object(
            controller, "_process_state_table", forbidden_external_table,
        ):
            launch_request(
                repo, runtime, series_path, durability_path, request,
                root / "worker.request.json", output,
                root / "controller.log.txt", branch_path,
                bounded_waiter, command, 0.50,
                sampler_backend_factory=lambda: backend,
            )
    except StopSignal as error:
        observed_stop = error.stop_id
        observed_detail = error.detail
    else:
        raise AssertionError(f"timeout case returned:{case_id}")
    if observed_stop != expected_stop:
        raise AssertionError(
            f"timeout stop:{case_id}:{observed_stop}!={expected_stop}"
        )
    if grace_calls != [controller.TIMEOUT_COOPERATIVE_GRACE_SECONDS]:
        raise AssertionError(f"timeout grace:{case_id}:{grace_calls}")
    stop = strict_json_load(output)
    termination = stop["termination"]
    pid_value = strict_json_load(pids)
    negative = case_id in TIMEOUT_CASE_IDS[-3:]
    if negative:
        if (
            termination.get("status") != "SB_STOP_TIMEOUT_TERMINATION"
            or termination.get("whole_process_tree_quiescent") is not False
            or termination.get("native_survivor_state")
            != "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE"
        ):
            raise AssertionError(f"timeout negative preservation:{case_id}")
    else:
        expected_force = case_id in TIMEOUT_CASE_IDS[2:5]
        if (
            termination["force_terminate_process_tree_executed"]
            is not expected_force
            or termination["survivor_pids_after_force"] != []
            or termination["whole_process_tree_quiescent"] is not True
            or termination["survivor_probe_error"] != "NONE"
        ):
            raise AssertionError(f"timeout positive completion:{case_id}")
        if expected_force and not termination["survivor_pids_after_grace"]:
            raise AssertionError(f"forced case had no census survivor:{case_id}")
    return {
        "case_id": case_id, "status": "PASS",
        "expected_stop_id": expected_stop,
        "observed_stop_id": observed_stop,
        "observed_stop_detail": observed_detail,
        "control_case_id": control_case,
        "production_grace_seconds_observed": grace_calls[0],
        "partial_evidence_preserved": (
            stop["partial_evidence_status"] == "PRESERVED"
        ),
        "root_pid": pid_value["root_pid"],
        "child_pid": pid_value.get("child_pid", "NOT_APPLICABLE"),
        "grandchild_pid": pid_value.get(
            "grandchild_pid", "NOT_APPLICABLE",
        ),
        "force_process_group_termination": termination.get(
            "force_terminate_process_tree_executed",
            termination.get("force_process_group_signal_emitted"),
        ),
        "native_survivors_after_grace": termination.get(
            "survivor_pids_after_grace",
            "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE",
        ),
        "native_survivors_after_force": termination.get(
            "survivor_pids_after_force",
            "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE",
        ),
        "whole_process_tree_quiescent": termination.get(
            "whole_process_tree_quiescent"
        ),
        "native_failure_injected": negative,
        "external_ps_call_count": 0,
        "decision_ledger_rows": 0,
        "later_request_launch_count": 0,
    }


def native_timeout_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        repo: Path, runtime: Path, evidence: Path,
        series_path: Path, branch_path: Path, durability_path: Path,
        series: Mapping[str, Any], durability: Mapping[str, Any],
        branch_sha: str) -> Dict[str, Any]:
    rows = [
        timeout_case(
            case_id, authority, assets, repo, runtime, evidence,
            series_path, branch_path, durability_path,
            series, durability, branch_sha,
        )
        for case_id in TIMEOUT_CASE_IDS
    ]
    if tuple(row["case_id"] for row in rows) != TIMEOUT_CASE_IDS:
        raise AssertionError("timeout case order")
    for row in rows[:5]:
        if row["whole_process_tree_quiescent"] is not True:
            raise AssertionError(f"timeout quiescence:{row['case_id']}")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003NativeTimeoutCorpus/v1",
        "status": "PASS", "cases": rows, "case_count": len(rows),
        "positive_case_count": 5, "negative_case_count": 3,
        "negative_stop_id": "SB_STOP_TIMEOUT_TERMINATION",
        "native_survivor_authority": controller.DARWIN_SAMPLER_MECHANISM_ID,
        "external_ps_call_count": 0,
        "production_timeout_grace_seconds": 60,
        "no_later_request_launch": True,
    }
    write_canonical_json(evidence / "P22_NATIVE_TIMEOUT_CORPUS.json", value)
    return value


def load_pid_rows(path: Path) -> Dict[str, int]:
    value = strict_json_load(path)
    if not isinstance(value, Mapping):
        raise AssertionError("PID evidence object")
    rows = {}
    for key, item in value.items():
        if type(item) is not int or item <= 0:
            raise AssertionError(f"PID evidence:{key}:{item}")
        rows[key] = item
    return rows


def native_unseen_topology_integration(evidence: Path) -> Dict[str, Any]:
    root = evidence / "P22_NATIVE_UNSEEN_TOPOLOGY"
    root.mkdir(parents=True, exist_ok=False)
    partial = root / "partial.json"
    pids_path = root / "pids.json"
    ready = root / "ready.json"
    command = [
        sys.executable, "-B", str(TIMEOUT_CONTROL),
        "--case-id", "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
        "--partial", str(partial), "--pid-evidence", str(pids_path),
        "--ready", str(ready),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    backend = DarwinLibprocSamplerBackend()
    sampler: ProcessTreeRssSampler | None = None
    stdout = b""
    try:
        wait_for_ready(ready, process)
        initial_pids = load_pid_rows(pids_path)
        if initial_pids != {"root_pid": process.pid}:
            raise AssertionError(f"unseen initial PID disclosure:{initial_pids}")
        sampler = ProcessTreeRssSampler(
            process.pid, native_backend=backend,
        )
        sampler._sample()
        previous_owned = sorted(sampler.owned_pids)
        if previous_owned != [process.pid]:
            raise AssertionError(f"unseen previous owned:{previous_owned}")
        os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        deadline = time.monotonic() + 10
        discovered: Dict[str, int] = {}
        while time.monotonic() < deadline:
            if pids_path.is_file():
                discovered = load_pid_rows(pids_path)
            sampler._sample()
            expected = {
                discovered.get("child_pid"),
                discovered.get("grandchild_pid"),
            }
            expected.discard(None)
            if (
                len(expected) == 2
                and expected.issubset(sampler.active_owned_pids)
                and process.pid in sampler.identity_aware_exit_pids
            ):
                break
            time.sleep(0.01)
        else:
            raise AssertionError("native unseen topology discovery timeout")
        child_pid = discovered["child_pid"]
        grandchild_pid = discovered["grandchild_pid"]
        observed_active = sorted(sampler.active_owned_pids)
        observed_identities = {
            str(pid): list(sampler.native_owned_identities[pid])
            for pid in (child_pid, grandchild_pid)
        }
        observed_rss = sampler.current_bytes
        observed_maximum = sampler.maximum_bytes
        os.killpg(process.pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                sampler._sample()
            except NativeSamplerCapabilityError:
                raise
            if backend.authority_evidence()["group_retired"] is True:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("native unseen group did not retire")
        stdout, _ = process.communicate(timeout=5)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if backend.process_group_pids(process.pid):
                raise
        if process.poll() is None:
            process.wait(timeout=5)
        if process.stdout is not None and not stdout:
            stdout = process.stdout.read() or b""
    assert sampler is not None
    stdout_path = root / "control.stdout.bin"
    branch_fix.write_raw(stdout_path, stdout)
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003NativeUnseenTopology/v1",
        "status": "PASS", "non_stage_b_control": True,
        "command": command, "root_pid": process.pid,
        "child_pid": child_pid, "grandchild_pid": grandchild_pid,
        "previous_owned_pids": previous_owned,
        "root_absent_before_unseen_admission": (
            process.pid in sampler.identity_aware_exit_pids
        ),
        "child_not_previously_owned": child_pid not in previous_owned,
        "grandchild_not_previously_owned": grandchild_pid not in previous_owned,
        "child_discovered_by_native_group_census": child_pid in observed_active,
        "grandchild_discovered_by_native_group_census": (
            grandchild_pid in observed_active
        ),
        "admitted_exact_identities": observed_identities,
        "whole_group_rss_bytes": observed_rss,
        "maximum_whole_group_rss_bytes": observed_maximum,
        "native_authority": backend.authority_evidence(),
        "group_retired_after_force": (
            backend.authority_evidence()["group_retired"] is True
        ),
        "stdout_path": stdout_path.relative_to(evidence).as_posix(),
        "stdout_sha256": file_sha256(stdout_path),
        "external_ps_call_count": 0,
        "stage_b_worker_launch_count": 0,
        "bounded_control_process_count": 3,
    }
    required = (
        "root_absent_before_unseen_admission", "child_not_previously_owned",
        "grandchild_not_previously_owned",
        "child_discovered_by_native_group_census",
        "grandchild_discovered_by_native_group_census",
        "group_retired_after_force",
    )
    if not all(value[field] is True for field in required):
        raise AssertionError(f"native unseen topology gate:{value}")
    write_canonical_json(evidence / "P22_NATIVE_UNSEEN_TOPOLOGY.json", value)
    return value


def native_authority_runtime_gate(
        pgrp_diag_zip: Path, native_unseen: Mapping[str, Any],
        controlled: Mapping[str, Any], e2e: Mapping[str, Any],
        timeout: Mapping[str, Any], evidence: Path) -> Dict[str, Any]:
    observed = os.lstat(pgrp_diag_zip)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise AssertionError("PGRP-DIAG001 ZIP must be regular nonsymlink")
    pgrp_sha = file_sha256(pgrp_diag_zip)
    if pgrp_sha != PGRP_DIAG_ZIP_SHA256:
        raise AssertionError("PGRP-DIAG001 ZIP hash")
    e2e_sampler = e2e["sampler_diagnostic"]
    e2e_authority = e2e_sampler["native_process_group_authority"]
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003NativeAuthorityRuntimeGate/v1",
        "status": "PASS",
        "mechanism_id": controller.DARWIN_SAMPLER_MECHANISM_ID,
        "ctypes_abi": controller._darwin_ctypes_abi(),
        "expected_abi": controller.DARWIN_EXPECTED_ABI,
        "abi_exact": controller._darwin_ctypes_abi()
        == controller.DARWIN_EXPECTED_ABI,
        "accepted_pgrp_diag001_zip_path": str(pgrp_diag_zip),
        "accepted_pgrp_diag001_zip_sha256": pgrp_sha,
        "dual_native_census_functions": [
            "proc_listpgrppids", "proc_listpids(PROC_PGRP_ONLY)",
        ],
        "native_unseen_topology_pass": native_unseen["status"] == "PASS",
        "controlled_known_topology_pass": controlled["status"] == "PASS",
        "bounded_e2e_authority": e2e_authority,
        "bounded_e2e_dual_census_observed": (
            e2e_authority["dual_census_agreement_count"] >= 1
        ),
        "timeout_case_count": timeout["case_count"],
        "timeout_native_authority": timeout["native_survivor_authority"],
        "external_ps_call_count": 0,
    }
    if not all(value[field] is True for field in (
        "abi_exact", "native_unseen_topology_pass",
        "controlled_known_topology_pass", "bounded_e2e_dual_census_observed",
    )):
        raise AssertionError(f"native authority runtime gate:{value}")
    write_canonical_json(evidence / "NATIVE_AUTHORITY_RUNTIME_GATE.json", value)
    return value


def evidence_hashes(evidence: Path) -> Dict[str, str]:
    return {
        path.relative_to(evidence).as_posix(): file_sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "SAMPLER_FIX003_SUMMARY.json"
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = lexical_absolute(args.repo_root).resolve(strict=True)
    runtime_input = lexical_absolute(args.runtime_root)
    evidence_input = lexical_absolute(args.evidence_root)
    runtime_identity = require_empty_root(runtime_input, "runtime")
    evidence_identity = require_empty_root(evidence_input, "evidence")
    runtime = runtime_input.resolve(strict=True)
    evidence = evidence_input.resolve(strict=True)
    if runtime == evidence or runtime in evidence.parents or evidence in runtime.parents:
        raise AssertionError("runtime/evidence overlap")
    commit, tree, pre = assert_source(repo)
    authority = ExecutionAuthority(repo, commit, tree)
    assets = FrozenAssets(authority)
    durability_path, durability = branch_fix.preserve_exact_durability(
        lexical_absolute(args.durability), evidence,
    )

    p22 = p22_case_corpus(evidence)
    native_unseen = native_unseen_topology_integration(evidence)
    controller_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/"
        "stage_b_controller.py",
    ))

    def forbidden_external_table(*_args, **_kwargs):
        raise AssertionError("positive Darwin path attempted external process table")

    with mock.patch.object(
        controller, "_process_state_table", forbidden_external_table,
    ):
        controlled = branch_fix.controlled_sampler_diagnostic(
            repo, evidence, controller_sha,
        )
    hard_gate = branch_fix.whole_tree_hard_gate_corpus(evidence)
    branch_path, series_path, branch, series, branch_sha, series_sha = (
        branch_fix.capture_pair(runtime, evidence)
    )
    p18 = branch_fix.branch_binding_corpus(
        authority, assets, runtime, evidence, durability,
        branch, series, branch_sha, series_sha,
    )
    omission = branch_fix.make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "fix003-cli-omission-never-created",
    )
    branch_fix.worker_cli_omission(
        repo, runtime, evidence, series_path, durability_path, omission,
    )
    precedence = branch_fix.stop_precedence_corpus(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        durability, branch_sha, series,
    )
    timeout = native_timeout_corpus(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        series, durability, branch_sha,
    )
    with mock.patch.object(
        controller, "_process_state_table", forbidden_external_table,
    ):
        e2e = branch_fix.bounded_e2e(
            authority, assets, repo, runtime, evidence,
            series_path, branch_path, durability_path,
            series, branch, durability, branch_sha, series_sha,
        )
    native_gate = native_authority_runtime_gate(
        lexical_absolute(args.pgrp_diag_package), native_unseen,
        controlled, e2e, timeout, evidence,
    )

    if any(runtime.iterdir()):
        raise AssertionError("runtime not empty after bounded corpus")
    post = source_checkpoint(repo)
    if post != pre:
        raise AssertionError("source changed during evidence transaction")
    source = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_identity, "evidence_root": evidence_identity,
        "changed_paths": sorted(CHANGED_PATHS),
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    zero = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003ZeroLargeExecution/v1",
        "status": "PASS_BOUNDED_PREFLIGHT_ONLY",
        "authorized_stage_b_worker_launch_count": 0,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "authority_sized_candidate_launch_count": 0,
        "stage_b_measured_clock_count": 0,
        "decision_engine_invocation_count": 0,
        "backend_selection_count": 0,
        "authorized_to_run_artifact_count": 0,
        "p22_synthetic_process_launch_count": 0,
        "p22_native_control_root_launch_count": 1,
        "p22_native_control_descendant_launch_count": 2,
        "known_topology_control_root_launch_count": 1,
        "known_topology_control_descendant_launch_count": 2,
        "bounded_timeout_root_launch_count": 8,
        "bounded_timeout_descendant_launch_count": 12,
        "precedence_control_process_launch_count": 3,
        "precedence_real_worker_live_entry_count": 1,
        "worker_cli_parser_process_count": 1,
        "bounded_e2e_worker_launch_count": 1,
        "bounded_diagnostic_allocation_bytes": 48 * 1024 * 1024,
        "bounded_candidate_store_construction_count": 1,
        "bounded_candidate_store_cleaned": True,
        "external_process_table_call_count": 0,
        "runtime_root_final_entry_count": 0,
        "physical_execution_authorized": False,
    }
    write_canonical_json(evidence / "ZERO_LARGE_EXECUTION_PROOF.json", zero)
    checker_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/independent/"
        "check_sampler_fix003.py",
    ))
    summary = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix003Summary/v1",
        "status": "PASS_SAMPLER_FIX003_BOUNDED_PREFLIGHT_ONLY",
        "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "checker_sha256": checker_sha,
        "p22_case_count": len(p22["cases"]),
        "native_unseen_topology_pass": native_unseen["status"] == "PASS",
        "native_timeout_case_count": len(timeout["cases"]),
        "p18_mutation_case_count": len(p18["cases"]),
        "worker_precedence_case_count": len(precedence["cases"]),
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "whole_tree_hard_gate_pass": hard_gate["status"] == "PASS",
        "native_authority_runtime_gate_pass": native_gate["status"] == "PASS",
        "external_ps_call_count_in_native_rss_and_timeout": 0,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_measured_clock_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": 0,
        "claim_ceiling": (
            "BOUNDED_SAMPLER_FIX003_PREFLIGHT_ONLY_"
            "NO_STAGEB_PERFORMANCE_OR_AUTHORIZATION_CLAIM"
        ),
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "SAMPLER_FIX003_SUMMARY.json", summary)
    return summary


def self_test() -> None:
    if len(P22_CASE_IDS) != 8 or len(TIMEOUT_CASE_IDS) != 8:
        raise AssertionError("case cardinality")
    temporary = Path("/private/tmp") / f"sampler-fix003-selftest-{os.getpid()}"
    if temporary.exists():
        raise AssertionError("self-test path exists")
    temporary.mkdir(mode=0o700)
    try:
        p22_case_corpus(temporary)
    finally:
        shutil.rmtree(temporary)
    print(
        "PASS_SAMPLER_FIX003_RUNNER_SELF_TEST P22=8 TIMEOUT=8 "
        "PHYSICAL_EXECUTION=0"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    parser.add_argument("--pgrp-diag-package", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-bounded-fix003", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.print_plan:
        print(
            "SAMPLER_FIX003_PLAN P22=8 TIMEOUT=8 P18=7 "
            "BOUNDED_E2E_WORKERS=1 LARGE_WORKERS=0 STAGEB_MEASURED=0"
        )
        return
    if None in (
        args.repo_root, args.runtime_root, args.evidence_root,
        args.durability, args.pgrp_diag_package,
    ):
        parser.error("all bounded execution paths are required")
    summary = execute(args)
    print(
        "PASS_SAMPLER_FIX003_BOUNDED_PREFLIGHT_ONLY "
        f"COMMIT={summary['source_commit']} P22=8 TIMEOUT=8 P18=7 "
        "BOUNDED_E2E=PASS LARGE_WORKERS=0 STAGEB_MEASURED=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
