#!/usr/bin/env python3
"""Review-only PrimitiveRowConsistency-v1 admission cases.

This is not a production writer.  It exercises the reference encoder's
candidate-row precondition without importing the independent checker.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from encode_tiny_fixture import (
    DESCRIPTOR_SCHEMA,
    STATE_MAPPED,
    STATE_NA_FUSE,
    STATE_NA_STRUCT,
    STATE_NA_TOPO,
    validate_composite_row_consistency_v1,
    validate_primitive_row_consistency_v1,
)


class ReviewRowAdmissionHarness:
    """Minimal in-memory oracle proving validation precedes row mutation."""

    def __init__(self, registry: dict):
        self.registry = registry
        self.next_row = 0
        self._hash = hashlib.sha256(b"PrimitiveRowConsistency-v1\0")
        # Nonempty sentinel models initialized backend bytes without claiming
        # filesystem persistence or crash durability.
        self._backend_buffer = bytearray(b"E3HARNESS\0")
        self._hash.update(self._backend_buffer)
        self.completion = False

    def snapshot(self) -> dict:
        backend_buffer_bytes = bytes(self._backend_buffer)
        return {
            "next_row": self.next_row,
            "rolling_sha256": self._hash.hexdigest(),
            "completion": self.completion,
            "backend_buffer_bytes": backend_buffer_bytes,
            "backend_buffer_length": len(backend_buffer_bytes),
            "backend_buffer_sha256": hashlib.sha256(
                backend_buffer_bytes
            ).hexdigest(),
        }

    def write_row(self, state_row: list[int], validity_row: list[bool]) -> None:
        validate_primitive_row_consistency_v1(
            self.registry, state_row, validity_row,
            f"candidate row {self.next_row}",
        )
        validate_composite_row_consistency_v1(
            self.registry, state_row, validity_row,
            f"candidate row {self.next_row}",
        )
        # Byte construction and mutable state begin only after admission.
        row_bytes = bytes(state_row) + bytes(int(value) for value in validity_row)
        self._backend_buffer.extend(row_bytes)
        self._hash.update(row_bytes)
        self.next_row += 1

    def finalize(self) -> None:
        self.completion = True


def authority() -> dict:
    return {
        "descriptor_schema": DESCRIPTOR_SCHEMA,
        "taxon_label_bytes_hex": ["41", "42", "43", "44"],
        "primitive_entries": [
            {"terminal": True, "terminal_taxon_id": 0,
             "authority_edge_split_hex": "01"},
            {"terminal": True, "terminal_taxon_id": 1,
             "authority_edge_split_hex": "02"},
            {"terminal": True, "terminal_taxon_id": 2,
             "authority_edge_split_hex": "04"},
            {"terminal": True, "terminal_taxon_id": 3,
             "authority_edge_split_hex": "08"},
            {"terminal": False, "terminal_taxon_id": 0xFFFFFFFF,
             "authority_edge_split_hex": "03"},
        ],
        "gene_ids": ["g0", "g1", "g2"],
        "bstar_members": [[0, 2], [1, 4]],
    }


def render_tsv(records: list[dict]) -> str:
    keys = (
        "case_id", "role", "expected_code", "observed_code",
        "rejected_before_mutation",
        "exact_snapshot_unchanged_after_reject", "same_row_retry_accepted",
        "before_next_row", "after_reject_next_row",
        "before_completion", "after_reject_completion",
        "before_rolling_sha256", "after_reject_rolling_sha256",
        "before_backend_buffer_length", "after_reject_backend_buffer_length",
        "before_backend_buffer_sha256", "after_reject_backend_buffer_sha256",
        "before_backend_buffer_hex", "after_reject_backend_buffer_hex",
        "retry_backend_buffer_length", "retry_backend_buffer_sha256",
        "coverage_claims", "result",
    )
    lines = ["\t".join(keys)]
    lines.extend("\t".join(str(record[key]) for key in keys)
                 for record in records)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        help="optional evidence TSV path; its parent must already exist",
    )
    args = parser.parse_args()
    registry = authority()
    fused_bstar_available = [
        STATE_NA_FUSE, STATE_MAPPED, STATE_NA_FUSE,
        STATE_NA_STRUCT, STATE_NA_TOPO,
    ]
    fused_bstar_validity = [False, True, False, False, False, True, False]
    mapped_invalid = [
        STATE_MAPPED, STATE_NA_FUSE, STATE_MAPPED,
        STATE_MAPPED, STATE_NA_FUSE,
    ]
    mapped_invalid_validity = [True, False, True, False, False, False, False]

    disjoint_composites = [
        STATE_NA_FUSE, STATE_NA_FUSE, STATE_NA_FUSE,
        STATE_MAPPED, STATE_NA_FUSE,
    ]
    disjoint_composites_validity = [
        False, False, False, True, False, True, True,
    ]

    invalid_cases = [
        ("terminal_NA_topo",
         [STATE_NA_TOPO, STATE_MAPPED, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         fused_bstar_validity, registry),
        ("NA_struct_with_primitive_validity_1",
         [STATE_NA_FUSE, STATE_NA_STRUCT, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         fused_bstar_validity, registry),
        ("NA_fuse_with_primitive_validity_1",
         [STATE_NA_FUSE, STATE_NA_FUSE, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         fused_bstar_validity, registry),
        ("NA_topo_with_primitive_validity_1", fused_bstar_available,
         [False, True, False, False, True, True, False], registry),
        ("valid_Bstar_with_Mapped_member",
         [STATE_MAPPED, STATE_MAPPED, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         fused_bstar_validity, registry),
        ("valid_Bstar_with_NA_struct_member",
         [STATE_NA_STRUCT, STATE_MAPPED, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         fused_bstar_validity, registry),
        ("valid_Bstar_with_NA_topo_member",
         [STATE_NA_FUSE, STATE_NA_FUSE, STATE_NA_FUSE,
          STATE_NA_STRUCT, STATE_NA_TOPO],
         [False, False, False, False, False, True, True], registry),
        ("two_valid_Bstar_overlap",
         [STATE_NA_FUSE, STATE_NA_FUSE, STATE_NA_FUSE,
          STATE_MAPPED, STATE_MAPPED],
         [False, False, False, True, True, True, True],
         {**registry, "bstar_members": [[0, 1], [1, 2]]}),
    ]

    failures = []
    records = []
    for name, state_row, validity_row, case_registry in invalid_cases:
        writer = ReviewRowAdmissionHarness(case_registry)
        expected_code = (
            "E3_COMPOSITE_ROW_CONSISTENCY"
            if name.startswith("valid_Bstar") or name == "two_valid_Bstar_overlap"
            else "E3_PRIMITIVE_ROW_CONSISTENCY"
        )
        before = writer.snapshot()
        try:
            writer.write_row(state_row, validity_row)
        except ValueError as error:
            observed_code = str(error).split(":", 1)[0]
            rejected = observed_code == expected_code
        else:
            observed_code = "NONE"
            rejected = False
        after_reject = writer.snapshot()
        unchanged = after_reject == before
        retry_row = writer.next_row
        retry_state = [STATE_NA_FUSE] * 5
        retry_validity = [False] * 5 + [True, False]
        writer.write_row(retry_state, retry_validity)
        after_retry = writer.snapshot()
        continued = (
            retry_row == before["next_row"] and
            writer.next_row == before["next_row"] + 1 and
            after_retry["backend_buffer_bytes"][
                :before["backend_buffer_length"]
            ] == before["backend_buffer_bytes"] and
            after_retry["backend_buffer_length"] >
            before["backend_buffer_length"]
        )
        passed = rejected and unchanged and continued and not writer.completion
        records.append({
            "case_id": name,
            "role": "NEGATIVE_ADMISSION",
            "expected_code": expected_code,
            "observed_code": observed_code,
            "rejected_before_mutation": str(rejected).upper(),
            "exact_snapshot_unchanged_after_reject": str(unchanged).upper(),
            "same_row_retry_accepted": str(continued).upper(),
            "before_next_row": before["next_row"],
            "after_reject_next_row": after_reject["next_row"],
            "before_completion": str(before["completion"]).upper(),
            "after_reject_completion": str(after_reject["completion"]).upper(),
            "before_rolling_sha256": before["rolling_sha256"],
            "after_reject_rolling_sha256": after_reject["rolling_sha256"],
            "before_backend_buffer_length": before["backend_buffer_length"],
            "after_reject_backend_buffer_length": (
                after_reject["backend_buffer_length"]
            ),
            "before_backend_buffer_sha256": before["backend_buffer_sha256"],
            "after_reject_backend_buffer_sha256": (
                after_reject["backend_buffer_sha256"]
            ),
            "before_backend_buffer_hex": before["backend_buffer_bytes"].hex(),
            "after_reject_backend_buffer_hex": (
                after_reject["backend_buffer_bytes"].hex()
            ),
            "retry_backend_buffer_length": after_retry["backend_buffer_length"],
            "retry_backend_buffer_sha256": after_retry["backend_buffer_sha256"],
            "coverage_claims": name,
            "result": "PASS" if passed else "FAIL",
        })
        if not passed:
            failures.append(name)

    writer = ReviewRowAdmissionHarness(registry)
    writer.write_row(fused_bstar_available, fused_bstar_validity)
    writer.write_row(disjoint_composites, disjoint_composites_validity)
    writer.write_row(mapped_invalid, mapped_invalid_validity)
    writer.finalize()
    rows = (
        (fused_bstar_available, fused_bstar_validity),
        (disjoint_composites, disjoint_composites_validity),
        (mapped_invalid, mapped_invalid_validity),
    )
    mapped_valid_seen = any(
        state_row[column] == STATE_MAPPED and validity_row[column]
        for state_row, validity_row in rows
        for column in range(5)
    )
    mapped_invalid_seen = any(
        state_row[column] == STATE_MAPPED and not validity_row[column]
        for state_row, validity_row in rows
        for column in range(5)
    )
    positive = (
        writer.next_row == 3 and writer.completion and mapped_valid_seen and
        mapped_invalid_seen and
        fused_bstar_available[3] == STATE_NA_STRUCT and
        not fused_bstar_validity[3] and
        fused_bstar_available[0] == STATE_NA_FUSE and
        not fused_bstar_validity[0] and
        fused_bstar_available[4] == STATE_NA_TOPO and
        not fused_bstar_validity[4] and
        0 in registry["bstar_members"][0] and fused_bstar_validity[5]
    )
    records.append({
        "case_id": "positive_coverage",
        "role": "POSITIVE_ADMISSION",
        "expected_code": "NOT_APPLICABLE",
        "observed_code": "NOT_APPLICABLE",
        "rejected_before_mutation": "NOT_APPLICABLE",
        "exact_snapshot_unchanged_after_reject": "NOT_APPLICABLE",
        "same_row_retry_accepted": "NOT_APPLICABLE",
        "before_next_row": "NOT_APPLICABLE",
        "after_reject_next_row": "NOT_APPLICABLE",
        "before_completion": "NOT_APPLICABLE",
        "after_reject_completion": "NOT_APPLICABLE",
        "before_rolling_sha256": "NOT_APPLICABLE",
        "after_reject_rolling_sha256": "NOT_APPLICABLE",
        "before_backend_buffer_length": "NOT_APPLICABLE",
        "after_reject_backend_buffer_length": "NOT_APPLICABLE",
        "before_backend_buffer_sha256": "NOT_APPLICABLE",
        "after_reject_backend_buffer_sha256": "NOT_APPLICABLE",
        "before_backend_buffer_hex": "NOT_APPLICABLE",
        "after_reject_backend_buffer_hex": "NOT_APPLICABLE",
        "retry_backend_buffer_length": writer.snapshot()["backend_buffer_length"],
        "retry_backend_buffer_sha256": writer.snapshot()["backend_buffer_sha256"],
        "coverage_claims": (
            "mapped_validity_1;mapped_validity_0;"
            "terminal_na_struct_validity_0;terminal_na_fuse_validity_0;"
            "internal_na_topo_validity_0;"
            "primitive_na_fuse_bstar_available"
            ";two_valid_disjoint_bstar;na_fuse_with_bstar_validity_0"
        ),
        "result": "PASS" if positive else "FAIL",
    })
    if not positive:
        failures.append("positive_coverage")

    rendered = render_tsv(records)
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_bytes(rendered.encode("utf-8"))

    if failures:
        raise SystemExit("writer semantic failures: " + ",".join(failures))
    suffix = f" output={args.output}" if args.output is not None else ""
    print(f"WRITER_SEMANTIC_CASES_PASS {len(records)}/{len(records)}{suffix}")


if __name__ == "__main__":
    main()
