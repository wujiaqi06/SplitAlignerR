"""Binding of the Linux backend to the Stage-B development controller.

`exec_preflight/stage_b_controller.py` in this WORKTREE carries the
DEV005/DEV006 platform-plumbing patch: an explicit per-run RunContext whose
termination provider is fixed at request start (default on Linux: none; the
simulated capability provider is termination.LinuxDevelopmentRoute). Its `_sampler_capability_backend()` still refuses Linux;
this module is the explicit, opt-in Linux route a developer uses instead:

    c = load_controller()
    backend = linux_backend(c, RealProcSource(), parse_proc_stat)
    sampler = c.ProcessTreeRssSampler(root_pid, native_backend=backend)

The backend raises the controller's own NativeSampler* exception classes so
the controller's except clauses (exit race, absence, reuse) behave exactly as
they do for the Darwin backend.
"""
import hashlib
import importlib
import os
import sys
import types

from linux_proc_backend import LinuxProcSamplerBackend, kernel_thread_tolerant

EXEC_PREFLIGHT = os.path.realpath(os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "..", "..", "exec_preflight"))
CONTROLLER_FILE = os.path.join(EXEC_PREFLIGHT, "stage_b_controller.py")


def load_controller(exec_preflight=EXEC_PREFLIGHT):
    """Import the WORKTREE controller; returns (module, file sha256)."""
    sys.dont_write_bytecode = True
    if exec_preflight not in sys.path:
        sys.path.append(exec_preflight)
    module = importlib.import_module("stage_b_controller")
    path = os.path.realpath(module.__file__)
    if path != os.path.join(exec_preflight, "stage_b_controller.py"):
        raise RuntimeError("CONTROLLER_MODULE_ORIGIN:" + path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return module, digest


def controller_errors(controller):
    return types.SimpleNamespace(
        CapabilityError=controller.NativeSamplerCapabilityError,
        ProcessAbsent=controller.NativeSamplerProcessAbsent,
        IdentityAwareExitRace=controller.NativeSamplerIdentityAwareExitRace)


def linux_backend(controller, source, parse_proc_stat, **kwargs):
    return LinuxProcSamplerBackend(source, kernel_thread_tolerant(parse_proc_stat),
                                   errors=controller_errors(controller), **kwargs)


def make_sampler(controller, root_pid, backend):
    """The controller's own sampler class, constructed with the Linux backend.

    Construction binds the dedicated-PGID authority (root must be its own
    process-group leader) exactly as on Darwin.
    """
    return controller.ProcessTreeRssSampler(root_pid, native_backend=backend)


def sample_once(sampler):
    """Run one sampler tick synchronously.

    `_sample()` is the exact body the sampler's own thread loop runs. It is
    driven from the caller's thread here because the pidfd acquisition
    precondition (one thread) and the development guard (no thread creation
    during custody) both exclude the sampler thread in this lifecycle.
    """
    sampler._sample()
    return {"sample_count": sampler.sample_count,
            "current_bytes": sampler.current_bytes,
            "current_root_bytes": sampler.current_root_bytes,
            "active_owned_pids": sorted(sampler.active_owned_pids),
            "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids)}


def sampler_report(sampler):
    return {"sample_count": sampler.sample_count,
            "maximum_bytes": sampler.maximum_bytes,
            "maximum_root_bytes": sampler.maximum_root_bytes,
            "owned_identities": {str(k): v for k, v in
                                 sampler.owned_identity_snapshot().items()},
            "identity_aware_exit_pids": sorted(sampler.identity_aware_exit_pids),
            "error": sampler.error,
            "authority": sampler.native_authority_snapshot()}
