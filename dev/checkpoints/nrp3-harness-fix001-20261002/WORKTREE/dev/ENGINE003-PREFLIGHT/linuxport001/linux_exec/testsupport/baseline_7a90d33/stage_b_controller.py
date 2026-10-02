#!/usr/bin/env python3
"""Generic process-tree controller for the parameterized Stage-B worker.

This is the exact controller boundary intended for both bounded certification
and a later externally authorized Stage-B launch.  The request file is the only
mode/config input.  An unauthorized large request stops before ``Popen``.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import os
import platform
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, MutableMapping, Set


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fix001_contract import (  # noqa: E402
    ExecutionAuthority,
    FrozenAssets,
    StopSignal,
    canonical_json_bytes,
    strict_json_load,
    write_canonical_json,
)
from stage_b_authorization import load_exact_runtime_resource_capture  # noqa: E402
from stage_b_runtime_contract import (  # noqa: E402
    BOUNDED_MODE,
    LIVE_SCHEMA,
    WORKER_RESULT_SCHEMA,
    prelaunch_guard,
)
from stage_b_orchestrator import validate_worker_result_identity  # noqa: E402


WORKER = HERE / "stage_b_worker.py"
TIMEOUT_COOPERATIVE_GRACE_SECONDS = 60
PROCESS_TREE_RSS_SAMPLE_INTERVAL_SECONDS = 0.01
PROCESS_TREE_COMMAND_TIMEOUT_SECONDS = 2.0
PROCESS_TREE_FORCE_VERIFY_SECONDS = 5.0
DARWIN_SAMPLER_MECHANISM_ID = "DARWIN_LIBPROC_PROCESS_TREE_AUTHORITY_V2"
DARWIN_LIBPROC_PATH = "/usr/lib/libproc.dylib"
DARWIN_PROC_ALL_PIDS = 1
DARWIN_PROC_PGRP_ONLY = 2
DARWIN_PROC_PIDTBSDINFO = 3
DARWIN_PROC_PIDTASKINFO = 4
DARWIN_PROCESS_STATUS_ZOMBIE = 5
DARWIN_LIVE_PROCESS_STATUSES = (1, 2, 3, 4)
DARWIN_CHILD_INITIAL_CAPACITY = 64
DARWIN_CHILD_MAXIMUM_CAPACITY = 4096
DARWIN_GROUP_INITIAL_CAPACITY = 64
DARWIN_GROUP_MAXIMUM_CAPACITY = 4096
DARWIN_ZERO_RSS_FOLLOWUP_ROUNDS = 4
DARWIN_ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS = 0.001
DARWIN_GROUP_CENSUS_FOLLOWUP_ROUNDS = 4
DARWIN_GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS = 0.001
DARWIN_AUTHORIZED_RELEASE = "23.4.0"
DARWIN_AUTHORIZED_MACHINE = "arm64"
DARWIN_AUTHORIZED_MACOS_VERSION = "14.4"


class NativeSamplerCapabilityError(RuntimeError):
    """Typed failure at the Darwin sampler authority boundary."""


class NativeSamplerProcessAbsent(NativeSamplerCapabilityError):
    """Identity-aware process disappearance, never a zero-valued sample."""


class NativeSamplerIdentityAwareExitRace(NativeSamplerProcessAbsent):
    """Stable-census/identity-proven exit during a zero-RSS follow-up."""


class DarwinProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class DarwinProcTaskInfo(ctypes.Structure):
    _fields_ = [
        ("pti_virtual_size", ctypes.c_uint64),
        ("pti_resident_size", ctypes.c_uint64),
        ("pti_total_user", ctypes.c_uint64),
        ("pti_total_system", ctypes.c_uint64),
        ("pti_threads_user", ctypes.c_uint64),
        ("pti_threads_system", ctypes.c_uint64),
        ("pti_policy", ctypes.c_int32),
        ("pti_faults", ctypes.c_int32),
        ("pti_pageins", ctypes.c_int32),
        ("pti_cow_faults", ctypes.c_int32),
        ("pti_messages_sent", ctypes.c_int32),
        ("pti_messages_received", ctypes.c_int32),
        ("pti_syscalls_mach", ctypes.c_int32),
        ("pti_syscalls_unix", ctypes.c_int32),
        ("pti_csw", ctypes.c_int32),
        ("pti_threadnum", ctypes.c_int32),
        ("pti_numrunning", ctypes.c_int32),
        ("pti_priority", ctypes.c_int32),
    ]


DARWIN_EXPECTED_ABI = {
    "sizeof_pid_t": 4,
    "sizeof_proc_bsdinfo": 136,
    "alignof_proc_bsdinfo": 8,
    "offsetof_pbi_status": 4,
    "offsetof_pbi_pid": 12,
    "offsetof_pbi_ppid": 16,
    "offsetof_pbi_pgid": 100,
    "offsetof_pbi_start_tvsec": 120,
    "offsetof_pbi_start_tvusec": 128,
    "sizeof_proc_taskinfo": 96,
    "alignof_proc_taskinfo": 8,
    "offsetof_pti_resident_size": 8,
    "proc_pidtbsdinfo": DARWIN_PROC_PIDTBSDINFO,
    "proc_pidtaskinfo": DARWIN_PROC_PIDTASKINFO,
    "proc_all_pids": DARWIN_PROC_ALL_PIDS,
    "proc_pgrp_only": DARWIN_PROC_PGRP_ONLY,
}


def _darwin_ctypes_abi() -> Dict[str, int]:
    return {
        "sizeof_pid_t": ctypes.sizeof(ctypes.c_int),
        "sizeof_proc_bsdinfo": ctypes.sizeof(DarwinProcBsdInfo),
        "alignof_proc_bsdinfo": ctypes.alignment(DarwinProcBsdInfo),
        "offsetof_pbi_status": DarwinProcBsdInfo.pbi_status.offset,
        "offsetof_pbi_pid": DarwinProcBsdInfo.pbi_pid.offset,
        "offsetof_pbi_ppid": DarwinProcBsdInfo.pbi_ppid.offset,
        "offsetof_pbi_pgid": DarwinProcBsdInfo.pbi_pgid.offset,
        "offsetof_pbi_start_tvsec": DarwinProcBsdInfo.pbi_start_tvsec.offset,
        "offsetof_pbi_start_tvusec": DarwinProcBsdInfo.pbi_start_tvusec.offset,
        "sizeof_proc_taskinfo": ctypes.sizeof(DarwinProcTaskInfo),
        "alignof_proc_taskinfo": ctypes.alignment(DarwinProcTaskInfo),
        "offsetof_pti_resident_size": DarwinProcTaskInfo.pti_resident_size.offset,
        "proc_pidtbsdinfo": DARWIN_PROC_PIDTBSDINFO,
        "proc_pidtaskinfo": DARWIN_PROC_PIDTASKINFO,
        "proc_all_pids": DARWIN_PROC_ALL_PIDS,
        "proc_pgrp_only": DARWIN_PROC_PGRP_ONLY,
    }


class DarwinLibprocSamplerBackend:
    """Fail-closed identity-aware libproc process-tree RSS authority."""

    def __init__(self) -> None:
        observed_profile = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "macos_version": platform.mac_ver()[0],
        }
        expected_profile = {
            "system": "Darwin",
            "release": DARWIN_AUTHORIZED_RELEASE,
            "machine": DARWIN_AUTHORIZED_MACHINE,
            "macos_version": DARWIN_AUTHORIZED_MACOS_VERSION,
        }
        if sys.platform != "darwin" or observed_profile != expected_profile:
            raise NativeSamplerCapabilityError("UNSUPPORTED_PLATFORM")
        observed_abi = _darwin_ctypes_abi()
        if observed_abi != DARWIN_EXPECTED_ABI:
            raise NativeSamplerCapabilityError(
                f"ABI_MISMATCH:{observed_abi!r}"
            )
        try:
            library = ctypes.CDLL(DARWIN_LIBPROC_PATH, use_errno=True)
            list_children = library.proc_listchildpids
            list_group_direct = library.proc_listpgrppids
            list_group_generic = library.proc_listpids
            process_info = library.proc_pidinfo
            list_children.argtypes = [
                ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
            ]
            list_children.restype = ctypes.c_int
            list_group_direct.argtypes = [
                ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
            ]
            list_group_direct.restype = ctypes.c_int
            list_group_generic.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_int,
            ]
            list_group_generic.restype = ctypes.c_int
            process_info.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                ctypes.c_void_p, ctypes.c_int,
            ]
            process_info.restype = ctypes.c_int
        except Exception as error:
            raise NativeSamplerCapabilityError(
                f"LIBPROC_LOAD_OR_ABI_CONFIG:{type(error).__name__}:{error}"
            ) from error
        self._library = library
        self._list_children = list_children
        self._list_group_direct = list_group_direct
        self._list_group_generic = list_group_generic
        self._process_info = process_info
        self._authority_lock = threading.Lock()
        self._authority_pgid: int | None = None
        self._authority_root_identity: tuple[int, int, int] | None = None
        self._group_retired = False
        self._group_census_count = 0
        self._dual_census_agreement_count = 0
        self._last_group_census: tuple[int, ...] = ()
        self._maximum_group_census_size = 0
        self._retirement_count = 0
        self._group_census_attempt_count = 0
        self._group_census_disagreement_count = 0
        self._group_census_followup_round_count = 0
        self._group_census_recovery_count = 0
        self._group_census_unresolved_count = 0
        self._zero_rss_initial_count = 0
        self._zero_rss_followup_round_count = 0
        self._zero_rss_recovery_count = 0
        self._zero_rss_exit_race_count = 0
        self._zero_rss_unresolved_count = 0
        self._known_identity_absence_revalidation_count = 0
        self._known_identity_absence_exit_count = 0
        self._known_identity_absence_fail_closed_count = 0

    def capability_evidence(self) -> Dict[str, Any]:
        return {
            "mechanism_id": DARWIN_SAMPLER_MECHANISM_ID,
            "library_path": DARWIN_LIBPROC_PATH,
            "ctypes_abi": _darwin_ctypes_abi(),
            "authorized_platform_profile": {
                "system": "Darwin",
                "release": DARWIN_AUTHORIZED_RELEASE,
                "machine": DARWIN_AUTHORIZED_MACHINE,
                "macos_version": DARWIN_AUTHORIZED_MACOS_VERSION,
            },
            "child_initial_capacity": DARWIN_CHILD_INITIAL_CAPACITY,
            "child_maximum_capacity": DARWIN_CHILD_MAXIMUM_CAPACITY,
            "group_initial_capacity": DARWIN_GROUP_INITIAL_CAPACITY,
            "group_maximum_capacity": DARWIN_GROUP_MAXIMUM_CAPACITY,
            "group_direct_function": "proc_listpgrppids",
            "group_cross_check_function": "proc_listpids",
            "group_cross_check_type": "PROC_PGRP_ONLY",
            "group_census_followup_rounds": (
                DARWIN_GROUP_CENSUS_FOLLOWUP_ROUNDS
            ),
            "group_census_followup_interval_nanoseconds": int(
                DARWIN_GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS
                * 1_000_000_000
            ),
            "zero_rss_followup_rounds": DARWIN_ZERO_RSS_FOLLOWUP_ROUNDS,
            "zero_rss_followup_interval_nanoseconds": int(
                DARWIN_ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS * 1_000_000_000
            ),
            "process_identity": [
                "pid", "pbi_start_tvsec", "pbi_start_tvusec",
            ],
            "group_member_pgid_field": "pbi_pgid",
            "once_empty_never_reacquire": True,
            "external_process_table_call_count": 0,
            "fallback_available": False,
        }

    @staticmethod
    def _validate_identity(
            identity: tuple[int, int, int], expected_pid: int | None = None,
            ) -> None:
        if (
            type(identity) is not tuple or len(identity) != 3
            or any(type(value) is not int for value in identity)
            or identity[0] <= 0 or identity[1] <= 0 or identity[2] < 0
            or (expected_pid is not None and identity[0] != expected_pid)
        ):
            raise NativeSamplerCapabilityError(
                f"PROCESS_IDENTITY_INVALID:{identity!r}"
            )

    def bind_process_group_authority(
            self, pgid: int, root_identity: tuple[int, int, int],
            ) -> None:
        if type(pgid) is not int or pgid <= 0:
            raise NativeSamplerCapabilityError("INVALID_AUTHORITY_PGID")
        self._validate_identity(root_identity, pgid)
        with self._authority_lock:
            if self._authority_pgid is None:
                self._authority_pgid = pgid
                self._authority_root_identity = root_identity
                return
            if (
                self._authority_pgid != pgid
                or self._authority_root_identity != root_identity
            ):
                raise NativeSamplerCapabilityError(
                    "PROCESS_GROUP_AUTHORITY_REBIND_REJECTED"
                )

    def _process_group_pids_once(
            self, pgid: int,
            ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Return one bounded dual-native census pair without consuming it."""
        if type(pgid) is not int or pgid <= 0:
            raise NativeSamplerCapabilityError("INVALID_GROUP_PID")
        ctypes.set_errno(0)
        direct_initial = int(self._list_group_direct(pgid, None, 0))
        direct_initial_errno = ctypes.get_errno()
        ctypes.set_errno(0)
        generic_initial = int(self._list_group_generic(
            DARWIN_PROC_PGRP_ONLY, pgid, None, 0,
        ))
        generic_initial_errno = ctypes.get_errno()
        if (
            direct_initial < 0 or direct_initial_errno != 0
            or generic_initial < 0 or generic_initial_errno != 0
            or generic_initial % ctypes.sizeof(ctypes.c_int) != 0
        ):
            raise NativeSamplerCapabilityError(
                "GROUP_ENUMERATION_INITIAL_FAILED:"
                f"pgid={pgid}:direct={direct_initial}:"
                f"direct_errno={direct_initial_errno}:"
                f"generic_bytes={generic_initial}:"
                f"generic_errno={generic_initial_errno}"
            )
        capacity = max(
            DARWIN_GROUP_INITIAL_CAPACITY,
            direct_initial + DARWIN_GROUP_INITIAL_CAPACITY,
            generic_initial // ctypes.sizeof(ctypes.c_int)
            + DARWIN_GROUP_INITIAL_CAPACITY,
        )
        if capacity > DARWIN_GROUP_MAXIMUM_CAPACITY:
            raise NativeSamplerCapabilityError(
                "GROUP_ENUMERATION_INITIAL_CAPACITY_EXCEEDS_BOUND:"
                f"pgid={pgid}:capacity={capacity}"
            )
        while capacity <= DARWIN_GROUP_MAXIMUM_CAPACITY:
            direct_buffer = (ctypes.c_int * capacity)()
            generic_buffer = (ctypes.c_int * capacity)()
            ctypes.set_errno(0)
            direct_return = int(self._list_group_direct(
                pgid, ctypes.byref(direct_buffer),
                ctypes.sizeof(direct_buffer),
            ))
            direct_errno = ctypes.get_errno()
            ctypes.set_errno(0)
            generic_return = int(self._list_group_generic(
                DARWIN_PROC_PGRP_ONLY, pgid,
                ctypes.byref(generic_buffer),
                ctypes.sizeof(generic_buffer),
            ))
            generic_errno = ctypes.get_errno()
            if (
                direct_return < 0 or direct_errno != 0
                or generic_return < 0 or generic_errno != 0
                or generic_return % ctypes.sizeof(ctypes.c_int) != 0
            ):
                raise NativeSamplerCapabilityError(
                    "GROUP_ENUMERATION_FAILED:"
                    f"pgid={pgid}:direct={direct_return}:"
                    f"direct_errno={direct_errno}:"
                    f"generic_bytes={generic_return}:"
                    f"generic_errno={generic_errno}"
                )
            generic_count = generic_return // ctypes.sizeof(ctypes.c_int)
            if direct_return > capacity or generic_count > capacity:
                raise NativeSamplerCapabilityError(
                    "GROUP_ENUMERATION_OVERFLOW:"
                    f"pgid={pgid}:capacity={capacity}"
                )
            truncated = direct_return >= capacity or generic_count >= capacity
            if truncated:
                if capacity == DARWIN_GROUP_MAXIMUM_CAPACITY:
                    break
                capacity = min(
                    capacity * 2, DARWIN_GROUP_MAXIMUM_CAPACITY,
                )
                continue
            direct_raw = tuple(
                int(direct_buffer[index])
                for index in range(direct_return)
            )
            generic_raw = tuple(
                int(generic_buffer[index])
                for index in range(generic_count)
            )
            if any(pid <= 0 for pid in direct_raw + generic_raw):
                raise NativeSamplerCapabilityError(
                    f"GROUP_ENUMERATION_NONPOSITIVE_PID:pgid={pgid}"
                )
            direct_set = tuple(sorted(set(direct_raw)))
            generic_set = tuple(sorted(set(generic_raw)))
            return direct_set, generic_set
        raise NativeSamplerCapabilityError(
            "GROUP_ENUMERATION_TRUNCATED:"
            f"pgid={pgid}:maximum={DARWIN_GROUP_MAXIMUM_CAPACITY}"
        )

    def _accept_group_census(self, census: tuple[int, ...]) -> tuple[int, ...]:
        self._group_census_count += 1
        self._dual_census_agreement_count += 1
        self._last_group_census = census
        self._maximum_group_census_size = max(
            self._maximum_group_census_size, len(census),
        )
        return census

    def process_group_pids(self, pgid: int) -> tuple[int, ...]:
        """Return only a bounded-stable exact dual-native PGID census."""
        direct, generic = self._process_group_pids_once(pgid)
        self._group_census_attempt_count += 1
        if direct == generic:
            return self._accept_group_census(direct)
        self._group_census_disagreement_count += 1
        last_direct, last_generic = direct, generic
        for followup_round in range(1, DARWIN_GROUP_CENSUS_FOLLOWUP_ROUNDS + 1):
            if followup_round > 1:
                time.sleep(DARWIN_GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS)
            direct, generic = self._process_group_pids_once(pgid)
            self._group_census_attempt_count += 1
            self._group_census_followup_round_count += 1
            if direct == generic:
                self._group_census_recovery_count += 1
                return self._accept_group_census(direct)
            self._group_census_disagreement_count += 1
            last_direct, last_generic = direct, generic
        self._group_census_unresolved_count += 1
        raise NativeSamplerCapabilityError(
            "GROUP_ENUMERATION_DISAGREEMENT_UNRESOLVED:"
            f"pgid={pgid}:direct={last_direct!r}:generic={last_generic!r}:"
            f"followup_rounds={DARWIN_GROUP_CENSUS_FOLLOWUP_ROUNDS}"
        )

    def children(self, pid: int) -> tuple[int, ...]:
        if type(pid) is not int or pid <= 0:
            raise NativeSamplerCapabilityError("INVALID_PARENT_PID")
        capacity = DARWIN_CHILD_INITIAL_CAPACITY
        while capacity <= DARWIN_CHILD_MAXIMUM_CAPACITY:
            buffer = (ctypes.c_int * capacity)()
            ctypes.set_errno(0)
            returned = int(self._list_children(
                pid, ctypes.byref(buffer), ctypes.sizeof(buffer),
            ))
            call_errno = ctypes.get_errno()
            if returned < 0 or call_errno != 0:
                raise NativeSamplerCapabilityError(
                    f"CHILD_ENUMERATION_FAILED:pid={pid}:rc={returned}:errno={call_errno}"
                )
            if returned > capacity:
                raise NativeSamplerCapabilityError(
                    f"CHILD_ENUMERATION_OVERFLOW:pid={pid}:count={returned}:capacity={capacity}"
                )
            raw = [int(buffer[index]) for index in range(returned)]
            if any(child <= 0 for child in raw):
                raise NativeSamplerCapabilityError(
                    f"CHILD_ENUMERATION_NONPOSITIVE_PID:pid={pid}"
                )
            values = tuple(sorted(set(raw)))
            if returned < capacity:
                return values
            capacity *= 2
        raise NativeSamplerCapabilityError(
            f"CHILD_ENUMERATION_TRUNCATED:pid={pid}:maximum={DARWIN_CHILD_MAXIMUM_CAPACITY}"
        )

    def identity_and_group(
            self, pid: int,
            ) -> tuple[int, int, tuple[int, int, int]]:
        value = DarwinProcBsdInfo()
        ctypes.set_errno(0)
        returned = int(self._process_info(
            pid, DARWIN_PROC_PIDTBSDINFO, 0,
            ctypes.byref(value), ctypes.sizeof(value),
        ))
        call_errno = ctypes.get_errno()
        if returned == 0 and call_errno == errno.ESRCH:
            raise NativeSamplerProcessAbsent(f"PROCESS_ABSENT:pid={pid}")
        if returned != ctypes.sizeof(value) or call_errno != 0:
            raise NativeSamplerCapabilityError(
                f"BSD_INFO_FAILED:pid={pid}:bytes={returned}:errno={call_errno}"
            )
        observed_pid = int(value.pbi_pid)
        if observed_pid != pid:
            raise NativeSamplerCapabilityError(
                f"BSD_INFO_PID_MISMATCH:requested={pid}:observed={observed_pid}"
            )
        identity = (
            observed_pid,
            int(value.pbi_start_tvsec),
            int(value.pbi_start_tvusec),
        )
        if identity[1] <= 0 or identity[2] < 0:
            raise NativeSamplerCapabilityError(
                f"BSD_INFO_IDENTITY_INVALID:pid={pid}:identity={identity!r}"
            )
        process_status = int(value.pbi_status)
        if process_status == DARWIN_PROCESS_STATUS_ZOMBIE:
            raise NativeSamplerProcessAbsent(f"PROCESS_ZOMBIE:pid={pid}")
        if process_status not in DARWIN_LIVE_PROCESS_STATUSES:
            raise NativeSamplerCapabilityError(
                "BSD_INFO_PROCESS_STATUS_INVALID:"
                f"pid={pid}:status={process_status}"
            )
        pgid = int(value.pbi_pgid)
        if pgid <= 0:
            raise NativeSamplerCapabilityError(
                f"BSD_INFO_PGID_INVALID:pid={pid}:pgid={pgid}"
            )
        return int(value.pbi_ppid), pgid, identity

    def identity(self, pid: int) -> tuple[int, tuple[int, int, int]]:
        ppid, _pgid, identity = self.identity_and_group(pid)
        return ppid, identity

    def _task_rss_once(self, pid: int) -> int:
        value = DarwinProcTaskInfo()
        ctypes.set_errno(0)
        returned = int(self._process_info(
            pid, DARWIN_PROC_PIDTASKINFO, 0,
            ctypes.byref(value), ctypes.sizeof(value),
        ))
        call_errno = ctypes.get_errno()
        if returned == 0:
            try:
                self.identity_and_group(pid)
            except NativeSamplerProcessAbsent as error:
                raise NativeSamplerProcessAbsent(
                    f"PROCESS_ABSENT_RSS:pid={pid}"
                ) from error
            if call_errno == errno.ESRCH:
                raise NativeSamplerProcessAbsent(f"PROCESS_ABSENT_RSS:pid={pid}")
        if returned != ctypes.sizeof(value) or call_errno != 0:
            raise NativeSamplerCapabilityError(
                f"TASK_INFO_FAILED:pid={pid}:bytes={returned}:errno={call_errno}"
            )
        resident = int(value.pti_resident_size)
        if resident < 0:
            raise NativeSamplerCapabilityError(
                f"TASK_INFO_NEGATIVE_RSS:pid={pid}:rss={resident}"
            )
        return resident

    def _revalidate_known_identity_absent_from_stable_census(
            self,
            pid: int,
            expected_identity: tuple[int, int, int],
            expected_pgid: int,
            ) -> None:
        """Classify one known PID omitted by a stable expected-PGID census.

        This is the sole absence authority shared by the owned-tree refresh and
        zero-RSS retry paths.  A stable group census omission is not itself
        proof of exit: the exact PID identity and PGID must be queried once
        more before the omission may be classified as identity-aware exit.
        """
        self._validate_identity(expected_identity, pid)
        if type(expected_pgid) is not int or expected_pgid <= 0:
            raise NativeSamplerCapabilityError(
                f"KNOWN_IDENTITY_EXPECTED_PGID_INVALID:pid={pid}"
            )
        self._known_identity_absence_revalidation_count = getattr(
            self, "_known_identity_absence_revalidation_count", 0,
        ) + 1
        try:
            _ppid, observed_pgid, observed_identity = (
                self.identity_and_group(pid)
            )
        except NativeSamplerProcessAbsent as error:
            self._known_identity_absence_exit_count = getattr(
                self, "_known_identity_absence_exit_count", 0,
            ) + 1
            raise NativeSamplerIdentityAwareExitRace(
                f"KNOWN_IDENTITY_NATIVE_EXIT:pid={pid}"
            ) from error
        except NativeSamplerCapabilityError:
            self._known_identity_absence_fail_closed_count = getattr(
                self, "_known_identity_absence_fail_closed_count", 0,
            ) + 1
            raise
        if observed_identity != expected_identity:
            self._known_identity_absence_fail_closed_count = getattr(
                self, "_known_identity_absence_fail_closed_count", 0,
            ) + 1
            raise NativeSamplerCapabilityError(
                "OWNED_PID_REUSE_REJECTED:"
                f"pid={pid}:expected={expected_identity!r}:"
                f"observed={observed_identity!r}"
            )
        if observed_pgid != expected_pgid:
            self._known_identity_absence_fail_closed_count = getattr(
                self, "_known_identity_absence_fail_closed_count", 0,
            ) + 1
            raise NativeSamplerCapabilityError(
                "OWNED_PROCESS_ESCAPED_WORKER_PGID:"
                f"pid={pid}:expected={expected_pgid}:"
                f"observed={observed_pgid}"
            )
        self._known_identity_absence_fail_closed_count = getattr(
            self, "_known_identity_absence_fail_closed_count", 0,
        ) + 1
        raise NativeSamplerCapabilityError(
            "STABLE_GROUP_CENSUS_IDENTITY_CONTRADICTION:"
            f"pid={pid}:identity={expected_identity!r}:pgid={expected_pgid}"
        )

    def rss(
            self, pid: int,
            expected_identity: tuple[int, int, int] | None = None,
            expected_pgid: int | None = None,
            ) -> int:
        """Read RSS, retrying only a live identity-bound Darwin zero."""
        resident = self._task_rss_once(pid)
        if resident > 0:
            return resident
        self._zero_rss_initial_count += 1
        if expected_identity is None or expected_pgid is None:
            raise NativeSamplerCapabilityError(
                f"TASK_INFO_ZERO_RSS_IDENTITY_AUTHORITY_REQUIRED:pid={pid}"
            )
        self._validate_identity(expected_identity, pid)
        if type(expected_pgid) is not int or expected_pgid <= 0:
            raise NativeSamplerCapabilityError(
                f"TASK_INFO_ZERO_RSS_PGID_INVALID:pid={pid}"
            )
        for followup_round in range(1, DARWIN_ZERO_RSS_FOLLOWUP_ROUNDS + 1):
            if followup_round > 1:
                time.sleep(DARWIN_ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS)
            census = self.process_group_pids(expected_pgid)
            self._zero_rss_followup_round_count += 1
            if pid not in census:
                try:
                    self._revalidate_known_identity_absent_from_stable_census(
                        pid, expected_identity, expected_pgid,
                    )
                except NativeSamplerIdentityAwareExitRace:
                    self._zero_rss_exit_race_count += 1
                    raise
                raise AssertionError("unreachable absence revalidation")
            try:
                _ppid, observed_pgid, observed_identity = (
                    self.identity_and_group(pid)
                )
            except NativeSamplerProcessAbsent as error:
                self._zero_rss_exit_race_count += 1
                raise NativeSamplerIdentityAwareExitRace(
                    f"PROCESS_EXITED_BEFORE_RSS:pid={pid}"
                ) from error
            if observed_identity != expected_identity:
                raise NativeSamplerCapabilityError(
                    "PID_REUSE_DURING_ZERO_RSS_RETRY:"
                    f"pid={pid}:expected={expected_identity!r}:"
                    f"observed={observed_identity!r}"
                )
            if observed_pgid != expected_pgid:
                raise NativeSamplerCapabilityError(
                    "PGID_CHANGE_DURING_ZERO_RSS_RETRY:"
                    f"pid={pid}:expected={expected_pgid}:"
                    f"observed={observed_pgid}"
                )
            resident = self._task_rss_once(pid)
            if resident > 0:
                self._zero_rss_recovery_count += 1
                return resident
        self._zero_rss_unresolved_count += 1
        raise NativeSamplerCapabilityError(
            "TASK_INFO_ZERO_RSS_UNRESOLVED:"
            f"pid={pid}:followup_rounds={DARWIN_ZERO_RSS_FOLLOWUP_ROUNDS}"
        )

    def live_owned_tree(
            self,
            known_identities: Mapping[int, tuple[int, int, int]],
            ) -> tuple[
                Dict[int, tuple[int, int, int]], Set[int],
            ]:
        """Refresh exact ownership from the frozen dedicated PGID census."""
        if not known_identities:
            raise NativeSamplerCapabilityError("OWNED_IDENTITY_SET_EMPTY")
        for pid, expected_identity in sorted(known_identities.items()):
            self._validate_identity(expected_identity, pid)
        with self._authority_lock:
            if (
                self._authority_pgid is None
                or self._authority_root_identity is None
            ):
                raise NativeSamplerCapabilityError(
                    "PROCESS_GROUP_AUTHORITY_NOT_BOUND"
                )
            pgid = self._authority_pgid
            root_identity = self._authority_root_identity
            census = self.process_group_pids(pgid)
            census_set = set(census)
            absent: Set[int] = set()
            for missing_pid in sorted(
                    set(known_identities).difference(census_set),
                    ):
                try:
                    self._revalidate_known_identity_absent_from_stable_census(
                        missing_pid, known_identities[missing_pid], pgid,
                    )
                except NativeSamplerIdentityAwareExitRace:
                    absent.add(missing_pid)
            if self._group_retired:
                if census:
                    raise NativeSamplerCapabilityError(
                        "PGID_REUSE_OR_AMBIGUITY:"
                        f"pgid={pgid}:pids={census!r}"
                    )
                return {}, absent
            if not census:
                self._group_retired = True
                self._retirement_count += 1
                return {}, absent

            live: Dict[int, tuple[int, int, int]] = {}
            for member_pid in census:
                try:
                    _ppid, observed_pgid, member_identity = (
                        self.identity_and_group(member_pid)
                    )
                except NativeSamplerProcessAbsent:
                    # The two enumeration calls and proc_pidinfo cannot be one
                    # atomic kernel transaction.  ESRCH proves that this row
                    # disappeared after the exact dual census; it contributes
                    # neither identity nor RSS.  Every other lookup failure is
                    # a sampler error.
                    absent.add(member_pid)
                    continue
                if observed_pgid != pgid:
                    raise NativeSamplerCapabilityError(
                        "GROUP_MEMBER_PGID_MISMATCH:"
                        f"pid={member_pid}:expected={pgid}:"
                        f"observed={observed_pgid}"
                    )
                if member_identity[1:] < root_identity[1:]:
                    raise NativeSamplerCapabilityError(
                        "GROUP_MEMBER_PREDATES_AUTHORITY_ROOT:"
                        f"pid={member_pid}:identity={member_identity!r}:"
                        f"root={root_identity!r}"
                    )
                known = known_identities.get(member_pid)
                if known is not None and known != member_identity:
                    raise NativeSamplerCapabilityError(
                        f"OWNED_PID_REUSE_REJECTED:pid={member_pid}"
                    )
                live[member_pid] = member_identity
            unclassified = set(known_identities).difference(live, absent)
            if unclassified:
                raise NativeSamplerCapabilityError(
                    "KNOWN_IDENTITY_CLASSIFICATION_INCOMPLETE:"
                    f"pids={sorted(unclassified)!r}"
                )
            return live, absent

    def authority_evidence(self) -> Dict[str, Any]:
        with self._authority_lock:
            return {
                "mechanism_id": DARWIN_SAMPLER_MECHANISM_ID,
                "authority_pgid": self._authority_pgid,
                "authority_root_identity": (
                    list(self._authority_root_identity)
                    if self._authority_root_identity is not None else None
                ),
                "group_retired": self._group_retired,
                "group_census_count": self._group_census_count,
                "dual_census_agreement_count": (
                    self._dual_census_agreement_count
                ),
                "last_group_census_pids": list(self._last_group_census),
                "maximum_group_census_size": (
                    self._maximum_group_census_size
                ),
                "retirement_count": self._retirement_count,
                "group_census_attempt_count": getattr(
                    self, "_group_census_attempt_count", 0,
                ),
                "group_census_disagreement_count": getattr(
                    self, "_group_census_disagreement_count", 0,
                ),
                "group_census_followup_round_count": getattr(
                    self, "_group_census_followup_round_count", 0,
                ),
                "group_census_recovery_count": getattr(
                    self, "_group_census_recovery_count", 0,
                ),
                "group_census_unresolved_count": getattr(
                    self, "_group_census_unresolved_count", 0,
                ),
                "zero_rss_initial_count": getattr(
                    self, "_zero_rss_initial_count", 0,
                ),
                "zero_rss_followup_round_count": getattr(
                    self, "_zero_rss_followup_round_count", 0,
                ),
                "zero_rss_recovery_count": getattr(
                    self, "_zero_rss_recovery_count", 0,
                ),
                "zero_rss_exit_race_count": getattr(
                    self, "_zero_rss_exit_race_count", 0,
                ),
                "zero_rss_unresolved_count": getattr(
                    self, "_zero_rss_unresolved_count", 0,
                ),
                "known_identity_absence_revalidation_count": getattr(
                    self, "_known_identity_absence_revalidation_count", 0,
                ),
                "known_identity_absence_exit_count": getattr(
                    self, "_known_identity_absence_exit_count", 0,
                ),
                "known_identity_absence_fail_closed_count": getattr(
                    self, "_known_identity_absence_fail_closed_count", 0,
                ),
                "external_process_table_call_count": 0,
            }


def _native_live_owned_tree(
        backend: DarwinLibprocSamplerBackend,
        known_identities: Mapping[int, tuple[int, int, int]],
        ) -> tuple[Dict[int, tuple[int, int, int]], Set[int]]:
    """One shared Darwin exact-identity authority for RSS and timeout."""
    return DarwinLibprocSamplerBackend.live_owned_tree(
        backend, known_identities,
    )


def _sampler_capability_backend() -> DarwinLibprocSamplerBackend | None:
    if os.name == "nt":
        return None
    if sys.platform == "darwin":
        return DarwinLibprocSamplerBackend()
    raise NativeSamplerCapabilityError("UNSUPPORTED_PLATFORM_NO_FALLBACK")


def _stop_worker_after_sampler_initialization_failure(
        process: subprocess.Popen) -> None:
    """Own the just-created group without consulting a process table."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass
    try:
        process.communicate(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    process.communicate()


def process_group_options() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _process_table() -> Dict[int, tuple[int, int, str]]:
    """Return the frozen Windows table; Darwin has no external fallback."""
    if os.name != "nt":
        raise NativeSamplerCapabilityError("EXTERNAL_PROCESS_TABLE_FORBIDDEN")
    script = (
        "Get-CimInstance Win32_Process | ForEach-Object { "
        "$created = $_.CreationDate.ToUniversalTime().Ticks.ToString(); "
        "Write-Output ($_.ProcessId.ToString() + ',' + "
        "$_.ParentProcessId.ToString() + ',' + $_.WorkingSetSize.ToString() + ',' + "
        "$created) }"
    )
    process = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, check=False,
        timeout=PROCESS_TREE_COMMAND_TIMEOUT_SECONDS,
    )
    multiplier = 1
    if process.returncode:
        return {}
    output: Dict[int, tuple[int, int, str]] = {}
    for line in process.stdout.splitlines():
        fields = line.replace(",", " ").split()
        if len(fields) != 4:
            continue
        try:
            pid, ppid, rss = map(int, fields[:3])
        except ValueError:
            continue
        identity = fields[3]
        output[pid] = (ppid, max(0, rss) * multiplier, identity)
    if not output:
        raise RuntimeError("Windows process table identity unavailable")
    return output


def process_tree_rss_bytes(
        root_pid: int, previously_owned: Set[int] | None = None,
        table: Mapping[int, tuple[Any, ...]] | None = None,
        ) -> tuple[int, Set[int]]:
    observed = dict(_process_table() if table is None else table)
    owned = set(previously_owned or ())
    owned.add(root_pid)
    changed = True
    while changed:
        changed = False
        for pid, record in observed.items():
            ppid = record[0]
            if pid not in owned and ppid in owned:
                owned.add(pid)
                changed = True
    return sum(observed[pid][1] for pid in owned if pid in observed), owned


class ProcessTreeRssSampler:
    """Controller-owned monotonic sampler spanning worker descendants."""

    def __init__(
            self, root_pid: int,
            interval: float = PROCESS_TREE_RSS_SAMPLE_INTERVAL_SECONDS,
            native_backend: DarwinLibprocSamplerBackend | None = None):
        self.root_pid = root_pid
        self.interval = interval
        self.maximum_bytes = 0
        self.maximum_root_bytes = 0
        self.current_bytes = 0
        self.current_root_bytes = 0
        self.sample_count = 0
        self.owned_pids: Set[int] = {root_pid}
        self.owned_process_identities: Dict[int, str] = {}
        self.active_owned_pids: Set[int] = set()
        self.native_backend = native_backend
        self.native_root_identity: tuple[int, int, int] | None = None
        self.native_worker_pgid: int | None = None
        self.native_owned_identities: Dict[int, tuple[int, int, int]] = {}
        self.identity_aware_exit_pids: Set[int] = set()
        self.error = "NONE"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if self.native_backend is not None:
            _root_ppid, root_pgid, root_identity = (
                self.native_backend.identity_and_group(root_pid)
            )
            if root_pgid != root_pid:
                raise NativeSamplerCapabilityError(
                    "WORKER_ROOT_NOT_DEDICATED_PROCESS_GROUP_LEADER:"
                    f"pid={root_pid}:pgid={root_pgid}"
                )
            self.native_backend.bind_process_group_authority(
                root_pgid, root_identity,
            )
            self.native_root_identity = root_identity
            self.native_worker_pgid = root_pgid
            self.native_owned_identities[root_pid] = root_identity
            self.owned_process_identities[root_pid] = self._identity_text(
                root_identity,
            )

    @staticmethod
    def _identity_text(identity: tuple[int, int, int]) -> str:
        return ":".join(str(value) for value in identity)

    def _native_sample(self) -> None:
        assert self.native_backend is not None
        assert self.native_root_identity is not None
        current, absent = _native_live_owned_tree(
            self.native_backend,
            self.native_owned_identities,
        )
        self.identity_aware_exit_pids.update(absent)
        if self.sample_count < 1 and self.root_pid not in current:
            raise NativeSamplerCapabilityError(
                "ROOT_DISAPPEARED_BEFORE_FIRST_SAMPLE"
            )

        rss_rows: Dict[int, int] = {}
        sampled_current = dict(current)
        for pid, expected_identity in sorted(current.items()):
            try:
                if (
                    getattr(type(self.native_backend), "rss", None)
                    is DarwinLibprocSamplerBackend.rss
                ):
                    resident = self.native_backend.rss(
                        pid, expected_identity, self.native_worker_pgid,
                    )
                else:
                    resident = self.native_backend.rss(pid)
            except NativeSamplerIdentityAwareExitRace:
                self.identity_aware_exit_pids.add(pid)
                sampled_current.pop(pid, None)
                continue
            except NativeSamplerProcessAbsent:
                try:
                    _ppid, observed_pgid, observed_identity = (
                        self.native_backend.identity_and_group(pid)
                    )
                except NativeSamplerProcessAbsent:
                    self.identity_aware_exit_pids.add(pid)
                    sampled_current.pop(pid, None)
                    continue
                if (
                    observed_identity != expected_identity
                    or observed_pgid != self.native_worker_pgid
                ):
                    raise NativeSamplerCapabilityError(
                        f"RSS_PID_REUSE_REJECTED:pid={pid}"
                    )
                raise NativeSamplerCapabilityError(
                    f"RSS_UNREADABLE_LIVE_PROCESS:pid={pid}"
                )
            rss_rows[pid] = resident
        if self.sample_count < 1 and self.root_pid not in rss_rows:
            raise NativeSamplerCapabilityError("ROOT_RSS_UNAVAILABLE")
        value = sum(rss_rows.values())
        with self._lock:
            self.native_owned_identities.update(sampled_current)
            self.owned_pids.update(sampled_current)
            self.owned_process_identities.update({
                pid: self._identity_text(identity)
                for pid, identity in sampled_current.items()
            })
            self.active_owned_pids = set(rss_rows)
            self.current_bytes = value
            self.current_root_bytes = rss_rows.get(self.root_pid, 0)
            self.maximum_bytes = max(self.maximum_bytes, value)
            if self.root_pid in rss_rows:
                self.maximum_root_bytes = max(
                    self.maximum_root_bytes, rss_rows[self.root_pid],
                )
            self.sample_count += 1

    def _windows_sample(self) -> None:
        table = _process_table()
        with self._lock:
            previous_owned = set(self.owned_pids)
        value, owned = process_tree_rss_bytes(
            self.root_pid, previous_owned, table,
        )
        identities = {
            pid: table[pid][2] for pid in owned
            if pid in table and len(table[pid]) >= 3 and table[pid][2]
        }
        with self._lock:
            self.owned_process_identities.update(identities)
            self.owned_pids = owned
            self.active_owned_pids = {pid for pid in owned if pid in table}
            self.current_bytes = value
            self.current_root_bytes = (
                table[self.root_pid][1] if self.root_pid in table else 0
            )
            self.maximum_bytes = max(self.maximum_bytes, value)
            if self.root_pid in table:
                self.maximum_root_bytes = max(
                    self.maximum_root_bytes, table[self.root_pid][1],
                )
            self.sample_count += 1

    def _sample(self) -> None:
        if self.native_backend is not None:
            self._native_sample()
        else:
            self._windows_sample()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._sample()
                self._stop.wait(self.interval)
            self._sample()
        except Exception as error:  # evidence records a fail-closed sampler error
            self.error = f"{type(error).__name__}:{error}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def owned_identity_snapshot(self) -> Dict[int, str]:
        """Return one atomic monotonic PID/identity snapshot."""
        with self._lock:
            return {
                pid: self.owned_process_identities.get(pid, "")
                for pid in self.owned_pids
            }

    def native_authority_snapshot(self) -> Dict[str, Any]:
        if self.native_backend is None:
            return {
                "mechanism_id": "NOT_APPLICABLE_NON_DARWIN",
                "external_process_table_call_count": 0,
            }
        return self.native_backend.authority_evidence()


def _process_table_mechanism() -> Dict[str, Any]:
    if os.name == "nt":
        return {
            "mechanism_id": "WINDOWS_CIM_WIN32_PROCESS_POWERSHELL",
            "argv_prefix": [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process",
            ],
            "rss_unit_multiplier": 1,
            "command_timeout_nanoseconds": int(
                PROCESS_TREE_COMMAND_TIMEOUT_SECONDS * 1_000_000_000
            ),
        }
    if sys.platform == "darwin":
        return {
            "mechanism_id": DARWIN_SAMPLER_MECHANISM_ID,
            "library_path": DARWIN_LIBPROC_PATH,
            "ctypes_abi": _darwin_ctypes_abi(),
            "authorized_platform_profile": {
                "system": "Darwin",
                "release": DARWIN_AUTHORIZED_RELEASE,
                "machine": DARWIN_AUTHORIZED_MACHINE,
                "macos_version": DARWIN_AUTHORIZED_MACOS_VERSION,
            },
            "child_initial_capacity": DARWIN_CHILD_INITIAL_CAPACITY,
            "child_maximum_capacity": DARWIN_CHILD_MAXIMUM_CAPACITY,
            "group_initial_capacity": DARWIN_GROUP_INITIAL_CAPACITY,
            "group_maximum_capacity": DARWIN_GROUP_MAXIMUM_CAPACITY,
            "group_direct_function": "proc_listpgrppids",
            "group_cross_check_function": "proc_listpids",
            "group_cross_check_type": "PROC_PGRP_ONLY",
            "once_empty_never_reacquire": True,
            "external_process_table_call_count": 0,
            "fallback_available": False,
        }
    return {
        "mechanism_id": "UNSUPPORTED_PLATFORM_NO_FALLBACK",
        "external_process_table_call_count": 0,
        "fallback_available": False,
    }


def _sampler_diagnostic(
        sampler: ProcessTreeRssSampler,
        worker_return_code: int) -> Dict[str, Any]:
    native_authority_provider = getattr(
        sampler, "native_authority_snapshot", None,
    )
    native_authority = (
        native_authority_provider()
        if callable(native_authority_provider)
        else {
            "mechanism_id": "NOT_APPLICABLE_INJECTED_SAMPLER_CONTROL",
            "external_process_table_call_count": 0,
        }
    )
    return {
        "schema": "SplitAlignerR/ENGINE003StageBProcessTreeSamplerDiagnostic/v1",
        "status": "PROCESS_TREE_SAMPLER_DIAGNOSTIC_CAPTURED",
        "sampler_valid": (
            sampler.error == "NONE" and sampler.sample_count >= 1
            and not sampler._thread.is_alive()
        ),
        "error": sampler.error,
        "sample_count": sampler.sample_count,
        "maximum_bytes": sampler.maximum_bytes,
        "maximum_root_bytes": sampler.maximum_root_bytes,
        "current_bytes": getattr(sampler, "current_bytes", 0),
        "current_root_bytes": getattr(sampler, "current_root_bytes", 0),
        "owned_pids": sorted(sampler.owned_pids),
        "active_owned_pids": sorted(sampler.active_owned_pids),
        "owned_process_identities": [
            {"pid": pid, "identity": identity}
            for pid, identity in sorted(sampler.owned_process_identities.items())
        ],
        "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
        "native_process_group_authority": native_authority,
        "sampling_interval_nanoseconds": int(sampler.interval * 1_000_000_000),
        "process_table_mechanism": _process_table_mechanism(),
        "sampler_thread_alive_after_stop": sampler._thread.is_alive(),
        "worker_return_code": worker_return_code,
    }


def _write_sampler_diagnostic(
        output_path: Path, sampler: ProcessTreeRssSampler,
        worker_return_code: int) -> tuple[Path, Dict[str, Any]]:
    path = output_path.with_suffix(".sampler.json")
    value = _sampler_diagnostic(sampler, worker_return_code)
    write_canonical_json(path, value)
    return path, value


def _raw_file_evidence(path: Path, raw: bytes, source: str) -> Dict[str, Any]:
    return {
        "path": str(path),
        "preserved": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source": source,
    }


def _observed_file_evidence(path: Path) -> Dict[str, Any]:
    try:
        observed = os.lstat(path)
    except OSError:
        return {
            "path": str(path), "preserved": False, "bytes": 0,
            "sha256": "NOT_AVAILABLE", "source": "FILE_ABSENT",
        }
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise StopSignal("SB_STOP_VALIDATION", "failure_evidence_not_regular")
    raw = path.read_bytes()
    return _raw_file_evidence(path, raw, "PRESERVED_FILE_BYTES")


def _write_worker_failure_evidence(
        request: Mapping[str, Any], request_path: Path, request_raw: bytes,
        resource_path: Path, resource_raw: bytes,
        branch_resource_path: Path, branch_resource_raw: bytes,
        output_path: Path, log_path: Path,
        worker_return_code: int, sampler_path: Path,
        sampler_diagnostic: Mapping[str, Any]) -> Path:
    partial_path = output_path.with_suffix(".partial.json")
    path = output_path.with_suffix(".worker-failure.json")
    sampler_raw = canonical_json_bytes(dict(sampler_diagnostic))
    write_canonical_json(path, {
        "schema": "SplitAlignerR/ENGINE003StageBWorkerFailureStop/v1",
        "status": "SB_STOP_VALIDATION",
        "classification": "WORKER_FAILURE_PRECEDES_SAMPLER_INTERPRETATION",
        "decision_ledger_eligible": False,
        "global_execution_stop": True,
        "no_later_request_launch": True,
        "workload_id": request["workload_id"],
        "candidate_id": request["candidate_id"],
        "schedule_row_sha256": request["schedule_row_sha256"],
        "worker_return_code": worker_return_code,
        "worker_result_path": str(output_path),
        "worker_result_exists": output_path.is_file(),
        "sampler_diagnostic": dict(sampler_diagnostic),
        "sampler_interpretation_eligible": False,
        "preserved_files": {
            "worker_log": _observed_file_evidence(log_path),
            "partial_worker_evidence": _observed_file_evidence(partial_path),
            "request": _raw_file_evidence(
                request_path, request_raw, "CONTROLLER_CANONICAL_REQUEST_BYTES",
            ),
            "candidate_series_resource": _raw_file_evidence(
                resource_path, resource_raw, "CONTROLLER_EXACT_LOADER_RAW",
            ),
            "workload_branch_resource": _raw_file_evidence(
                branch_resource_path, branch_resource_raw,
                "CONTROLLER_EXACT_LOADER_RAW",
            ),
            "sampler_diagnostic": _raw_file_evidence(
                sampler_path, sampler_raw, "CONTROLLER_CANONICAL_SIDECAR_BYTES",
            ),
        },
    })
    return path


def _cooperative_stop(process: subprocess.Popen) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, OSError):
        return False


def _process_state_table(
        probe_timeout_seconds: float = PROCESS_TREE_COMMAND_TIMEOUT_SECONDS,
        ) -> Dict[int, tuple[int, int, str, str]]:
    """Return pid -> (ppid, process-group id, state, stable identity)."""
    if probe_timeout_seconds <= 0:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "process_state_probe_budget")
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | ForEach-Object { "
            "$created = $_.CreationDate.ToUniversalTime().Ticks.ToString(); "
            "Write-Output ($_.ProcessId.ToString() + ',' + "
            "$_.ParentProcessId.ToString() + ',' + $created) }"
        )
        command = ["powershell", "-NoProfile", "-Command", script]
    elif sys.platform == "darwin":
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "external_process_state_authority_retired_on_darwin",
        )
    else:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "unsupported_process_state_authority",
        )
    try:
        completed = subprocess.run(
            capture_output=True, text=True, check=False,
            args=command, timeout=probe_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION", "process_state_probe_timeout",
        ) from error
    if completed.returncode:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "process_state_probe_failed")
    output: Dict[int, tuple[int, int, str, str]] = {}
    malformed = 0
    for line in completed.stdout.splitlines():
        fields = line.replace(",", " ").split()
        if not fields:
            continue
        try:
            if os.name == "nt" and len(fields) == 3:
                pid, ppid = map(int, fields[:2])
                identity = fields[2]
                if not identity.isdigit():
                    raise ValueError("missing Windows creation identity")
                output[pid] = (ppid, 0, "LIVE", identity)
            elif os.name != "nt" and len(fields) >= 4:
                pid, ppid, pgid = map(int, fields[:3])
                output[pid] = (ppid, pgid, fields[3], "")
            else:
                malformed += 1
        except ValueError:
            malformed += 1
    if malformed or not output or os.getpid() not in output:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION", "process_state_probe_untrustworthy",
        )
    return output


def _owned_tree_survivors(
        process: subprocess.Popen,
        previously_owned: Mapping[int, str] | Set[int] | None = None,
        probe_timeout_seconds: float = PROCESS_TREE_COMMAND_TIMEOUT_SECONDS,
        native_backend: DarwinLibprocSamplerBackend | None = None,
        ) -> tuple[Set[int], Dict[int, str]]:
    """Refresh ownership and return all live root/group/known descendants."""
    if sys.platform == "darwin":
        del probe_timeout_seconds
        backend = native_backend or DarwinLibprocSamplerBackend()
        if not isinstance(previously_owned, Mapping):
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                "native_owned_identity_map_required",
            )
        parsed: Dict[int, tuple[int, int, int]] = {}
        try:
            for pid, identity_text in previously_owned.items():
                values = tuple(int(value) for value in identity_text.split(":"))
                if len(values) != 3 or values[0] != pid:
                    raise ValueError(f"identity mismatch:{pid}")
                parsed[pid] = values
            root_identity = parsed.get(process.pid)
            if root_identity is None:
                raise ValueError("authority root identity missing")
            backend.bind_process_group_authority(
                process.pid, root_identity,
            )
            current, _absent = _native_live_owned_tree(backend, parsed)
        except (NativeSamplerCapabilityError, ValueError) as error:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                f"native_survivor_authority:{type(error).__name__}:{error}",
            ) from error
        merged = dict(previously_owned)
        merged.update({
            pid: ProcessTreeRssSampler._identity_text(identity)
            for pid, identity in current.items()
        })
        return set(current), merged

    table = _process_state_table(probe_timeout_seconds)
    if isinstance(previously_owned, Mapping):
        owned = dict(previously_owned)
    else:
        owned = {pid: "" for pid in (previously_owned or ())}
    owned.setdefault(process.pid, "")
    if process.pid in table and process.poll() is None:
        root_identity = table[process.pid][3]
        if root_identity and not owned.get(process.pid):
            # The live Popen handle proves that this is still the launched
            # root, so filling its first CreationDate cannot target a reused
            # PID.  Never perform this fill after the root has exited.
            owned[process.pid] = root_identity
        elif (
            os.name == "nt" and root_identity
            and owned.get(process.pid) != root_identity
        ):
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                "windows_root_process_identity_changed",
            )
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _pgid, _state, identity) in table.items():
            if pid not in owned and ppid in owned:
                if os.name == "nt":
                    recorded_parent_identity = owned.get(ppid, "")
                    if not recorded_parent_identity:
                        continue
                    if (
                        ppid in table
                        and table[ppid][3] != recorded_parent_identity
                    ):
                        # A reused parent PID must not transfer ownership to
                        # an unrelated new child.  If the historical parent is
                        # absent, CIM's preserved PPID may still identify an
                        # orphaned descendant of the recorded process.
                        continue
                owned[pid] = identity
                changed = True
    if os.name != "nt":
        # start_new_session=True makes the worker PID its process-group ID.
        # This still finds a descendant after the group leader has exited and
        # also catches a descendant missed by an earlier sampler tick.
        for pid, (_ppid, pgid, _state, identity) in table.items():
            if pgid == process.pid:
                owned.setdefault(pid, identity)
    live = {
        pid for pid in owned if pid in table
        and not table[pid][2].upper().startswith("Z")
        and (not owned[pid] or owned[pid] == table[pid][3])
    }
    return live, owned


def _force_live_processes(
        process: subprocess.Popen, live: Set[int], owned: Dict[int, str],
        command_timeout_seconds: float,
        native_backend: DarwinLibprocSamplerBackend | None = None,
        ) -> Dict[int, str]:
    if command_timeout_seconds <= 0:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "force_command_budget")
    if os.name == "nt":
        command_deadline = time.monotonic() + command_timeout_seconds
        if any(not owned.get(pid) for pid in live):
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                "windows_process_identity_unavailable",
            )
        for pid in sorted(live):
            remaining = command_deadline - time.monotonic()
            if remaining <= 0:
                raise StopSignal(
                    "SB_STOP_TIMEOUT_TERMINATION", "taskkill_budget_exhausted",
                )
            refreshed_live, owned = _owned_tree_survivors(
                process, owned, remaining, native_backend,
            )
            if pid not in refreshed_live:
                continue
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    check=False, timeout=max(
                        0.001, command_deadline - time.monotonic()
                    ),
                )
            except subprocess.TimeoutExpired as error:
                raise StopSignal(
                    "SB_STOP_TIMEOUT_TERMINATION", "taskkill_timeout",
                ) from error
            if completed.returncode:
                still_live, owned = _owned_tree_survivors(
                    process, owned, max(
                        0.001, command_deadline - time.monotonic()
                    ), native_backend,
                )
                if pid in still_live:
                    raise StopSignal(
                        "SB_STOP_TIMEOUT_TERMINATION",
                        f"taskkill_failed:{pid}:{completed.returncode}",
                    )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION", "process_group_force_failed",
            ) from error
    return owned


def _force_terminate_tree(
        process: subprocess.Popen,
        previously_owned: Mapping[int, str] | Set[int] | None = None,
        native_backend: DarwinLibprocSamplerBackend | None = None,
        ) -> tuple[Set[int], Dict[int, str], int]:
    if isinstance(previously_owned, Mapping):
        owned = dict(previously_owned)
    else:
        owned = {pid: "" for pid in (previously_owned or ())}
    owned.setdefault(process.pid, "")
    try:
        live, owned = _owned_tree_survivors(
            process, owned, native_backend=native_backend,
        )
    except StopSignal:
        if sys.platform == "darwin":
            raise
        # Enumeration failure must make termination more conservative, not
        # suppress it.  POSIX killpg still reaches the owned session even if
        # the leader has exited; Windows still has the sampler's monotonic PIDs.
        live = set(owned)
    deadline = time.monotonic() + PROCESS_TREE_FORCE_VERIFY_SECONDS
    owned = _force_live_processes(
        process, live, owned, PROCESS_TREE_COMMAND_TIMEOUT_SECONDS,
        native_backend,
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "force_verify_deadline")
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "process_tree_survived_force") from error
    verification_attempts = 1
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            survivors = set(owned)
            break
        survivors, owned = _owned_tree_survivors(
            process, owned,
            min(PROCESS_TREE_COMMAND_TIMEOUT_SECONDS, remaining),
            native_backend,
        )
        if not survivors:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        owned = _force_live_processes(
            process, survivors, owned,
            min(PROCESS_TREE_COMMAND_TIMEOUT_SECONDS, remaining),
            native_backend,
        )
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.02, remaining))
        verification_attempts += 1
    if survivors:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "owned_processes_survived_force:" + ",".join(map(str, sorted(survivors))),
        )
    return survivors, owned, verification_attempts


def exact_timeout_state_machine(
        process: subprocess.Popen,
        grace_waiter: Callable[[subprocess.Popen, int], bool] | None = None,
        owned_process_provider: Callable[
            [], Mapping[int, str] | Set[int]
        ] | None = None,
        native_backend: DarwinLibprocSamplerBackend | None = None,
        ) -> Dict[str, Any]:
    """Run REQUEST, exact 60-second policy wait, then conditional tree kill.

    Tests inject a virtual waiter, but it is still called with the immutable
    production value 60.  The default performs the real 60-second wait.
    """
    def production_waiter(value: subprocess.Popen, seconds: int) -> bool:
        try:
            value.wait(timeout=seconds)
            return True
        except subprocess.TimeoutExpired:
            return False

    if sys.platform == "darwin" and native_backend is None:
        try:
            native_backend = DarwinLibprocSamplerBackend()
        except NativeSamplerCapabilityError as error:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                f"native_survivor_authority:{type(error).__name__}:{error}",
            ) from error
    pre_stop_owned = owned_process_provider() if owned_process_provider else {}
    if sys.platform == "darwin" and not pre_stop_owned:
        assert native_backend is not None
        try:
            _ppid, root_pgid, root_identity = (
                native_backend.identity_and_group(process.pid)
            )
            if root_pgid != process.pid:
                raise NativeSamplerCapabilityError(
                    "WORKER_ROOT_NOT_DEDICATED_PROCESS_GROUP_LEADER:"
                    f"pid={process.pid}:pgid={root_pgid}"
                )
            native_backend.bind_process_group_authority(
                root_pgid, root_identity,
            )
        except NativeSamplerCapabilityError as error:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                f"native_root_identity:{type(error).__name__}:{error}",
            ) from error
        pre_stop_owned = {
            process.pid: ProcessTreeRssSampler._identity_text(root_identity),
        }
    emitted = _cooperative_stop(process)
    waiter = grace_waiter or production_waiter
    exited = waiter(process, TIMEOUT_COOPERATIVE_GRACE_SECONDS)
    provided_owned = owned_process_provider() if owned_process_provider else {}
    if isinstance(pre_stop_owned, Mapping) and isinstance(provided_owned, Mapping):
        provided_owned = {**pre_stop_owned, **provided_owned}
    elif not provided_owned:
        provided_owned = pre_stop_owned
    if isinstance(provided_owned, Mapping):
        known_owned = dict(provided_owned)
    else:
        known_owned = {pid: "" for pid in provided_owned}
    survivor_probe_error = "NONE"
    try:
        survivors_after_grace, known_owned = _owned_tree_survivors(
            process, known_owned, native_backend=native_backend,
        )
    except StopSignal as error:
        if sys.platform == "darwin":
            raise
        survivor_probe_error = str(error)
        known_owned.setdefault(process.pid, "")
        survivors_after_grace = set(known_owned)
    forced = False
    if survivors_after_grace:
        forced = True
        survivors_after_force, known_owned, verification_attempts = _force_terminate_tree(
            process, known_owned, native_backend,
        )
    else:
        survivors_after_force = set()
        verification_attempts = 1
    if survivors_after_force:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "process_tree_not_quiescent")
    return {
        "termination_sequence": [
            "REQUEST_COOPERATIVE_STOP", "WAIT_60_SECONDS",
            "FORCE_TERMINATE_PROCESS_TREE",
        ],
        "cooperative_stop_request_emitted": emitted,
        "cooperative_outcome": (
            "EXITED_DURING_GRACE" if exited else "ALIVE_AFTER_GRACE"
        ),
        "whole_tree_outcome": (
            "QUIESCENT_AFTER_FORCE" if forced
            else "QUIESCENT_DURING_GRACE"
        ),
        "production_grace_seconds": TIMEOUT_COOPERATIVE_GRACE_SECONDS,
        "force_terminate_process_tree_executed": forced,
        "root_process_exited": process.poll() is not None,
        "root_exited_during_grace": exited and process.poll() is not None,
        "owned_pids": sorted(known_owned),
        "survivor_pids_after_grace": sorted(survivors_after_grace),
        "descendant_survived_grace": any(
            pid != process.pid for pid in survivors_after_grace
        ),
        "survivor_pids_after_force": sorted(survivors_after_force),
        "whole_process_tree_quiescent": not survivors_after_force,
        "post_force_verification_attempts": verification_attempts,
        "survivor_probe_error": survivor_probe_error,
    }


def _timeout_authority_failure_cleanup(
        process: subprocess.Popen,
        ) -> Dict[str, Any]:
    """Bound a failed native timeout probe without claiming quiescence."""
    force_signal_emitted = False
    force_signal_error = "NONE"
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        force_signal_emitted = True
    except ProcessLookupError:
        force_signal_error = "PROCESS_GROUP_ABSENT"
    except OSError as error:
        force_signal_error = f"{type(error).__name__}:{error}"
    try:
        process.wait(timeout=PROCESS_TREE_FORCE_VERIFY_SECONDS)
        root_reaped = True
    except subprocess.TimeoutExpired:
        root_reaped = False
    return {
        "force_process_group_signal_emitted": force_signal_emitted,
        "force_process_group_signal_error": force_signal_error,
        "root_process_reaped": root_reaped,
        "native_survivor_state": "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE",
        "whole_process_tree_quiescent": False,
    }


def _bounded_collect_after_timeout_authority_failure(
        process: subprocess.Popen,
        ) -> tuple[str, bool]:
    """Never let a descendant-held stdout pipe hide a typed timeout STOP."""
    try:
        stdout, _ = process.communicate(timeout=1)
        return stdout or "", True
    except subprocess.TimeoutExpired:
        if process.stdout is not None:
            process.stdout.close()
        return (
            "CONTROLLER_STDOUT_NOT_AVAILABLE_DESCENDANT_PIPE_REMAINED_OPEN\n",
            False,
        )


def terminate_tree(process: subprocess.Popen) -> None:
    """Compatibility entry using the same frozen timeout state machine."""
    exact_timeout_state_machine(process)


def evaluate_resource_hard_gate(
        request: Mapping[str, Any], result: MutableMapping[str, Any],
        process_tree_peak_rss_bytes_value: int,
        sampler_evidence: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    operations = result["operation_integer_values"]
    worker_peak = operations["peak_rss"]
    authoritative_peak = max(worker_peak, process_tree_peak_rss_bytes_value)
    operations["peak_rss"] = authoritative_peak
    result["integer_metrics"]["peak_rss_repetitions"] = authoritative_peak
    if "operation_status" in result:
        result["operation_status"]["peak_rss"] = (
            "MEASURED_WORKER_CONTROLLER_PROCESS_TREE_MAX_INTEGER_BYTES"
        )
    disk_values = {
        name: operations[name] for name in (
            "temporary_physical_disk", "final_physical_disk",
            "publication_high_water",
        )
    }
    if not all(type(value) is int and value >= 0 for value in (
            worker_peak, process_tree_peak_rss_bytes_value, *disk_values.values())):
        raise StopSignal("SB_STOP_MEASURED_RESOURCE", "noninteger_metric")
    violations = []
    if authoritative_peak > request["memory_admission_required_bytes"]:
        violations.append("PEAK_RSS_EXCEEDS_MEMORY_ADMISSION")
    disk_envelope = request["disk_admission_required_bytes"]
    for name, value in disk_values.items():
        if value > disk_envelope:
            violations.append(f"{name.upper()}_EXCEEDS_DISK_ADMISSION")
    if disk_values["publication_high_water"] > request["publication_high_water_bound_bytes"]:
        violations.append("PUBLICATION_HIGH_WATER_EXCEEDS_FROZEN_BOUND")
    evidence = {
        "schema": "SplitAlignerR/ENGINE003StageBMeasuredResourceGate/v1",
        "status": "PASS" if not violations else "STOP",
        "worker_monotonic_peak_rss_bytes": worker_peak,
        "controller_process_tree_peak_rss_bytes": process_tree_peak_rss_bytes_value,
        "authoritative_peak_rss_bytes": authoritative_peak,
        "memory_admission_required_bytes": request["memory_admission_required_bytes"],
        "disk_admission_required_bytes": disk_envelope,
        "publication_high_water_bound_bytes": request["publication_high_water_bound_bytes"],
        "measured_disk_bytes": disk_values,
        "violations": violations,
        "decision_ledger_eligible": not violations,
        "sampler": dict(sampler_evidence or {}),
    }
    result["measured_resource_gate"] = evidence
    return evidence


def _target_timeout_dispositions(runtime: Path, request: Mapping[str, Any]) -> list[Dict[str, Any]]:
    final = Path(request["runtime_target"])
    targets = [final, final.with_name(final.name + ".partial")]
    rows = []
    for target in targets:
        if not target.exists() and not target.is_symlink():
            rows.append({"path": str(target), "decision": "ABSENT_NOTHING_TO_CLEAN"})
            continue
        try:
            target.parent.resolve().relative_to(runtime.resolve())
            inside = True
        except (ValueError, OSError):
            inside = False
        if inside and target.is_dir() and not target.is_symlink():
            rows.append({"path": str(target), "decision": "PRESERVE_TARGET_IF_SAFE_IN_PLACE"})
            continue
        if inside:
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            rows.append({"path": str(target), "decision": "UNSAFE_TARGET_CLEANED"})
        else:
            rows.append({"path": str(target), "decision": "OUTSIDE_RUNTIME_NOT_TOUCHED"})
    return rows


def _timeout_stop_evidence(
        runtime: Path, request: Mapping[str, Any], output_path: Path,
        log_path: Path, stdout: str, termination: Mapping[str, Any],
        sampler: ProcessTreeRssSampler) -> Dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout, encoding="utf-8")
    partial = output_path.with_suffix(".partial.json")
    preserved_path = None
    last_completed = "NONE_RECORDED"
    current_phase = "UNKNOWN"
    if partial.is_file():
        case_scope = "".join(
            value if value.isalnum() or value in "-_" else "_"
            for value in f"{output_path.parent.name}__{output_path.stem}"
        )
        destination = (
            Path(request["evidence_root"]) / "TIMEOUT_PARTIAL_EVIDENCE" /
            case_scope / partial.name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION", "partial_evidence_path_exists",
            )
        shutil.copy2(partial, destination)
        preserved_path = str(destination)
        try:
            value = strict_json_load(destination)
            last_completed = value.get("last_completed_phase", last_completed)
            current_phase = value.get("current_phase", current_phase)
        except Exception:
            current_phase = "PARTIAL_EVIDENCE_UNREADABLE"
    value = {
        "schema": "SplitAlignerR/ENGINE003StageBTimeoutStop/v1",
        "status": "SB_STOP_TIMEOUT",
        "decision_ledger_eligible": False,
        "global_execution_stop": True,
        "no_later_request_launch": True,
        "workload_id": request["workload_id"],
        "candidate_id": request["candidate_id"],
        "schedule_row_sha256": request["schedule_row_sha256"],
        "controller_log_path": str(log_path),
        "controller_log_preserved": True,
        "partial_evidence_status": "PRESERVED" if preserved_path else "ABSENT",
        "partial_evidence_preserved_path": preserved_path or "NOT_AVAILABLE",
        "last_completed_phase": last_completed,
        "current_phase": current_phase,
        "target_dispositions": _target_timeout_dispositions(runtime, request),
        "termination": dict(termination),
        "process_tree_sampler": {
            "maximum_bytes": sampler.maximum_bytes,
            "maximum_root_bytes": sampler.maximum_root_bytes,
            "current_bytes": getattr(sampler, "current_bytes", 0),
            "current_root_bytes": getattr(sampler, "current_root_bytes", 0),
            "sample_count": sampler.sample_count,
            "owned_pids": sorted(sampler.owned_pids),
            "active_owned_pids": sorted(sampler.active_owned_pids),
            "owned_process_identities": [
                {"pid": pid, "identity": identity}
                for pid, identity in sorted(
                    sampler.owned_process_identities.items()
                )
            ],
            "identity_aware_exit_pids": sorted(
                sampler.identity_aware_exit_pids,
            ),
            "error": sampler.error,
            "process_table_mechanism": _process_table_mechanism(),
        },
    }
    write_canonical_json(output_path, value)
    return value


def launch_request(
        repo: Path, runtime: Path, resource_path: Path,
        durability_path: Path, request: Mapping[str, Any], request_path: Path,
        output_path: Path, log_path: Path,
        branch_resource_path: Path | None = None,
        timeout_grace_waiter: Callable[[subprocess.Popen, int], bool] | None = None,
        worker_command: list[str] | None = None,
        watchdog_timeout_seconds: float | None = None,
        sampler_backend_factory: Callable[
            [], DarwinLibprocSamplerBackend | None
        ] | None = None) -> Dict[str, Any]:
    """Validate, start, watch and validate exactly one parameterized worker."""
    if request.get("schema") != LIVE_SCHEMA:
        raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "controller_schema")
    if branch_resource_path is None and request.get("execution_mode") != BOUNDED_MODE:
        raise StopSignal(
            "SB_STOP_RUNTIME_CAPTURE", "live_branch_resource_path_required",
        )
    effective_branch_resource_path = branch_resource_path or resource_path
    resource, resource_raw = load_exact_runtime_resource_capture(
        resource_path, request.get("fresh_resource_capture_sha256"),
    )
    branch_resource, branch_resource_raw = load_exact_runtime_resource_capture(
        effective_branch_resource_path,
        request.get("workload_branch_resource_capture_sha256"),
    )
    durability = strict_json_load(durability_path)
    authority = ExecutionAuthority(
        repo, request["source_commit"], request["source_tree"],
    )
    assets = FrozenAssets(authority)
    guard = prelaunch_guard(
        authority, assets, request, runtime, resource, durability,
        branch_resource,
    )
    if guard["worker_launch_authorized"] is not True:
        raise StopSignal("SB_STOP_ACTIVATION", "controller_launch_guard")
    try:
        sampler_backend = (
            sampler_backend_factory()
            if sampler_backend_factory is not None
            else _sampler_capability_backend()
        )
    except NativeSamplerCapabilityError as error:
        raise StopSignal(
            "SB_STOP_SAMPLER_CAPABILITY", str(error),
        ) from error
    request_raw = canonical_json_bytes(dict(request))
    write_canonical_json(request_path, dict(request))
    command = worker_command or [
        sys.executable, "-B", str(WORKER),
        "--repo-root", str(repo), "--runtime-root", str(runtime),
        "--resource", str(resource_path),
        "--branch-resource", str(effective_branch_resource_path),
        "--durability", str(durability_path),
        "--request", str(request_path), "--output", str(output_path),
    ]
    if request["execution_mode"] != BOUNDED_MODE and worker_command is not None:
        positions = [
            index for index, value in enumerate(command)
            if value == "--branch-resource"
        ]
        if (
            len(positions) != 1
            or positions[0] + 1 >= len(command)
            or command[positions[0] + 1] != str(effective_branch_resource_path)
        ):
            raise StopSignal(
                "SB_STOP_RUNTIME_CAPTURE", "live_worker_command_branch_resource",
            )
    start = time.perf_counter_ns()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        **process_group_options(),
    )
    try:
        sampler = ProcessTreeRssSampler(
            process.pid, native_backend=sampler_backend,
        )
    except NativeSamplerCapabilityError as error:
        # The ABI was validated before Popen.  A root identity failure after
        # launch still fails closed and owns cleanup of the just-started tree.
        _stop_worker_after_sampler_initialization_failure(process)
        raise StopSignal(
            "SB_STOP_SAMPLER_CAPABILITY", str(error),
        ) from error
    sampler.start()
    try:
        stdout, _ = process.communicate(timeout=(
            request["timeout_seconds"]
            if watchdog_timeout_seconds is None else watchdog_timeout_seconds
        ))
    except subprocess.TimeoutExpired as error:
        try:
            termination = exact_timeout_state_machine(
                process, timeout_grace_waiter,
                sampler.owned_identity_snapshot,
                sampler.native_backend,
            )
        except StopSignal as termination_error:
            cleanup = _timeout_authority_failure_cleanup(process)
            stdout, stdout_complete = (
                _bounded_collect_after_timeout_authority_failure(process)
            )
            sampler.stop()
            failure_termination = {
                "termination_sequence": [
                    "REQUEST_COOPERATIVE_STOP", "WAIT_60_SECONDS",
                    "NATIVE_SURVIVOR_AUTHORITY_FAILED",
                    "BEST_EFFORT_FORCE_PROCESS_GROUP",
                ],
                "status": termination_error.stop_id,
                "detail": termination_error.detail,
                "decision_ledger_eligible": False,
                "controller_stdout_complete": stdout_complete,
                **cleanup,
            }
            _timeout_stop_evidence(
                runtime, request, output_path, log_path, stdout or "",
                failure_termination, sampler,
            )
            raise termination_error from error
        stdout, _ = process.communicate()
        sampler.stop()
        _timeout_stop_evidence(
            runtime, request, output_path, log_path, stdout or "",
            termination, sampler,
        )
        raise StopSignal("SB_STOP_TIMEOUT", "parameterized_worker") from error
    finally:
        if sampler._thread.is_alive():
            sampler.stop()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout, encoding="utf-8")
    sampler_path, sampler_diagnostic = _write_sampler_diagnostic(
        output_path, sampler, process.returncode,
    )
    sampler_diagnostic_sha256 = hashlib.sha256(
        canonical_json_bytes(sampler_diagnostic)
    ).hexdigest()
    if process.returncode != 0:
        failure_path = _write_worker_failure_evidence(
            request, request_path, request_raw,
            resource_path, resource_raw,
            effective_branch_resource_path, branch_resource_raw,
            output_path, log_path, process.returncode,
            sampler_path, sampler_diagnostic,
        )
        raise StopSignal(
            "SB_STOP_VALIDATION",
            f"worker_exit={process.returncode};evidence={failure_path}",
        )
    if (
        sampler.error != "NONE" or sampler.sample_count < 1
        or sampler._thread.is_alive()
    ):
        raise StopSignal("SB_STOP_MEASURED_RESOURCE", "process_tree_sampler")
    result = strict_json_load(output_path)
    expected_status = (
        "BOUNDED_PARAMETERIZED_REAL_WORKER_PASS"
        if request["execution_mode"] == BOUNDED_MODE
        else "STAGEB_AUTHORIZED_PARAMETERIZED_REAL_WORKER_PASS"
    )
    if result.get("schema") != WORKER_RESULT_SCHEMA or result.get("status") != expected_status:
        raise StopSignal("SB_STOP_VALIDATION", "worker_result_identity")
    validate_worker_result_identity(request, result)
    gate = evaluate_resource_hard_gate(
        request, result, sampler.maximum_bytes,
        {
            "sample_count": sampler.sample_count,
            "maximum_root_bytes": sampler.maximum_root_bytes,
            "owned_pids": sorted(sampler.owned_pids),
            "error": sampler.error,
            "interval_nanoseconds": int(
                PROCESS_TREE_RSS_SAMPLE_INTERVAL_SECONDS * 1_000_000_000
            ),
        },
    )
    if gate["status"] != "PASS":
        raw_worker_path = output_path.with_suffix(".worker-pre-gate.json")
        shutil.copy2(output_path, raw_worker_path)
        stop = {
            "schema": "SplitAlignerR/ENGINE003StageBMeasuredResourceStop/v1",
            "status": "SB_STOP_MEASURED_RESOURCE",
            "decision_ledger_eligible": False,
            "global_execution_stop": True,
            "no_later_request_launch": True,
            "workload_id": request["workload_id"],
            "candidate_id": request["candidate_id"],
            "schedule_row_sha256": request["schedule_row_sha256"],
            "worker_pre_gate_result_path": str(raw_worker_path),
            "resource_gate": gate,
        }
        write_canonical_json(output_path, stop)
        raise StopSignal(
            "SB_STOP_MEASURED_RESOURCE", ",".join(gate["violations"]),
        )
    if result.get("cleanup_result") != "PASS_TARGET_REMOVED" or Path(request["runtime_target"]).exists():
        raise StopSignal("SB_STOP_CLEANUP", "worker_target_survived")
    result["controller_watchdog_elapsed_ns"] = max(
        1, time.perf_counter_ns() - start,
    )
    result["controller_prelaunch_status"] = guard["status"]
    result["process_tree_sampler_diagnostic_path"] = str(sampler_path)
    result["process_tree_sampler_diagnostic_sha256"] = sampler_diagnostic_sha256
    write_canonical_json(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--resource", required=True, type=Path)
    parser.add_argument("--branch-resource", required=True, type=Path)
    parser.add_argument("--durability", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    args = parser.parse_args()
    request = strict_json_load(args.request)
    result = launch_request(
        args.repo_root.resolve(), args.runtime_root.resolve(),
        Path(os.path.abspath(args.resource)), args.durability.resolve(), request,
        args.request.resolve(), args.output.resolve(), args.log.resolve(),
        Path(os.path.abspath(args.branch_resource)),
    )
    write_canonical_json(args.output, result)
    print(
        f"{result['status']} CANDIDATE={result['candidate_id']} "
        f"MODE={result['execution_mode']}"
    )


if __name__ == "__main__":
    main()
