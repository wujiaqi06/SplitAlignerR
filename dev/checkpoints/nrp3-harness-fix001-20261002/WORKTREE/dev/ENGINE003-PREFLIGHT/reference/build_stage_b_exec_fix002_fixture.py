#!/usr/bin/env python3
"""Build the small descriptor-driven Stage-B execution-certification fixture.

This generator derives a 129-row fixture from the already frozen Stage-A
authority-shape descriptor.  It is an engineering fixture only: its purpose is
to cross the 128-row scan boundary while keeping all four physical backends
small.  No Stage-B authority workload is constructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from encode_stage_a_tiled_store import row_vectors  # noqa: E402
from encode_tiny_fixture import (  # noqa: E402
    bstar_registry_digest,
    canonical_bstar_members,
    gene_registry_digest,
    numeric_registry_digest,
    species_authority_digest,
)
from stage_a_authority_v2 import canonical_descriptor_bytes  # noqa: E402
from stage_a_fiber_v3 import canonical_pairs  # noqa: E402


SOURCE_SHA256 = "3d2b5b5ff45e053d463978684df16633ad540ee225edc47ab0fbd7510a188fed"
FORMULA = "ENGINE003_STAGE_A_FIBER_CONSISTENT_BITS_V3"
ROWS = 129
PRIMITIVE = 7
BSTAR = 4


class ContinuousBitHasher:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.current = 0
        self.used = 0
        self.count = 0

    def add(self, value: int) -> None:
        if value not in (0, 1):
            raise ValueError("validity must be binary")
        if value:
            self.current |= 1 << self.used
        self.used += 1
        if self.used == 8:
            self.digest.update(bytes([self.current]))
            self.count += 1
            self.current = self.used = 0

    def finish(self) -> tuple[str, int]:
        if self.used:
            self.digest.update(bytes([self.current]))
            self.count += 1
            self.current = self.used = 0
        return self.digest.hexdigest(), self.count


def numeric_row(row: int, columns: int, validity: bytes) -> bytes:
    output = bytearray(columns * 8)
    for column, available in enumerate(validity):
        if available:
            linear = row * columns + column
            bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
            struct.pack_into("<Q", output, column * 8, bits)
    return bytes(output)


def build(source: Path) -> tuple[bytes, dict[str, object]]:
    source_raw = source.read_bytes()
    if hashlib.sha256(source_raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("frozen authority-shape descriptor hash mismatch")
    descriptor = json.loads(source_raw)
    descriptor["gene_ids"] = descriptor["gene_ids"][:ROWS]
    descriptor["primitive_entries"] = descriptor["primitive_entries"][:PRIMITIVE]
    descriptor["bstar_members"] = canonical_pairs(PRIMITIVE, BSTAR)
    raw = canonical_descriptor_bytes(descriptor)

    species = species_authority_digest(descriptor)
    genes = gene_registry_digest(descriptor["gene_ids"])
    encoded = canonical_bstar_members(descriptor["bstar_members"], PRIMITIVE)
    bstar = bstar_registry_digest(species, encoded)
    numeric_registry = numeric_registry_digest(species, PRIMITIVE, bstar, encoded)
    authorities = (species, genes, species, bstar, numeric_registry)
    numeric_count = PRIMITIVE + BSTAR
    terminals = tuple(item["terminal"] for item in descriptor["primitive_entries"])

    state_digest = hashlib.sha256()
    numeric_digest = hashlib.sha256()
    validity_digest = ContinuousBitHasher()
    logical = hashlib.sha256()
    logical.update(b"SplitAlignerR/MatrixLogicalContent/v1\0")
    logical.update(struct.pack(
        "<HHQQQQ", 1, 0, ROWS, PRIMITIVE, BSTAR, numeric_count,
    ))
    for value in authorities:
        logical.update(value)

    state_rows: list[bytes] = []
    numeric_rows: list[bytes] = []
    validity_rows: list[bytes] = []
    for row in range(ROWS):
        state, validity = row_vectors(descriptor, terminals, row)
        numeric = numeric_row(row, numeric_count, validity)
        state_rows.append(state)
        numeric_rows.append(numeric)
        validity_rows.append(validity)

    state_bytes = b"".join(state_rows)
    numeric_bytes = b"".join(numeric_rows)
    state_digest.update(state_bytes)
    numeric_digest.update(numeric_bytes)
    for row in validity_rows:
        for value in row:
            validity_digest.add(value)
    validity_sha, validity_bytes = validity_digest.finish()
    packed = bytearray()
    current = used = 0
    for row in validity_rows:
        for value in row:
            if value:
                current |= 1 << used
            used += 1
            if used == 8:
                packed.append(current)
                current = used = 0
    if used:
        packed.append(current)
    for value in (state_bytes, numeric_bytes, bytes(packed)):
        logical.update(struct.pack("<Q", len(value)))
        logical.update(value)

    metric_raw = (ENGINE / "stage_b/STAGEB_METRIC_CONTRACT.tsv").read_bytes()
    anchor = {
        "complete_descriptor_sha256": hashlib.sha256(raw).hexdigest(),
        "species_authority_sha256": species.hex(),
        "gene_registry_sha256": genes.hex(),
        "primitive_registry_sha256": species.hex(),
        "bstar_registry_sha256": bstar.hex(),
        "numeric_coordinate_registry_sha256": numeric_registry.hex(),
        "state_stream_sha256": state_digest.hexdigest(),
        "numeric_stream_sha256": numeric_digest.hexdigest(),
        "validity_stream_sha256": validity_sha,
        "logical_content_sha256": logical.hexdigest(),
    }
    authority = {
        "schema": "SplitAlignerR/ENGINE003StageBExecFix002BoundedAuthority/v1",
        "fixture_id": "EXEC_PREFLIGHT_DESCRIPTOR_129x7x4_V2",
        "authority_scope": "BOUNDED_ENGINEERING_CERTIFICATION_ONLY",
        "source_descriptor_sha256": SOURCE_SHA256,
        "payload_formula": FORMULA,
        "dimensions": {"G": ROWS, "B": PRIMITIVE, "B_star": BSTAR, "C": numeric_count},
        "anchor": anchor,
        "metric_contract_sha256": hashlib.sha256(metric_raw).hexdigest(),
        "bounded_schedule_id": "BOUNDED_FOUR_CANDIDATE_ONCE_V1",
        "timeout_seconds": 900,
        "memory_admission_required_bytes": 134_217_728,
        "file_disk_admission_required_bytes": 16_777_216,
        "validity_packed_bytes": validity_bytes,
        "generator": "reference/build_stage_b_exec_fix002_fixture.py",
    }
    return raw, authority


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--authority", required=True, type=Path)
    args = parser.parse_args()
    descriptor, authority = build(args.source)
    args.descriptor.parent.mkdir(parents=True, exist_ok=True)
    args.descriptor.write_bytes(descriptor)
    args.authority.write_text(
        json.dumps(authority, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "descriptor_sha256": hashlib.sha256(descriptor).hexdigest(),
        "logical_content_sha256": authority["anchor"]["logical_content_sha256"],
        "status": "BOUNDED_FIXTURE_GENERATION_PASS",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
