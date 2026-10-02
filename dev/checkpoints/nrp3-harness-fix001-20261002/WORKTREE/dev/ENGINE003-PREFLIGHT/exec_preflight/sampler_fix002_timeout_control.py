#!/usr/bin/env python3
"""Bounded non-Stage-B controls for the SAMPLER-FIX002 timeout corpus."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


sys.dont_write_bytecode = True


CASES = (
    "ROOT_ONLY_COOPERATIVE_EXIT",
    "ROOT_AND_CHILD_COOPERATIVE_EXIT",
    "ROOT_EXITS_CHILD_IGNORES",
    "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD",
    "ROOT_AND_DESCENDANTS_REQUIRE_FORCE",
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("ascii")


def atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        raw = canonical(value)
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short_write")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def update_pids(path: Path, **rows: int) -> None:
    current = {}
    if path.is_file():
        current = json.loads(path.read_text(encoding="ascii"))
    current.update(rows)
    atomic_write(path, current)


def wait_forever() -> None:
    while True:
        time.sleep(0.05)


def grandchild_main(pid_evidence: Path, ready: Path) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    update_pids(pid_evidence, grandchild_pid=os.getpid())
    atomic_write(ready, {"status": "READY", "pid": os.getpid()})
    wait_forever()


def child_main(
        case_id: str, pid_evidence: Path, ready: Path,
        grandchild_ready: Path) -> None:
    update_pids(pid_evidence, child_pid=os.getpid())
    spawned: list[subprocess.Popen] = []

    def spawn_grandchild() -> None:
        if spawned:
            return
        spawned.append(subprocess.Popen([
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--internal-role", "grandchild",
            "--case-id", case_id,
            "--pid-evidence", str(pid_evidence),
            "--ready", str(grandchild_ready),
        ]))

    if case_id == "ROOT_AND_CHILD_COOPERATIVE_EXIT":
        pass
    elif case_id == "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD":
        def on_term(_signum, _frame):
            spawn_grandchild()
        signal.signal(signal.SIGTERM, on_term)
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    if case_id == "ROOT_AND_DESCENDANTS_REQUIRE_FORCE":
        spawn_grandchild()
        deadline = time.monotonic() + 5
        while not grandchild_ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not grandchild_ready.is_file():
            raise RuntimeError("grandchild readiness timeout")

    atomic_write(ready, {"status": "READY", "pid": os.getpid()})
    wait_forever()


def root_main(
        case_id: str, partial: Path, pid_evidence: Path, ready: Path) -> None:
    atomic_write(partial, {
        "schema": "SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1",
        "last_completed_phase": "NONE",
        "current_phase": "SAMPLER_FIX002_BOUNDED_TIMEOUT_CONTROL",
        "target_binding_status": "NOT_YET_BOUND",
    })
    update_pids(pid_evidence, root_pid=os.getpid())

    if case_id in (
        "ROOT_ONLY_COOPERATIVE_EXIT",
        "ROOT_AND_CHILD_COOPERATIVE_EXIT",
        "ROOT_EXITS_CHILD_IGNORES",
        "ROOT_EXITS_CHILD_SPAWNS_GRANDCHILD",
    ):
        def root_stop(_signum, _frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, root_stop)
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    child_ready = ready.with_name(f"{ready.name}.child")
    grandchild_ready = ready.with_name(f"{ready.name}.grandchild")
    child = None
    if case_id != "ROOT_ONLY_COOPERATIVE_EXIT":
        child = subprocess.Popen([
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--internal-role", "child", "--case-id", case_id,
            "--pid-evidence", str(pid_evidence),
            "--ready", str(child_ready),
            "--grandchild-ready", str(grandchild_ready),
        ])
        deadline = time.monotonic() + 5
        while not child_ready.is_file() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("child exited before readiness")
            time.sleep(0.01)
        if not child_ready.is_file():
            raise RuntimeError("child readiness timeout")
    atomic_write(ready, {
        "status": "READY", "case_id": case_id,
        "root_pid": os.getpid(),
        "child_pid": None if child is None else child.pid,
    })
    print(
        f"SAMPLER_FIX002_TIMEOUT_CONTROL_READY case={case_id} "
        f"root={os.getpid()}",
        flush=True,
    )
    wait_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True, choices=CASES)
    parser.add_argument(
        "--internal-role", choices=("root", "child", "grandchild"),
        default="root",
    )
    parser.add_argument("--partial", type=Path)
    parser.add_argument("--pid-evidence", required=True, type=Path)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--grandchild-ready", type=Path)
    args = parser.parse_args()
    if args.internal_role == "root":
        if args.partial is None:
            parser.error("--partial is required for root")
        root_main(args.case_id, args.partial, args.pid_evidence, args.ready)
    elif args.internal_role == "child":
        if args.grandchild_ready is None:
            parser.error("--grandchild-ready is required for child")
        child_main(
            args.case_id, args.pid_evidence, args.ready,
            args.grandchild_ready,
        )
    else:
        grandchild_main(args.pid_evidence, args.ready)


if __name__ == "__main__":
    main()
