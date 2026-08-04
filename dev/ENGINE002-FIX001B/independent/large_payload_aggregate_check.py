#!/usr/bin/env python3
"""Bounded independent aggregate reconstruction for multi-gigabyte stores."""

from __future__ import annotations

import argparse
import hashlib
import mmap
import pathlib
import struct
from typing import List


DOMAIN = b"SplitAlignerR/TruthPlanPayloadAggregate/v1\0"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def u16(data: mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def check(path: pathlib.Path) -> List[str]:
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            file_bytes = len(data)
            require(file_bytes >= 384, "store is shorter than v1 minimum")
            require(data[:8] == b"SATRST01", "store magic mismatch")
            require(
                (u16(data, 8), u16(data, 10), u16(data, 12), u16(data, 14))
                == (1, 0, 256, 0),
                "store schema/header mismatch",
            )
            global_taxa = u32(data, 32)
            primitives = u32(data, 36)
            count = u64(data, 40)
            records_start = u64(data, 48)
            index_offset = u64(data, 56)
            footer_offset = u64(data, 64)
            require(records_start == 256, "record region does not start at 256")
            require(u64(data, 72) == file_bytes, "header file size mismatch")
            require(index_offset == 256 + u64(data, 80),
                    "record region geometry mismatch")
            require(u64(data, 88) == 64 * count,
                    "index byte count mismatch")
            require(footer_offset == index_offset + 64 * count,
                    "index/footer geometry mismatch")
            require(file_bytes == footer_offset + 128,
                    "footer/file geometry mismatch")
            require(data[footer_offset:footer_offset + 8] == b"SATDONE1",
                    "footer magic mismatch")
            require(u64(data, footer_offset + 16) == count,
                    "footer record count mismatch")
            require(u64(data, footer_offset + 24) == file_bytes,
                    "footer file size mismatch")

            digest = hashlib.sha256()
            digest.update(DOMAIN)
            digest.update(struct.pack("<Q", count))
            canonical_bytes = len(DOMAIN) + 8
            expected_offset = records_start
            prior_retained = None
            retained_bytes = (global_taxa + 7) // 8
            state_bytes = (primitives + 3) // 4
            for pattern_id in range(count):
                entry = index_offset + 64 * pattern_id
                indexed_id, record_offset, record_bytes = struct.unpack_from(
                    "<QQQ", data, entry
                )
                require(indexed_id == pattern_id, "index pattern ID mismatch")
                require(record_offset == expected_offset and record_bytes >= 144,
                        "record boundary mismatch")
                require(record_offset + record_bytes <= index_offset,
                        "record crosses the index boundary")
                require(data[record_offset:record_offset + 4] == b"TPLN",
                        "record magic mismatch")
                require(u64(data, record_offset + 12) == pattern_id,
                        "record pattern ID mismatch")
                require(
                    (u32(data, record_offset + 20),
                     u32(data, record_offset + 24))
                    == (global_taxa, primitives),
                    "record authority dimensions mismatch",
                )
                require(
                    (u32(data, record_offset + 28),
                     u32(data, record_offset + 32))
                    == (retained_bytes, state_bytes),
                    "record count-derived widths mismatch",
                )
                payload_bytes = u64(data, record_offset + 48)
                require(record_bytes == 144 + payload_bytes,
                        "record payload length mismatch")
                retained = bytes(data[
                    record_offset + 144:record_offset + 144 + retained_bytes
                ])
                require(data[entry + 24:entry + 56] ==
                        data[record_offset + 56:record_offset + 88],
                        "index retained identity mismatch")
                if prior_retained is not None:
                    require(prior_retained < retained,
                            "retained patterns are not canonical and unique")
                prior_retained = retained
                payload_start = record_offset + 144
                digest.update(struct.pack("<Q", pattern_id))
                digest.update(struct.pack("<Q", payload_bytes))
                digest.update(data[payload_start:payload_start + payload_bytes])
                canonical_bytes += 16 + payload_bytes
                expected_offset += record_bytes
            require(expected_offset == index_offset,
                    "record region has a gap or overlap")
            expected = digest.hexdigest()
            stored = bytes(data[
                footer_offset + 48:footer_offset + 80
            ]).hex()
            require(expected == stored, "payload aggregate SHA-256 mismatch")
            return [
                f"file={path}",
                f"file_bytes={file_bytes}",
                f"record_count={count}",
                f"canonical_stream_bytes={canonical_bytes}",
                f"expected_standard_sha256={expected}",
                f"stored_payload_aggregate_sha256={stored}",
                "match=TRUE",
                "memory_policy=mmap plus one-record bounded payload slices",
                "nonaggregate_hashes=validated_by_production_reopen_gate",
            ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stores", nargs="+", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    lines: List[str] = []
    for path in args.stores:
        lines.extend(check(path))
    text = "\n".join(lines) + "\n"
    if args.output:
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
