#!/usr/bin/env python3
"""Produce bounded SAMPLER-FIX002 evidence; never run authority-sized Stage-B."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Dict, Mapping


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
import run_branch_fix001_preflight as fix1  # noqa: E402
import stage_b_controller as controller  # noqa: E402
from stage_b_controller import (  # noqa: E402
    DarwinLibprocSamplerBackend,
    NativeSamplerCapabilityError,
    NativeSamplerProcessAbsent,
    ProcessTreeRssSampler,
    launch_request,
)


BASE_COMMIT = "f766314dfb2770fbb6a302248ab0b3a3348344d1"
BASE_TREE = "7dc7b09c1e6a51b5e112700f074a7347a71fa59d"
EXPECTED_DURABILITY_SHA256 = (
    "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
)
TIMEOUT_CONTROL = HERE / "sampler_fix002_timeout_control.py"
P20_CASE_IDS = (
    "ROOT_EXITS_CHILD_LIVES",
    "ROOT_EXITS_CHILD_MEMORY_GROWS",
    "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD",
)
TIMEOUT_CASE_IDS = (
    "ROOT_ONLY_COOPERATIVE_EXIT",
    "ROOT_AND_CHILD_COOPERATIVE_EXIT",
    "ROOT_EXITS_CHILD_IGNORES",
    "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD",
    "ROOT_AND_DESCENDANTS_REQUIRE_FORCE",
    "PID_REUSE_DURING_TIMEOUT_PROBE",
    "NATIVE_ENUMERATION_FAILURE",
    "NATIVE_IDENTITY_FAILURE",
)
CHANGED_PATHS = {
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_sampler_fix002_preflight.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/sampler_fix002_timeout_control.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix002.py",
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


def require_root(path: Path, label: str) -> Dict[str, Any]:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise AssertionError(f"{label} must be an ordinary directory")
    if any(path.iterdir()):
        raise AssertionError(f"{label} must be empty before execution")
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
        raise AssertionError("base tree")
    if any(pre[field] for field in (
        "branch_stdout", "full_status_stdout", "protected_status_stdout",
    )):
        raise AssertionError("producer source must be detached and clean")
    changed = {
        row.split("\t", 1)[1]
        for row in git(
            repo, "diff-tree", "--no-commit-id", "--name-status", "-r",
            BASE_COMMIT, commit,
        ).decode("utf-8").splitlines()
    }
    if changed != CHANGED_PATHS:
        raise AssertionError(f"changed scope:{changed}")
    for relative in CHANGED_PATHS:
        if (
            git(repo, "show", f"{commit}:{relative}")
            != (repo / relative).read_bytes()
        ):
            raise AssertionError(f"Git/worktree bytes:{relative}")
    if Path(__file__).read_bytes() != git(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/"
        "run_sampler_fix002_preflight.py",
    ):
        raise AssertionError("executed runner not child Git object")
    return commit, tree, pre


class FakeNativeBackend:
    def __init__(self) -> None:
        self.children_map: Dict[int, tuple[int, ...]] = {
            100: (101,), 101: (), 102: (),
        }
        self.identities: Dict[int, tuple[int, tuple[int, int, int]]] = {
            100: (1, (100, 10, 1)),
            101: (100, (101, 11, 1)),
            102: (101, (102, 12, 1)),
        }
        self.rss_map = {100: 10, 101: 100, 102: 500}

    def children(self, pid: int) -> tuple[int, ...]:
        return self.children_map.get(pid, ())

    def identity(self, pid: int) -> tuple[int, tuple[int, int, int]]:
        try:
            return self.identities[pid]
        except KeyError as error:
            raise NativeSamplerProcessAbsent(f"ABSENT:{pid}") from error

    def rss(self, pid: int) -> int:
        try:
            return self.rss_map[pid]
        except KeyError as error:
            raise NativeSamplerProcessAbsent(f"ABSENT_RSS:{pid}") from error


def root_exit_descendant_corpus(evidence: Path) -> Dict[str, Any]:
    rows = []

    backend = FakeNativeBackend()
    sampler = ProcessTreeRssSampler(100, native_backend=backend)
    sampler._sample()
    initial_max = sampler.maximum_bytes
    del backend.identities[100]
    del backend.rss_map[100]
    backend.children_map[100] = ()
    sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_CHILD_LIVES", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101]
        == (101, 11, 1),
        "active_owned_pids": sorted(sampler.active_owned_pids),
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
        "initial_maximum_bytes": initial_max,
    })

    backend.rss_map[101] = 1000
    sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_CHILD_MEMORY_GROWS", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101]
        == (101, 11, 1),
        "child_rss_bytes": backend.rss_map[101],
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
        "maximum_grew_after_root_exit": sampler.maximum_bytes >= 1000,
    })

    backend.children_map[101] = (102,)
    sampler._sample()
    rows.append({
        "case_id": "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD", "status": "PASS",
        "root_absent": 100 in sampler.identity_aware_exit_pids,
        "child_identity_preserved": sampler.native_owned_identities[101]
        == (101, 11, 1),
        "grandchild_discovered_from_live_owned_child": 102
        in sampler.active_owned_pids,
        "grandchild_identity": list(sampler.native_owned_identities[102]),
        "current_whole_tree_rss_bytes": sampler.current_bytes,
        "maximum_whole_tree_rss_bytes": sampler.maximum_bytes,
    })

    if tuple(row["case_id"] for row in rows) != P20_CASE_IDS:
        raise AssertionError("P20 case order")
    if not all(
        row["root_absent"] and row["child_identity_preserved"]
        for row in rows
    ):
        raise AssertionError("P20 exact identity/root exit")
    if rows[0]["current_whole_tree_rss_bytes"] != 100:
        raise AssertionError("P20 child-live RSS")
    if rows[1]["maximum_grew_after_root_exit"] is not True:
        raise AssertionError("P20 child growth")
    if rows[2]["grandchild_discovered_from_live_owned_child"] is not True:
        raise AssertionError("P20 post-root grandchild")

    del backend.identities[101]
    del backend.identities[102]
    del backend.rss_map[101]
    del backend.rss_map[102]
    sampler._sample()
    if sampler.active_owned_pids or sampler.current_bytes != 0:
        raise AssertionError("P20 quiescence")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix002RootExitCorpus/v1",
        "status": "PASS", "cases": rows,
        "all_exact_owned_identities_absent_quiescent": True,
        "final_current_whole_tree_rss_bytes": sampler.current_bytes,
        "final_active_owned_pids": sorted(sampler.active_owned_pids),
        "external_process_table_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P20_ROOT_EXIT_DESCENDANT_CORPUS.json", value)
    return value


class ArmedBackend:
    def __init__(self, inner: DarwinLibprocSamplerBackend) -> None:
        self.inner = inner
        self.failure = "NONE"

    def children(self, pid: int) -> tuple[int, ...]:
        if self.failure == "ENUMERATION":
            raise NativeSamplerCapabilityError("INJECTED_NATIVE_ENUMERATION_FAILURE")
        return self.inner.children(pid)

    def identity(self, pid: int) -> tuple[int, tuple[int, int, int]]:
        if self.failure == "IDENTITY":
            raise NativeSamplerCapabilityError("INJECTED_NATIVE_IDENTITY_FAILURE")
        ppid, identity = self.inner.identity(pid)
        if self.failure == "PID_REUSE":
            return ppid, (identity[0], identity[1] + 1, identity[2])
        return ppid, identity

    def rss(self, pid: int) -> int:
        return self.inner.rss(pid)

    def capability_evidence(self) -> Dict[str, Any]:
        return self.inner.capability_evidence()


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
    root = evidence / "P21_NATIVE_TIMEOUT_CORPUS" / case_id
    root.mkdir(parents=True, exist_ok=False)
    request = fix1.make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, f"timeout-{case_id.lower()}",
    )
    output = root / "worker.result.json"
    partial = output.with_suffix(".partial.json")
    pids = root / "pids.json"
    ready = root / "ready.json"
    control_case = (
        case_id if case_id in fix_timeout_control_cases()
        else "ROOT_AND_DESCENDANTS_REQUIRE_FORCE"
    )
    command = [
        sys.executable, "-B", str(TIMEOUT_CONTROL),
        "--case-id", control_case, "--partial", str(partial),
        "--pid-evidence", str(pids), "--ready", str(ready),
    ]
    inner = DarwinLibprocSamplerBackend()
    armed = ArmedBackend(inner)
    grace_calls = []

    def bounded_waiter(process: subprocess.Popen, seconds: int) -> bool:
        grace_calls.append(seconds)
        wait_for_ready(ready, process)
        if case_id == "PID_REUSE_DURING_TIMEOUT_PROBE":
            armed.failure = "PID_REUSE"
        elif case_id == "NATIVE_ENUMERATION_FAILURE":
            armed.failure = "ENUMERATION"
        elif case_id == "NATIVE_IDENTITY_FAILURE":
            armed.failure = "IDENTITY"
        try:
            process.wait(timeout=0.6)
            return True
        except subprocess.TimeoutExpired:
            return False

    expected_stop = (
        "SB_STOP_TIMEOUT_TERMINATION"
        if case_id in TIMEOUT_CASE_IDS[-3:] else "SB_STOP_TIMEOUT"
    )
    try:
        launch_request(
            repo, runtime, series_path, durability_path, request,
            root / "worker.request.json", output,
            root / "controller.log.txt", branch_path,
            bounded_waiter, command, 0.50,
            sampler_backend_factory=lambda: armed,
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
        expected_force = case_id not in TIMEOUT_CASE_IDS[:2]
        if (
            termination["force_terminate_process_tree_executed"]
            is not expected_force
            or termination["survivor_pids_after_force"] != []
            or termination["whole_process_tree_quiescent"] is not True
            or termination["survivor_probe_error"] != "NONE"
        ):
            raise AssertionError(f"timeout positive completion:{case_id}")
    return {
        "case_id": case_id, "status": "PASS",
        "expected_stop_id": expected_stop,
        "observed_stop_id": observed_stop,
        "observed_stop_detail": observed_detail,
        "control_case_id": control_case,
        "production_grace_seconds_observed": grace_calls[0],
        "partial_evidence_preserved": stop["partial_evidence_status"]
        == "PRESERVED",
        "root_pid": pid_value["root_pid"],
        "child_pid": pid_value.get("child_pid", "NOT_APPLICABLE"),
        "grandchild_pid": pid_value.get("grandchild_pid", "NOT_APPLICABLE"),
        "force_process_group_termination": termination.get(
            "force_terminate_process_tree_executed",
            termination.get("force_process_group_signal_emitted"),
        ),
        "native_survivors_after_force": termination.get(
            "survivor_pids_after_force", "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE",
        ),
        "whole_process_tree_quiescent": termination.get(
            "whole_process_tree_quiescent"
        ),
        "native_failure_injected": negative,
        "external_ps_call_count": 0,
        "decision_ledger_rows": 0,
        "later_request_launch_count": 0,
    }


def fix_timeout_control_cases() -> tuple[str, ...]:
    return TIMEOUT_CASE_IDS[:5]


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
        raise AssertionError("P21 timeout case order")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix002NativeTimeoutCorpus/v1",
        "status": "PASS", "cases": rows,
        "case_count": len(rows),
        "external_ps_call_count": 0,
        "native_survivor_authority": controller.DARWIN_SAMPLER_MECHANISM_ID,
        "positive_case_count": 5, "negative_case_count": 3,
        "negative_stop_id": "SB_STOP_TIMEOUT_TERMINATION",
        "no_later_request_launch": True,
    }
    write_canonical_json(evidence / "P21_NATIVE_TIMEOUT_CORPUS.json", value)
    return value


def evidence_hashes(evidence: Path) -> Dict[str, str]:
    return {
        path.relative_to(evidence).as_posix(): file_sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "SAMPLER_FIX002_SUMMARY.json"
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = lexical_absolute(args.repo_root).resolve(strict=True)
    runtime_input = lexical_absolute(args.runtime_root)
    evidence_input = lexical_absolute(args.evidence_root)
    runtime_identity = require_root(runtime_input, "runtime")
    evidence_identity = require_root(evidence_input, "evidence")
    runtime = runtime_input.resolve(strict=True)
    evidence = evidence_input.resolve(strict=True)
    if runtime == evidence or runtime in evidence.parents or evidence in runtime.parents:
        raise AssertionError("runtime/evidence overlap")
    commit, tree, pre = assert_source(repo)
    authority = ExecutionAuthority(repo, commit, tree)
    assets = FrozenAssets(authority)
    durability_path, durability = fix1.preserve_exact_durability(
        lexical_absolute(args.durability), evidence,
    )

    p20 = root_exit_descendant_corpus(evidence)
    fix1.external_ps_independence_regression(evidence)
    controller_sha = sha256(git(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    ))
    fix1.controlled_sampler_diagnostic(repo, evidence, controller_sha)
    fix1.native_sampler_failure_corpus(evidence)
    fix1.whole_tree_hard_gate_corpus(evidence)
    branch_path, series_path, branch, series, branch_sha, series_sha = (
        fix1.capture_pair(runtime, evidence)
    )
    p18 = fix1.branch_binding_corpus(
        authority, assets, runtime, evidence, durability,
        branch, series, branch_sha, series_sha,
    )
    omission = fix1.make_request(
        authority, assets, branch_sha, series, durability,
        runtime, evidence, "fix002-cli-omission-never-created",
    )
    fix1.worker_cli_omission(
        repo, runtime, evidence, series_path, durability_path, omission,
    )
    fix1.stop_precedence_corpus(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        durability, branch_sha, series,
    )
    p21 = native_timeout_corpus(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        series, durability, branch_sha,
    )
    e2e = fix1.bounded_e2e(
        authority, assets, repo, runtime, evidence,
        series_path, branch_path, durability_path,
        series, branch, durability, branch_sha, series_sha,
    )

    if any(runtime.iterdir()):
        raise AssertionError("runtime not empty after bounded corpus")
    post = source_checkpoint(repo)
    if post != pre:
        raise AssertionError("source changed during evidence transaction")
    source = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix002SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_identity, "evidence_root": evidence_identity,
        "changed_paths": sorted(CHANGED_PATHS),
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    zero = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix002ZeroLargeExecution/v1",
        "status": "PASS_BOUNDED_PREFLIGHT_ONLY",
        "authorized_stage_b_worker_launch_count": 0,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_measured_clock_count": 0,
        "decision_engine_invocation_count": 0,
        "backend_selection_count": 0,
        "production_r_or_src_change_count": 0,
        "p20_synthetic_process_launch_count": 0,
        "p21_bounded_timeout_controller_launch_count": 8,
        "p18_precedence_control_launch_count": 3,
        "p18_cli_parser_process_count": 1,
        "bounded_e2e_worker_launch_count": 1,
        "controlled_native_sampler_process_tree_count": 1,
        "bounded_diagnostic_allocation_bytes": 48 * 1024 * 1024,
        "runtime_root_final_entry_count": 0,
        "physical_execution_authorized": False,
    }
    write_canonical_json(evidence / "ZERO_LARGE_EXECUTION_PROOF.json", zero)
    checker_sha = sha256(git(
        repo, "show",
        f"{commit}:dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix002.py",
    ))
    summary = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix002Summary/v1",
        "status": "PASS_SAMPLER_FIX002_BOUNDED_PREFLIGHT_ONLY",
        "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "checker_sha256": checker_sha,
        "p20_case_count": len(p20["cases"]),
        "p21_timeout_case_count": len(p21["cases"]),
        "p18_mutation_case_count": len(p18["cases"]),
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "external_ps_call_count_in_native_rss_and_timeout": 0,
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "stage_b_measured_clock_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": 0,
        "claim_ceiling": (
            "BOUNDED_SAMPLER_FIX002_PREFLIGHT_ONLY_"
            "NO_STAGEB_PERFORMANCE_OR_AUTHORIZATION_CLAIM"
        ),
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "SAMPLER_FIX002_SUMMARY.json", summary)
    return summary


def self_test() -> None:
    if len(P20_CASE_IDS) != 3 or len(TIMEOUT_CASE_IDS) != 8:
        raise AssertionError("case cardinality")
    temporary = Path("/private/tmp") / f"sampler-fix002-selftest-{os.getpid()}"
    if temporary.exists():
        raise AssertionError("self-test path exists")
    temporary.mkdir(mode=0o700)
    try:
        root_exit_descendant_corpus(temporary)
    finally:
        shutil.rmtree(temporary)
    print(
        "PASS_SAMPLER_FIX002_RUNNER_SELF_TEST P20=3 P21=8 "
        "PHYSICAL_EXECUTION=0"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-bounded-fix002", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.print_plan:
        print(
            "SAMPLER_FIX002_PLAN P20=3 P21_TIMEOUT=8 P18=REGRESSION "
            "BOUNDED_E2E_WORKERS=1 LARGE_WORKERS=0 STAGEB_MEASURED=0"
        )
        return
    if None in (
        args.repo_root, args.runtime_root, args.evidence_root, args.durability,
    ):
        parser.error("all bounded execution paths are required")
    summary = execute(args)
    print(
        "PASS_SAMPLER_FIX002_BOUNDED_PREFLIGHT_ONLY "
        f"COMMIT={summary['source_commit']} P20=3 P21=8 P18=PASS "
        "BOUNDED_E2E=PASS LARGE_WORKERS=0 STAGEB_MEASURED=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
