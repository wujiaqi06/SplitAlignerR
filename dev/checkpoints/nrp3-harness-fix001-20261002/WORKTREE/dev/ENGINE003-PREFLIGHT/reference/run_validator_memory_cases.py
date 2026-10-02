#!/usr/bin/env python3
"""Magnified exact-memory vector for MULTIPASS_ROW_SEGMENT_V1."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from planner_projection import charge_backend, mandatory_terms, project_format


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    format_row = project_format(
        "magnified_validator", 1, 100000, 1, "EXACT_VALIDATOR_VECTOR"
    )
    rows = []
    failures = []
    for backend, expected_access, expected_total in (
        ("COMPACT_IN_MEMORY", "COMPACT_LOGICAL_ARRAY_ACCESS_V1", 2337),
        ("TILED_DISK", "TILED_PREAD_ACCESS_V1", 65536),
    ):
        charge = charge_backend(
            f"magnified_{backend.lower()}", format_row, backend,
            "EXACT_VALIDATOR_VECTOR", "BACKEND_ONLY", mandatory_terms(), False,
        )
        prefix = "production_validator_"
        observed = {
            "algorithm": charge[prefix + "algorithm"],
            "access_profile": charge[prefix + "access_profile"],
            "state_segment_bytes": charge[prefix + "state_segment_bytes"],
            "numeric_segment_bytes": charge[prefix + "numeric_segment_bytes"],
            "validity_segment_bytes": charge[prefix + "validity_segment_bytes"],
            "standard_semantic_segment_bytes":
                charge[prefix + "standard_semantic_segment_bytes"],
            "composite_occupancy_bytes":
                charge[prefix + "composite_occupancy_bytes"],
            "composite_bstar_validity_window_bytes":
                charge[prefix + "composite_bstar_validity_window_bytes"],
            "composite_segment_bytes": charge[prefix + "composite_segment_bytes"],
            "selected_segment_bytes": charge[prefix + "tile_or_segment_bytes"],
            "logical_packer_bytes": charge[prefix + "logical_packer_bytes"],
            "internal_peak_bytes": charge[prefix + "internal_peak_bytes"],
            "validator_total_bytes": charge[prefix + "bytes"],
            "primitive_segment_count": charge[prefix + "primitive_segment_count"],
            "bstar_validity_window_count":
                charge[prefix + "bstar_validity_window_count"],
            "composite_state_read_bytes":
                charge[prefix + "composite_state_read_bytes"],
            "composite_bstar_validity_rescan_windows":
                charge[prefix + "composite_bstar_validity_rescan_windows"],
            "composite_bstar_source_read_bytes_upper":
                charge[prefix + "composite_bstar_source_read_bytes_upper"],
            "composite_bstar_source_read_ops_upper":
                charge[prefix + "composite_bstar_source_read_ops_upper"],
            "registry_entry_segment_probes_upper":
                charge[prefix + "registry_entry_segment_probes_upper"],
        }
        passed = (
            observed["algorithm"] == "MULTIPASS_ROW_SEGMENT_V1"
            and observed["access_profile"] == expected_access
            and tuple(observed[key] for key in (
                "state_segment_bytes", "numeric_segment_bytes",
                "validity_segment_bytes", "standard_semantic_segment_bytes",
                "composite_occupancy_bytes",
                "composite_bstar_validity_window_bytes",
                "composite_segment_bytes", "selected_segment_bytes",
            )) == (256, 2048, 32, 2336, 32, 1, 289, 2336)
            and observed["validator_total_bytes"] == expected_total
            and tuple(observed[key] for key in (
                "primitive_segment_count", "bstar_validity_window_count",
                "composite_state_read_bytes",
                "composite_bstar_validity_rescan_windows",
                "composite_bstar_source_read_bytes_upper",
                "composite_bstar_source_read_ops_upper",
                "registry_entry_segment_probes_upper",
            )) == (391, 1, 100000, 391, 391, 391, 391)
        )
        rows.append({
            "case_id": "G1_B100000_K1",
            "backend": backend,
            "rows": 1,
            "primitive_columns": 100000,
            "bstar_columns": 1,
            "numeric_columns": 100001,
            **observed,
            "result": "PASS" if passed else "FAIL",
        })
        if not passed:
            failures.append(backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    if failures:
        raise SystemExit("validator-memory failures: " + ",".join(failures))
    print("VALIDATOR_MEMORY_CASES_PASS 2/2")


if __name__ == "__main__":
    main()
