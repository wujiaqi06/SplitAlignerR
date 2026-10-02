#!/usr/bin/env python3
"""Bounded non-Stage-B Darwin child-churn control for SAMPLER-FIX004."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


sys.dont_write_bytecode = True


def append_event(path: Path, value: dict[str, object]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short event write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive(path: Path, value: dict[str, object]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short marker write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=48)
    parser.add_argument("--bytes", type=int, default=1024 * 1024)
    args = parser.parse_args()
    if args.cycles != 48 or args.bytes != 1024 * 1024:
        parser.error("frozen bounded control is exactly 48 x 1 MiB")
    write_exclusive(args.ready, {
        "status": "READY", "root_pid": os.getpid(), "root_pgid": os.getpgrp(),
        "cycle_count": args.cycles, "requested_bytes_per_child": args.bytes,
    })
    for sequence in range(args.cycles):
        code = (
            "import os,time;"
            f"payload=bytearray({args.bytes});"
            "print(os.getpid(),flush=True);"
            "time.sleep(0.002 if (os.getpid()%3) else 0.0002);"
            "raise SystemExit(0 if len(payload) else 9)"
        )
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", code], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(timeout=5)
        append_event(args.events, {
            "sequence": sequence, "child_pid": process.pid,
            "return_code": process.returncode,
            "stdout": stdout.decode("ascii").strip(),
            "stderr": stderr.decode("utf-8", errors="replace"),
        })
        if process.returncode != 0 or stderr or stdout.strip() != str(process.pid).encode():
            raise RuntimeError(f"bounded child failure:{sequence}")
    time.sleep(0.02)
    print("PASS_SAMPLER_FIX004_CHURN_CONTROL CYCLES=48 BYTES_PER_CHILD=1048576")


if __name__ == "__main__":
    main()
