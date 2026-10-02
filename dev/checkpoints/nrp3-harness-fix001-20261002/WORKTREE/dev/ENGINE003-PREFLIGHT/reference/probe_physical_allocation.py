#!/usr/bin/env python3
"""Bounded macOS/APFS physical-allocation capability probe without timing.

This is an engineering capability probe, not a Stage-A payload workload.  It
uses the construction primitive required by the frozen column-major and tiled
plans, records the file state before and after zero fill, and fails closed when
physical allocation or the absence of holes cannot be demonstrated.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import platform
import struct
import subprocess
import tempfile
from pathlib import Path


F_PREALLOCATE = 42
F_ALLOCATEALL = 0x00000004
F_PEOFPOSMODE = 3
F_FULLFSYNC = 51
ZERO_CHUNK_BYTES = 64 * 1024
CASES = {
    "COLUMN_MAJOR_DISK": 1_048_613,
    "TILED_DISK": 1_114_149,
}


def filesystem_type(path: Path) -> str:
    process = subprocess.run(
        ["df", "-P", str(path)], check=False, capture_output=True, text=True
    )
    if process.returncode != 0 or len(process.stdout.splitlines()) < 2:
        return "NOT_AVAILABLE"
    mountpoint = process.stdout.splitlines()[-1].split()[-1]
    mounts = subprocess.run(
        ["mount"], check=False, capture_output=True, text=True
    )
    marker = f" on {mountpoint} ("
    for line in mounts.stdout.splitlines():
        if marker in line:
            return line.split(marker, 1)[1].split(",", 1)[0].rstrip(")")
    return "NOT_AVAILABLE"


def seek_extent(fd: int, logical_bytes: int) -> dict[str, object]:
    if logical_bytes == 0:
        return {
            "seek_data_offset": "NOT_APPLICABLE_EMPTY",
            "seek_hole_offset": "NOT_APPLICABLE_EMPTY",
            "seek_extent_status": "PASS_EMPTY",
        }
    if not hasattr(os, "SEEK_DATA") or not hasattr(os, "SEEK_HOLE"):
        return {
            "seek_data_offset": "NOT_AVAILABLE",
            "seek_hole_offset": "NOT_AVAILABLE",
            "seek_extent_status": "UNSUPPORTED",
        }
    try:
        data = os.lseek(fd, 0, os.SEEK_DATA)
        hole = os.lseek(fd, 0, os.SEEK_HOLE)
    except OSError as error:
        return {
            "seek_data_offset": "ERROR",
            "seek_hole_offset": "ERROR",
            "seek_extent_status": f"UNSUPPORTED_ERRNO_{error.errno}",
        }
    return {
        "seek_data_offset": data,
        "seek_hole_offset": hole,
        "seek_extent_status": (
            "PASS_NO_HOLE" if data == 0 and hole >= logical_bytes
            else "FAIL_HOLE_OR_MISSING_DATA"
        ),
    }


def snapshot(fd: int, phase: str, requested_bytes: int) -> dict[str, object]:
    value = os.fstat(fd)
    allocated = value.st_blocks * 512
    output = {
        "phase": phase,
        "requested_logical_bytes": requested_bytes,
        "logical_length_bytes": value.st_size,
        "st_blocks_512": value.st_blocks,
        "physical_allocated_bytes": allocated,
        "allocated_covers_logical_length": allocated >= value.st_size,
    }
    output.update(seek_extent(fd, value.st_size))
    return output


def preallocate_exact(fd: int, length: int) -> int:
    import fcntl

    request = struct.pack("@IIqqq", F_ALLOCATEALL, F_PEOFPOSMODE, 0, length, 0)
    returned = fcntl.fcntl(fd, F_PREALLOCATE, request)
    _flags, _posmode, _offset, returned_length, bytes_allocated = struct.unpack(
        "@IIqqq", returned
    )
    if returned_length != length:
        raise OSError(errno.EIO, "F_PREALLOCATE returned a different length")
    os.ftruncate(fd, length)
    return bytes_allocated


def zero_fill(fd: int, length: int) -> int:
    block = bytes(ZERO_CHUNK_BYTES)
    offset = 0
    writes = 0
    while offset < length:
        count = min(ZERO_CHUNK_BYTES, length - offset)
        written = os.pwrite(fd, block[:count], offset)
        if written != count:
            raise OSError(errno.EIO, "short bounded zero-fill write")
        offset += written
        writes += 1
    return writes


def verify_zero(fd: int, length: int) -> tuple[int, bool]:
    offset = 0
    reads = 0
    while offset < length:
        value = os.pread(fd, min(ZERO_CHUNK_BYTES, length - offset), offset)
        if not value:
            return reads, False
        if any(value):
            return reads + 1, False
        offset += len(value)
        reads += 1
    return reads, offset == length


def run_case(parent: Path, backend: str, length: int) -> dict[str, object]:
    path = parent / f"{backend.lower()}.bin"
    fd = os.open(
        str(path),
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        before = snapshot(fd, "EMPTY_NEW_FILE", length)
        returned_allocation = preallocate_exact(fd, length)
        after_preallocate = snapshot(fd, "AFTER_F_PREALLOCATE_AND_FTRUNCATE", length)
        writes = zero_fill(fd, length)
        os.fsync(fd)
        try:
            import fcntl
            fcntl.fcntl(fd, F_FULLFSYNC, 0)
            sync_primitive = "fsync+fcntl(F_FULLFSYNC)"
        except OSError:
            sync_primitive = "fsync;F_FULLFSYNC_UNAVAILABLE"
        after_zero = snapshot(fd, "AFTER_BOUNDED_FULL_ZERO_FILL", length)
        reads, all_zero = verify_zero(fd, length)
    finally:
        os.close(fd)
    passed = (
        after_preallocate["logical_length_bytes"] == length
        and after_preallocate["physical_allocated_bytes"] >= length
        and after_zero["logical_length_bytes"] == length
        and after_zero["physical_allocated_bytes"] >= length
        and after_zero["seek_extent_status"] == "PASS_NO_HOLE"
        and all_zero
    )
    return {
        "backend": backend,
        "status": "PASS" if passed else "UNSUPPORTED_FAIL_CLOSED",
        "requested_bytes": length,
        "allocation_primitive": (
            "fcntl(F_PREALLOCATE,F_ALLOCATEALL,F_PEOFPOSMODE)+ftruncate+"
            "bounded_pwrite_zero_fill"
        ),
        "f_preallocate_reported_bytes_allocated": returned_allocation,
        "zero_fill_chunk_bytes": ZERO_CHUNK_BYTES,
        "zero_fill_write_count": writes,
        "zero_verification_read_count": reads,
        "all_logical_bytes_verified_zero": all_zero,
        "sync_primitive": sync_primitive,
        "snapshots": [before, after_preallocate, after_zero],
    }


def probe(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("probe root must be an existing directory")
    system = platform.system()
    fs_type = filesystem_type(root)
    cases: dict[str, dict[str, object]] = {}
    if system != "Darwin" or fs_type.lower() != "apfs":
        for backend, length in CASES.items():
            cases[backend] = {
                "backend": backend,
                "status": "UNSUPPORTED_FAIL_CLOSED",
                "requested_bytes": length,
                "reason": "probe contract requires macOS on APFS",
            }
    else:
        with tempfile.TemporaryDirectory(
            prefix="e3-allocation-probe-", dir=str(root)
        ) as raw:
            parent = Path(raw)
            for backend, length in CASES.items():
                try:
                    cases[backend] = run_case(parent, backend, length)
                except (OSError, ValueError, struct.error) as error:
                    cases[backend] = {
                        "backend": backend,
                        "status": "UNSUPPORTED_FAIL_CLOSED",
                        "requested_bytes": length,
                        "reason": f"{type(error).__name__}:{error}",
                    }
    supported = all(value["status"] == "PASS" for value in cases.values())
    return {
        "status": (
            "PHYSICAL_ALLOCATION_NO_HOLE_PROBE_PASS" if supported
            else "PHYSICAL_ALLOCATION_NO_HOLE_PROBE_UNSUPPORTED"
        ),
        "probe_scope": "BOUNDED_CAPABILITY_ONLY_NO_TIMING_NO_STAGE_A_PAYLOAD",
        "platform_system": system,
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "filesystem_type": fs_type,
        "probe_root": str(root.resolve()),
        "construction_policy": (
            "EXACT_PHYSICAL_PREALLOCATION_THEN_FULL_BOUNDED_ZERO_FILL_V1"
        ),
        "cases": cases,
        "all_required_backends_supported": supported,
        "timing_executed": False,
        "stage_a_payload_workload_executed": False,
        "sparse_or_truncate_only_shortcut_permitted": False,
        "cleanup": "OWNED_TEMPORARY_DIRECTORY_REMOVED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = probe(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    if not report["all_required_backends_supported"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
