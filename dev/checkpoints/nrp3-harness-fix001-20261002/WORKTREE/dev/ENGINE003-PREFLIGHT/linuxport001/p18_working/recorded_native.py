"""P17 diagnostic recorder; diagnostics never acquire or close custody."""
from common import detached, raw_exception, raw_return
from ledger import require
from direct_child_pidfd import DirectChildPidfdView, DirectChildProof
from integrated_native_effects import RegisteredDirectChildCustody


class RecordedRegisteredNative:
    def __init__(self, diagnostic_callback):
        require(callable(diagnostic_callback), "DIAGNOSTIC_CALLBACK")
        self._diagnostic_callback = diagnostic_callback
        self._events = []
        self._raw_diagnostic_references = []
        self._last_unrecorded_diagnostic_reference = None

    def record_open_attempt(self, pid, flags):
        require(type(pid) is int and not isinstance(pid, bool)
                and 0 < pid < 2**31 and type(flags) is int and flags == 0,
                "PIDFD_OPEN_ATTEMPT_ARGUMENT")
        event = {
            "kind": "PIDFD_OPEN_ATTEMPT", "pid": pid, "flags": flags,
            "fd": None, "owns_fd": False,
        }
        self._events.append(detached(event))
        return detached(event)

    def record_registered_proven_return(self, registered_custody, proof, view):
        require(type(registered_custody) is RegisteredDirectChildCustody
                and registered_custody.registration_accepted is True
                and type(proof) is DirectChildProof
                and type(view) is DirectChildPidfdView
                and view.proof is proof
                and view.borrowed_fd == registered_custody.fd
                and view.token == registered_custody.token,
                "RETURN_AFTER_REGISTER_PROOF_VIEW")
        event = {
            "kind": "PIDFD_OPEN_RETURN",
            "token": detached(registered_custody.token),
            "fd": registered_custody.fd, "pid": proof.pid,
            "proof_identity": proof.identity, "view_identity": view.identity,
            "non_owning_view": True,
        }
        try:
            result = self._diagnostic_callback(detached(event))
            self._raw_diagnostic_references.append(result)
            observation = raw_return(result)
            self._events.append({
                "event": detached(event), "status": "PIDFD_OPEN_RETURN_RECORDED",
                "diagnostic_observation": detached(observation),
            })
        except BaseException as exc:
            self._last_unrecorded_diagnostic_reference = exc
            try:
                self._raw_diagnostic_references.append(exc)
                self._events.append({
                    "event": detached(event),
                    "status": "RETURN_DIAGNOSTIC_FAILED",
                    "diagnostic_observation": raw_exception(exc),
                    "custody_preserved": True, "view_preserved": True,
                    "fallback_close": False,
                })
            except BaseException:
                # The already-reachable custody and view remain authoritative.
                # Allocation/logging failure is not claimed to be infallibly recordable.
                pass
        return view

    def report(self):
        return {
            "events": detached(self._events),
            "raw_diagnostic_references_retained":
                len(self._raw_diagnostic_references),
            "last_unrecorded_diagnostic_reference_retained":
                self._last_unrecorded_diagnostic_reference is not None,
            "fallback_closes": 0,
            "claim": "DIAGNOSTIC_ONLY_NOT_CUSTODY_OR_NATIVE_AUTHORITY",
        }
