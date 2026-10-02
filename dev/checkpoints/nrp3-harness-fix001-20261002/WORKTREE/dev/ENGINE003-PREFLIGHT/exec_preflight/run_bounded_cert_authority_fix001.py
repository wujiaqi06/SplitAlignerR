#!/usr/bin/env python3
"""Recertify the bounded engineering-only memory ceiling; never run Stage-B."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import ExecutionAuthority, FrozenAssets, write_canonical_json  # noqa: E402
import run_branch_fix001_preflight as branch_fix  # noqa: E402
import run_sampler_fix005_preflight as fix5  # noqa: E402


PARENT_COMMIT = "788cda41bc6a2e8f9082471f0b59747ce126fe79"
PARENT_TREE = "f1aa8ea833cb270f5631ede2b1ffc8284a74ab28"
PARENT_PARENT = "cce7ce6c5ab17de1e766fa9efba7c66a73452c39"
CONTROLLER_SHA256 = "841343124265a3934abee19856cf9218190968a6e309b5d6e28d5d9ccc844c51"
DURABILITY_SHA256 = "1c6378e804626174053dfc550795beed46356126b0d31f63992a353ad0411bb4"
OLD_CEILING = 67_108_864
NEW_CEILING = 134_217_728

AUTHORITY_REL = "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_exec_fix002/BOUNDED_AUTHORITY.json"
DESCRIPTOR_REL = "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_exec_fix002/bounded_129x7x4.json"
GENERATOR_REL = "dev/ENGINE003-PREFLIGHT/reference/build_stage_b_exec_fix002_fixture.py"
RUNNER_REL = "dev/ENGINE003-PREFLIGHT/exec_preflight/run_bounded_cert_authority_fix001.py"
CHECKER_REL = "dev/ENGINE003-PREFLIGHT/independent/check_bounded_cert_authority_fix001.py"
CHANGED_PATHS = {AUTHORITY_REL, GENERATOR_REL, RUNNER_REL, CHECKER_REL}

PRODUCTION_FROZEN_PATHS = (
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_worker.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_orchestrator.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_authorization.py",
    "dev/ENGINE003-PREFLIGHT/reference/capture_pretiming_resources.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/fix001_contract.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py",
    "dev/ENGINE003-PREFLIGHT/stage_b/build_stage_b_prereg001.py",
    "dev/ENGINE003-PREFLIGHT/fixtures/stage_a_v3_descriptors/authority_shape.json",
    "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_prereg001/stress_projected_100000x4913.json",
    "dev/ENGINE003-PREFLIGHT/fixtures/stage_b_prereg001/stress_all_layouts_over4gib_102500x4913.json",
    "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_WORKLOAD_LEDGER.tsv",
    "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_CANDIDATE_PROJECTIONS.tsv",
    "dev/ENGINE003-PREFLIGHT/evidence/STAGEB_PREREG001/STAGEB_EXECUTION_SCHEDULE.tsv",
    "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_WORKLOAD_SCHEDULE_SELECTION_CONTRACT.tsv",
    "dev/ENGINE003-PREFLIGHT/stage_b/STAGEB_WARMUP_SCHEDULE.tsv",
    DESCRIPTOR_REL,
)

HISTORY_ROWS = (
    ("SAMPLER_FIX001", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX001_Review_Package_20260812_JST/02_BOUNDED_EVIDENCE/BOUNDED_DISTINCT_CAPTURE_E2E.json", 66_699_264),
    ("SAMPLER_FIX002", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX002_Review_Package_20260812_JST/02_BOUNDED_EVIDENCE/BOUNDED_DISTINCT_CAPTURE_E2E.json", 65_372_160),
    ("SAMPLER_FIX003", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX003_Review_Package_20260812_JST/02_BOUNDED_EVIDENCE/BOUNDED_DISTINCT_CAPTURE_E2E.json", 65_863_680),
    ("SAMPLER_FIX004", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX004_Review_Package_20260812_JST/02_BOUNDED_EVIDENCE/BOUNDED_DISTINCT_CAPTURE_E2E.json", 58_425_344),
    ("SAMPLER_FIX005_PRELIMINARY_1", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX005_STOP_Review_Package_20260812_JST/03_PRELIMINARY_ATTEMPTS/SAMPLER_FIX005_EVIDENCE_2976e3c/BOUNDED_REPLAY/worker.result.sampler.json", 67_551_232),
    ("SAMPLER_FIX005_PRELIMINARY_2", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX005_STOP_Review_Package_20260812_JST/03_PRELIMINARY_ATTEMPTS/SAMPLER_FIX005_EVIDENCE_2976e3c_RERUN1/BOUNDED_REPLAY/worker.result.sampler.json", 64_208_896),
    ("SAMPLER_FIX005_FINAL_1", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX005_STOP_Review_Package_20260812_JST/02_FINAL_ATTEMPTS/SAMPLER_FIX005_EVIDENCE_788cda4/BOUNDED_REPLAY/worker.result.sampler.json", 67_665_920),
    ("SAMPLER_FIX005_FINAL_2", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX005_STOP_Review_Package_20260812_JST/02_FINAL_ATTEMPTS/SAMPLER_FIX005_EVIDENCE_788cda4_RERUN1/BOUNDED_REPLAY/worker.result.sampler.json", 71_270_400),
    ("SAMPLER_FIX005_FINAL_3", "SplitAlignerR_ENGINE003_STAGEB_SAMPLER_FIX005_STOP_Review_Package_20260812_JST/02_FINAL_ATTEMPTS/SAMPLER_FIX005_EVIDENCE_788cda4_RERUN2_MALLOC/BOUNDED_REPLAY/worker.result.sampler.json", 71_811_072),
)


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
        raise AssertionError(f"git:{args}:{process.returncode}:{process.stderr!r}")
    return process.stdout


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode("utf-8").strip()


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def source_checkpoint(repo: Path) -> dict[str, Any]:
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
        "full_status_stdout": git(repo, "status", "--porcelain=v1", "--untracked-files=all").decode().strip(),
        "protected_status_stdout": git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--", "dev/ENGINE003-PREFLIGHT", "R", "src").decode().strip(),
    }


def root_identity(path: Path, label: str) -> dict[str, Any]:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise AssertionError(f"{label} ordinary directory")
    if any(path.iterdir()):
        raise AssertionError(f"{label} initially empty")
    return {
        "path": str(path), "st_dev": observed.st_dev, "st_ino": observed.st_ino,
        "mode": stat.S_IMODE(observed.st_mode), "entry_count_before": 0,
    }


def assert_source(repo: Path) -> tuple[str, str, dict[str, Any]]:
    pre = source_checkpoint(repo)
    commit, tree = pre["head"], pre["tree"]
    if git_text(repo, "show", "-s", "--format=%P", commit).split() != [PARENT_COMMIT]:
        raise AssertionError("ordinary child")
    if git_text(repo, "rev-parse", f"{PARENT_COMMIT}^{{tree}}") != PARENT_TREE:
        raise AssertionError("parent tree")
    if git_text(repo, "show", "-s", "--format=%P", PARENT_COMMIT) != PARENT_PARENT:
        raise AssertionError("parent ancestry")
    if any(pre[key] for key in ("branch_stdout", "full_status_stdout", "protected_status_stdout")):
        raise AssertionError("source detached clean")
    rows = git(repo, "diff-tree", "--no-commit-id", "--name-status", "-r", PARENT_COMMIT, commit).decode().splitlines()
    changed = {row.split("\t", 1)[1] for row in rows}
    if changed != CHANGED_PATHS:
        raise AssertionError(f"changed scope:{changed}")
    for relative in CHANGED_PATHS:
        if git(repo, "show", f"{commit}:{relative}") != (repo / relative).read_bytes():
            raise AssertionError(f"Git/worktree bytes:{relative}")
    return commit, tree, pre


def json_value(raw: bytes) -> Any:
    return json.loads(raw.decode("ascii"), parse_float=lambda value: (_ for _ in ()).throw(AssertionError(value)))


def generated_authority_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def authority_and_generator_proof(repo: Path, commit: str) -> dict[str, Any]:
    parent_authority_raw = git(repo, "show", f"{PARENT_COMMIT}:{AUTHORITY_REL}")
    child_authority_raw = git(repo, "show", f"{commit}:{AUTHORITY_REL}")
    parent_generator_raw = git(repo, "show", f"{PARENT_COMMIT}:{GENERATOR_REL}")
    child_generator_raw = git(repo, "show", f"{commit}:{GENERATOR_REL}")
    if parent_authority_raw.replace(b"67108864", b"134217728") != child_authority_raw:
        raise AssertionError("authority exact one-field byte change")
    if parent_generator_raw.replace(b"67_108_864", b"134_217_728") != child_generator_raw:
        raise AssertionError("generator exact literal change")
    parent_value = json_value(parent_authority_raw)
    child_value = json_value(child_authority_raw)
    if parent_value["memory_admission_required_bytes"] != OLD_CEILING:
        raise AssertionError("old ceiling")
    if child_value["memory_admission_required_bytes"] != NEW_CEILING:
        raise AssertionError("new ceiling")
    if child_value["authority_scope"] != "BOUNDED_ENGINEERING_CERTIFICATION_ONLY":
        raise AssertionError("authority scope")
    parent_without = dict(parent_value)
    child_without = dict(child_value)
    parent_without.pop("memory_admission_required_bytes")
    child_without.pop("memory_admission_required_bytes")
    if parent_without != child_without:
        raise AssertionError("authority collateral field change")

    generator = repo / GENERATOR_REL
    spec = importlib.util.spec_from_file_location("bounded_cert_generator", generator)
    if spec is None or spec.loader is None:
        raise AssertionError("generator import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated_descriptor, generated_authority = module.build(
        repo / "dev/ENGINE003-PREFLIGHT/fixtures/stage_a_v3_descriptors/authority_shape.json"
    )
    committed_descriptor = git(repo, "show", f"{commit}:{DESCRIPTOR_REL}")
    if generated_descriptor != committed_descriptor:
        raise AssertionError("regenerated descriptor bytes")
    if generated_authority_bytes(generated_authority) != child_authority_raw:
        raise AssertionError("regenerated authority bytes")
    if committed_descriptor != git(repo, "show", f"{PARENT_COMMIT}:{DESCRIPTOR_REL}"):
        raise AssertionError("bounded descriptor changed")
    return {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001AuthorityProof/v1",
        "status": "PASS", "authority_scope": child_value["authority_scope"],
        "old_ceiling_bytes": OLD_CEILING, "new_ceiling_bytes": NEW_CEILING,
        "authority_parent_sha256": sha256(parent_authority_raw),
        "authority_child_sha256": sha256(child_authority_raw),
        "generator_parent_sha256": sha256(parent_generator_raw),
        "generator_child_sha256": sha256(child_generator_raw),
        "descriptor_sha256": sha256(committed_descriptor),
        "authority_only_memory_field_changed": True,
        "generator_only_ceiling_literal_changed": True,
        "regenerated_descriptor_exact": True,
        "regenerated_authority_exact": True,
    }


def noninterference_proof(repo: Path, commit: str) -> dict[str, Any]:
    rows = []
    for relative in PRODUCTION_FROZEN_PATHS:
        parent = git(repo, "show", f"{PARENT_COMMIT}:{relative}")
        child = git(repo, "show", f"{commit}:{relative}")
        if parent != child:
            raise AssertionError(f"production drift:{relative}")
        rows.append({"path": relative, "sha256": sha256(child), "byte_identical_to_parent": True})
    controller = next(row for row in rows if row["path"].endswith("stage_b_controller.py"))
    if controller["sha256"] != CONTROLLER_SHA256:
        raise AssertionError("controller frozen SHA")
    runtime_source = git(repo, "show", f"{commit}:dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py").decode()
    tree = ast.parse(runtime_source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    consumers = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "bounded_authority"
        ):
            continue
        owner = node
        while owner in parents and not isinstance(owner, ast.FunctionDef):
            owner = parents[owner]
        consumers.append(owner.name)
    if sorted(consumers) != ["make_bounded_request", "prelaunch_guard"]:
        raise AssertionError(f"bounded authority consumers:{consumers}")
    return {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001Noninterference/v1",
        "status": "PASS", "rows": rows,
        "production_frozen_file_count": len(rows),
        "large_workload_descriptor_count": 3,
        "controller_sha256": CONTROLLER_SHA256,
        "bounded_authority_consumers": sorted(consumers),
        "large_request_reads_bounded_ceiling": False,
        "production_execution_source_changed": False,
    }


def historical_calibration(root: Path) -> dict[str, Any]:
    rows = []
    for row_id, relative, expected in HISTORY_ROWS:
        path = root / relative
        observed = os.lstat(path)
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise AssertionError(f"historical regular:{row_id}")
        raw = path.read_bytes()
        value = json_value(raw)
        peak = value.get("sampler_diagnostic", value).get("maximum_bytes")
        root_peak = value.get("sampler_diagnostic", value).get("maximum_root_bytes")
        if peak != expected:
            raise AssertionError(f"historical peak:{row_id}:{peak}")
        rows.append({
            "row_id": row_id, "source_relative_path": relative,
            "source_sha256": sha256(raw), "whole_tree_peak_bytes": peak,
            "root_process_peak_bytes": root_peak,
        })
    maximum = max(row["whole_tree_peak_bytes"] for row in rows)
    if maximum != 71_811_072 or len(rows) != 9:
        raise AssertionError("historical ledger maximum/cardinality")
    value = {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001Calibration/v1",
        "status": "PASS", "row_count": 9, "rows": rows,
        "old_ceiling_bytes": OLD_CEILING, "observed_maximum_bytes": maximum,
        "new_ceiling_bytes": NEW_CEILING,
        "new_ceiling_headroom_bytes": NEW_CEILING - maximum,
        "selection_rule": "NEXT_POWER_OF_TWO_STRICTLY_ABOVE_OBSERVED_MAXIMUM",
        "pass_attempt_not_selected": True,
    }
    if value["new_ceiling_headroom_bytes"] != 62_406_656:
        raise AssertionError("headroom")
    return value


def evidence_hashes(evidence: Path) -> dict[str, str]:
    return {
        path.relative_to(evidence).as_posix(): file_sha256(path)
        for path in sorted(evidence.rglob("*"))
        if path.is_file() and path.name != "BOUNDED_CERT_AUTHORITY_FIX001_SUMMARY.json"
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo_input = lexical_absolute(args.repo_root)
    if stat.S_ISLNK(os.lstat(repo_input).st_mode):
        raise AssertionError("repo symlink")
    repo = repo_input.resolve(strict=True)
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
        raise AssertionError("durability")
    authority_proof = authority_and_generator_proof(repo, commit)
    write_canonical_json(evidence / "AUTHORITY_REGENERATION_PROOF.json", authority_proof)
    noninterference = noninterference_proof(repo, commit)
    write_canonical_json(evidence / "PRODUCTION_NONINTERFERENCE.json", noninterference)
    calibration = historical_calibration(lexical_absolute(args.history_root).resolve(strict=True))
    write_canonical_json(evidence / "HISTORICAL_CALIBRATION_LEDGER.json", calibration)

    p25 = fix5.p25_corpus(evidence)
    hard_gate = branch_fix.whole_tree_hard_gate_corpus(evidence)
    branch_path, series_path, branch, series, branch_sha, series_sha = branch_fix.capture_pair(runtime, evidence)
    e2e = branch_fix.bounded_e2e(
        authority, assets, repo, runtime, evidence, series_path, branch_path,
        durability_path, series, branch, durability, branch_sha, series_sha,
    )
    sampler = e2e["sampler_diagnostic"]
    whole_peak = sampler["maximum_bytes"]
    root_peak = sampler["maximum_root_bytes"]
    if not (0 <= root_peak <= whole_peak < NEW_CEILING):
        raise AssertionError(f"recertification peak:{root_peak}:{whole_peak}")
    result = {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001Result/v1",
        "status": "PASS", "official_bounded_e2e_invocation_count": 1,
        "official_bounded_worker_launch_count": 1,
        "memory_admission_required_bytes": NEW_CEILING,
        "controller_process_tree_peak_rss_bytes": whole_peak,
        "worker_root_peak_rss_bytes": root_peak,
        "whole_tree_margin_bytes": NEW_CEILING - whole_peak,
        "controller_sampler_pass": e2e["controller_sampler_pass"],
        "logical_correctness_pass": e2e["logical_correctness_pass"],
        "resource_hard_gate_pass": e2e["resource_hard_gate_pass"],
        "bounded_store_cleanup_pass": e2e["bounded_store_cleanup_pass"],
        "external_process_table_call_count": sampler["process_table_mechanism"]["external_process_table_call_count"],
        "stage_b_measured_timing": e2e["stage_b_measured_timing"],
        "no_retry_or_pass_selection": True,
    }
    if not all(result[key] is True for key in (
        "controller_sampler_pass", "logical_correctness_pass",
        "resource_hard_gate_pass", "bounded_store_cleanup_pass",
        "no_retry_or_pass_selection",
    )):
        raise AssertionError("official bounded result")
    if result["external_process_table_call_count"] != 0 or result["stage_b_measured_timing"] is not False:
        raise AssertionError("bounded authority boundary")
    write_canonical_json(evidence / "BOUNDED_RECERTIFICATION_RESULT.json", result)

    if any(runtime.iterdir()):
        raise AssertionError("runtime not empty")
    post = source_checkpoint(repo)
    if post != pre:
        raise AssertionError("source changed")
    source = {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001SourceIdentity/v1",
        "status": "PASS", "source_commit": commit, "source_tree": tree,
        "direct_parent": PARENT_COMMIT, "pre": pre, "post": post,
        "runtime_root": runtime_id, "evidence_root": evidence_id,
        "changed_paths": sorted(CHANGED_PATHS),
    }
    write_canonical_json(evidence / "SOURCE_IDENTITY.json", source)
    zero = {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001ZeroBoundary/v1",
        "status": "PASS_BOUNDED_ENGINEERING_CERTIFICATION_ONLY",
        "official_bounded_e2e_invocation_count": 1,
        "bounded_e2e_worker_launch_count": 1,
        "authorized_stage_b_worker_launch_count": 0,
        "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "over_2gib_store_count": 0, "over_4gib_store_count": 0,
        "backend_selection_count": 0, "decision_engine_invocation_count": 0,
        "authorized_to_run_artifact_count": 0,
        "attempt003_resume_count": 0, "attempt003_root_write_count": 0,
        "external_process_table_call_count": 0,
        "runtime_root_final_entry_count": 0,
        "physical_execution_authorized": False,
    }
    write_canonical_json(evidence / "ZERO_BOUNDARY.json", zero)
    checker_sha = sha256(git(repo, "show", f"{commit}:{CHECKER_REL}"))
    summary = {
        "schema": "SplitAlignerR/ENGINE003BoundedCertAuthorityFix001Summary/v1",
        "status": "PASS_BOUNDED_CERT_AUTHORITY_FIX001_ENGINEERING_ONLY",
        "source_commit": commit, "source_tree": tree, "direct_parent": PARENT_COMMIT,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "checker_sha256": checker_sha,
        "historical_calibration_row_count": calibration["row_count"],
        "historical_maximum_bytes": calibration["observed_maximum_bytes"],
        "old_ceiling_bytes": OLD_CEILING, "new_ceiling_bytes": NEW_CEILING,
        "new_ceiling_headroom_from_history_bytes": calibration["new_ceiling_headroom_bytes"],
        "p25_case_count": p25["case_count"],
        "whole_tree_hard_gate_pass": hard_gate["status"] == "PASS",
        "official_bounded_e2e_invocation_count": 1,
        "official_bounded_worker_launch_count": 1,
        "official_bounded_whole_tree_peak_bytes": whole_peak,
        "official_bounded_root_peak_bytes": root_peak,
        "official_bounded_margin_bytes": NEW_CEILING - whole_peak,
        "production_noninterference_pass": noninterference["status"] == "PASS",
        "regeneration_pass": authority_proof["status"] == "PASS",
        "stage_b_measured_clock_count": 0,
        "mandatory_large_worker_launch_count": 0,
        "decision_engine_invocation_count": 0,
        "runtime_root_final_entry_count": 0,
        "claim_ceiling": "BOUNDED_ENGINEERING_CERTIFICATION_ONLY_NO_STAGEB_AUTHORIZATION_OR_PERFORMANCE_CLAIM",
        "evidence_file_sha256": evidence_hashes(evidence),
    }
    write_canonical_json(evidence / "BOUNDED_CERT_AUTHORITY_FIX001_SUMMARY.json", summary)
    return summary


def self_test(repo: Path) -> None:
    commit = git_text(repo, "rev-parse", "HEAD")
    proof = authority_and_generator_proof(repo, commit)
    if proof["new_ceiling_bytes"] != NEW_CEILING:
        raise AssertionError("self-test authority")
    with tempfile.TemporaryDirectory(prefix="bounded-cert-authority-selftest-") as value:
        evidence = Path(value)
        p25 = fix5.p25_corpus(evidence)
        hard = branch_fix.whole_tree_hard_gate_corpus(evidence)
        if p25["case_count"] != 8 or hard["decision_ledger_eligible"] is not False:
            raise AssertionError("self-test corpus")
    print("PASS_BOUNDED_CERT_AUTHORITY_FIX001_RUNNER_SELF_TEST P25=8 HARD_GATE=1 WORKERS=0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--durability", type=Path)
    parser.add_argument("--history-root", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--self-test", action="store_true")
    selector.add_argument("--print-plan", action="store_true")
    selector.add_argument("--execute-exactly-one-bounded-e2e", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.repo_root is None:
            parser.error("--repo-root required for self-test")
        self_test(lexical_absolute(args.repo_root).resolve(strict=True))
        return
    if args.print_plan:
        print("BOUNDED_CERT_AUTHORITY_FIX001_PLAN HISTORY=9 P25=8 HARD_GATE=1 BOUNDED_E2E=1 RETRY=0 LARGE=0 STAGEB_CLOCK=0")
        return
    if None in (args.repo_root, args.runtime_root, args.evidence_root, args.durability, args.history_root):
        parser.error("all execution inputs are required")
    summary = execute(args)
    print(
        "PASS_BOUNDED_CERT_AUTHORITY_FIX001_ENGINEERING_ONLY "
        f"COMMIT={summary['source_commit']} HISTORY=9 P25=8 HARD_GATE=PASS "
        f"BOUNDED_E2E=1 PEAK={summary['official_bounded_whole_tree_peak_bytes']} "
        f"MARGIN={summary['official_bounded_margin_bytes']} LARGE=0 STAGEB_CLOCK=0 DECISION=0"
    )


if __name__ == "__main__":
    main()
