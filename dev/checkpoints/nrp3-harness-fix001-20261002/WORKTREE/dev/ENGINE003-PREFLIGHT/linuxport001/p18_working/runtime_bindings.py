"""P17 exact process-local bindings; construction is forbidden in P17 cases."""
import hashlib
import os
import posix
import sys
from pathlib import Path

import native_syscalls_factory as setup001
import parsers
import pidfd_primitives as p01
from ledger import require


class RuntimeBindings:
    def __init__(self, source_root, source_pins, host_pins, expected_pid):
        self.root = str(Path(source_root))
        self.pins = dict(source_pins)
        self.owner_pid = os.getpid()
        require(self.owner_pid == expected_pid
                and sys.version_info[:3] == (3, 8, 10),
                "RUNTIME_OWNER_VERSION")
        self.p01 = p01
        self.p01_path = str(Path(p01.__file__))
        self.factory_path = str(Path(setup001.__file__))
        self.effects_path = str(Path(source_root) / "integrated_native_effects.py")
        self.direct_path = str(Path(source_root) / "direct_child_pidfd.py")
        self.os_close = os.close
        self.getpid = os.getpid
        self.path_read_bytes_function = Path.read_bytes
        self.native_class = p01.NativeSyscalls
        self.handle_class = p01.PidfdHandle
        self.policy_class = p01.AcquisitionPolicy
        self.environment_class = p01.AcquisitionEnvironment
        self.procstat_class = parsers.ProcStat
        self.native_init_function = p01.NativeSyscalls.__init__
        self.handle_init_function = p01.PidfdHandle.__init__
        self.native_open_function = p01.NativeSyscalls.open
        self.native_environment_function = p01.NativeSyscalls.acquisition_environment
        self.validate_environment_function = p01.validate_acquisition_environment
        self.direct_child_stat_function = p01.direct_child_stat
        self.wait_without_reaping_function = p01.wait_without_reaping
        self.bounded_read_function = p01.bounded_read
        self.native_factory = setup001.construct_native_syscalls
        require(self.os_close is posix.close
                and self.os_close.__module__ == "posix",
                "EXACT_OS_CLOSE")
        require(p01.os is os and setup001.p01 is p01 and setup001.os is os,
                "P01_SETUP_MODULE_BINDING")
        require(p01.NativeSyscalls.open.__code__.co_filename == self.p01_path
                and p01.direct_child_stat.__code__.co_filename == self.p01_path
                and p01.wait_without_reaping.__code__.co_filename == self.p01_path
                and p01.bounded_read.__code__.co_filename == self.p01_path,
                "P01_FUNCTION_SOURCE_BINDING")
        required_names = {
            "direct_child_pidfd.py", "integrated_native_effects.py",
            "integrated_native_adapter.py", "native_owner_controller.py",
            "runtime_bindings.py", "development_guard.py", "recorded_native.py",
            "ledger.py", "common.py", "pidfd_primitives.py", "parsers.py",
            "native_syscalls_factory.py", "SUPPLIED_FIXTURES.json",
            "SOURCE_ISOLATION_MANIFEST.json", "pure_candidate_runner.py",
            "STATIC_CHECKLIST.json", "README.md",
        }
        require(set(self.pins) == required_names, "P17_SOURCE_PIN_SET")
        self.module_records = []
        for name in sorted(required_names):
            path = Path(source_root) / name
            data = path.read_bytes()
            require(hashlib.sha256(data).hexdigest() == self.pins[name],
                    "P17_SOURCE_FILE_PIN")
            self.module_records.append({
                "path": str(path), "bytes": len(data),
                "sha256": self.pins[name],
            })
        for module in (p01, parsers, setup001):
            require(str(Path(module.__file__).parent) == self.root,
                    "DEPENDENCY_MODULE_ROOT")
        self.host_pins = list(host_pins)
        for row in self.host_pins:
            data = Path(row["path"]).read_bytes()
            require(len(data) == row["bytes"]
                    and hashlib.sha256(data).hexdigest() == row["sha256"],
                    "HOST_FILE_PIN")
        from direct_child_pidfd import (
            DirectChildPidfdView, NonOwningViewCapability,
            PostRegisterProofCapability, PreOpenPrepareCapability,
            PreparedDirectChild, RawCaptureCapability,
        )
        from integrated_native_effects import (
            IntegratedNativeEffects, RawDirectChildCustody,
            RegisteredDirectChildCustody,
        )
        from native_owner_controller import NativeOwnerController
        self.prepared_class = PreparedDirectChild
        self.raw_custody_class = RawDirectChildCustody
        self.registered_custody_class = RegisteredDirectChildCustody
        self.prepare_capability_class = PreOpenPrepareCapability
        self.capture_capability_class = RawCaptureCapability
        self.proof_capability_class = PostRegisterProofCapability
        self.view_capability_class = NonOwningViewCapability
        self.view_class = DirectChildPidfdView
        self.provider_class = IntegratedNativeEffects
        self.controller_class = NativeOwnerController
        self.api_records = {}
        for name, function in (
            ("os.close", self.os_close),
            ("NativeSyscalls.open", self.native_open_function),
            ("NativeSyscalls.acquisition_environment",
             self.native_environment_function),
            ("validate_acquisition_environment",
             self.validate_environment_function),
            ("direct_child_stat", self.direct_child_stat_function),
            ("wait_without_reaping", self.wait_without_reaping_function),
            ("bounded_read", self.bounded_read_function),
            ("construct_native_syscalls", self.native_factory),
            ("Path.read_bytes", self.path_read_bytes_function),
        ):
            code = getattr(function, "__code__", None)
            self.api_records[name] = {
                "module": getattr(function, "__module__", None),
                "qualname": getattr(function, "__qualname__",
                                    getattr(function, "__name__", None)),
                "process_local_id": id(function),
                "python_code_filename": code.co_filename if code else None,
                "python_first_line": code.co_firstlineno if code else None,
            }
        self.monitor = None

    def bind_monitor(self, monitor):
        require(self.monitor is None and monitor.runtime is self,
                "MONITOR_BINDING")
        self.monitor = monitor

    def validate_native(self, native):
        self.validate()
        require(type(native) is self.native_class
                and type(native.no_cldwait) is int
                and native.no_cldwait == 2
                and native.open.__self__ is native
                and native.open.__func__ is self.native_open_function
                and native.acquisition_environment.__self__ is native
                and native.acquisition_environment.__func__
                    is self.native_environment_function,
                "EXACT_NATIVE_INSTANCE_BINDING")

    def validate(self):
        require(os.getpid() == self.owner_pid, "OWNER_PROCESS_CHANGED")
        require(os.close is self.os_close and posix.close is self.os_close,
                "OS_CLOSE_REPLACED")
        require(p01.NativeSyscalls is self.native_class
                and p01.AcquisitionPolicy is self.policy_class
                and p01.AcquisitionEnvironment is self.environment_class
                and parsers.ProcStat is self.procstat_class
                and p01.NativeSyscalls.__init__ is self.native_init_function
                and p01.PidfdHandle is self.handle_class
                and p01.PidfdHandle.__init__ is self.handle_init_function
                and p01.NativeSyscalls.open is self.native_open_function
                and p01.NativeSyscalls.acquisition_environment
                    is self.native_environment_function
                and p01.validate_acquisition_environment
                    is self.validate_environment_function
                and p01.direct_child_stat is self.direct_child_stat_function
                and p01.wait_without_reaping
                    is self.wait_without_reaping_function
                and p01.bounded_read is self.bounded_read_function
                and setup001.construct_native_syscalls is self.native_factory
                and Path.read_bytes is self.path_read_bytes_function,
                "P17_RUNTIME_API_REPLACED")

    def report(self):
        return {
            "scope": "P17_EXACT_DIRECT_CHILD_RUNTIME_BINDINGS",
            "owner_pid": self.owner_pid,
            "modules": list(self.module_records),
            "host_pins": list(self.host_pins),
            "apis": dict(self.api_records),
            "native_provider_executions_in_P17_candidate": 0,
            "owning_handle_constructions_in_P17_candidate": 0,
        }
