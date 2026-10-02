#!/usr/bin/env python3
"""Bounded non-Stage-B root/child/grandchild process-tree control."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


ALLOCATION_BYTES = 48 * 1024 * 1024


def exclusive_text(path: Path, text: str) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        raw = text.encode("ascii")
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short write")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def wait_for(path: Path, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"control signal timeout:{path.name}")
        time.sleep(0.01)


def role_grandchild(control: Path) -> None:
    payload = bytearray(ALLOCATION_BYTES)
    for offset in range(0, len(payload), 4096):
        payload[offset] = offset % 251
    exclusive_text(control / "grandchild.pid", f"{os.getpid()}\n")
    exclusive_text(control / "grandchild.ready", f"{len(payload)}\n")
    print(f"SAMPLER_FIX001_GRANDCHILD_READY bytes={len(payload)}", flush=True)
    wait_for(control / "exit-grandchild.signal")


def role_child(control: Path, script: Path) -> None:
    process = subprocess.Popen([
        sys.executable, "-B", str(script), "--role", "grandchild",
        "--control-dir", str(control),
    ])
    exclusive_text(control / "child.pid", f"{os.getpid()}\n")
    wait_for(control / "grandchild.ready")
    exclusive_text(control / "child.ready", "READY\n")
    wait_for(control / "exit-child.signal")
    process.wait(timeout=30)
    if process.returncode != 0:
        raise RuntimeError("grandchild returned nonzero")


def role_root(control: Path, script: Path) -> None:
    process = subprocess.Popen([
        sys.executable, "-B", str(script), "--role", "child",
        "--control-dir", str(control),
    ])
    exclusive_text(control / "root.pid", f"{os.getpid()}\n")
    wait_for(control / "child.ready")
    exclusive_text(control / "root.ready", "READY\n")
    print("SAMPLER_FIX001_ROOT_READY", flush=True)
    wait_for(control / "exit-root.signal")
    process.wait(timeout=30)
    if process.returncode != 0:
        raise RuntimeError("child returned nonzero")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("root", "child", "grandchild"))
    parser.add_argument("--control-dir", required=True, type=Path)
    args = parser.parse_args()
    control = args.control_dir.resolve(strict=True)
    script = Path(__file__).resolve(strict=True)
    if args.role == "grandchild":
        role_grandchild(control)
    elif args.role == "child":
        role_child(control, script)
    else:
        role_root(control, script)


if __name__ == "__main__":
    main()
