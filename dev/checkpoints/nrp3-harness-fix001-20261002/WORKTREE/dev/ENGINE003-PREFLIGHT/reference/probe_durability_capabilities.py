#!/usr/bin/env python3
"""Non-timing local filesystem capability probe for DURABLE_PUBLISH_V1."""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path


REQUIRED = (
    "component_file_sync", "temporary_directory_sync", "atomic_no_replace",
    "parent_directory_sync", "manifest_file_sync", "final_directory_sync",
)


def result(status: str, primitive: str, detail: str = "") -> dict[str, str]:
    return {"status": status, "primitive": primitive, "detail": detail}


def sync_file(fd: int) -> tuple[str, str]:
    if platform.system() == "Darwin":
        import fcntl
        command = getattr(fcntl, "F_FULLFSYNC", 51)
        fcntl.fcntl(fd, command, 0)
        return "PASS", "fcntl(F_FULLFSYNC)"
    if platform.system() == "Linux":
        os.fsync(fd)
        return "PASS", "fsync(regular-file-fd)"
    raise OSError(errno.ENOTSUP, "no frozen full-file sync primitive")


def sync_directory(path: Path) -> tuple[str, str]:
    if platform.system() not in {"Darwin", "Linux"}:
        raise OSError(errno.ENOTSUP, "directory durability barrier unsupported")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(str(path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return "PASS", "fsync(directory-fd)"


def rename_exclusive(source: Path, target: Path) -> tuple[str, str]:
    libc = ctypes.CDLL(None, use_errno=True)
    if platform.system() == "Darwin":
        function = getattr(libc, "renamex_np", None)
        if function is None:
            raise OSError(errno.ENOTSUP, "renamex_np absent")
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        rc = function(os.fsencode(source), os.fsencode(target), 0x00000004)
        primitive = "renamex_np(RENAME_EXCL)"
    elif platform.system() == "Linux":
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise OSError(errno.ENOTSUP, "renameat2 absent")
        function.argtypes = (
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        rc = function(-100, os.fsencode(source), -100, os.fsencode(target), 1)
        primitive = "renameat2(RENAME_NOREPLACE)"
    else:
        raise OSError(errno.ENOTSUP, "exclusive rename unsupported")
    if rc != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return "PASS", primitive


def filesystem_type(path: Path) -> str:
    if platform.system() == "Darwin":
        disk = subprocess.run(
            ["df", "-P", str(path)], check=False, capture_output=True, text=True
        )
        if disk.returncode != 0 or len(disk.stdout.splitlines()) < 2:
            return "NOT_AVAILABLE"
        mountpoint = disk.stdout.splitlines()[-1].split()[-1]
        mounts = subprocess.run(
            ["mount"], check=False, capture_output=True, text=True
        )
        marker = f" on {mountpoint} ("
        for line in mounts.stdout.splitlines():
            if marker in line:
                return line.split(marker, 1)[1].split(",", 1)[0].rstrip(")")
        return "NOT_AVAILABLE"
    elif platform.system() == "Linux":
        command = ["stat", "-f", "-c", "%T", str(path)]
    else:
        return "NOT_AVAILABLE"
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    return process.stdout.strip() if process.returncode == 0 else "NOT_AVAILABLE"


def capture(callable_value, primitive_if_error: str) -> dict[str, str]:
    try:
        status, primitive = callable_value()
        return result(status, primitive)
    except OSError as error:
        return result("UNSUPPORTED", primitive_if_error,
                      f"errno={error.errno}:{error.strerror}")


def probe(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("probe root must be an existing directory")
    capabilities: dict[str, dict[str, str]] = {}
    if platform.system() not in {"Darwin", "Linux"}:
        for name in REQUIRED:
            capabilities[name] = result(
                "UNSUPPORTED", "NONE",
                "DURABLE_PUBLISH_V1 has no frozen implementation on this platform",
            )
    else:
        with tempfile.TemporaryDirectory(prefix="e3-durability-probe-", dir=str(root)) as raw:
            parent = Path(raw)
            temporary = parent / "candidate.tmp"
            final = parent / "candidate.final"
            temporary.mkdir()
            component = temporary / "COMPONENT.bin"
            fd = os.open(str(component), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            try:
                if os.write(fd, b"ENGINE003_DURABILITY_CAPABILITY_PROBE\n") <= 0:
                    raise OSError(errno.EIO, "component probe write failed")
                capabilities["component_file_sync"] = capture(
                    lambda: sync_file(fd), "required regular-file full sync",
                )
            finally:
                os.close(fd)
            capabilities["temporary_directory_sync"] = capture(
                lambda: sync_directory(temporary), "fsync(temporary-directory-fd)",
            )
            capabilities["atomic_no_replace"] = capture(
                lambda: rename_exclusive(temporary, final),
                "exclusive no-replace directory rename",
            )
            if capabilities["atomic_no_replace"]["status"] == "PASS":
                capabilities["parent_directory_sync"] = capture(
                    lambda: sync_directory(parent), "fsync(parent-directory-fd)",
                )
                manifest = final / "VALIDATED"
                fd = os.open(str(manifest), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
                try:
                    if os.write(fd, b"ENGINE003_DURABILITY_MANIFEST_PROBE\n") <= 0:
                        raise OSError(errno.EIO, "manifest probe write failed")
                    capabilities["manifest_file_sync"] = capture(
                        lambda: sync_file(fd), "required manifest full sync",
                    )
                finally:
                    os.close(fd)
                capabilities["final_directory_sync"] = capture(
                    lambda: sync_directory(final), "fsync(final-directory-fd)",
                )
            else:
                for name in ("parent_directory_sync", "manifest_file_sync", "final_directory_sync"):
                    capabilities[name] = result(
                        "NOT_RUN_DEPENDENCY_FAILED", "NONE",
                        "exclusive rename capability failed first",
                    )
    supported = all(capabilities[name]["status"] == "PASS" for name in REQUIRED)
    return {
        "status": (
            "DURABILITY_CAPABILITY_PROBE_PASS" if supported
            else "DURABILITY_CAPABILITY_PROBE_UNSUPPORTED"
        ),
        "probe_scope": "CAPABILITY_ONLY_NO_TIMING_PAYLOAD_WORKLOAD",
        "requested_profile": "DURABLE_PUBLISH_V1",
        "effective_profile": "DURABLE_PUBLISH_V1" if supported else "UNSUPPORTED",
        "durable_publish_v1_supported": supported,
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "filesystem_type": filesystem_type(root),
        "probe_root": str(root.resolve()),
        "capabilities": capabilities,
        "physical_preallocation_capability": "NOT_PROBED_SEPARATE_STAGE_A_GATE",
        "timing_executed": False,
        "payload_workload_executed": False,
        "silent_downgrade_permitted": False,
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


if __name__ == "__main__":
    main()
