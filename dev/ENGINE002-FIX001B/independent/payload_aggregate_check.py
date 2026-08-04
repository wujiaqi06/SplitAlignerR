#!/usr/bin/env python3
"""Independent TruthPlanStore-v1 aggregate and geometry validator."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct
from dataclasses import dataclass
from typing import List


MASK64 = (1 << 64) - 1
PRIME1 = 11400714785074694791
PRIME2 = 14029467366897019727
PRIME3 = 1609587929392839161
PRIME4 = 9650029242287828579
PRIME5 = 2870177450012600261


def rotl64(value: int, bits: int) -> int:
    return ((value << bits) | (value >> (64 - bits))) & MASK64


def xxh_round(accumulator: int, value: int) -> int:
    accumulator = (accumulator + value * PRIME2) & MASK64
    accumulator = rotl64(accumulator, 31)
    return (accumulator * PRIME1) & MASK64


def xxh_merge(accumulator: int, value: int) -> int:
    accumulator ^= xxh_round(0, value)
    return (accumulator * PRIME1 + PRIME4) & MASK64


def xxh64(data: bytes, seed: int = 0) -> int:
    size = len(data)
    offset = 0
    if size >= 32:
        v1 = (seed + PRIME1 + PRIME2) & MASK64
        v2 = (seed + PRIME2) & MASK64
        v3 = seed & MASK64
        v4 = (seed - PRIME1) & MASK64
        limit = size - 32
        while offset <= limit:
            v1 = xxh_round(v1, struct.unpack_from("<Q", data, offset)[0])
            v2 = xxh_round(v2, struct.unpack_from("<Q", data, offset + 8)[0])
            v3 = xxh_round(v3, struct.unpack_from("<Q", data, offset + 16)[0])
            v4 = xxh_round(v4, struct.unpack_from("<Q", data, offset + 24)[0])
            offset += 32
        result = (
            rotl64(v1, 1) + rotl64(v2, 7) +
            rotl64(v3, 12) + rotl64(v4, 18)
        ) & MASK64
        for value in (v1, v2, v3, v4):
            result = xxh_merge(result, value)
    else:
        result = (seed + PRIME5) & MASK64
    result = (result + size) & MASK64
    while offset + 8 <= size:
        lane = xxh_round(0, struct.unpack_from("<Q", data, offset)[0])
        result ^= lane
        result = (rotl64(result, 27) * PRIME1 + PRIME4) & MASK64
        offset += 8
    if offset + 4 <= size:
        result ^= struct.unpack_from("<I", data, offset)[0] * PRIME1
        result &= MASK64
        result = (rotl64(result, 23) * PRIME2 + PRIME3) & MASK64
        offset += 4
    while offset < size:
        result ^= data[offset] * PRIME5
        result &= MASK64
        result = (rotl64(result, 11) * PRIME1) & MASK64
        offset += 1
    result ^= result >> 33
    result = (result * PRIME2) & MASK64
    result ^= result >> 29
    result = (result * PRIME3) & MASK64
    result ^= result >> 32
    return result & MASK64


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass
class Result:
    path: pathlib.Path
    file_bytes: int
    record_count: int
    canonical_bytes: int
    expected: str
    stored: str

    @property
    def match(self) -> bool:
        return self.expected == self.stored


def check_record_geometry(record: bytes, expected_id: int,
                          global_taxa: int, primitives: int) -> bytes:
    u16 = lambda offset: struct.unpack_from("<H", record, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", record, offset)[0]
    u64 = lambda offset: struct.unpack_from("<Q", record, offset)[0]
    require(len(record) >= 144, "record is shorter than its v1 header")
    require(record[:4] == b"TPLN", "record magic mismatch")
    require((u16(4), u16(6), u16(8), u16(10)) == (1, 0, 144, 0),
            "record schema/header mismatch")
    require(u64(12) == expected_id, "record pattern ID mismatch")
    require((u32(20), u32(24)) == (global_taxa, primitives),
            "record authority dimensions mismatch")
    retained_bytes = u32(28)
    state_bytes = u32(32)
    active_count = u32(36)
    query_count = u32(40)
    require(retained_bytes == (global_taxa + 7) // 8,
            "record retained width mismatch")
    require(state_bytes == (primitives + 3) // 4,
            "record state width mismatch")
    require(record[44:48] == bytes((1, 4, 1, 0)),
            "record encoding marker mismatch")
    payload_bytes = u64(48)
    require(payload_bytes < (1 << 32) and len(record) == 144 + payload_bytes,
            "record payload geometry mismatch")
    require(record[136:144] == bytes(8), "record reserved bytes nonzero")
    payload = record[144:]
    require(xxh64(payload) == u64(120), "record payload XXH64 mismatch")
    require(xxh64(record[:128]) == u64(128), "record header XXH64 mismatch")

    references_begin = retained_bytes + state_bytes
    offsets_begin = references_begin + 4 * active_count
    pool_begin = offsets_begin + 4 * (query_count + 1)
    require(pool_begin <= len(payload), "record section geometry overflow")
    references = [
        struct.unpack_from("<I", payload, references_begin + 4 * index)[0]
        for index in range(active_count)
    ]
    require(all(reference < query_count for reference in references),
            "record query reference out of range")
    offsets = [
        struct.unpack_from("<I", payload, offsets_begin + 4 * index)[0]
        for index in range(query_count + 1)
    ]
    require(offsets[0] == 0 and offsets == sorted(offsets),
            "record query offsets are not canonical")
    require(offsets[-1] == len(payload) - pool_begin,
            "record query pool does not end at payload boundary")
    for index in range(query_count):
        entry = payload[pool_begin + offsets[index]:pool_begin + offsets[index + 1]]
        require(len(entry) >= 12, "query-pool entry is truncated")
        require(entry[0] in (1, 2) and entry[1:4] == bytes(3),
                "query-pool encoding/reserved bytes fail")
        selected = struct.unpack_from("<I", entry, 4)[0]
        encoded_bytes = struct.unpack_from("<I", entry, 8)[0]
        require(len(entry) == 12 + encoded_bytes,
                "query-pool payload length mismatch")
        if entry[0] == 1:
            require(encoded_bytes == retained_bytes,
                    "dense query width mismatch")
        else:
            require(encoded_bytes == 4 * selected,
                    "sparse query width mismatch")
    return payload[:retained_bytes]


def check_store(path: pathlib.Path) -> Result:
    data = path.read_bytes()
    require(len(data) >= 384, "store is shorter than v1 minimum")
    u16 = lambda offset: struct.unpack_from("<H", data, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", data, offset)[0]
    u64 = lambda offset: struct.unpack_from("<Q", data, offset)[0]
    require(data[:8] == b"SATRST01", "store magic mismatch")
    require((u16(8), u16(10), u16(12), u16(14)) == (1, 0, 256, 0),
            "store schema/header mismatch")
    require(data[16:18] == bytes((1, 1)), "store byte-order/state mismatch")
    require((u16(18), u16(20), u16(22), u16(24), u16(26)) ==
            (1, 0, 144, 64, 128), "store member widths mismatch")
    require(data[28:32] == bytes(4) and data[232:256] == bytes(24),
            "store header reserved bytes nonzero")
    require(xxh64(data[:224]) == u64(224), "store header XXH64 mismatch")

    global_taxa = u32(32)
    primitives = u32(36)
    record_count = u64(40)
    records_start = u64(48)
    index_offset = u64(56)
    footer_offset = u64(64)
    file_bytes = u64(72)
    records_bytes = u64(80)
    index_bytes = u64(88)
    require(records_start == 256 and index_offset == 256 + records_bytes,
            "store records geometry mismatch")
    require(index_bytes == 64 * record_count,
            "store index length mismatch")
    require(footer_offset == index_offset + index_bytes,
            "store index/footer geometry mismatch")
    require(file_bytes == footer_offset + 128 == len(data),
            "store exact file length mismatch")

    footer = data[footer_offset:]
    fu16 = lambda offset: struct.unpack_from("<H", footer, offset)[0]
    fu64 = lambda offset: struct.unpack_from("<Q", footer, offset)[0]
    require(footer[:8] == b"SATDONE1", "footer magic mismatch")
    require((fu16(8), fu16(10), fu16(12), fu16(14)) == (1, 0, 128, 0),
            "footer schema mismatch")
    require(fu64(16) == record_count and fu64(24) == file_bytes,
            "footer count/size mismatch")
    require(footer[120:128] == bytes(8), "footer reserved bytes nonzero")
    footer_normalized = bytearray(footer)
    footer_normalized[80:120] = bytes(40)
    require(xxh64(bytes(footer_normalized)) == fu64(112),
            "footer XXH64 mismatch")
    require(xxh64(data[records_start:index_offset]) == fu64(32),
            "ordered-records XXH64 mismatch")
    require(xxh64(data[index_offset:footer_offset]) == fu64(40),
            "index XXH64 mismatch")
    file_normalized = bytearray(data)
    file_normalized[footer_offset + 80:footer_offset + 112] = bytes(32)
    require(hashlib.sha256(file_normalized).digest() == footer[80:112],
            "normalized complete-file SHA-256 mismatch")

    canonical = bytearray(b"SplitAlignerR/TruthPlanPayloadAggregate/v1\0")
    canonical.extend(struct.pack("<Q", record_count))
    expected_offset = records_start
    prior_retained = None
    for pattern_id in range(record_count):
        entry = index_offset + 64 * pattern_id
        indexed_id, record_offset, record_bytes = struct.unpack_from(
            "<QQQ", data, entry
        )
        require(indexed_id == pattern_id, "index pattern ID mismatch")
        require(record_offset == expected_offset and record_bytes >= 144,
                "index record boundary mismatch")
        require(record_offset + record_bytes <= index_offset,
                "index record extends beyond records region")
        record = data[record_offset:record_offset + record_bytes]
        retained = check_record_geometry(
            record, pattern_id, global_taxa, primitives
        )
        require(data[entry + 24:entry + 56] == record[56:88],
                "index retained identity mismatch")
        require(struct.unpack_from("<Q", data, entry + 56)[0] == xxh64(record),
                "index record XXH64 mismatch")
        if prior_retained is not None:
            require(prior_retained < retained,
                    "retained patterns are not canonical and unique")
        prior_retained = retained
        payload = record[144:]
        canonical.extend(struct.pack("<Q", pattern_id))
        canonical.extend(struct.pack("<Q", len(payload)))
        canonical.extend(payload)
        expected_offset += record_bytes
    require(expected_offset == index_offset, "record region has a gap")
    expected = hashlib.sha256(canonical).hexdigest()
    stored = footer[48:80].hex()
    return Result(path, file_bytes, record_count, len(canonical), expected, stored)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stores", nargs="+", type=pathlib.Path)
    parser.add_argument("--allow-mismatch", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    lines: List[str] = []
    failed = False
    for store in args.stores:
        result = check_store(store)
        lines.extend((
            f"file={result.path}",
            f"file_bytes={result.file_bytes}",
            f"record_count={result.record_count}",
            f"canonical_stream_bytes={result.canonical_bytes}",
            f"expected_standard_sha256={result.expected}",
            f"stored_payload_aggregate_sha256={result.stored}",
            f"match={str(result.match).upper()}",
        ))
        failed = failed or not result.match
    text = "\n".join(lines) + "\n"
    if args.output:
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        print(text, end="")
    if failed and not args.allow_mismatch:
        raise SystemExit("payload aggregate SHA-256 mismatch")


if __name__ == "__main__":
    main()
