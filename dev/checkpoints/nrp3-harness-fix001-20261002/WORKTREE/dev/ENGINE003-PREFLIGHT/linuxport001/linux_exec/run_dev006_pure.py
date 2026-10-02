"""Portable pure-simulation runner for the DEV006/DEV007 regression evidence.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 run_dev006_pure.py [--list]

Needs no git, no absolute historical path and no host /proc: baselines come
from testsupport/ (sha256-checked), parsers from the in-tree p18_working
bytes verified against the bundled pins when the historical INPUTS copy is
absent. While the suites run, host effects are blocked: os.kill, os.killpg,
os.fork, os.setpgid, subprocess.Popen and opening any /proc path raise
HostEffectBlocked, so a candidate path that tried a real signal, fork or
/proc read fails the run instead of acting.

Excluded (they deliberately touch the host and are unchanged by DEV006):
ProcSourceTests (reads /proc/self), ObservingGuardTests and StuckGuardTests
(spawn a Python subprocess that installs the real p18 guard).
"""
import builtins
import io
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUITES = [
    # DEV_PHASE_EVIDENCE001: durable effect-handoff slot / zero-effect closure
    "test_dev_phase_evidence001",
    "test_dev_phase_evidence001_fix001",
    "test_dev007_fix005",
    # DEV007_FIX005: the FIX004 below-caller binding classes (bind_current_
    # dispatch / verify_current_dispatch_acceptance, removed) are superseded
    # by test_dev007_fix005 and kept unchanged as history; A007F3-2 stays.
    "test_dev007_fix004.TimeoutPrimarySecondaryTests",
    "test_dev007_fix003",
    "test_dev007_fix002",
    "test_dev007_fix001",
    "test_dev007",
    "test_dev006",
    "test_controller_dispatch",
    "test_linux_exec.BackendIdentityTests",
    "test_linux_exec.BackendCensusTests",
    "test_linux_exec.BackendOwnedTreeTests",
    "test_linux_exec.BackendRssTests",
    "test_linux_exec.BackendRssGroupBindingTests",
    "test_linux_exec.UnchangedControllerSamplerTests",
    "test_linux_exec.LifecycleSuccessTests",
    "test_linux_exec.LifecycleAdmissionTests",
    "test_linux_exec.LifecycleAdmissionBoundaryTests",
    "test_linux_exec.LifecycleAdverseTests",
]


class HostEffectBlocked(AssertionError):
    pass


def _blocked(name):
    def refuse(*args, **kwargs):
        raise HostEffectBlocked("%s%r" % (name, args[:2]))
    return refuse


def block_host_effects():
    for name in ("kill", "killpg", "fork", "setpgid", "setsid"):
        if hasattr(os, name):
            setattr(os, name, _blocked("os." + name))
    subprocess.Popen = _blocked("subprocess.Popen")
    real_open, real_io_open = builtins.open, io.open

    def guarded(opener):
        def open_(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = os.fsdecode(file)
                if path == "/proc" or path.startswith("/proc/"):
                    raise HostEffectBlocked("open(%s)" % path)
            return opener(file, *args, **kwargs)
        return open_
    builtins.open = guarded(real_open)
    io.open = guarded(real_io_open)


def main(argv):
    if "--list" in argv:
        print("\n".join(SUITES))
        return 0
    # Import (parser pin verification reads in-tree source files) first,
    # then block host effects for the whole test run.
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(SUITES)
    block_host_effects()
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    print("DEV006_PURE_RUN tests=%d failures=%d errors=%d skipped=%d"
          % (result.testsRun, len(result.failures), len(result.errors),
             len(result.skipped)))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
