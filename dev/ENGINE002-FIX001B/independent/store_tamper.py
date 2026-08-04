#!/usr/bin/env python3
"""Build targeted self-consistent negative TruthPlanStore-v1 fixtures."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct
from typing import Tuple

from payload_aggregate_check import check_store, xxh64


def u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def put_u64(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<Q", data, offset, value)


def finalize_enclosing_hashes(data: bytearray, footer_offset: int) -> None:
    data[footer_offset + 80:footer_offset + 112] = bytes(32)
    data[footer_offset + 112:footer_offset + 120] = bytes(8)
    put_u64(
        data,
        footer_offset + 112,
        xxh64(bytes(data[footer_offset:footer_offset + 128])),
    )
    normalized = bytearray(data)
    normalized[footer_offset + 80:footer_offset + 112] = bytes(32)
    data[footer_offset + 80:footer_offset + 112] = hashlib.sha256(
        normalized
    ).digest()


def replace_manifest_hash(manifest: bytes, component: bytes) -> bytes:
    text = manifest.decode("ascii")
    lines = text.splitlines()
    replacement = "store_sha256=" + hashlib.sha256(component).hexdigest()
    found = False
    for index, line in enumerate(lines):
        if line.startswith("store_sha256="):
            lines[index] = replacement
            found = True
    if not found:
        raise ValueError("manifest has no store_sha256 field")
    return ("\n".join(lines) + "\n").encode("ascii")


def aggregate_only(original: bytes) -> Tuple[bytes, str]:
    data = bytearray(original)
    footer_offset = u64(data, 64)
    data[footer_offset + 48] ^= 1
    finalize_enclosing_hashes(data, footer_offset)
    return bytes(data), "aggregate byte 0 bit 0 flipped; enclosing hashes rebuilt"


def payload_mutation(original: bytes) -> Tuple[bytes, str]:
    data = bytearray(original)
    index_offset = u64(data, 56)
    footer_offset = u64(data, 64)
    record_offset = u64(data, index_offset + 64 + 8)
    record_bytes = u64(data, index_offset + 64 + 16)
    if record_bytes < 144:
        raise ValueError("second record is too short")
    retained_bytes = struct.unpack_from("<I", data, record_offset + 28)[0]
    state_bytes = struct.unpack_from("<I", data, record_offset + 32)[0]
    references = record_offset + 144 + retained_bytes + state_bytes
    first = bytes(data[references:references + 4])
    second = bytes(data[references + 4:references + 8])
    if first == second:
        raise ValueError("selected record references do not differ")
    data[references:references + 4] = second
    data[references + 4:references + 8] = first

    payload = bytes(data[record_offset + 144:record_offset + record_bytes])
    put_u64(data, record_offset + 120, xxh64(payload))
    put_u64(
        data,
        record_offset + 128,
        xxh64(bytes(data[record_offset:record_offset + 128])),
    )
    record = bytes(data[record_offset:record_offset + record_bytes])
    put_u64(data, index_offset + 64 + 56, xxh64(record))
    records_start = u64(data, 48)
    put_u64(
        data,
        footer_offset + 32,
        xxh64(bytes(data[records_start:index_offset])),
    )
    put_u64(
        data,
        footer_offset + 40,
        xxh64(bytes(data[index_offset:footer_offset])),
    )
    finalize_enclosing_hashes(data, footer_offset)
    return bytes(data), "second-record primitive query references 0 and 1 swapped"


def write_fixture(
    output_dir: pathlib.Path,
    stem: str,
    component: bytes,
    manifest: bytes,
) -> pathlib.Path:
    component_path = output_dir / (stem + ".truthstore.bin")
    manifest_path = output_dir / (stem + ".truthstore.manifest")
    component_path.write_bytes(component)
    manifest_path.write_bytes(replace_manifest_hash(manifest, component))
    return component_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    original = args.component.read_bytes()
    manifest = args.manifest.read_bytes()
    base = check_store(args.component)
    if not base.match:
        raise ValueError("source store does not have a standard aggregate")

    cases = []
    for stem, builder in (
        ("aggregate_only_mismatch", aggregate_only),
        ("payload_mutation_aggregate_mismatch", payload_mutation),
    ):
        component, mutation = builder(original)
        path = write_fixture(args.output_dir, stem, component, manifest)
        result = check_store(path)
        if result.match:
            raise ValueError(stem + " unexpectedly retained a valid aggregate")
        cases.append((stem, mutation, result))

    lines = [
        "source_store_sha256=" + hashlib.sha256(original).hexdigest(),
        "source_standard_aggregate=" + base.expected,
    ]
    for stem, mutation, result in cases:
        lines.extend((
            "case=" + stem,
            "mutation=" + mutation,
            "geometry_and_enclosing_hashes=PASS",
            "independent_recomputed_aggregate=" + result.expected,
            "stored_aggregate=" + result.stored,
            "aggregate_match=FALSE",
        ))
    output = "\n".join(lines) + "\n"
    if args.report:
        with args.report.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
