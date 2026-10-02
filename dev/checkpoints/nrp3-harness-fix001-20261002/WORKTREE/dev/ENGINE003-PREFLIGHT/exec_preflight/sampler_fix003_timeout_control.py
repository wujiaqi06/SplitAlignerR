#!/usr/bin/env python3
"""Bounded non-Stage-B controls for the SAMPLER-FIX003 timeout corpus."""

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
    "ROOT_EXITS_UNSEEN_CHILD_IGNORES",
    "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
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
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(canonical(value))
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise OSError("short_write")
            remaining = remaining[count:]
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


def internal_argv(
        case_id: str, role: str, pid_evidence: Path, ready: Path,
        ) -> list[str]:
    return [
        sys.executable, "-B", str(Path(__file__).resolve()),
        "--case-id", case_id, "--internal-role", role,
        "--pid-evidence", str(pid_evidence), "--ready", str(ready),
    ]


def grandchild_main(pid_evidence: Path, ready: Path) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    update_pids(pid_evidence, grandchild_pid=os.getpid())
    atomic_write(ready, {"pid": os.getpid(), "status": "READY"})
    wait_forever()


def child_main(case_id: str, pid_evidence: Path, ready: Path) -> None:
    if case_id == "ROOT_AND_CHILD_COOPERATIVE_EXIT":
        signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    update_pids(pid_evidence, child_pid=os.getpid())
    atomic_write(ready, {"pid": os.getpid(), "status": "READY"})
    if case_id in (
        "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
        "ROOT_AND_DESCENDANTS_REQUIRE_FORCE",
    ):
        grandchild_ready = ready.with_name(f"{ready.name}.grandchild")
        subprocess.Popen(
            internal_argv(
                case_id, "grandchild", pid_evidence, grandchild_ready,
            ),
            stdin=subprocess.DEVNULL,
        )
    wait_forever()


def spawn_child(
        case_id: str, pid_evidence: Path, ready: Path,
        ) -> subprocess.Popen:
    return subprocess.Popen(
        internal_argv(case_id, "child", pid_evidence, ready),
        stdin=subprocess.DEVNULL,
    )


def wait_ready(path: Path, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 5
    while not path.is_file():
        if process.poll() is not None:
            raise RuntimeError("control process exited before readiness")
        if time.monotonic() >= deadline:
            raise RuntimeError("control readiness timeout")
        time.sleep(0.01)


def root_main(
        case_id: str, partial: Path, pid_evidence: Path, ready: Path,
        ) -> None:
    atomic_write(partial, {
        "schema": "SplitAlignerR/ENGINE003StageBWorkerPartialEvidence/v1",
        "last_completed_phase": "NONE",
        "current_phase": "SAMPLER_FIX003_BOUNDED_TIMEOUT_CONTROL",
        "target_binding_status": "NOT_YET_BOUND",
    })
    update_pids(pid_evidence, root_pid=os.getpid())
    child_ready = ready.with_name(f"{ready.name}.child")
    child: subprocess.Popen | None = None

    if case_id in (
        "ROOT_AND_CHILD_COOPERATIVE_EXIT",
        "ROOT_AND_DESCENDANTS_REQUIRE_FORCE",
    ):
        child = spawn_child(case_id, pid_evidence, child_ready)
        wait_ready(child_ready, child)

    if case_id in (
        "ROOT_ONLY_COOPERATIVE_EXIT",
        "ROOT_AND_CHILD_COOPERATIVE_EXIT",
    ):
        signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    elif case_id in (
        "ROOT_EXITS_UNSEEN_CHILD_IGNORES",
        "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD",
    ):
        def spawn_unseen_and_exit(_signum, _frame) -> None:
            unseen_child = spawn_child(case_id, pid_evidence, child_ready)
            wait_ready(child_ready, unseen_child)
            if case_id == "ROOT_EXITS_UNSEEN_CHILD_SPAWNS_GRANDCHILD":
                wait_ready(
                    child_ready.with_name(f"{child_ready.name}.grandchild"),
                    unseen_child,
                )
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, spawn_unseen_and_exit)
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    atomic_write(ready, {
        "case_id": case_id,
        "child_pid": None if child is None else child.pid,
        "root_pid": os.getpid(),
        "status": "READY",
    })
    print(
        f"SAMPLER_FIX003_TIMEOUT_CONTROL_READY case={case_id} "
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
    args = parser.parse_args()
    if args.internal_role == "root":
        if args.partial is None:
            parser.error("--partial is required for root")
        root_main(args.case_id, args.partial, args.pid_evidence, args.ready)
    elif args.internal_role == "child":
        child_main(args.case_id, args.pid_evidence, args.ready)
    else:
        grandchild_main(args.pid_evidence, args.ready)


if __name__ == "__main__":
    main()
