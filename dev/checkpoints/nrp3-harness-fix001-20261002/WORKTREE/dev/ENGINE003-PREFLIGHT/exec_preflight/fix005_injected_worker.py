#!/usr/bin/env python3
"""Bounded-only process-tree, resource and timeout injection worker.

This file is never a Stage-B backend and never receives an authority-sized
descriptor.  It exists solely to exercise controller ownership boundaries.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def allocate_child(megabytes: int, seconds: float) -> None:
    payload = bytearray(megabytes * 1024 * 1024)
    for offset in range(0, len(payload), 4096):
        payload[offset] = offset % 251
    print(f"CHILD_MEMORY_READY bytes={len(payload)}", flush=True)
    time.sleep(seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=(
        "cooperative", "uncooperative", "grandchild", "memory-parent",
        "memory-child", "root-exits-grandchild-ignores",
    ))
    parser.add_argument("--partial", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--pid-evidence", type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--megabytes", type=int, default=48)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--partial-state", choices=("present", "absent"), default="present")
    parser.add_argument("--target-state", choices=("safe", "unsafe", "absent"), default="absent")
    args = parser.parse_args()

    if args.mode == "memory-child":
        allocate_child(args.megabytes, args.seconds)
        return
    if args.mode == "memory-parent":
        child = subprocess.Popen([
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--mode", "memory-child", "--megabytes", str(args.megabytes),
            "--seconds", str(args.seconds),
        ])
        if args.pid_evidence:
            write(args.pid_evidence, {"parent_pid": os.getpid(), "child_pid": child.pid})
        child.wait()
        return

    if args.partial_state == "present" and args.partial:
        write(args.partial, {
            "schema": "SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1",
            "last_completed_phase": "INJECTED_SETUP",
            "current_phase": "INJECTED_TIMEOUT_WAIT",
        })
    if args.target_state == "safe" and args.target:
        args.target.mkdir(parents=True, exist_ok=False)
        (args.target / "partial-evidence.bin").write_bytes(b"bounded-timeout-evidence")
    elif args.target_state == "unsafe" and args.target:
        args.target.parent.mkdir(parents=True, exist_ok=True)
        args.target.symlink_to(Path("/tmp"), target_is_directory=True)

    handled_signals = [signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        handled_signals.append(signal.SIGBREAK)
    if args.mode in ("cooperative", "root-exits-grandchild-ignores"):
        def stop(_signum, _frame):
            if args.partial:
                write(args.partial, {
                    "schema": "SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1",
                    "last_completed_phase": "INJECTED_SETUP",
                    "current_phase": "COOPERATIVE_STOP_ACKNOWLEDGED",
                })
            print("COOPERATIVE_STOP_ACKNOWLEDGED", flush=True)
            raise SystemExit(0)
        for handled_signal in handled_signals:
            signal.signal(handled_signal, stop)
    else:
        for handled_signal in handled_signals:
            signal.signal(handled_signal, signal.SIG_IGN)

    if args.ready_file:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text("READY\n", encoding="ascii")

    child = None
    if args.mode in ("grandchild", "root-exits-grandchild-ignores"):
        child_ready = (
            args.pid_evidence.with_suffix(".child-ready")
            if args.pid_evidence else Path.cwd() / f"child-{os.getpid()}.ready"
        )
        child = subprocess.Popen([
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--mode", "uncooperative", "--partial-state", "absent",
            "--target-state", "absent", "--ready-file", str(child_ready),
        ])
        deadline = time.monotonic() + 2
        while not child_ready.is_file() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("uncooperative child exited before ready")
            time.sleep(0.01)
        if not child_ready.is_file():
            child.kill()
            raise RuntimeError("uncooperative child readiness timeout")
        if args.pid_evidence:
            write(args.pid_evidence, {
                "parent_pid": os.getpid(), "child_pid": child.pid,
                "child_ready_path": str(child_ready),
            })
    print(f"INJECTED_WORKER_READY mode={args.mode} pid={os.getpid()}", flush=True)
    while True:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
