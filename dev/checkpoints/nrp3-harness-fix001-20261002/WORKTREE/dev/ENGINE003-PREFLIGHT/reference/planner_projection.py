#!/usr/bin/env python3
"""NON-PRODUCTION checked resource planner through VALIDATION/XPLAT PRE-RUN.

The output separates wire-format bytes, backend-native live memory, owned R
outputs, phase-local buffers, and disk publication.  It records projections
and hard lower bounds only; it performs no Stage-A timing.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


U64_MAX = (1 << 64) - 1
SIGNED_FILE_OFFSET_MAX = (1 << 63) - 1
SIZE_T_64_MAX = U64_MAX
INT_MAX = (1 << 31) - 1
R_XLEN_T_MAX = 1 << 52
TR = TC = 256
HEADER_BYTES = 256
INDEX_ENTRY_BYTES = 128
FOOTER_BYTES = 512
STATE_TILE_BYTES = TR * TC
NUMERIC_TILE_BYTES = TR * TC * 8
VALIDITY_TILE_BYTES = TR * TC // 8
INITIALIZATION_CHUNK_BYTES = 64 * 1024
CONSTRUCTION_ALGORITHM = "DIRECT_INITIALIZED_FILE_V1"
VALIDATOR_ALGORITHM = "MULTIPASS_ROW_SEGMENT_V1"
ROW_FILE_ALGORITHM = "SEQUENTIAL_ROW_STREAM_FILE_V1"
COLUMN_FILE_ALGORITHM = "ROW_SPOOL_THEN_COLUMN_TRANSPOSE_V1"
STAGE_A_METADATA_BYTES = 512
STAGE_A_MANIFEST_BYTES = 1024


def checked_input(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= U64_MAX:
        raise OverflowError(f"{label}: outside u64")
    return value


def add(left: int, right: int, label: str = "u64 addition") -> int:
    checked_input(left, label)
    checked_input(right, label)
    if left > U64_MAX - right:
        raise OverflowError(label)
    return left + right


def mul(left: int, right: int, label: str = "u64 multiplication") -> int:
    checked_input(left, label)
    checked_input(right, label)
    if left and right > U64_MAX // left:
        raise OverflowError(label)
    return left * right


def checked_sum(values, label: str) -> int:
    total = 0
    for value in values:
        total = add(total, value, label)
    return total


def ceil_div(value: int, divisor: int) -> int:
    checked_input(value, "ceil-dividend")
    if divisor <= 0:
        raise ValueError("ceil-divisor")
    quotient, remainder = divmod(value, divisor)
    return add(quotient, int(remainder != 0), "ceil division")


def primitive_plus_bstar(primitive: int, bstar: int) -> int:
    return add(primitive, bstar, "primitive plus B* columns")


def rounded_file(value: int, allocation_unit: int) -> int:
    checked_input(value, "file bytes")
    checked_input(allocation_unit, "allocation unit")
    if allocation_unit == 0:
        raise OverflowError("allocation unit is zero")
    return mul(ceil_div(value, allocation_unit), allocation_unit,
               "rounded file allocation")


def manifest_bytes(rows: int, primitive: int, bstar: int,
                   state_bytes: int, numeric_bytes: int,
                   validity_bytes: int, index_bytes: int) -> int:
    numeric = primitive_plus_bstar(primitive, bstar)
    values = [
        ("magic", "SplitAlignerR-MatrixStore-VALIDATED"),
        ("manifest_schema_major", "1"), ("manifest_schema_minor", "0"),
        ("completion_state", "VALIDATED"), ("store_schema", "1.0-candidate"),
        ("layout", "tiled_row_major_provisional"), ("tile_rows", "256"),
        ("tile_columns", "256"), ("row_count", str(rows)),
        ("primitive_count", str(primitive)), ("bstar_count", str(bstar)),
        ("numeric_coordinate_count", str(numeric)),
        ("species_authority_sha256", "0" * 64),
        ("gene_registry_sha256", "0" * 64),
        ("primitive_registry_sha256", "0" * 64),
        ("bstar_registry_sha256", "0" * 64),
        ("numeric_coordinate_registry_sha256", "0" * 64),
        ("logical_content_sha256", "0" * 64),
        ("state_component", "STATE.bin"), ("state_bytes", str(state_bytes)),
        ("state_sha256", "0" * 64), ("numeric_component", "NUMERIC.bin"),
        ("numeric_bytes", str(numeric_bytes)), ("numeric_sha256", "0" * 64),
        ("validity_component", "VALIDITY.bin"),
        ("validity_bytes", str(validity_bytes)), ("validity_sha256", "0" * 64),
        ("index_component", "TILE_INDEX.bin"), ("index_bytes", str(index_bytes)),
        ("index_sha256", "0" * 64), ("footer_component", "COMPLETION.bin"),
        ("footer_bytes", "512"), ("footer_sha256", "0" * 64),
        ("publication_timestamp_policy", "OMITTED_V1"),
    ]
    total = 0
    for key, value in values:
        total = checked_sum(
            (total, len(key.encode("ascii")), 1, len(value.encode("ascii")), 1),
            "manifest rendering",
        )
    return total


def project_format(name: str, rows: int, primitive: int, bstar: int,
                   evidence_class: str) -> dict[str, object]:
    rows = checked_input(rows, "rows")
    primitive = checked_input(primitive, "primitive")
    bstar = checked_input(bstar, "B*")
    numeric = primitive_plus_bstar(primitive, bstar)
    row_tiles = ceil_div(rows, TR) if rows else 0
    state_col_tiles = ceil_div(primitive, TC) if primitive else 0
    numeric_col_tiles = ceil_div(numeric, TC) if numeric else 0
    state_tiles = mul(row_tiles, state_col_tiles, "state tile count")
    numeric_tiles = mul(row_tiles, numeric_col_tiles, "numeric tile count")
    validity_tiles = numeric_tiles
    total_tiles = checked_sum(
        (state_tiles, numeric_tiles, validity_tiles), "aggregate tile count"
    )
    state_component = add(HEADER_BYTES, mul(state_tiles, STATE_TILE_BYTES,
                                             "state payload"),
                          "state component length")
    numeric_component = add(HEADER_BYTES, mul(numeric_tiles, NUMERIC_TILE_BYTES,
                                               "numeric payload"),
                            "numeric component length")
    validity_component = add(HEADER_BYTES, mul(validity_tiles, VALIDITY_TILE_BYTES,
                                                "validity payload"),
                             "validity component length")
    index_component = add(HEADER_BYTES, mul(total_tiles, INDEX_ENTRY_BYTES,
                                             "index entries"),
                          "index component length")
    manifest = manifest_bytes(rows, primitive, bstar, state_component,
                              numeric_component, validity_component, index_component)
    final_physical = checked_sum(
        (state_component, numeric_component, validity_component,
         index_component, FOOTER_BYTES, manifest), "final physical store"
    )
    logical_state = mul(rows, primitive, "logical state cells")
    logical_cells = mul(rows, numeric, "logical numeric cells")
    logical_numeric = mul(logical_cells, 8, "logical numeric bytes")
    logical_validity = ceil_div(logical_cells, 8)
    logical_payload = checked_sum(
        (logical_state, logical_numeric, logical_validity), "logical payload"
    )
    return {
        "case": name, "evidence_class": evidence_class, "rows": rows,
        "primitive_columns": primitive, "bstar_columns": bstar,
        "numeric_columns": numeric, "row_tiles": row_tiles,
        "state_column_tiles": state_col_tiles,
        "numeric_column_tiles": numeric_col_tiles, "state_tiles": state_tiles,
        "numeric_tiles": numeric_tiles, "validity_tiles": validity_tiles,
        "total_index_entries": total_tiles, "logical_payload_bytes": logical_payload,
        "state_component_bytes": state_component,
        "numeric_component_bytes": numeric_component,
        "validity_component_bytes": validity_component,
        "index_component_bytes": index_component, "footer_bytes": FOOTER_BYTES,
        "manifest_bytes": manifest, "final_physical_bytes": final_physical,
        "crosses_2GiB": str(final_physical > 2 * 1024**3).upper(),
        "crosses_4GiB": str(final_physical > 4 * 1024**3).upper(),
        "allocated_disk_bytes": "NOT MEASURED",
    }


def check_r_materialization(rows: int, columns: int) -> int:
    if rows > INT_MAX or columns > INT_MAX:
        raise OverflowError("R matrix dimension exceeds INT_MAX")
    cells = mul(rows, columns, "R materialization cell product")
    if cells > R_XLEN_T_MAX:
        raise OverflowError("R vector length exceeds R_XLEN_T_MAX")
    return cells


def check_file_target(value: int) -> int:
    checked_input(value, "file offset")
    if value > SIGNED_FILE_OFFSET_MAX or value > SIZE_T_64_MAX:
        raise OverflowError("file offset exceeds supported signed-64/size_t target")
    return value


def mandatory_terms(**overrides: int) -> dict[str, int]:
    terms = {
        "truth_plan_store_bytes": 0,
        "gene_workspace_bytes": 0,
        "empirical_split_index_bytes": 0,
        "registry_representation_bytes": 0,
        "r_orchestration_bytes": 0,
        "backend_native_allocation_overhead_bytes": 0,
        "r_dimnames_and_registry_bytes": 0,
        "r_conversion_scratch_bytes": 0,
        "r_allocator_and_object_overhead_bytes": 0,
        "production_validator_registry_bytes": 0,
        "production_validator_overhead_bytes": 0,
        "independent_validator_registry_bytes": 0,
        "independent_validator_overhead_bytes": 0,
        "implementation_overhead_bytes": 0,
        "safety_reserve_bytes": 0,
    }
    unknown = set(overrides) - set(terms)
    if unknown:
        raise KeyError("unknown planner terms: " + ",".join(sorted(unknown)))
    terms.update(overrides)
    for key, value in terms.items():
        checked_input(value, key)
    return terms


def compact_native_charge(rows: int, primitive: int, numeric: int) -> dict[str, int]:
    state_cells = mul(rows, primitive, "backend state cells")
    numeric_cells = mul(rows, numeric, "backend numeric cells")
    native_state = state_cells
    native_numeric = mul(numeric_cells, 8, "backend native numeric")
    native_validity = ceil_div(numeric_cells, 8)
    native_total = checked_sum(
        (native_state, native_numeric, native_validity, 0),
        "backend native total",
    )
    return {
        "backend_native_state_bytes": native_state,
        "backend_native_numeric_bytes": native_numeric,
        "backend_native_validity_bytes": native_validity,
        "backend_native_index_or_lookup_bytes": 0,
        "backend_native_total_bytes": native_total,
    }


def row_staging_charge(primitive: int, numeric: int) -> dict[str, int]:
    state_row = checked_input(primitive, "state row staging")
    numeric_row = mul(numeric, 8, "numeric row staging")
    validity_row = ceil_div(numeric, 8) if numeric else 0
    row_total = checked_sum((state_row, numeric_row, validity_row),
                            "row staging total")
    return {
        "state_row_staging_bytes": state_row,
        "numeric_row_staging_bytes": numeric_row,
        "validity_row_staging_bytes": validity_row,
        "row_staging_total_bytes": row_total,
    }


def r_materialization_charge(rows: int, primitive: int, numeric: int,
                             terms: dict[str, int]) -> dict[str, int]:
    r_state_cells = check_r_materialization(rows, primitive)
    r_numeric_cells = check_r_materialization(rows, numeric)
    r_state = mul(r_state_cells, 4, "R integer state output")
    r_numeric = mul(r_numeric_cells, 8, "R numeric output")
    r_payload = add(r_state, r_numeric, "R payload total")
    r_owned_total = checked_sum(
        (r_payload, terms["r_dimnames_and_registry_bytes"],
         terms["r_conversion_scratch_bytes"],
         terms["r_allocator_and_object_overhead_bytes"]),
        "R owned output total",
    )
    return {
        "r_state_output_bytes": r_state,
        "r_numeric_output_bytes": r_numeric,
        "r_payload_total_bytes": r_payload,
        "r_owned_output_total_bytes": r_owned_total,
    }


def phase_peak_charge(base_live: int, writer_initialization_chunk: int,
                      writer_tile_or_slab: int,
                      row_total: int, validity_packer_carry: int,
                      writer_index_builder: int, writer_hash_io: int,
                      production_validator: int, independent_validator: int,
                      r_owned_total, materialization_requested: bool,
                      safety_reserve: int) -> dict[str, object]:
    if not isinstance(materialization_requested, bool):
        raise ValueError("materialization_requested must be bool")
    construction_initialization = checked_sum(
        (base_live, writer_initialization_chunk),
        "construction initialization live",
    )
    construction_row = checked_sum(
        (base_live, row_total, validity_packer_carry),
        "construction row live",
    )
    construction_tile_or_slab = add(
        base_live, writer_tile_or_slab, "construction tile/slab live"
    )
    construction_peak = max(
        construction_initialization, construction_row,
        construction_tile_or_slab,
    )
    finalization = add(base_live, max(writer_index_builder, writer_hash_io),
                       "finalization/hash peak")
    production_peak = add(base_live, production_validator,
                          "production validation peak")
    independent_peak = add(base_live, independent_validator,
                           "independent validation peak")
    r_peak: object
    if r_owned_total is None:
        r_peak = "NOT_AVAILABLE"
    elif materialization_requested:
        r_peak = add(base_live, r_owned_total, "R materialization peak")
    else:
        try:
            r_peak = add(base_live, r_owned_total, "R materialization peak")
        except OverflowError:
            r_peak = "NOT_AVAILABLE"
    live_candidates = [construction_peak, finalization,
                       production_peak, independent_peak]
    if materialization_requested:
        if not isinstance(r_peak, int):
            raise OverflowError("requested R materialization is unavailable")
        live_candidates.append(r_peak)
    overall = max(live_candidates)
    admission = add(overall, safety_reserve, "memory admission")
    return {
        "construction_initialization_live_bytes": construction_initialization,
        "construction_row_live_bytes": construction_row,
        "construction_tile_or_slab_live_bytes": construction_tile_or_slab,
        "construction_peak_live_bytes": construction_peak,
        "finalization_hash_peak_live_bytes": finalization,
        "production_validation_peak_live_bytes": production_peak,
        "independent_validation_peak_live_bytes": independent_peak,
        "r_materialization_peak_live_bytes": r_peak,
        "overall_max_live_bytes": overall,
        "safety_reserve_bytes": safety_reserve,
        "admission_required_bytes": admission,
    }


def validator_segment_contract(format_row: dict[str, object]) -> dict[str, int]:
    """Exact MULTIPASS_ROW_SEGMENT_V1 buffers and access amplification."""
    rows = checked_input(int(format_row["rows"]), "validator rows")
    primitive = checked_input(
        int(format_row["primitive_columns"]), "validator primitive columns"
    )
    bstar = checked_input(
        int(format_row["bstar_columns"]), "validator B* columns"
    )
    numeric = checked_input(
        int(format_row["numeric_columns"]), "validator numeric columns"
    )
    if numeric != primitive_plus_bstar(primitive, bstar):
        raise ValueError("validator numeric dimension mismatch")

    state_segment = min(primitive, TC)
    numeric_segment = mul(min(numeric, TC), 8, "validator numeric segment")
    validity_segment = ceil_div(min(numeric, TC), 8) if numeric else 0
    standard_segment = checked_sum(
        (state_segment, numeric_segment, validity_segment),
        "validator standard semantic segment",
    )

    occupancy = ceil_div(state_segment, 8) if state_segment else 0
    bstar_validity_window = ceil_div(min(bstar, TC), 8) if bstar else 0
    composite_segment = checked_sum(
        (state_segment, occupancy, bstar_validity_window),
        "validator composite segment",
    )
    selected_segment = max(standard_segment, composite_segment)

    primitive_segments = ceil_div(primitive, TC) if primitive else 0
    bstar_windows = ceil_div(bstar, TC) if bstar else 0
    state_read_bytes = mul(rows, primitive, "validator composite state reads")
    rescan_windows = mul(
        mul(rows, primitive_segments, "validator row-segment count"),
        bstar_windows,
        "validator B* validity rescan windows",
    )

    full_windows, tail_bits = divmod(bstar, TC)
    bit_offset = primitive % 8
    full_source_bytes = TC // 8 + int(bit_offset != 0)
    tail_source_bytes = (
        ceil_div(add(bit_offset, tail_bits, "validator tail source bits"), 8)
        if tail_bits else 0
    )
    source_bytes_per_primitive_segment = checked_sum(
        (
            mul(full_windows, full_source_bytes,
                "validator full B* source bytes"),
            tail_source_bytes,
        ),
        "validator B* source bytes per primitive segment",
    )
    source_read_bytes_upper = mul(
        mul(rows, primitive_segments, "validator source row-segments"),
        source_bytes_per_primitive_segment,
        "validator B* source read bytes upper",
    )

    tile_offset = primitive % TC
    full_source_ops = 1 if tile_offset == 0 else 2
    tail_source_ops = (
        (1 if tile_offset + tail_bits <= TC else 2) if tail_bits else 0
    )
    source_ops_per_primitive_segment = checked_sum(
        (
            mul(full_windows, full_source_ops,
                "validator full B* source operations"),
            tail_source_ops,
        ),
        "validator B* source operations per primitive segment",
    )
    source_read_ops_upper = mul(
        mul(rows, primitive_segments, "validator operation row-segments"),
        source_ops_per_primitive_segment,
        "validator B* source read operations upper",
    )
    registry_probes = mul(
        mul(rows, primitive_segments, "validator registry row-segments"),
        bstar,
        "validator registry entry-segment probes upper",
    )
    return {
        "state_segment_bytes": state_segment,
        "numeric_segment_bytes": numeric_segment,
        "validity_segment_bytes": validity_segment,
        "standard_semantic_segment_bytes": standard_segment,
        "composite_occupancy_bytes": occupancy,
        "composite_bstar_validity_window_bytes": bstar_validity_window,
        "composite_segment_bytes": composite_segment,
        "selected_segment_bytes": selected_segment,
        "primitive_segment_count": primitive_segments,
        "bstar_validity_window_count": bstar_windows,
        "composite_state_read_bytes": state_read_bytes,
        "composite_bstar_validity_rescan_windows": rescan_windows,
        "composite_bstar_source_read_bytes_upper": source_read_bytes_upper,
        "composite_bstar_source_read_ops_upper": source_read_ops_upper,
        "registry_entry_segment_probes_upper": registry_probes,
    }


def validator_charge(format_row: dict[str, object], prefix: str,
                     terms: dict[str, int], backend: str) -> dict[str, object]:
    contract = validator_segment_contract(format_row)
    segment = int(contract["selected_segment_bytes"])
    numeric = int(format_row["numeric_columns"])
    logical_packer = 1 if int(format_row["rows"]) and numeric else 0
    if backend == "COMPACT_IN_MEMORY":
        access_profile = "COMPACT_LOGICAL_ARRAY_ACCESS_V1"
        index_window = 0
        hash_io = 0
    elif backend == "TILED_DISK":
        access_profile = "TILED_PREAD_ACCESS_V1"
        index_window = 2 * INDEX_ENTRY_BYTES
        hash_io = INITIALIZATION_CHUNK_BYTES
    elif backend == "ROW_MAJOR_DISK":
        access_profile = "ROW_MAJOR_PREAD_ACCESS_V1"
        index_window = 0
        hash_io = INITIALIZATION_CHUNK_BYTES
    elif backend == "COLUMN_MAJOR_DISK":
        access_profile = "COLUMN_MAJOR_GATHER_ACCESS_V1"
        index_window = 0
        hash_io = INITIALIZATION_CHUNK_BYTES
    else:
        raise ValueError(backend)
    internal_peak = max(index_window, hash_io, add(segment, logical_packer,
                                                   f"{prefix} logical packer"))
    registry = terms[f"{prefix}_validator_registry_bytes"]
    overhead = terms[f"{prefix}_validator_overhead_bytes"]
    total = checked_sum((registry, internal_peak, overhead),
                        f"{prefix} validator total")
    return {
        f"{prefix}_validator_algorithm": VALIDATOR_ALGORITHM,
        f"{prefix}_validator_access_profile": access_profile,
        f"{prefix}_validator_registry_bytes": registry,
        f"{prefix}_validator_index_window_bytes": index_window,
        f"{prefix}_validator_state_segment_bytes":
            contract["state_segment_bytes"],
        f"{prefix}_validator_numeric_segment_bytes":
            contract["numeric_segment_bytes"],
        f"{prefix}_validator_validity_segment_bytes":
            contract["validity_segment_bytes"],
        f"{prefix}_validator_standard_semantic_segment_bytes":
            contract["standard_semantic_segment_bytes"],
        f"{prefix}_validator_composite_occupancy_bytes":
            contract["composite_occupancy_bytes"],
        f"{prefix}_validator_composite_bstar_validity_window_bytes":
            contract["composite_bstar_validity_window_bytes"],
        f"{prefix}_validator_composite_segment_bytes":
            contract["composite_segment_bytes"],
        f"{prefix}_validator_tile_or_segment_bytes": segment,
        f"{prefix}_validator_hash_io_bytes": hash_io,
        f"{prefix}_validator_logical_packer_bytes": logical_packer,
        f"{prefix}_validator_primitive_segment_count":
            contract["primitive_segment_count"],
        f"{prefix}_validator_bstar_validity_window_count":
            contract["bstar_validity_window_count"],
        f"{prefix}_validator_composite_state_read_bytes":
            contract["composite_state_read_bytes"],
        f"{prefix}_validator_composite_bstar_validity_rescan_windows":
            contract["composite_bstar_validity_rescan_windows"],
        f"{prefix}_validator_composite_bstar_source_read_bytes_upper":
            contract["composite_bstar_source_read_bytes_upper"],
        f"{prefix}_validator_composite_bstar_source_read_ops_upper":
            contract["composite_bstar_source_read_ops_upper"],
        f"{prefix}_validator_registry_entry_segment_probes_upper":
            contract["registry_entry_segment_probes_upper"],
        f"{prefix}_validator_overhead_bytes": overhead,
        f"{prefix}_validator_internal_peak_bytes": internal_peak,
        f"{prefix}_validator_bytes": total,
    }


def charge_backend(case: str, format_row: dict[str, object], backend: str,
                   evidence_class: str, integration_scope: str,
                   terms: dict[str, int],
                   materialization_requested: bool) -> dict[str, object]:
    if not isinstance(materialization_requested, bool):
        raise ValueError("materialization_requested must be bool")
    required = set(mandatory_terms())
    if set(terms) != required:
        missing = required - set(terms)
        extra = set(terms) - required
        raise KeyError(f"mandatory planner term mismatch missing={missing} extra={extra}")
    rows = int(format_row["rows"])
    primitive = int(format_row["primitive_columns"])
    numeric = int(format_row["numeric_columns"])
    if backend == "COMPACT_IN_MEMORY":
        native = compact_native_charge(rows, primitive, numeric)
        writer_tile_or_slab = 0
        writer_initialization_chunk = 0
        writer_index_builder = 0
        writer_hash_io = 0
        writer_algorithm = "COMPACT_CONTIGUOUS_V1"
        compact_validity_layout = "CONTINUOUS_LSB_FIRST_BITMAP"
        compact_validity_packer = "ROW_STAGING_TO_CONTINUOUS_CARRY_V1"
        validity_packer_carry = 1 if rows and numeric else 0
    elif backend == "TILED_DISK":
        native = {
            "backend_native_state_bytes": 0,
            "backend_native_numeric_bytes": 0,
            "backend_native_validity_bytes": 0,
            "backend_native_index_or_lookup_bytes": 0,
            "backend_native_total_bytes": 0,
        }
        writer_tile_or_slab = 0
        writer_initialization_chunk = INITIALIZATION_CHUNK_BYTES
        writer_index_builder = INDEX_ENTRY_BYTES
        writer_hash_io = INITIALIZATION_CHUNK_BYTES
        writer_algorithm = CONSTRUCTION_ALGORITHM
        compact_validity_layout = "NOT_APPLICABLE_TILED_DISK"
        compact_validity_packer = "NOT_APPLICABLE_TILED_DISK"
        validity_packer_carry = 0
    elif backend == "ROW_MAJOR_DISK":
        native = {
            "backend_native_state_bytes": 0,
            "backend_native_numeric_bytes": 0,
            "backend_native_validity_bytes": 0,
            "backend_native_index_or_lookup_bytes": 0,
            "backend_native_total_bytes": 0,
        }
        writer_tile_or_slab = 0
        writer_initialization_chunk = 0
        writer_index_builder = 0
        writer_hash_io = INITIALIZATION_CHUNK_BYTES
        writer_algorithm = ROW_FILE_ALGORITHM
        compact_validity_layout = "NOT_APPLICABLE_ROW_MAJOR_FILE"
        compact_validity_packer = "ROW_STAGING_TO_CONTINUOUS_CARRY_V1"
        validity_packer_carry = 1 if rows and numeric else 0
    elif backend == "COLUMN_MAJOR_DISK":
        native = {
            "backend_native_state_bytes": 0,
            "backend_native_numeric_bytes": 0,
            "backend_native_validity_bytes": 0,
            "backend_native_index_or_lookup_bytes": 0,
            "backend_native_total_bytes": 0,
        }
        # Component transposes are sequential and nonconcurrent; numeric is
        # the largest 256 x 256 slab.
        writer_tile_or_slab = NUMERIC_TILE_BYTES
        writer_initialization_chunk = INITIALIZATION_CHUNK_BYTES
        writer_index_builder = 0
        writer_hash_io = INITIALIZATION_CHUNK_BYTES
        writer_algorithm = COLUMN_FILE_ALGORITHM
        compact_validity_layout = "NOT_APPLICABLE_COLUMN_MAJOR_FILE"
        compact_validity_packer = "ROW_SPOOL_BYTE_PADDED_THEN_COLUMN_TRANSPOSE"
        validity_packer_carry = 1 if rows and numeric else 0
    else:
        raise ValueError(backend)
    row = row_staging_charge(primitive, numeric)
    try:
        r_charge = r_materialization_charge(rows, primitive, numeric, terms)
    except OverflowError:
        if materialization_requested:
            raise
        r_charge = {
            "r_state_output_bytes": "NOT_AVAILABLE",
            "r_numeric_output_bytes": "NOT_AVAILABLE",
            "r_payload_total_bytes": "NOT_AVAILABLE",
            "r_owned_output_total_bytes": "NOT_AVAILABLE",
        }
        r_status = "NOT_REQUESTED_UNAVAILABLE_EXCLUDED"
        r_owned_for_phase = None
    else:
        if materialization_requested:
            r_status = "REQUESTED_AVAILABLE_INCLUDED"
        else:
            r_status = "NOT_REQUESTED_AVAILABLE_EXCLUDED"
        r_owned_for_phase = int(r_charge["r_owned_output_total_bytes"])
    production = validator_charge(format_row, "production", terms, backend)
    independent = validator_charge(format_row, "independent", terms, backend)
    persistent_integration = checked_sum(
        (terms["truth_plan_store_bytes"], terms["gene_workspace_bytes"],
         terms["empirical_split_index_bytes"],
         terms["registry_representation_bytes"], terms["r_orchestration_bytes"],
         terms["implementation_overhead_bytes"]),
        "persistent integration charge",
    )
    base_live = checked_sum(
        (native["backend_native_total_bytes"],
         terms["backend_native_allocation_overhead_bytes"],
         persistent_integration), "base live memory",
    )
    phases = phase_peak_charge(
        base_live, writer_initialization_chunk, writer_tile_or_slab,
        row["row_staging_total_bytes"], validity_packer_carry,
        writer_index_builder, writer_hash_io,
        int(production["production_validator_bytes"]),
        int(independent["independent_validator_bytes"]),
        r_owned_for_phase, materialization_requested,
        terms["safety_reserve_bytes"],
    )
    if (r_status == "NOT_REQUESTED_AVAILABLE_EXCLUDED" and
            phases["r_materialization_peak_live_bytes"] == "NOT_AVAILABLE"):
        r_status = "NOT_REQUESTED_UNAVAILABLE_PEAK_EXCLUDED"
    return {
        "case": case, "evidence_class": evidence_class,
        "integration_scope": integration_scope, "backend_candidate": backend,
        "writer_construction_algorithm": writer_algorithm,
        "compact_validity_layout": compact_validity_layout,
        "compact_validity_packer": compact_validity_packer,
        **native,
        "backend_native_allocation_overhead_bytes":
            terms["backend_native_allocation_overhead_bytes"],
        **row,
        "validity_packer_carry_bytes": validity_packer_carry,
        "r_materialization_requested": str(materialization_requested).upper(),
        "r_materialization_status": r_status,
        "r_materialization_included_in_admission":
            str(materialization_requested).upper(),
        "r_state_output_type": "INTSXP",
        "r_state_output_bytes": r_charge["r_state_output_bytes"],
        "r_numeric_output_type": "REALSXP_WITH_NA_REAL_FOR_INVALID",
        "r_numeric_output_bytes": r_charge["r_numeric_output_bytes"],
        "r_payload_total_bytes": r_charge["r_payload_total_bytes"],
        "r_dimnames_and_registry_bytes": terms["r_dimnames_and_registry_bytes"],
        "r_conversion_scratch_bytes": terms["r_conversion_scratch_bytes"],
        "r_allocator_and_object_overhead_bytes":
            terms["r_allocator_and_object_overhead_bytes"],
        "r_owned_output_total_bytes": r_charge["r_owned_output_total_bytes"],
        "writer_tile_or_slab_bytes": writer_tile_or_slab,
        "writer_initialization_chunk_bytes": writer_initialization_chunk,
        "writer_index_builder_bytes": writer_index_builder,
        "writer_hash_io_bytes": writer_hash_io,
        **production, **independent,
        "truth_plan_store_bytes": terms["truth_plan_store_bytes"],
        "gene_workspace_bytes": terms["gene_workspace_bytes"],
        "empirical_split_index_bytes": terms["empirical_split_index_bytes"],
        "registry_representation_bytes": terms["registry_representation_bytes"],
        "r_orchestration_bytes": terms["r_orchestration_bytes"],
        "implementation_overhead_bytes": terms["implementation_overhead_bytes"],
        "persistent_integration_bytes": persistent_integration,
        "base_live_bytes": base_live,
        **phases,
        "peak_rss_bytes": "NOT MEASURED",
    }


def validity_row_overwrite_charge(rows: int, numeric: int) -> int:
    validity_row_bytes = ceil_div(numeric, 8) if numeric else 0
    return mul(rows, validity_row_bytes, "validity row overwrite")


def construction_projection(format_row: dict[str, object], allocation_unit: int = 4096,
                            temp_directory_metadata_bound: int = 0,
                            final_directory_metadata_bound: int = 0,
                            disk_safety_reserve: int = 0) -> dict[str, object]:
    rows = int(format_row["rows"])
    primitive = int(format_row["primitive_columns"])
    numeric = int(format_row["numeric_columns"])
    state_component = int(format_row["state_component_bytes"])
    numeric_component = int(format_row["numeric_component_bytes"])
    validity_component = int(format_row["validity_component_bytes"])
    index_component = int(format_row["index_component_bytes"])
    manifest = int(format_row["manifest_bytes"])
    for component_name, component_bytes in (
        ("STATE.bin", state_component),
        ("NUMERIC.bin", numeric_component),
        ("VALIDITY.bin", validity_component),
        ("TILE_INDEX.bin", index_component),
        ("COMPLETION.bin", FOOTER_BYTES),
        ("VALIDATED", manifest),
    ):
        try:
            check_file_target(component_bytes)
        except OverflowError as error:
            raise OverflowError(f"{component_name} target length: {error}")
    initialized_payload = checked_sum(
        (state_component - HEADER_BYTES, numeric_component - HEADER_BYTES,
         validity_component - HEADER_BYTES), "initialized physical payload"
    )
    state_overwrite = mul(rows, primitive, "state row overwrite")
    numeric_overwrite = mul(mul(rows, numeric, "numeric row cells"), 8,
                            "numeric row overwrite")
    validity_overwrite = validity_row_overwrite_charge(rows, numeric)
    row_overwrite = checked_sum(
        (state_overwrite, numeric_overwrite, validity_overwrite),
        "row overwrite total",
    )
    temporary_binary = checked_sum(
        (state_component, numeric_component, validity_component,
         index_component, FOOTER_BYTES), "temporary binary bytes"
    )
    final_exact = add(temporary_binary, manifest, "published exact bytes")
    total_written = checked_sum(
        (initialized_payload, row_overwrite, 3 * HEADER_BYTES,
         index_component, FOOTER_BYTES, manifest), "candidate bytes written"
    )
    temporary_allocated = checked_sum(
        (rounded_file(state_component, allocation_unit),
         rounded_file(numeric_component, allocation_unit),
         rounded_file(validity_component, allocation_unit),
         rounded_file(index_component, allocation_unit),
         rounded_file(FOOTER_BYTES, allocation_unit),
         temp_directory_metadata_bound), "temporary allocated upper"
    )
    published_allocated = checked_sum(
        (rounded_file(state_component, allocation_unit),
         rounded_file(numeric_component, allocation_unit),
         rounded_file(validity_component, allocation_unit),
         rounded_file(index_component, allocation_unit),
         rounded_file(FOOTER_BYTES, allocation_unit),
         rounded_file(manifest, allocation_unit),
         final_directory_metadata_bound), "published allocated upper"
    )
    high_water = max(temporary_allocated, published_allocated)
    admission = add(high_water, disk_safety_reserve, "disk admission")
    no_reserve_projection = (
        temp_directory_metadata_bound == 0 and
        final_directory_metadata_bound == 0 and
        disk_safety_reserve == 0
    )
    evidence_class = (
        "DIRECT_INITIALIZED_FILE_V1_EXACT_NO_RESERVE_PROJECTION_"
        "NOT_EXECUTABLE_ADMISSION"
        if no_reserve_projection else
        "DIRECT_INITIALIZED_FILE_V1_DECLARED_RESOURCE_PROJECTION_"
        "NOT_MEASURED"
    )
    return {
        "case": format_row["case"],
        "evidence_class": evidence_class,
        "executable_admission": "FALSE",
        "file_target_gate": "SIGNED_64_AND_SIZE_T_64_COMPONENT_LENGTHS",
        "construction_algorithm": CONSTRUCTION_ALGORITHM,
        "physical_allocation_policy": "PLATFORM_PREALLOCATE_PLUS_FULL_ZERO_WRITE_NO_SPARSE",
        "rows_written_sequentially": "TRUE", "row_major_spool_bytes": 0,
        "active_tile_row_slab_bytes": 0,
        "writer_initialization_chunk_bytes": INITIALIZATION_CHUNK_BYTES,
        "initialized_physical_payload_bytes": initialized_payload,
        "state_row_overwrite_bytes": state_overwrite,
        "numeric_row_overwrite_bytes": numeric_overwrite,
        "validity_row_overwrite_bytes": validity_overwrite,
        "row_overwrite_total_bytes": row_overwrite,
        "candidate_total_bytes_written": total_written,
        "write_amplification_excludes_filesystem_journal": "TRUE",
        "temporary_binary_bytes": temporary_binary, "spool_bytes": 0,
        "copy_duplicate_bytes": 0, "manifest_bytes": manifest,
        "published_exact_bytes": final_exact, "allocation_unit_bytes": allocation_unit,
        "temp_directory_metadata_bound_bytes": temp_directory_metadata_bound,
        "final_directory_metadata_bound_bytes": final_directory_metadata_bound,
        "temporary_allocated_upper_bytes": temporary_allocated,
        "published_allocated_upper_bytes": published_allocated,
        "publication_allocated_high_water_bytes": high_water,
        "disk_safety_reserve_bytes": disk_safety_reserve,
        "admission_free_space_bytes": admission,
        "allocated_disk_bytes": "NOT MEASURED",
    }


def flat_file_construction_projection(
    format_row: dict[str, object], backend: str, allocation_unit: int = 4096,
    temp_directory_metadata_bound: int = 0,
    final_directory_metadata_bound: int = 0,
    disk_safety_reserve: int = 0,
) -> dict[str, object]:
    """Exact non-production row/column-major prototype disk model."""
    if backend not in {"ROW_MAJOR_DISK", "COLUMN_MAJOR_DISK"}:
        raise ValueError("flat-file projection backend")
    rows = int(format_row["rows"])
    primitive = int(format_row["primitive_columns"])
    numeric = int(format_row["numeric_columns"])
    logical_state = mul(rows, primitive, "flat logical state")
    logical_numeric = mul(mul(rows, numeric, "flat numeric cells"), 8,
                          "flat numeric bytes")
    logical_validity = ceil_div(mul(rows, numeric, "flat validity bits"), 8)
    state_component = add(HEADER_BYTES, logical_state, "flat state component")
    numeric_component = add(HEADER_BYTES, logical_numeric, "flat numeric component")
    validity_component = add(HEADER_BYTES, logical_validity, "flat validity component")
    component_lengths = (state_component, numeric_component, validity_component)
    for value in component_lengths + (STAGE_A_METADATA_BYTES, STAGE_A_MANIFEST_BYTES):
        check_file_target(value)
    final_without_manifest = checked_sum(
        component_lengths + (STAGE_A_METADATA_BYTES,),
        "flat final without manifest",
    )
    published_exact = add(
        final_without_manifest, STAGE_A_MANIFEST_BYTES,
        "flat published exact",
    )
    row_padded_validity = mul(
        rows, ceil_div(numeric, 8) if numeric else 0,
        "column row-spool validity",
    )
    spool = (checked_sum(
        (logical_state, logical_numeric, row_padded_validity),
        "column row spool",
    ) if backend == "COLUMN_MAJOR_DISK" else 0)
    allocated_components = checked_sum(
        tuple(rounded_file(value, allocation_unit) for value in component_lengths)
        + (rounded_file(STAGE_A_METADATA_BYTES, allocation_unit),),
        "flat allocated components",
    )
    allocated_spool = rounded_file(spool, allocation_unit) if spool else 0
    temporary_allocated = checked_sum(
        (allocated_components, allocated_spool, temp_directory_metadata_bound),
        "flat temporary allocated upper",
    )
    published_allocated = checked_sum(
        (allocated_components, rounded_file(STAGE_A_MANIFEST_BYTES, allocation_unit),
         final_directory_metadata_bound),
        "flat published allocated upper",
    )
    high_water = max(temporary_allocated, published_allocated)
    admission = add(high_water, disk_safety_reserve, "flat disk admission")
    payload = checked_sum(
        (logical_state, logical_numeric, logical_validity),
        "flat final payload",
    )
    total_written = checked_sum(
        (spool, payload, 3 * HEADER_BYTES, STAGE_A_METADATA_BYTES,
         STAGE_A_MANIFEST_BYTES),
        "flat candidate bytes written",
    )
    row_behavior = (
        "DIRECT_SEQUENTIAL_APPEND_STATE_NUMERIC_CONTINUOUS_VALIDITY"
        if backend == "ROW_MAJOR_DISK" else
        "SEQUENTIAL_APPEND_TO_ROW_MAJOR_SPOOL_BEFORE_BOUNDED_TRANSPOSE"
    )
    column_behavior = (
        "STRIDED_BOUNDED_GATHER_FROM_ROW_MAJOR_COMPONENTS"
        if backend == "ROW_MAJOR_DISK" else
        "DIRECT_CONTIGUOUS_COLUMN_RANGE_READ"
    )
    return {
        "case": format_row["case"],
        "evidence_class": "FLAT_FILE_DECLARED_RESOURCE_PROJECTION_NOT_MEASURED",
        "executable_admission": "FALSE",
        "file_target_gate": "SIGNED_64_AND_SIZE_T_64_COMPONENT_LENGTHS",
        "construction_algorithm": (
            ROW_FILE_ALGORITHM if backend == "ROW_MAJOR_DISK"
            else COLUMN_FILE_ALGORITHM
        ),
        "physical_allocation_policy": (
            "SEQUENTIAL_APPEND_FULL_BYTES_NO_SPARSE"
            if backend == "ROW_MAJOR_DISK" else
            "ROW_SPOOL_PLUS_PREALLOCATED_FULL_COLUMN_TRANSPOSE_NO_SPARSE"
        ),
        "rows_written_sequentially": "TRUE",
        "row_write_behavior": row_behavior,
        "column_read_behavior": column_behavior,
        "row_read_behavior": (
            "DIRECT_CONTIGUOUS_ROW_RANGE_READ"
            if backend == "ROW_MAJOR_DISK" else
            "STRIDED_BOUNDED_GATHER_FROM_COLUMN_MAJOR_COMPONENTS"
        ),
        "row_major_spool_bytes": spool,
        "active_tile_row_slab_bytes": (
            0 if backend == "ROW_MAJOR_DISK" else NUMERIC_TILE_BYTES
        ),
        "writer_initialization_chunk_bytes": (
            0 if backend == "ROW_MAJOR_DISK" else INITIALIZATION_CHUNK_BYTES
        ),
        "initialized_physical_payload_bytes": (
            0 if backend == "ROW_MAJOR_DISK" else payload
        ),
        "state_row_overwrite_bytes": logical_state,
        "numeric_row_overwrite_bytes": logical_numeric,
        "validity_row_overwrite_bytes": row_padded_validity,
        "row_overwrite_total_bytes": checked_sum(
            (logical_state, logical_numeric, row_padded_validity),
            "flat row writes",
        ),
        "candidate_total_bytes_written": total_written,
        "write_amplification_excludes_filesystem_journal": "TRUE",
        "temporary_binary_bytes": final_without_manifest,
        "spool_bytes": spool,
        "copy_duplicate_bytes": spool,
        "manifest_bytes": STAGE_A_MANIFEST_BYTES,
        "published_exact_bytes": published_exact,
        "allocation_unit_bytes": allocation_unit,
        "temp_directory_metadata_bound_bytes": temp_directory_metadata_bound,
        "final_directory_metadata_bound_bytes": final_directory_metadata_bound,
        "temporary_allocated_upper_bytes": temporary_allocated,
        "published_allocated_upper_bytes": published_allocated,
        "publication_allocated_high_water_bytes": high_water,
        "disk_safety_reserve_bytes": disk_safety_reserve,
        "admission_free_space_bytes": admission,
        "allocated_disk_bytes": "NOT MEASURED",
        "state_component_bytes": state_component,
        "numeric_component_bytes": numeric_component,
        "validity_component_bytes": validity_component,
        "prototype_metadata_bytes": STAGE_A_METADATA_BYTES,
        "prototype_manifest_bytes": STAGE_A_MANIFEST_BYTES,
    }


def pwrite_last_segment_vector(format_row: dict[str, object]) -> tuple[int, ...]:
    rows = int(format_row["rows"])
    primitive = int(format_row["primitive_columns"])
    numeric = int(format_row["numeric_columns"])
    row = rows - 1
    tile_row, local_row = divmod(row, TR)
    state_tiles = int(format_row["state_column_tiles"])
    numeric_tiles = int(format_row["numeric_column_tiles"])
    state_column = state_tiles - 1
    numeric_column = numeric_tiles - 1
    state_extent = primitive - state_column * TC
    numeric_extent = numeric - numeric_column * TC
    state_offset = checked_sum(
        (HEADER_BYTES,
         mul(add(mul(tile_row, state_tiles, "state tile row"), state_column),
             STATE_TILE_BYTES, "state tile offset"),
         mul(local_row, TC, "state local row")), "state pwrite offset"
    )
    numeric_offset = checked_sum(
        (HEADER_BYTES,
         mul(add(mul(tile_row, numeric_tiles, "numeric tile row"), numeric_column),
             NUMERIC_TILE_BYTES, "numeric tile offset"),
         mul(local_row, TC * 8, "numeric local row")), "numeric pwrite offset"
    )
    validity_offset = checked_sum(
        (HEADER_BYTES,
         mul(add(mul(tile_row, numeric_tiles, "validity tile row"), numeric_column),
             VALIDITY_TILE_BYTES, "validity tile offset"),
         mul(local_row, TC // 8, "validity local row")), "validity pwrite offset"
    )
    state_end = add(state_offset, state_extent, "state pwrite end")
    numeric_end = add(numeric_offset, mul(numeric_extent, 8), "numeric pwrite end")
    validity_end = add(validity_offset, ceil_div(numeric_extent, 8),
                       "validity pwrite end")
    for value in (state_offset, state_end, numeric_offset, numeric_end,
                  validity_offset, validity_end):
        check_file_target(value)
    return (state_offset, state_end, numeric_offset, numeric_end,
            validity_offset, validity_end)


def outcome(case: str, expected: str, operation) -> dict[str, str]:
    try:
        operation()
        observed = "ACCEPT"
    except (KeyError, OverflowError, ValueError):
        observed = "REJECT"
    return {"case": case, "expected": expected, "observed": observed,
            "result": "PASS" if expected == observed else "FAIL"}


def exact(case: str, expected, operation) -> dict[str, str]:
    try:
        observed = operation()
    except Exception as error:
        observed = f"ERROR:{type(error).__name__}"
    return {"case": case, "expected": str(expected), "observed": str(observed),
            "result": "PASS" if observed == expected else "FAIL"}


def overflow_and_exact_corpus(authority_format: dict[str, object]) -> list[dict[str, str]]:
    authority = charge_backend(
        "authority_shape_compact_lower_bound", authority_format,
        "COMPACT_IN_MEMORY", "HARD_PAYLOAD_LOWER_BOUND", "BACKEND_ONLY",
        mandatory_terms(), True,
    )
    construction = construction_projection(authority_format)
    compact_vectors = []
    for name, rows, primitive, bstar in (
        ("one_cell", 1, 1, 0),
        ("exact_256", 256, 256, 0),
        ("partial_257", 257, 257, 0),
        ("multi_257", 257, 257, 2),
    ):
        projected = project_format(name, rows, primitive, bstar, "EXACT_TEST_VECTOR")
        compact_vectors.append(charge_backend(
            name, projected, "COMPACT_IN_MEMORY", "HARD_PAYLOAD_LOWER_BOUND",
            "BACKEND_ONLY", mandatory_terms(), True,
        ))
    signed_gap = project_format("signed_file_gap", 1, 0, 1 << 52,
                                "OVERFLOW_TEST")
    pwrite_gap = project_format("pwrite_gap", 256, 1, (1 << 52) - 1,
                                "OVERFLOW_TEST")
    slice_only = project_format("slice_only_r_unavailable", INT_MAX + 1, 1, 0,
                                "OVERFLOW_TEST")
    slice_charge = charge_backend(
        "slice_only_r_unavailable", slice_only, "TILED_DISK", "OVERFLOW_TEST",
        "BACKEND_ONLY", mandatory_terms(), False,
    )
    magnified_validator = project_format(
        "magnified_validator", 1, 100000, 1, "EXACT_VALIDATOR_VECTOR"
    )
    magnified_compact = charge_backend(
        "magnified_validator_compact", magnified_validator,
        "COMPACT_IN_MEMORY", "EXACT_VALIDATOR_VECTOR", "BACKEND_ONLY",
        mandatory_terms(), False,
    )
    magnified_tiled = charge_backend(
        "magnified_validator_tiled", magnified_validator,
        "TILED_DISK", "EXACT_VALIDATOR_VECTOR", "BACKEND_ONLY",
        mandatory_terms(), False,
    )
    authority_row_file = flat_file_construction_projection(
        authority_format, "ROW_MAJOR_DISK",
        temp_directory_metadata_bound=mib(1),
        final_directory_metadata_bound=mib(1),
        disk_safety_reserve=mib(64),
    )
    authority_column_file = flat_file_construction_projection(
        authority_format, "COLUMN_MAJOR_DISK",
        temp_directory_metadata_bound=mib(1),
        final_directory_metadata_bound=mib(1),
        disk_safety_reserve=mib(64),
    )
    authority_row_charge = charge_backend(
        "authority_row_file", authority_format, "ROW_MAJOR_DISK",
        "EXACT_VALIDATOR_VECTOR", "BACKEND_ONLY", mandatory_terms(), False,
    )
    authority_column_charge = charge_backend(
        "authority_column_file", authority_format, "COLUMN_MAJOR_DISK",
        "EXACT_VALIDATOR_VECTOR", "BACKEND_ONLY", mandatory_terms(), False,
    )

    def extra_mandatory_term():
        bad_terms = mandatory_terms()
        bad_terms["undeclared_extra"] = 0
        return charge_backend(
            "bad-extra", authority_format, "COMPACT_IN_MEMORY", "TEST",
            "BACKEND_ONLY", bad_terms, True,
        )

    phase_sentinel = phase_peak_charge(
        100, 0, 0, 10, 0, 20, 20, 40, 50, 65, True, 0,
    )
    nonrequested_r_peak_overflow = phase_peak_charge(
        U64_MAX, 0, 0, 0, 0, 0, 0, 0, 0, 1, False, 0,
    )
    return [
        outcome("u64_add_overflow", "REJECT", lambda: add(U64_MAX, 1)),
        outcome("primitive_plus_bstar_overflow", "REJECT",
                lambda: primitive_plus_bstar(U64_MAX, 1)),
        outcome("tile_count_product_overflow", "REJECT",
                lambda: mul(1 << 32, 1 << 32, "tile count product")),
        outcome("component_length_overflow", "REJECT",
                lambda: add(HEADER_BYTES, mul(U64_MAX, STATE_TILE_BYTES))),
        outcome("index_length_overflow", "REJECT",
                lambda: add(HEADER_BYTES, mul(U64_MAX, INDEX_ENTRY_BYTES))),
        outcome("logical_cell_product_overflow", "REJECT",
                lambda: mul(U64_MAX, 2, "logical cell product")),
        outcome("compact_native_actual_path_overflow", "REJECT",
                lambda: compact_native_charge(U64_MAX, 0, 2)),
        outcome("row_staging_actual_path_overflow", "REJECT",
                lambda: row_staging_charge(0, U64_MAX)),
        outcome("validity_row_overwrite_actual_path_overflow", "REJECT",
                lambda: validity_row_overwrite_charge(U64_MAX // 2 + 1, 9)),
        outcome("r_materialization_actual_path_reject", "REJECT",
                lambda: r_materialization_charge(1, 0, INT_MAX + 1,
                                                 mandatory_terms())),
        outcome("phase_live_sum_actual_path_overflow", "REJECT",
                lambda: phase_peak_charge(U64_MAX, 1, 0, 0, 0, 0, 0, 0, 0,
                                          None, False, 0)),
        outcome("phase_admission_actual_path_overflow", "REJECT",
                lambda: phase_peak_charge(U64_MAX, 0, 0, 0, 0, 0, 0, 0, 0,
                                          None, False, 1)),
        outcome("requested_r_peak_actual_path_overflow", "REJECT",
                lambda: phase_peak_charge(U64_MAX, 0, 0, 0, 0, 0, 0, 0, 0,
                                          1, True, 0)),
        outcome("publication_high_water_overflow", "REJECT",
                lambda: add(U64_MAX, 1, "publication high-water")),
        outcome("construction_disk_reserve_actual_path_overflow", "REJECT",
                lambda: construction_projection(authority_format,
                                                disk_safety_reserve=U64_MAX)),
        outcome("construction_metadata_actual_path_overflow", "REJECT",
                lambda: construction_projection(
                    authority_format, temp_directory_metadata_bound=U64_MAX)),
        outcome("block_rounding_overflow", "REJECT",
                lambda: rounded_file(U64_MAX, 4096)),
        exact(
            "authority_row_file_projection",
            (0, 21442587, 21443611, 22499328, 22503424, 89612288),
            lambda: (
                authority_row_file["row_major_spool_bytes"],
                authority_row_file["temporary_binary_bytes"],
                authority_row_file["published_exact_bytes"],
                authority_row_file["temporary_allocated_upper_bytes"],
                authority_row_file["publication_allocated_high_water_bytes"],
                authority_row_file["admission_free_space_bytes"],
            ),
        ),
        exact(
            "authority_column_file_projection",
            (21441875, 21442587, 21443611, 43941888, 43941888, 111050752),
            lambda: (
                authority_column_file["row_major_spool_bytes"],
                authority_column_file["temporary_binary_bytes"],
                authority_column_file["published_exact_bytes"],
                authority_column_file["temporary_allocated_upper_bytes"],
                authority_column_file["publication_allocated_high_water_bytes"],
                authority_column_file["admission_free_space_bytes"],
            ),
        ),
        exact(
            "authority_flat_validator_profiles",
            ("ROW_MAJOR_PREAD_ACCESS_V1", "COLUMN_MAJOR_GATHER_ACCESS_V1",
             0, 524288),
            lambda: (
                authority_row_charge["production_validator_access_profile"],
                authority_column_charge["production_validator_access_profile"],
                authority_row_charge["writer_tile_or_slab_bytes"],
                authority_column_charge["writer_tile_or_slab_bytes"],
            ),
        ),
        outcome("manifest_rendering_actual_path_overflow", "REJECT",
                lambda: manifest_bytes(0, U64_MAX, 1, 256, 256, 256, 256)),
        outcome("signed_file_offset_boundary", "ACCEPT",
                lambda: check_file_target(SIGNED_FILE_OFFSET_MAX)),
        outcome("signed_file_offset_overflow", "REJECT",
                lambda: check_file_target(SIGNED_FILE_OFFSET_MAX + 1)),
        outcome("construction_signed_component_actual_path", "REJECT",
                lambda: construction_projection(signed_gap)),
        outcome("pwrite_offset_actual_path_overflow", "REJECT",
                lambda: pwrite_last_segment_vector(pwrite_gap)),
        outcome("r_xlen_t_state_boundary", "ACCEPT",
                lambda: check_r_materialization(1 << 26, 1 << 26)),
        outcome("r_xlen_t_state_overflow", "REJECT",
                lambda: check_r_materialization((1 << 26) + 1, 1 << 26)),
        outcome("r_xlen_t_numeric_boundary", "ACCEPT",
                lambda: check_r_materialization(1 << 26, 1 << 26)),
        outcome("r_xlen_t_numeric_overflow", "REJECT",
                lambda: check_r_materialization((1 << 26) + 1, 1 << 26)),
        outcome("int_max_dimension_boundary", "ACCEPT",
                lambda: check_r_materialization(INT_MAX, 1)),
        outcome("int_max_dimension_overflow", "REJECT",
                lambda: check_r_materialization(INT_MAX + 1, 1)),
        outcome("missing_mandatory_planner_term", "REJECT",
                lambda: charge_backend("bad", authority_format, "COMPACT_IN_MEMORY",
                                       "TEST", "BACKEND_ONLY", {}, True)),
        outcome("extra_mandatory_planner_term", "REJECT", extra_mandatory_term),
        outcome("materialization_request_type_gate", "REJECT",
                lambda: charge_backend(
                    "bad-bool", authority_format, "COMPACT_IN_MEMORY", "TEST",
                    "BACKEND_ONLY", mandatory_terms(), 1)),
        outcome("requested_r_unavailable_rejects_backend", "REJECT",
                lambda: charge_backend(
                    "slice-requested", slice_only, "TILED_DISK", "TEST",
                    "BACKEND_ONLY", mandatory_terms(), True)),
        outcome("u64_exact_boundary", "ACCEPT", lambda: add(U64_MAX, 0)),
        exact("unrequested_r_unavailable_slice_backend_accepts",
              "NOT_REQUESTED_UNAVAILABLE_EXCLUDED",
              lambda: slice_charge["r_materialization_status"]),
        exact("unrequested_r_excluded_from_admission", "FALSE",
              lambda: slice_charge["r_materialization_included_in_admission"]),
        exact("unrequested_r_peak_overflow_excluded",
              ("NOT_AVAILABLE", U64_MAX),
              lambda: (
                  nonrequested_r_peak_overflow[
                      "r_materialization_peak_live_bytes"],
                  nonrequested_r_peak_overflow["overall_max_live_bytes"],
              )),
        exact("authority_native_state", 1367275,
              lambda: authority["backend_native_state_bytes"]),
        exact("authority_native_numeric", 19765200,
              lambda: authority["backend_native_numeric_bytes"]),
        exact("authority_native_validity", 308832,
              lambda: authority["backend_native_validity_bytes"]),
        exact("authority_native_total", 21441307,
              lambda: authority["backend_native_total_bytes"]),
        exact("authority_row_staging", 9425,
              lambda: authority["row_staging_total_bytes"]),
        exact("authority_r_state", 5469100,
              lambda: authority["r_state_output_bytes"]),
        exact("authority_r_numeric", 19765200,
              lambda: authority["r_numeric_output_bytes"]),
        exact("authority_compact_plus_owned_r", 46675607,
              lambda: authority["r_materialization_peak_live_bytes"]),
        exact("authority_prepublication_exact", 25747584,
              lambda: construction["temporary_binary_bytes"]),
        exact("authority_published_exact", 25749104,
              lambda: construction["published_exact_bytes"]),
        exact("authority_candidate_total_written", 47190979,
              lambda: construction["candidate_total_bytes_written"]),
        exact("authority_allocated_prepublication", 25763840,
              lambda: construction["temporary_allocated_upper_bytes"]),
        exact("authority_allocated_published", 25767936,
              lambda: construction["published_allocated_upper_bytes"]),
        exact("authority_last_pwrite_offsets",
              (1762048, 1762137, 23531776, 23532272, 367936, 367944),
              lambda: pwrite_last_segment_vector(authority_format)),
        exact("one_cell_native_r_row", (10, 22, 10),
              lambda: (compact_vectors[0]["backend_native_total_bytes"],
                       compact_vectors[0]["r_materialization_peak_live_bytes"],
                       compact_vectors[0]["row_staging_total_bytes"])),
        exact("exact_256_native_r_row", (598016, 1384448, 2336),
              lambda: (compact_vectors[1]["backend_native_total_bytes"],
                       compact_vectors[1]["r_materialization_peak_live_bytes"],
                       compact_vectors[1]["row_staging_total_bytes"])),
        exact("partial_257_native_r_row", (602698, 1395286, 2346),
              lambda: (compact_vectors[2]["backend_native_total_bytes"],
                       compact_vectors[2]["r_materialization_peak_live_bytes"],
                       compact_vectors[2]["row_staging_total_bytes"])),
        exact("multi_257_native_r_row", (606874, 1403574, 2362),
              lambda: (compact_vectors[3]["backend_native_total_bytes"],
                       compact_vectors[3]["r_materialization_peak_live_bytes"],
                       compact_vectors[3]["row_staging_total_bytes"])),
        exact(
            "magnified_validator_algorithm_and_peak",
            (
                "MULTIPASS_ROW_SEGMENT_V1", "COMPACT_LOGICAL_ARRAY_ACCESS_V1",
                2337, "MULTIPASS_ROW_SEGMENT_V1", "TILED_PREAD_ACCESS_V1",
                65536,
            ),
            lambda: (
                magnified_compact["production_validator_algorithm"],
                magnified_compact["production_validator_access_profile"],
                magnified_compact["production_validator_bytes"],
                magnified_tiled["production_validator_algorithm"],
                magnified_tiled["production_validator_access_profile"],
                magnified_tiled["production_validator_bytes"],
            ),
        ),
        exact(
            "magnified_validator_segments",
            (256, 2048, 32, 2336, 32, 1, 289, 2336),
            lambda: (
                magnified_compact["production_validator_state_segment_bytes"],
                magnified_compact["production_validator_numeric_segment_bytes"],
                magnified_compact["production_validator_validity_segment_bytes"],
                magnified_compact[
                    "production_validator_standard_semantic_segment_bytes"],
                magnified_compact[
                    "production_validator_composite_occupancy_bytes"],
                magnified_compact[
                    "production_validator_composite_bstar_validity_window_bytes"],
                magnified_compact[
                    "production_validator_composite_segment_bytes"],
                magnified_compact["production_validator_tile_or_segment_bytes"],
            ),
        ),
        exact(
            "magnified_validator_access_amplification",
            (391, 1, 100000, 391, 391, 391, 391),
            lambda: (
                magnified_compact[
                    "production_validator_primitive_segment_count"],
                magnified_compact[
                    "production_validator_bstar_validity_window_count"],
                magnified_compact[
                    "production_validator_composite_state_read_bytes"],
                magnified_compact[
                    "production_validator_composite_bstar_validity_rescan_windows"],
                magnified_compact[
                    "production_validator_composite_bstar_source_read_bytes_upper"],
                magnified_compact[
                    "production_validator_composite_bstar_source_read_ops_upper"],
                magnified_compact[
                    "production_validator_registry_entry_segment_probes_upper"],
            ),
        ),
        exact("phase_nonconcurrency_actual_helper",
              (110, 120, 140, 150, 165, 165),
              lambda: (
                  phase_sentinel["construction_peak_live_bytes"],
                  phase_sentinel["finalization_hash_peak_live_bytes"],
                  phase_sentinel["production_validation_peak_live_bytes"],
                  phase_sentinel["independent_validation_peak_live_bytes"],
                  phase_sentinel["r_materialization_peak_live_bytes"],
                  phase_sentinel["overall_max_live_bytes"],
              )),
    ]


def write_table(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def mib(value: int) -> int:
    return mul(value, 1024 * 1024, "MiB budget")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format-output", required=True, type=Path)
    parser.add_argument("--charge-output", required=True, type=Path)
    parser.add_argument("--construction-output", required=True, type=Path)
    parser.add_argument("--overflow-output", required=True, type=Path)
    args = parser.parse_args()
    formats = [
        project_format("tiny_correctness", 3, 4, 2, "FIXTURE_DERIVED_FORMAT_BYTES"),
        project_format("catnip10_like_synthetic", 10, 17, 8,
                       "FORMAT_ONLY_PROJECTION"),
        project_format("authority_shape_synthetic", 2275, 601, 485,
                       "FORMAT_ONLY_PROJECTION"),
        project_format("moderate_churn_synthetic", 10000, 1000, 1000,
                       "FORMAT_ONLY_PROJECTION"),
        project_format("large_projected_shape", 100000, 1997, 2916,
                       "FORMAT_ONLY_PROJECTION"),
    ]
    authority = formats[2]
    charges = [
        charge_backend(
            "tiny_compact_lower_bound", formats[0], "COMPACT_IN_MEMORY",
            "HARD_PAYLOAD_LOWER_BOUND", "BACKEND_ONLY", mandatory_terms(), True),
        charge_backend(
            "authority_shape_compact_lower_bound", authority, "COMPACT_IN_MEMORY",
            "HARD_PAYLOAD_LOWER_BOUND", "BACKEND_ONLY", mandatory_terms(), True),
        charge_backend(
            "authority_shape_compact_declared", authority, "COMPACT_IN_MEMORY",
            "DECLARED_SYNTHETIC_ADMISSION_BUDGET_NOT_MEASURED", "BACKEND_ONLY",
            mandatory_terms(
                registry_representation_bytes=mib(1), r_orchestration_bytes=mib(2),
                backend_native_allocation_overhead_bytes=mib(1),
                r_dimnames_and_registry_bytes=mib(2),
                r_conversion_scratch_bytes=mib(1),
                r_allocator_and_object_overhead_bytes=mib(2),
                production_validator_registry_bytes=mib(1),
                production_validator_overhead_bytes=mib(1),
                independent_validator_registry_bytes=mib(1),
                independent_validator_overhead_bytes=mib(1),
                implementation_overhead_bytes=mib(2), safety_reserve_bytes=mib(32)),
            True),
        charge_backend(
            "authority_shape_tiled_declared", authority, "TILED_DISK",
            "DECLARED_SYNTHETIC_ADMISSION_BUDGET_NOT_MEASURED", "BACKEND_ONLY",
            mandatory_terms(
                registry_representation_bytes=mib(1), r_orchestration_bytes=mib(2),
                backend_native_allocation_overhead_bytes=mib(1),
                r_dimnames_and_registry_bytes=mib(2),
                r_conversion_scratch_bytes=mib(1),
                r_allocator_and_object_overhead_bytes=mib(2),
                production_validator_registry_bytes=mib(1),
                production_validator_overhead_bytes=mib(1),
                independent_validator_registry_bytes=mib(1),
                independent_validator_overhead_bytes=mib(1),
                implementation_overhead_bytes=mib(2), safety_reserve_bytes=mib(32)),
            True),
        charge_backend(
            "large_integrated_tiled_projection", formats[4], "TILED_DISK",
            "DECLARED_SYNTHETIC_INTEGRATED_PROJECTION_NOT_MEASURED", "INTEGRATED_FUTURE",
            mandatory_terms(
                truth_plan_store_bytes=mib(128), gene_workspace_bytes=mib(64),
                empirical_split_index_bytes=mib(128),
                registry_representation_bytes=mib(32), r_orchestration_bytes=mib(64),
                backend_native_allocation_overhead_bytes=mib(8),
                r_dimnames_and_registry_bytes=mib(64),
                r_conversion_scratch_bytes=mib(8),
                r_allocator_and_object_overhead_bytes=mib(64),
                production_validator_registry_bytes=mib(16),
                production_validator_overhead_bytes=mib(8),
                independent_validator_registry_bytes=mib(16),
                independent_validator_overhead_bytes=mib(8),
                implementation_overhead_bytes=mib(64), safety_reserve_bytes=mib(256)),
            False),
    ]
    construction = [construction_projection(row) for row in formats]
    corpus = overflow_and_exact_corpus(authority)
    if any(row["result"] != "PASS" for row in corpus):
        raise SystemExit("planner boundary/exact corpus failure")
    write_table(args.format_output, formats)
    write_table(args.charge_output, charges)
    write_table(args.construction_output, construction)
    write_table(args.overflow_output, corpus)
    print(f"FORMAT_ONLY_PROJECTIONS_WRITTEN {len(formats)}")
    print(f"MEMORY_PHASE_CHARGES_WRITTEN {len(charges)}")
    print(f"CONSTRUCTION_PROJECTIONS_WRITTEN {len(construction)}")
    print(f"PLANNER_BOUNDARY_AND_EXACT_CASES_PASS {len(corpus)}/{len(corpus)}")


if __name__ == "__main__":
    main()
