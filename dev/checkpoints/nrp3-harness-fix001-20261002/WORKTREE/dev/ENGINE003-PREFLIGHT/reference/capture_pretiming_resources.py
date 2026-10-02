#!/usr/bin/env python3
"""Capture fresh host resource inputs for the no-timing admission table."""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path

from probe_durability_capabilities import filesystem_type


DARWIN_PHYSICAL_MEMORY_AUTHORITY = "DARWIN_SYSCTLBYNAME_HW_MEMSIZE_V1"


class ResourceCaptureError(RuntimeError):
    """Typed fail-closed resource-capture error."""

    def __init__(self, reason: str, detail: str):
        self.capture_stage = "DARWIN_HW_MEMSIZE"
        self.reason = reason
        self.detail = detail
        super().__init__(
            f"RESOURCE_CAPTURE_DARWIN_HW_MEMSIZE:{reason}:{detail}"
        )


def command(argv: list[str]) -> str:
    value = subprocess.run(argv, check=True, capture_output=True, text=True)
    return value.stdout.strip()


def _load_darwin_sysctlbyname():
    try:
        function = ctypes.CDLL(None, use_errno=True).sysctlbyname
        function.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        function.restype = ctypes.c_int
    except (AttributeError, OSError) as error:
        raise ResourceCaptureError(
            "NATIVE_API_UNAVAILABLE", type(error).__name__,
        ) from error
    except Exception as error:
        raise ResourceCaptureError(
            "NATIVE_ABI_CONFIGURATION_FAILURE", type(error).__name__,
        ) from error
    return function


def darwin_sysctlbyname_hw_memsize(sysctlbyname=None) -> int:
    """Return exact Darwin hw.memsize or fail with a typed capture error."""
    function = sysctlbyname or _load_darwin_sysctlbyname()
    value = ctypes.c_uint64(0)
    returned_size = ctypes.c_size_t(ctypes.sizeof(value))
    ctypes.set_errno(0)
    try:
        return_code = int(function(
            b"hw.memsize",
            ctypes.byref(value),
            ctypes.byref(returned_size),
            None,
            0,
        ))
    except Exception as error:
        raise ResourceCaptureError(
            "NATIVE_CALL_EXCEPTION", type(error).__name__,
        ) from error
    observed_errno = int(ctypes.get_errno())
    if return_code != 0:
        raise ResourceCaptureError(
            "NONZERO_NATIVE_RETURN",
            f"return_code={return_code};errno={observed_errno}",
        )
    if observed_errno != 0:
        raise ResourceCaptureError(
            "NONZERO_ERRNO_ON_SUCCESS", f"errno={observed_errno}",
        )
    if returned_size.value != ctypes.sizeof(ctypes.c_uint64):
        raise ResourceCaptureError(
            "WRONG_RETURNED_BYTE_COUNT",
            f"returned={returned_size.value};expected=8",
        )
    physical = int(value.value)
    if physical <= 0:
        raise ResourceCaptureError(
            "NONPOSITIVE_PHYSICAL_MEMORY", f"value={physical}",
        )
    return physical


def capture(destination: Path) -> dict[str, object]:
    if not destination.is_dir():
        raise ValueError("destination must be an existing directory")
    if platform.system() != "Darwin":
        raise ResourceCaptureError(
            "UNSUPPORTED_PLATFORM", f"platform={platform.system()}",
        )
    physical = darwin_sysctlbyname_hw_memsize()
    physical_authority = DARWIN_PHYSICAL_MEMORY_AUTHORITY
    pressure = command(["/usr/bin/memory_pressure", "-Q"])
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", pressure)
    if not match:
        raise ValueError("memory_pressure did not report a free percentage")
    disk = shutil.disk_usage(destination)
    statvfs = os.statvfs(destination)
    allocation_unit = statvfs.f_frsize or statvfs.f_bsize
    df_lines = command(["df", "-Pk", str(destination)]).splitlines()
    if len(df_lines) < 2:
        raise ValueError("df did not report the exact target volume")
    df_fields = df_lines[-1].split()
    if len(df_fields) < 6:
        raise ValueError("df target-volume row is incomplete")
    volume_device = df_fields[0]
    volume_mount_point = df_fields[-1]
    mount_marker = f" on {volume_mount_point} ("
    mount_entry = next(
        (line for line in command(["mount"]).splitlines() if mount_marker in line),
        "NOT_AVAILABLE",
    )
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    return {
        "status": "FRESH_PRETIMING_RESOURCE_CAPTURE_PASS",
        "capture_time": now,
        "host_id": socket.gethostname(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "os_build": (
            f"macOS-{command(['sw_vers', '-productVersion'])}-"
            f"{command(['sw_vers', '-buildVersion'])}-Darwin-"
            f"{platform.release()}-{platform.machine()}"
        ),
        "filesystem": filesystem_type(destination),
        "destination": str(destination.resolve()),
        "destination_device_id": os.stat(destination).st_dev,
        "target_volume_device": volume_device,
        "target_volume_mount_point": volume_mount_point,
        "target_volume_mount_entry": mount_entry,
        "target_volume_df_pk": df_lines[-1],
        "physical_memory_bytes": physical,
        "physical_memory_authority": physical_authority,
        "observed_memory_free_percent": int(match.group(1)),
        "observed_available_memory_bytes": "NOT_EXACTLY_REPORTED_BY_OS",
        "observed_available_memory_proxy_bytes": (
            physical * int(match.group(1)) // 100
        ),
        "observed_available_memory_proxy_basis": (
            "hw.memsize multiplied by memory_pressure -Q free percentage; "
            "recorded as a proxy, not an exact allocatable-byte claim"
        ),
        "admission_memory_ceiling_policy": "50_PERCENT_OF_PHYSICAL_MEMORY",
        "admission_memory_ceiling_bytes": physical // 2,
        "available_local_disk_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "allocation_unit_bytes": allocation_unit,
        "capture_commands": [
            physical_authority, "memory_pressure -Q", "shutil.disk_usage",
            "os.statvfs", "sw_vers", "platform", "socket.gethostname",
            "df -Pk", "mount", "os.stat(destination).st_dev",
        ],
        "timing_executed": False,
        "backend_allocation_executed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.destination)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
