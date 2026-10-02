#!/usr/bin/env python3
"""Generate a bounded-checker Stage-A tiled store without recording timing.

This is a review-only producer.  It imports the reference encoder/formula and
is intentionally forbidden from the independent checker import graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from encode_boundary_fixture import indexed_entry
from encode_tiny_fixture import (
    HEADER_BYTES,
    TILE_COLS,
    TILE_ROWS,
    bstar_registry_digest,
    canonical_bstar_members,
    completion_footer,
    data_header,
    gene_registry_digest,
    index_header,
    manifest_text,
    numeric_registry_digest,
    sha,
    species_authority_digest,
    u16,
    u64,
)
from stage_a_authority_v2 import canonical_descriptor_bytes
from stage_a_fiber_v3 import (
    EXPECTED_IDENTITIES,
    FORMULA_ID,
    complete_descriptor,
    evaluate,
    primitive_state,
)


CASES = {
    "catnip10_like": (10, 17, 8),
    "authority_shape": (2275, 601, 485),
}


def ceil_div(value: int, divisor: int) -> int:
    return divmod(value, divisor)[0] + int(value % divisor != 0)


def row_vectors(descriptor: dict, terminals: list[bool], row: int) -> tuple[bytes, bytes]:
    states = bytes(
        primitive_state(terminals[primitive], row, primitive)
        for primitive in range(len(terminals))
    )
    valid = bytearray(len(terminals) + len(descriptor["bstar_members"]))
    for primitive, state in enumerate(states):
        valid[primitive] = int(state == 0 and ((row + 5 * primitive) % 4 != 0))
    occupied: set[int] = set()
    for bstar_id, members in enumerate(descriptor["bstar_members"]):
        candidate = (
            ((row + 7 * bstar_id + 1) % 5 != 0)
            and all(states[member] == 2 for member in members)
        )
        available = candidate and not occupied.intersection(members)
        if available:
            occupied.update(members)
        valid[len(terminals) + bstar_id] = int(available)
    return states, bytes(valid)


def tile_payload(component: int, tile_row: int, tile_column: int, rows: int,
                 columns: int, descriptor: dict, terminals: list[bool]) -> bytes:
    tile_bytes = {1: 65536, 2: 524288, 3: 8192}[component]
    output = bytearray(tile_bytes)
    row_start, column_start = tile_row * TILE_ROWS, tile_column * TILE_COLS
    row_extent = min(TILE_ROWS, rows - row_start)
    column_extent = min(TILE_COLS, columns - column_start)
    cached = [row_vectors(descriptor, terminals, row_start + local)
              for local in range(row_extent)]
    for local_row, (states, validity) in enumerate(cached):
        for local_column in range(column_extent):
            column = column_start + local_column
            cell = local_row * TILE_COLS + local_column
            if component == 1:
                output[cell] = states[column]
            elif component == 2:
                if validity[column]:
                    linear = (row_start + local_row) * columns + column
                    bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
                    struct.pack_into("<Q", output, cell * 8, bits)
            elif validity[column]:
                output[cell // 8] |= 1 << (cell % 8)
    return bytes(output)


def build_component(component: int, magic: bytes, rows: int, columns: int,
                    coordinate_digest: bytes, descriptor: dict, terminals: list[bool],
                    species: bytes, genes: bytes) -> tuple[bytes, list[bytes]]:
    tile_bytes = {1: 65536, 2: 524288, 3: 8192}[component]
    payloads = []
    for tile_row in range(ceil_div(rows, TILE_ROWS) if rows else 0):
        for tile_column in range(ceil_div(columns, TILE_COLS) if columns else 0):
            payloads.append(tile_payload(
                component, tile_row, tile_column, rows, columns,
                descriptor, terminals,
            ))
    header = data_header(
        magic, component, component, rows, columns, tile_bytes,
        species, genes, coordinate_digest,
    )
    return header + b"".join(payloads), payloads


class BitPacker:
    def __init__(self, hasher):
        self.hasher = hasher
        self.current = 0
        self.used = 0
        self.count = 0

    def add(self, value: bool) -> None:
        if value:
            self.current |= 1 << self.used
        self.used += 1
        if self.used == 8:
            self.hasher.update(bytes([self.current]))
            self.count += 1
            self.current = self.used = 0

    def finish(self) -> None:
        if self.used:
            self.hasher.update(bytes([self.current]))
            self.count += 1
            self.current = self.used = 0


def logical_digest(descriptor: dict, terminals: list[bool], rows: int,
                   primitive: int, bstar: int, authorities: tuple[bytes, ...]) -> tuple[bytes, dict[str, str]]:
    numeric = primitive + bstar
    logical = hashlib.sha256()
    logical.update(b"SplitAlignerR/MatrixLogicalContent/v1\0")
    logical.update(u16(1) + u16(0) + u64(rows) + u64(primitive) + u64(bstar) + u64(numeric))
    for value in authorities:
        logical.update(value)

    state_hash = hashlib.sha256()
    logical.update(u64(rows * primitive))
    for row in range(rows):
        states, _ = row_vectors(descriptor, terminals, row)
        state_hash.update(states)
        logical.update(states)

    numeric_hash = hashlib.sha256()
    logical.update(u64(rows * numeric * 8))
    for row in range(rows):
        _, validity = row_vectors(descriptor, terminals, row)
        row_bytes = bytearray(numeric * 8)
        for coordinate, available in enumerate(validity):
            if available:
                linear = row * numeric + coordinate
                bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
                struct.pack_into("<Q", row_bytes, coordinate * 8, bits)
        numeric_hash.update(row_bytes)
        logical.update(row_bytes)

    validity_length = ceil_div(rows * numeric, 8)
    logical.update(u64(validity_length))
    validity_hash = hashlib.sha256()
    logical_packer = BitPacker(logical)
    validity_packer = BitPacker(validity_hash)
    for row in range(rows):
        _, validity = row_vectors(descriptor, terminals, row)
        for available in validity:
            logical_packer.add(bool(available))
            validity_packer.add(bool(available))
    logical_packer.finish()
    validity_packer.finish()
    if logical_packer.count != validity_length or validity_packer.count != validity_length:
        raise AssertionError("continuous validity length mismatch")
    return logical.digest(), {
        "state_stream_sha256": state_hash.hexdigest(),
        "numeric_stream_sha256": numeric_hash.hexdigest(),
        "validity_stream_sha256": validity_hash.hexdigest(),
    }


def build(case_id: str, store: Path, descriptor_path: Path) -> dict[str, object]:
    rows, primitive_count, bstar_count = CASES[case_id]
    descriptor, _construction, _scope = complete_descriptor(
        case_id, rows, primitive_count, bstar_count
    )
    raw_descriptor = canonical_descriptor_bytes(descriptor)
    terminals = [entry["terminal"] for entry in descriptor["primitive_entries"]]
    species = species_authority_digest(descriptor)
    genes = gene_registry_digest(descriptor["gene_ids"])
    encoded_members = canonical_bstar_members(descriptor["bstar_members"], primitive_count)
    bstar = bstar_registry_digest(species, encoded_members)
    numeric_registry = numeric_registry_digest(
        species, primitive_count, bstar, encoded_members
    )
    numeric_count = primitive_count + bstar_count
    logical, stream_hashes = logical_digest(
        descriptor, terminals, rows, primitive_count, bstar_count,
        (species, genes, species, bstar, numeric_registry),
    )
    semantic_record, expected_descriptor = evaluate(
        case_id, rows, primitive_count, bstar_count
    )
    if expected_descriptor != raw_descriptor:
        raise AssertionError("descriptor bytes differ from Stage-A V3 authority")
    for key, observed in stream_hashes.items():
        if observed != semantic_record[key]:
            raise AssertionError(f"{key} differs from frozen semantic oracle")

    specifications = (
        (1, b"SARST001", primitive_count, species, "STATE.bin"),
        (2, b"SARNM001", numeric_count, numeric_registry, "NUMERIC.bin"),
        (3, b"SARVL001", numeric_count, numeric_registry, "VALIDITY.bin"),
    )
    components: dict[str, bytes] = {}
    payloads: dict[int, list[bytes]] = {}
    for component, magic, columns, coordinate, name in specifications:
        components[name], payloads[component] = build_component(
            component, magic, rows, columns, coordinate, descriptor, terminals,
            species, genes,
        )
    entries = []
    for component, _magic, columns, _coordinate, _name in specifications:
        tile_bytes = {1: 65536, 2: 524288, 3: 8192}[component]
        column_tiles = ceil_div(columns, 256)
        for tile_row in range(ceil_div(rows, 256)):
            for tile_column in range(column_tiles):
                payload = payloads[component][tile_row * column_tiles + tile_column]
                entries.append(indexed_entry(
                    component, tile_row, tile_column,
                    min(256, rows - tile_row * 256),
                    min(256, columns - tile_column * 256),
                    column_tiles, tile_bytes, payload,
                ))
    components["TILE_INDEX.bin"] = index_header(
        len(entries), rows, primitive_count, bstar_count, species, genes,
        species, bstar, numeric_registry,
    ) + b"".join(entries)
    components["COMPLETION.bin"] = completion_footer(
        components, logical, species, genes, species, bstar, numeric_registry,
        rows, primitive_count, bstar_count,
    )
    components["VALIDATED"] = manifest_text(
        components, logical, species, genes, species, bstar, numeric_registry,
        rows, primitive_count, bstar_count,
    )
    store.mkdir(parents=True)
    for name, value in components.items():
        (store / name).write_bytes(value)
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_bytes(raw_descriptor)
    expected_identity = EXPECTED_IDENTITIES[case_id]
    if hashlib.sha256(raw_descriptor).hexdigest() != expected_identity[0]:
        raise AssertionError("descriptor identity mismatch")
    return {
        "status": "REFERENCE_STAGE_A_TILED_STORE_WRITTEN_NO_TIMING",
        "case_id": case_id, "formula_id": FORMULA_ID,
        "rows": rows, "primitive_count": primitive_count,
        "bstar_count": bstar_count, "logical_content_sha256": logical.hex(),
        "descriptor_sha256": hashlib.sha256(raw_descriptor).hexdigest(),
        "stream_hashes": stream_hashes,
        "components": {name: {"bytes": len(value), "sha256": sha(value).hex()}
                       for name, value in components.items()},
        "timing_executed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=tuple(CASES))
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.store.exists() or args.descriptor.exists():
        raise SystemExit("refusing to overwrite existing output")
    result = build(args.case, args.store, args.descriptor)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
