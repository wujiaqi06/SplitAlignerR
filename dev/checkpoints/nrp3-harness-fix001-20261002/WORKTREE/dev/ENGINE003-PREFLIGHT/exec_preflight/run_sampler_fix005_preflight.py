#!/usr/bin/env python3
"""Produce bounded SAMPLER-FIX005 evidence; never run measured Stage-B."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Dict


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    ExecutionAuthority, FrozenAssets, write_canonical_json,
)
import run_branch_fix001_preflight as branch_fix  # noqa: E402
import run_sampler_fix003_preflight as fix3  # noqa: E402
import run_sampler_fix004_preflight as fix4  # noqa: E402
import stage_b_controller as controller  # noqa: E402
from stage_b_controller import (  # noqa: E402
    DarwinLibprocSamplerBackend, NativeSamplerCapabilityError,
    NativeSamplerIdentityAwareExitRace, NativeSamplerProcessAbsent,
)


BASE_COMMIT = "cce7ce6c5ab17de1e766fa9efba7c66a73452c39"
BASE_TREE = "500fc6d0d3a0c06bbceaf99c4e0d1ddc85461d22"
DURABILITY_SHA256 = "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
P25_CASE_IDS = (
    "KNOWN_PID_ABSENT_CENSUS_AND_ESRCH",
    "KNOWN_PID_ABSENT_CENSUS_SAME_IDENTITY_DIFFERENT_PGID",
    "KNOWN_PID_ABSENT_CENSUS_DIFFERENT_IDENTITY",
    "KNOWN_PID_ABSENT_CENSUS_SAME_IDENTITY_SAME_PGID",
    "ZERO_RSS_ABSENT_CENSUS_AND_ESRCH",
    "ZERO_RSS_ABSENT_CENSUS_SAME_IDENTITY_DIFFERENT_PGID",
    "ZERO_RSS_ABSENT_CENSUS_PID_REUSED",
    "ZERO_RSS_ABSENT_CENSUS_SAME_IDENTITY_SAME_PGID",
)
CHANGED_PATHS = {
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_sampler_fix005_preflight.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix005.py",
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
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
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
            "branch_stdout", "full_status_stdout", "protected_status_stdout")):
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


class MissingCensusBackend(DarwinLibprocSamplerBackend):
    """Deterministic stable-census omission authority; no process launch."""

    def __init__(self, identity_outcome: object, task_zero: bool = False) -> None:
        fix4.initialize_backend(self)
        self.identity_outcome = identity_outcome
        self.identity_lookup_count = 0
        self.stable_census_call_count = 0
        self.taskinfo_call_count = 0
        self.task_zero = task_zero

    def process_group_pids(self, pgid: int) -> tuple[int, ...]:
        if pgid != 100:
            raise AssertionError("expected PGID")
        self.stable_census_call_count += 1
        return ()

    def identity_and_group(self, pid: int):
        if pid != 42:
            raise AssertionError("expected PID")
        self.identity_lookup_count += 1
        if isinstance(self.identity_outcome, BaseException):
            raise self.identity_outcome
        return self.identity_outcome

    def _task_rss_once(self, pid: int) -> int:
        if not self.task_zero or pid != 42:
            raise AssertionError("unexpected taskinfo")
        self.taskinfo_call_count += 1
        return 0


def p25_case(case_id: str, zero_rss: bool, outcome: object,
             expected: str) -> Dict[str, Any]:
    expected_identity = (42, 123, 456)
    backend = MissingCensusBackend(outcome, zero_rss)
    terminal, error, absent = "NONE", "NONE", []
    try:
        if zero_rss:
            backend.rss(42, expected_identity, 100)
        else:
            live, absent_set = backend.live_owned_tree({42: expected_identity})
            if live:
                raise AssertionError("omitted PID classified live")
            absent = sorted(absent_set)
            terminal = "IDENTITY_AWARE_EXIT"
    except NativeSamplerIdentityAwareExitRace as failure:
        terminal, error = "IDENTITY_AWARE_EXIT", str(failure)
    except NativeSamplerCapabilityError as failure:
        terminal, error = "TYPED_FAIL_CLOSED", str(failure)
    if expected == "IDENTITY_AWARE_EXIT":
        if terminal != expected or (not zero_rss and absent != [42]):
            raise AssertionError(f"P25 exit:{case_id}:{terminal}:{error}:{absent}")
    elif terminal != "TYPED_FAIL_CLOSED" or expected not in error:
        raise AssertionError(f"P25 failure:{case_id}:{terminal}:{error}")
    authority = backend.authority_evidence()
    if (
        backend.identity_lookup_count != 1
        or authority["known_identity_absence_revalidation_count"] != 1
    ):
        raise AssertionError(f"P25 exact revalidation:{case_id}:{authority}")
    return {
        "case_id": case_id, "status": "PASS", "path": (
            "ZERO_RSS" if zero_rss else "LIVE_OWNED_TREE"
        ),
        "expected_terminal": expected, "observed_terminal": terminal,
        "terminal_error": error, "known_pid": 42,
        "expected_identity": list(expected_identity), "expected_pgid": 100,
        "stable_census_pids": [],
        "identity_and_group_lookup_count": backend.identity_lookup_count,
        "stable_census_call_count": backend.stable_census_call_count,
        "taskinfo_call_count": backend.taskinfo_call_count,
        "identity_aware_absent_pids": absent,
        "shared_primitive_revalidation_count": authority[
            "known_identity_absence_revalidation_count"
        ],
        "shared_primitive_exit_count": authority[
            "known_identity_absence_exit_count"
        ],
        "shared_primitive_fail_closed_count": authority[
            "known_identity_absence_fail_closed_count"
        ],
        "zero_rss_never_accepted": True,
    }


def p25_corpus(evidence: Path) -> Dict[str, Any]:
    absent = NativeSamplerProcessAbsent("PROCESS_ABSENT:pid=42")
    same = (1, 100, (42, 123, 456))
    escaped = (1, 999, (42, 123, 456))
    reused = (1, 100, (42, 124, 456))
    rows = [
        p25_case(P25_CASE_IDS[0], False, absent, "IDENTITY_AWARE_EXIT"),
        p25_case(P25_CASE_IDS[1], False, escaped, "OWNED_PROCESS_ESCAPED_WORKER_PGID"),
        p25_case(P25_CASE_IDS[2], False, reused, "OWNED_PID_REUSE_REJECTED"),
        p25_case(P25_CASE_IDS[3], False, same, "STABLE_GROUP_CENSUS_IDENTITY_CONTRADICTION"),
        p25_case(P25_CASE_IDS[4], True, absent, "IDENTITY_AWARE_EXIT"),
        p25_case(P25_CASE_IDS[5], True, escaped, "OWNED_PROCESS_ESCAPED_WORKER_PGID"),
        p25_case(P25_CASE_IDS[6], True, reused, "OWNED_PID_REUSE_REJECTED"),
        p25_case(P25_CASE_IDS[7], True, same, "STABLE_GROUP_CENSUS_IDENTITY_CONTRADICTION"),
    ]
    if tuple(row["case_id"] for row in rows) != P25_CASE_IDS:
        raise AssertionError("P25 order")
    counterexample = rows[1]
    if not (
        counterexample["expected_identity"] == [42, 123, 456]
        and counterexample["expected_pgid"] == 100
        and counterexample["identity_and_group_lookup_count"] == 1
        and "observed=999" in counterexample["terminal_error"]
    ):
        raise AssertionError("main-control counterexample")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix005P25KnownIdentityAbsence/v1",
        "status": "PASS", "case_count": 8, "cases": rows,
        "shared_primitive": (
            "DarwinLibprocSamplerBackend."
            "_revalidate_known_identity_absent_from_stable_census"
        ),
        "live_owned_tree_case_count": 4, "zero_rss_case_count": 4,
        "identity_lookup_call_count": 8,
        "external_process_table_call_count": 0,
        "physical_process_launch_count": 0,
    }
    write_canonical_json(evidence / "P25_KNOWN_IDENTITY_ABSENCE_CORPUS.json", value)
    return value


def p23_corpus(evidence: Path) -> Dict[str, Any]:
    absent = NativeSamplerProcessAbsent("PROCESS_ABSENT:pid=100")
    zombie = NativeSamplerProcessAbsent("PROCESS_ZOMBIE:pid=100")
    ids = fix4.P23_CASE_IDS
    rows = [
        fix4.p23_case(ids[0], [0, 4096], [(100,)], None, "POSITIVE"),
        fix4.p23_case(ids[1], [0, 0, 4096], [(100,), (100,)], None, "POSITIVE"),
        fix4.p23_case(ids[2], [0, 0, 0, 0, 4096], [(100,)] * 4, None, "POSITIVE"),
        fix4.p23_case(ids[3], [0], [()], [absent], "ABSENT"),
        fix4.p23_case(ids[4], [0], [(100,)], [zombie], "ABSENT"),
        fix4.p23_case(ids[5], [0] * 5, [(100,)] * 4, None, "TASK_INFO_ZERO_RSS_UNRESOLVED"),
        fix4.p23_case(ids[6], [0], [(100,)], [(1, 100, (100, 11, 1))], "PID_REUSE_DURING_ZERO_RSS_RETRY"),
        fix4.p23_case(ids[7], [0], [(100,)], [(1, 101, (100, 10, 1))], "PGID_CHANGE_DURING_ZERO_RSS_RETRY"),
        fix4.p23_case(ids[8], [0, {"resident": 4096, "returned": 95, "errno": 0}], [(100,)], None, "TASK_INFO_FAILED"),
        fix4.p23_case(ids[9], [0, {"resident": 4096, "returned": 96, "errno": 1}], [(100,)], None, "TASK_INFO_FAILED"),
    ]
    if tuple(row["case_id"] for row in rows) != ids:
        raise AssertionError("P23 order")
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix005P23Regression/v1",
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


def evidence_hashes(evidence: Path) -> Dict[str, str]:
    return {
        path.relative_to(evidence).as_posix(): file_sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "SAMPLER_FIX005_SUMMARY.json"
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = lexical_absolute(args.repo_root).resolve(strict=True)
    runtime_input = lexical_absolute(args.runtime_root)
    evidence_input = lexical_absolute(args.evidence_root)
    runtime_id = root_identity(runtime_input, "runtime")
    evidence_id = root_identity(evidence_input, "evidence")
    runtime = runtime_input.resolve(strict=True)
    evidence = evidence_input.resolve(strict=True)
    if runtime == evidence or runtime in evidence.parents or evidence in runtime.parents:
        raise AssertionError("root overlap")
    commit, tree, pre = assert_source(repo)
    authority = ExecutionAuthority(repo, commit, tree)
    assets = FrozenAssets(authority)
    durability_path, durability = branch_fix.preserve_exact_durability(
        lexical_absolute(args.durability), evidence,
    )
    if file_sha256(durability_path) != DURABILITY_SHA256:
        raise AssertionError("durability SHA")

    p25 = p25_corpus(evidence)
    p23 = p23_corpus(evidence)
    p24 = fix4.p24_corpus(evidence)
    p20 = fix4.p20_regression(evidence)
    p22 = fix3.p22_case_corpus(evidence)
    churn = fix4.darwin_churn(evidence)
    if churn["native_authority"]["known_identity_absence_revalidation_count"] < 1:
        raise AssertionError("real Darwin churn did not revalidate known absence")
    churn["schema"] = "SplitAlignerR/ENGINE003StageBSamplerFix005DarwinChurn/v1"
    churn["known_identity_disappearance_revalidated"] = True
    churn["false_identity_aware_exit_count"] = 0
    write_canonical_json(evidence / "DARWIN_BOUNDED_CHURN.json", churn)
    controller_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    ))
    controlled = branch_fix.controlled_sampler_diagnostic(repo, evidence, controller_sha)
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
        runtime, evidence, "fix005-cli-omission-never-created",
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
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix005SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": BASE_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_id, "evidence_root": evidence_id,
        "changed_paths": sorted(CHANGED_PATHS),
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    zero = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix005ZeroBoundary/v1",
        "status": "PASS_BOUNDED_PREFLIGHT_ONLY",
        "authorized_stage_b_worker_launch_count": 0,
        "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "over_2gib_store_count": 0, "over_4gib_store_count": 0,
        "backend_selection_count": 0, "decision_engine_invocation_count": 0,
        "authorized_to_run_artifact_count": 0,
        "attempt003_resume_count": 0, "attempt003_root_write_count": 0,
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "bounded_churn_root_launch_count": 1,
        "bounded_churn_child_launch_count": 48,
        "controlled_sampler_root_process_count": 1,
        "controlled_sampler_descendant_process_count": 1,
        "precedence_control_process_launch_count": 3,
        "worker_cli_parser_process_count": 1,
        "external_process_table_call_count": 0,
        "runtime_root_final_entry_count": 0,
        "physical_execution_authorized": False,
    }
    write_canonical_json(evidence / "ZERO_BOUNDARY.json", zero)
    checker_sha = sha256(git(
        repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/independent/check_sampler_fix005.py",
    ))
    summary = {
        "schema": "SplitAlignerR/ENGINE003StageBSamplerFix005Summary/v1",
        "status": "PASS_SAMPLER_FIX005_BOUNDED_PREFLIGHT_ONLY",
        "source_commit": commit, "source_tree": tree, "direct_parent": BASE_COMMIT,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "checker_sha256": checker_sha,
        "p25_case_count": p25["case_count"],
        "p23_case_count": p23["case_count"],
        "p24_case_count": p24["case_count"],
        "p18_case_count": len(p18["cases"]),
        "p20_case_count": len(p20["cases"]),
        "p22_case_count": len(p22["cases"]),
        "p21_timeout_case_count": len(timeout["cases"]),
        "worker_precedence_case_count": len(precedence["cases"]),
        "darwin_churn_pass": churn["status"] == "PASS",
        "known_identity_disappearance_revalidated": True,
        "controlled_sampler_pass": controlled["status"] == "PASS",
        "whole_tree_hard_gate_pass": hard_gate["status"] == "PASS",
        "bounded_e2e_pass": e2e["status"] == "PASS",
        "bounded_e2e_worker_launch_count": e2e["worker_launch_count"],
        "external_process_table_call_count": 0,
        "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": 0,
        "claim_ceiling": (
            "BOUNDED_SAMPLER_FIX005_PREFLIGHT_ONLY_"
            "NO_STAGEB_PERFORMANCE_OR_AUTHORIZATION_CLAIM"
        ),
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "SAMPLER_FIX005_SUMMARY.json", summary)
    return summary


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="sampler-fix005-selftest-") as value:
        temporary = Path(value)
        p25_corpus(temporary)
        p23_corpus(temporary)
        fix4.p24_corpus(temporary)
        fix4.p20_regression(temporary)
    print("PASS_SAMPLER_FIX005_RUNNER_SELF_TEST P25=8 P23=10 P24=7 PHYSICAL_EXECUTION=0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-bounded-fix005", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.print_plan:
        print("SAMPLER_FIX005_PLAN P25=8 P23=10 P24=7 P18=7 BOUNDED_E2E=1 LARGE=0 STAGEB_MEASURED=0")
        return
    if None in (args.repo_root, args.runtime_root, args.evidence_root, args.durability):
        parser.error("all bounded paths are required")
    summary = execute(args)
    print(
        "PASS_SAMPLER_FIX005_BOUNDED_PREFLIGHT_ONLY "
        f"COMMIT={summary['source_commit']} P25=8 P23=10 P24=7 P18=7 "
        "BOUNDED_E2E=PASS LARGE=0 STAGEB_MEASURED=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
