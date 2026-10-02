#!/usr/bin/env python3
"""Parameterized physical Stage-B worker frozen by EXEC-PREFLIGHT001-FIX002.

The bounded descriptor and future authority descriptors use the same
``DescriptorCase`` and backend path.  FIX002 only authorizes the small case;
large requests stop in the shared prelaunch guard before this module allocates
or launches any backend.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import math
import os
import platform
import resource
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
PILOT = ENGINE / "pilot"
for value in (HERE, PILOT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from fix001_contract import (  # noqa: E402
    MAX_INT64,
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    strict_json_load,
    write_canonical_json,
)
from stage_b_authorization import load_exact_runtime_resource_capture  # noqa: E402
from stage_a_prototypes import (  # noqa: E402
    BACKENDS,
    PackedValidityStream,
    reopen_backend,
)
from stage_b_durable_publish import (  # noqa: E402
    durable_publish,
    durable_publish_barriers,
    publication_evidence_hashes,
    tree_sha256,
    write_race_result,
)
from stage_b_runtime_contract import (  # noqa: E402
    BOUNDED_MODE,
    FULL_SCAN_ALGORITHM,
    FULL_SCAN_BLOCK_ROWS,
    METRIC_HANDLERS,
    OPERATION_CONTRACT,
    WORKER_RESULT_SCHEMA,
    DescriptorCase,
    FrozenMetricPlan,
    prelaunch_guard,
)


DURATION_METRICS = {
    "allocation_initialization", "row_construction", "finalization",
    "bounded_validation", "row_read_sample", "column_extraction_sample",
    "block_read_sample", "full_logical_read", "physical_component_hashing",
    "logical_hash_reconstruction", "same_process_reopen",
    "fresh_process_reopen_internal_open", "fresh_process_reopen_total",
    "publication_durability_barriers", "worker_end_to_end",
}


def expected_final_component_sizes(candidate: str, case: DescriptorCase) -> Dict[str, int]:
    if candidate == "COMPACT_IN_MEMORY":
        return {}
    if candidate in {"ROW_MAJOR_DISK", "COLUMN_MAJOR_DISK"}:
        return {
            "STATE.bin": 256 + case.rows * case.primitive,
            "NUMERIC.bin": 256 + case.rows * case.numeric * 8,
            "VALIDITY.bin": 256 + (case.rows * case.numeric + 7) // 8,
            "TILE_INDEX.bin": 0,
            "COMPLETION.bin": 512,
            "VALIDATED": 1024,
        }
    row_tiles = (case.rows + 255) // 256
    state_tiles = row_tiles * ((case.primitive + 255) // 256)
    numeric_tiles = row_tiles * ((case.numeric + 255) // 256)
    return {
        "STATE.bin": 256 + state_tiles * 65536,
        "NUMERIC.bin": 256 + numeric_tiles * 524288,
        "VALIDITY.bin": 256 + numeric_tiles * 8192,
        "TILE_INDEX.bin": 256 + (state_tiles + 2 * numeric_tiles) * 128,
        "COMPLETION.bin": 512,
        "VALIDATED": 1024,
    }


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def disk_snapshot(root: Path) -> Dict[str, Any]:
    files = []
    logical = physical = 0
    all_no_hole = True
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            observed = path.stat()
            allocated = int(getattr(observed, "st_blocks", 0)) * 512
            if allocated == 0 and observed.st_size:
                allocated = observed.st_size
            no_hole = allocated >= observed.st_size
            logical += observed.st_size
            physical += allocated
            all_no_hole = all_no_hole and no_hole
            files.append({
                "path": path.relative_to(root).as_posix(),
                "logical_bytes": observed.st_size,
                "physical_allocated_bytes": allocated,
                "no_hole": no_hole,
            })
    return {
        "logical_bytes": logical,
        "physical_allocated_bytes": physical,
        "all_files_no_hole": all_no_hole,
        "files": files,
    }


def timed(operation: Callable[[], Any]) -> Tuple[Any, int]:
    start = time.perf_counter_ns()
    value = operation()
    elapsed = max(1, time.perf_counter_ns() - start)
    if elapsed > MAX_INT64:
        raise RuntimeError("duration escaped signed int64")
    return value, elapsed


class MetricRecorder:
    def __init__(self, plan: FrozenMetricPlan):
        self.plan = plan
        self.values: Dict[str, int] = {}
        self.status: Dict[str, str] = {}

    def run(self, metric_id: str, operation: Callable[[], Any]) -> Any:
        if metric_id in self.values or metric_id not in METRIC_HANDLERS:
            raise AssertionError(f"metric execution cardinality:{metric_id}")
        value, elapsed = timed(operation)
        self.values[metric_id] = elapsed
        self.status[metric_id] = "MEASURED_BOUNDED_NON_AUTHORITATIVE"
        return value

    def record(self, metric_id: str, value: int, status: str) -> None:
        if metric_id in self.values or metric_id not in METRIC_HANDLERS:
            raise AssertionError(f"metric execution cardinality:{metric_id}")
        if type(value) is not int or not 0 <= value <= MAX_INT64:
            raise AssertionError(f"metric integer contract:{metric_id}")
        self.values[metric_id] = value
        self.status[metric_id] = status

    def finish(self) -> None:
        if set(self.values) != set(METRIC_HANDLERS):
            missing = sorted(set(METRIC_HANDLERS) - set(self.values))
            extra = sorted(set(self.values) - set(METRIC_HANDLERS))
            raise AssertionError(f"19 metric coverage:missing={missing};extra={extra}")


def _accumulate_duration(total: int, elapsed: int) -> int:
    output = total + elapsed
    if output > MAX_INT64:
        raise RuntimeError("accumulated duration escaped signed int64")
    return output


def _elapsed_since(start_ns: int) -> int:
    elapsed = max(1, time.perf_counter_ns() - start_ns)
    if elapsed > MAX_INT64:
        raise RuntimeError("duration escaped signed int64")
    return elapsed


class ExpectedProbeOracle:
    """Bounded expected-value cache populated from already-generated rows.

    Only frozen sample rows, frozen sample columns, and frozen sample blocks are
    retained.  It never owns or regenerates the complete logical matrix.
    """

    def __init__(self, case: DescriptorCase, plan: FrozenMetricPlan):
        self.case = case
        self.row_indices = plan.row_indices(case.rows)
        self.column_indices = {
            "state": plan.column_indices(case.primitive),
            "numeric": plan.column_indices(case.numeric),
            "validity": plan.column_indices(case.numeric),
        }
        self.blocks = {
            "state": plan.blocks(case.rows, case.primitive),
            "numeric": plan.blocks(case.rows, case.numeric),
            "validity": plan.blocks(case.rows, case.numeric),
        }
        self.rows: Dict[int, Tuple[bytes, bytes, bytes]] = {}
        self.columns = {
            (component, column): bytearray()
            for component, indices in self.column_indices.items()
            for column in indices
        }
        self.block_values = {
            (component, block): bytearray()
            for component, blocks in self.blocks.items()
            for block in blocks
        }
        self.observed_rows = 0

    @staticmethod
    def _slice(component: str, value: Tuple[bytes, bytes, bytes],
               column_start: int, column_count: int) -> bytes:
        source = {
            "state": value[0], "numeric": value[1], "validity": value[2],
        }[component]
        multiplier = 8 if component == "numeric" else 1
        start = column_start * multiplier
        return source[start:start + column_count * multiplier]

    def observe(self, row: int, value: Tuple[bytes, bytes, bytes]) -> None:
        if row != self.observed_rows:
            raise AssertionError(f"probe oracle row order:{row}")
        if row in self.row_indices:
            self.rows[row] = value
        for component, indices in self.column_indices.items():
            for column in indices:
                self.columns[(component, column)].extend(
                    self._slice(component, value, column, 1)
                )
        for component, blocks in self.blocks.items():
            for block in blocks:
                row_start, row_count, column_start, column_count = block
                if row_start <= row < row_start + row_count:
                    self.block_values[(component, block)].extend(
                        self._slice(component, value, column_start, column_count)
                    )
        self.observed_rows += 1

    def finish(self) -> None:
        if self.observed_rows != self.case.rows:
            raise AssertionError("probe oracle incomplete")
        if set(self.rows) != set(self.row_indices):
            raise AssertionError("probe oracle row set")

    def maximum_owned_bytes(self) -> int:
        return (
            sum(sum(len(component) for component in value) for value in self.rows.values())
            + sum(len(value) for value in self.columns.values())
            + sum(len(value) for value in self.block_values.values())
        )


def build_rows(
        backend: Any, case: DescriptorCase,
        probe_oracle: Optional[ExpectedProbeOracle] = None) -> int:
    """Generate payload outside, then accumulate only write_row call time."""
    authoritative_ns = 0
    for row in range(case.rows):
        value = case.row(row)
        if probe_oracle is not None:
            probe_oracle.observe(row, value)
        start_ns = time.perf_counter_ns()
        backend.write_row(row, *value)
        elapsed = _elapsed_since(start_ns)
        authoritative_ns = _accumulate_duration(authoritative_ns, elapsed)
    if probe_oracle is not None:
        probe_oracle.finish()
    return authoritative_ns


def expected_block(
        case: DescriptorCase, component: str,
        block: Tuple[int, int, int, int]) -> bytes:
    row_start, row_count, column_start, column_count = block
    output = bytearray()
    for row in range(row_start, row_start + row_count):
        state, numeric, validity = case.row(row)
        if component == "state":
            output.extend(state[column_start:column_start + column_count])
        elif component == "numeric":
            output.extend(
                numeric[column_start * 8:(column_start + column_count) * 8]
            )
        else:
            output.extend(validity[column_start:column_start + column_count])
    return bytes(output)


def frozen_bounded_validator(backend: Any, case: DescriptorCase) -> Dict[str, Any]:
    """Execute the sole frozen production-scale semantic algorithm."""
    segment_width = 256
    state_cells = numeric_cells = validity_cells = 0
    primitive_segments = validity_rescans = registry_probes = 0
    member_checks = overlap_checks = active_bstar_segment_visits = 0
    max_standard = max_composite = 0

    def bit(raw: bytes, index: int) -> int:
        return (raw[index // 8] >> (index % 8)) & 1

    # Standard state/numeric/validity pass, bounded to 256 coordinates.
    for row in range(case.rows):
        for start in range(0, case.numeric, segment_width):
            count = min(segment_width, case.numeric - start)
            numeric = backend.read_block("numeric", row, 1, start, count)
            validity = backend.read_validity_window_packed(row, start, count)
            state_count = (
                max(0, min(count, case.primitive - start))
                if start < case.primitive else 0
            )
            state = (
                backend.read_block("state", row, 1, start, state_count)
                if state_count else b""
            )
            max_standard = max(
                max_standard, len(state) + len(numeric) + len(validity),
            )
            for local in range(count):
                available = bit(validity, local)
                bits = numeric[local * 8:(local + 1) * 8]
                if available:
                    if not math.isfinite(struct.unpack("<d", bits)[0]):
                        raise StopSignal("E3_NUMERIC", f"nonfinite:{row}:{start + local}")
                elif bits != bytes(8):
                    raise StopSignal("E3_NUMERIC", f"invalid_nonzero:{row}:{start + local}")
                numeric_cells += 1
                validity_cells += 1
            for local, state_value in enumerate(state):
                primitive_id = start + local
                if state_value > 3:
                    raise StopSignal("E3_STATE", f"domain:{row}:{primitive_id}")
                if state_value != 0 and bit(validity, local):
                    raise StopSignal(
                        "E3_PRIMITIVE_ROW_CONSISTENCY",
                        f"nonmapped_available:{row}:{primitive_id}",
                    )
                if case.terminals[primitive_id] and state_value == 3:
                    raise StopSignal(
                        "E3_PRIMITIVE_ROW_CONSISTENCY",
                        f"terminal_na_topo:{row}:{primitive_id}",
                    )
                state_cells += 1

    # CompositeRowConsistency-v1 multipass with segment-local occupancy.
    members = case.descriptor["bstar_members"]
    for row in range(case.rows):
        for start in range(0, case.primitive, segment_width):
            count = min(segment_width, case.primitive - start)
            state = backend.read_block("state", row, 1, start, count)
            occupied = bytearray((count + 7) // 8)
            primitive_segments += 1
            for window_start in range(0, case.bstar, segment_width):
                window_count = min(segment_width, case.bstar - window_start)
                validity = backend.read_validity_window_packed(
                    row, case.primitive + window_start, window_count,
                )
                validity_rescans += 1
                max_composite = max(
                    max_composite, len(state) + len(occupied) + len(validity),
                )
                for local_bstar in range(window_count):
                    bstar_id = window_start + local_bstar
                    registry_probes += 1
                    if not bit(validity, local_bstar):
                        continue
                    active_bstar_segment_visits += 1
                    fiber = members[bstar_id]
                    left = bisect.bisect_left(fiber, start)
                    right = bisect.bisect_left(fiber, start + count, left)
                    for member in fiber[left:right]:
                        local = member - start
                        member_checks += 1
                        if state[local] != 2:
                            raise StopSignal(
                                "E3_COMPOSITE_ROW_CONSISTENCY",
                                f"active_bstar_non_na_fuse:{row}:{bstar_id}:{member}",
                            )
                        overlap_checks += 1
                        mask = 1 << (local % 8)
                        if occupied[local // 8] & mask:
                            raise StopSignal(
                                "E3_COMPOSITE_ROW_CONSISTENCY",
                                f"active_bstar_overlap:{row}:{bstar_id}:{member}",
                            )
                        occupied[local // 8] |= mask
    return {
        "validator_id": "MULTIPASS_ROW_SEGMENT_V1",
        "semantic_contracts": [
            "PrimitiveRowConsistency-v1", "CompositeRowConsistency-v1",
        ],
        "access_profile": {
            "COMPACT_IN_MEMORY": "COMPACT_LOGICAL_ARRAY_ACCESS_V1",
            "ROW_MAJOR_DISK": "ROW_MAJOR_PREAD_ACCESS_V1",
            "COLUMN_MAJOR_DISK": "COLUMN_MAJOR_GATHER_ACCESS_V1",
            "TILED_DISK": "TILED_PREAD_ACCESS_V1",
        }[next(key for key, value in BACKENDS.items() if isinstance(backend, value))],
        "status": "PASS",
        "rows_checked": case.rows,
        "state_cells_checked": state_cells,
        "numeric_cells_checked": numeric_cells,
        "validity_cells_checked": validity_cells,
        "primitive_segment_width": segment_width,
        "bstar_validity_window_width": segment_width,
        "primitive_segment_count": primitive_segments,
        "bstar_validity_window_rescans": validity_rescans,
        "registry_probes": registry_probes,
        "member_checks": member_checks,
        "overlap_checks": overlap_checks,
        "active_bstar_segment_visits": active_bstar_segment_visits,
        "maximum_standard_live_buffer_bytes": max_standard,
        "maximum_composite_live_buffer_bytes": max_composite,
        "complete_owned_matrix_bytes": 0,
    }


def row_read_sample(
        backend: Any, oracle: ExpectedProbeOracle,
        comparison_hook: Optional[Callable[[], None]] = None
        ) -> Tuple[Dict[str, Any], int]:
    authoritative_ns = 0
    for row in oracle.row_indices:
        start_ns = time.perf_counter_ns()
        observed = backend.read_row(row)
        elapsed = _elapsed_since(start_ns)
        authoritative_ns = _accumulate_duration(authoritative_ns, elapsed)
        if comparison_hook is not None:
            comparison_hook()
        if observed != oracle.rows[row]:
            raise AssertionError(f"row read sample:{row}")
    return ({
        "indices": list(oracle.row_indices),
        "checks": len(oracle.row_indices), "status": "PASS",
        "timing_boundary": "BACKEND_READ_ROW_ONLY",
    }, authoritative_ns)


def column_extraction_sample(
        backend: Any, oracle: ExpectedProbeOracle,
        comparison_hook: Optional[Callable[[], None]] = None
        ) -> Tuple[Dict[str, Any], int]:
    output = []
    authoritative_ns = 0
    for component in ("state", "numeric", "validity"):
        indices = oracle.column_indices[component]
        for column in indices:
            start_ns = time.perf_counter_ns()
            observed = backend.read_column(component, column)
            elapsed = _elapsed_since(start_ns)
            authoritative_ns = _accumulate_duration(authoritative_ns, elapsed)
            if comparison_hook is not None:
                comparison_hook()
            if observed != bytes(oracle.columns[(component, column)]):
                raise AssertionError(f"column sample:{component}:{column}")
        output.append({"component": component, "indices": list(indices)})
    return ({
        "components": output,
        "checks": sum(len(value["indices"]) for value in output),
        "status": "PASS", "timing_boundary": "BACKEND_READ_COLUMN_ONLY",
    }, authoritative_ns)


def block_read_sample(
        backend: Any, oracle: ExpectedProbeOracle,
        comparison_hook: Optional[Callable[[], None]] = None
        ) -> Tuple[Dict[str, Any], int]:
    output = []
    authoritative_ns = 0
    for component in ("state", "numeric", "validity"):
        blocks = oracle.blocks[component]
        for block in blocks:
            start_ns = time.perf_counter_ns()
            observed = backend.read_block(component, *block)
            elapsed = _elapsed_since(start_ns)
            authoritative_ns = _accumulate_duration(authoritative_ns, elapsed)
            if comparison_hook is not None:
                comparison_hook()
            if observed != bytes(oracle.block_values[(component, block)]):
                raise AssertionError(f"block sample:{component}:{block}")
        output.append({
            "component": component,
            "blocks": [list(value) for value in blocks],
        })
    return ({
        "components": output,
        "checks": sum(len(value["blocks"]) for value in output),
        "status": "PASS", "timing_boundary": "BACKEND_READ_BLOCK_ONLY",
    }, authoritative_ns)


def publish_barriers_with_prepublication_evidence(
        temp_target: Path, final_target: Path,
        barrier_operation=durable_publish_barriers,
        hash_operation=tree_sha256) -> Tuple[Dict[str, Any], int, str]:
    """Hash private bytes, then time only barriers; defer final-tree hashing.

    The caller must attach the published-tree evidence only after all reopen
    decision metrics, so that evidence scans cannot warm their filesystem cache.
    """
    before = hash_operation(temp_target)
    start_ns = time.perf_counter_ns()
    barriers = barrier_operation(temp_target, final_target)
    authoritative_ns = _elapsed_since(start_ns)
    return dict(barriers), authoritative_ns, before


def _packed_validity_blocks(
        backend: Any, case: DescriptorCase) -> Iterable[bytes]:
    packer = PackedValidityStream()
    for start in range(0, case.rows, FULL_SCAN_BLOCK_ROWS):
        count = min(FULL_SCAN_BLOCK_ROWS, case.rows - start)
        block = backend.read_block("validity", start, count, 0, case.numeric)
        yield from packer.feed(block)
    yield from packer.finish()


def bounded_full_logical_scan(
        backend: Any, case: DescriptorCase) -> Dict[str, Any]:
    logical = hashlib.sha256()
    logical.update(b"SplitAlignerR/MatrixLogicalContent/v1\0")
    logical.update(struct.pack(
        "<HHQQQQ", 1, 0, case.rows, case.primitive, case.bstar, case.numeric,
    ))
    for authority in case.authorities:
        logical.update(authority)
    output: Dict[str, Any] = {
        "algorithm": FULL_SCAN_ALGORITHM,
        "component_order": ["STATE", "NUMERIC", "VALIDITY"],
        "maximum_logical_block_rows": FULL_SCAN_BLOCK_ROWS,
        "complete_owned_logical_result_bytes": 0,
        "r_materialization_bytes": 0,
    }
    max_buffer = 0
    for component, columns, cell_bytes in (
            ("state", case.primitive, 1), ("numeric", case.numeric, 8)):
        digest = hashlib.sha256()
        length = case.rows * columns * cell_bytes
        logical.update(struct.pack("<Q", length))
        observed = 0
        for start in range(0, case.rows, FULL_SCAN_BLOCK_ROWS):
            count = min(FULL_SCAN_BLOCK_ROWS, case.rows - start)
            block = backend.read_block(component, start, count, 0, columns)
            observed += len(block)
            max_buffer = max(max_buffer, len(block))
            digest.update(block)
            logical.update(block)
        if observed != length:
            raise AssertionError(f"full scan length:{component}")
        output[f"{component}_stream_sha256"] = digest.hexdigest()
    validity_digest = hashlib.sha256()
    validity_length = (case.rows * case.numeric + 7) // 8
    logical.update(struct.pack("<Q", validity_length))
    observed = 0
    for block in _packed_validity_blocks(backend, case):
        observed += len(block)
        max_buffer = max(max_buffer, len(block))
        validity_digest.update(block)
        logical.update(block)
    if observed != validity_length:
        raise AssertionError("full scan length:validity")
    output.update({
        "validity_stream_sha256": validity_digest.hexdigest(),
        "logical_content_sha256": logical.hexdigest(),
        "actual_max_live_scan_buffer_bytes": max_buffer,
    })
    expected = {
        "state_stream_sha256": case.anchor["state_stream_sha256"],
        "numeric_stream_sha256": case.anchor["numeric_stream_sha256"],
        "validity_stream_sha256": case.anchor["validity_stream_sha256"],
        "logical_content_sha256": case.anchor["logical_content_sha256"],
    }
    observed_hashes = {
        "state_stream_sha256": output["state_stream_sha256"],
        "numeric_stream_sha256": output["numeric_stream_sha256"],
        "validity_stream_sha256": output["validity_stream_sha256"],
        "logical_content_sha256": output["logical_content_sha256"],
    }
    if observed_hashes != expected:
        raise AssertionError("bounded scan frozen anchor mismatch")
    return output


def fresh_reopen(request_path: Path, output_path: Path) -> None:
    request = strict_json_load(request_path)
    required = {
        "schema", "backend", "target", "dimensions", "authorities",
        "expected_logical_content_sha256",
    }
    if set(request) != required or request["schema"] != "SplitAlignerR/ENGINE003FreshReopen/v3":
        raise ValueError("fresh reopen request schema")
    dimensions = request["dimensions"]
    authorities = tuple(bytes.fromhex(value) for value in request["authorities"])
    backend, elapsed = timed(lambda: reopen_backend(
        request["backend"], Path(request["target"]), dimensions["G"],
        dimensions["B"], dimensions["B_star"], authorities,
    ))
    try:
        logical = backend.logical_sha256()
    finally:
        backend.close()
    if logical != request["expected_logical_content_sha256"]:
        raise AssertionError("fresh reopen logical mismatch")
    write_canonical_json(output_path, {
        "schema": "SplitAlignerR/ENGINE003FreshReopenResult/v3",
        "status": "PASS", "internal_open_ns": elapsed,
        "logical_content_sha256": logical,
        "peak_rss_bytes": peak_rss_bytes(),
    })


def execute_live(
        repo_root: Path, runtime_root: Path, resource_path: Path,
        branch_resource_path: Path, durability_path: Path,
        request_path: Path, output_path: Path) -> None:
    overall_start = time.perf_counter_ns()
    progress_path = output_path.with_suffix(".partial.json")
    progress_target = {"value": "NOT_YET_BOUND"}

    def progress(last_completed: str, current: str) -> None:
        write_canonical_json(progress_path, {
            "schema": "SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1",
            "last_completed_phase": last_completed,
            "current_phase": current,
            "target": progress_target["value"],
        })

    progress("NONE", "PRELAUNCH_VALIDATION")
    request = strict_json_load(request_path)
    resource, _resource_raw = load_exact_runtime_resource_capture(
        resource_path, request.get("fresh_resource_capture_sha256"),
    )
    branch_resource, _branch_resource_raw = load_exact_runtime_resource_capture(
        branch_resource_path,
        request.get("workload_branch_resource_capture_sha256"),
    )
    durability = strict_json_load(durability_path)
    authority = ExecutionAuthority(
        repo_root, request["source_commit"], request["source_tree"],
    )
    assets = FrozenAssets(authority)
    guard = prelaunch_guard(
        authority, assets, request, runtime_root, resource, durability,
        branch_resource,
    )
    if guard["worker_launch_authorized"] is not True or guard["physical_allocation_authorized"] is not True:
        raise StopSignal("SB_STOP_ACTIVATION", "worker_guard")
    case: DescriptorCase = guard["case"]
    plan = FrozenMetricPlan(assets)
    recorder = MetricRecorder(plan)
    probe_oracle = ExpectedProbeOracle(case, plan)
    candidate = request["candidate_id"]
    final_target = Path(request["runtime_target"])
    progress_target["value"] = str(final_target)
    temp_target = final_target.with_name(final_target.name + ".partial")
    if temp_target.exists() or final_target.exists():
        raise StopSignal("SB_STOP_CLEANUP", "nonfresh_worker_target")
    backend = None
    snapshots = []
    try:
        progress("PRELAUNCH_VALIDATION", "ALLOCATION_INITIALIZATION")
        backend = recorder.run(
            "allocation_initialization",
            lambda: BACKENDS[candidate](
                temp_target, case.rows, case.primitive, case.bstar,
                case.authorities,
            ),
        )
        progress("ALLOCATION_INITIALIZATION", "ROW_CONSTRUCTION")
        snapshots.append({"phase": "AFTER_ALLOCATION", **disk_snapshot(temp_target)})
        row_construction_ns = build_rows(backend, case, probe_oracle)
        recorder.record(
            "row_construction", row_construction_ns,
            "MEASURED_BOUNDED_NON_AUTHORITATIVE",
        )
        progress("ROW_CONSTRUCTION", "FINALIZATION")
        snapshots.append({"phase": "AFTER_ROWS", **disk_snapshot(temp_target)})
        recorder.run("finalization", backend.finalize)
        progress("FINALIZATION", "BOUNDED_VALIDATION")
        snapshots.append({"phase": "AFTER_FINALIZATION", **disk_snapshot(temp_target)})
        if candidate != "COMPACT_IN_MEMORY" and not snapshots[-1]["all_files_no_hole"]:
            raise StopSignal("SB_STOP_CAPABILITY", "physical_allocation_no_hole")

        validator = recorder.run(
            "bounded_validation", lambda: frozen_bounded_validator(backend, case),
        )
        progress("BOUNDED_VALIDATION", "ACCESS_AND_INTEGRITY_PROBES")
        snapshots.append({
            "phase": "AFTER_MULTIPASS_VALIDATION_BEFORE_ARTIFACT_RETIREMENT",
            **disk_snapshot(temp_target),
        })
        spool_exists_during_construction = (
            candidate == "COLUMN_MAJOR_DISK"
            and (temp_target / "ROWSPOOL.bin").is_file()
        )
        artifact_retirement = backend.retire_construction_artifacts()
        snapshots.append({
            "phase": "AFTER_CONSTRUCTION_ARTIFACT_RETIREMENT",
            **disk_snapshot(temp_target),
        })
        if candidate == "COLUMN_MAJOR_DISK":
            if not spool_exists_during_construction:
                raise AssertionError("column spool absent during construction/validation")
            if (temp_target / "ROWSPOOL.bin").exists():
                raise AssertionError("column spool survived retirement")
        rows, row_read_ns = row_read_sample(backend, probe_oracle)
        recorder.record(
            "row_read_sample", row_read_ns,
            "MEASURED_BOUNDED_NON_AUTHORITATIVE",
        )
        columns, column_read_ns = column_extraction_sample(
            backend, probe_oracle,
        )
        recorder.record(
            "column_extraction_sample", column_read_ns,
            "MEASURED_BOUNDED_NON_AUTHORITATIVE",
        )
        blocks, block_read_ns = block_read_sample(backend, probe_oracle)
        recorder.record(
            "block_read_sample", block_read_ns,
            "MEASURED_BOUNDED_NON_AUTHORITATIVE",
        )
        scan = recorder.run(
            "full_logical_read", lambda: bounded_full_logical_scan(backend, case),
        )
        physical_hashes = recorder.run(
            "physical_component_hashing", backend.component_hashes,
        )
        if "ROWSPOOL.bin" in physical_hashes:
            raise AssertionError("construction spool entered final component hashes")
        reconstructed = recorder.run(
            "logical_hash_reconstruction", backend.logical_sha256,
        )
        if reconstructed != scan["logical_content_sha256"]:
            raise AssertionError("logical reconstruction mismatch")

        temporary_snapshot = disk_snapshot(temp_target)
        durability_result: Dict[str, Any]
        if candidate == "COMPACT_IN_MEMORY":
            backend.close()
            backend = None
            shutil.rmtree(temp_target)
            durability_result = {"status": "NOT_APPLICABLE_IN_MEMORY"}
            final_snapshot = {
                "logical_bytes": 0, "physical_allocated_bytes": 0,
                "all_files_no_hole": True, "files": [],
            }
            recorder.record("publication_durability_barriers", 0, "NOT_APPLICABLE")
            recorder.record("same_process_reopen", 0, "NOT_APPLICABLE")
            recorder.record("fresh_process_reopen_internal_open", 0, "NOT_APPLICABLE")
            recorder.record("fresh_process_reopen_total", 0, "NOT_APPLICABLE")
        else:
            progress("ACCESS_AND_INTEGRITY_PROBES", "DURABLE_PUBLICATION")
            backend.close()
            backend = None
            durability_result, publication_barrier_ns, prepublication_hash = (
                publish_barriers_with_prepublication_evidence(
                    temp_target, final_target,
                )
            )
            recorder.record(
                "publication_durability_barriers", publication_barrier_ns,
                "MEASURED_BOUNDED_NON_AUTHORITATIVE",
            )
            final_snapshot = disk_snapshot(final_target)
            expected_components = expected_final_component_sizes(candidate, case)
            observed_components = {
                value["path"]: value["logical_bytes"]
                for value in final_snapshot["files"]
            }
            if observed_components != expected_components:
                raise AssertionError(
                    f"final component layout:{observed_components}!={expected_components}"
                )
            reopened = recorder.run(
                "same_process_reopen",
                lambda: reopen_backend(
                    candidate, final_target, case.rows, case.primitive,
                    case.bstar, case.authorities,
                ),
            )
            progress("SAME_PROCESS_REOPEN", "FRESH_PROCESS_REOPEN")
            try:
                if reopened.logical_sha256() != reconstructed:
                    raise AssertionError("same-process reopen mismatch")
            finally:
                reopened.close()
            reopen_request = output_path.with_suffix(".fresh-reopen-request.json")
            reopen_output = output_path.with_suffix(".fresh-reopen-result.json")
            write_canonical_json(reopen_request, {
                "schema": "SplitAlignerR/ENGINE003FreshReopen/v3",
                "backend": candidate, "target": str(final_target),
                "dimensions": request["dimensions"],
                "authorities": [value.hex() for value in case.authorities],
                "expected_logical_content_sha256": reconstructed,
            })
            command = [
                sys.executable, "-B", str(Path(__file__).resolve()),
                "--fresh-reopen-request", str(reopen_request),
                "--fresh-reopen-output", str(reopen_output),
            ]
            start = time.perf_counter_ns()
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            fresh_total = max(1, time.perf_counter_ns() - start)
            if process.returncode != 0:
                raise RuntimeError(f"fresh reopen failed:{process.stdout}{process.stderr}")
            fresh_result = strict_json_load(reopen_output)
            if fresh_result["status"] != "PASS" or fresh_result["logical_content_sha256"] != reconstructed:
                raise AssertionError("fresh-process reopen mismatch")
            recorder.record(
                "fresh_process_reopen_internal_open",
                fresh_result["internal_open_ns"],
                "MEASURED_BOUNDED_NON_AUTHORITATIVE",
            )
            recorder.record(
                "fresh_process_reopen_total", fresh_total,
                "MEASURED_BOUNDED_NON_AUTHORITATIVE",
            )
            # Both reopen decision metrics have finished.  Only now may the
            # evidence-only final-tree scan touch published component bytes.
            durability_result.update(publication_evidence_hashes(
                prepublication_hash, final_target, tree_sha256,
            ))
            durability_result["published_tree_hash_after_reopen_metrics"] = True
            shutil.rmtree(final_target)
            if final_target.exists():
                raise StopSignal("SB_STOP_CLEANUP", "published_target_survived")

        maximum_unpublished_snapshot = max(
            snapshots, key=lambda value: value["physical_allocated_bytes"],
        )
        temporary_disk = maximum_unpublished_snapshot["physical_allocated_bytes"]
        if candidate == "COLUMN_MAJOR_DISK" and "ROWSPOOL.bin" not in {
                value["path"] for value in maximum_unpublished_snapshot["files"]}:
            raise AssertionError("column spool absent from unpublished high-water")
        final_disk = final_snapshot["physical_allocated_bytes"]
        recorder.record("peak_rss", max(1, peak_rss_bytes()), "MEASURED_INTEGER_BYTES")
        recorder.record("temporary_physical_disk", temporary_disk, "MEASURED_INTEGER_BYTES")
        recorder.record("final_physical_disk", final_disk, "MEASURED_INTEGER_BYTES")
        recorder.record(
            "publication_high_water", max(temporary_disk, final_disk),
            "MEASURED_INTEGER_BYTES",
        )
        recorder.record(
            "worker_end_to_end", max(1, time.perf_counter_ns() - overall_start),
            "MEASURED_BOUNDED_NON_AUTHORITATIVE",
        )
        recorder.finish()
        integer_metrics = {
            "lifecycle": {name: recorder.values[name] for name in (
                "allocation_initialization", "row_construction", "finalization",
                "bounded_validation",
            )},
            "peak_rss_repetitions": recorder.values["peak_rss"],
            "publication_highwater_repetitions": recorder.values["publication_high_water"],
            "column_extraction_repetitions": recorder.values["column_extraction_sample"],
            "full_logical_scan_repetitions": recorder.values["full_logical_read"],
        }
        bounded_execution = request["execution_mode"] == BOUNDED_MODE
        result = {
            "schema": WORKER_RESULT_SCHEMA,
            "status": (
                "BOUNDED_PARAMETERIZED_REAL_WORKER_PASS" if bounded_execution
                else "STAGEB_AUTHORIZED_PARAMETERIZED_REAL_WORKER_PASS"
            ),
            "execution_mode": request["execution_mode"],
            "decision_authority": not bounded_execution,
            "stage_b_measured_timing": not bounded_execution,
            "performance_conclusion_authorized": False,
            "physical_candidate_store_constructed": True,
            "workload_id": request["workload_id"],
            "candidate_id": candidate,
            "dimensions": request["dimensions"],
            "descriptor_sha256": request["descriptor_sha256"],
            "source_commit": authority.commit,
            "source_tree": authority.tree,
            "selected_schedule_id": request["selected_schedule_id"],
            "measured_repetition": request["measured_repetition"],
            "schedule_position": request["schedule_position"],
            "schedule_row_sha256": request["schedule_row_sha256"],
            "operation_contract": OPERATION_CONTRACT,
            "metric_contract_sha256": plan.metric_contract_sha256,
            "metric_operation_binding": plan.binding_rows(),
            "operation_integer_values": recorder.values,
            "operation_status": recorder.status,
            "operation_units": {
                name: "INTEGER_NANOSECONDS" if name in DURATION_METRICS
                else "INTEGER_BYTES" for name in METRIC_HANDLERS
            },
            "operation_markers": [{
                "metric_id": name,
                "operation_handler": METRIC_HANDLERS[name],
                "execution_count": 1,
                "inside_controller_watchdog": True,
            } for name in plan.rows],
            "integer_metrics": integer_metrics,
            "bounded_validator": validator,
            "construction_artifact_retirement": artifact_retirement,
            "column_spool_lifecycle": {
                "spool_exists_during_construction": spool_exists_during_construction,
                "temporary_high_water_includes_spool": (
                    candidate != "COLUMN_MAJOR_DISK"
                    or "ROWSPOOL.bin" in {
                        value["path"] for value in maximum_unpublished_snapshot["files"]
                    }
                ),
                "spool_exists_in_final_store": False,
                "final_component_hash_set_contains_spool": False,
            },
            "probe_plan": {"rows": rows, "columns": columns, "blocks": blocks},
            "metric_boundary_contract": {
                "row_construction": "BACKEND_WRITE_ROW_CALLS_ONLY_PER_ROW_ACCUMULATION",
                "row_read_sample": "BACKEND_READ_ROW_CALLS_ONLY",
                "column_extraction_sample": "BACKEND_READ_COLUMN_CALLS_ONLY",
                "block_read_sample": "BACKEND_READ_BLOCK_CALLS_ONLY",
                "payload_generation": "OUTSIDE_DECISION_TIMING",
                "expected_value_generation": "BOUNDED_PROBE_CACHE_OUTSIDE_DECISION_TIMING",
                "correctness_comparison": "OUTSIDE_DECISION_TIMING",
                "probe_oracle_complete_matrix_owned": False,
                "probe_oracle_maximum_owned_bytes": probe_oracle.maximum_owned_bytes(),
            },
            "bounded_full_logical_scan": scan,
            "physical_component_sha256": physical_hashes,
            "expected_final_component_sizes": expected_final_component_sizes(
                candidate, case,
            ),
            "final_component_set_exact": True,
            "logical_content_sha256": reconstructed,
            "disk_snapshots": snapshots,
            "temporary_disk_snapshot": temporary_snapshot,
            "final_disk_snapshot": final_snapshot,
            "maximum_unpublished_physical_disk_bytes": temporary_disk,
            "maximum_unpublished_physical_disk_phase": (
                maximum_unpublished_snapshot["phase"]
            ),
            "final_published_physical_disk_bytes": final_disk,
            "publication_high_water_physical_bytes": max(
                temporary_disk, final_disk,
            ),
            "durable_publication": durability_result,
            "allocation_no_hole": (
                candidate == "COMPACT_IN_MEMORY"
                or snapshots[-1]["all_files_no_hole"]
            ),
            "same_process_reopen": (
                "NOT_APPLICABLE" if candidate == "COMPACT_IN_MEMORY" else "PASS"
            ),
            "fresh_process_reopen": (
                "NOT_APPLICABLE" if candidate == "COMPACT_IN_MEMORY" else "PASS"
            ),
            "host_profile": request["host_profile"],
            "worker_prelaunch_status": guard["status"],
            "worker_candidate_series_resource_sha256": request[
                "fresh_resource_capture_sha256"
            ],
            "worker_workload_branch_resource_sha256": request[
                "workload_branch_resource_capture_sha256"
            ],
            "worker_branch_resource_explicit": True,
            "cleanup_result": "PASS_TARGET_REMOVED",
        }
        write_canonical_json(output_path, result)
        progress("RESULT_WRITTEN", "CLEANUP_COMPLETE")
        progress_path.unlink()
    finally:
        if backend is not None:
            backend.close()
        for path in (temp_target, final_target):
            if path.exists():
                shutil.rmtree(path)


def race_participant(
        temp_target: Path, final_target: Path, start_gate: Path,
        output: Path, participant_id: str) -> None:
    deadline = time.monotonic() + 30
    while not start_gate.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("race start gate timeout")
        time.sleep(0.005)
    try:
        result = durable_publish(temp_target, final_target)
    except StopSignal as signal_value:
        if signal_value.stop_id != "SB_STOP_PUBLICATION_DESTINATION_EXISTS":
            raise
        write_race_result(output, {
            "participant_id": participant_id,
            "status": "LOSER_TYPED_STOP",
            "stop_id": signal_value.stop_id,
            "temporary_target_survived": temp_target.exists(),
            "final_target_exists": final_target.exists(),
        })
        return
    write_race_result(output, {
        "participant_id": participant_id,
        "status": "WINNER_PUBLISHED",
        "stop_id": "NONE",
        "temporary_target_survived": temp_target.exists(),
        "final_target_exists": final_target.exists(),
        "winner_tree_sha256": tree_sha256(final_target),
        "publication": result,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--resource", type=Path)
    parser.add_argument("--branch-resource", type=Path)
    parser.add_argument("--durability", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fresh-reopen-request", type=Path)
    parser.add_argument("--fresh-reopen-output", type=Path)
    parser.add_argument("--race-participant", action="store_true")
    parser.add_argument("--temp-target", type=Path)
    parser.add_argument("--final-target", type=Path)
    parser.add_argument("--start-gate", type=Path)
    parser.add_argument("--participant-id")
    args = parser.parse_args()
    if args.fresh_reopen_request:
        if not args.fresh_reopen_output:
            parser.error("fresh reopen output required")
        fresh_reopen(args.fresh_reopen_request, args.fresh_reopen_output)
        return
    if args.race_participant:
        if None in (
                args.temp_target, args.final_target, args.start_gate,
                args.output, args.participant_id):
            parser.error("complete race participant arguments required")
        race_participant(
            args.temp_target, args.final_target, args.start_gate,
            args.output, args.participant_id,
        )
        return
    if None in (
            args.repo_root, args.runtime_root, args.resource,
            args.branch_resource, args.durability, args.request, args.output):
        parser.error("complete live worker arguments required")
    execute_live(
        args.repo_root, args.runtime_root, args.resource,
        args.branch_resource, args.durability, args.request, args.output,
    )


if __name__ == "__main__":
    main()
