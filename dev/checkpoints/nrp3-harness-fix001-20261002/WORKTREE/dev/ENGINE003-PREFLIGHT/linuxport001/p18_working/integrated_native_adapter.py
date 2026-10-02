"""P17 exact BEGIN/callback/normalization/COMPLETE adapter."""
from ledger import Ledger, label, require
from common import detached, raw_exception, raw_return
from integrated_native_effects import IntegratedNativeEffects, RegisteredDirectChildCustody


DIRECT_CHILD_POLICY = "PY38_OS_CLOSE_NONE"


def normalize_native(binding, raw, entry, pins):
    """Normalize only an exact retained P17 provider callback observation."""
    invalid = {
        "valid": False, "model_outcome": None,
        "reason": "INVALID_NATIVE_OBSERVATION",
        "raw_observation": detached(raw),
    }
    required_binding = {
        "scope", "policy", "token", "fd", "provider_identity", "row_identity",
        "callback_source_sha256", "policy_source_sha256",
    }
    if (type(binding) is not dict or set(binding) != required_binding
            or binding["scope"] != "P17_DIRECT_CHILD_PROVIDER_CUSTODY"
            or binding["policy"] != DIRECT_CHILD_POLICY
            or binding["callback_source_sha256"] != pins.get("integrated_native_effects.py")
            or binding["policy_source_sha256"] != pins.get("STATIC_CHECKLIST.json")):
        return invalid
    if (type(entry) is not dict or set(entry) != {
            "action", "binding", "raw_observation", "call_entered",
            "exact_function_identity_validated", "retained_row_identity_validated"}
            or entry["call_entered"] is not True
            or entry["action"].get("kind") != "SIMULATED_CLOSE_ONCE"
            or entry["action"].get("token") != binding["token"]
            or entry["action"].get("fd") != binding["fd"]
            or entry["binding"] != binding
            or entry["raw_observation"] != raw
            or entry["exact_function_identity_validated"] is not True
            or entry["retained_row_identity_validated"] is not True):
        return dict(invalid, reason="MISSING_EXACT_PROVIDER_CALL_ENTRY")
    if raw == {
            "kind": "RETURN", "python_type": "NoneType",
            "representation": "None", "returned_normally": True}:
        return {
            "valid": True, "reason": None, "raw_observation": detached(raw),
            "model_outcome": {
                "result": "SUCCESS", "return_value": 0, "errno": None,
                "diagnostic": "close returned None",
            },
            "encoding_scope": "MODEL_OUTCOME_NOT_NATIVE_INTEGER_RETURN",
        }
    if (raw.get("kind") == "EXCEPTION"
            and raw.get("python_type") == "OSError"
            and type(raw.get("errno")) is int
            and 1 <= raw["errno"] <= 4095):
        return {
            "valid": True, "reason": None, "raw_observation": detached(raw),
            "model_outcome": {
                "result": "ERROR", "return_value": -1, "errno": raw["errno"],
                "diagnostic": "OSError errno " + str(raw["errno"]),
            },
            "encoding_scope": "MODEL_OUTCOME_NOT_NATIVE_INTEGER_RETURN",
        }
    return invalid


class PureRollbackAdapter:
    """Pure exact public transition core; callback is supplied by its caller."""

    def __init__(self, ledger, callback_binding, pins):
        require(type(ledger) is Ledger and type(callback_binding) is dict
                and type(pins) is dict, "PURE_ADAPTER_BINDING")
        self.ledger = ledger
        self.binding = detached(callback_binding)
        self.pins = dict(pins)
        self.begin_request = None
        self.begin_reply = None
        self.action = None
        self.raw_reference = None
        self.raw_observation = None
        self.call_entry = None
        self.normalization = None
        self.complete_request = None
        self.complete_reply = None
        self.callback_entries = 0

    def begin(self, token, attempt_id, begin_event_id):
        require(self.begin_request is None, "BEGIN_ALREADY_SUBMITTED")
        label(attempt_id, "ATTEMPT_ID")
        label(begin_event_id, "BEGIN_EVENT_ID")
        request = {
            "kind": "BEGIN", "event_id": begin_event_id,
            "token": detached(token), "attempt_id": attempt_id,
        }
        reply = self.ledger.submit(detached(request))
        self.begin_request = detached(request)
        self.begin_reply = detached(reply)
        if reply["accepted"]:
            action = reply["action"]
            require(type(action) is dict and set(action) == {
                "kind", "token", "attempt_id", "fd", "source_event_id"}
                and action == {
                    "kind": "SIMULATED_CLOSE_ONCE", "token": detached(token),
                    "attempt_id": attempt_id, "fd": self.binding["fd"],
                    "source_event_id": begin_event_id,
                }, "INCOMPLETE_ACCEPTED_BEGIN_ACTION")
            self.action = detached(action)
        return detached(reply)

    def invoke_and_normalize(self, callback):
        require(self.begin_reply is not None and self.begin_reply["accepted"] is True
                and self.action is not None and self.callback_entries == 0,
                "CALLBACK_WITHOUT_ACCEPTED_BEGIN")
        require(callable(callback), "CALLBACK_NOT_CALLABLE")
        self.callback_entries += 1
        raised = False
        try:
            raw_reference = callback(detached(self.action))
        except BaseException as exc:
            raw_reference = exc
            raised = True
        # The object reference and raw representation are retained before normalization.
        self.raw_reference = raw_reference
        self.raw_observation = (raw_exception(raw_reference)
                                if raised else raw_return(raw_reference))
        self.call_entry = {
            "action": detached(self.action), "binding": detached(self.binding),
            "raw_observation": detached(self.raw_observation),
            "call_entered": True,
            "exact_function_identity_validated": True,
            "retained_row_identity_validated": True,
        }
        self.normalization = normalize_native(
            self.binding, self.raw_observation, self.call_entry, self.pins)
        return detached(self.normalization)

    def complete(self, complete_event_id):
        require(self.normalization is not None and self.normalization["valid"] is True,
                "COMPLETE_WITHOUT_VALID_NORMALIZATION")
        require(self.complete_request is None, "COMPLETE_ALREADY_SUBMITTED")
        label(complete_event_id, "COMPLETE_EVENT_ID")
        request = {
            "kind": "COMPLETE", "event_id": complete_event_id,
            "token": detached(self.action["token"]),
            "attempt_id": self.action["attempt_id"],
            "outcome": detached(self.normalization["model_outcome"]),
        }
        reply = self.ledger.submit(detached(request))
        self.complete_request = detached(request)
        self.complete_reply = detached(reply)
        return detached(reply)

    def report(self):
        return {
            "begin_request": detached(self.begin_request) if self.begin_request else None,
            "begin_reply": detached(self.begin_reply) if self.begin_reply else None,
            "action": detached(self.action) if self.action else None,
            "raw_reference_retained": self.raw_reference is not None
                or (self.raw_observation is not None
                    and self.raw_observation.get("python_type") == "NoneType"),
            "raw_observation": detached(self.raw_observation)
                if self.raw_observation else None,
            "call_entry": detached(self.call_entry) if self.call_entry else None,
            "normalization": detached(self.normalization)
                if self.normalization else None,
            "complete_request": detached(self.complete_request)
                if self.complete_request else None,
            "complete_reply": detached(self.complete_reply)
                if self.complete_reply else None,
            "callback_entries": self.callback_entries,
            "automatic_retry_actions": [],
        }


class IntegratedNativeAdapter:
    """Production wrapper binding the pure transition core to the exact provider."""

    def __init__(self, ledger, effects, ownership_key):
        require(type(ledger) is Ledger and type(effects) is IntegratedNativeEffects
                and effects.is_bound_to(ledger, ownership_key),
                "NATIVE_ADAPTER_BINDING")
        self.ledger = ledger
        self.effects = effects
        self._key = ownership_key
        self._last = None

    def register(self, event_id, token, fd):
        return self.ledger.submit({
            "kind": "REGISTER", "event_id": event_id,
            "token": detached(token), "fd": fd,
        })

    def close_once(self, token, attempt_id, begin_event_id,
                   complete_event_id):
        row = self.effects.row(token)
        require(type(row) is RegisteredDirectChildCustody
                and row.callback_attempted is False,
                "REGISTERED_CALLBACK_ROW")
        binding = {
            "scope": "P17_DIRECT_CHILD_PROVIDER_CUSTODY",
            "policy": DIRECT_CHILD_POLICY, "token": detached(token),
            "fd": row.fd, "provider_identity": id(self.effects),
            "row_identity": id(row),
            "callback_source_sha256": self.effects.runtime.pins["integrated_native_effects.py"],
            "policy_source_sha256": self.effects.runtime.pins["STATIC_CHECKLIST.json"],
        }
        pure = PureRollbackAdapter(self.ledger, binding, self.effects.runtime.pins)
        begin = pure.begin(token, attempt_id, begin_event_id)
        if begin["accepted"]:
            pure.invoke_and_normalize(
                lambda action: self.effects.invoke(action, self._key))
            if pure.normalization["valid"]:
                pure.complete(complete_event_id)
        self._last = pure
        return pure.report()

    def report(self):
        return self._last.report() if self._last else {
            "callback_entries": 0, "automatic_retry_actions": []}
