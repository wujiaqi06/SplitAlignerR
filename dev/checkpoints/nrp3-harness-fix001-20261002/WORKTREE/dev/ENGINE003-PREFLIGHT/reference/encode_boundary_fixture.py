#!/usr/bin/env python3
"""NON-PRODUCTION multi-tile fixture encoder for ENGINE003-PREFLIGHT-FIX002.

This review-only program deliberately reuses the frozen reference-format
helpers.  It is not a production writer and is never imported by the
independent checker.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

from canonical_text import write_canonical_json

from encode_tiny_fixture import (
    DESCRIPTOR_SCHEMA,
    FOOTER_BYTES,
    HEADER_BYTES,
    INDEX_ENTRY_BYTES,
    STATE_MAPPED,
    STATE_NA_FUSE,
    STATE_NA_STRUCT,
    TILE_COLS,
    TILE_ROWS,
    bstar_registry_digest,
    canonical_bstar_members,
    ceil_div,
    completion_footer,
    data_header,
    gene_registry_digest,
    index_header,
    logical_hash,
    manifest_text,
    numeric_registry_digest,
    sha,
    species_authority_digest,
    u16,
    u32,
    u64,
    validate_fixture_rows_v1,
)


def terminal_registry(taxon_count: int, rows: int, bstar_members: list[list[int]]) -> dict:
    width = ceil_div(taxon_count, 8)
    entries = []
    for taxon_id in range(taxon_count):
        split = (1 << taxon_id).to_bytes(width, "little")
        entries.append({
            "terminal": True,
            "terminal_taxon_id": taxon_id,
            "authority_edge_split_hex": split.hex(),
        })
    return {
        "descriptor_schema": DESCRIPTOR_SCHEMA,
        "taxon_label_bytes_hex": [
            f"T{taxon_id:04d}".encode("ascii").hex()
            for taxon_id in range(taxon_count)
        ],
        "primitive_entries": entries,
        "gene_ids": [f"g{row:04d}" for row in range(rows)],
        "bstar_members": bstar_members,
    }


def fixture_values(
    rows: int, primitive_count: int, bstar_members: list[list[int]],
):
    numeric_count = primitive_count + len(bstar_members)
    state_cycle = (STATE_MAPPED, STATE_NA_STRUCT, STATE_NA_FUSE)
    state = [[state_cycle[(row * 3 + column) % len(state_cycle)]
              for column in range(primitive_count)]
             for row in range(rows)]
    valid = []
    for row in range(rows):
        validity_row = []
        for column in range(primitive_count):
            available = (row + column) % 7 != 0
            available = state[row][column] == STATE_MAPPED and available
            validity_row.append(available)
        occupied: set[int] = set()
        for bstar_id, members in enumerate(bstar_members):
            candidate = (
                (row + primitive_count + bstar_id) % 7 != 0
                and all(state[row][member] == STATE_NA_FUSE for member in members)
            )
            available = candidate and not occupied.intersection(members)
            if available:
                occupied.update(members)
            validity_row.append(available)
        valid.append(validity_row)
    values = [[(row + 1) * 0.125 + (column + 1) * 0.0009765625
               for column in range(numeric_count)] for row in range(rows)]
    return state, values, valid


def tile_payloads(
    component_type: int, rows: int, columns: int, state: list[list[int]],
    values: list[list[float]], valid: list[list[bool]]
) -> list[bytes]:
    payloads = []
    row_tiles = ceil_div(rows, TILE_ROWS) if rows else 0
    column_tiles = ceil_div(columns, TILE_COLS) if columns else 0
    for tile_row in range(row_tiles):
        for tile_column in range(column_tiles):
            if component_type == 1:
                payload = bytearray(TILE_ROWS * TILE_COLS)
            elif component_type == 2:
                payload = bytearray(TILE_ROWS * TILE_COLS * 8)
            else:
                payload = bytearray(TILE_ROWS * TILE_COLS // 8)
            for local_row in range(TILE_ROWS):
                row = tile_row * TILE_ROWS + local_row
                if row >= rows:
                    break
                for local_column in range(TILE_COLS):
                    column = tile_column * TILE_COLS + local_column
                    if column >= columns:
                        break
                    cell = local_row * TILE_COLS + local_column
                    if component_type == 1:
                        payload[cell] = state[row][column]
                    elif component_type == 2:
                        value = values[row][column] if valid[row][column] else 0.0
                        if valid[row][column] and not math.isfinite(value):
                            raise ValueError("nonfinite valid numeric fixture value")
                        payload[cell * 8:cell * 8 + 8] = struct.pack("<d", value)
                    elif valid[row][column]:
                        payload[cell // 8] |= 1 << (cell % 8)
            payloads.append(bytes(payload))
    return payloads


def component(
    magic: bytes, component_type: int, rows: int, columns: int,
    payloads: list[bytes], tile_bytes: int, species: bytes, genes: bytes,
    coordinate: bytes
) -> bytes:
    expected = ((ceil_div(rows, TILE_ROWS) if rows else 0) *
                (ceil_div(columns, TILE_COLS) if columns else 0))
    if len(payloads) != expected or any(len(value) != tile_bytes for value in payloads):
        raise ValueError("tile payload geometry mismatch")
    return data_header(
        magic, component_type, component_type, rows, columns, tile_bytes,
        species, genes, coordinate
    ) + b"".join(payloads)


def indexed_entry(
    component_type: int, tile_row: int, tile_column: int, row_extent: int,
    column_extent: int, tile_columns: int, tile_bytes: int, payload: bytes
) -> bytes:
    entry = bytearray(INDEX_ENTRY_BYTES)
    entry[0:2] = u16(component_type)
    entry[2:4] = u16(1)
    entry[8:16] = u64(tile_row)
    entry[16:24] = u64(tile_column)
    entry[24:32] = u64(tile_row * TILE_ROWS)
    entry[32:40] = u64(tile_column * TILE_COLS)
    entry[40:44] = u32(row_extent)
    entry[44:48] = u32(column_extent)
    entry[48:56] = u64(HEADER_BYTES + (tile_row * tile_columns + tile_column) * tile_bytes)
    entry[56:64] = u64(tile_bytes)
    entry[64:68] = u32(TILE_ROWS)
    entry[68:72] = u32(TILE_COLS)
    entry[72:74] = u16(component_type)
    entry[80:112] = sha(payload)
    return bytes(entry)


def make_store(profile: str, output: Path, registry_path: Path) -> dict:
    if profile == "one_cell":
        rows, primitive_count, bstar_members = 1, 1, []
    elif profile == "exact_256":
        rows, primitive_count, bstar_members = 256, 256, []
    elif profile == "multi_257":
        # Encoded order is the exact little-endian member-byte order.  The
        # first set includes primitive ID 256 and therefore detects accidental
        # integer/hex/text sorting in B* canonicalization.
        rows, primitive_count = 257, 257
        bstar_members = [[0, 256], [1, 255]]
    elif profile == "bstar_u32le":
        # Exact encoded-byte order is [256,257] then [255,300]: 0x00 is less
        # than 0xff in the first u32le byte. Integer-list order would reverse
        # these records, so this case detects the wrong comparator.
        rows, primitive_count = 257, 301
        bstar_members = [[256, 257], [255, 300]]
    else:
        raise ValueError(profile)
    registry = terminal_registry(primitive_count, rows, bstar_members)
    bstar_count = len(bstar_members)
    numeric_count = primitive_count + bstar_count
    state, values, valid = fixture_values(rows, primitive_count, bstar_members)
    # Admit every candidate row before any tiled payload is constructed.
    validate_fixture_rows_v1(registry, state, values, valid)

    species = species_authority_digest(registry)
    primitive = species
    genes = gene_registry_digest(registry["gene_ids"])
    encoded_members = canonical_bstar_members(bstar_members, primitive_count)
    bstar = bstar_registry_digest(primitive, encoded_members)
    numeric_registry = numeric_registry_digest(
        primitive, primitive_count, bstar, encoded_members
    )

    specifications = (
        (1, b"SARST001", primitive_count, TILE_ROWS * TILE_COLS, primitive),
        (2, b"SARNM001", numeric_count, TILE_ROWS * TILE_COLS * 8, numeric_registry),
        (3, b"SARVL001", numeric_count, TILE_ROWS * TILE_COLS // 8, numeric_registry),
    )
    components = {}
    payload_by_component = {}
    for component_type, magic, columns, tile_bytes, coordinate in specifications:
        payloads = tile_payloads(component_type, rows, columns, state, values, valid)
        payload_by_component[component_type] = payloads
        name = {1: "STATE.bin", 2: "NUMERIC.bin", 3: "VALIDITY.bin"}[component_type]
        components[name] = component(
            magic, component_type, rows, columns, payloads, tile_bytes,
            species, genes, coordinate
        )

    entries = []
    for component_type, _, columns, tile_bytes, _ in specifications:
        row_tiles = ceil_div(rows, TILE_ROWS)
        column_tiles = ceil_div(columns, TILE_COLS)
        for tile_row in range(row_tiles):
            for tile_column in range(column_tiles):
                entries.append(indexed_entry(
                    component_type, tile_row, tile_column,
                    min(TILE_ROWS, rows - tile_row * TILE_ROWS),
                    min(TILE_COLS, columns - tile_column * TILE_COLS),
                    column_tiles, tile_bytes,
                    payload_by_component[component_type][tile_row * column_tiles + tile_column],
                ))
    components["TILE_INDEX.bin"] = index_header(
        len(entries), rows, primitive_count, bstar_count, species, genes,
        primitive, bstar, numeric_registry
    ) + b"".join(entries)
    logical = logical_hash(
        rows, primitive_count, bstar_count, species, genes, primitive, bstar,
        numeric_registry, state, values, valid
    )
    components["COMPLETION.bin"] = completion_footer(
        components, logical, species, genes, primitive, bstar, numeric_registry,
        rows, primitive_count, bstar_count
    )
    components["VALIDATED"] = manifest_text(
        components, logical, species, genes, primitive, bstar, numeric_registry,
        rows, primitive_count, bstar_count
    )

    output.mkdir(parents=True)
    for name, value in components.items():
        (output / name).write_bytes(value)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    write_canonical_json(registry_path, registry)
    return {
        "status": "REFERENCE_BOUNDARY_FIXTURE_WRITTEN_NON_PRODUCTION",
        "profile": profile,
        "rows": rows,
        "primitive_count": primitive_count,
        "bstar_count": bstar_count,
        "logical_content_sha256": logical.hex(),
        "components": {name: {"bytes": len(value), "sha256": sha(value).hex()}
                       for name, value in components.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True,
                        choices=("one_cell", "exact_256", "multi_257", "bstar_u32le"))
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    if args.store.exists() or args.registry.exists():
        raise SystemExit("refusing to overwrite an existing fixture path")
    print(json.dumps(make_store(args.profile, args.store, args.registry),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
