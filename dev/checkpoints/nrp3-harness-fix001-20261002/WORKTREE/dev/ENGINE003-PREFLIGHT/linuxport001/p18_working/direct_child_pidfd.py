"""P17 direct-child custody primitives; native entry remains static-only in P17."""
from pathlib import Path

from ledger import require
from pidfd_primitives import (
    AcquisitionPolicy,
    NativeSyscalls,
    bounded_read,
    direct_child_stat,
    validate_acquisition_environment,
    wait_without_reaping,
)
from parsers import ProcStat


ACQUISITION_PRECONDITIONS = (
    "default SIGCHLD; SA_NOCLDWAIT absent; one native/Python thread; caller "
    "exclusively owns unreaped child since fork; no other reaper"
)
DIRECT_CHILD_SCOPE = "P01_DIRECT_CHILD_PRIMITIVE_ONLY_NOT_CENSUS_AUTHORITY"


class CapabilityAuthority:
    """Controller-held authority, independent of every capability being checked."""

    __slots__ = ("_controller", "identity")

    def __init__(self, controller):
        self._controller = controller
        self.identity = id(self)

    def controls(self, controller):
        return controller is self._controller

    def __getstate__(self):
        raise TypeError("CAPABILITY_AUTHORITY_NOT_SERIALIZABLE")


class _OpaqueOneUseCapability:
    """Process-local issuer-bound authority; deliberately not serializable."""

    __slots__ = ("_authority", "_payload", "_used", "identity")

    def __init__(self, authority, payload):
        require(type(authority) is CapabilityAuthority and type(payload) is dict,
                "CAPABILITY_AUTHORITY")
        self._authority = authority
        self._payload = dict(payload)
        self._used = False
        self.identity = id(self)

    @classmethod
    def _issue(cls, authority, payload):
        return cls(authority, payload)

    def validate(self, authority, **expected):
        require(type(authority) is CapabilityAuthority
                and authority is self._authority,
                "CAPABILITY_FOREIGN_AUTHORITY")
        for name, value in expected.items():
            require(name in self._payload and self._payload[name] is value
                    if name.endswith("_object") else self._payload.get(name) == value,
                    "CAPABILITY_" + name.upper())
        return True

    def consume(self, authority, **expected):
        self.validate(authority, **expected)
        require(self._used is False, "CAPABILITY_ALREADY_CONSUMED")
        self._used = True
        return True

    def validate_provenance(self, authority, **expected):
        """Rollback may validate issuance after proof consumed; this never reconsumes."""
        self.validate(authority, **expected)
        require(self._used is True, "PROOF_CAPABILITY_NOT_CONSUMED")
        return True

    @property
    def consumed(self):
        return self._used

    def summary(self):
        result = {
            key: (id(value) if key.endswith("_object") else value)
            for key, value in self._payload.items()
        }
        result.update({"identity": self.identity, "consumed": self._used})
        return result

    def __getstate__(self):
        raise TypeError("OPAQUE_CAPABILITY_NOT_SERIALIZABLE")

    def __reduce_ex__(self, protocol):
        raise TypeError("OPAQUE_CAPABILITY_NOT_SERIALIZABLE")


class PreOpenPrepareCapability(_OpaqueOneUseCapability):
    pass


class RawCaptureCapability(_OpaqueOneUseCapability):
    pass


class PostRegisterProofCapability(_OpaqueOneUseCapability):
    pass


class NonOwningViewCapability(_OpaqueOneUseCapability):
    pass


class PreparedDirectChild:
    """Validated pre-open facts. This object contains no FD or close authority."""

    __slots__ = (
        "pid", "expected_identity", "before_stat", "zombie_before",
        "pre_environment", "native_identity", "policy_identity",
        "prepare_capability_identity", "identity",
    )

    def __init__(self, pid, expected_identity, before_stat, zombie_before,
                 pre_environment, native_identity, policy_identity,
                 prepare_capability_identity):
        self.pid = pid
        self.expected_identity = tuple(expected_identity)
        self.before_stat = before_stat
        self.zombie_before = zombie_before
        self.pre_environment = pre_environment
        self.native_identity = native_identity
        self.policy_identity = policy_identity
        self.prepare_capability_identity = prepare_capability_identity
        self.identity = id(self)


class DirectChildProof:
    __slots__ = (
        "pid", "ppid", "starttime_ticks", "zombie_before", "zombie_after",
        "fdinfo_pid", "acquisition_preconditions", "scope", "identity",
    )

    def __init__(self, pid, ppid, starttime_ticks, zombie_before, zombie_after,
                 fdinfo_pid, acquisition_preconditions=ACQUISITION_PRECONDITIONS,
                 scope=DIRECT_CHILD_SCOPE):
        self.pid = pid
        self.ppid = ppid
        self.starttime_ticks = starttime_ticks
        self.zombie_before = zombie_before
        self.zombie_after = zombie_after
        self.fdinfo_pid = fdinfo_pid
        self.acquisition_preconditions = acquisition_preconditions
        self.scope = scope
        self.identity = id(self)

    def report(self):
        return {name: getattr(self, name) for name in (
            "pid", "ppid", "starttime_ticks", "zombie_before", "zombie_after",
            "fdinfo_pid", "acquisition_preconditions", "scope")}


class DirectChildPidfdView:
    """Non-owning alias: deliberately no close/context/destructor/receive/transfer."""

    __slots__ = ("token", "pid", "borrowed_fd", "proof", "identity")

    def __init__(self, token, pid, borrowed_fd, proof):
        require(type(token) is dict and type(pid) is int and not isinstance(pid, bool),
                "VIEW_IDENTITY")
        require(type(borrowed_fd) is int and borrowed_fd >= 0,
                "VIEW_BORROWED_FD")
        require(type(proof) is DirectChildProof and proof.pid == pid,
                "VIEW_PROOF")
        self.token = dict(token)
        self.pid = pid
        self.borrowed_fd = borrowed_fd
        self.proof = proof
        self.identity = id(self)

    def report(self):
        return {
            "token": dict(self.token), "pid": self.pid,
            "borrowed_fd": self.borrowed_fd, "proof": self.proof.report(),
            "non_owning": True,
        }


def prepare_direct_child(native: NativeSyscalls, pid: int, expected: ProcStat,
                         policy: AcquisitionPolicy,
                         prepare_capability: PreOpenPrepareCapability,
                         authority: CapabilityAuthority) -> PreparedDirectChild:
    """Exact P01 pre-open checks only; no FD is opened or returned here."""
    require(type(native) is NativeSyscalls, "EXACT_NATIVE_SYSCALLS")
    require(type(pid) is int and not isinstance(pid, bool) and 0 < pid < 2**31,
            "PIDFD_OPEN_ARGUMENT")
    require(type(expected) is ProcStat, "EXPECTED_PROCSTAT_TYPE")
    require(type(policy) is AcquisitionPolicy, "EXACT_ACQUISITION_POLICY")
    require(type(prepare_capability) is PreOpenPrepareCapability,
            "EXACT_PREPARE_CAPABILITY")
    prepare_capability.consume(authority,
                               native_object=native, policy_object=policy, pid=pid)
    observed = native.acquisition_environment()
    validate_acquisition_environment(policy, observed, native.no_cldwait)
    require(expected.pid == pid and expected.ppid == __import__("os").getpid(),
            "EXPECTED_DIRECT_CHILD")
    zombie_before = wait_without_reaping(pid)
    before = direct_child_stat(pid)
    expected_identity = (expected.pid, expected.ppid, expected.starttime_ticks)
    require((before.pid, before.ppid, before.starttime_ticks) == expected_identity,
            "CHILD_IDENTITY_CHANGED")
    return PreparedDirectChild(
        pid, expected_identity, before, zombie_before, observed,
        id(native), id(policy), prepare_capability.identity)


def capture_direct_child_open(native: NativeSyscalls, prepared: PreparedDirectChild,
                              raw_owner, capture_capability: RawCaptureCapability,
                              authority: CapabilityAuthority):
    """Delegate the single open to the provider so its field is first retention."""
    from integrated_native_effects import IntegratedNativeEffects
    require(type(native) is NativeSyscalls and type(prepared) is PreparedDirectChild,
            "CAPTURE_INPUT_TYPES")
    require(type(raw_owner) is IntegratedNativeEffects,
            "EXACT_DIRECT_CHILD_PROVIDER")
    require(type(capture_capability) is RawCaptureCapability,
            "EXACT_CAPTURE_CAPABILITY")
    capture_capability.consume(authority,
                               native_object=native, prepared_object=prepared,
                               provider_object=raw_owner)
    return raw_owner.acquire_direct_child_raw(prepared, capture_capability)


def prove_registered_direct_child(prepared: PreparedDirectChild,
                                  registered_custody, native: NativeSyscalls,
                                  policy: AcquisitionPolicy,
                                  capability: PostRegisterProofCapability,
                                  authority: CapabilityAuthority) -> DirectChildProof:
    """Consume proof authority once, then repeat all exact P01 post-open checks."""
    from integrated_native_effects import RegisteredDirectChildCustody
    require(type(prepared) is PreparedDirectChild
            and type(registered_custody) is RegisteredDirectChildCustody,
            "REGISTERED_PROOF_INPUTS")
    require(type(native) is NativeSyscalls and type(policy) is AcquisitionPolicy,
            "EXACT_PROOF_NATIVE_POLICY")
    require(type(capability) is PostRegisterProofCapability,
            "EXACT_PROOF_CAPABILITY")
    capability.consume(authority,
                       prepared_object=prepared,
                       custody_object=registered_custody,
                       native_object=native, policy_object=policy,
                       native_identity=id(native), policy_identity=id(policy))
    before = prepared.before_stat
    after = direct_child_stat(prepared.pid)
    require((after.pid, after.ppid, after.starttime_ticks)
            == (before.pid, before.ppid, before.starttime_ticks),
            "CHILD_IDENTITY_CHANGED")
    zombie_after = wait_without_reaping(prepared.pid)
    observed = native.acquisition_environment()
    validate_acquisition_environment(policy, observed, native.no_cldwait)
    value = bounded_read(Path("/proc/self/fdinfo") / str(registered_custody.fd), 8192)
    import re
    matches = re.findall(rb"^Pid:\s*([0-9]+)\s*$", value, re.MULTILINE)
    require(len(matches) == 1 and int(matches[0]) == prepared.pid,
            "PIDFD_INFO_BINDING")
    return DirectChildProof(
        prepared.pid, before.ppid, before.starttime_ticks,
        prepared.zombie_before, zombie_after, int(matches[0]))


def build_direct_child_view(proof: DirectChildProof, registered_custody,
                            view_capability: NonOwningViewCapability,
                            authority: CapabilityAuthority) -> DirectChildPidfdView:
    from integrated_native_effects import RegisteredDirectChildCustody
    require(type(proof) is DirectChildProof
            and type(registered_custody) is RegisteredDirectChildCustody,
            "VIEW_INPUT_TYPES")
    require(type(view_capability) is NonOwningViewCapability,
            "EXACT_VIEW_CAPABILITY")
    view_capability.consume(authority,
                            proof_object=proof,
                            custody_object=registered_custody)
    return DirectChildPidfdView(
        registered_custody.token, proof.pid, registered_custody.fd, proof)
