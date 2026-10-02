#!/usr/bin/env python3
"""Run FIX003 bounded execution and zero-allocation large-plan preflight."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import math
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REFERENCE = ENGINE / "reference"
PILOT = ENGINE / "pilot"
import sys
for value in (HERE, REFERENCE, PILOT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from capture_pretiming_resources import capture  # noqa: E402
from fix001_contract import (  # noqa: E402
    ALL_CANDIDATES,
    WORKLOADS,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_load,
    write_canonical_json,
)
from probe_durability_capabilities import probe  # noqa: E402
from run_fix002_preflight import (  # noqa: E402
    bounded_matrix,
    publication_race,
    write_tsv,
)
from stage_a_prototypes import BACKENDS, set_packed_bits  # noqa: E402
from stage_b_authorization import (  # noqa: E402
    AUTHORIZATION_SCHEMA,
    make_authorization_artifact,
)
from stage_b_orchestrator import branch_resource, dry_run_plan  # noqa: E402
from stage_b_runtime_contract import (  # noqa: E402
    BOUNDED_AUTHORITY_PATH,
    BOUNDED_DESCRIPTOR_PATH,
    bounded_authority,
    descriptor_case,
    make_large_request,
    prelaunch_guard,
)
from stage_b_worker import (  # noqa: E402
    build_rows,
    frozen_bounded_validator,
)


SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBExecPreflightFix003Summary/v1"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rounded(value: int, unit: int = 4096) -> int:
    return ((value + unit - 1) // unit) * unit if value else 0


def tiled_manifest_bytes(
        g: int, b: int, bstar: int, state: int, numeric: int,
        validity: int, index: int) -> int:
    c = b + bstar
    values = [
        ("magic", "SplitAlignerR-MatrixStore-VALIDATED"),
        ("manifest_schema_major", "1"), ("manifest_schema_minor", "0"),
        ("completion_state", "VALIDATED"), ("store_schema", "1.0-candidate"),
        ("layout", "tiled_row_major_provisional"), ("tile_rows", "256"),
        ("tile_columns", "256"), ("row_count", str(g)),
        ("primitive_count", str(b)), ("bstar_count", str(bstar)),
        ("numeric_coordinate_count", str(c)),
        ("species_authority_sha256", "0" * 64),
        ("gene_registry_sha256", "0" * 64),
        ("primitive_registry_sha256", "0" * 64),
        ("bstar_registry_sha256", "0" * 64),
        ("numeric_coordinate_registry_sha256", "0" * 64),
        ("logical_content_sha256", "0" * 64),
        ("state_component", "STATE.bin"), ("state_bytes", str(state)),
        ("state_sha256", "0" * 64), ("numeric_component", "NUMERIC.bin"),
        ("numeric_bytes", str(numeric)), ("numeric_sha256", "0" * 64),
        ("validity_component", "VALIDITY.bin"),
        ("validity_bytes", str(validity)), ("validity_sha256", "0" * 64),
        ("index_component", "TILE_INDEX.bin"), ("index_bytes", str(index)),
        ("index_sha256", "0" * 64), ("footer_component", "COMPLETION.bin"),
        ("footer_bytes", "512"), ("footer_sha256", "0" * 64),
        ("publication_timestamp_policy", "OMITTED_V1"),
    ]
    return sum(len(key.encode("ascii")) + len(value.encode("ascii")) + 2 for key, value in values)


def projection_crosscheck(assets: FrozenAssets) -> list[Dict[str, Any]]:
    directory_metadata_bound = 64 * 1024 * 1024
    rows = []
    for workload in WORKLOADS:
        for candidate in ALL_CANDIDATES:
            source = assets.projections[(workload, candidate)]
            g, b, bstar, c = (
                int(source[name]) for name in ("G", "B", "B_star", "C")
            )
            if candidate == "COMPACT_IN_MEMORY":
                final_exact = spool = temporary = final_allocated = high = 0
            elif candidate in {"ROW_MAJOR_DISK", "COLUMN_MAJOR_DISK"}:
                state = 256 + g * b
                numeric = 256 + g * c * 8
                validity = 256 + (g * c + 7) // 8
                final_exact = state + numeric + validity + 512 + 1024
                spool = (
                    g * (b + c * 8 + (c + 7) // 8)
                    if candidate == "COLUMN_MAJOR_DISK" else 0
                )
                temporary = directory_metadata_bound + sum(
                    map(rounded, (state, numeric, validity, 512, spool))
                )
                final_allocated = directory_metadata_bound + sum(
                    map(rounded, (state, numeric, validity, 512, 1024))
                )
                high = max(temporary, final_allocated)
            else:
                rt = (g + 255) // 256
                st = (b + 255) // 256
                nt = (c + 255) // 256
                state = 256 + rt * st * 65536
                numeric = 256 + rt * nt * 524288
                validity = 256 + rt * nt * 8192
                index = 256 + (rt * st + 2 * rt * nt) * 128
                manifest = tiled_manifest_bytes(
                    g, b, bstar, state, numeric, validity, index,
                )
                final_exact = state + numeric + validity + index + 512 + manifest
                spool = 0
                temporary = directory_metadata_bound + sum(
                    map(rounded, (state, numeric, validity, index, 512))
                )
                final_allocated = directory_metadata_bound + sum(
                    map(rounded, (state, numeric, validity, index, 512, manifest))
                )
                high = max(temporary, final_allocated)
            checks = {
                "final_physical_exact_bytes": final_exact,
                "column_row_spool_bytes": spool,
                "temporary_allocated_upper_bytes": temporary,
                "final_allocated_upper_bytes": final_allocated,
                "publication_high_water_bytes": high,
            }
            if any(int(source[field]) != value for field, value in checks.items()):
                raise AssertionError(f"projection arithmetic:{workload}:{candidate}:{checks}")
            rows.append({
                "workload_id": workload,
                "candidate_id": candidate,
                **checks,
                "spool_excluded_from_final_exact": (
                    "TRUE" if candidate == "COLUMN_MAJOR_DISK" else "NOT_APPLICABLE"
                ),
                "status": "PASS",
            })
    return rows


def _bounded_case(authority: ExecutionAuthority):
    raw = authority.repo_root.joinpath(BOUNDED_DESCRIPTOR_PATH).read_bytes()
    bounded = strict_json_load(authority.repo_root / BOUNDED_AUTHORITY_PATH)
    return descriptor_case(
        "exec_preflight_bounded_129x7x4", raw,
        bounded["dimensions"], bounded["anchor"],
    )


def semantic_mutations(
        authority: ExecutionAuthority, runtime: Path) -> list[Dict[str, Any]]:
    case = _bounded_case(authority)
    rows: list[Dict[str, Any]] = []

    def execute(case_id: str, mutate) -> None:
        target = runtime / "semantic-mutations" / case_id
        backend = BACKENDS["COMPACT_IN_MEMORY"](
            target, case.rows, case.primitive, case.bstar, case.authorities,
        )
        try:
            build_rows(backend, case)
            backend.finalize()
            before_physical = backend.component_hashes()
            before_logical = backend.logical_sha256()
            mutate(backend)
            after_physical = backend.component_hashes()
            after_logical = backend.logical_sha256()
            if before_physical == after_physical or before_logical == after_logical:
                raise AssertionError(f"mutation did not refresh hashes:{case_id}")
            try:
                frozen_bounded_validator(backend, case)
            except StopSignal as signal_value:
                if signal_value.stop_id != "E3_COMPOSITE_ROW_CONSISTENCY":
                    raise
                rows.append({
                    "case_id": case_id,
                    "integrity_metadata_refreshed": "TRUE",
                    "physical_hash_before": sha(canonical_json_bytes(before_physical)),
                    "physical_hash_after": sha(canonical_json_bytes(after_physical)),
                    "logical_hash_before": before_logical,
                    "logical_hash_after": after_logical,
                    "observed_stop_id": signal_value.stop_id,
                    "worker_launch_count": 0,
                    "status": "PASS",
                })
                return
            raise AssertionError(f"semantic mutation accepted:{case_id}")
        finally:
            backend.close()
            if target.exists():
                shutil.rmtree(target)

    active = None
    for row in range(case.rows):
        state, _numeric, validity = case.row(row)
        for bstar_id, members in enumerate(case.descriptor["bstar_members"]):
            if validity[case.primitive + bstar_id]:
                active = (row, bstar_id, members[0])
                break
        if active:
            break
    if active is None:
        raise AssertionError("bounded descriptor has no active B*")
    row, _bstar_id, member = active

    def non_fuse(backend) -> None:
        backend.states[row * case.primitive + member] = 0

    execute("ACTIVE_BSTAR_MEMBER_NOT_NA_FUSE", non_fuse)

    overlap_pair = None
    members = case.descriptor["bstar_members"]
    for left in range(case.bstar):
        for right in range(left + 1, case.bstar):
            shared = set(members[left]).intersection(members[right])
            if shared:
                overlap_pair = (left, right, sorted(set(members[left] + members[right])))
                break
        if overlap_pair:
            break
    if overlap_pair is None:
        raise AssertionError("bounded descriptor has no overlapping B* pair")
    left, right, union = overlap_pair

    def overlap(backend) -> None:
        row_value = 0
        for primitive in union:
            backend.states[row_value * case.primitive + primitive] = 2
            set_packed_bits(backend.validity, row_value * case.numeric + primitive, b"\x00")
            start = (row_value * case.numeric + primitive) * 8
            backend.numerics[start:start + 8] = bytes(8)
        for bstar_id in (left, right):
            coordinate = case.primitive + bstar_id
            set_packed_bits(backend.validity, row_value * case.numeric + coordinate, b"\x01")

    execute("SIMULTANEOUS_ACTIVE_BSTAR_OVERLAP", overlap)
    return rows


def authorization_rejection_corpus(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path) -> list[Dict[str, Any]]:
    pass_resource = dict(resource)
    workload = WORKLOADS[0]
    admission = (
        "PASS" if pass_resource["admission_memory_ceiling_bytes"] >= int(
            assets.projections[(workload, "COMPACT_IN_MEMORY")][
                "memory_admission_required_bytes"
            ]
        ) else "FAIL"
    )
    selection = assets.schedule_selection[(workload, admission)]
    schedule_row = assets.schedule_rows(
        workload, selection["selected_schedule_id"],
    )[0]
    authorization_id = "FIX003_NEGATIVE_CORPUS_NEVER_VALID"
    base = make_authorization_artifact(
        assets, authority.commit, authority.tree,
        {key: pass_resource[key] for key in (
            "host_id", "platform_system", "platform_release", "platform_machine",
            "os_build", "filesystem", "destination_device_id",
            "target_volume_device", "target_volume_mount_point",
        )},
        sha(canonical_json_bytes(dict(durability))),
        evidence, runtime, authorization_id, True,
    )
    cases = []
    mutations = {
        "INVENTED_AUTHORIZATION_SHA": lambda value: None,
        "WRONG_AUTHORIZATION_BYTES": lambda value: None,
        "WRONG_COMMIT_TREE": lambda value: value.update(
            authorized_execution_commit="0" * 40,
        ),
        "WRONG_WORKLOAD": lambda value: value["allowed_workload_ids"].__setitem__(0, "OTHER"),
        "WRONG_CANDIDATE": lambda value: value["workload_authorizations"][0][
            "admission_branches"][admission]["allowed_candidate_ids"].pop(),
        "WRONG_SCHEDULE": lambda value: value["workload_authorizations"][0][
            "admission_branches"][admission].update(
                selected_schedule_id="MUTATED_SCHEDULE_NOT_FROZEN",
        ),
        "WRONG_REPETITION_COUNT": lambda value: value["workload_authorizations"][0][
            "admission_branches"][admission].update(
                expected_measured_repetitions=7,
        ),
        "WRONG_HOST_VOLUME": lambda value: value["host_profile"].update(
            target_volume_device="WRONG_VOLUME",
        ),
        "WRONG_TIMEOUT_IDENTITY": lambda value: value.update(timeout_contract_sha256="0" * 64),
        "WRONG_EVIDENCE_ROOT": lambda value: value.update(evidence_root=str(evidence / "OTHER")),
        "STALE_AUTHORIZATION_ID": lambda value: None,
    }
    raw_root = evidence / "AUTHORIZATION_NEGATIVE_CORPUS"
    for case_id, mutate in mutations.items():
        artifact = copy.deepcopy(base)
        mutate(artifact)
        artifact_path = raw_root / f"{case_id}.authorization.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json_bytes(artifact)
        if case_id == "WRONG_AUTHORIZATION_BYTES":
            raw += b" "
        artifact_path.write_bytes(raw)
        authorization_sha = sha(raw)
        if case_id == "INVENTED_AUTHORIZATION_SHA":
            authorization_sha = "f" * 64
        activation_id = authorization_id
        if case_id == "STALE_AUTHORIZATION_ID":
            activation_id = "STALE_DIFFERENT_ID"
        activation = {
            "state": "AUTHORIZED_TO_RUN",
            "authorization_id": activation_id,
            "authorization_sha256": authorization_sha,
            "authorization_artifact_path": str(artifact_path.resolve()),
            "physical_allocation_authorized": True,
        }
        request = make_large_request(
            authority, assets, pass_resource, durability, workload,
            schedule_row["backend"],
            runtime / "authorization-never-created" / case_id,
            schedule_row, "MEASURED", evidence, activation,
        )
        try:
            prelaunch_guard(
                authority, assets, request, runtime, pass_resource, durability,
            )
        except StopSignal as signal_value:
            if signal_value.stop_id not in {
                "SB_STOP_AUTHORIZATION_HASH", "SB_STOP_AUTHORIZATION_OBJECT",
                "SB_STOP_AUTHORIZATION_BINDING",
            }:
                raise
            cases.append({
                "case_id": case_id,
                "artifact_sha256": sha(raw),
                "activation_sha256": authorization_sha,
                "observed_stop_id": signal_value.stop_id,
                "worker_launch_count": 0,
                "physical_allocation_count": 0,
                "status": "PASS",
            })
            continue
        raise AssertionError(f"fake authorization activated:{case_id}")
    return cases


def source_gates(repo: Path) -> list[Dict[str, Any]]:
    files = [
        repo / "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_authorization.py",
        repo / "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_orchestrator.py",
        repo / "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py",
        repo / "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_worker.py",
        repo / "dev/ENGINE003-PREFLIGHT/pilot/stage_a_prototypes.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    checks = {
        "EXTERNAL_AUTHORIZATION_SCHEMA_PRESENT": AUTHORIZATION_SCHEMA in text,
        "EXACT_AUTHORIZATION_BYTES_HASHED": "_sha256(raw) != expected_sha256" in text,
        "STRICT_JSON_AUTHORIZATION": "strict_json_loads(raw)" in text,
        "COMPLETE_ORCHESTRATOR_PRESENT": "COMPLETE_PLAN_FROZEN_NOT_EXECUTED" in text,
        "MULTIPASS_VALIDATOR_PRESENT": "MULTIPASS_ROW_SEGMENT_V1" in text,
        "COLUMN_SPOOL_RETIREMENT_PRESENT": "retire_construction_artifacts" in text,
        "NO_REPLACE_REGRESSION": "os.replace" not in text,
    }
    if not all(checks.values()):
        raise AssertionError(f"source gates:{checks}")
    return [
        {"case_id": key, "status": "PASS", "detail": "FIX003_ACTIVE_SOURCE"}
        for key, value in checks.items() if value
    ]


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    authority = ExecutionAuthority(repo, args.authorized_commit, args.authorized_tree)
    assets = FrozenAssets(authority)
    from stage_b_runtime_contract import assert_protected_source_clean
    assert_protected_source_clean(authority)
    evidence.mkdir(parents=True, exist_ok=False)
    runtime.mkdir(parents=True, exist_ok=False)
    resource = capture(runtime)
    durability = probe(runtime)
    if (
        resource["platform_system"] != "Darwin"
        or resource["filesystem"].lower() != "apfs"
        or durability["durable_publish_v1_supported"] is not True
    ):
        raise StopSignal("SB_STOP_CAPABILITY", "FIX003_REQUIRES_MACOS_APFS")
    resource_path = evidence / "FRESH_RESOURCE_CAPTURE.json"
    durability_path = evidence / "DURABLE_PUBLISH_CAPABILITY.json"
    write_canonical_json(resource_path, resource)
    write_canonical_json(durability_path, durability)
    write_canonical_json(evidence / "SOURCE_AND_FROZEN_AUTHORITY_PROOF.json", {
        "schema": "SplitAlignerR/ENGINE003SourceAuthorityProof/v3",
        **authority.proof(),
        "untracked_protected_source_absent": True,
        "frozen_artifact_sha256": {
            key: sha(raw) for key, raw in assets.raw.items()
        },
    })

    bounded_results, bounded_ledger = bounded_matrix(
        authority, assets, resource, durability, repo, runtime, evidence,
        resource_path, durability_path,
    )
    write_tsv(evidence / "BOUNDED_REAL_BACKEND_LEDGER.tsv", bounded_ledger)
    validator_rows = []
    for result in bounded_results:
        validator_rows.append({
            "candidate_id": result["candidate_id"],
            "validator_id": result["bounded_validator"]["validator_id"],
            "access_profile": result["bounded_validator"]["access_profile"],
            "primitive_segment_count": result["bounded_validator"]["primitive_segment_count"],
            "bstar_validity_window_rescans": result["bounded_validator"]["bstar_validity_window_rescans"],
            "registry_probes": result["bounded_validator"]["registry_probes"],
            "member_checks": result["bounded_validator"]["member_checks"],
            "overlap_checks": result["bounded_validator"]["overlap_checks"],
            "complete_owned_matrix_bytes": 0,
            "status": "PASS",
        })
    write_tsv(evidence / "MULTIPASS_VALIDATOR_EVIDENCE.tsv", validator_rows)

    column = next(
        result for result in bounded_results
        if result["candidate_id"] == "COLUMN_MAJOR_DISK"
    )
    write_canonical_json(evidence / "COLUMN_MAJOR_SPOOL_LIFECYCLE.json", {
        "schema": "SplitAlignerR/ENGINE003ColumnSpoolLifecycle/v1",
        "status": "PASS",
        **column["column_spool_lifecycle"],
        "artifact_retirement": column["construction_artifact_retirement"],
        "maximum_unpublished_physical_disk_bytes": column["maximum_unpublished_physical_disk_bytes"],
        "final_published_physical_disk_bytes": column["final_published_physical_disk_bytes"],
        "publication_high_water_physical_bytes": column["publication_high_water_physical_bytes"],
        "expected_final_component_sizes": column["expected_final_component_sizes"],
        "physical_component_hash_names": sorted(column["physical_component_sha256"]),
        "durable_synced_files": column["durable_publication"]["synced_files"],
    })

    projection_rows = projection_crosscheck(assets)
    write_tsv(evidence / "FROZEN_PROJECTION_ARITHMETIC_CROSSCHECK.tsv", projection_rows)
    mutation_rows = semantic_mutations(authority, runtime)
    write_tsv(evidence / "COMPOSITE_SEMANTIC_MUTATION_RESULTS.tsv", mutation_rows)
    auth_rows = authorization_rejection_corpus(
        authority, assets, resource, durability, runtime, evidence,
    )
    write_tsv(evidence / "AUTHORIZATION_REJECTION_RESULTS.tsv", auth_rows)

    plan_summaries = []
    total_requests = 0
    for admission, expected in (("PASS", 108), ("FAIL", 63)):
        branch = branch_resource(assets, resource, admission)
        write_canonical_json(evidence / f"RESOURCE_VIEW_{admission}.json", branch)
        plan = dry_run_plan(
            authority, assets, branch, durability,
            runtime / f"large-{admission.lower()}-never-created", evidence,
        )
        if plan["request_count"] != expected:
            raise AssertionError(f"plan cardinality:{admission}:{plan['request_count']}")
        write_canonical_json(evidence / f"COMPLETE_PLAN_{admission}.json", plan)
        total_requests += plan["request_count"]
        plan_summaries.append({
            "compact_admission_result": admission,
            "workload_count": len(plan["workloads"]),
            "warmup_request_count": plan["warmup_request_count"],
            "measured_request_count": plan["measured_request_count"],
            "total_request_count": plan["request_count"],
            "worker_launch_count": plan["worker_launch_count"],
            "physical_allocation_count": plan["physical_allocation_count"],
            "decision_input_ledger_assembled_after_complete_plan": "TRUE",
            "status": "PASS",
        })
    write_tsv(evidence / "COMPLETE_PLAN_BRANCH_SUMMARY.tsv", plan_summaries)

    race = publication_race(runtime, evidence)
    source_rows = source_gates(repo)
    write_tsv(evidence / "SOURCE_LEVEL_GATES.tsv", source_rows)
    for path in sorted(runtime.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if any(runtime.iterdir()):
        raise StopSignal("SB_STOP_CLEANUP", "runtime_root_not_empty")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_BOUNDED_FIX003_PREFLIGHT_ONLY",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "frozen_prereg_commit": authority.prereg_commit,
        "frozen_prereg_tree": authority.prereg_tree,
        "bounded_physical_worker_launches": len(bounded_results),
        "multipass_validator_candidates": len(validator_rows),
        "authorization_negative_cases": len(auth_rows),
        "composite_semantic_mutation_cases": len(mutation_rows),
        "large_complete_plan_requests": total_requests,
        "large_plan_branch_count": len(plan_summaries),
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "projection_crosscheck_count": len(projection_rows),
        "publication_race_status": race["status"],
        "stage_b_clock": False,
        "stage_b_execution_authorized": False,
        "large_store_constructed": False,
        "over2gib_or_over4gib_constructed": False,
        "backend_selected": False,
        "runtime_root_empty_after_cleanup": True,
    }
    write_canonical_json(evidence / "FIX003_SUMMARY.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--authorized-commit", required=True)
    parser.add_argument("--authorized-tree", required=True)
    args = parser.parse_args()
    result = execute(args)
    print(
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX003_"
        f"{result['status']} BOUNDED_WORKERS={result['bounded_physical_worker_launches']} "
        f"LARGE_PLAN_REQUESTS={result['large_complete_plan_requests']} LARGE_WORKERS=0"
    )


if __name__ == "__main__":
    main()
