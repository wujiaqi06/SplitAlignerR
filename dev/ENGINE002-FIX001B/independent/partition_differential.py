#!/usr/bin/env python3
"""Independent hashlib oracle for the production FIX001B SHA probe."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import random
import struct
import subprocess
from typing import BinaryIO, Iterable, List, Sequence, Tuple


PROTOCOL_MAGIC = b"SAHCASE1"
END = 0xFFFFFFFF
BOUNDARY_LENGTHS = (
    0, 1, 2, 55, 56, 57, 62, 63, 64, 65, 66, 119, 120, 121,
    126, 127, 128, 129, 130, 191, 192, 193, 255, 256, 257,
)


def read_exact(handle: BinaryIO, size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        chunk = handle.read(size - len(value))
        if not chunk:
            raise RuntimeError("production SHA probe ended before its response")
        value.extend(chunk)
    return bytes(value)


class Probe:
    def __init__(self, executable: pathlib.Path) -> None:
        self.process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("cannot open production SHA probe pipes")
        self.process.stdin.write(PROTOCOL_MAGIC)
        self.process.stdin.flush()

    def run(self, message: bytes, chunks: Sequence[int],
            digest_between_updates: bool = False) -> Tuple[str, str, str]:
        if sum(chunks) != len(message):
            raise ValueError("partition does not cover its message")
        request = bytearray(struct.pack(
            "<III", len(message), len(chunks),
            1 if digest_between_updates else 0,
        ))
        for chunk in chunks:
            request.extend(struct.pack("<I", chunk))
        request.extend(message)
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(request)
        self.process.stdin.flush()
        response = read_exact(self.process.stdout, 96)
        return tuple(
            response[offset:offset + 32].hex() for offset in (0, 32, 64)
        )

    def close(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.write(struct.pack("<I", END))
            self.process.stdin.flush()
            self.process.stdin.close()
        stderr = b""
        if self.process.stderr is not None:
            stderr = self.process.stderr.read()
        code = self.process.wait()
        if code != 0:
            raise RuntimeError(
                "production SHA probe failed: " +
                stderr.decode("utf-8", errors="replace")
            )


def write_lines(path: pathlib.Path, lines: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line)
            handle.write("\n")


def load_vectors(path: pathlib.Path) -> List[Tuple[str, bytes, str]]:
    vectors = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in handle:
            if not raw.strip() or raw.startswith("#"):
                continue
            name, kind, value, repeats, expected = raw.rstrip("\n").split("\t")
            if kind == "hex":
                message = b"" if value == "-" else bytes.fromhex(value)
            elif kind == "utf8":
                message = value.encode("utf-8") * int(repeats)
            else:
                raise ValueError("unknown reference-vector kind: " + kind)
            if hashlib.sha256(message).hexdigest() != expected:
                raise RuntimeError("reference vector disagrees with hashlib: " + name)
            vectors.append((name, message, expected))
    return vectors


def irregular_partition(length: int) -> List[int]:
    remaining = length
    result = [0]
    for width in (1, 2, 55, 0, 56, 63, 64, 65, 7, 128, 3):
        take = min(width, remaining)
        result.append(take)
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        result.append(remaining)
    result.extend((0, 0))
    return result


def deterministic_message(length: int) -> bytes:
    return bytes(((index * 131 + length * 17 + 0x53) & 0xFF)
                 for index in range(length))


def random_partition(length: int, case_index: int,
                     rng: random.Random) -> List[int]:
    if length == 0:
        return [0, 0]
    mode = case_index % 6
    if mode == 0:
        return [1] * length
    if mode == 1:
        return [0, length, 0]
    widths = []
    remaining = length
    toggle = False
    while remaining:
        if mode == 2:
            requested = 1 if not toggle else 4096
            toggle = not toggle
        elif mode == 3:
            requested = rng.randint(1, 97)
        elif mode == 4:
            requested = (55, 1, 7, 56, 8, 63, 1, 64, 65)[len(widths) % 9]
        else:
            requested = rng.randint(1, min(8192, remaining))
        take = min(requested, remaining)
        widths.append(take)
        remaining -= take
        if len(widths) % 7 == 0:
            widths.append(0)
    return [0] + widths + [0]


def assert_case(probe: Probe, message: bytes, chunks: Sequence[int],
                digest_between: bool = False) -> Tuple[bool, str]:
    expected = hashlib.sha256(message).hexdigest()
    observed = probe.run(message, chunks, digest_between)
    return all(value == expected for value in observed), expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument(
        "--vectors", type=pathlib.Path,
        default=pathlib.Path(__file__).with_name("reference_vectors.txt"),
    )
    parser.add_argument("--random-cases", type=int, default=10000)
    parser.add_argument("--seed", type=lambda value: int(value, 0),
                        default=0x5A17B001)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    probe = Probe(args.probe.resolve())
    standard_rows = ["vector\tpartition\tmessage_bytes\tchunks\texpected\tstatus"]
    boundary_rows = ["message_bytes\tsplit\texpected\tstatus"]
    standard_mismatches = 0
    two_part_cases = 0
    two_part_mismatches = 0
    random_mismatches = 0
    try:
        for name, message, expected in load_vectors(args.vectors):
            partitions = (
                ("single", [len(message)], False),
                ("one_byte", [1] * len(message) if message else [0], False),
                ("irregular_zero", irregular_partition(len(message)),
                 name == "abc"),
            )
            for label, chunks, digest_between in partitions:
                passed, observed_expected = assert_case(
                    probe, message, chunks, digest_between
                )
                standard_mismatches += 0 if passed else 1
                standard_rows.append(
                    f"{name}\t{label}\t{len(message)}\t{len(chunks)}\t"
                    f"{observed_expected}\t{'PASS' if passed else 'FAIL'}"
                )
                if observed_expected != expected:
                    raise RuntimeError("fixed vector expected digest changed")

        for length in range(261):
            message = deterministic_message(length)
            expected = hashlib.sha256(message).hexdigest()
            for split in range(length + 1):
                passed, _ = assert_case(
                    probe, message, [split, length - split]
                )
                two_part_cases += 1
                two_part_mismatches += 0 if passed else 1
                if length in BOUNDARY_LENGTHS:
                    boundary_rows.append(
                        f"{length}\t{split}\t{expected}\t"
                        f"{'PASS' if passed else 'FAIL'}"
                    )

        rng = random.Random(args.seed)
        forced_lengths = (0, 1, 2, 55, 56, 63, 64, 65, 65536)
        for case_index in range(args.random_cases):
            if case_index < len(forced_lengths):
                length = forced_lengths[case_index]
            elif case_index % 1000 == 0:
                length = 65536
            else:
                draw = rng.random()
                if draw < 0.40:
                    length = rng.choice(BOUNDARY_LENGTHS)
                elif draw < 0.80:
                    length = rng.randint(0, 2048)
                else:
                    length = rng.randint(2049, 16384)
            message = rng.randbytes(length)
            chunks = random_partition(length, case_index, rng)
            passed, _ = assert_case(probe, message, chunks)
            random_mismatches += 0 if passed else 1
    finally:
        probe.close()

    write_lines(args.output_dir / "STANDARD_VECTOR_RESULTS.tsv", standard_rows)
    write_lines(args.output_dir / "BOUNDARY_SPLIT_RESULTS.tsv", boundary_rows)
    summary = [
        "status=" + (
            "PASS" if standard_mismatches == two_part_mismatches ==
            random_mismatches == 0 else "FAIL"
        ),
        "independent_reference=Python hashlib.sha256",
        f"seed=0x{args.seed:08x}",
        f"standard_vector_forms={len(standard_rows) - 1}",
        f"standard_vector_mismatches={standard_mismatches}",
        f"pro_exact_mre={'PASS' if standard_mismatches == 0 else 'FAIL'}",
        "two_part_message_lengths=0..260",
        f"two_part_cases={two_part_cases}",
        f"two_part_mismatches={two_part_mismatches}",
        f"random_multipart_cases={args.random_cases}",
        f"random_multipart_mismatches={random_mismatches}",
        "random_max_message_bytes=65536",
        "zero_length_updates=covered",
        "digest_repeat_and_continue=covered",
    ]
    write_lines(args.output_dir / "SUMMARY.txt", summary)
    if standard_mismatches or two_part_mismatches or random_mismatches:
        raise SystemExit("FIX001B SHA differential mismatch")


if __name__ == "__main__":
    main()
