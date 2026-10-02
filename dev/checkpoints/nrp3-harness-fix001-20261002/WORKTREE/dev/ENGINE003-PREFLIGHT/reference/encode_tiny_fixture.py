#!/usr/bin/env python3
"""NON-PRODUCTION ENGINE003-PREFLIGHT golden-fixture encoder.

This program writes review fixtures only. It is not a package writer, does not
implement atomic publication, and must never be imported by production code or
the independent checker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

from canonical_text import write_canonical_json


TILE_ROWS = 256
TILE_COLS = 256
HEADER_BYTES = 256
INDEX_ENTRY_BYTES = 128
FOOTER_BYTES = 512
MASK64 = (1 << 64) - 1
DESCRIPTOR_SCHEMA = "SplitAlignerR/ENGINE003ExternalAuthorityDescriptor/v1"
DESCRIPTOR_KEYS = {
    "descriptor_schema", "taxon_label_bytes_hex", "primitive_entries",
    "gene_ids", "bstar_members"
}
PRIMITIVE_KEYS = {
    "terminal", "terminal_taxon_id", "authority_edge_split_hex"
}
STATE_MAPPED = 0
STATE_NA_STRUCT = 1
STATE_NA_FUSE = 2
STATE_NA_TOPO = 3
VALID_STATES = {
    STATE_MAPPED, STATE_NA_STRUCT, STATE_NA_FUSE, STATE_NA_TOPO
}
COMPOSITE_ROW_INVARIANT = "CompositeRowConsistency-v1"


def u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("u16 overflow")
    return struct.pack("<H", value)


def u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("u32 overflow")
    return struct.pack("<I", value)


def u64(value: int) -> bytes:
    if not 0 <= value <= MASK64:
        raise ValueError("u64 overflow")
    return struct.pack("<Q", value)


def sized(value: bytes) -> bytes:
    return u64(len(value)) + value


def sha(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def ceil_div(value: int, divisor: int) -> int:
    quotient, remainder = divmod(value, divisor)
    return quotient + int(remainder != 0)


def exact_lower_hex(value, label: str, allow_empty: bool = False) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a lowercase hex string")
    if (not allow_empty and not value) or len(value) % 2:
        raise ValueError(f"{label} has empty/odd-length hex")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} is not canonical lowercase hex")
    return bytes.fromhex(value)


def validate_primitive_row_consistency_v1(
    registry: dict, state_row: list[int], validity_row: list[bool],
    row_label: str,
) -> None:
    """Validate one candidate row before any matrix payload is constructed."""
    def reject(code: str, detail: str) -> None:
        raise ValueError(f"{code}: {row_label}: {detail}")

    primitives = registry["primitive_entries"]
    numeric_count = len(primitives) + len(registry["bstar_members"])
    if len(state_row) != len(primitives):
        reject("E3_GEOMETRY", "primitive state width mismatch")
    if len(validity_row) != numeric_count:
        reject("E3_GEOMETRY", "numeric validity width mismatch")
    if any(not isinstance(value, bool) for value in validity_row):
        reject("E3_VALIDITY", "validity entries must be boolean")
    for primitive_id, state_value in enumerate(state_row):
        if (not isinstance(state_value, int) or isinstance(state_value, bool) or
                state_value not in VALID_STATES):
            reject("E3_STATE", f"primitive {primitive_id} has invalid state")
        if primitives[primitive_id]["terminal"] and state_value == STATE_NA_TOPO:
            reject(
                "E3_PRIMITIVE_ROW_CONSISTENCY",
                f"terminal primitive {primitive_id} is NA_topo",
            )
        if state_value != STATE_MAPPED and validity_row[primitive_id]:
            reject(
                "E3_PRIMITIVE_ROW_CONSISTENCY",
                f"non-Mapped primitive {primitive_id} is available",
            )


def validate_composite_row_consistency_v1(
    registry: dict, state_row: list[int], validity_row: list[bool],
    row_label: str,
) -> None:
    """Validate B* availability against the frozen primitive fusion fibers.

    This is intentionally one-way: validity=0 creates no state obligation and
    NA_fuse does not require a B* value.  Registry order is the authoritative
    order used for the within-row disjointness rule.
    """
    def reject(detail: str) -> None:
        raise ValueError(
            f"E3_COMPOSITE_ROW_CONSISTENCY: {row_label}: {detail}"
        )

    primitive_count = len(registry["primitive_entries"])
    if len(state_row) != primitive_count:
        raise ValueError(f"E3_GEOMETRY: {row_label}: primitive state width mismatch")
    if len(validity_row) != primitive_count + len(registry["bstar_members"]):
        raise ValueError(f"E3_GEOMETRY: {row_label}: numeric validity width mismatch")
    occupied: set[int] = set()
    for bstar_id, members in enumerate(registry["bstar_members"]):
        if not validity_row[primitive_count + bstar_id]:
            continue
        non_fused = [member for member in members
                     if state_row[member] != STATE_NA_FUSE]
        if non_fused:
            reject(
                f"valid B* {bstar_id} has non-NA_fuse member(s) "
                + ",".join(str(member) for member in non_fused)
            )
        overlap = occupied.intersection(members)
        if overlap:
            reject(
                f"valid B* {bstar_id} overlaps an earlier valid B* at member(s) "
                + ",".join(str(member) for member in sorted(overlap))
            )
        occupied.update(members)


def validate_fixture_rows_v1(
    registry: dict, state: list[list[int]], values: list[list[float]],
    valid: list[list[bool]],
) -> None:
    """Batch admission gate used by the non-production fixture encoders."""
    rows = len(registry["gene_ids"])
    numeric_count = (len(registry["primitive_entries"]) +
                     len(registry["bstar_members"]))
    if len(state) != rows or len(values) != rows or len(valid) != rows:
        raise ValueError("fixture row count differs from GeneRegistry")
    for row_index in range(rows):
        if len(values[row_index]) != numeric_count:
            raise ValueError(f"row {row_index}: numeric value width mismatch")
        validate_primitive_row_consistency_v1(
            registry, state[row_index], valid[row_index], f"row {row_index}"
        )
        validate_composite_row_consistency_v1(
            registry, state[row_index], valid[row_index], f"row {row_index}"
        )


def species_authority_digest(registry: dict) -> bytes:
    if set(registry) != DESCRIPTOR_KEYS or registry["descriptor_schema"] != DESCRIPTOR_SCHEMA:
        raise ValueError("external authority descriptor key/schema mismatch")
    taxa_input = registry["taxon_label_bytes_hex"]
    primitives = registry["primitive_entries"]
    if not isinstance(taxa_input, list) or not taxa_input:
        raise ValueError("taxon count must be nonzero")
    if len(taxa_input) > 0xFFFFFFFF or not isinstance(primitives, list) or len(primitives) > 0xFFFFFFFF:
        raise ValueError("taxon or primitive count does not fit u32")
    taxa = []
    seen = set()
    for taxon_id, label in enumerate(taxa_input):
        raw = exact_lower_hex(label, f"taxon_label_bytes_hex[{taxon_id}]")
        if not raw:
            raise ValueError("taxon labels must be nonempty")
        if raw in seen:
            raise ValueError("duplicate taxon label")
        seen.add(raw)
        taxa.append(raw)
    stream = bytearray(b"SplitAlignerR/SpeciesAuthority/v1\0")
    stream += u32(len(taxa)) + u32(len(primitives))
    for taxon_id, label in enumerate(taxa):
        stream += u32(taxon_id) + sized(label)
    width = ceil_div(len(taxa), 8)
    all_mask = (1 << len(taxa)) - 1
    for primitive_id, item in enumerate(primitives):
        if not isinstance(item, dict) or set(item) != PRIMITIVE_KEYS:
            raise ValueError(f"primitive {primitive_id} key set mismatch")
        if not isinstance(item.get("terminal"), bool):
            raise ValueError("primitive terminal flag must be boolean")
        split = exact_lower_hex(
            item["authority_edge_split_hex"],
            f"primitive_entries[{primitive_id}].authority_edge_split_hex",
            allow_empty=(width == 0)
        )
        if len(split) != width:
            raise ValueError("authority split width mismatch")
        used_bits = len(taxa) % 8 or 8
        if split[-1] & ~((1 << used_bits) - 1):
            raise ValueError("nonzero authority split padding")
        terminal = item["terminal"]
        terminal_taxon = item.get("terminal_taxon_id")
        if not isinstance(terminal_taxon, int) or isinstance(terminal_taxon, bool):
            raise ValueError("terminal taxon ID must be an integer")
        u32(terminal_taxon)
        selected = int.from_bytes(split, "little")
        if terminal:
            if not 0 <= terminal_taxon < len(taxa):
                raise ValueError("terminal taxon out of range")
            if selected != (1 << terminal_taxon):
                raise ValueError("terminal split is not its exact singleton")
        else:
            if terminal_taxon != 0xFFFFFFFF:
                raise ValueError("internal terminal taxon ID must be sentinel")
            complement = all_mask ^ selected
            if selected == 0 or complement == 0:
                raise ValueError("internal split side is empty")
            selected_count = bin(selected).count("1")
            complement_count = bin(complement).count("1")
            if selected_count > complement_count:
                raise ValueError("internal split uses larger side")
            if selected_count == complement_count and split > complement.to_bytes(width, "little"):
                raise ValueError("internal split violates unsigned-byte lex tie rule")
        stream += u32(primitive_id)
        stream += bytes([1 if terminal else 0]) + bytes(3)
        stream += u32(terminal_taxon) + sized(split)
    return sha(bytes(stream))


def gene_registry_digest(gene_ids: list[str]) -> bytes:
    if not isinstance(gene_ids, list):
        raise ValueError("gene IDs must be a list")
    stream = bytearray(b"SplitAlignerR/GeneRegistry/v1\0") + u64(len(gene_ids))
    seen = set()
    for index, gene_id in enumerate(gene_ids):
        if not isinstance(gene_id, str):
            raise ValueError("gene ID must be a string")
        raw = gene_id.encode("utf-8")
        if not raw or b"\0" in raw:
            raise ValueError("gene IDs must be nonempty and NUL-free")
        if raw in seen:
            raise ValueError("duplicate gene ID")
        seen.add(raw)
        stream += u64(index) + sized(raw)
    return sha(bytes(stream))


def canonical_bstar_members(members: list[list[int]], primitive_count: int) -> list[bytes]:
    encoded = []
    for item in members:
        if len(item) < 2 or item != sorted(set(item)):
            raise ValueError("noncanonical B* members")
        if item[0] < 0 or item[-1] >= primitive_count:
            raise ValueError("B* member out of range")
        encoded.append(b"".join(u32(member) for member in item))
    if encoded != sorted(encoded) or len(set(encoded)) != len(encoded):
        raise ValueError("B* registry order/duplicate failure")
    return encoded


def bstar_registry_digest(primitive_digest: bytes, encoded: list[bytes]) -> bytes:
    stream = bytearray(b"SplitAlignerR/BStarRegistry/v1\0")
    stream += primitive_digest + u64(len(encoded))
    for index, member_bytes in enumerate(encoded):
        stream += u64(index) + sized(member_bytes)
    return sha(bytes(stream))


def numeric_registry_digest(
    primitive_digest: bytes, primitive_count: int, bstar_digest: bytes,
    encoded: list[bytes]
) -> bytes:
    stream = bytearray(b"SplitAlignerR/NumericCoordinateRegistry/v1\0")
    stream += primitive_digest + u64(primitive_count)
    stream += bstar_digest + u64(len(encoded))
    for index, member_bytes in enumerate(encoded):
        stream += u64(index) + sized(member_bytes)
    return sha(bytes(stream))


def data_header(
    magic: bytes, component_type: int, scalar_encoding: int, rows: int,
    columns: int, tile_payload_bytes: int, species_digest: bytes,
    gene_digest: bytes, coordinate_digest: bytes
) -> bytes:
    tile_row_count = ceil_div(rows, TILE_ROWS) if rows else 0
    tile_col_count = ceil_div(columns, TILE_COLS) if columns else 0
    tile_count = tile_row_count * tile_col_count
    payload_bytes = tile_count * tile_payload_bytes
    header = bytearray(HEADER_BYTES)
    header[0:8] = magic
    header[8:10] = u16(1)
    header[10:12] = u16(0)
    header[12:14] = u16(HEADER_BYTES)
    header[14:16] = u16(component_type)
    header[16] = 1
    header[17] = 1
    header[18] = scalar_encoding
    header[19] = 0
    header[20:24] = u32(TILE_ROWS)
    header[24:28] = u32(TILE_COLS)
    header[32:40] = u64(rows)
    header[40:48] = u64(columns)
    header[48:56] = u64(tile_row_count)
    header[56:64] = u64(tile_col_count)
    header[64:72] = u64(tile_count)
    header[72:80] = u64(tile_payload_bytes)
    header[80:88] = u64(HEADER_BYTES)
    header[88:96] = u64(payload_bytes)
    header[96:104] = u64(HEADER_BYTES + payload_bytes)
    header[128:160] = species_digest
    header[160:192] = gene_digest
    header[192:224] = coordinate_digest
    return bytes(header)


def make_state_payload(logical: list[list[int]]) -> bytes:
    if not logical or not logical[0]:
        return b""
    payload = bytearray(TILE_ROWS * TILE_COLS)
    for row, values in enumerate(logical):
        for column, value in enumerate(values):
            if not 0 <= value <= 3:
                raise ValueError("invalid fixture state")
            payload[row * TILE_COLS + column] = value
    return bytes(payload)


def make_numeric_payload(values: list[list[float]], valid: list[list[bool]]) -> bytes:
    if not values or not values[0]:
        return b""
    payload = bytearray(TILE_ROWS * TILE_COLS * 8)
    for row, row_values in enumerate(values):
        for column, value in enumerate(row_values):
            actual = value if valid[row][column] else 0.0
            if valid[row][column] and not math.isfinite(actual):
                raise ValueError("nonfinite valid fixture numeric")
            offset = (row * TILE_COLS + column) * 8
            payload[offset:offset + 8] = struct.pack("<d", actual)
    return bytes(payload)


def make_validity_payload(valid: list[list[bool]]) -> bytes:
    if not valid or not valid[0]:
        return b""
    payload = bytearray((TILE_ROWS * TILE_COLS) // 8)
    for row, row_values in enumerate(valid):
        for column, value in enumerate(row_values):
            if value:
                bit_index = row * TILE_COLS + column
                payload[bit_index // 8] |= 1 << (bit_index % 8)
    return bytes(payload)


def make_data_component(
    magic: bytes, component_type: int, encoding: int, rows: int, columns: int,
    payload: bytes, tile_payload_bytes: int, species_digest: bytes, gene_digest: bytes,
    coordinate_digest: bytes
) -> bytes:
    expected_tiles = (ceil_div(rows, TILE_ROWS) if rows else 0) * (
        ceil_div(columns, TILE_COLS) if columns else 0
    )
    if len(payload) != expected_tiles * tile_payload_bytes:
        raise ValueError("fixture payload length differs from declared full tiles")
    header = data_header(
        magic, component_type, encoding, rows, columns, tile_payload_bytes,
        species_digest, gene_digest, coordinate_digest
    )
    return header + payload


def index_header(
    entry_count: int, rows: int, primitive_count: int, bstar_count: int,
    species_digest: bytes, gene_digest: bytes, primitive_digest: bytes,
    bstar_digest: bytes, numeric_digest: bytes
) -> bytes:
    header = bytearray(HEADER_BYTES)
    header[0:8] = b"SARIX001"
    header[8:10] = u16(1)
    header[10:12] = u16(0)
    header[12:14] = u16(HEADER_BYTES)
    header[14:16] = u16(4)
    header[16] = 1
    header[17] = 1
    header[20:24] = u32(INDEX_ENTRY_BYTES)
    header[24:32] = u64(entry_count)
    header[32:40] = u64(HEADER_BYTES + entry_count * INDEX_ENTRY_BYTES)
    header[40:48] = u64(rows)
    header[48:56] = u64(primitive_count)
    header[56:64] = u64(bstar_count)
    header[64:72] = u64(primitive_count + bstar_count)
    header[72:76] = u32(TILE_ROWS)
    header[76:80] = u32(TILE_COLS)
    header[80:112] = species_digest
    header[112:144] = gene_digest
    header[144:176] = primitive_digest
    header[176:208] = bstar_digest
    header[208:240] = numeric_digest
    return bytes(header)


def index_entry(
    component_type: int, scalar_encoding: int, row_extent: int,
    column_extent: int, stored_length: int, tile_digest: bytes
) -> bytes:
    entry = bytearray(INDEX_ENTRY_BYTES)
    entry[0:2] = u16(component_type)
    entry[2:4] = u16(1)
    entry[8:16] = u64(0)
    entry[16:24] = u64(0)
    entry[24:32] = u64(0)
    entry[32:40] = u64(0)
    entry[40:44] = u32(row_extent)
    entry[44:48] = u32(column_extent)
    entry[48:56] = u64(HEADER_BYTES)
    entry[56:64] = u64(stored_length)
    entry[64:68] = u32(TILE_ROWS)
    entry[68:72] = u32(TILE_COLS)
    entry[72:74] = u16(scalar_encoding)
    entry[80:112] = tile_digest
    return bytes(entry)


def pack_logical_validity(valid: list[list[bool]]) -> bytes:
    count = sum(len(row) for row in valid)
    output = bytearray(ceil_div(count, 8))
    logical_index = 0
    for row in valid:
        for value in row:
            if value:
                output[logical_index // 8] |= 1 << (logical_index % 8)
            logical_index += 1
    return bytes(output)


def logical_hash(
    rows: int, primitive_count: int, bstar_count: int,
    species_digest: bytes, gene_digest: bytes, primitive_digest: bytes,
    bstar_digest: bytes, numeric_digest: bytes, state: list[list[int]],
    values: list[list[float]], valid: list[list[bool]]
) -> bytes:
    state_stream = bytes(value for row in state for value in row)
    numeric_stream = bytearray()
    for row_index, row in enumerate(values):
        for column, value in enumerate(row):
            numeric_stream += struct.pack("<d", value if valid[row_index][column] else 0.0)
    validity_stream = pack_logical_validity(valid)
    stream = bytearray(b"SplitAlignerR/MatrixLogicalContent/v1\0")
    stream += u16(1) + u16(0)
    stream += u64(rows) + u64(primitive_count) + u64(bstar_count)
    stream += u64(primitive_count + bstar_count)
    stream += species_digest + gene_digest + primitive_digest
    stream += bstar_digest + numeric_digest
    stream += sized(state_stream) + sized(bytes(numeric_stream)) + sized(validity_stream)
    return sha(bytes(stream))


def completion_footer(
    components: dict[str, bytes], logical_digest: bytes, species_digest: bytes,
    gene_digest: bytes, primitive_digest: bytes, bstar_digest: bytes,
    numeric_digest: bytes, rows: int, primitive_count: int, bstar_count: int
) -> bytes:
    footer = bytearray(FOOTER_BYTES)
    footer[0:8] = b"SARFT001"
    footer[8:10] = u16(1)
    footer[10:12] = u16(0)
    footer[12:14] = u16(FOOTER_BYTES)
    footer[14:16] = u16(0)
    footer[16:20] = u32(4)
    names = ["STATE.bin", "NUMERIC.bin", "VALIDITY.bin", "TILE_INDEX.bin"]
    for index, name in enumerate(names):
        footer[32 + 8 * index:40 + 8 * index] = u64(len(components[name]))
        footer[64 + 32 * index:96 + 32 * index] = sha(components[name])
    footer[192:224] = logical_digest
    footer[224:256] = species_digest
    footer[256:288] = gene_digest
    footer[288:320] = primitive_digest
    footer[320:352] = bstar_digest
    footer[352:384] = numeric_digest
    footer[384:392] = u64(rows)
    footer[392:400] = u64(primitive_count)
    footer[400:408] = u64(bstar_count)
    footer[408:416] = u64(primitive_count + bstar_count)
    footer[416:420] = u32(TILE_ROWS)
    footer[420:424] = u32(TILE_COLS)
    footer[424:426] = u16(1)
    return bytes(footer)


def manifest_text(
    components: dict[str, bytes], logical_digest: bytes, species_digest: bytes,
    gene_digest: bytes, primitive_digest: bytes, bstar_digest: bytes,
    numeric_digest: bytes, rows: int, primitive_count: int, bstar_count: int
) -> bytes:
    values = [
        ("magic", "SplitAlignerR-MatrixStore-VALIDATED"),
        ("manifest_schema_major", "1"),
        ("manifest_schema_minor", "0"),
        ("completion_state", "VALIDATED"),
        ("store_schema", "1.0-candidate"),
        ("layout", "tiled_row_major_provisional"),
        ("tile_rows", str(TILE_ROWS)),
        ("tile_columns", str(TILE_COLS)),
        ("row_count", str(rows)),
        ("primitive_count", str(primitive_count)),
        ("bstar_count", str(bstar_count)),
        ("numeric_coordinate_count", str(primitive_count + bstar_count)),
        ("species_authority_sha256", species_digest.hex()),
        ("gene_registry_sha256", gene_digest.hex()),
        ("primitive_registry_sha256", primitive_digest.hex()),
        ("bstar_registry_sha256", bstar_digest.hex()),
        ("numeric_coordinate_registry_sha256", numeric_digest.hex()),
        ("logical_content_sha256", logical_digest.hex()),
        ("state_component", "STATE.bin"),
        ("state_bytes", str(len(components["STATE.bin"]))),
        ("state_sha256", sha(components["STATE.bin"]).hex()),
        ("numeric_component", "NUMERIC.bin"),
        ("numeric_bytes", str(len(components["NUMERIC.bin"]))),
        ("numeric_sha256", sha(components["NUMERIC.bin"]).hex()),
        ("validity_component", "VALIDITY.bin"),
        ("validity_bytes", str(len(components["VALIDITY.bin"]))),
        ("validity_sha256", sha(components["VALIDITY.bin"]).hex()),
        ("index_component", "TILE_INDEX.bin"),
        ("index_bytes", str(len(components["TILE_INDEX.bin"]))),
        ("index_sha256", sha(components["TILE_INDEX.bin"]).hex()),
        ("footer_component", "COMPLETION.bin"),
        ("footer_bytes", str(len(components["COMPLETION.bin"]))),
        ("footer_sha256", sha(components["COMPLETION.bin"]).hex()),
        ("publication_timestamp_policy", "OMITTED_V1"),
    ]
    return ("".join(f"{key}={value}\n" for key, value in values)).encode("ascii")


def validity_vectors() -> str:
    rows = ["logical_cells\tset_bits_zero_based\texpected_lsb_first_hex"]
    for count in (1, 7, 8, 9, 63, 64, 65):
        bits = {0, count - 1}
        output = bytearray(ceil_div(count, 8))
        for bit in bits:
            output[bit // 8] |= 1 << (bit % 8)
        rows.append(f"{count}\t{','.join(str(bit) for bit in sorted(bits))}\t{output.hex()}")
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--validity-vectors", type=Path)
    parser.add_argument(
        "--profile",
        choices=("tiny", "zero_rows", "zero_columns", "raw_ff"),
                        default="tiny")
    args = parser.parse_args()
    if args.store.exists() or args.registry.exists() or (
        args.validity_vectors is not None and args.validity_vectors.exists()
    ):
        raise SystemExit("refusing to overwrite an existing fixture path")

    if args.profile in ("tiny", "zero_rows"):
        registry = {
            "descriptor_schema": DESCRIPTOR_SCHEMA,
            "taxon_label_bytes_hex": ["41", "42", "43", "44"],
            "primitive_entries": [
                {"terminal": True, "terminal_taxon_id": 0, "authority_edge_split_hex": "01"},
                {"terminal": True, "terminal_taxon_id": 1, "authority_edge_split_hex": "02"},
                {"terminal": True, "terminal_taxon_id": 2, "authority_edge_split_hex": "04"},
                {"terminal": True, "terminal_taxon_id": 3, "authority_edge_split_hex": "08"},
                {"terminal": False, "terminal_taxon_id": 0xFFFFFFFF,
                 "authority_edge_split_hex": "03"},
            ],
            "gene_ids": ["g0", "g1", "g2"] if args.profile == "tiny" else [],
            "bstar_members": [[0, 2], [1, 4]],
        }
    elif args.profile == "zero_columns":
        registry = {
            "descriptor_schema": DESCRIPTOR_SCHEMA,
            "taxon_label_bytes_hex": ["41", "42"],
            "primitive_entries": [],
            "gene_ids": ["g0", "g1", "g2"],
            "bstar_members": [],
        }
    else:
        registry = {
            "descriptor_schema": DESCRIPTOR_SCHEMA,
            "taxon_label_bytes_hex": ["ff", "42"],
            "primitive_entries": [
                {"terminal": True, "terminal_taxon_id": 0,
                 "authority_edge_split_hex": "01"},
                {"terminal": True, "terminal_taxon_id": 1,
                 "authority_edge_split_hex": "02"},
            ],
            "gene_ids": ["g0"],
            "bstar_members": [],
        }
    primitive_count = len(registry["primitive_entries"])
    rows = len(registry["gene_ids"])
    bstar_count = len(registry["bstar_members"])

    if args.profile == "tiny":
        state = [
            [STATE_NA_FUSE, STATE_MAPPED, STATE_NA_FUSE,
             STATE_NA_STRUCT, STATE_NA_TOPO],
            [STATE_NA_FUSE, STATE_NA_FUSE, STATE_NA_FUSE,
             STATE_MAPPED, STATE_NA_FUSE],
            [STATE_MAPPED, STATE_NA_FUSE, STATE_MAPPED,
             STATE_MAPPED, STATE_NA_FUSE],
        ]
        values = [
            [999.0, -0.0, 999.0, 999.0, 999.0, 2.25, 999.0],
            [999.0, 999.0, 999.0, 3.5, 999.0, 1.25, 4.5],
            [0.0, 999.0, float.fromhex("0x0.0000000000001p-1022"),
             999.0, 999.0, 999.0, 999.0],
        ]
        valid = [
            [False, True, False, False, False, True, False],
            [False, False, False, True, False, True, True],
            [True, False, True, False, False, False, False],
        ]
    elif args.profile == "zero_rows":
        state, values, valid = [], [], []
    elif args.profile == "zero_columns":
        state = [[], [], []]
        values = [[], [], []]
        valid = [[], [], []]
    else:
        state = [[0, 1]]
        values = [[1.0, 999.0]]
        valid = [[True, False]]

    # PrimitiveRowConsistency-v1 is a candidate write_row precondition.  It
    # must run before any state/numeric/validity payload bytes are built.
    validate_fixture_rows_v1(registry, state, values, valid)

    species_digest = species_authority_digest(registry)
    primitive_digest = species_digest
    gene_digest = gene_registry_digest(registry["gene_ids"])
    encoded_members = canonical_bstar_members(registry["bstar_members"], primitive_count)
    bstar_digest = bstar_registry_digest(primitive_digest, encoded_members)
    numeric_digest = numeric_registry_digest(
        primitive_digest, primitive_count, bstar_digest, encoded_members
    )

    state_payload = make_state_payload(state)
    numeric_payload = make_numeric_payload(values, valid)
    validity_payload = make_validity_payload(valid)
    components = {
        "STATE.bin": make_data_component(
            b"SARST001", 1, 1, rows, primitive_count, state_payload,
            TILE_ROWS * TILE_COLS, species_digest, gene_digest, primitive_digest
        ),
        "NUMERIC.bin": make_data_component(
            b"SARNM001", 2, 2, rows, primitive_count + bstar_count,
            numeric_payload, TILE_ROWS * TILE_COLS * 8, species_digest,
            gene_digest, numeric_digest
        ),
        "VALIDITY.bin": make_data_component(
            b"SARVL001", 3, 3, rows, primitive_count + bstar_count,
            validity_payload, TILE_ROWS * TILE_COLS // 8, species_digest,
            gene_digest, numeric_digest
        ),
    }
    entries = []
    for component_type, encoding, name, column_count in (
        (1, 1, "STATE.bin", primitive_count),
        (2, 2, "NUMERIC.bin", primitive_count + bstar_count),
        (3, 3, "VALIDITY.bin", primitive_count + bstar_count),
    ):
        payload = components[name][HEADER_BYTES:]
        if rows and column_count:
            entries.append(index_entry(
                component_type, encoding, rows, column_count, len(payload), sha(payload)
            ))
    components["TILE_INDEX.bin"] = index_header(
        len(entries), rows, primitive_count, bstar_count, species_digest,
        gene_digest, primitive_digest, bstar_digest, numeric_digest
    ) + b"".join(entries)
    logical_digest = logical_hash(
        rows, primitive_count, bstar_count, species_digest, gene_digest,
        primitive_digest, bstar_digest, numeric_digest, state, values, valid
    )
    components["COMPLETION.bin"] = completion_footer(
        components, logical_digest, species_digest, gene_digest,
        primitive_digest, bstar_digest, numeric_digest, rows, primitive_count,
        bstar_count
    )
    components["VALIDATED"] = manifest_text(
        components, logical_digest, species_digest, gene_digest,
        primitive_digest, bstar_digest, numeric_digest, rows, primitive_count,
        bstar_count
    )

    args.store.mkdir(parents=True)
    for name in ("STATE.bin", "NUMERIC.bin", "VALIDITY.bin", "TILE_INDEX.bin",
                 "COMPLETION.bin", "VALIDATED"):
        (args.store / name).write_bytes(components[name])
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    write_canonical_json(args.registry, registry)
    if args.validity_vectors is not None:
        args.validity_vectors.write_bytes(validity_vectors().encode("ascii"))

    result = {
        "status": "REFERENCE_FIXTURE_WRITTEN_NON_PRODUCTION",
        "profile": args.profile,
        "logical_content_sha256": logical_digest.hex(),
        "components": {name: {"bytes": len(value), "sha256": sha(value).hex()}
                       for name, value in components.items()},
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
