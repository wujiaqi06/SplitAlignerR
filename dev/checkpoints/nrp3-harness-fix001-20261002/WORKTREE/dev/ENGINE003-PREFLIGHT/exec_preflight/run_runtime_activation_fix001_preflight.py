#!/usr/bin/env python3
"""Zero-execution evidence producer for RUNTIME-ACTIVATION-FIX001.

This runner never imports the controller or worker and never launches a child
process.  It proves the four-field LARGE activation boundary with the frozen
authorization machinery and stops at ``prelaunch_guard``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from fix001_contract import (
    WORKLOADS,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_load,
)
from stage_b_authorization import make_authorization_artifact
from stage_b_orchestrator import (
    adaptive_execution_protocol,
    validate_adaptive_execution_protocol,
)
from stage_b_runtime_contract import (
    EXTERNAL_LARGE_ACTIVATION_FIELDS,
    LEGACY_LARGE_DRY_ACTIVATION,
    make_large_request,
    prelaunch_guard,
)


PARENT_COMMIT = "8b0f86b669c74b29fee0e182e52f028958f0d6d2"
PARENT_TREE = "fb4a0bddc2271d88ed223636ec6d1925e0f74345"
PARENT_PARENT = "3cf4a5ec4b868413af50b08f98d453da1a6d08a4"
SERIES_INPUT_SHA256 = "cb662b14e3208a08805a3ac244213899b6017177ec903b5ac50e0e8154043f47"
BRANCH_INPUT_SHA256 = "4942840d5bfe5df8cee558b618da6eae0a5df8ab61ce5b0e711b9dc6823c8607"
DURABILITY_INPUT_SHA256 = "f5781231e4ba0b522c4c888fb98ccb98eeeb9703a10eb80e17a7c1cc681b2086"
SCRATCH_AUTHORIZATION_ID = (
    "ENGINE003_STAGEB_RUNTIME_ACTIVATION_FIX001_SCRATCH_PREWORKER_ONLY"
)
CHANGED_PATHS = (
    "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py",
    "dev/ENGINE003-PREFLIGHT/exec_preflight/run_runtime_activation_fix001_preflight.py",
    "dev/ENGINE003-PREFLIGHT/independent/check_runtime_activation_fix001.py",
)
MUTATION_CASE_IDS = (
    "VALID_FOUR_FIELD",
    "EXTRA_STATE_AUTHORIZED_TO_RUN",
    "MISSING_AUTHORIZATION_PATH",
    "MISSING_AUTHORIZATION_ID",
    "WRONG_AUTHORIZATION_SHA",
    "ACTIVATION_PHYSICAL_FALSE",
    "ARTIFACT_STATE_NOT_AUTHORIZED",
    "ARTIFACT_PHYSICAL_FALSE",
    "LEGACY_EXACT_DRY_SENTINEL",
    "MALFORMED_FIVE_FIELD_NOT_DRY",
)
EXPECTED_MUTATION_RESULTS = {
    "VALID_FOUR_FIELD": "PASS",
    "EXTRA_STATE_AUTHORIZED_TO_RUN": "SB_STOP_ACTIVATION:field_set",
    "MISSING_AUTHORIZATION_PATH": "SB_STOP_ACTIVATION:field_set",
    "MISSING_AUTHORIZATION_ID": "SB_STOP_ACTIVATION:field_set",
    "WRONG_AUTHORIZATION_SHA": "SB_STOP_AUTHORIZATION_HASH:exact_bytes_sha256",
    "ACTIVATION_PHYSICAL_FALSE": "SB_STOP_AUTHORIZATION_OBJECT:state_id_scope",
    "ARTIFACT_STATE_NOT_AUTHORIZED": "SB_STOP_AUTHORIZATION_OBJECT:state_id_scope",
    "ARTIFACT_PHYSICAL_FALSE": "SB_STOP_AUTHORIZATION_OBJECT:state_id_scope",
    "LEGACY_EXACT_DRY_SENTINEL": (
        "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED:"
        "ALL_PRELAUNCH_DECISIONS_COMPLETE;WORKER_LAUNCH=0;PHYSICAL_ALLOCATION=0"
    ),
    "MALFORMED_FIVE_FIELD_NOT_DRY": "SB_STOP_ACTIVATION:field_set",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def git(repo: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    process = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True, text=True, check=False, env=environment,
    )
    if process.returncode:
        raise RuntimeError(
            f"git {' '.join(arguments)} rc={process.returncode}:"
            f"{process.stderr.strip()}"
        )
    return process.stdout


def git_bytes(repo: Path, object_name: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), "show", object_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if process.returncode:
        raise RuntimeError(f"git show {object_name}: {process.stderr.decode().strip()}")
    return process.stdout


def source_identity(repo: Path, commit: str, tree: str, parent: str) -> dict[str, Any]:
    head = git(repo, "rev-parse", "HEAD").strip()
    observed_tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").strip().split()
    branch_process = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    require(branch_process.returncode in (0, 1), "symbolic-ref status")
    require(branch_process.stderr == "", "symbolic-ref stderr")
    branch = branch_process.stdout.strip()
    full_status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    protected = git(
        repo, "status", "--porcelain=v1", "--untracked-files=all", "--",
        "dev/ENGINE003-PREFLIGHT",
    )
    require(head == commit, "source commit")
    require(observed_tree == tree, "source tree")
    require(parents == [commit, parent], "ordinary child parent")
    require(branch == "", "source must be detached")
    require(full_status == "", "full source dirty")
    require(protected == "", "protected source dirty")
    require(git(repo, "rev-parse", f"{parent}^{{tree}}").strip() == PARENT_TREE, "parent tree")
    require(git(repo, "rev-parse", f"{parent}^").strip() == PARENT_PARENT, "parent parent")
    return {
        "commit": head,
        "tree": observed_tree,
        "parent": parent,
        "parent_tree": PARENT_TREE,
        "parent_parent": PARENT_PARENT,
        "commit_object_type": git(repo, "cat-file", "-t", head).strip(),
        "direct_parents": parents[1:],
        "detached": True,
        "full_clean_including_untracked": True,
        "protected_clean_including_untracked": True,
    }


def read_exact_canonical(path: Path, expected_sha256: str) -> dict[str, Any]:
    observed = os.lstat(path)
    require(stat.S_ISREG(observed.st_mode) and not stat.S_ISLNK(observed.st_mode), f"input type:{path}")
    raw = path.read_bytes()
    require(sha256(raw) == expected_sha256, f"input sha256:{path}")
    value = strict_json_load(path)
    require(isinstance(value, dict), f"input object:{path}")
    require(raw == canonical_json_bytes(value), f"input canonical:{path}")
    return value


def exclusive_json(path: Path, value: Mapping[str, Any]) -> str:
    raw = canonical_json_bytes(dict(value))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise RuntimeError(f"short write:{path}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256(raw)


def derive_resource(base: Mapping[str, Any], destination: Path, role: str) -> dict[str, Any]:
    value = copy.deepcopy(dict(base))
    value["destination"] = str(destination.resolve())
    value["capture_time"] = f"SCRATCH_DERIVED_PREWORKER_{role}"
    return value


def host_profile(resource: Mapping[str, Any]) -> dict[str, Any]:
    return {key: resource[key] for key in (
        "host_id", "platform_system", "platform_release", "platform_machine",
        "os_build", "filesystem", "destination_device_id",
        "target_volume_device", "target_volume_mount_point",
    )}


def guard_result(
        authority: ExecutionAuthority, assets: FrozenAssets,
        request: Mapping[str, Any], runtime_root: Path,
        series: Mapping[str, Any], durability: Mapping[str, Any],
        branch: Mapping[str, Any]) -> str:
    try:
        result = prelaunch_guard(
            authority, assets, request, runtime_root, series, durability, branch,
        )
        require(
            result["status"] == "PRELAUNCH_PASS_LARGE_EXTERNALLY_AUTHORIZED",
            "unexpected guard pass status",
        )
        return "PASS"
    except StopSignal as error:
        return str(error)


def request_with_activation(request: Mapping[str, Any], activation: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(request))
    value["activation"] = dict(activation)
    return value


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve(strict=True)
    evidence = args.evidence_root
    require(not evidence.is_symlink() and evidence.is_dir(), "evidence root")
    require(list(evidence.iterdir()) == [], "evidence root must start empty")
    require(not os.path.lexists(args.scratch_runtime_root), "scratch runtime must remain absent")
    require(args.scratch_runtime_root not in args.evidence_root.parents, "root nesting")
    require(args.evidence_root not in args.scratch_runtime_root.parents, "root nesting")
    identity = source_identity(repo, args.expected_commit, args.expected_tree, args.expected_parent)
    authority = ExecutionAuthority(repo, args.expected_commit, args.expected_tree)
    assets = FrozenAssets(authority)

    series_base = read_exact_canonical(args.series_resource, SERIES_INPUT_SHA256)
    branch_base = read_exact_canonical(args.branch_resource, BRANCH_INPUT_SHA256)
    durability = read_exact_canonical(args.durability, DURABILITY_INPUT_SHA256)
    series = derive_resource(series_base, args.scratch_runtime_root, "CANDIDATE_SERIES")
    branch = derive_resource(branch_base, args.scratch_runtime_root, "WORKLOAD_BRANCH")
    series_path = evidence / "SCRATCH_RESOURCE_SERIES.json"
    branch_path = evidence / "SCRATCH_RESOURCE_BRANCH.json"
    series_sha = exclusive_json(series_path, series)
    branch_sha = exclusive_json(branch_path, branch)

    artifact = make_authorization_artifact(
        assets, args.expected_commit, args.expected_tree, host_profile(series),
        sha256(canonical_json_bytes(durability)), args.evidence_root,
        args.scratch_runtime_root, SCRATCH_AUTHORIZATION_ID,
        physical_allocation_authorized=True,
    )
    artifact_path = evidence / "SCRATCH_PREWORKER_AUTHORIZED_TO_RUN.json"
    artifact_sha = exclusive_json(artifact_path, artifact)
    activation = {
        "authorization_artifact_path": str(artifact_path.resolve()),
        "authorization_id": SCRATCH_AUTHORIZATION_ID,
        "authorization_sha256": artifact_sha,
        "physical_allocation_authorized": True,
    }
    require(set(activation) == EXTERNAL_LARGE_ACTIVATION_FIELDS, "four activation fields")

    protocol = adaptive_execution_protocol(authority, assets, activation)
    require(validate_adaptive_execution_protocol(authority, assets, protocol) == protocol, "P26 protocol")
    protocol_path = evidence / "P26_FOUR_FIELD_PROTOCOL.json"
    protocol_sha = exclusive_json(protocol_path, protocol)

    workload = WORKLOADS[0]
    warmup = next(
        row for row in assets.warmup_rows(workload, "PASS")
        if row["backend"] == "COLUMN_MAJOR_DISK"
    )
    runtime_target = args.scratch_runtime_root / "never_created_column_major_target"
    request = make_large_request(
        authority, assets, series, durability, workload, "COLUMN_MAJOR_DISK",
        runtime_target, warmup, "UNTIMED_WARMUP", args.evidence_root,
        activation=activation, branch_resource=branch,
    )
    request_path = evidence / "REAL_LARGE_REQUEST.json"
    request_sha = exclusive_json(request_path, request)
    require(
        guard_result(authority, assets, request, args.scratch_runtime_root, series, durability, branch)
        == "PASS", "real preworker handshake",
    )

    bad_state = copy.deepcopy(artifact)
    bad_state["state"] = "NOT_AUTHORIZED_PREFLIGHT_ARTIFACT"
    bad_state_path = evidence / "SCRATCH_BAD_ARTIFACT_STATE.json"
    bad_state_sha = exclusive_json(bad_state_path, bad_state)
    bad_physical = copy.deepcopy(artifact)
    bad_physical["physical_allocation_authorized"] = False
    bad_physical_path = evidence / "SCRATCH_BAD_ARTIFACT_PHYSICAL.json"
    bad_physical_sha = exclusive_json(bad_physical_path, bad_physical)

    mutations: dict[str, dict[str, Any]] = {}
    mutation_activations: dict[str, dict[str, Any]] = {}
    mutation_activations["VALID_FOUR_FIELD"] = dict(activation)
    extra = dict(activation)
    extra["state"] = "AUTHORIZED_TO_RUN"
    mutation_activations["EXTRA_STATE_AUTHORIZED_TO_RUN"] = extra
    missing_path = dict(activation)
    del missing_path["authorization_artifact_path"]
    mutation_activations["MISSING_AUTHORIZATION_PATH"] = missing_path
    missing_id = dict(activation)
    del missing_id["authorization_id"]
    mutation_activations["MISSING_AUTHORIZATION_ID"] = missing_id
    wrong_sha = dict(activation)
    wrong_sha["authorization_sha256"] = "f" * 64
    mutation_activations["WRONG_AUTHORIZATION_SHA"] = wrong_sha
    activation_false = dict(activation)
    activation_false["physical_allocation_authorized"] = False
    mutation_activations["ACTIVATION_PHYSICAL_FALSE"] = activation_false
    state_activation = dict(activation)
    state_activation["authorization_artifact_path"] = str(bad_state_path.resolve())
    state_activation["authorization_sha256"] = bad_state_sha
    mutation_activations["ARTIFACT_STATE_NOT_AUTHORIZED"] = state_activation
    physical_activation = dict(activation)
    physical_activation["authorization_artifact_path"] = str(bad_physical_path.resolve())
    physical_activation["authorization_sha256"] = bad_physical_sha
    mutation_activations["ARTIFACT_PHYSICAL_FALSE"] = physical_activation
    mutation_activations["LEGACY_EXACT_DRY_SENTINEL"] = dict(LEGACY_LARGE_DRY_ACTIVATION)
    malformed = dict(LEGACY_LARGE_DRY_ACTIVATION)
    malformed["authorization_id"] = "NOT_THE_EXACT_DRY_SENTINEL"
    mutation_activations["MALFORMED_FIVE_FIELD_NOT_DRY"] = malformed

    for case_id in MUTATION_CASE_IDS:
        candidate = request_with_activation(request, mutation_activations[case_id])
        observed = guard_result(
            authority, assets, candidate, args.scratch_runtime_root,
            series, durability, branch,
        )
        expected = EXPECTED_MUTATION_RESULTS[case_id]
        require(observed == expected, f"mutation {case_id}:{observed}!={expected}")
        mutations[case_id] = {
            "case_id": case_id,
            "activation_field_names": sorted(mutation_activations[case_id]),
            "activation_field_count": len(mutation_activations[case_id]),
            "expected": expected,
            "observed": observed,
            "pass": observed == expected,
        }
    mutation_value = {
        "schema": "SplitAlignerR/RuntimeActivationFix001MutationCorpus/v1",
        "status": "PASS_EXACT_TEN_CASES_ZERO_EXECUTION",
        "case_order": list(MUTATION_CASE_IDS),
        "cases": [mutations[key] for key in MUTATION_CASE_IDS],
    }
    mutation_path = evidence / "ACTIVATION_MUTATION_CORPUS.json"
    mutation_sha = exclusive_json(mutation_path, mutation_value)

    wrong_series = copy.deepcopy(series)
    wrong_series["capture_time"] = "WRONG_SERIES_BYTES"
    wrong_branch = copy.deepcopy(branch)
    wrong_branch["capture_time"] = "WRONG_BRANCH_BYTES"
    host_branch = copy.deepcopy(branch)
    host_branch["host_id"] = "HOST_VOLUME_MISMATCH"
    host_request = copy.deepcopy(request)
    host_request["workload_branch_resource_capture_sha256"] = sha256(
        canonical_json_bytes(host_branch)
    )
    regression_cases = [
        {
            "case_id": "VALID_DISTINCT_SERIES_BRANCH",
            "observed": guard_result(authority, assets, request, args.scratch_runtime_root, series, durability, branch),
            "expected": "PASS",
        },
        {
            "case_id": "WRONG_SERIES_BYTES",
            "observed": guard_result(authority, assets, request, args.scratch_runtime_root, wrong_series, durability, branch),
            "expected": "SB_STOP_ADMISSION_MEMORY:resource_capture_identity",
        },
        {
            "case_id": "WRONG_BRANCH_BYTES",
            "observed": guard_result(authority, assets, request, args.scratch_runtime_root, series, durability, wrong_branch),
            "expected": "SB_STOP_ADMISSION_MEMORY:workload_branch_capture_identity",
        },
        {
            "case_id": "BRANCH_SERIES_HOST_VOLUME_MISMATCH",
            "observed": guard_result(authority, assets, host_request, args.scratch_runtime_root, series, durability, host_branch),
            "expected": "SB_STOP_CAPABILITY:branch_series_host_volume",
        },
    ]
    require(all(row["observed"] == row["expected"] for row in regression_cases), "P18-P25 cases")
    regression_value = {
        "schema": "SplitAlignerR/RuntimeActivationFix001P18P25Regression/v1",
        "status": "PASS_ZERO_ALLOCATION_REGRESSION",
        "cases": regression_cases,
        "controller_imported": False,
        "worker_imported": False,
        "sampler_invocation_count": 0,
    }
    regression_path = evidence / "P18_P25_ZERO_ALLOCATION_REGRESSION.json"
    regression_sha = exclusive_json(regression_path, regression_value)

    handshake = {
        "schema": "SplitAlignerR/RuntimeActivationFix001PreworkerHandshake/v1",
        "status": "PASS_REAL_LARGE_PREWORKER_FOUR_FIELD_HANDSHAKE",
        "source_commit": args.expected_commit,
        "source_tree": args.expected_tree,
        "workload_id": workload,
        "candidate_id": "COLUMN_MAJOR_DISK",
        "run_phase": "UNTIMED_WARMUP",
        "activation_field_names": sorted(activation),
        "activation_field_count": len(activation),
        "activation_contains_state": False,
        "artifact_state": artifact["state"],
        "artifact_physical_allocation_authorized": artifact["physical_allocation_authorized"],
        "scratch_test_only_artifact": True,
        "new_attempt_authorization": False,
        "request_sha256": request_sha,
        "protocol_sha256": protocol_sha,
        "authorization_sha256": artifact_sha,
        "series_resource_sha256": series_sha,
        "branch_resource_sha256": branch_sha,
        "guard_status": "PRELAUNCH_PASS_LARGE_EXTERNALLY_AUTHORIZED",
        "worker_launch_count": 0,
        "matrix_store_count": 0,
        "stage_b_measured_clock_count": 0,
        "mandatory_large_allocation_count": 0,
    }
    handshake_path = evidence / "REAL_LARGE_HANDSHAKE.json"
    handshake_sha = exclusive_json(handshake_path, handshake)

    zero = {
        "schema": "SplitAlignerR/RuntimeActivationFix001ZeroExecution/v1",
        "status": "PASS_ZERO_EXECUTION_BOUNDARY",
        "stage_b_worker_launch_count": 0,
        "stage_b_measured_clock_count": 0,
        "fresh_runtime_capture_count": 0,
        "bounded_probe_count": 0,
        "mandatory_large_allocation_count": 0,
        "matrix_store_count": 0,
        "backend_selection_count": 0,
        "decision_engine_count": 0,
        "attempt005_repair_or_resume_count": 0,
        "attempt005_root_write_count": 0,
        "new_attempt_authorized_to_run_artifact_count": 0,
        "scratch_preworker_authorization_artifact_count": 1,
        "p28_repair_count": 0,
        "scratch_runtime_root_created": False,
        "scratch_runtime_root_entry_count": 0,
    }
    zero_path = evidence / "ZERO_EXECUTION_LEDGER.json"
    zero_sha = exclusive_json(zero_path, zero)

    identity_path = evidence / "SOURCE_IDENTITY.json"
    identity_sha = exclusive_json(identity_path, identity)
    file_hashes = {
        path.name: sha256(path.read_bytes())
        for path in sorted(evidence.iterdir()) if path.is_file()
    }
    summary = {
        "schema": "SplitAlignerR/RuntimeActivationFix001Summary/v1",
        "status": "PASS_RUNTIME_ACTIVATION_FIX001_NOT_EXECUTION_AUTHORIZATION",
        "source_identity": identity,
        "changed_paths": list(CHANGED_PATHS),
        "changed_source_sha256": {
            path: sha256(git_bytes(repo, f"{args.expected_commit}:{path}"))
            for path in CHANGED_PATHS
        },
        "parent_runtime_contract_sha256": sha256(git_bytes(
            repo, f"{args.expected_parent}:{CHANGED_PATHS[0]}",
        )),
        "input_sha256": {
            "series_resource": SERIES_INPUT_SHA256,
            "branch_resource": BRANCH_INPUT_SHA256,
            "durability": DURABILITY_INPUT_SHA256,
        },
        "derived_resource_sha256": {"series": series_sha, "branch": branch_sha},
        "handshake_sha256": handshake_sha,
        "mutation_corpus_sha256": mutation_sha,
        "p18_p25_regression_sha256": regression_sha,
        "zero_execution_sha256": zero_sha,
        "source_identity_sha256": identity_sha,
        "evidence_file_sha256_excluding_summary": file_hashes,
        "mutation_case_count": len(MUTATION_CASE_IDS),
        "p26_protocol_activation_field_count": len(protocol["activation"]),
        "legacy_dry_stop_preserved": True,
        "p27_closed_by_source_candidate": True,
        "p28_external_launcher_repair_status": "OPEN_NOT_CHANGED",
        "claim_ceiling": "SOURCE_FIX_AND_PREWORKER_GUARD_PASS_ONLY",
    }
    summary_path = evidence / "RUNTIME_ACTIVATION_FIX001_SUMMARY.json"
    summary_sha = exclusive_json(summary_path, summary)
    require(not os.path.lexists(args.scratch_runtime_root), "scratch runtime created")
    require(source_identity(repo, args.expected_commit, args.expected_tree, args.expected_parent) == identity, "source changed")
    return {
        "status": summary["status"],
        "summary_sha256": summary_sha,
        "evidence_file_count": len(list(evidence.iterdir())),
        "mutation_case_count": len(MUTATION_CASE_IDS),
        "worker_launch_count": 0,
        "mandatory_large_allocation_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    modes = value.add_mutually_exclusive_group(required=True)
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--print-plan", action="store_true")
    value.add_argument("--repo-root", type=Path)
    value.add_argument("--expected-commit")
    value.add_argument("--expected-tree")
    value.add_argument("--expected-parent", default=PARENT_COMMIT)
    value.add_argument("--series-resource", type=Path)
    value.add_argument("--branch-resource", type=Path)
    value.add_argument("--durability", type=Path)
    value.add_argument("--scratch-runtime-root", type=Path)
    value.add_argument("--evidence-root", type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        require(set(LEGACY_LARGE_DRY_ACTIVATION) == EXTERNAL_LARGE_ACTIVATION_FIELDS | {"state"}, "legacy fields")
        require(LEGACY_LARGE_DRY_ACTIVATION["state"] == "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED", "legacy state")
        require(len(MUTATION_CASE_IDS) == 10, "mutation count")
        print("PASS_RUNTIME_ACTIVATION_FIX001_SELF_TEST PHYSICAL_EXECUTION=0")
        return 0
    if args.print_plan:
        print("PLAN_RUNTIME_ACTIVATION_FIX001 SOURCE_FILES=3 WORKERS=0 CLOCKS=0 LARGE_ALLOCATIONS=0")
        return 0
    required = (
        args.repo_root, args.expected_commit, args.expected_tree,
        args.series_resource, args.branch_resource, args.durability,
        args.scratch_runtime_root, args.evidence_root,
    )
    require(all(value is not None for value in required), "missing execute argument")
    result = execute(args)
    print(
        "PASS_RUNTIME_ACTIVATION_FIX001 "
        f"SUMMARY_SHA256={result['summary_sha256']} "
        f"CASES={result['mutation_case_count']} WORKERS=0 CLOCKS=0 LARGE_ALLOCATIONS=0"
    )
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
