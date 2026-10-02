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
import stage_b_dispatch_journal as journal_protocol  # noqa: E402


WORKER = HERE / "stage_b_worker.py"
TIMEOUT_COOPERATIVE_GRACE_SECONDS = 60
PROCESS_TREE_RSS_SAMPLE_INTERVAL_SECONDS = 0.01
# NRP-2: finite COOPERATIVE lock wait for pre-effect/exceptional
# RunContext.close() (no cleanup deadline exists before an effect).  Bounds
# only the provider's table-lock acquisition; provider/Python/native I/O is
# not preemptible.  An expired wait leaves custody unresolved (fail closed).
PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS = 1.0
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
    """One shared exact-identity authority for RSS and timeout.

    A backend declaring OWNED_TREE_PROTOCOL classifies readable exited rows
    by identity/PGID itself; Darwin keeps its unchanged algorithm."""
    if getattr(type(backend), "OWNED_TREE_PROTOCOL", None) is not None:
        return backend.live_owned_tree(known_identities)
    return DarwinLibprocSamplerBackend.live_owned_tree(
        backend, known_identities,
    )


class GroupSignalRefused(OSError):
    """A POSIX signal was refused before any kill(2); never success."""


# Cleanup plumbing budgets (not scientific/cadence values).  One
# CleanupDeadline spans every cleanup phase; sub-steps take min(cap, remaining)
# and never receive a fresh full budget.
FAILURE_CLEANUP_TOTAL_SECONDS = 12.0
INITIALIZATION_FAILURE_TERM_WAIT_SECONDS = 5.0
OUTPUT_COLLECTION_SECONDS = 1.0
SAMPLER_STOP_JOIN_SECONDS = 5.0
POST_GRACE_BUDGET_SECONDS = (
    PROCESS_TREE_COMMAND_TIMEOUT_SECONDS + PROCESS_TREE_FORCE_VERIFY_SECONDS
)
TIMEOUT_CLEANUP_TOTAL_SECONDS = (
    TIMEOUT_COOPERATIVE_GRACE_SECONDS + POST_GRACE_BUDGET_SECONDS
    + FAILURE_CLEANUP_TOTAL_SECONDS
)


class CleanupDeadline:
    """One total cleanup deadline; created before the first census."""

    def __init__(self, clock: Callable[[], float], total_seconds: float,
                 label: str) -> None:
        self.clock = clock
        self.label = label
        self.total_seconds = total_seconds
        self.started = clock()
        self.deadline = self.started + total_seconds
        self.overruns: list[Dict[str, Any]] = []

    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def budget(self, cap: float) -> float:
        return min(cap, self.remaining())

    def expired(self) -> bool:
        return self.clock() >= self.deadline

    def note_overrun(self, phase: str) -> bool:
        """An operation cannot be preempted; an overrun is recorded, not hidden."""
        now = self.clock()
        if now <= self.deadline:
            return False
        self.overruns.append({
            "phase": phase,
            "overrun_nanoseconds": int((now - self.deadline) * 1_000_000_000),
        })
        return True

    def report(self) -> Dict[str, Any]:
        # Canonical evidence JSON is integer-only: nanoseconds.
        return {
            "label": self.label,
            "total_nanoseconds": int(self.total_seconds * 1_000_000_000),
            "elapsed_nanoseconds": int(
                (self.clock() - self.started) * 1_000_000_000
            ),
            "exhausted": self.expired(),
            "overruns": list(self.overruns),
        }


class DispatchLatch:
    """Blocks every later request while an earlier run is unresolved."""

    def __init__(self) -> None:
        self.records: list[Dict[str, Any]] = []

    @property
    def blocked(self) -> bool:
        return bool(self.records)

    def block(self, run_id: Any, reasons: list[str]) -> None:
        self.records.append({"run_id": run_id, "reasons": list(reasons)})


DISPATCH_LATCH = DispatchLatch()


class NoTerminationAuthority:
    """Default for every non-Darwin POSIX platform: no signal authority."""

    authority_id = "NONE_UNSUPPORTED_PLATFORM"

    def acquire_root(self, process: Any, context: "RunContext") -> Any:
        raise GroupSignalRefused(
            errno.EPERM, "UNSUPPORTED_PLATFORM_NO_ROOT_AUTHORITY",
        )

    def group_signal(self, pgid: int, signum: int, context: "RunContext",
                     owned: Any) -> None:
        raise GroupSignalRefused(
            errno.EPERM, "UNSUPPORTED_PLATFORM_NO_GROUP_SIGNAL_FALLBACK",
        )


class _DarwinGroupRootAuthority:
    covers_process_group = True

    def __init__(self, pgid: int) -> None:
        self.pgid = pgid

    def signal(self, signum: int) -> None:
        os.killpg(self.pgid, signum)

    def close(self) -> str:
        return "NOT_APPLICABLE_NUMERIC_DARWIN_GROUP"


class DarwinKillpgAuthority:
    """Unchanged Darwin semantics: numeric killpg of the dedicated group."""

    authority_id = "DARWIN_KILLPG_DEDICATED_GROUP"

    def acquire_root(self, process: Any, context: "RunContext") -> Any:
        return _DarwinGroupRootAuthority(process.pid)

    def group_signal(self, pgid: int, signum: int, context: "RunContext",
                     owned: Any) -> None:
        os.killpg(pgid, signum)


CLOSED_CUSTODY_OUTCOMES = frozenset((
    "CLOSED", "ALREADY_CLOSED", "NO_ROOT_AUTHORITY",
    "NOT_APPLICABLE_NUMERIC_DARWIN_GROUP",
))


class RunContext:
    """Fixed per-run references, created once per request.

    Every request/waiter/timeout/cleanup call receives this object; nothing
    below the request re-reads a module global to find a backend or a signal
    provider.  The termination provider, backend, run id, generation, clock,
    dispatch latch and evidence list are bound here and never replaced.
    """

    def __init__(
            self, *, run_id: Any, generation: int, native_backend: Any,
            termination: Any, clock: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], None] = time.sleep,
            dispatch_latch: DispatchLatch | None = None,
            evidence: list | None = None) -> None:
        if not (callable(getattr(termination, "group_signal", None))
                and callable(getattr(termination, "acquire_root", None))):
            raise TypeError("termination provider requires acquire_root/group_signal")
        self.run_id = run_id
        self.generation = generation
        self.native_backend = native_backend
        self.termination = termination
        self.clock = clock
        self.sleep = sleep
        self.dispatch_latch = (
            DISPATCH_LATCH if dispatch_latch is None else dispatch_latch
        )
        self.evidence = [] if evidence is None else evidence
        self.deadline: CleanupDeadline | None = None
        self.root_authority: Any = None
        self.root_authority_state = "NOT_ACQUIRED"
        self.admitted = False
        self.teardown_started = False
        self.custody: Dict[str, Any] | None = None
        self.closed = False
        # DEV007_FIX005: the durable dispatch ticket (reservation sha256)
        # this context executes; bound once, before spawn.
        self.dispatch_ticket: str | None = None
        # NRP-2 FIX001: outcome of the one pre-effect close attempt
        self.pre_effect_close_outcome: str | None = None

    @property
    def has_signal_authority(self) -> bool:
        return not isinstance(self.termination, NoTerminationAuthority)

    def record(self, kind: str, **details: Any) -> None:
        self.evidence.append({
            "run_id": self.run_id, "generation": self.generation,
            "kind": kind, **details,
        })

    def _require_open(self) -> None:
        if self.closed:
            raise GroupSignalRefused(errno.EPERM, "RUN_CONTEXT_CLOSED")
        if self.teardown_started:
            raise GroupSignalRefused(errno.EPERM, "RUN_CONTEXT_TEARDOWN_STARTED")

    def admit(self) -> None:
        """Single-use admission, before any spawn: a closed, torn-down,
        already-admitted or already-used context is refused, and so is one
        its termination provider refuses (bound elsewhere, invalidated or
        holding capabilities)."""
        self._require_open()
        if (self.admitted or self.root_authority is not None
                or self.root_authority_state != "NOT_ACQUIRED"
                or self.deadline is not None or self.custody is not None):
            raise GroupSignalRefused(errno.EPERM, "RUN_CONTEXT_NOT_FRESH")
        preflight = getattr(self.termination, "preflight", None)
        if preflight is not None:
            preflight(self)
        self.admitted = True
        self.record("ADMITTED")

    def start_deadline(self, total_seconds: float, label: str) -> CleanupDeadline:
        if self.deadline is None:
            self.deadline = CleanupDeadline(self.clock, total_seconds, label)
            self.record(
                "DEADLINE_START", label=label,
                total_nanoseconds=int(total_seconds * 1_000_000_000),
            )
        return self.deadline

    def attach_root(self, process: Any) -> None:
        """Acquire root cleanup authority right after spawn, independent of
        any sampler; failure is recorded, never replaced by a fallback."""
        self._require_open()
        if self.root_authority_state != "NOT_ACQUIRED":
            raise GroupSignalRefused(errno.EPERM, "ROOT_ALREADY_ATTACHED")
        try:
            if not self.admitted:
                self.admit()
            self.root_authority = self.termination.acquire_root(process, self)
            self.root_authority_state = "ACQUIRED"
        except OSError as error:
            self.root_authority = None
            self.root_authority_state = (
                f"UNAVAILABLE:{error.strerror or error}"
            )
        self.record("ROOT_AUTHORITY", state=self.root_authority_state)

    def root_signal(self, signum: int) -> None:
        self._require_open()
        if self.root_authority is None:
            raise GroupSignalRefused(
                errno.EPERM,
                "ROOT_CLEANUP_AUTHORITY_" + self.root_authority_state,
            )
        self.record("ROOT_SIGNAL_REQUEST", signal=int(signum))
        self.root_authority.signal(signum)

    def group_signal(self, pgid: int, signum: int, owned: Any = None) -> None:
        self._require_open()
        self.record("GROUP_SIGNAL_REQUEST", pgid=pgid, signal=int(signum))
        self.termination.group_signal(pgid, signum, self, owned)

    def close(self, lock_timeout: float | None = None) -> str:
        """Idempotent teardown of the run's complete custody.

        A provider with a capability table tears down every capability it
        owns (root and members, recorded independently); `closed` becomes
        true only when every one reports CLOSED.  A deferred (lease held),
        in-progress or failed provider close leaves the context open and
        the capabilities retained; calling close again re-evaluates.
        """
        if self.closed:
            return "ALREADY_CLOSED"
        self.teardown_started = True
        teardown = getattr(self.termination, "teardown", None)
        if teardown is not None:
            try:
                custody = teardown(self, lock_timeout)
            except Exception as error:
                custody = {
                    "resolved": False,
                    "outcome": f"TEARDOWN_FAILED:{type(error).__name__}:{error}",
                }
            outcome = "CLOSED" if custody["resolved"] else (
                "CUSTODY_UNRESOLVED:" + str(custody.get("outcome", "UNKNOWN"))
            )
        else:
            outcome = (
                "NO_ROOT_AUTHORITY" if self.root_authority is None
                else self.root_authority.close()
            )
            custody = {
                "resolved": outcome in CLOSED_CUSTODY_OUTCOMES,
                "outcome": outcome, "root": outcome,
                "members": "NO_MEMBER_CAPABILITIES_IN_PROVIDER",
            }
        self.custody = custody
        if custody["resolved"]:
            self.closed = True
        self.record("CONTEXT_CLOSE", outcome=outcome, custody=custody)
        return outcome


def default_run_context(
        native_backend: Any, run_id: Any = "STAGEB_REQUEST",
        ) -> RunContext:
    """Darwin keeps killpg; every other POSIX platform has no authority."""
    termination = (
        DarwinKillpgAuthority() if sys.platform == "darwin" and os.name != "nt"
        else NoTerminationAuthority()
    )
    return RunContext(
        run_id=run_id, generation=1, native_backend=native_backend,
        termination=termination,
    )


def _posix_group_signal(
        pgid: int, signum: int, context: RunContext | None,
        owned: Any = None,
        ) -> None:
    """The only POSIX process-group signal path: the run's own provider."""
    if context is None:
        raise GroupSignalRefused(errno.EPERM, "RUN_CONTEXT_REQUIRED")
    context.group_signal(pgid, signum, owned)


def _sampler_capability_backend() -> DarwinLibprocSamplerBackend | None:
    if os.name == "nt":
        return None
    if sys.platform == "darwin":
        return DarwinLibprocSamplerBackend()
    raise NativeSamplerCapabilityError("UNSUPPORTED_PLATFORM_NO_FALLBACK")


def _stop_worker_after_sampler_initialization_failure(
        process: subprocess.Popen, context: RunContext,
        original_failure: str = "SAMPLER_INITIALIZATION_FAILED",
        ) -> Dict[str, Any]:
    """Own the just-created root through the run's independent root authority."""
    return _bounded_failure_cleanup(
        process, context, original_failure=original_failure,
        cooperative_first=True,
    )


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
            native_backend: DarwinLibprocSamplerBackend | None = None,
            clock_ns: Callable[[], int] = time.monotonic_ns):
        self.root_pid = root_pid
        self._clock_ns = clock_ns
        self.tick_diagnostics: list[Dict[str, Any]] = []
        self.tick_diagnostics_dropped = 0
        self._last_tick_end_ns: int | None = None
        self._tick_phase: Dict[str, int] = {}
        self.stop_requested_ns: int | None = None
        self.stop_state = "NOT_REQUESTED"
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
        self._tick_phase["census_end_ns"] = self._clock_ns()
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
                    or getattr(
                        type(self.native_backend),
                        "RSS_BINDS_IDENTITY_AND_GROUP", False,
                    ) is True
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
                revalidate = getattr(
                    self.native_backend, "revalidate_expected_exit", None,
                )
                if revalidate is not None:
                    # Identity and PGID are checked on any readable row
                    # before a Z/X state may count as exit (F3).
                    revalidate(pid, expected_identity, self.native_worker_pgid)
                    self.identity_aware_exit_pids.add(pid)
                    sampled_current.pop(pid, None)
                    continue
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
        self._tick_phase["rss_end_ns"] = self._clock_ns()
        with self._lock:
            self._tick_phase["lock_acquired_ns"] = self._clock_ns()
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

    TICK_DIAGNOSTIC_LIMIT = 4096

    def _timed_sample(self, final: bool = False) -> None:
        """One unchanged sample plus observed timing; never a catch-up tick."""
        start = self._clock_ns()
        scheduled = (
            None if self._last_tick_end_ns is None
            else self._last_tick_end_ns + int(self.interval * 1_000_000_000)
        )
        self._tick_phase = {}
        row: Dict[str, Any] = {
            "scheduled_ns": scheduled, "start_ns": start, "final": final,
            "start_lag_ns": None if scheduled is None else start - scheduled,
        }
        try:
            self._sample()
        finally:
            end = self._clock_ns()
            self._last_tick_end_ns = end
            census_end = self._tick_phase.get("census_end_ns")
            rss_end = self._tick_phase.get("rss_end_ns")
            locked = self._tick_phase.get("lock_acquired_ns")
            row.update({
                "end_ns": end, "duration_ns": end - start,
                "overrun_ns": max(
                    0, end - start - int(self.interval * 1_000_000_000),
                ),
                "census_ns": None if census_end is None else census_end - start,
                "rss_ns": (
                    None if rss_end is None or census_end is None
                    else rss_end - census_end
                ),
                "lock_wait_ns": (
                    None if locked is None or rss_end is None
                    else locked - rss_end
                ),
                "completed": self._tick_phase.get("lock_acquired_ns") is not None,
            })
            if len(self.tick_diagnostics) < self.TICK_DIAGNOSTIC_LIMIT:
                self.tick_diagnostics.append(row)
            else:
                self.tick_diagnostics_dropped += 1

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._timed_sample()
                self._stop.wait(self.interval)
            self._timed_sample(final=True)
        except Exception as error:  # evidence records a fail-closed sampler error
            self.error = f"{type(error).__name__}:{error}"

    def start(self) -> None:
        self._thread.start()

    def request_stop(self) -> None:
        if self.stop_requested_ns is None:
            self.stop_requested_ns = self._clock_ns()
            self.stop_state = "REQUESTED"
        self._stop.set()

    def stop_bounded(self, timeout: float) -> Dict[str, Any]:
        """join(timeout) proves nothing; only a dead thread is 'STOPPED'."""
        self.request_stop()
        if timeout > 0:
            self._thread.join(timeout=timeout)
        alive = self._thread.is_alive()
        self.stop_state = (
            "RUNNING_AFTER_BOUNDED_JOIN_UNRESOLVED" if alive else "STOPPED"
        )
        return {
            "stop_requested_ns": self.stop_requested_ns,
            "join_timeout_nanoseconds": int(max(0.0, timeout) * 1_000_000_000),
            "observed_ns": self._clock_ns(),
            "thread_alive_after_join": alive,
            "state": self.stop_state,
        }

    def stop(self) -> None:
        self.stop_bounded(SAMPLER_STOP_JOIN_SECONDS)

    def cadence_report(self) -> Dict[str, Any]:
        """Observed timing only; no claim that the configured interval held."""
        completed = [row for row in self.tick_diagnostics if row["completed"]]
        return {
            "configured_interval_nanoseconds": int(
                self.interval * 1_000_000_000
            ),
            "tick_count_recorded": len(self.tick_diagnostics),
            "tick_count_dropped": self.tick_diagnostics_dropped,
            "completed_tick_count": len(completed),
            "maximum_duration_ns": max(
                (row["duration_ns"] for row in self.tick_diagnostics), default=0,
            ),
            "overrun_tick_count": sum(
                1 for row in self.tick_diagnostics if row["overrun_ns"] > 0
            ),
            "stop_state": self.stop_state,
            "cadence_claim": "OBSERVED_ONLY_NOT_A_10MS_GUARANTEE",
            "ticks": list(self.tick_diagnostics),
        }

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
        "cadence_diagnostics": (
            sampler.cadence_report()
            if callable(getattr(sampler, "cadence_report", None))
            else "NOT_AVAILABLE_INJECTED_SAMPLER"
        ),
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


def _cooperative_stop(
        process: subprocess.Popen, context: RunContext | None = None,
        owned: Any = None,
        ) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            _posix_group_signal(process.pid, signal.SIGTERM, context, owned)
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
        context: RunContext | None = None,
        ) -> tuple[Set[int], Dict[int, str]]:
    """Refresh ownership and return all live root/group/known descendants."""
    context_authority = (
        context is not None and os.name != "nt" and sys.platform != "darwin"
        and context.has_signal_authority
    )
    if context_authority and native_backend is None:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "run_context_requires_bound_backend",
        )
    if sys.platform == "darwin" or context_authority:
        del probe_timeout_seconds
        deadline = context.deadline if context is not None else None
        if deadline is not None and deadline.remaining() <= 0:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                "cleanup_deadline_exhausted_before_census",
            )
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
        if deadline is not None and deadline.note_overrun("owned_tree_census"):
            # A native census cannot be preempted; its late answer is not
            # accepted as bounded evidence.
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                "census_overran_cleanup_deadline",
            )
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
        context: RunContext | None = None,
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
                process, owned, remaining, native_backend, context,
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
                    ), native_backend, context,
                )
                if pid in still_live:
                    raise StopSignal(
                        "SB_STOP_TIMEOUT_TERMINATION",
                        f"taskkill_failed:{pid}:{completed.returncode}",
                    )
    else:
        try:
            _posix_group_signal(process.pid, signal.SIGKILL, context, owned)
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
        context: RunContext | None = None,
        ) -> tuple[Set[int], Dict[int, str], int]:
    clock = context.clock if context is not None else time.monotonic
    sleep = context.sleep if context is not None else time.sleep
    if isinstance(previously_owned, Mapping):
        owned = dict(previously_owned)
    else:
        owned = {pid: "" for pid in (previously_owned or ())}
    owned.setdefault(process.pid, "")
    # The force deadline starts before the first survivor census and never
    # extends past the run's total cleanup deadline.
    deadline = clock() + PROCESS_TREE_FORCE_VERIFY_SECONDS
    if context is not None and context.deadline is not None:
        deadline = min(deadline, context.deadline.deadline)
    try:
        live, owned = _owned_tree_survivors(
            process, owned, native_backend=native_backend, context=context,
        )
    except StopSignal:
        if os.name != "nt":
            # Darwin and a run context with authority have exact survivor
            # authority; nothing falls through to a blind group force.
            raise
        # Enumeration failure must make termination more conservative, not
        # suppress it.  Windows still has the sampler's monotonic PIDs.
        live = set(owned)
    owned = _force_live_processes(
        process, live, owned,
        min(PROCESS_TREE_COMMAND_TIMEOUT_SECONDS, max(0.0, deadline - clock())),
        native_backend, context,
    )
    remaining = deadline - clock()
    if remaining <= 0:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "force_verify_deadline")
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        raise StopSignal("SB_STOP_TIMEOUT_TERMINATION", "process_tree_survived_force") from error
    verification_attempts = 1
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            survivors = set(owned)
            break
        survivors, owned = _owned_tree_survivors(
            process, owned,
            min(PROCESS_TREE_COMMAND_TIMEOUT_SECONDS, remaining),
            native_backend, context,
        )
        if not survivors:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        owned = _force_live_processes(
            process, survivors, owned,
            min(PROCESS_TREE_COMMAND_TIMEOUT_SECONDS, remaining),
            native_backend, context,
        )
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(0.02, remaining))
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
        run_context: RunContext | None = None,
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

    if run_context is not None:
        if (
            native_backend is not None
            and native_backend is not run_context.native_backend
        ):
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION", "run_context_backend_mismatch",
            )
        native_backend = run_context.native_backend
    context_authority = (
        run_context is not None and os.name != "nt"
        and sys.platform != "darwin" and run_context.has_signal_authority
    )
    if os.name != "nt" and sys.platform != "darwin" and not context_authority:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "unsupported_platform_no_termination_authority",
        )
    if context_authority and native_backend is None:
        raise StopSignal(
            "SB_STOP_TIMEOUT_TERMINATION",
            "run_context_requires_bound_backend",
        )
    if sys.platform == "darwin" and native_backend is None:
        try:
            native_backend = DarwinLibprocSamplerBackend()
        except NativeSamplerCapabilityError as error:
            raise StopSignal(
                "SB_STOP_TIMEOUT_TERMINATION",
                f"native_survivor_authority:{type(error).__name__}:{error}",
            ) from error
    if run_context is None:
        run_context = default_run_context(native_backend)
    deadline = run_context.start_deadline(
        TIMEOUT_CLEANUP_TOTAL_SECONDS, "TIMEOUT",
    )
    pre_stop_owned = owned_process_provider() if owned_process_provider else {}
    if (sys.platform == "darwin" or context_authority) and not pre_stop_owned:
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
    emitted = _cooperative_stop(process, run_context, pre_stop_owned)
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
            context=run_context,
        )
    except StopSignal as error:
        if os.name != "nt":
            raise
        survivor_probe_error = str(error)
        known_owned.setdefault(process.pid, "")
        survivors_after_grace = set(known_owned)
    forced = False
    if survivors_after_grace:
        forced = True
        survivors_after_force, known_owned, verification_attempts = _force_terminate_tree(
            process, known_owned, native_backend, run_context,
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
        "bounded_cleanup_deadline": deadline.report(),
    }


def _text_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class CumulativeOutputCollector:
    """The one output-collection contract for a run's stdout.

    Popen.communicate() output is cumulative from spawn: every
    TimeoutExpired.output and the final return value already contain all
    earlier bytes.  So the latest snapshot supersedes earlier ones and is
    never concatenated with them; content is never compared or de-duplicated
    (a genuine repetition stays).  A collector failure keeps the last
    snapshot and marks output incomplete.  A later snapshot that does not
    extend the earlier one violates the contract: it is reported and the
    superseded text is kept in the report instead of being dropped.

    The same rule applies to a snapshot carried on a collector exception
    (`error.output`, as TimeoutExpired carries it): it supersedes the last
    one, but output stays incomplete.  An exception without `output` keeps
    the last snapshot.

    Text boundary: bytes snapshots are decoded UTF-8 with errors=replace,
    so the kept text is not byte-exact when `lossy_decode` is true; each
    bytes snapshot records its raw length and sha256.  Every log write is
    recorded (`mark_persisted`); a later snapshot that differs from the
    persisted log is flagged, never silently diverging from it.
    """

    TEXT_NORMALIZATION = "BYTES_DECODED_UTF8_ERRORS_REPLACE;STR_KEPT_AS_IS"

    def __init__(self) -> None:
        self.text = ""
        self.complete = False
        self.snapshots: list[Dict[str, Any]] = []
        self.inconsistent: list[Dict[str, Any]] = []
        self.persisted: list[Dict[str, Any]] = []

    def _take(self, value: Any, phase: str, kind: str,
              **extra: Any) -> Dict[str, Any]:
        if value is None:           # no snapshot carried: keep the last one
            row = {"phase": phase, "kind": kind + ":NONE",
                   "chars": len(self.text), **extra}
            self.snapshots.append(row)
            return row
        text = _text_output(value)
        if not text.startswith(self.text):
            self.inconsistent.append({
                "phase": phase, "superseded_text": self.text,
                "superseded_chars": len(self.text),
            })
        self.text = text
        row = {"phase": phase, "kind": kind, "chars": len(text), **extra}
        if isinstance(value, bytes):
            try:
                value.decode("utf-8")
                lossy = False
            except UnicodeDecodeError:
                lossy = True
            row.update(source_type="bytes", raw_bytes=len(value),
                       raw_sha256=hashlib.sha256(value).hexdigest(),
                       lossy_decode=lossy)
        else:
            row["source_type"] = type(value).__name__
        if self.persisted and self.persisted[-1]["text_sha256"] != _sha256_text(text):
            row["differs_from_persisted_log"] = self.persisted[-1]["phase"]
        self.snapshots.append(row)
        return row

    def timeout_snapshot(self, value: Any, phase: str) -> None:
        self._take(value, phase, "TIMEOUT_EXPIRED_CUMULATIVE")

    def final(self, value: Any, phase: str) -> None:
        self._take(value, phase, "COMMUNICATE_RETURNED_CUMULATIVE")
        self.complete = True

    def failure(self, error: BaseException, phase: str) -> None:
        detail = f"{type(error).__name__}:{error}"
        value = getattr(error, "output", None)
        if value is None:
            self.snapshots.append({
                "phase": phase, "kind": "COLLECTOR_FAILED_SNAPSHOT_KEPT",
                "error": detail, "chars": len(self.text),
            })
        else:
            self._take(value, phase, "COLLECTOR_FAILED_CUMULATIVE", error=detail)
        self.complete = False

    def mark_persisted(self, phase: str, text: str) -> None:
        """Record exactly what a log write persisted."""
        self.persisted.append({"phase": phase, "chars": len(text),
                               "text_sha256": _sha256_text(text)})

    def report(self) -> Dict[str, Any]:
        return {
            "contract": "POPEN_COMMUNICATE_CUMULATIVE_LATEST_SNAPSHOT",
            "text_normalization": self.TEXT_NORMALIZATION,
            "complete": self.complete, "chars": len(self.text),
            "snapshots": list(self.snapshots),
            "cumulative_contract_consistent": not self.inconsistent,
            "inconsistent_snapshots": list(self.inconsistent),
            "persisted_logs": list(self.persisted),
            "persisted_log_matches_latest": (
                None if not self.persisted
                else self.persisted[-1]["text_sha256"] == _sha256_text(self.text)
            ),
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _write_log(log_path: Path, text: str,
               collector: CumulativeOutputCollector | None, phase: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text, encoding="utf-8")
    if collector is not None:
        collector.mark_persisted(phase, text)


def _bounded_collect(
        process: subprocess.Popen, budget: float,
        collector: CumulativeOutputCollector | None = None,
        phase: str = "BOUNDED_COLLECT",
        ) -> tuple[str, Dict[str, Any]]:
    """Collect stdout within `budget`; pipe EOF is independent of root reap.

    A timeout or collector failure keeps the latest cumulative snapshot and
    reports output_complete=False; nothing is invented or duplicated.
    """
    collector = collector or CumulativeOutputCollector()
    try:
        stdout, _ = process.communicate(timeout=max(0.0, budget))
        collector.final(stdout, phase)
        return collector.text, {
            "output_complete": True, "collector_state": "PIPE_EOF_OBSERVED",
            "partial_output_chars": len(collector.text),
            "controller_stdout_close": "CLOSED_BY_COMMUNICATE",
            "output_contract": collector.report(),
        }
    except subprocess.TimeoutExpired as error:
        collector.timeout_snapshot(error.output, phase)
        state = "PIPE_EOF_NOT_OBSERVED_WITHIN_DEADLINE"
    except Exception as error:  # collector failure is evidence, not success
        collector.failure(error, phase)
        state = f"COLLECTOR_FAILED:{type(error).__name__}:{error}"
    partial = collector.text
    close_state = "NOT_OPEN"
    if process.stdout is not None:
        try:
            process.stdout.close()
            close_state = "CLOSED_BY_CONTROLLER"
        except Exception as error:
            close_state = f"CLOSE_FAILED:{type(error).__name__}"
    return partial, {
        "output_complete": False, "collector_state": state,
        "partial_output_chars": len(partial),
        "controller_stdout_close": close_state,
        "output_contract": collector.report(),
    }


def _stop_sampler_bounded(sampler: Any, budget: float) -> Dict[str, Any]:
    """One bounded stop attempt; only a thread seen dead counts as stopped."""
    if sampler is None:
        return {"state": "NOT_CREATED"}
    try:
        return sampler.stop_bounded(budget)
    except Exception as error:
        failure = f"{type(error).__name__}:{error}"
    try:
        alive = sampler._thread.is_alive()
    except Exception as error:
        return {"state": f"STOP_FAILED_LIVENESS_UNKNOWN:{failure}",
                "liveness_error": f"{type(error).__name__}:{error}"}
    return {
        "state": "STOPPED" if not alive else f"STOP_FAILED_THREAD_ALIVE:{failure}",
        "stop_error": failure, "thread_alive_after_join": alive,
    }


def resolve_known_descendants(
        process: Any, context: RunContext,
        owned: Mapping[int, str] | None,
        ) -> Dict[str, Any]:
    """D1: explicit ownership resolution of every KNOWN non-root identity.

    Root reaped, pipe EOF, sampler STOPPED and closed descriptors are
    separate facts; none of them proves a descendant exited.  Each known
    descendant is classified by the bound backend's identity-exact owned-tree
    census (readable Z/X rows are checked for identity/PGID first):
    EXITED_IDENTITY_VERIFIED resolves it; LIVE or anything uncertain does
    not.  Numeric PID absence is never used.  Discovery of unknown
    descendants is NOT claimed (descendant_discovery below)."""
    known = dict(owned or {})
    root_pid = getattr(process, "pid", None)
    descendants = sorted(pid for pid in known if pid != root_pid)
    result: Dict[str, Any] = {
        "known_descendants": descendants, "classification": {},
        "descendant_discovery": "KNOWN_IDENTITIES_ONLY_NOT_COMPLETE",
        "resolved": True, "live": [], "uncertain": [],
    }
    if not descendants:
        return result
    backend = getattr(context, "native_backend", None)
    try:
        if backend is None:
            raise RuntimeError("NO_BOUND_BACKEND")
        parsed = {}
        for pid, text in known.items():
            values = tuple(int(v) for v in str(text).split(":"))
            if len(values) != 3 or values[0] != pid:
                raise ValueError(f"identity mismatch:{pid}")
            parsed[pid] = values
        live, absent = _native_live_owned_tree(backend, parsed)
        for pid in descendants:
            if pid in live:
                result["classification"][str(pid)] = "LIVE"
                result["live"].append(pid)
            elif pid in absent:
                result["classification"][str(pid)] = "EXITED_IDENTITY_VERIFIED"
            else:
                result["classification"][str(pid)] = "UNCLASSIFIED"
                result["uncertain"].append(pid)
    except Exception as error:
        result["error"] = f"{type(error).__name__}:{error}"
        for pid in descendants:
            result["classification"][str(pid)] = "UNCERTAIN"
        result["uncertain"] = list(descendants)
    result["resolved"] = not result["live"] and not result["uncertain"]
    return result


def _finish_custody(
        context: RunContext, deadline: CleanupDeadline, reasons: list[str],
        ) -> str:
    """Tear down the complete custody only when nothing else is unresolved;
    otherwise keep every capability (still-needed cleanup authority).  Any
    reason blocks later dispatch."""
    if context.closed:
        outcome = "ALREADY_CLOSED"      # nothing retained; report the fact
    elif reasons:
        outcome = "RETAINED_OWNERSHIP_UNRESOLVED"
    else:
        outcome = context.close(lock_timeout=deadline.remaining())
    if outcome not in CLOSED_CUSTODY_OUTCOMES:
        reasons.append("CUSTODY_NOT_CLOSED")
    if deadline.expired() and "CLEANUP_DEADLINE_EXHAUSTED" not in reasons:
        reasons.append("CLEANUP_DEADLINE_EXHAUSTED")
    if reasons:
        context.dispatch_latch.block(context.run_id, reasons)
    return outcome


def _bounded_failure_cleanup(
        process: subprocess.Popen, context: RunContext, *,
        original_failure: str, sampler: Any = None,
        owned: Mapping[int, str] | None = None,
        cooperative_first: bool = False,
        collector: CumulativeOutputCollector | None = None,
        primary_failure: Mapping[str, Any] | None = None,
        prior_secondary: list[Dict[str, Any]] | None = None,
        ) -> Dict[str, Any]:
    """The one bounded failure-cleanup protocol.

    Signals only through the run's root authority (acquired at spawn,
    independent of the sampler), waits for the root with min(cap, remaining),
    collects output with its own bounded collector, stops the sampler with a
    bounded join, and records each outcome separately.  Anything unresolved
    keeps ownership and blocks later dispatch.  Never claims quiescence.
    """
    deadline = context.start_deadline(
        FAILURE_CLEANUP_TOTAL_SECONDS, "FAILURE_CLEANUP",
    )
    # D2: every cleanup operation may itself fail.  Each is guarded and its
    # secondary failure kept; none escapes, none restarts the deadline.
    # Interrupts (BaseException) are not caught here: the outer containment
    # in launch_request latches and re-raises them.
    secondary: list[Dict[str, Any]] = []

    def guarded(step: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as error:
            secondary.append({"step": step,
                              "error": f"{type(error).__name__}:{error}"})
            return default

    if sampler is not None:
        guarded("SAMPLER_REQUEST_STOP", sampler.request_stop, None)
    signals: list[Dict[str, Any]] = []

    def emit(signum: int) -> None:
        try:
            if os.name == "nt":
                if signum == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
            else:
                context.root_signal(signum)
            outcome = "SENT"
        except ProcessLookupError:
            outcome = "ESRCH_TARGET_ABSENT"
        except PermissionError as error:
            outcome = f"EPERM_DENIED:{error.strerror or error}"
        except OSError as error:
            outcome = f"REFUSED:{type(error).__name__}:{error.strerror or error}"
        except Exception as error:      # signal port itself failed
            outcome = f"PORT_FAILED:{type(error).__name__}:{error}"
            secondary.append({"step": "SIGNAL_PORT", "error": outcome})
        signals.append({
            "signal": signal.Signals(signum).name, "outcome": outcome,
            "remaining_nanoseconds": int(deadline.remaining() * 1_000_000_000),
        })

    def wait_root(cap: float) -> bool:
        if guarded("POLL", process.poll, None) is not None:
            return True
        budget = deadline.budget(cap)
        if budget <= 0:
            return False
        try:
            process.wait(timeout=budget)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception as error:  # one attempt; never retried
            secondary.append({"step": "WAIT",
                              "error": f"{type(error).__name__}:{error}"})
            return False

    if guarded("POLL", process.poll, None) is None:
        if cooperative_first:
            emit(signal.SIGTERM)
            if not wait_root(INITIALIZATION_FAILURE_TERM_WAIT_SECONDS):
                emit(signal.SIGKILL)
                wait_root(PROCESS_TREE_FORCE_VERIFY_SECONDS)
        else:
            emit(signal.SIGKILL)
            wait_root(PROCESS_TREE_FORCE_VERIFY_SECONDS)
    root_reaped = getattr(process, "returncode", None) is not None
    collector = collector or CumulativeOutputCollector()
    stdout, collection = guarded("COLLECTOR", lambda: _bounded_collect(
        process, deadline.budget(OUTPUT_COLLECTION_SECONDS), collector,
        "FAILURE_CLEANUP",
    ), None) or (collector.text, {
        "output_complete": False, "collector_state": "COLLECT_HELPER_FAILED",
        "partial_output_chars": len(collector.text),
        "output_contract": collector.report(),
    })
    sampler_stop = guarded("SAMPLER_STOP", lambda: _stop_sampler_bounded(
        sampler, deadline.budget(SAMPLER_STOP_JOIN_SECONDS),
    ), {"state": "STOP_HELPER_FAILED"})
    sampler_stopped = sampler_stop["state"] in ("NOT_CREATED", "STOPPED")
    descendants = guarded(
        "OWNERSHIP_RESOLUTION",
        lambda: resolve_known_descendants(process, context, owned),
        {"resolved": False, "live": [], "uncertain": ["RESOLUTION_FAILED"]})
    unverified_descendants = sorted(
        descendants["live"] + descendants["uncertain"], key=str)
    residual = ([] if root_reaped else [process.pid]) + unverified_descendants
    ownership_resolved = (
        root_reaped and not unverified_descendants
        and collection["output_complete"]
    )
    reasons = []
    if secondary:
        reasons.append("SECONDARY_CLEANUP_FAILURE")
    if not root_reaped:
        reasons.append("ROOT_NOT_REAPED")
    if unverified_descendants:
        reasons.append("OWNED_DESCENDANTS_UNVERIFIED")
    if not collection["output_complete"]:
        reasons.append("OUTPUT_EOF_NOT_OBSERVED")
    if not sampler_stopped:
        reasons.append("SAMPLER_NOT_STOPPED")
    if deadline.expired():
        reasons.append("CLEANUP_DEADLINE_EXHAUSTED")
    custody_close = guarded(
        "FINISH_CUSTODY", lambda: _finish_custody(context, deadline, reasons),
        "FINISH_CUSTODY_FAILED")
    if secondary and "SECONDARY_CLEANUP_FAILURE" not in reasons:
        reasons.append("SECONDARY_CLEANUP_FAILURE")
    if reasons:                     # latch independent of _finish_custody
        context.dispatch_latch.block(context.run_id, reasons)
    exhausted = deadline.expired()
    record = {
        "schema": "SplitAlignerR/ENGINE003BoundedFailureCleanup/v2",
        "original_failure": original_failure,
        # FIX004: structured primary (None only for legacy direct callers);
        # prior_secondary = failures that preceded this cleanup, after the
        # primary; the unresolved reasons above count this cleanup's own.
        "primary_failure": (None if primary_failure is None
                            else dict(primary_failure)),
        "secondary_failures": list(prior_secondary or []) + secondary,
        "descendant_resolution": descendants,
        "run_id": context.run_id,
        "generation": context.generation,
        "root_authority_state": context.root_authority_state,
        "signal_outcomes": signals,
        "force_process_group_signal_emitted": any(
            row["signal"] == "SIGKILL" and row["outcome"] == "SENT"
            for row in signals
        ),
        "root_exit_observed": root_reaped,
        "root_process_reaped": root_reaped,
        "residual_owned_targets": residual,
        "descendant_coverage": "NOT_ENUMERATED_NO_TRUSTED_CENSUS",
        "ownership_unresolved": not ownership_resolved,
        "ownership_retained": not ownership_resolved,
        **collection,
        "sampler_stop": sampler_stop,
        "sampler_stopped": sampler_stopped,
        "custody_close_outcome": custody_close,
        "custody": context.custody,
        "context_closed": context.closed,
        "cleanup_deadline": deadline.report(),
        "cleanup_deadline_exhausted": exhausted,
        "unresolved_reasons": reasons,
        "dispatch_blocked": bool(reasons),
        "native_survivor_state": "NOT_AVAILABLE_NATIVE_AUTHORITY_FAILURE",
        "whole_process_tree_quiescent": False,
    }
    context.record("FAILURE_CLEANUP", unresolved_reasons=reasons)
    return {"record": record, "stdout": stdout}


def _timeout_authority_failure_cleanup(
        process: subprocess.Popen, context: RunContext | None = None,
        original_failure: str = "TIMEOUT_AUTHORITY_FAILURE",
        sampler: Any = None, owned: Mapping[int, str] | None = None,
        ) -> Dict[str, Any]:
    """Bound a failed native timeout probe without claiming quiescence."""
    if context is None:
        context = default_run_context(None)
        context.attach_root(process)
    return _bounded_failure_cleanup(
        process, context, original_failure=original_failure,
        sampler=sampler, owned=owned,
    )["record"]


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


def _primary_failure_record(error: BaseException, phase: str) -> Dict[str, Any]:
    """DEV007_FIX004: the structured primary failure, registered once at the
    entry where it occurs (for a timeout: the watchdog's TimeoutExpired with
    its timeout and cumulative output fields).  Later cleanup, helper,
    sampler or evidence failures are secondary; they never replace it."""
    output = getattr(error, "output", None)
    timeout = getattr(error, "timeout", None)
    record: Dict[str, Any] = {
        "type": type(error).__name__, "message": str(error), "phase": phase,
        "label": f"{phase}:{type(error).__name__}:{error}",
        "interrupt": not isinstance(error, Exception),
        # strict canonical JSON: integers/strings only, no floats
        "timeout_nanoseconds": (int(timeout * 1_000_000_000)
                                if isinstance(timeout, (int, float)) else None),
        "timeout_text": None if timeout is None else str(timeout),
        "output_carried": output is not None,
    }
    if output is not None:
        try:
            raw = output if isinstance(output, bytes) else str(output).encode(
                "utf-8", "surrogatepass")
            record.update(output_source_type=type(output).__name__,
                          output_raw_bytes=len(raw),
                          output_raw_sha256=hashlib.sha256(raw).hexdigest())
        except Exception as describe_error:
            record["output_describe_error"] = type(describe_error).__name__
    return record


def _secondary_failure_record(step: str, error: BaseException,
                              **extra: Any) -> Dict[str, Any]:
    return {"step": step, "type": type(error).__name__,
            "error": f"{type(error).__name__}:{error}",
            "interrupt": not isinstance(error, Exception), **extra}


def _timeout_evidence_after_cleanup(
        write: Callable[[], Any], record: Dict[str, Any],
        context: RunContext) -> None:
    """The timeout cleanup has ALREADY completed under its one deadline: a
    failing (or interrupted) evidence/log write is recorded as a secondary
    failure next to the retained primary and blocks later dispatch.  No
    second cleanup, close or provider operation runs for nicer evidence.
    An interrupt is re-raised as itself, carrying this record."""
    try:
        write()
        record["timeout_stop_evidence"] = "WRITTEN"
    except BaseException as write_error:
        record.setdefault("secondary_failures", []).append(
            _secondary_failure_record("TIMEOUT_STOP_EVIDENCE_WRITE", write_error,
                                      after_cleanup_completed=True))
        record["timeout_stop_evidence"] = "WRITE_FAILED"
        record["evidence_write_failure"] = f"{type(write_error).__name__}:{write_error}"
        record["dispatch_blocked"] = True
        try:
            context.dispatch_latch.block(context.run_id, ["EVIDENCE_WRITE_FAILED"])
        except Exception:
            pass
        if not isinstance(write_error, Exception):
            write_error.cleanup = record
            write_error.controller_cleanup_completed = True
            raise


def _timeout_stop_evidence(
        runtime: Path, request: Mapping[str, Any], output_path: Path,
        log_path: Path, stdout: str, termination: Mapping[str, Any],
        sampler: ProcessTreeRssSampler,
        collector: CumulativeOutputCollector | None = None) -> Dict[str, Any]:
    _write_log(log_path, stdout, collector, "TIMEOUT_STOP_EVIDENCE")
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
        # Q6: `termination` (incl. its output contract) is a phase snapshot
        # taken before this record's own log write; the receipt below is
        # taken after that write.  The journal FINAL is published later and
        # is not claimed here.
        "termination_phase": "PHASE_SNAPSHOT_BEFORE_TIMEOUT_STOP_LOG_WRITE",
        "final_output_receipt": (
            None if collector is None else
            {"phase": "AFTER_TIMEOUT_STOP_LOG_WRITE", **collector.report()}
        ),
        "dispatch_journal_final": "NOT_PUBLISHED_AT_THIS_WRITE",
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
        ] | None = None,
        run_context_factory: Callable[[Any], RunContext] | None = None,
        popen_factory: Callable[..., Any] | None = None,
        sampler_factory: Callable[..., Any] | None = None,
        dispatch_latch: DispatchLatch | None = None,
        dispatch_journal: Any = None,
        dispatch_ticket: Any = None) -> Dict[str, Any]:
    """Validate, start, watch and validate exactly one parameterized worker.

    run_context_factory/popen_factory/sampler_factory are injection points
    for pure simulation; production uses default_run_context, Popen and
    ProcessTreeRssSampler.  One RunContext is created per call and passed to
    every waiter/timeout/cleanup step.

    DEV007_FIX002 protocol: dispatch_journal (stage_b_dispatch_journal) is
    required; IN_FLIGHT is published before any spawn and the scope refuses
    any unresolved earlier dispatch.  The worker writes its raw result to a
    unique run-specific, non-authoritative path (raw_worker_output_path);
    the controller never moves, overwrites or deletes it.  output_path holds
    exactly one controller record: the acceptance envelope (published only
    after every completion condition and validation) or a refusal record.

    DEV007_FIX005 (caller-bound transaction, see stage_b_dispatch_journal):
      * dispatch_journal: this call is the coordinator for its own caller's
        request (single-request/CLI): it reserves the ticket for exactly this
        request, executes it and commits through commit_current_dispatch();
        returns the committed acceptance envelope.
      * dispatch_ticket: execution authority for one reserved dispatch of an
        outer coordinator; the actual request/paths are checked against the
        ticket before spawn; returns PREPARED evidence only (never FINAL
        ACCEPTED).  Exactly one of the two is accepted.
    """
    # DEV_PHASE_EVIDENCE001: everything before the successful ticket check
    # is pre-effect (no spawn, acquisition, sampler or collector exists yet).
    # A failure here while a ticket is held is closed by THIS controller path
    # (_pre_effect_refusal: CLOSED_ZERO_EFFECT slot + STOP), not by a label.
    held, context, admission = dispatch_ticket, None, "REQUEST_SCHEMA"
    try:
        if request.get("schema") != LIVE_SCHEMA:
            raise StopSignal("SB_STOP_CONTRACT_FIELD_SET", "controller_schema")
        latch = DISPATCH_LATCH if dispatch_latch is None else dispatch_latch
        if latch.blocked:
            raise StopSignal(
                "SB_STOP_DISPATCH_BLOCKED",
                "unresolved_prior_run_ownership:" + ",".join(
                    str(record["run_id"]) for record in latch.records
                ),
            )
        if dispatch_journal is None and dispatch_ticket is None:
            # FIX003: unqualified callers denied first
            raise StopSignal("SB_STOP_DISPATCH_JOURNAL", "journal_required")
        if dispatch_journal is not None and dispatch_ticket is not None:
            raise StopSignal("SB_STOP_DISPATCH_JOURNAL", "journal_and_ticket")
        if branch_resource_path is None and request.get("execution_mode") != BOUNDED_MODE:
            raise StopSignal(
                "SB_STOP_RUNTIME_CAPTURE", "live_branch_resource_path_required",
            )
        effective_branch_resource_path = branch_resource_path or resource_path
        admission = "RESOURCE_CAPTURE"
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
        admission = "PRELAUNCH_GUARD"
        guard = prelaunch_guard(
            authority, assets, request, runtime, resource, durability,
            branch_resource,
        )
        if guard["worker_launch_authorized"] is not True:
            raise StopSignal("SB_STOP_ACTIVATION", "controller_launch_guard")
        admission = "SAMPLER_CAPABILITY"
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
        admission = "RUN_CONTEXT"
        try:    # NRP-2 FIX001: a capability refusal here is a controller STOP
            context = (
                run_context_factory(sampler_backend) if run_context_factory is not None
                else default_run_context(sampler_backend)
            )
        except NativeSamplerCapabilityError as error:
            raise StopSignal(
                "SB_STOP_SAMPLER_CAPABILITY", str(error),
            ) from error
        if context.native_backend is not sampler_backend:
            raise StopSignal("SB_STOP_ACTIVATION", "run_context_backend_mismatch")
        if context.dispatch_latch is not latch:
            raise StopSignal("SB_STOP_ACTIVATION", "run_context_latch_mismatch")
        try:
            context.admit()
        except OSError as error:
            raise StopSignal(
                "SB_STOP_ACTIVATION",
                f"run_context_admission:{error.strerror or error}",
            ) from error
        admission = "OUTPUT_AND_COMMAND"
        request_raw = canonical_json_bytes(dict(request))
        raw_path = raw_worker_output_path(output_path, context.run_id)
        if raw_path.exists() or output_path.exists():
            _pre_effect_close(context)
            raise StopSignal("SB_STOP_DISPATCH_JOURNAL", "output_paths_not_fresh")
        command = worker_command or [
            sys.executable, "-B", str(WORKER),
            "--repo-root", str(repo), "--runtime-root", str(runtime),
            "--resource", str(resource_path),
            "--branch-resource", str(effective_branch_resource_path),
            "--durability", str(durability_path),
            "--request", str(request_path), "--output", str(raw_path),
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
                _pre_effect_close(context)  # pure validation: before any reservation
                raise StopSignal(
                    "SB_STOP_RUNTIME_CAPTURE", "live_worker_command_branch_resource",
                )
        request_sha256 = hashlib.sha256(request_raw).hexdigest()
        write_canonical_json(request_path, dict(request))
        admission = "CALLER_RESERVATION"
        if dispatch_ticket is None:
            try:    # coordinator: caller-bound RESERVED + IN_FLIGHT before spawn
                dispatch_ticket = held = journal_protocol.reserve_current_dispatch(
                    dispatch_journal, run_id=str(context.run_id),
                    request_sha256=request_sha256, raw_path=raw_path,
                    output_path=output_path)
            except journal_protocol.JournalRefused as refused:
                _pre_effect_close(context)  # nothing was spawned or acquired
                raise StopSignal("SB_STOP_DISPATCH_JOURNAL", str(refused)) from refused
        ticket = dispatch_ticket
        admission = "TICKET_CHECK"
        # the actual request/paths must be the reserved ticket's; on success the
        # durable EFFECT_PERMITTED slot exists and only then may anything spawn
        ticket.check_execution(run_id=str(context.run_id),
                               request_sha256=request_sha256,
                               raw_path=raw_path, output_path=output_path)
    except BaseException as error:
        if held is None or isinstance(error, journal_protocol.CrashCut):
            raise           # no authority held (zero writes), or process death
        failures = _pre_effect_refusal(held, context, admission, error)
        if admission == "TICKET_CHECK" and isinstance(error, Exception):
            raise StopSignal("SB_STOP_DISPATCH_TICKET",
                             f"{error};secondary={failures}") from error
        if isinstance(error, StopSignal):
            error.detail = f"{error.detail};pre_effect_secondary={failures}"
        raise
    context.dispatch_ticket = ticket.ticket_sha256
    receipt = DispatchReceipt(ticket)
    start = time.perf_counter_ns()
    try:
        process = (popen_factory or subprocess.Popen)(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, **process_group_options(),
        )
    except BaseException as error:
        _pre_effect_close(context)  # spawn raised: no process object returned
        receipt.stop("SPAWN_FAILED", f"{type(error).__name__}:{error}")
        raise
    # Everything after spawn runs inside one protected region: any exit that
    # is not already a fully handled StopSignal goes through the bounded
    # failure cleanup, which keeps the primary failure plus residual
    # ownership/custody and blocks later dispatch while unresolved.
    collector = CumulativeOutputCollector()
    sampler: Any = None
    phase = "ROOT_ACQUISITION"
    primary_failure: Dict[str, Any] | None = None   # FIX004: set at the entry
    try:
        # Root cleanup authority is acquired before, and independently of,
        # the sampler, so a sampler initialization failure cannot remove it.
        context.attach_root(process)
        # NRP-2: durable post-spawn identity handoff from this acquisition,
        # before any sampler; a failure here is a post-spawn failure (the
        # owned root is cleaned up under retained custody, STOP, no accept).
        phase = "EFFECT_IDENTITY"
        receipt.record_effect(process, context)
        phase = "SAMPLER_CONSTRUCTION"
        sampler = (sampler_factory or ProcessTreeRssSampler)(
            process.pid, native_backend=sampler_backend,
        )
        phase = "SAMPLER_START"
        sampler.start()
        phase = "WATCHDOG"
        try:
            stdout, _ = process.communicate(timeout=(
                request["timeout_seconds"]
                if watchdog_timeout_seconds is None else watchdog_timeout_seconds
            ))
            collector.final(stdout, "WATCHDOG")
        except subprocess.TimeoutExpired as error:
            phase = "TIMEOUT"
            primary_failure = _primary_failure_record(error, "TIMEOUT")
            _handle_watchdog_timeout(
                error, process, context, sampler, collector,
                timeout_grace_waiter, runtime, request, output_path, log_path,
                primary_failure,
            )
        phase = "COMPLETION_CLEANUP"
        completion = _completion_cleanup(process, context, sampler, collector)
    except BaseException as error:
        # D5: the exception's own cumulative snapshot is registered at the
        # exception entry, before any cleanup can call communicate again.
        if phase == "WATCHDOG" or getattr(error, "output", None) is not None:
            try:
                collector.failure(error, phase + ":EXCEPTION_ENTRY")
            except Exception:
                pass
        # A StopSignal with .cleanup, or an interrupt that escaped AFTER the
        # timeout cleanup completed, is fully handled: publish the durable
        # STOP only (no second cleanup/close).
        if getattr(error, "cleanup", None) is not None and (
                isinstance(error, StopSignal)
                or getattr(error, "controller_cleanup_completed", False) is True):
            receipt.stop(getattr(error, "stop_id", "SB_STOP_TIMEOUT"), error.cleanup)
            if isinstance(error.cleanup, dict):
                error.cleanup["receipt"] = receipt.report()
            raise
        stop = _contained_post_spawn_failure(
            process, context, phase, error, sampler, collector,
            output_path, log_path, receipt, primary_failure,
        )
        if not isinstance(error, Exception):   # KeyboardInterrupt/SystemExit
            error.cleanup = stop.cleanup
            raise
        if isinstance(error, StopSignal):
            raise stop from error
        raise stop from error
    if not completion["completion_resolved"]:
        # Controller acceptance needs a fully resolved completion.  The
        # cleanup already ran once under its one deadline; this only records
        # evidence and stops (no second cleanup, close or deadline).
        stop = _completion_unresolved_stop(
            completion, context, process, collector, output_path, log_path,
            raw_path,
        )
        receipt.stop(stop.stop_id, completion)
        raise stop
    stdout = collector.text
    try:
        result = _validate_completed_worker(
            request, request_path, request_raw, resource_path, resource_raw,
            effective_branch_resource_path, branch_resource_raw,
            raw_path, log_path, process, sampler, stdout, guard, start,
            collector=collector, stop_record_path=output_path,
        )
    except StopSignal as stop:
        stop.cleanup = completion
        receipt.stop(stop.stop_id, completion)
        raise
    except BaseException as error:
        receipt.stop("VALIDATION_FAILED", f"{type(error).__name__}:{error}")
        raise
    prepared = _prepare_evidence(
        receipt, context, raw_path, completion, result, request_sha256,
    )
    if dispatch_journal is None:
        return prepared             # the outer coordinator verifies/commits
    # This call is the coordinator of its caller's request: the same unique
    # final-commit service as the orchestrator adapter.
    try:
        return journal_protocol.commit_current_dispatch(
            dispatch_journal, ticket, prepared)
    except journal_protocol.JournalRefused as refused:
        context.dispatch_latch.block(context.run_id, [refused.code])
        stop = StopSignal("SB_STOP_ACCEPTANCE_PUBLICATION", str(refused))
        stop.cleanup = {"receipt": dict(
            prepared["receipt"], commit_failure=str(refused),
            completed_in_order=getattr(refused, "completed_in_order",
                                       prepared["receipt"]["completed_in_order"]),
            failures=getattr(refused, "stop_failures", []),
            final="STOP" if getattr(refused, "completed_in_order", [None])[-1]
            == "JOURNAL_FINAL_STOP_PUBLISHED" else None),
            "completion": completion}
        raise stop from refused


def _pre_effect_refusal(ticket: Any, context: RunContext | None,
                        admission: str, error: BaseException) -> list:
    """The lower controller's own refusal while holding a ticket and BEFORE
    any effect handoff.  Closes the run context; if nothing was acquired
    (no context, or a closed context that never attached a root) it occupies
    the ticket's effect-handoff slot with CLOSED_ZERO_EFFECT, binding the
    controller phase and cause, then records STOP bound to that slot.  If the
    closure is refused or fails (slot taken, dispatch not open, custody
    unresolved, write failure) only the plain STOP is attempted and no
    zero-effect evidence exists.  Returns the secondary failures."""
    failures: list = []
    custody = "NO_RUN_CONTEXT"
    if context is not None:
        try:
            custody = str(_pre_effect_close(context))
        except Exception as close_error:
            custody = f"CLOSE_FAILED:{type(close_error).__name__}"
    detail = getattr(error, "detail", None)
    cause = {"controller_phase": "PRE_EFFECT:" + admission,
             "failure_type": type(error).__name__,
             "stop_id": getattr(error, "stop_id", None),
             "failure_sha256": hashlib.sha256(
                 str(error if detail is None else detail).encode(
                     "utf-8", "replace")).hexdigest(),
             "run_context_close": custody}
    phase_sha256 = None
    if context is None or (context.closed and context.root_authority is None
                           and context.root_authority_state == "NOT_ACQUIRED"):
        try:
            phase_sha256 = ticket.close_zero_effect(cause)
        except journal_protocol.CrashCut:
            raise
        except BaseException as close_error:
            failures.append(f"ZERO_EFFECT_CLOSURE:{type(close_error).__name__}:"
                            f"{close_error}")
    else:
        failures.append("ZERO_EFFECT_CLOSURE:RUN_CONTEXT_CUSTODY_UNRESOLVED")
    fields: Dict[str, Any] = {"pre_effect_cause": cause}
    if phase_sha256 is not None:
        fields["phase_sha256"] = phase_sha256
    if admission == "TICKET_CHECK":
        reason = "TICKET_BINDING_REFUSED_BEFORE_SPAWN"
        fields["binding_violation"] = {"expected": dict(ticket.binding),
                                       "failed": str(detail if detail is not None
                                                     else error)}
    else:
        reason = "PRE_EFFECT_ADMISSION_REFUSED"
    try:        # durable STOP, else the non-terminal IN_FLIGHT refuses
        ticket.stop(reason, **fields)
    except journal_protocol.CrashCut:
        raise
    except Exception as stop_error:
        failures.append(f"JOURNAL_FINAL_STOP:{type(stop_error).__name__}:{stop_error}")
    return failures


def _pre_effect_close(context: RunContext) -> str:
    """RunContext.close() with a finite cooperative lock wait: the remaining
    time of an existing cleanup deadline (never restarted or extended), else
    PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS.  NRP-2 FIX001: ONE attempt per
    context: a later pre-effect close of the same refusal (the ticket path's
    _pre_effect_refusal after an inline close) reuses the first outcome
    instead of waiting again.  An unresolved outcome stays unresolved (no
    zero-effect proof follows from it); a raised close is reported as
    CLOSE_FAILED on reuse."""
    done = getattr(context, "pre_effect_close_outcome", None)
    if done is not None:
        return done
    deadline = context.deadline
    try:
        outcome = context.close(lock_timeout=(
            deadline.remaining() if deadline is not None
            else PRE_EFFECT_CLOSE_LOCK_TIMEOUT_SECONDS))
    except Exception as error:
        context.pre_effect_close_outcome = f"CLOSE_FAILED:{type(error).__name__}"
        raise
    context.pre_effect_close_outcome = str(outcome)
    return outcome


def _effect_evidence(process: Any, context: RunContext) -> Dict[str, Any]:
    """What the controller actually observed at the modeled acquisition.
    The identity is the termination provider's own report (root_identity);
    a provider without one yields None, never an invented identity."""
    identity = None
    reporter = getattr(context.termination, "root_identity", None)
    if context.root_authority_state == "ACQUIRED" and callable(reporter):
        identity = reporter(context)
    return {"attempted_effect": "SPAWN_RETURNED_PROCESS_OBJECT",
            "observed_root": {"pid": process.pid,
                              "returncode_at_attach": process.returncode},
            "root_authority_state": context.root_authority_state,
            "custody": ("REGISTERED" if context.root_authority_state == "ACQUIRED"
                        else "NOT_REGISTERED"),
            "identity": identity,
            "controller_phase": "POST_SPAWN:ROOT_ACQUISITION"}


def raw_worker_output_path(output_path: Path, run_id: Any) -> Path:
    """Unique run-specific NON-authoritative worker raw result path."""
    return output_path.with_name(f"{output_path.stem}.raw-worker.{run_id}.json")


class DispatchReceipt:
    """Records the actually completed order of durable steps for one
    dispatch ticket; the lower layer publishes at most one FINAL, and only
    STOP.  A failed STOP publish leaves the durable IN_FLIGHT, which refuses.
    FINAL ACCEPTED belongs to the coordinator's commit service."""

    def __init__(self, ticket: Any) -> None:
        self.ticket, self.seq, self.run_id = ticket, ticket.seq, str(ticket.run_id)
        self.completed: list[str] = ["PROGRESSION_RESERVED_PUBLISHED",
                                     "JOURNAL_IN_FLIGHT_PUBLISHED",
                                     "TICKET_CHECKED_BEFORE_SPAWN"]
        self.failures: list[str] = []
        self.final: str | None = None

    def record_effect(self, process: Any, context: RunContext) -> None:
        """Durable EFFECT record (raises; the caller's post-spawn region
        handles any failure).  Recorded only after a successful write.  A
        ticket of a pre-NRP-2 journal module has no such service (its
        reservations declare no EFFECT_PROTOCOL, so no reader expects one);
        a current ticket always has it and its CLEANUP/FINAL ACCEPTED
        require the record."""
        writer = getattr(self.ticket, "record_effect_identity", None)
        self.effect_sha256 = None
        if writer is None:
            return
        self.effect_sha256 = writer(_effect_evidence(process, context))
        self.completed.append("JOURNAL_EFFECT_IDENTITY_PUBLISHED")

    def stop(self, reason: str, evidence: Any = None) -> None:
        if self.final is not None:
            return
        self.final = "STOP"
        try:
            digest = hashlib.sha256(canonical_json_bytes(
                {"evidence": evidence}) if not isinstance(evidence, str)
                else evidence.encode("utf-8", "replace")).hexdigest()
        except Exception:
            digest = None
        try:
            self.ticket.stop(reason, evidence_sha256=digest,
                             completed_steps=list(self.completed))
            self.completed.append("JOURNAL_FINAL_STOP_PUBLISHED")
        except Exception as error:
            self.failures.append(
                f"JOURNAL_FINAL_STOP:{type(error).__name__}:{error}")

    def report(self) -> Dict[str, Any]:
        return {"seq": self.seq, "ticket_sha256": self.ticket.ticket_sha256,
                "completed_in_order": list(self.completed),
                "failures": list(self.failures), "final": self.final,
                "receipt_phase": "FINAL_AS_OF_RETURN"}


def _prepare_evidence(
        receipt: DispatchReceipt, context: RunContext, raw_path: Path,
        completion: Mapping[str, Any], result: Mapping[str, Any],
        executed_request_sha256: str) -> Dict[str, Any]:
    """Persist the successful completion-cleanup + validation evidence as
    the ticket's CLEANUP record and return it as PREPARED evidence.  This is
    not acceptance: only the coordinator's commit_current_dispatch() may
    write FINAL ACCEPTED.  Any failure stops; the raw bytes are only read."""
    try:
        raw = raw_path.read_bytes()
        cleanup_sha = receipt.ticket.record_prepared(
            completion, raw_path, raw, result, executed_request_sha256)
        receipt.completed.append("JOURNAL_CLEANUP_RECORD_PUBLISHED")
    except Exception as error:
        # NRP-2 FIX002: the primary is fixed BEFORE receipt.stop, which may
        # append its own (secondary) JOURNAL_FINAL_STOP failure to the list.
        primary = f"PREPARED_PUBLISH:{type(error).__name__}:{error}"
        receipt.failures.append(primary)
        context.dispatch_latch.block(context.run_id, ["PREPARED_PUBLISH_FAILED"])
        receipt.stop("PREPARED_PUBLISH_FAILED")
        stop = StopSignal("SB_STOP_ACCEPTANCE_PUBLICATION", primary)
        stop.cleanup = {"receipt": receipt.report(), "completion": completion}
        raise stop from error
    return {
        "schema": journal_protocol.PREPARED_SCHEMA,
        "status": "PREPARED_NOT_ACCEPTED",
        "ticket": dict(receipt.ticket.binding),
        "cleanup_sha256": cleanup_sha,
        "executed_request_sha256": executed_request_sha256,
        "raw_worker_result_path": str(raw_path),
        "raw_worker_result_sha256": hashlib.sha256(raw).hexdigest(),
        "validated_result": dict(result),
        "receipt": receipt.report(),
    }


def _contained_post_spawn_failure(
        process: Any, context: RunContext, phase: str, error: BaseException,
        sampler: Any, collector: CumulativeOutputCollector,
        output_path: Path, log_path: Path, receipt: DispatchReceipt,
        primary_failure: Mapping[str, Any] | None = None,
        ) -> StopSignal:
    """D2 outer containment: whatever the cleanup or its evidence writes do
    (including raising or being interrupted), the primary failure, residual
    custody and the dispatch refusal are recorded without depending on the
    normal tail; an interrupt is re-raised after this minimal containment.
    FIX004: primary_failure (registered at the timeout entry) stays the
    primary; `error` is then recorded as a secondary failure."""
    try:
        stop = _post_spawn_failure(
            process, context, phase, error, sampler, collector,
            output_path, log_path, primary_failure,
        )
    except BaseException as escaped:
        try:
            context.dispatch_latch.block(context.run_id,
                                         ["POST_SPAWN_CLEANUP_ESCAPED"])
        finally:
            pass
        try:
            held = [c.report() for c in context.termination.table.held_caps()]
        except Exception as held_error:
            held = f"UNKNOWN:{type(held_error).__name__}"
        primary = (dict(primary_failure) if primary_failure is not None
                   else _primary_failure_record(error, phase))
        prior = ([] if primary_failure is None else
                 [_secondary_failure_record(phase + ":HANDLING", error)])
        record = {
            "schema": "SplitAlignerR/ENGINE003ContainedCleanupEscape/v1",
            "original_failure": primary["label"],
            "primary_failure": primary,
            "failure_phase": phase,
            "secondary_failures": prior + [
                _secondary_failure_record("CLEANUP_PROTOCOL", escaped)],
            "residual_custody_held": held, "context_closed": context.closed,
            "ownership_retained": True, "dispatch_blocked": True,
            "output_contract": collector.report(),
        }
        receipt.stop("POST_SPAWN_CLEANUP_ESCAPED", record)
        record["receipt"] = receipt.report()
        if not isinstance(escaped, Exception):
            escaped.cleanup = record
            raise
        stop = StopSignal("SB_STOP_CONTROLLER_POST_SPAWN_FAILURE",
                          record["original_failure"])
        stop.cleanup = record
        return stop
    receipt.stop(stop.stop_id, stop.cleanup)
    stop.cleanup["receipt"] = receipt.report()
    return stop


def _post_spawn_failure(
        process: Any, context: RunContext, phase: str, error: BaseException,
        sampler: Any, collector: CumulativeOutputCollector,
        output_path: Path, log_path: Path,
        primary_failure: Mapping[str, Any] | None = None,
        ) -> StopSignal:
    """Bounded cleanup for every post-spawn exit not otherwise handled."""
    owned = None
    if sampler is not None:
        try:
            owned = sampler.owned_identity_snapshot()
        except Exception:
            owned = None
    prior: list[Dict[str, Any]] = []
    if primary_failure is not None:
        # FIX004: the timeout handling itself failed before its cleanup
        # completed.  The timeout stays primary; this is its secondary.
        prior.append(_secondary_failure_record(phase + ":HANDLING", error))
        original = str(primary_failure["label"])
        stop_id = "SB_STOP_TIMEOUT"
        detail = f"parameterized_worker;secondary={type(error).__name__}:{error}"
    elif isinstance(error, StopSignal):
        original, stop_id, detail = str(error), error.stop_id, error.detail
    elif phase == "SAMPLER_CONSTRUCTION" and isinstance(
            error, NativeSamplerCapabilityError):
        # The ABI was validated before Popen.  A root identity failure after
        # launch still fails closed and owns cleanup of the just-started tree.
        original = f"SB_STOP_SAMPLER_CAPABILITY:{error}"
        stop_id, detail = "SB_STOP_SAMPLER_CAPABILITY", str(error)
    else:
        original = f"{phase}:{type(error).__name__}:{error}"
        stop_id, detail = "SB_STOP_CONTROLLER_POST_SPAWN_FAILURE", original
    # After the frozen grace period a cooperative wait is not restarted.
    cleanup = _bounded_failure_cleanup(
        process, context, original_failure=original, sampler=sampler,
        owned=owned, cooperative_first=phase != "TIMEOUT", collector=collector,
        primary_failure=(primary_failure if primary_failure is not None
                         else _primary_failure_record(error, phase)),
        prior_secondary=prior,
    )
    if prior:       # the disrupted timeout handling itself blocks dispatch
        cleanup["record"]["dispatch_blocked"] = True
        context.dispatch_latch.block(context.run_id, ["TIMEOUT_HANDLING_FAILED"])
    cleanup["record"]["failure_phase"] = phase
    try:
        _write_log(log_path, cleanup["stdout"], collector, "POST_SPAWN_CLEANUP")
        cleanup["record"]["output_contract"] = collector.report()
        suffix = (
            ".initialization-cleanup.json"
            if stop_id == "SB_STOP_SAMPLER_CAPABILITY"
            else ".post-spawn-cleanup.json"
        )
        write_canonical_json(output_path.with_suffix(suffix), cleanup["record"])
    except Exception as write_error:   # evidence failure never hides custody
        cleanup["record"]["evidence_write_failure"] = (
            f"{type(write_error).__name__}:{write_error}"
        )
        context.dispatch_latch.block(context.run_id, ["EVIDENCE_WRITE_FAILED"])
    stop = StopSignal(stop_id, detail)
    stop.cleanup = cleanup["record"]
    return stop


def _completion_cleanup(
        process: Any, context: RunContext, sampler: Any,
        collector: CumulativeOutputCollector,
        ) -> Dict[str, Any]:
    """Normal worker exit: one deadline for sampler stop and custody close."""
    deadline = context.start_deadline(
        FAILURE_CLEANUP_TOTAL_SECONDS, "COMPLETION_CLEANUP",
    )
    sampler_stop = _stop_sampler_bounded(
        sampler, deadline.budget(SAMPLER_STOP_JOIN_SECONDS),
    )
    try:
        owned = sampler.owned_identity_snapshot() if sampler is not None else {}
        descendants = resolve_known_descendants(process, context, owned)
    except Exception as error:
        descendants = {"resolved": False, "live": [], "uncertain": ["SNAPSHOT"],
                       "error": f"{type(error).__name__}:{error}"}
    reasons = []
    if descendants["live"]:
        reasons.append("KNOWN_DESCENDANT_LIVE")
    if descendants["uncertain"]:
        reasons.append("DESCENDANT_OWNERSHIP_UNCERTAIN")
    if process.returncode is None:
        reasons.append("ROOT_NOT_REAPED")
    if not collector.complete:
        reasons.append("OUTPUT_EOF_NOT_OBSERVED")
    if sampler_stop["state"] != "STOPPED":
        reasons.append("SAMPLER_NOT_STOPPED")
    if deadline.expired():
        reasons.append("CLEANUP_DEADLINE_EXHAUSTED")
    custody_close = _finish_custody(context, deadline, reasons)
    if not context.closed and "CUSTODY_NOT_CLOSED" not in reasons:
        reasons.append("CUSTODY_NOT_CLOSED")        # never accept open custody
        context.dispatch_latch.block(context.run_id, reasons)
    record = {
        "schema": "SplitAlignerR/ENGINE003CompletionCleanup/v2",
        "run_id": context.run_id, "generation": context.generation,
        "dispatch_ticket": context.dispatch_ticket,
        "worker_returncode": process.returncode,
        "root_reaped": process.returncode is not None,
        "pipe_eof": collector.complete,
        "descendant_resolution": descendants,
        "whole_process_tree_quiescent": "NOT_CLAIMED",
        "sampler_stop": sampler_stop, "output_contract": collector.report(),
        "custody_close_outcome": custody_close, "custody": context.custody,
        "context_closed": context.closed,
        "cleanup_deadline": deadline.report(),
        "unresolved_reasons": reasons, "dispatch_blocked": bool(reasons),
        "completion_resolved": not reasons and context.closed,
    }
    context.record("COMPLETION_CLEANUP", unresolved_reasons=reasons)
    return record


def _completion_unresolved_stop(
        completion: Dict[str, Any], context: RunContext, process: Any,
        collector: CumulativeOutputCollector,
        output_path: Path, log_path: Path, raw_path: Path,
        ) -> StopSignal:
    """Fail closed after a normal worker exit whose completion cleanup is
    unresolved.  The worker's raw result stays where the worker wrote it
    (run-specific, non-authoritative raw_path): it is never moved,
    overwritten or deleted.  The refusal is a separate controller record at
    output_path (no-clobber) plus the completion record; a failure of any of
    these writes is recorded and keeps the refusal (default: no acceptance
    envelope exists, and the journal IN_FLIGHT/STOP refuses)."""
    reasons = list(completion["unresolved_reasons"])
    completion_path = output_path.with_suffix(".completion-cleanup.json")
    failures: list[str] = []
    completed: list[str] = []
    try:
        raw_exists = raw_path.is_file()
        raw_sha = (hashlib.sha256(raw_path.read_bytes()).hexdigest()
                   if raw_exists else None)
    except Exception as error:
        raw_exists, raw_sha = "UNKNOWN", None
        failures.append(f"RAW_READ:{type(error).__name__}:{error}")
    completion["worker_output_disposition"] = (
        "RAW_PRESERVED_UNACCEPTED_IN_PLACE" if raw_exists is True
        else "NO_WORKER_OUTPUT" if raw_exists is False else "RAW_STATE_UNKNOWN")
    completion["raw_worker_result_path"] = str(raw_path)
    completion["raw_worker_result_sha256"] = raw_sha
    completion["raw_move_attempted"] = False
    completion["controller_acceptance"] = "REFUSED_COMPLETION_UNRESOLVED"
    try:
        _write_log(log_path, collector.text, collector, "COMPLETION_UNRESOLVED")
        completed.append("LOG_WRITTEN")
    except Exception as error:
        failures.append(f"LOG:{type(error).__name__}:{error}")
    completion["output_contract"] = collector.report()
    stop_record = {
        "schema": "SplitAlignerR/ENGINE003CompletionUnresolvedStop/v2",
        "status": "SB_STOP_CONTROLLER_COMPLETION_UNRESOLVED",
        "decision_ledger_eligible": False,
        "controller_acceptance": "REFUSED_COMPLETION_UNRESOLVED",
        "no_later_request_launch": True,
        "worker_returncode": process.returncode,
        "worker_result_validated": False,
        "worker_output_disposition": completion["worker_output_disposition"],
        "raw_worker_result_path": str(raw_path),
        "raw_worker_result_sha256": raw_sha,
        "completion_cleanup_path": str(completion_path),
        "completion_cleanup": completion,
    }
    for name, path, value in (("STOP_RECORD", output_path, stop_record),
                              ("COMPLETION_RECORD", completion_path, completion)):
        try:
            journal_protocol.publish_no_clobber(
                path, canonical_json_bytes(dict(value)))
            completed.append(name + "_WRITTEN")
        except Exception as error:
            failures.append(f"{name}:{type(error).__name__}:{error}")
    completion["evidence_completed_in_order"] = completed
    if failures:                    # evidence failure never hides custody
        completion["evidence_write_failure"] = failures
        context.dispatch_latch.block(context.run_id, ["EVIDENCE_WRITE_FAILED"])
    stop = StopSignal(
        "SB_STOP_CONTROLLER_COMPLETION_UNRESOLVED",
        ",".join(reasons) + f";worker_exit={process.returncode}",
    )
    stop.cleanup = completion
    return stop


def _handle_watchdog_timeout(
        error: subprocess.TimeoutExpired, process: Any, context: RunContext,
        sampler: Any, collector: CumulativeOutputCollector,
        timeout_grace_waiter: Any, runtime: Path, request: Mapping[str, Any],
        output_path: Path, log_path: Path,
        primary_failure: Mapping[str, Any] | None = None,
        ) -> None:
    """The frozen timeout state machine plus one bounded cleanup; always
    raises a StopSignal carrying its cleanup record.

    FIX004: primary_failure is the TimeoutExpired registered at the watchdog
    entry; every record keeps it as `primary_failure` / `original_failure`.
    A helper exception before the cleanup completes leaves this function and
    is contained by launch_request as a SECONDARY failure (same deadline).
    After the cleanup completed, an evidence/log failure is only recorded
    (_timeout_evidence_after_cleanup), never cleaned up a second time."""
    if primary_failure is None:
        primary_failure = _primary_failure_record(error, "TIMEOUT")
    deadline = context.start_deadline(
        TIMEOUT_CLEANUP_TOTAL_SECONDS, "TIMEOUT",
    )
    collector.timeout_snapshot(error.output, "WATCHDOG_TIMEOUT")
    try:
        termination = exact_timeout_state_machine(
            process, timeout_grace_waiter,
            sampler.owned_identity_snapshot,
            sampler.native_backend, context,
        )
    except StopSignal as termination_error:
        # The timeout stays primary; the failed termination authority is the
        # timeout protocol's own outcome (stop id), recorded separately.
        cleanup = _bounded_failure_cleanup(
            process, context,
            original_failure=str(primary_failure["label"]),
            sampler=sampler, owned=sampler.owned_identity_snapshot(),
            collector=collector, primary_failure=primary_failure,
        )
        cleanup_record = cleanup["record"]
        cleanup_record["failure_phase"] = "TIMEOUT"
        cleanup_record["timeout_termination_failure"] = {
            "stop_id": termination_error.stop_id,
            "detail": termination_error.detail,
            "message": str(termination_error),
        }
        failure_termination = {
            "termination_sequence": [
                "REQUEST_COOPERATIVE_STOP", "WAIT_60_SECONDS",
                "NATIVE_SURVIVOR_AUTHORITY_FAILED",
                "BEST_EFFORT_FORCE_PROCESS_GROUP",
            ],
            "status": termination_error.stop_id,
            "detail": termination_error.detail,
            "decision_ledger_eligible": False,
            "controller_stdout_complete": cleanup_record["output_complete"],
            **cleanup_record,
        }
        termination_error.cleanup = cleanup_record
        _timeout_evidence_after_cleanup(lambda: _timeout_stop_evidence(
            runtime, request, output_path, log_path, cleanup["stdout"],
            failure_termination, sampler, collector,
        ), cleanup_record, context)
        raise termination_error from error
    stdout, collection = _bounded_collect(
        process, deadline.budget(OUTPUT_COLLECTION_SECONDS), collector,
        "TIMEOUT_COLLECT",
    )
    sampler_stop = _stop_sampler_bounded(
        sampler, deadline.budget(SAMPLER_STOP_JOIN_SECONDS),
    )
    unresolved = []
    if termination.get("whole_process_tree_quiescent") is not True:
        unresolved.append("WHOLE_TREE_NOT_QUIESCENT")
    if process.returncode is None:
        unresolved.append("ROOT_NOT_REAPED")
    if not collection["output_complete"]:
        unresolved.append("OUTPUT_EOF_NOT_OBSERVED")
    if sampler_stop["state"] != "STOPPED":
        unresolved.append("SAMPLER_NOT_STOPPED")
    if deadline.expired():
        unresolved.append("CLEANUP_DEADLINE_EXHAUSTED")
    custody_close = _finish_custody(context, deadline, unresolved)
    # The timeout cleanup has completed from here on.
    try:
        termination = {
            **termination,
            "output_collection": collection,
            "controller_stdout_complete": collection["output_complete"],
            "sampler_stop": sampler_stop,
            "bounded_cleanup_deadline": deadline.report(),
            "custody_close_outcome": custody_close,
            "custody": context.custody,
            "context_closed": context.closed,
            "unresolved_reasons": unresolved,
            "dispatch_blocked": bool(unresolved),
        }
        secondary: list[Dict[str, Any]] = []
    except Exception as build_error:        # keep what is already known
        termination = {"custody_close_outcome": custody_close,
                       "unresolved_reasons": unresolved,
                       "dispatch_blocked": True}
        secondary = [_secondary_failure_record("TIMEOUT_RECORD_BUILD", build_error)]
        context.dispatch_latch.block(context.run_id, ["TIMEOUT_RECORD_BUILD_FAILED"])
    termination.update(original_failure=str(primary_failure["label"]),
                       primary_failure=dict(primary_failure),
                       secondary_failures=secondary, failure_phase="TIMEOUT")
    stop = StopSignal("SB_STOP_TIMEOUT", "parameterized_worker")
    stop.cleanup = termination
    _timeout_evidence_after_cleanup(lambda: _timeout_stop_evidence(
        runtime, request, output_path, log_path, stdout,
        termination, sampler, collector,
    ), termination, context)
    raise stop from error


def _validate_completed_worker(
        request: Mapping[str, Any], request_path: Path, request_raw: bytes,
        resource_path: Path, resource_raw: bytes,
        effective_branch_resource_path: Path, branch_resource_raw: bytes,
        output_path: Path, log_path: Path, process: Any, sampler: Any,
        stdout: str, guard: Mapping[str, Any], start: int,
        collector: CumulativeOutputCollector | None = None,
        stop_record_path: Path | None = None,
        ) -> Dict[str, Any]:
    """Unchanged result validation after a completed, cleaned-up worker.

    `output_path` here is the worker's raw result path: it is read, never
    rewritten.  Only reached when completion cleanup is fully resolved; the
    returned result is accepted only once commit_current_dispatch commits."""
    _write_log(log_path, stdout, collector, "COMPLETED_WORKER")
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
        raw_worker_path = output_path      # raw stays in place, unmodified
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
        journal_protocol.publish_no_clobber(
            stop_record_path or output_path.with_suffix(".resource-stop.json"),
            canonical_json_bytes(stop))
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
    # DEV007_FIX002: the stable dispatch scope.  FileStorage is UNQUALIFIED
    # (journal_protocol.NATIVE_STORAGE_QUALIFIED is False); without these
    # arguments launch_request refuses before any spawn.
    parser.add_argument("--dispatch-journal-dir", type=Path)
    # DEV007_FIX003: independent progression store (separate failure domain;
    # also UNQUALIFIED).  Without it the journal refuses.
    parser.add_argument("--dispatch-progression-dir", type=Path)
    parser.add_argument("--dispatch-generation")
    parser.add_argument("--dispatch-input-identity")
    parser.add_argument("--dispatcher-owner")
    parser.add_argument("--initialize-dispatch-scope", action="store_true")
    args = parser.parse_args()
    journal = None
    if args.dispatch_journal_dir is not None:
        journal = journal_protocol.DispatchJournal(
            journal_protocol.FileStorage(args.dispatch_journal_dir),
            run_generation=args.dispatch_generation,
            input_identity=args.dispatch_input_identity,
            dispatcher_owner=args.dispatcher_owner,
            progression=(None if args.dispatch_progression_dir is None else
                         journal_protocol.FileStorage(args.dispatch_progression_dir)))
        if args.initialize_dispatch_scope:      # explicit, never implicit
            journal.initialize_scope()
            print(f"DISPATCH_SCOPE_INITIALIZED {journal.scope_id}")
            return
    request = strict_json_load(args.request)
    envelope = launch_request(
        args.repo_root.resolve(), args.runtime_root.resolve(),
        Path(os.path.abspath(args.resource)), args.durability.resolve(), request,
        args.request.resolve(), args.output.resolve(), args.log.resolve(),
        Path(os.path.abspath(args.branch_resource)),
        dispatch_journal=journal,
    )
    # The acceptance envelope is already published (no-clobber) at --output;
    # it is not rewritten here (that would break its journaled hash).
    result = envelope["accepted_result"]
    print(
        f"{envelope['status']} STATUS={result['status']} "
        f"CANDIDATE={result.get('candidate_id')} "
        f"MODE={result.get('execution_mode')}"
    )


if __name__ == "__main__":
    main()
