"""NRP-2: explicit opt-in Linux entry seam into the shared launch_request.

Supplies launch_request's existing injection points (sampler_backend_factory,
run_context_factory, dispatch_latch) from caller-INJECTED ports only.  It
selects no backend and no termination primitive (D-Q3 is undecided): every
port, the clock and the sleep are the caller's.  Without the exact opt-in
token (or with any port missing) the sampler factory raises
NativeSamplerCapabilityError, and with a NoTerminationAuthority provider the
run-context factory raises it; launch_request turns both into its ordinary
pre-effect SB_STOP_SAMPLER_CAPABILITY refusal (SAMPLER_CAPABILITY resp.
RUN_CONTEXT admission; the cause is chained, nothing is spawned; on a ticket
path the controller's own CLOSED_ZERO_EFFECT + STOP is the durable refusal).
The defaults of the shared controller (_sampler_capability_backend,
default_run_context) are unchanged.
RunContext.admit/termination.preflight capability checks still run inside
launch_request; the final commit service stays the caller's
(commit_current_dispatch for the CLI coordinator, the orchestrator adapter
for a ticket).

ModeledRootIdentity labels an explicitly injected modeled root identity
(provenance MODELED_INJECTED).  No native boot/starttime identity is read or
invented here.  The recorded token binds modeled reconciliation assertions to
the dispatch; it is not a per-descendant/lease identity and proves no real
resource fact.  A provider without root_identity (every current real
provider) records identity None, and such a dispatch has no positive
post-effect reconciliation path (deliberate fail-closed limitation; see
stage_b_dispatch_journal's recorded-identity note).
"""

OPT_IN = "NRP2_LINUX_SHARED_CONTROLLER_ENTRY_EXPLICIT_OPT_IN"


class ModeledRootIdentity:
    """Termination provider wrapper adding root_identity(context) from an
    injected function; every controller-protocol call is delegated."""

    def __init__(self, provider, identity_of):
        self._provider, self._identity_of = provider, identity_of
        self._process = None

    def __getattr__(self, name):          # preflight, teardown, group_signal ...
        return getattr(self._provider, name)

    def acquire_root(self, process, context):
        authority = self._provider.acquire_root(process, context)
        self._process = process
        return authority

    def root_identity(self, context):
        if self._process is None:
            return None
        token = self._identity_of(self._process)
        return None if token is None else {"token": str(token),
                                           "provenance": "MODELED_INJECTED"}


class LinuxControllerEntry:
    def __init__(self, controller, *, opt_in=None, capability_backend=None,
                 termination_factory=None, clock=None, sleep=None,
                 run_id="STAGEB_REQUEST", generation=1, dispatch_latch=None,
                 modeled_identity=None):
        self.C = controller
        self.opt_in, self.backend = opt_in, capability_backend
        self.termination_factory, self.clock, self.sleep = termination_factory, clock, sleep
        self.run_id, self.generation = run_id, generation
        self.latch = controller.DispatchLatch() if dispatch_latch is None else dispatch_latch
        self.modeled_identity = modeled_identity
        self.contexts = []

    def refusal(self):
        if self.opt_in != OPT_IN:
            return "LINUX_ENTRY_NOT_OPTED_IN"
        missing = [name for name, value in (
            ("capability_backend", self.backend),
            ("termination_factory", self.termination_factory),
            ("clock", self.clock), ("sleep", self.sleep)) if value is None]
        return "LINUX_ENTRY_PORT_NOT_INJECTED:" + ",".join(missing) if missing else None

    def sampler_backend_factory(self):
        refused = self.refusal()
        if refused is not None:
            raise self.C.NativeSamplerCapabilityError(refused)
        return self.backend

    def run_context_factory(self, backend):
        termination = self.termination_factory()
        if isinstance(termination, self.C.NoTerminationAuthority):
            raise self.C.NativeSamplerCapabilityError("LINUX_ENTRY_NO_TERMINATION_AUTHORITY")
        if self.modeled_identity is not None:
            termination = ModeledRootIdentity(termination, self.modeled_identity)
        context = self.C.RunContext(
            run_id=self.run_id, generation=self.generation, native_backend=backend,
            termination=termination, clock=self.clock, sleep=self.sleep,
            dispatch_latch=self.latch)
        self.contexts.append(context)
        return context

    def launch_kwargs(self):
        return {"sampler_backend_factory": self.sampler_backend_factory,
                "run_context_factory": self.run_context_factory,
                "dispatch_latch": self.latch}
