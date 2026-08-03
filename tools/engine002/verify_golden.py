#!/usr/bin/env python3
"""Independent stdlib-only verifier for ENGINE002 golden plan bytes."""

from pathlib import Path
import struct
import sys

MASK = (1 << 64) - 1
P1 = 11400714785074694791
P2 = 14029467366897019727
P3 = 1609587929392839161
P4 = 9650029242287828579
P5 = 2870177450012600261


def rol(value, bits):
    return ((value << bits) | (value >> (64 - bits))) & MASK


def round64(acc, value):
    acc = (acc + value * P2) & MASK
    acc = rol(acc, 31)
    return (acc * P1) & MASK


def merge(acc, value):
    acc ^= round64(0, value)
    return (acc * P1 + P4) & MASK


def xxh64(data):
    size = len(data)
    cursor = 0
    if size >= 32:
        v1 = (P1 + P2) & MASK
        v2 = P2
        v3 = 0
        v4 = (-P1) & MASK
        while cursor <= size - 32:
            v1 = round64(v1, struct.unpack_from("<Q", data, cursor)[0])
            v2 = round64(v2, struct.unpack_from("<Q", data, cursor + 8)[0])
            v3 = round64(v3, struct.unpack_from("<Q", data, cursor + 16)[0])
            v4 = round64(v4, struct.unpack_from("<Q", data, cursor + 24)[0])
            cursor += 32
        result = (rol(v1, 1) + rol(v2, 7) + rol(v3, 12) + rol(v4, 18)) & MASK
        for value in (v1, v2, v3, v4):
            result = merge(result, value)
    else:
        result = P5
    result = (result + size) & MASK
    while cursor <= size - 8:
        value = round64(0, struct.unpack_from("<Q", data, cursor)[0])
        result ^= value
        result = (rol(result, 27) * P1 + P4) & MASK
        cursor += 8
    if cursor <= size - 4:
        result ^= struct.unpack_from("<I", data, cursor)[0] * P1
        result = (rol(result, 23) * P2 + P3) & MASK
        cursor += 4
    while cursor < size:
        result ^= data[cursor] * P5
        result = (rol(result, 11) * P1) & MASK
        cursor += 1
    result ^= result >> 33
    result = (result * P2) & MASK
    result ^= result >> 29
    result = (result * P3) & MASK
    result ^= result >> 32
    return result


def u16(data, at):
    return struct.unpack_from("<H", data, at)[0]


def u32(data, at):
    return struct.unpack_from("<I", data, at)[0]


def u64(data, at):
    return struct.unpack_from("<Q", data, at)[0]


def verify(path):
    raw = bytes.fromhex(Path(path).read_text(encoding="ascii").strip())
    assert len(raw) == 218
    assert raw[:4] == b"TPLN"
    assert (u16(raw, 4), u16(raw, 6), u16(raw, 8), u16(raw, 10)) == (1, 0, 144, 0)
    assert (u64(raw, 12), u32(raw, 20), u32(raw, 24)) == (17, 4, 5)
    assert (u32(raw, 28), u32(raw, 32), u32(raw, 36), u32(raw, 40)) == (1, 2, 4, 3)
    assert raw[44:48] == bytes((1, 4, 1, 0))
    assert u64(raw, 48) == 74
    assert raw[136:144] == bytes(8)
    assert u64(raw, 120) == xxh64(raw[144:])
    assert u64(raw, 128) == xxh64(raw[:128])
    assert raw[144] == 0x07
    assert raw[145:147] == bytes((0x60, 0x02))
    assert tuple(u32(raw, 147 + 4 * i) for i in range(4)) == (0, 1, 2, 2)
    assert tuple(u32(raw, 163 + 4 * i) for i in range(4)) == (0, 13, 26, 39)
    entries = raw[179:]
    assert len(entries) == 39
    assert [entries[i + 12] for i in (0, 13, 26)] == [1, 2, 4]
    return raw


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_golden.py <plan.hex>")
    verified = verify(sys.argv[1])
    print("ENGINE002_PYTHON_GOLDEN_PASS")
    print(f"record_bytes={len(verified)}")
    print(f"record_xxh64={xxh64(verified):016x}")
