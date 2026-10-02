#!/usr/bin/env python3
"""Run ENGINE003-STAGEB-EXEC-PREFLIGHT001-FIX002.

Only the 129-row descriptor is physically executed.  The three frozen
authority/stress descriptors each produce four complete launch requests and
must stop at the final activation barrier with zero worker launches and zero
physical allocations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REFERENCE = ENGINE / "reference"
for value in (HERE, REFERENCE):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from capture_pretiming_resources import capture  # noqa: E402
from fix001_contract import (  # noqa: E402
    ALL_CANDIDATES,
    WORKLOADS,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    strict_json_load,
    write_canonical_json,
)
from probe_durability_capabilities import probe  # noqa: E402
from stage_b_durable_publish import tree_sha256  # noqa: E402
from stage_b_controller import (  # noqa: E402
    launch_request,
    process_group_options,
    terminate_tree,
)
from stage_b_runtime_contract import (  # noqa: E402
    METRIC_HANDLERS,
    OPERATION_CONTRACT,
    FrozenMetricPlan,
    make_bounded_request,
    make_large_request,
    prelaunch_guard,
)


WORKER = HERE / "stage_b_worker.py"
SUMMARY_SCHEMA = "SplitAlignerR/ENGINE003StageBExecPreflightFix002Summary/v1"


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty TSV:{path}")
    fields = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in rows:
            if list(row) != fields:
                raise ValueError(f"TSV field order:{path}")
            writer.writerow(row)


def bounded_matrix(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        repo: Path, runtime: Path, evidence: Path,
        resource_path: Path, durability_path: Path) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    results = []
    ledger = []
    raw = evidence / "RAW_BOUNDED_WORKERS"
    for position, candidate in enumerate(ALL_CANDIDATES, 1):
        stem = f"p{position}_{candidate}"
        request = make_bounded_request(
            authority, assets, resource, durability, candidate, position,
            runtime / "bounded" / stem, evidence,
        )
        guard = prelaunch_guard(
            authority, assets, request, runtime, resource, durability,
        )
        if guard["status"] != "PRELAUNCH_PASS_BOUNDED_PHYSICAL_ALLOWED":
            raise AssertionError("bounded activation guard")
        result = launch_request(
            repo, runtime, resource_path, durability_path, request,
            raw / f"{stem}.request.json", raw / f"{stem}.result.json",
            raw / f"{stem}.log.txt",
            branch_resource_path=resource_path,
        )
        markers = result.get("operation_markers", [])
        if len(markers) != len(METRIC_HANDLERS) or {
                value["metric_id"] for value in markers} != set(METRIC_HANDLERS):
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "metric_marker_set")
        if any(value.get("execution_count") != 1 for value in markers):
            raise StopSignal("SB_STOP_OPERATION_CONTRACT", "metric_cardinality")
        results.append(result)
        ledger.append({
            "candidate_id": candidate,
            "execution_mode": request["execution_mode"],
            "descriptor_sha256": request["descriptor_sha256"],
            "G": request["dimensions"]["G"],
            "B": request["dimensions"]["B"],
            "B_star": request["dimensions"]["B_star"],
            "C": request["dimensions"]["C"],
            "prelaunch_status": guard["status"],
            "worker_status": result["status"],
            "physical_store_constructed": "TRUE",
            "all_19_metrics_once": "TRUE",
            "cleanup_result": result["cleanup_result"],
            "status": "PASS",
        })
    expected = None
    for result in results:
        scan = result["bounded_full_logical_scan"]
        identity = (
            scan["state_stream_sha256"], scan["numeric_stream_sha256"],
            scan["validity_stream_sha256"], scan["logical_content_sha256"],
        )
        expected = identity if expected is None else expected
        if identity != expected or result["logical_content_sha256"] != identity[-1]:
            raise AssertionError("four-backend semantic inequality")
    return results, ledger


def large_activation_dry_run(
        authority: ExecutionAuthority, assets: FrozenAssets,
        resource: Mapping[str, Any], durability: Mapping[str, Any],
        runtime: Path, evidence: Path) -> list[Dict[str, Any]]:
    rows = []
    raw = evidence / "LARGE_DRY_RUN_REQUESTS"
    for workload in WORKLOADS:
        for candidate in ALL_CANDIDATES:
            compact_required = int(assets.projections[(
                workload, "COMPACT_IN_MEMORY",
            )]["memory_admission_required_bytes"])
            admission = (
                "PASS" if resource["admission_memory_ceiling_bytes"] >= compact_required
                else "FAIL"
            )
            selection = assets.schedule_selection[(workload, admission)]
            matching_rows = [
                row for row in assets.schedule_rows(
                    workload, selection["selected_schedule_id"],
                ) if row["backend"] == candidate
            ]
            if not matching_rows:
                continue
            request = make_large_request(
                authority, assets, resource, durability, workload, candidate,
                runtime / "large-never-created" / workload / candidate,
                matching_rows[0], "MEASURED", evidence,
            )
            path = raw / f"{workload}__{candidate}.request.json"
            write_canonical_json(path, request)
            try:
                prelaunch_guard(
                    authority, assets, request, runtime, resource, durability,
                )
            except StopSignal as signal_value:
                if signal_value.stop_id != "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED":
                    raise AssertionError(
                        f"large dry-run:{workload}:{candidate}:{signal_value}"
                    )
                rows.append({
                    "workload_id": workload,
                    "candidate_id": candidate,
                    "G": request["dimensions"]["G"],
                    "B": request["dimensions"]["B"],
                    "B_star": request["dimensions"]["B_star"],
                    "C": request["dimensions"]["C"],
                    "descriptor_sha256": request["descriptor_sha256"],
                    "logical_content_sha256": request["anchor"]["logical_content_sha256"],
                    "selected_schedule_id": request["selected_schedule_id"],
                    "measured_repetition": request["measured_repetition"],
                    "schedule_position": request["schedule_position"],
                    "schedule_row_sha256": request["schedule_row_sha256"],
                    "timeout_seconds": request["timeout_seconds"],
                    "fresh_resource_capture_sha256": request["fresh_resource_capture_sha256"],
                    "observed_stop_id": signal_value.stop_id,
                    "last_completed_stage": "ALL_PRELAUNCH_DECISIONS_COMPLETE",
                    "worker_launch_count": 0,
                    "physical_allocation_count": 0,
                    "request_path": path.relative_to(evidence).as_posix(),
                    "status": "PASS",
                })
                continue
            raise AssertionError(f"large execution activated:{workload}:{candidate}")
    return rows


def publication_race(runtime: Path, evidence: Path) -> Dict[str, Any]:
    race = runtime / "publication-race"
    race.mkdir(parents=True, exist_ok=False)
    final = race / "winner"
    gate = race / "START"
    processes = []
    outputs = []
    for participant in ("A", "B"):
        temporary = race / f"candidate-{participant}.partial"
        temporary.mkdir()
        marker = (f"PARTICIPANT={participant}\n" * 32).encode("ascii")
        (temporary / "MARKER.bin").write_bytes(marker)
        output = evidence / "PUBLICATION_RACE" / f"participant-{participant}.json"
        log = evidence / "PUBLICATION_RACE" / f"participant-{participant}.log.txt"
        command = [
            sys.executable, "-B", str(WORKER), "--race-participant",
            "--temp-target", str(temporary), "--final-target", str(final),
            "--start-gate", str(gate), "--output", str(output),
            "--participant-id", participant,
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, **process_group_options(),
        )
        processes.append((participant, temporary, process, log))
        outputs.append(output)
    gate.write_text("GO\n", encoding="ascii")
    for _participant, _temporary, process, log in processes:
        try:
            stdout, _ = process.communicate(timeout=60)
        except subprocess.TimeoutExpired as error:
            terminate_tree(process)
            raise StopSignal("SB_STOP_TIMEOUT", "publication_race") from error
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(stdout, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"publication race participant failed:{stdout}")
    values = [strict_json_load(path) for path in outputs]
    winners = [value for value in values if value["status"] == "WINNER_PUBLISHED"]
    losers = [value for value in values if value["status"] == "LOSER_TYPED_STOP"]
    if len(winners) != 1 or len(losers) != 1:
        raise AssertionError("exclusive publication winner cardinality")
    if losers[0]["stop_id"] != "SB_STOP_PUBLICATION_DESTINATION_EXISTS":
        raise AssertionError("publication loser typed stop")
    winner_hash_before = tree_sha256(final)
    loser_id = losers[0]["participant_id"]
    loser_temp = race / f"candidate-{loser_id}.partial"
    if not loser_temp.is_dir():
        raise AssertionError("loser temporary tree did not survive exclusive rename")
    shutil.rmtree(loser_temp)
    winner_hash_after = tree_sha256(final)
    if winner_hash_before != winner_hash_after:
        raise AssertionError("loser cleanup altered winner")
    winner_marker = (final / "MARKER.bin").read_bytes().decode("ascii").splitlines()[0]
    result = {
        "schema": "SplitAlignerR/ENGINE003DurablePublishRaceResult/v1",
        "status": "PASS",
        "publication_primitive": winners[0]["publication"]["publication_primitive"],
        "winner_id": winners[0]["participant_id"],
        "loser_id": loser_id,
        "winner_marker": winner_marker,
        "winner_count": len(winners),
        "loser_count": len(losers),
        "loser_stop_id": losers[0]["stop_id"],
        "winner_sha256_before_loser_cleanup": winner_hash_before,
        "winner_sha256_after_loser_cleanup": winner_hash_after,
        "winner_bytes_unchanged": True,
        "loser_cleanup_scope": "OWN_RECOGNIZED_SAME_PARENT_TEMPORARY_ONLY",
        "exists_then_replace_emulation": False,
    }
    write_canonical_json(evidence / "PUBLICATION_RACE_RESULT.json", result)
    shutil.rmtree(final)
    gate.unlink()
    race.rmdir()
    return result


def source_level_gates(repo: Path) -> list[Dict[str, Any]]:
    paths = (
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_runtime_contract.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_worker.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_controller.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/run_fix002_preflight.py",
        "dev/ENGINE003-PREFLIGHT/exec_preflight/stage_b_durable_publish.py",
    )
    worker_controller = paths[:4]
    combined = "\n".join((repo / value).read_text(encoding="utf-8") for value in worker_controller)
    durable = (repo / paths[4]).read_text(encoding="utf-8")
    cases = []
    def record(case_id: str, passed: bool, detail: str) -> None:
        if not passed:
            raise AssertionError(f"source gate:{case_id}:{detail}")
        cases.append({"case_id": case_id, "status": "PASS", "detail": detail})
    dimension_assignment = re.compile(
        r"(?m)^\s*(?:G|ROWS|B|PRIMITIVE|B_STAR|BSTAR|C|NUMERIC)\s*=\s*"
        r"(?:2275|100000|102500|601|1997|2916|1086|4913)\b"
    )
    record(
        "NO_HARDCODED_LARGE_DIMENSION_ASSIGNMENT",
        dimension_assignment.search(combined) is None,
        "worker/controller dimensions are request/descriptor driven",
    )
    record("NO_OS_REPLACE", "os.replace" not in durable, "exclusive rename primitive only")
    record("NO_OS_RENAME", "os.rename" not in durable, "exclusive rename primitive only")
    record(
        "EXACT_RENAME_EXCLUSIVE_CALL", "rename_exclusive(temp_target, final_target)" in durable,
        "frozen wrapper reaches renamex_np(RENAME_EXCL) on macOS",
    )
    record(
        "LARGE_ACTIVATION_BARRIER_PRESENT",
        "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED" in combined,
        "large dry-run stop is explicit",
    )
    return cases


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    repo = args.repo_root.resolve()
    evidence = args.evidence_dir.resolve()
    runtime = args.runtime_root.resolve()
    authority = ExecutionAuthority(
        repo, args.authorized_commit, args.authorized_tree,
    )
    assets = FrozenAssets(authority)
    # Final source-clean proof includes untracked files and precedes any output.
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
        raise StopSignal(
            "SB_STOP_CAPABILITY",
            "FIX002_REAL_BACKEND_COLD_REPLAY_REQUIRES_MACOS_APFS",
        )
    resource_path = evidence / "FRESH_RESOURCE_CAPTURE.json"
    durability_path = evidence / "DURABLE_PUBLISH_CAPABILITY.json"
    write_canonical_json(resource_path, resource)
    write_canonical_json(durability_path, durability)
    write_canonical_json(evidence / "SOURCE_AND_FROZEN_AUTHORITY_PROOF.json", {
        "schema": "SplitAlignerR/ENGINE003SourceAuthorityProof/v2",
        **authority.proof(),
        "untracked_protected_source_absent": True,
        "frozen_artifact_sha256": {
            key: hashlib.sha256(raw).hexdigest() for key, raw in assets.raw.items()
        },
    })

    plan = FrozenMetricPlan(assets)
    write_tsv(evidence / "FROZEN_METRIC_OPERATION_BINDING.tsv", plan.binding_rows())
    results, bounded_ledger = bounded_matrix(
        authority, assets, resource, durability, repo, runtime, evidence,
        resource_path, durability_path,
    )
    write_tsv(evidence / "BOUNDED_REAL_BACKEND_LEDGER.tsv", bounded_ledger)
    large_rows = large_activation_dry_run(
        authority, assets, resource, durability, runtime, evidence,
    )
    write_tsv(evidence / "LARGE_ACTIVATION_DRY_RUN.tsv", large_rows)
    race = publication_race(runtime, evidence)
    source_gates = source_level_gates(repo)
    write_tsv(evidence / "SOURCE_LEVEL_GATES.tsv", source_gates)

    for path in sorted(runtime.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if any(runtime.iterdir()):
        raise StopSignal("SB_STOP_CLEANUP", "runtime_root_not_empty")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "PASS_BOUNDED_PARAMETERIZED_EXECUTION_PREFLIGHT_ONLY",
        "source_commit": authority.commit,
        "source_tree": authority.tree,
        "frozen_prereg_commit": authority.prereg_commit,
        "frozen_prereg_tree": authority.prereg_tree,
        "execution_platform_scope": "macOS/APFS",
        "observed_host_profile": results[0]["host_profile"],
        "operation_contract": OPERATION_CONTRACT,
        "frozen_metric_count": len(METRIC_HANDLERS),
        "metric_operation_cardinality": "EXACTLY_ONE_EACH",
        "bounded_physical_worker_launches": len(results),
        "bounded_candidate_ids": list(ALL_CANDIDATES),
        "bounded_all_four_semantically_equal": True,
        "large_request_count": len(large_rows),
        "large_worker_launch_count": 0,
        "large_physical_allocation_count": 0,
        "large_activation_stop_id": "STAGEB_LARGE_EXECUTION_NOT_AUTHORIZED",
        "publication_race_status": race["status"],
        "publication_race_winner_count": race["winner_count"],
        "publication_race_loser_count": race["loser_count"],
        "source_level_gate_count": len(source_gates),
        "stage_b_measured_timing": False,
        "performance_conclusion_authorized": False,
        "backend_selection_authorized": False,
        "large_store_constructed": False,
        "workload_100000_executed": False,
        "over2gib_or_over4gib_constructed": False,
        "production_writer_or_reader_implemented": False,
        "tile_geometry_frozen": False,
        "runtime_root_empty_after_cleanup": True,
    }
    write_canonical_json(evidence / "FIX002_SUMMARY.json", summary)
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
        "ENGINE003_STAGEB_EXEC_PREFLIGHT001_FIX002_"
        f"{result['status']} BOUNDED_WORKERS={result['bounded_physical_worker_launches']} "
        f"LARGE_DRY_RUNS={result['large_request_count']} LARGE_WORKERS=0"
    )


if __name__ == "__main__":
    main()
