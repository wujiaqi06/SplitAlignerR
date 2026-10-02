"""P17 direct-child controller: pure transition core plus static-only native shell."""
from ledger import Ledger, freeze, label, require, token_types
from common import detached, raw_exception
from direct_child_pidfd import (
    CapabilityAuthority,
    DirectChildPidfdView,
    DirectChildProof,
    NonOwningViewCapability,
    PostRegisterProofCapability,
    PreOpenPrepareCapability,
    PreparedDirectChild,
    RawCaptureCapability,
    build_direct_child_view,
    capture_direct_child_open,
    prepare_direct_child,
    prove_registered_direct_child,
)
from integrated_native_adapter import PureRollbackAdapter
from integrated_native_effects import (
    IntegratedNativeEffects,
    PureCustodyTransitions,
    RawDirectChildCustody,
    RegisteredDirectChildCustody,
)
from runtime_bindings import RuntimeBindings


AUTHENTIC_CAUGHT_EXCEPTION = "AUTHENTIC_CAUGHT_EXCEPTION"
SUPPLIED_STATIC_REJECTION = "SUPPLIED_STATIC_REJECTION"


class PrimaryFailureRecord:
    """Origin-aware record retaining the raw primary object separately.

    This object is the only primary-failure authority. `report()` produces a
    detached dictionary for evidence and regression comparison; a report never
    carries authority and is never accepted by the rollback consumers.
    """

    def __init__(self, raw_primary_reference, origin, phase, kind,
                 exception_fqname, code, operation, error_number, args,
                 diagnostic, context, pid, borrowed_fd, token,
                 prepared_identity, proof_capability_identity,
                 runtime_failure_observed, static_fixture_only):
        self.raw_primary_reference = raw_primary_reference
        self.raw_exception_context_reference = getattr(
            raw_primary_reference, "__context__", None)
        self.raw_exception_cause_reference = getattr(
            raw_primary_reference, "__cause__", None)
        self.raw_exception_traceback_reference = getattr(
            raw_primary_reference, "__traceback__", None)
        self.origin = origin
        self.phase = phase
        self.kind = kind
        self.exception_fqname = exception_fqname
        self.code = code
        self.operation = operation
        self.errno = error_number
        self.args = tuple(args)
        self.diagnostic = diagnostic
        self.context = detached(context)
        self.pid = pid
        self.borrowed_fd = borrowed_fd
        self.token = detached(token)
        self.prepared_identity = prepared_identity
        self.proof_capability_identity = proof_capability_identity
        self.raw_primary_reference_retained = True
        self.runtime_failure_observed = runtime_failure_observed
        self.static_fixture_only = static_fixture_only
        self.primary_error_preserved = True
        self.rollback = None
        self.rollback_confirmed = False
        self.automatic_retry_actions = []

    def report(self):
        return {
            "origin": self.origin, "phase": self.phase, "kind": self.kind,
            "exception_fqname": self.exception_fqname, "code": self.code,
            "operation": self.operation, "errno": self.errno,
            "args": list(self.args), "diagnostic": self.diagnostic,
            "context": detached(self.context), "pid": self.pid,
            "borrowed_fd": self.borrowed_fd, "token": detached(self.token),
            "prepared_identity": self.prepared_identity,
            "proof_capability_identity": self.proof_capability_identity,
            "raw_primary_reference_retained": self.raw_primary_reference_retained,
            "raw_exception_context_reference_retained":
                self.raw_exception_context_reference is not None,
            "raw_exception_cause_reference_retained":
                self.raw_exception_cause_reference is not None,
            "raw_exception_traceback_reference_retained":
                self.raw_exception_traceback_reference is not None,
            "runtime_failure_observed": self.runtime_failure_observed,
            "static_fixture_only": self.static_fixture_only,
            "primary_error_preserved": self.primary_error_preserved,
            "rollback": detached(self.rollback) if self.rollback else None,
            "rollback_confirmed": self.rollback_confirmed,
            "automatic_retry_actions": [],
        }


class PureDirectChildController:
    """Actual pure state-transition core used after production identity checks."""

    def __init__(self, ledger, provider_identity, source_pins):
        require(type(ledger) is Ledger and type(provider_identity) is int
                and type(source_pins) is dict, "PURE_CONTROLLER_BINDING")
        self.ledger = ledger
        self.provider_identity = provider_identity
        self.source_pins = dict(source_pins)
        self._key = object()
        self._capability_authority = CapabilityAuthority(self)
        self._expected_slots = ledger.admission_report()["submission_slots"]
        self._expected_history = detached(ledger.report()["history"])
        self._holds = frozenset()
        self._reservation_id = None
        self._reservation_remaining = 0
        self._row = None
        self._prepared = None
        self._native_object = None
        self._policy_object = None
        self._provider_object = None
        self._prepare_capability = None
        self._capture_capability = None
        self._proof_capability = None
        self._view_capability = None
        self._proof = "NOT_STARTED"
        self._view = None
        self._primary_record = None
        self._primary = "NONE"
        self._rollback = "NOT_REQUESTED"
        self._adapter = None
        self._stop = False
        self._rollback_authority_used = False
        self._last_raw_primary_reference = None
        self._last_raw_primary_token = None
        self._raw_primary_references = {}
        self._secondary_failure_references = []
        self._secondary_failures = []
        self._operations = []

    def _accept_public(self):
        self._expected_slots = self.ledger.admission_report()["submission_slots"]
        self._expected_history = detached(self.ledger.report()["history"])

    def _sync(self):
        if (self._expected_slots != self.ledger.admission_report()["submission_slots"]
                or self._expected_history != self.ledger.report()["history"]):
            self._holds |= frozenset(("EXTERNAL_PUBLIC_SUBMISSION",
                                      "STOP_FURTHER_EFFECTS"))
            self._stop = True
            return False
        return True

    def _require_effect_eligibility(self, allowed_holds=()):
        synchronized = self._sync()
        fatal = set(self._holds) - set(allowed_holds)
        if not synchronized or fatal or self._stop:
            self._stop = True
            require(False, "EFFECT_STOPPED_BY_HOLD")
        return True

    def _primary_rollback_holds(self):
        if self._primary_record is None:
            return frozenset()
        origin = ("AUTHENTIC_POST_OPEN_PROOF_FAILURE"
                  if self._primary_record.origin == AUTHENTIC_CAUGHT_EXCEPTION
                  else "SUPPLIED_POST_OPEN_PROOF_REJECTION")
        return frozenset(("PRIMARY_PROOF_REJECTION",
                          "PRIMARY_ERROR_RETAINED", origin))

    def budget(self):
        self._sync()
        report = self.ledger.report()
        counts = report["counts"]
        debt = 2 * counts["PENDING_OWNERSHIP"] + counts["ATTEMPTED_WITHOUT_COMPLETION"]
        admission = self.ledger.admission_report()
        credits = 3 * self._reservation_remaining
        return {
            "registered_lifetime": report["registered_total"],
            "resource_limit": 8,
            "public_submissions_used": admission["submission_slots"],
            "public_submission_limit": admission["submission_limit"],
            "public_submissions_remaining": admission["remaining_submission_slots"],
            "reserved_resources": self._reservation_remaining,
            "reserved_submission_credits": credits,
            "cleanup_debt": debt,
            "unreserved_submission_slots":
                admission["remaining_submission_slots"] - credits - debt,
        }

    def _snapshot(self):
        self._sync()
        report = self.ledger.report()
        budget = self.budget()
        counts = report["counts"]
        custody = "NONE" if self._row is None else self._row.status
        confirmed = bool(
            report["all_close_outcomes_confirmed"]
            and custody == "CONFIRMED_CLOSE"
            and not self._holds and self._primary_record is None)
        return {
            "accepted_event_count": report["accepted_event_count"],
            "attempted": counts["ATTEMPTED_WITHOUT_COMPLETION"],
            "cleanup_debt": budget["cleanup_debt"],
            "confirmed": counts["CONFIRMED_CLOSE"],
            "controller_confirmed": confirmed,
            "custody": custody,
            "history_event_ids": [item["event_id"] for item in report["history"]],
            "holds": sorted(self._holds),
            "pending": counts["PENDING_OWNERSHIP"],
            "primary": self._primary,
            "proof": self._proof,
            "registered_lifetime": report["registered_total"],
            "remaining_submission_slots": budget["public_submissions_remaining"],
            "reservation_remaining": self._reservation_remaining,
            "reserved_credits": budget["reserved_submission_credits"],
            "rollback": self._rollback,
            "stop": self._stop,
            "submission_slots": budget["public_submissions_used"],
            "unreserved_submission_slots": budget["unreserved_submission_slots"],
            "unresolved": counts["UNRESOLVED_ERROR"],
        }

    def snapshot(self):
        self._sync()
        return detached(self._snapshot())

    def _record(self, operation, result):
        self._operations.append({
            "index": len(self._operations), "operation": operation,
            "result": detached(result), "after": self.snapshot(),
        })
        return result

    def issue_prepare_capability(self, native_object, policy_object, pid):
        self._sync()
        self._require_effect_eligibility()
        require(self._prepare_capability is None and type(pid) is int
                and not isinstance(pid, bool), "PREPARE_CAPABILITY_SEQUENCE")
        self._native_object = native_object
        self._policy_object = policy_object
        self._prepare_capability = PreOpenPrepareCapability._issue(
            self._capability_authority, {
                "controller_object": self, "native_object": native_object,
                "policy_object": policy_object, "native_identity": id(native_object),
                "policy_identity": id(policy_object), "pid": pid})
        return self._prepare_capability

    def issue_capture_capability(self, prepared, native_object,
                                 provider_object):
        self._sync()
        self._require_effect_eligibility()
        require(self._prepare_capability is not None
                and self._prepare_capability.consumed
                and self._capture_capability is None
                and type(prepared) is PreparedDirectChild
                and prepared.native_identity == id(native_object)
                and provider_object is not None,
                "CAPTURE_CAPABILITY_AFTER_PREPARED")
        self._prepared = prepared
        self._provider_object = provider_object
        self._capture_capability = RawCaptureCapability._issue(
            self._capability_authority, {
                "controller_object": self, "native_object": native_object,
                "prepared_object": prepared, "provider_object": provider_object,
                "native_identity": id(native_object),
                "prepared_identity": prepared.identity,
                "provider_identity": id(provider_object)})
        return self._capture_capability

    def issue_view_capability(self, proof, registered_custody):
        self._sync()
        self._require_effect_eligibility()
        require(type(proof) is DirectChildProof
                and registered_custody is self._row
                and self._proof_capability is not None
                and self._proof_capability.consumed
                and self._view_capability is None,
                "VIEW_CAPABILITY_AFTER_PROOF")
        self._view_capability = NonOwningViewCapability._issue(
            self._capability_authority, {
                "controller_object": self, "proof_object": proof,
                "custody_object": registered_custody,
                "proof_identity": proof.identity,
                "custody_identity": id(registered_custody)})
        return self._view_capability

    def capability_flow_report(self):
        return {
            "authority_identity": self._capability_authority.identity,
            "authority_controls_controller":
                self._capability_authority.controls(self),
            "prepare": self._prepare_capability.summary()
                if self._prepare_capability else None,
            "capture": self._capture_capability.summary()
                if self._capture_capability else None,
            "proof": self._proof_capability.summary()
                if self._proof_capability else None,
            "view": self._view_capability.summary()
                if self._view_capability else None,
            "order": ["PREPARE", "PREPARED", "CAPTURE", "REGISTER",
                      "PROOF", "PROOF_CONSUMED", "VIEW"],
        }

    def reserve(self, reservation_id):
        self._sync()
        self._require_effect_eligibility()
        require(not self._holds and self._reservation_id is None
                and self._row is None, "RESERVATION_NOT_ADMITTED")
        label(reservation_id, "RESERVATION_ID")
        budget = self.budget()
        require(budget["registered_lifetime"] + 1 <= 8
                and budget["unreserved_submission_slots"] >= 3,
                "RESERVATION_BUDGET")
        self._reservation_id = reservation_id
        self._reservation_remaining = 1
        self._proof = "PRE_OPEN_ACCEPTED"
        return self._record("RESERVE", {
            "admitted": True, "resources": 1, "credits": 3,
            "reservation_id": reservation_id,
        })

    def attach_raw_custody(self, prepared, row, post_open_pending=True):
        self._sync()
        self._require_effect_eligibility()
        require(not self._holds and self._reservation_remaining == 1
                and self._row is None and type(prepared) is PreparedDirectChild
                and type(row) is RawDirectChildCustody
                and row.provider_identity == self.provider_identity
                and row.prepared_identity == prepared.identity,
                "RAW_CUSTODY_RECONCILIATION")
        self._prepared = prepared
        self._row = row
        self._proof = ("POST_OPEN_NOT_ELIGIBLE" if post_open_pending
                       else "PRE_OPEN_ACCEPTED")
        self._row.status = "RAW_PROVIDER_FD_" + str(row.fd)
        return self._record("RAW_CAPTURE", row.report())

    def register_captured(self, event_id):
        self._sync()
        self._require_effect_eligibility()
        baseline = self.registration_submission_baseline()
        request = {
            "event_id": event_id, "kind": "REGISTER",
            "token": detached(self._row.token), "fd": self._row.fd,
        }
        reply = self.ledger.submit(detached(request))
        return self.reconcile_registration_result(request, reply, baseline)

    def registration_submission_baseline(self):
        self._sync()
        self._require_effect_eligibility()
        require(self._row is not None and type(self._row) is RawDirectChildCustody
                and self._reservation_remaining == 1,
                "REGISTER_NOT_ELIGIBLE")
        return {"submission_slots": self._expected_slots,
                "accepted_history": detached(self._expected_history)}

    def reconcile_registration_result(self, request, reply, baseline):
        require(type(baseline) is dict and set(baseline) == {
            "submission_slots", "accepted_history"}
            and baseline["submission_slots"] == self._expected_slots
            and baseline["accepted_history"] == self._expected_history,
            "REGISTRATION_BASELINE_IDENTITY")
        admission = self.ledger.admission_report()
        report = self.ledger.report()
        require(type(request) is dict and request.get("kind") == "REGISTER"
                and request.get("token") == self._row.token
                and type(reply) is dict
                and reply.get("submission_slot") == baseline["submission_slots"] + 1
                and reply.get("admission") == admission
                and admission["submission_slots"] == baseline["submission_slots"] + 1,
                "REGISTRATION_ACTUAL_REPLY_RECONCILIATION")
        if reply.get("accepted") is True:
            require(request.get("fd") == self._row.fd
                    and report["history"] == baseline["accepted_history"] + [request],
                    "ACCEPTED_REGISTER_EXACT_CAPTURED_FD")
        else:
            require(report["history"] == baseline["accepted_history"],
                    "REJECTED_REGISTER_HISTORY_UNCHANGED")
        self._accept_public()
        result = {"request": detached(request), "reply": detached(reply)}
        if reply["accepted"]:
            prior_identity = id(self._row)
            PureCustodyTransitions.mark_registered(
                self._row, request, reply, self._reservation_id,
                self.provider_identity)
            require(id(self._row) == prior_identity, "CUSTODY_ROW_TRANSFER")
            self._reservation_remaining = 0
            self._proof = "CAPABILITY_ELIGIBLE"
            self._row.status = "REGISTERED_PENDING_FD_" + str(self._row.fd)
        else:
            PureCustodyTransitions.retain_unregistered(
                self._row, request, reply, self.provider_identity)
            self._row.status = "REGISTER_REJECTED_UNREGISTERED_FD_" + str(self._row.fd)
            self._proof = "NOT_STARTED_NO_RETURN"
            self._rollback = "NOT_ADMITTED"
            self._holds |= frozenset((
                "REGISTRATION_REJECTED", "UNREGISTERED_CUSTODY",
                "STOP_FURTHER_EFFECTS"))
            self._stop = True
        return self._record("REGISTER", result)

    def derive_post_register_proof_capability(self, native_object,
                                              policy_object):
        self._sync()
        self._require_effect_eligibility()
        native_identity = id(native_object)
        policy_identity = id(policy_object)
        require(native_object is self._native_object
                and policy_object is self._policy_object
                and type(self._row) is RegisteredDirectChildCustody
                and self._row.provider_identity == self.provider_identity
                and self._row.registration_accepted is True
                and self._row.committed_reservation_id == self._reservation_id
                and self._reservation_remaining == 0
                and self._prepared is not None
                and self._row.prepared_identity == self._prepared.identity
                and self._row.native_identity == native_identity
                and self._prepared.native_identity == native_identity
                and self._prepared.policy_identity == policy_identity
                and self._proof_capability is None,
                "PROOF_CAPABILITY_IDENTITY_RECONCILIATION")
        obligations = [item for item in self.ledger.report()["obligations"]
                       if item["token"] == self._row.token]
        require(len(obligations) == 1
                and obligations[0]["fd"] == self._row.fd
                and obligations[0]["state"] == "PENDING_OWNERSHIP"
                and obligations[0]["registration_event_id"]
                    == self._row.registration_event_id,
                "PROOF_CAPABILITY_LEDGER_RECONCILIATION")
        payload = {
            "controller_object": self,
            "provider_identity": self.provider_identity,
            "ledger_object": self.ledger,
            "prepared_object": self._prepared,
            "custody_object": self._row,
            "native_object": native_object,
            "policy_object": policy_object,
            "native_identity": native_identity,
            "policy_identity": policy_identity,
            "token": detached(self._row.token), "borrowed_fd": self._row.fd,
            "registration_event_id": self._row.registration_event_id,
            "reservation_id": self._reservation_id,
            "issuance_snapshot_digest": repr(self.snapshot()),
        }
        self._proof_capability = PostRegisterProofCapability._issue(
            self._capability_authority, payload)
        return self._proof_capability

    def accept_supplied_proof_and_view(self, capability, proof_data,
                                       native_object, policy_object):
        self._sync()
        self._require_effect_eligibility()
        require(type(capability) is PostRegisterProofCapability
                and capability is self._proof_capability
                and type(proof_data) is dict,
                "SUPPLIED_PROOF_INPUT")
        capability.consume(
            self._capability_authority,
            controller_object=self, ledger_object=self.ledger,
            prepared_object=self._prepared, custody_object=self._row,
            native_object=native_object, policy_object=policy_object,
            native_identity=id(native_object),
            policy_identity=id(policy_object),
            token=self._row.token, borrowed_fd=self._row.fd,
            registration_event_id=self._row.registration_event_id,
            reservation_id=self._reservation_id)
        proof = DirectChildProof(**proof_data)
        require(proof.pid == self._prepared.pid
                and proof.fdinfo_pid == self._prepared.pid,
                "SUPPLIED_PROOF_DECLARED_PREMISE")
        view_capability = self.issue_view_capability(proof, self._row)
        view_capability.consume(
            self._capability_authority, controller_object=self,
            proof_object=proof, custody_object=self._row,
            proof_identity=proof.identity, custody_identity=id(self._row))
        view = DirectChildPidfdView(
            self._row.token, proof.pid, self._row.fd, proof)
        self._view = view
        self._proof = "ACCEPTED_RETURN_ELIGIBLE"
        self._row.status = "REGISTERED_PENDING_FD_" + str(self._row.fd) + "_NONOWNING_VIEW"
        self._record("SUPPLIED_PROOF_AND_VIEW", {
            "proof": proof.report(), "view": view.report(),
            "native_identity_validity": "DECLARED_SUPPLIED_PREMISE",
            "real_proof_executed": False,
        })
        return view

    def _log_primary_report(self, record):
        """Log the primary report separately from the authority object.

        Report formatting is fallible and carries no authority. If it fails
        after the record exists, the retained record is neither replaced nor
        discarded: the formatting failure reference is retained and a bounded
        non-formatting operation row is appended instead.
        """
        try:
            return self._record("CAPTURE_PRIMARY_FAILURE", record.report())
        except BaseException as report_formatting_failure:
            self._secondary_failure_references.append(report_formatting_failure)
            self._operations.append({
                "index": len(self._operations),
                "operation": "CAPTURE_PRIMARY_FAILURE_REPORT_UNFORMATTED",
                "result": {
                    "raw_primary_reference_retained": True,
                    "primary_error_preserved": True,
                    "report_carries_no_authority": True,
                    "report_formatting_failure_type":
                        type(report_formatting_failure).__name__,
                },
                "after": None,
            })
            return None

    def capture_primary_failure(self, token, caught_or_supplied, origin,
                                phase, context, proof_capability):
        """Retain the raw primary and return the exact PrimaryFailureRecord.

        The returned object is `self._primary_record` itself and is the only
        value the rollback consumers accept. The `CAPTURE_PRIMARY_FAILURE`
        report is logged separately by `_log_primary_report`.
        """
        self._last_raw_primary_reference = caught_or_supplied
        self._last_raw_primary_token = token
        self._raw_primary_references[freeze(token)] = caught_or_supplied
        self._sync()
        self._require_effect_eligibility()
        raw_primary_reference = self._raw_primary_references[freeze(token)]
        require(raw_primary_reference is caught_or_supplied
                and token == self._row.token
                and type(self._row) is RegisteredDirectChildCustody
                and type(proof_capability) is PostRegisterProofCapability
                and proof_capability is self._proof_capability,
                "PRIMARY_CUSTODY_AND_CAPABILITY")
        if not proof_capability.consumed:
            proof_capability.consume(
                self._capability_authority,
                controller_object=self, ledger_object=self.ledger,
                prepared_object=self._prepared, custody_object=self._row,
                native_object=self._native_object,
                policy_object=self._policy_object,
                native_identity=id(self._native_object),
                policy_identity=id(self._policy_object),
                token=self._row.token, borrowed_fd=self._row.fd,
                registration_event_id=self._row.registration_event_id,
                reservation_id=self._reservation_id)
        else:
            proof_capability.validate_provenance(
                self._capability_authority,
                controller_object=self, ledger_object=self.ledger,
                prepared_object=self._prepared, custody_object=self._row,
                native_object=self._native_object,
                policy_object=self._policy_object)
        if origin == SUPPLIED_STATIC_REJECTION:
            require(type(caught_or_supplied) is dict
                    and caught_or_supplied.get("origin") == origin
                    and caught_or_supplied.get("phase") == phase
                    and caught_or_supplied.get("runtime_failure_observed") is False
                    and caught_or_supplied.get("static_fixture_only") is True,
                    "SUPPLIED_PRIMARY_ORIGIN")
            exception_fqname = None
            code = caught_or_supplied.get("code")
            operation = None
            error_number = None
            args = ()
            diagnostic = caught_or_supplied.get("diagnostic")
            runtime_observed = False
            fixture_only = True
        else:
            require(origin == AUTHENTIC_CAUGHT_EXCEPTION
                    and isinstance(caught_or_supplied, BaseException),
                    "AUTHENTIC_PRIMARY_ORIGIN")
            exception_fqname = (type(caught_or_supplied).__module__ + "."
                                + type(caught_or_supplied).__qualname__)
            code = getattr(caught_or_supplied, "code", None)
            operation = getattr(caught_or_supplied, "operation", None)
            error_number = getattr(caught_or_supplied, "errno", None)
            args = caught_or_supplied.args
            diagnostic = str(caught_or_supplied)
            runtime_observed = True
            fixture_only = False
        # The raw primary is already retained above, before this construction
        # and before any formatting. PrimaryFailureRecord construction is the
        # one remaining fallible step that precedes the authority object. A
        # failure inside it stays bounded and unresolved: the raw primary and
        # its token remain retained, no second record is constructed, no
        # substitute authority is fabricated, and the failure propagates.
        record = PrimaryFailureRecord(
            raw_primary_reference, origin, phase,
            caught_or_supplied.get("kind") if type(caught_or_supplied) is dict
                else "CAUGHT_EXCEPTION",
            exception_fqname, code, operation, error_number, args,
            diagnostic, context, self._prepared.pid, self._row.fd,
            self._row.token, self._prepared.identity,
            proof_capability.identity, runtime_observed, fixture_only)
        self._primary_record = record
        self._primary = origin + "_RETAINED"
        self._proof = "REJECTED_NO_RETURN"
        self._rollback = "REQUIRED"
        origin_hold = ("AUTHENTIC_POST_OPEN_PROOF_FAILURE"
                       if origin == AUTHENTIC_CAUGHT_EXCEPTION
                       else "SUPPLIED_POST_OPEN_PROOF_REJECTION")
        self._holds |= frozenset((
            "PRIMARY_PROOF_REJECTION", origin_hold, "PRIMARY_ERROR_RETAINED"))
        self._log_primary_report(record)
        return record

    def _callback_binding(self):
        return {
            "scope": "P17_DIRECT_CHILD_PROVIDER_CUSTODY",
            "policy": "PY38_OS_CLOSE_NONE", "token": detached(self._row.token),
            "fd": self._row.fd, "provider_identity": self.provider_identity,
            "row_identity": id(self._row),
            "callback_source_sha256": self.source_pins["integrated_native_effects.py"],
            "policy_source_sha256": self.source_pins["STATIC_CHECKLIST.json"],
        }

    def begin_close(self, attempt_id, begin_event_id, rollback=False):
        self._sync()
        allowed_holds = self._primary_rollback_holds() if rollback else frozenset()
        self._require_effect_eligibility(allowed_holds)
        require(not self._stop and type(self._row) is RegisteredDirectChildCustody
                and self._adapter is None, "BEGIN_CLOSE_ELIGIBILITY")
        if rollback:
            require(self._primary_record is not None
                    and self._proof_capability.consumed
                    and self._rollback_authority_used is False,
                    "ONE_ATTEMPT_ROLLBACK_AUTHORITY")
            self._proof_capability.validate_provenance(
                self._capability_authority,
                controller_object=self, ledger_object=self.ledger,
                prepared_object=self._prepared, custody_object=self._row,
                native_object=self._native_object,
                policy_object=self._policy_object)
            self._rollback_authority_used = True
        else:
            require(self._primary_record is None
                    and self._proof == "ACCEPTED_RETURN_ELIGIBLE",
                    "NORMAL_CLOSE_AFTER_VIEW")
        self._adapter = PureRollbackAdapter(
            self.ledger, self._callback_binding(), self.source_pins)
        reply = self._adapter.begin(self._row.token, attempt_id, begin_event_id)
        self._accept_public()
        if reply["accepted"]:
            self._row.status = "REGISTERED_ATTEMPTED_FD_" + str(self._row.fd)
            if rollback:
                self._rollback = "BEGIN_ACCEPTED"
        else:
            require(rollback, "NORMAL_BEGIN_REJECTED")
            self._rollback = "BEGIN_REJECTED_NO_CALLBACK"
            self._holds |= frozenset((
                "ROLLBACK_BEGIN_REJECTED", "CLOSE_UNCONFIRMED",
                "STOP_FURTHER_EFFECTS"))
            self._stop = True
        return self._record("ROLLBACK_BEGIN" if rollback else "BEGIN", reply)

    def invoke_and_normalize(self, callback, rollback=False):
        self._sync()
        allowed_holds = self._primary_rollback_holds() if rollback else frozenset()
        self._require_effect_eligibility(allowed_holds)
        require(self._adapter is not None and not self._stop,
                "CALLBACK_PHASE_ELIGIBILITY")
        normalization = self._adapter.invoke_and_normalize(callback)
        if normalization["valid"] is not True:
            self._row.status = "REGISTERED_ATTEMPTED_INVALID_RAW_RETAINED"
            self._rollback = "INVALID_NORMALIZATION_NO_COMPLETE_NO_RETRY"
            self._holds |= frozenset((
                "INVALID_NATIVE_OBSERVATION", "CLOSE_UNCONFIRMED",
                "STOP_FURTHER_EFFECTS"))
            self._stop = True
            if rollback and self._primary_record is not None:
                self._primary_record.rollback = self._adapter.report()
            return self._record("ROLLBACK_INVALID_NORMALIZATION"
                                if rollback else "INVALID_NORMALIZATION",
                                normalization)
        if normalization["model_outcome"]["result"] == "SUCCESS":
            self._row.status = "REGISTERED_ATTEMPTED_RAW_NONE_RETAINED"
            if rollback:
                self._rollback = "RAW_SUCCESS_RETAINED"
        else:
            self._row.status = ("REGISTERED_ATTEMPTED_RAW_OSERROR_"
                                + str(normalization["model_outcome"]["errno"])
                                + "_RETAINED")
            if rollback:
                self._rollback = "RAW_ERROR_RETAINED"
        return self._record("ROLLBACK_CALLBACK_AND_NORMALIZE"
                            if rollback else "CALLBACK_AND_NORMALIZE",
                            normalization)

    def complete_close(self, complete_event_id, rollback=False):
        self._sync()
        allowed_holds = self._primary_rollback_holds() if rollback else frozenset()
        self._require_effect_eligibility(allowed_holds)
        require(self._adapter is not None and not self._stop,
                "COMPLETE_PHASE_ELIGIBILITY")
        reply = self._adapter.complete(complete_event_id)
        self._accept_public()
        outcome = self._adapter.normalization["model_outcome"]
        if not reply["accepted"]:
            self._row.status = "REGISTERED_ATTEMPTED_RAW_NONE_NOT_LEDGER_CONFIRMED"
            self._rollback = "COMPLETE_REJECTED_NO_RETRY"
            self._holds |= frozenset((
                "ROLLBACK_COMPLETE_REJECTED", "CLOSE_UNCONFIRMED",
                "STOP_FURTHER_EFFECTS"))
        elif outcome["result"] == "SUCCESS":
            self._row.status = "CONFIRMED_CLOSE"
            if rollback:
                self._rollback = "CONFIRMED_PRIMARY_PRESERVED"
                self._primary_record.rollback_confirmed = True
        else:
            self._row.status = "REGISTERED_UNRESOLVED_ERROR"
            self._rollback = "UNRESOLVED_ERROR_NO_RETRY"
            self._holds |= frozenset(("CLOSE_UNCONFIRMED", "STOP_FURTHER_EFFECTS"))
        self._stop = True
        if rollback:
            self._primary_record.rollback = self._adapter.report()
        return self._record("ROLLBACK_COMPLETE" if rollback else "COMPLETE", reply)

    def retain_secondary_rollback_failure(self, primary_failure, phase,
                                          secondary_failure):
        self._secondary_failure_references.append(secondary_failure)
        require(type(primary_failure) is PrimaryFailureRecord
                and primary_failure is self._primary_record
                and isinstance(secondary_failure, BaseException),
                "SECONDARY_FAILURE_PRIMARY_PROVENANCE")
        try:
            raw_observation = raw_exception(secondary_failure)
        except BaseException as formatting_failure:
            self._secondary_failure_references.append(formatting_failure)
            raw_observation = {
                "kind": "UNFORMATTED_SECONDARY_EXCEPTION",
                "python_type": type(secondary_failure).__name__,
                "formatting_failure_type": type(formatting_failure).__name__,
            }
        record = {
            "phase": phase, "raw_reference_retained": True,
            "raw_observation": raw_observation,
            "primary_replaced": False, "rollback_confirmed": False,
            "automatic_retry_actions": [],
        }
        self._secondary_failures.append(record)
        self._rollback = "SECONDARY_FAILURE_PRIMARY_PRESERVED"
        self._holds |= frozenset((
            "SECONDARY_ROLLBACK_FAILURE", "CLOSE_UNCONFIRMED",
            "STOP_FURTHER_EFFECTS"))
        self._stop = True
        try:
            adapter_report = self._adapter.report() if self._adapter else None
        except BaseException as reporting_failure:
            self._secondary_failure_references.append(reporting_failure)
            adapter_report = {"reporting_failed": True,
                              "python_type": type(reporting_failure).__name__}
        primary_failure.rollback = {"secondary_failure": detached(record),
                                    "adapter": adapter_report}
        primary_failure.rollback_confirmed = False
        return primary_failure

    def record_primary_and_rollback(self, token, primary_failure,
                                    proof_capability, ids, callback):
        """Accept only the exact retained PrimaryFailureRecord as authority."""
        phase = "ROLLBACK_VALIDATION"
        try:
            self._sync()
            self._require_effect_eligibility(self._primary_rollback_holds())
            require(type(primary_failure) is PrimaryFailureRecord
                    and primary_failure is self._primary_record
                    and token == self._row.token
                    and proof_capability is self._proof_capability
                    and type(ids) is dict and set(ids) == {
                        "attempt", "begin", "complete"},
                    "ROLLBACK_PRIMARY_PROVENANCE")
            phase = "ROLLBACK_BEGIN"
            begin = self.begin_close(ids["attempt"], ids["begin"], True)
            if begin["accepted"]:
                phase = "ROLLBACK_CALLBACK_AND_NORMALIZE"
                normalization = self.invoke_and_normalize(callback, True)
                if normalization["valid"] is True and not self._stop:
                    phase = "ROLLBACK_COMPLETE"
                    self.complete_close(ids["complete"], True)
        except BaseException as secondary_failure:
            if primary_failure is self._primary_record:
                self.retain_secondary_rollback_failure(
                    primary_failure, phase, secondary_failure)
            else:
                raise
        return primary_failure

    def stop_unregistered_custody(self, raw_custody, full_register_reply):
        self._sync()
        require(raw_custody is self._row
                and type(raw_custody) is RawDirectChildCustody
                and full_register_reply["accepted"] is False
                and self._stop is True, "UNREGISTERED_STOP_STATE")
        return self.snapshot()

    def report(self):
        self._sync()
        return {
            "snapshot": self.snapshot(),
            "ledger": self.ledger.report(),
            "admission": self.ledger.admission_report(),
            "row": self._row.report() if self._row else None,
            "view": self._view.report() if self._view else None,
            "primary": self._primary_record.report()
                if self._primary_record else None,
            "raw_primary_reference_retained":
                self._last_raw_primary_reference is not None,
            "raw_primary_token_retained": detached(self._last_raw_primary_token)
                if self._last_raw_primary_token is not None else None,
            "secondary_failures": detached(self._secondary_failures),
            "adapter": self._adapter.report() if self._adapter else None,
            "capability_flow": self.capability_flow_report(),
            "operations": detached(self._operations),
            "automatic_retry_actions": [],
            "process_exit_reclamation_not_confirmation": True,
        }


class NativeOwnerController:
    """Native shell. Its authentic and native paths are static-only in P17."""

    def __init__(self, ledger, runtime, native, token, recorded_native,
                 source_pins):
        require(type(ledger) is Ledger and type(runtime) is RuntimeBindings,
                "NATIVE_OWNER_BINDING")
        runtime.validate()
        runtime.validate_native(native)
        require(type(native) is runtime.native_class,
                "EXACT_NATIVE_CONTROLLER_BINDING")
        token_types(token)
        self.ledger = ledger
        self.runtime = runtime
        self.native = native
        self.token = detached(token)
        self.recorded_native = recorded_native
        self._key = object()
        self.effects = IntegratedNativeEffects(
            ledger, runtime, self._key, native, token)
        self.core = PureDirectChildController(
            ledger, id(self.effects), source_pins)

    def _sync(self):
        return self.core._sync()

    def budget(self):
        self._sync()
        return self.core.budget()

    def snapshot(self):
        self._sync()
        return self.core.snapshot()

    def derive_post_register_proof_capability(self, prepared,
                                              registered_custody,
                                              native, policy):
        self._sync()
        require(prepared is self.core._prepared
                and registered_custody is self.core._row
                and native is self.native,
                "FULL_PROOF_CAPABILITY_INPUT")
        return self.core.derive_post_register_proof_capability(
            native, policy)

    def capture_primary_failure(self, token, caught_or_supplied, origin,
                                phase, context):
        """Public authority handoff: return the exact retained record object.

        The core retains the record and logs its report separately. This
        wrapper forwards that identical object, so the native catch path never
        needs to reach into `core._primary_record` and never passes a report.
        """
        self._sync()
        record = self.core.capture_primary_failure(
            token, caught_or_supplied, origin, phase, context,
            self.core._proof_capability)
        require(type(record) is PrimaryFailureRecord
                and record is self.core._primary_record
                and record.raw_primary_reference is caught_or_supplied,
                "FULL_PRIMARY_AUTHORITY_HANDOFF")
        return record

    def record_primary_and_rollback(self, token, primary_failure,
                                    proof_capability, ids):
        """Accept only the exact retained PrimaryFailureRecord as authority."""
        guard = self.runtime.monitor
        phase = "ROLLBACK_VALIDATION"
        try:
            self._sync()
            require(type(primary_failure) is PrimaryFailureRecord
                    and primary_failure is self.core._primary_record
                    and proof_capability is self.core._proof_capability,
                    "FULL_ROLLBACK_PRIMARY_PROVENANCE")
            phase = "ROLLBACK_BEGIN"
            guard.enter_phase("ROLLBACK_BEGIN", token, proof_capability)
            try:
                begin = self.core.begin_close(ids["attempt"], ids["begin"], True)
            finally:
                guard.leave_phase()
            if begin["accepted"]:
                phase = "ROLLBACK_CALLBACK_AND_NORMALIZE"
                guard.enter_phase(
                    "ROLLBACK_CALLBACK", token, proof_capability,
                    {"accepted_begin_action": True})
                try:
                    normalization = self.core.invoke_and_normalize(
                        lambda action: self.effects.invoke(action, self._key), True)
                finally:
                    guard.leave_phase()
                if normalization["valid"] is True and not self.core._stop:
                    phase = "ROLLBACK_COMPLETE"
                    guard.enter_phase("ROLLBACK_COMPLETE", token, proof_capability)
                    try:
                        self.core.complete_close(ids["complete"], True)
                    finally:
                        guard.leave_phase()
        except BaseException as secondary_failure:
            if primary_failure is self.core._primary_record:
                self.core.retain_secondary_rollback_failure(
                    primary_failure, phase, secondary_failure)
            else:
                raise
        return primary_failure

    def close_registered_direct_child(self, token, ids):
        """Normal close of the registered, proven direct child.

        This is the normal-close sibling of `record_primary_and_rollback`. It
        routes through the same pure core transitions with `rollback=False`,
        the same `PureRollbackAdapter` BEGIN/COMPLETE submissions and the same
        single provider callback, so the one admitted `os.close` site and all
        existing custody/ledger bookkeeping are unchanged. The ownership key is
        only closed over here; it is never returned, copied or reported.

        Every argument is validated before any phase is entered, so a malformed
        request neither submits a ledger event nor mutates controller state.
        A repeated request is rejected by `NORMAL_CLOSE_PROVENANCE` because the
        adapter is no longer `None`, before any second callback is possible.
        """
        guard = self.runtime.monitor
        require(type(ids) is dict and set(ids) == {
            "attempt", "begin", "complete"}, "NORMAL_CLOSE_IDS_SCHEMA")
        token_types(token)
        label(ids["attempt"], "ATTEMPT_ID")
        label(ids["begin"], "BEGIN_EVENT_ID")
        label(ids["complete"], "COMPLETE_EVENT_ID")
        self._sync()
        self.runtime.validate_native(self.native)
        require(guard is not None and token == self.token
                and self.core._primary_record is None
                and self.core._proof == "ACCEPTED_RETURN_ELIGIBLE"
                and self.core._view is not None
                and self.core._proof_capability is not None
                and self.core._proof_capability.consumed
                and self.core._view_capability is not None
                and self.core._view_capability.consumed
                and type(self.core._row) is RegisteredDirectChildCustody
                and self.core.provider_identity == id(self.effects)
                and self.core._row.provider_identity == self.core.provider_identity
                and token == self.core._row.token
                and self.core._adapter is None
                and not self.core._stop and not self.core._holds
                and self.effects.row(token) is self.core._row,
                "NORMAL_CLOSE_PROVENANCE")
        guard.enter_phase("NORMAL_CLOSE_BEGIN", token, None)
        try:
            self.core.begin_close(ids["attempt"], ids["begin"], False)
        finally:
            guard.leave_phase()
        # A rejected normal BEGIN raises "NORMAL_BEGIN_REJECTED" inside
        # `begin_close` (:650), so there is no accepted-false continuation to
        # write here and no recovery path is implied.
        guard.enter_phase("NORMAL_CLOSE_CALLBACK", token, None,
                          {"accepted_begin_action": True})
        try:
            normalization = self.core.invoke_and_normalize(
                lambda action: self.effects.invoke(action, self._key), False)
        finally:
            guard.leave_phase()
        if normalization["valid"] is True and not self.core._stop:
            guard.enter_phase("NORMAL_CLOSE_COMPLETE", token, None)
            try:
                self.core.complete_close(ids["complete"], False)
            finally:
                guard.leave_phase()
        # An invalid normalization, a rejected COMPLETE and an unresolved error
        # outcome are all left exactly as the core recorded them: raw retained,
        # holds set, STOP set, no retry and no confirmed close.
        return self.snapshot()

    def stop_unregistered_custody(self, raw_custody, full_register_reply):
        self._sync()
        return self.core.stop_unregistered_custody(
            raw_custody, full_register_reply)

    def acquire_register_prove_direct_child(
            self, reservation_id, register_event_id, token, native, pid,
            expected, policy, rollback_ids):
        self._sync()
        require(not self.core._holds and token == self.token
                and native is self.native,
                "DIRECT_CHILD_ORCHESTRATION_INPUT")
        self.runtime.validate_native(native)
        guard = self.runtime.monitor
        prepare_capability = self.core.issue_prepare_capability(
            native, policy, pid)
        guard.enter_phase("PRE_OPEN_PREPARE", token, prepare_capability)
        try:
            prepared = prepare_direct_child(
                native, pid, expected, policy, prepare_capability,
                self.core._capability_authority)
        finally:
            guard.leave_phase()
        self.core.reserve(reservation_id)
        capture_capability = self.core.issue_capture_capability(
            prepared, native, self.effects)
        guard.enter_phase("RAW_CAPTURE", token, capture_capability)
        try:
            self.recorded_native.record_open_attempt(pid, 0)
            raw = capture_direct_child_open(
                native, prepared, self.effects, capture_capability,
                self.core._capability_authority)
        finally:
            guard.leave_phase()
        self.core.attach_raw_custody(prepared, raw, True)
        guard.enter_phase("REGISTER", token, None)
        try:
            registration = self.core.register_captured(register_event_id)
        finally:
            guard.leave_phase()
        if not registration["reply"]["accepted"]:
            return self.stop_unregistered_custody(raw, registration["reply"])
        registered = self.core._row
        capability = self.derive_post_register_proof_capability(
            prepared, registered, native, policy)
        try:
            guard.enter_phase("POST_REGISTER_PROOF", token, capability)
            try:
                proof = prove_registered_direct_child(
                    prepared, registered, native, policy, capability,
                    self.core._capability_authority)
            finally:
                guard.leave_phase()
            view_capability = self.core.issue_view_capability(
                proof, registered)
            guard.enter_phase("VIEW_AND_RETURN", token, view_capability)
            try:
                view = build_direct_child_view(
                    proof, registered, view_capability,
                    self.core._capability_authority)
                self.core._proof = "ACCEPTED_RETURN_ELIGIBLE"
                self.core._view = view
                registered.status = (
                    "REGISTERED_PENDING_FD_" + str(registered.fd)
                    + "_NONOWNING_VIEW")
                return self.recorded_native.record_registered_proven_return(
                    registered, proof, view)
            finally:
                guard.leave_phase()
        except BaseException as exc:
            primary_exception = exc
            # `primary` is the exact retained PrimaryFailureRecord returned by
            # the public handoff, not its report, so the consumer's exact
            # identity requirement holds without any internal-attribute access.
            primary = self.capture_primary_failure(
                token, primary_exception, AUTHENTIC_CAUGHT_EXCEPTION,
                guard.last_effect_phase, {"pid": pid, "fd": registered.fd})
            return self.record_primary_and_rollback(
                token, primary, capability, rollback_ids)

    def report(self):
        self._sync()
        return self.core.report()
