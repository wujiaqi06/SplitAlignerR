#!/usr/bin/env python3
"""Generate an exact four-candidate non-executing Stage-A admission proposal.

This script performs checked resource arithmetic only.  It does not allocate a
backend, probe durability, write a MatrixStore, materialize R objects, or record
timing.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Optional

from planner_projection import (
    add,
    charge_backend,
    checked_input,
    checked_sum,
    ceil_div,
    construction_projection,
    flat_file_construction_projection,
    mandatory_terms,
    mib,
    mul,
    project_format,
)


FORMULA = "ENGINE003_STAGE_A_FIBER_CONSISTENT_BITS_V3"
PROPOSAL_SCHEMA = "SplitAlignerR/ENGINE003StageAAdmissionProposal/v3"
FIX001_PROPOSAL_SCHEMA = "SplitAlignerR/ENGINE003StageAFix001AdmissionProposal/v1"
HISTORICAL_EXECUTION_CONTRACT = "HISTORICAL_STAGEA_TIMING_001_V1"
FIX001_EXECUTION_CONTRACT = "STAGEA_FIX001_UNTIL_CLOCK_V1"
PILOT_PROCESS_RUNTIME_OVERHEAD_BYTES = mib(64)
PILOT_STREAM_CHUNK_BYTES = mib(1)
PILOT_VALIDATOR_ROW_BLOCK = 256
CASES = (
    "tiny_correctness", "catnip10_like", "authority_shape", "moderate_churn",
)
BACKENDS = (
    "COMPACT_IN_MEMORY", "ROW_MAJOR_DISK", "COLUMN_MAJOR_DISK", "TILED_DISK",
)


def checked_margin(available: int, required: int, label: str) -> int:
    checked_input(available, f"available {label}")
    checked_input(required, f"required {label}")
    return available - required


def evaluate_execution_admission(
    backend: str,
    required_memory: int,
    memory_ceiling: int,
    required_disk: int,
    available_disk: int,
    durability_capabilities_pass: bool,
    allocation_capabilities_pass: bool = True,
) -> dict[str, object]:
    """Separate checked projection from fail-closed execution admission."""
    if backend not in set(BACKENDS):
        raise ValueError("unsupported admission backend")
    if not isinstance(durability_capabilities_pass, bool):
        raise ValueError("durability capability result must be bool")
    if not isinstance(allocation_capabilities_pass, bool):
        raise ValueError("allocation capability result must be bool")
    memory_margin = checked_margin(memory_ceiling, required_memory, "memory")
    disk_margin = checked_margin(available_disk, required_disk, "disk")
    memory_ok = required_memory <= memory_ceiling
    disk_applicable = backend != "COMPACT_IN_MEMORY"
    disk_ok = required_disk <= available_disk if disk_applicable else True
    if not memory_ok and not disk_ok:
        resource_admission = "NOT_ADMITTED_MEMORY_AND_DISK"
    elif not memory_ok:
        resource_admission = "NOT_ADMITTED_MEMORY"
    elif not disk_ok:
        resource_admission = "NOT_ADMITTED_DISK"
    else:
        resource_admission = "PASS"
    if disk_applicable:
        durability_admission = (
            "PASS" if durability_capabilities_pass else "NOT_ADMITTED_DURABILITY"
        )
    else:
        durability_admission = "NOT_APPLICABLE_COMPACT_MEMORY"
    if resource_admission != "PASS":
        execution_admission = resource_admission
    elif disk_applicable and not allocation_capabilities_pass:
        execution_admission = "NOT_ADMITTED_ALLOCATION"
    elif disk_applicable and durability_admission != "PASS":
        execution_admission = "NOT_ADMITTED_DURABILITY"
    else:
        execution_admission = "PASS"
    return {
        "memory_margin_bytes": memory_margin,
        "disk_margin_bytes": disk_margin,
        "memory_ok": str(memory_ok).upper(),
        "disk_ok": str(disk_ok).upper() if disk_applicable else "NOT_APPLICABLE",
        "durability_capabilities_ok": (
            str(durability_capabilities_pass).upper()
            if disk_applicable else "NOT_APPLICABLE"
        ),
        "allocation_capabilities_ok": (
            str(allocation_capabilities_pass).upper()
            if disk_applicable else "NOT_APPLICABLE"
        ),
        "memory_admission": "PASS" if memory_ok else "NOT_ADMITTED_MEMORY",
        "disk_admission": (
            ("PASS" if disk_ok else "NOT_ADMITTED_DISK")
            if disk_applicable else "NOT_APPLICABLE_COMPACT_MEMORY"
        ),
        "execution_resource_admission": resource_admission,
        "execution_allocation_admission": (
            ("PASS" if allocation_capabilities_pass else
             "NOT_ADMITTED_ALLOCATION")
            if disk_applicable else "NOT_APPLICABLE_COMPACT_MEMORY"
        ),
        "execution_durability_admission": durability_admission,
        "execution_admission": execution_admission,
    }


def declared_terms() -> dict[str, int]:
    return mandatory_terms(
        registry_representation_bytes=mib(1),
        r_orchestration_bytes=mib(2),
        backend_native_allocation_overhead_bytes=mib(1),
        r_dimnames_and_registry_bytes=mib(2),
        r_conversion_scratch_bytes=mib(1),
        r_allocator_and_object_overhead_bytes=mib(2),
        production_validator_registry_bytes=mib(1),
        production_validator_overhead_bytes=mib(1),
        independent_validator_registry_bytes=mib(1),
        independent_validator_overhead_bytes=mib(1),
        implementation_overhead_bytes=mib(2),
        safety_reserve_bytes=mib(32),
    )


def fix001_execution_charge(
    format_row: dict[str, object], charge: dict[str, object], terms: dict[str, int]
) -> dict[str, object]:
    """Charge the operations actually executed by the no-clock Stage-A pilot."""
    rows = checked_input(int(format_row["rows"]), "pilot rows")
    primitive = checked_input(
        int(format_row["primitive_columns"]), "pilot primitive columns"
    )
    numeric = checked_input(
        int(format_row["numeric_columns"]), "pilot numeric columns"
    )
    state_output = mul(rows, primitive, "pilot full state output")
    numeric_output = mul(mul(rows, numeric, "pilot numeric cells"), 8,
                         "pilot full numeric output")
    validity_output = ceil_div(
        mul(rows, numeric, "pilot validity cells"), 8
    ) if rows and numeric else 0
    full_output = checked_sum(
        (state_output, numeric_output, validity_output),
        "pilot complete logical output",
    )
    row_width = checked_sum(
        (primitive, mul(numeric, 8, "pilot numeric row"), numeric),
        "pilot unpacked logical row width",
    )
    row_block = mul(
        min(rows, PILOT_VALIDATOR_ROW_BLOCK), row_width,
        "pilot bounded validator row block",
    )
    full_scratch = max(PILOT_STREAM_CHUNK_BYTES, row_width)
    logical_hash_buffer = checked_sum(
        (row_block, PILOT_STREAM_CHUNK_BYTES, row_width),
        "pilot streaming logical-hash buffer",
    )
    validation_buffer = checked_sum(
        (row_block, PILOT_STREAM_CHUNK_BYTES,
         mul(row_width, 2, "pilot validator row pair")),
        "pilot bounded validation buffer",
    )
    # The complete output is logically released before later operations, but
    # CPython/macOS may retain its arenas in current RSS until process exit.
    # Charge that predictable pilot behavior explicitly instead of spending
    # the generic safety reserve on it.
    post_full_retention = full_output
    base_live = int(charge["base_live_bytes"])
    runtime = PILOT_PROCESS_RUNTIME_OVERHEAD_BYTES
    operation_peaks = {
        "pilot_construction_peak_live_bytes": add(
            int(charge["construction_peak_live_bytes"]), runtime,
            "pilot construction plus runtime",
        ),
        "pilot_finalization_peak_live_bytes": add(
            int(charge["finalization_hash_peak_live_bytes"]), runtime,
            "pilot finalization plus runtime",
        ),
        "pilot_full_logical_read_peak_live_bytes": checked_sum(
            (base_live, full_output, full_scratch, runtime),
            "pilot complete logical read peak",
        ),
        "pilot_physical_hash_peak_live_bytes": checked_sum(
            (base_live, post_full_retention, PILOT_STREAM_CHUNK_BYTES, runtime),
            "pilot physical hash peak",
        ),
        "pilot_logical_hash_peak_live_bytes": checked_sum(
            (base_live, post_full_retention, logical_hash_buffer, runtime),
            "pilot streaming logical hash peak",
        ),
        "pilot_bounded_validation_peak_live_bytes": checked_sum(
            (base_live, post_full_retention, validation_buffer, runtime),
            "pilot bounded validation peak",
        ),
    }
    production_like_peak = int(charge["overall_max_live_bytes"])
    pilot_peak = max(operation_peaks.values())
    execution_peak = max(production_like_peak, pilot_peak)
    admission = add(
        execution_peak, terms["safety_reserve_bytes"],
        "Stage-A Fix001 admission",
    )
    return {
        "pilot_full_state_output_bytes": state_output,
        "pilot_full_numeric_output_bytes": numeric_output,
        "pilot_full_validity_output_bytes": validity_output,
        "pilot_full_logical_output_bytes": full_output,
        "pilot_full_read_scratch_bytes": full_scratch,
        "pilot_logical_hash_buffer_bytes": logical_hash_buffer,
        "pilot_validation_buffer_bytes": validation_buffer,
        "pilot_process_runtime_overhead_bytes": runtime,
        "pilot_post_full_allocator_retention_charge_bytes": post_full_retention,
        "pilot_allocator_retention_policy": (
            "CONSERVATIVE_COMPLETE_OUTPUT_UNTIL_WORKER_PROCESS_EXIT_V1"
        ),
        "pilot_row_block_bytes": row_block,
        **operation_peaks,
        "production_like_peak_live_bytes": production_like_peak,
        "pilot_operation_peak_live_bytes": pilot_peak,
        "stage_a_execution_peak_live_bytes": execution_peak,
        "stage_a_admission_required_bytes": admission,
    }


def read_semantic_results(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = {row["case_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    if set(rows) != set(CASES):
        raise ValueError("Stage-A V3 case set mismatch")
    for case, row in rows.items():
        if row["formula_id"] != FORMULA:
            raise ValueError(f"formula mismatch: {case}")
        if row["execution_status"] != "SEMANTIC_ORACLE_EXECUTED_NO_TIMING":
            raise ValueError(f"semantic status mismatch: {case}")
    return rows


def read_durability_probe(path: Optional[Path]) -> Optional[dict[str, object]]:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "component_file_sync", "temporary_directory_sync", "atomic_no_replace",
        "parent_directory_sync", "manifest_file_sync", "final_directory_sync",
    }
    if set(value.get("capabilities", {})) != required:
        raise ValueError("durability probe capability key mismatch")
    supported = value.get("durable_publish_v1_supported")
    if not isinstance(supported, bool):
        raise ValueError("durability probe support flag type")
    observed = all(
        value["capabilities"][name].get("status") == "PASS"
        for name in required
    )
    if observed != supported:
        raise ValueError("durability probe aggregate mismatch")
    return value


def read_allocation_probe(path: Optional[Path]) -> Optional[dict[str, object]]:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"COLUMN_MAJOR_DISK", "TILED_DISK"}
    cases = value.get("cases")
    if not isinstance(cases, dict) or set(cases) != required:
        raise ValueError("physical-allocation probe backend set mismatch")
    if value.get("construction_policy") != (
        "EXACT_PHYSICAL_PREALLOCATION_THEN_FULL_BOUNDED_ZERO_FILL_V1"
    ):
        raise ValueError("physical-allocation construction policy mismatch")
    if value.get("sparse_or_truncate_only_shortcut_permitted") is not False:
        raise ValueError("physical-allocation probe permits sparse shortcut")
    if value.get("stage_a_payload_workload_executed") is not False:
        raise ValueError("physical-allocation probe contains payload workload")
    expected_primitive = (
        "fcntl(F_PREALLOCATE,F_ALLOCATEALL,F_PEOFPOSMODE)+ftruncate+"
        "bounded_pwrite_zero_fill"
    )
    for backend in required:
        case = cases[backend]
        requested = case.get("requested_bytes")
        if not isinstance(requested, int) or isinstance(requested, bool) or requested <= 0:
            raise ValueError("physical-allocation requested length invalid")
        if case.get("status") == "PASS":
            if case.get("allocation_primitive") != expected_primitive:
                raise ValueError("physical-allocation primitive mismatch")
            if case.get("all_logical_bytes_verified_zero") is not True:
                raise ValueError("physical-allocation zero readback missing")
            snapshots = case.get("snapshots")
            if not isinstance(snapshots, list) or len(snapshots) != 3:
                raise ValueError("physical-allocation snapshot set mismatch")
            expected_phases = (
                "EMPTY_NEW_FILE", "AFTER_F_PREALLOCATE_AND_FTRUNCATE",
                "AFTER_BOUNDED_FULL_ZERO_FILL",
            )
            if tuple(item.get("phase") for item in snapshots) != expected_phases:
                raise ValueError("physical-allocation phase order mismatch")
            for snapshot in snapshots[1:]:
                if (snapshot.get("logical_length_bytes") != requested or
                        not isinstance(snapshot.get("physical_allocated_bytes"), int) or
                        snapshot["physical_allocated_bytes"] < requested or
                        snapshot.get("allocated_covers_logical_length") is not True or
                        snapshot.get("seek_data_offset") != 0 or
                        snapshot.get("seek_hole_offset") != requested or
                        snapshot.get("seek_extent_status") != "PASS_NO_HOLE"):
                    raise ValueError("physical-allocation no-hole proof mismatch")
    observed = all(cases[name].get("status") == "PASS" for name in required)
    supported = value.get("all_required_backends_supported")
    if not isinstance(supported, bool) or observed != supported:
        raise ValueError("physical-allocation probe aggregate mismatch")
    if value.get("timing_executed") is not False:
        raise ValueError("physical-allocation probe contains timing")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--capture-time", required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--os-build", required=True)
    parser.add_argument("--filesystem", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--physical-memory-bytes", required=True, type=int)
    parser.add_argument("--memory-free-percent", required=True, type=int)
    parser.add_argument("--admission-memory-ceiling-bytes", required=True, type=int)
    parser.add_argument("--available-disk-bytes", required=True, type=int)
    parser.add_argument("--allocation-unit-bytes", required=True, type=int)
    parser.add_argument("--durability-probe-json", type=Path)
    parser.add_argument("--allocation-probe-json", type=Path)
    parser.add_argument(
        "--execution-contract",
        choices=(HISTORICAL_EXECUTION_CONTRACT, FIX001_EXECUTION_CONTRACT),
        default=HISTORICAL_EXECUTION_CONTRACT,
    )
    args = parser.parse_args()
    if not 0 <= args.memory_free_percent <= 100:
        raise ValueError("memory free percent out of range")
    if args.admission_memory_ceiling_bytes > args.physical_memory_bytes:
        raise ValueError("admission memory ceiling exceeds physical memory")
    semantic = read_semantic_results(args.semantic_results)
    durability_probe = read_durability_probe(args.durability_probe_json)
    allocation_probe = read_allocation_probe(args.allocation_probe_json)
    terms = declared_terms()
    output = []
    for case_id in CASES:
        identity = semantic[case_id]
        rows = int(identity["row_count"])
        primitive = int(identity["primitive_count"])
        bstar = int(identity["bstar_count"])
        format_row = project_format(
            case_id, rows, primitive, bstar,
            "STAGE_A_V3_COMPLETE_DESCRIPTOR_BOUND",
        )
        for backend in BACKENDS:
            fix001 = args.execution_contract == FIX001_EXECUTION_CONTRACT
            charge = charge_backend(
                f"{case_id}_{backend.lower()}_proposal", format_row, backend,
                "EXACT_RESOURCE_PROPOSAL_NOT_MEASURED", "BACKEND_ONLY",
                terms, not fix001,
            )
            execution_charge = (
                fix001_execution_charge(format_row, charge, terms)
                if fix001 else None
            )
            if backend != "COMPACT_IN_MEMORY":
                projection = (
                    construction_projection if backend == "TILED_DISK"
                    else lambda row, **kwargs: flat_file_construction_projection(
                        row, backend, **kwargs
                    )
                )
                disk = projection(
                    format_row,
                    allocation_unit=args.allocation_unit_bytes,
                    temp_directory_metadata_bound=mib(1),
                    final_directory_metadata_bound=mib(1),
                    disk_safety_reserve=mib(64),
                )
                requested_durability = "DURABLE_PUBLISH_V1"
                if durability_probe is None:
                    effective_durability = "UNSUPPORTED_PENDING_CAPABILITY_PROBE"
                    success_state = "NONE"
                    durability_capabilities_pass = False
                    capability_values = {
                        name: "NOT_PROBED" for name in (
                            "component_file_sync", "temporary_directory_sync",
                            "atomic_no_replace", "parent_directory_sync",
                            "manifest_file_sync", "final_directory_sync",
                        )
                    }
                    unsupported_reason = "CAPABILITIES_NOT_PROBED_TIMING_SUSPENDED"
                else:
                    durability_capabilities_pass = bool(
                        durability_probe["durable_publish_v1_supported"]
                    )
                    effective_durability = (
                        "DURABLE_PUBLISH_V1" if durability_capabilities_pass
                        else "UNSUPPORTED"
                    )
                    success_state = (
                        "OPEN_VALIDATED_READONLY" if durability_capabilities_pass
                        else "NONE"
                    )
                    capability_values = {
                        name: (
                            durability_probe["capabilities"][name]["status"]
                            + ":"
                            + durability_probe["capabilities"][name]["primitive"]
                        )
                        for name in durability_probe["capabilities"]
                    }
                    unsupported_reason = (
                        "NONE" if durability_capabilities_pass
                        else "ONE_OR_MORE_REQUIRED_DURABILITY_PRIMITIVES_UNSUPPORTED"
                    )
                cleanup = "SAME_PARENT_TEMP_REMOVAL_ONLY_AFTER_FAILURE_REVIEW"
                if backend == "ROW_MAJOR_DISK":
                    allocation_capabilities_pass = True
                    physical_allocation_capability = (
                        "PASS_BY_FULL_SEQUENTIAL_APPEND_NO_SPARSE_SHORTCUT"
                    )
                else:
                    if allocation_probe is None:
                        allocation_capabilities_pass = False
                        physical_allocation_capability = (
                            "NOT_PROBED_SEPARATE_STAGE_A_PREALLOCATION_NO_HOLE_GATE"
                        )
                        allocation_reason = (
                            "PHYSICAL_PREALLOCATION_NO_HOLE_CAPABILITY_NOT_PROBED"
                        )
                    else:
                        case = allocation_probe["cases"][backend]
                        allocation_capabilities_pass = case["status"] == "PASS"
                        physical_allocation_capability = (
                            case["status"] + ":" +
                            case.get("allocation_primitive", "NONE")
                        )
                        allocation_reason = (
                            "NONE" if allocation_capabilities_pass else
                            "PHYSICAL_PREALLOCATION_NO_HOLE_CAPABILITY_UNSUPPORTED"
                        )
                    if allocation_reason != "NONE":
                        unsupported_reason = (
                            allocation_reason if unsupported_reason == "NONE" else
                            unsupported_reason + ";" + allocation_reason
                        )
            else:
                disk = {
                    "temporary_allocated_upper_bytes": 0,
                    "published_exact_bytes": 0,
                    "publication_allocated_high_water_bytes": 0,
                    "disk_safety_reserve_bytes": 0,
                    "admission_free_space_bytes": 0,
                }
                requested_durability = "NOT_APPLICABLE_COMPACT_MEMORY"
                effective_durability = "NOT_APPLICABLE_COMPACT_MEMORY"
                success_state = "COMPACT_READONLY_PILOT_OBJECT"
                capability_values = {
                    name: "NOT_APPLICABLE" for name in (
                        "component_file_sync", "temporary_directory_sync",
                        "atomic_no_replace", "parent_directory_sync",
                        "manifest_file_sync", "final_directory_sync",
                    )
                }
                durability_capabilities_pass = True
                allocation_capabilities_pass = True
                physical_allocation_capability = "NOT_APPLICABLE_COMPACT_MEMORY"
                unsupported_reason = "NOT_APPLICABLE"
                cleanup = "DROP_IN_MEMORY_PILOT_OBJECT_AFTER_EVIDENCE_HANDOFF"
            memory_required = int(
                execution_charge["stage_a_admission_required_bytes"]
                if execution_charge is not None
                else charge["admission_required_bytes"]
            )
            disk_required = int(disk["admission_free_space_bytes"])
            admission = evaluate_execution_admission(
                backend,
                memory_required,
                args.admission_memory_ceiling_bytes,
                disk_required,
                args.available_disk_bytes,
                durability_capabilities_pass,
                allocation_capabilities_pass,
            )
            if admission["execution_admission"] == "PASS":
                status = "EXECUTION_ADMISSION_PASS_BUT_TIMING_SUSPENDED"
            else:
                status = f"{admission['execution_admission']}_AND_TIMING_SUSPENDED"
                success_state = "NONE"
            output.append({
                "proposal_schema": (
                    FIX001_PROPOSAL_SCHEMA if fix001 else PROPOSAL_SCHEMA
                ),
                "execution_contract": args.execution_contract,
                "proposal_status": status,
                "resource_projection_result": "PASS",
                "memory_ok": admission["memory_ok"],
                "disk_ok": admission["disk_ok"],
                "durability_capabilities_ok":
                    admission["durability_capabilities_ok"],
                "allocation_capabilities_ok":
                    admission["allocation_capabilities_ok"],
                "memory_admission": admission["memory_admission"],
                "disk_admission": admission["disk_admission"],
                "execution_resource_admission":
                    admission["execution_resource_admission"],
                "execution_allocation_admission":
                    admission["execution_allocation_admission"],
                "execution_durability_admission":
                    admission["execution_durability_admission"],
                "execution_admission": admission["execution_admission"],
                "capture_time": args.capture_time,
                "host_id": args.host_id,
                "os_build": args.os_build,
                "filesystem": args.filesystem,
                "destination": args.destination,
                "physical_memory_bytes": args.physical_memory_bytes,
                "observed_memory_free_percent": args.memory_free_percent,
                "observed_available_memory_bytes": "NOT_EXACTLY_REPORTED_BY_OS",
                "admission_memory_ceiling_policy": "50_PERCENT_OF_PHYSICAL_MEMORY",
                "admission_memory_ceiling_bytes": args.admission_memory_ceiling_bytes,
                "available_local_disk_bytes": args.available_disk_bytes,
                "formula_id": FORMULA,
                "case_id": case_id,
                "complete_descriptor_sha256": identity["complete_descriptor_sha256"],
                "species_authority_sha256": identity["species_authority_sha256"],
                "gene_registry_sha256": identity["gene_registry_sha256"],
                "bstar_registry_sha256": identity["bstar_registry_sha256"],
                "numeric_coordinate_registry_sha256":
                    identity["numeric_coordinate_registry_sha256"],
                "state_stream_sha256": identity["state_stream_sha256"],
                "numeric_stream_sha256": identity["numeric_stream_sha256"],
                "validity_stream_sha256": identity["validity_stream_sha256"],
                "rows": rows,
                "primitive_columns": primitive,
                "bstar_columns": bstar,
                "numeric_columns": primitive + bstar,
                "backend": backend,
                "layout": {
                    "COMPACT_IN_MEMORY": "COMPACT_CONTIGUOUS_V1",
                    "ROW_MAJOR_DISK": "ROW_MAJOR_FILE_V1",
                    "COLUMN_MAJOR_DISK": "COLUMN_MAJOR_FILE_V1",
                    "TILED_DISK": "TILED_ROW_MAJOR_PROVISIONAL_256X256",
                }[backend],
                "construction_algorithm": charge["writer_construction_algorithm"],
                "requested_durability_profile": requested_durability,
                "effective_durability_profile": effective_durability,
                "eligible_success_state": success_state,
                "component_file_sync": capability_values["component_file_sync"],
                "temporary_directory_sync": capability_values["temporary_directory_sync"],
                "atomic_no_replace": capability_values["atomic_no_replace"],
                "parent_directory_sync": capability_values["parent_directory_sync"],
                "manifest_file_sync": capability_values["manifest_file_sync"],
                "final_directory_sync": capability_values["final_directory_sync"],
                "unsupported_capability_reason": unsupported_reason,
                "physical_allocation_capability":
                    physical_allocation_capability,
                "row_write_behavior": disk.get(
                    "row_write_behavior",
                    "DIRECT_ARRAY_COPY" if backend == "COMPACT_IN_MEMORY"
                    else "SEQUENTIAL_ROWS_SCATTERED_TO_INITIALIZED_TILES",
                ),
                "row_read_behavior": disk.get(
                    "row_read_behavior",
                    "DIRECT_ARRAY_SLICE" if backend == "COMPACT_IN_MEMORY"
                    else "TILED_PREAD_ROW_SEGMENTS",
                ),
                "column_read_behavior": disk.get(
                    "column_read_behavior",
                    "STRIDED_ARRAY_GATHER" if backend == "COMPACT_IN_MEMORY"
                    else "TILED_PREAD_COLUMN_BLOCKS",
                ),
                "row_major_spool_bytes": disk.get("row_major_spool_bytes", 0),
                "temporary_binary_bytes": disk.get("temporary_binary_bytes", 0),
                "candidate_total_bytes_written": disk.get(
                    "candidate_total_bytes_written", 0
                ),
                "backend_native_state_bytes": charge["backend_native_state_bytes"],
                "backend_native_numeric_bytes": charge["backend_native_numeric_bytes"],
                "backend_native_validity_bytes": charge["backend_native_validity_bytes"],
                "backend_native_index_or_lookup_bytes":
                    charge["backend_native_index_or_lookup_bytes"],
                "state_row_staging_bytes": charge["state_row_staging_bytes"],
                "numeric_row_staging_bytes": charge["numeric_row_staging_bytes"],
                "validity_row_staging_bytes": charge["validity_row_staging_bytes"],
                "writer_tile_or_slab_bytes": charge["writer_tile_or_slab_bytes"],
                "writer_initialization_chunk_bytes":
                    charge["writer_initialization_chunk_bytes"],
                "production_validator_algorithm":
                    charge["production_validator_algorithm"],
                "production_validator_access_profile":
                    charge["production_validator_access_profile"],
                "production_validator_state_segment_bytes":
                    charge["production_validator_state_segment_bytes"],
                "production_validator_numeric_segment_bytes":
                    charge["production_validator_numeric_segment_bytes"],
                "production_validator_validity_segment_bytes":
                    charge["production_validator_validity_segment_bytes"],
                "production_validator_standard_semantic_segment_bytes":
                    charge["production_validator_standard_semantic_segment_bytes"],
                "production_validator_composite_occupancy_bytes":
                    charge["production_validator_composite_occupancy_bytes"],
                "production_validator_composite_bstar_validity_window_bytes":
                    charge[
                        "production_validator_composite_bstar_validity_window_bytes"
                    ],
                "production_validator_composite_segment_bytes":
                    charge["production_validator_composite_segment_bytes"],
                "production_validator_tile_or_segment_bytes":
                    charge["production_validator_tile_or_segment_bytes"],
                "production_validator_primitive_segment_count":
                    charge["production_validator_primitive_segment_count"],
                "production_validator_bstar_validity_window_count":
                    charge["production_validator_bstar_validity_window_count"],
                "production_validator_composite_state_read_bytes":
                    charge["production_validator_composite_state_read_bytes"],
                "production_validator_composite_bstar_validity_rescan_windows":
                    charge[
                        "production_validator_composite_bstar_validity_rescan_windows"
                    ],
                "production_validator_composite_bstar_source_read_bytes_upper":
                    charge[
                        "production_validator_composite_bstar_source_read_bytes_upper"
                    ],
                "production_validator_composite_bstar_source_read_ops_upper":
                    charge[
                        "production_validator_composite_bstar_source_read_ops_upper"
                    ],
                "production_validator_registry_entry_segment_probes_upper":
                    charge[
                        "production_validator_registry_entry_segment_probes_upper"
                    ],
                "production_validator_logical_packer_bytes":
                    charge["production_validator_logical_packer_bytes"],
                "production_validator_internal_peak_bytes":
                    charge["production_validator_internal_peak_bytes"],
                "production_validator_bytes": charge["production_validator_bytes"],
                "independent_validator_algorithm":
                    charge["independent_validator_algorithm"],
                "independent_validator_access_profile":
                    charge["independent_validator_access_profile"],
                "independent_validator_standard_semantic_segment_bytes":
                    charge["independent_validator_standard_semantic_segment_bytes"],
                "independent_validator_composite_segment_bytes":
                    charge["independent_validator_composite_segment_bytes"],
                "independent_validator_tile_or_segment_bytes":
                    charge["independent_validator_tile_or_segment_bytes"],
                "independent_validator_bytes": charge["independent_validator_bytes"],
                "r_state_output_type": charge["r_state_output_type"],
                "r_state_output_bytes": charge["r_state_output_bytes"],
                "r_numeric_output_type": charge["r_numeric_output_type"],
                "r_numeric_output_bytes": charge["r_numeric_output_bytes"],
                "r_materialization_requested":
                    charge["r_materialization_requested"],
                "r_materialization_status": charge["r_materialization_status"],
                "r_materialization_admission_contribution_bytes": (
                    0 if fix001 else charge["r_materialization_peak_live_bytes"]
                ),
                "r_dimnames_and_registry_bytes": charge["r_dimnames_and_registry_bytes"],
                "r_conversion_scratch_bytes": charge["r_conversion_scratch_bytes"],
                "r_allocator_and_object_overhead_bytes":
                    charge["r_allocator_and_object_overhead_bytes"],
                "construction_peak_live_bytes": charge["construction_peak_live_bytes"],
                "finalization_hash_peak_live_bytes":
                    charge["finalization_hash_peak_live_bytes"],
                "production_validation_peak_live_bytes":
                    charge["production_validation_peak_live_bytes"],
                "independent_validation_peak_live_bytes":
                    charge["independent_validation_peak_live_bytes"],
                "r_materialization_peak_live_bytes":
                    charge["r_materialization_peak_live_bytes"],
                "overall_max_live_bytes": charge["overall_max_live_bytes"],
                "memory_safety_reserve_bytes": charge["safety_reserve_bytes"],
                "pilot_full_logical_read_requested": str(fix001).upper(),
                "pilot_logical_hash_requested": str(fix001).upper(),
                "pilot_bounded_validation_requested": str(fix001).upper(),
                **(execution_charge or {}),
                "admission_required_memory_bytes": memory_required,
                "memory_margin_bytes": admission["memory_margin_bytes"],
                "temporary_allocated_high_water_bytes":
                    disk["temporary_allocated_upper_bytes"],
                "final_exact_bytes": disk["published_exact_bytes"],
                "publication_allocated_high_water_bytes":
                    disk["publication_allocated_high_water_bytes"],
                "disk_safety_reserve_bytes": disk["disk_safety_reserve_bytes"],
                "admission_required_free_disk_bytes": disk_required,
                "disk_margin_bytes": admission["disk_margin_bytes"],
                "cleanup_recovery_path": cleanup,
                "timing_executed": "FALSE",
                "allocation_or_backend_mutation_executed": "FALSE",
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(output[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(output)
    print(f"STAGE_A_ADMISSION_PROPOSAL_PASS {len(output)}/{len(output)} NO_TIMING")


if __name__ == "__main__":
    main()
