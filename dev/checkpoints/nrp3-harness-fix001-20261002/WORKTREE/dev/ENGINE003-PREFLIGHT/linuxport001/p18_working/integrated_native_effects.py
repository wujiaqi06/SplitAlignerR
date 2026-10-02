"""P17 direct-child raw-FD provider with one continuous custody row."""
from ledger import Ledger, freeze, require, token_types
from common import detached, raw_exception, raw_return
from runtime_bindings import RuntimeBindings


class RawDirectChildCustody:
    """Provider-owned mutable row; callers receive only the same row as a view."""

    def __init__(self, provider_identity, ownership_key_identity, token, fd,
                 prepared_identity, native_identity, capture_index):
        token_types(token)
        require(type(fd) is int and not isinstance(fd, bool) and fd >= 0,
                "RAW_CAPTURED_FD")
        self.provider_identity = provider_identity
        self.ownership_key_identity = ownership_key_identity
        self.token = detached(token)
        self.fd = fd
        self.prepared_identity = prepared_identity
        self.native_identity = native_identity
        self.capture_index = capture_index
        self.registration_accepted = False
        self.full_register_request = None
        self.full_register_reply = None
        self.registration_event_id = None
        self.committed_reservation_id = None
        self.status = "RAW_PROVIDER_CUSTODY"
        self.callback_attempted = False
        self.callback_action = None
        self.callback_raw_reference = None
        self.callback_raw_observation = None

    @property
    def identity(self):
        return id(self)

    def report(self):
        return {
            "provider_identity": self.provider_identity,
            "ownership_key_identity": self.ownership_key_identity,
            "token": detached(self.token), "fd": self.fd,
            "prepared_identity": self.prepared_identity,
            "native_identity": self.native_identity,
            "capture_index": self.capture_index,
            "registration_accepted": self.registration_accepted,
            "full_register_request": detached(self.full_register_request)
                if self.full_register_request is not None else None,
            "full_register_reply": detached(self.full_register_reply)
                if self.full_register_reply is not None else None,
            "registration_event_id": self.registration_event_id,
            "committed_reservation_id": self.committed_reservation_id,
            "status": self.status, "callback_attempted": self.callback_attempted,
            "callback_action": detached(self.callback_action)
                if self.callback_action is not None else None,
            "identity": id(self),
        }


class RegisteredDirectChildCustody(RawDirectChildCustody):
    """The same provider row after accepted REGISTER; no ownership transfer."""

    pass


class PureCustodyTransitions:
    """Pure row transitions shared by production orchestration and P17 cases."""

    @staticmethod
    def mark_registered(raw_custody, full_request, full_reply, reservation_id,
                        provider_identity):
        require(type(raw_custody) is RawDirectChildCustody,
                "EXACT_RAW_CUSTODY")
        require(raw_custody.provider_identity == provider_identity,
                "PROVIDER_ROW_IDENTITY")
        require(type(full_request) is dict and set(full_request) == {
            "event_id", "kind", "token", "fd"}, "REGISTER_REQUEST_SCHEMA")
        require(full_request["kind"] == "REGISTER"
                and full_request["token"] == raw_custody.token
                and full_request["fd"] == raw_custody.fd,
                "REGISTER_EXACT_CAPTURED_FD")
        require(type(full_reply) is dict and full_reply.get("accepted") is True
                and full_reply.get("reason") is None
                and full_reply.get("action") is None
                and type(full_reply.get("submission_slot")) is int
                and type(full_reply.get("admission")) is dict,
                "FULL_ACCEPTED_REGISTER_REPLY")
        require(type(reservation_id) is str and reservation_id,
                "COMMITTED_RESERVATION_ID")
        raw_custody.registration_accepted = True
        raw_custody.full_register_request = detached(full_request)
        raw_custody.full_register_reply = detached(full_reply)
        raw_custody.registration_event_id = full_request["event_id"]
        raw_custody.committed_reservation_id = reservation_id
        raw_custody.status = "REGISTERED_PENDING"
        raw_custody.__class__ = RegisteredDirectChildCustody
        return raw_custody

    @staticmethod
    def retain_unregistered(raw_custody, full_request, full_rejection_reply,
                            provider_identity):
        require(type(raw_custody) is RawDirectChildCustody,
                "EXACT_RAW_CUSTODY")
        require(raw_custody.provider_identity == provider_identity,
                "PROVIDER_ROW_IDENTITY")
        require(type(full_request) is dict and full_request.get("kind") == "REGISTER",
                "REGISTER_REJECTION_REQUEST")
        require(type(full_rejection_reply) is dict
                and full_rejection_reply.get("accepted") is False,
                "FULL_REJECTED_REGISTER_REPLY")
        raw_custody.full_register_request = detached(full_request)
        raw_custody.full_register_reply = detached(full_rejection_reply)
        raw_custody.status = "REGISTER_REJECTED_UNREGISTERED_CUSTODY"
        return raw_custody


class IntegratedNativeEffects:
    """Full native provider. P17 candidates never import or construct this class."""

    def __init__(self, ledger, runtime, ownership_key, native, token):
        require(type(ledger) is Ledger and type(runtime) is RuntimeBindings,
                "DIRECT_CHILD_PROVIDER_BINDING")
        require(type(ownership_key) is object, "OWNERSHIP_KEY")
        runtime.validate()
        require(type(native) is runtime.native_class, "EXACT_NATIVE_INSTANCE")
        token_types(token)
        self.ledger = ledger
        self.runtime = runtime
        self._key = ownership_key
        self.native = native
        self.token = detached(token)
        self._raw_capture = None
        self._rows = {}
        self._calls = []

    def is_bound_to(self, ledger, ownership_key):
        return self.ledger is ledger and self._key is ownership_key

    def acquire_direct_child_raw(self, prepared, capture_capability):
        from direct_child_pidfd import PreparedDirectChild, RawCaptureCapability
        require(type(prepared) is PreparedDirectChild
                and type(capture_capability) is RawCaptureCapability,
                "RAW_CAPTURE_INPUTS")
        require(not self._rows and self._raw_capture is None,
                "RAW_CAPTURE_ONCE")
        # First reachable assignment after native return is the provider field.
        self._raw_capture = self.native.open(prepared.pid, 0)
        require(type(self._raw_capture) is int
                and not isinstance(self._raw_capture, bool)
                and 0 <= self._raw_capture < 2**31,
                "RAW_CAPTURED_FD")
        row = RawDirectChildCustody(
            id(self), id(self._key), self.token, self._raw_capture,
            prepared.identity, id(self.native), 0)
        self._rows[freeze(self.token)] = row
        return row

    def row(self, token):
        token_types(token)
        key = freeze(token)
        require(key in self._rows, "UNKNOWN_DIRECT_CHILD_CUSTODY")
        return self._rows[key]

    def mark_direct_child_registered(self, raw_custody, full_request,
                                     full_reply, reservation_id):
        require(self.row(raw_custody.token) is raw_custody,
                "SAME_PROVIDER_ROW")
        return PureCustodyTransitions.mark_registered(
            raw_custody, full_request, full_reply, reservation_id, id(self))

    def retain_unregistered(self, raw_custody, full_request,
                            full_rejection_reply):
        require(self.row(raw_custody.token) is raw_custody,
                "SAME_PROVIDER_ROW")
        PureCustodyTransitions.retain_unregistered(
            raw_custody, full_request, full_rejection_reply, id(self))

    def invoke(self, action, ownership_key):
        """The sole production os.close site, gated by the exact BEGIN action."""
        require(ownership_key is self._key, "FOREIGN_CALLBACK_AUTHORITY")
        require(type(action) is dict and set(action) == {
            "kind", "token", "attempt_id", "fd", "source_event_id"},
            "COMPLETE_BEGIN_ACTION")
        row = self.row(action["token"])
        report = self.ledger.report()
        begin = {
            "kind": "BEGIN", "event_id": action["source_event_id"],
            "token": detached(action["token"]),
            "attempt_id": action["attempt_id"],
        }
        obligations = [item for item in report["obligations"]
                       if item["token"] == action["token"]]
        require(type(row) is RegisteredDirectChildCustody
                and row.registration_accepted is True
                and row.callback_attempted is False
                and action["kind"] == "SIMULATED_CLOSE_ONCE"
                and action["fd"] == row.fd
                and len(obligations) == 1
                and obligations[0]["state"] == "ATTEMPTED_WITHOUT_COMPLETION"
                and obligations[0]["attempt_id"] == action["attempt_id"]
                and report["history"][-1] == begin,
                "ADMITTED_DIRECT_CHILD_BEGIN")
        row.callback_attempted = True
        row.callback_action = detached(action)
        try:
            value = self.runtime.os_close(row.fd)
            row.callback_raw_reference = value
            row.callback_raw_observation = raw_return(value)
            self._calls.append({"action": detached(action),
                                "raw": detached(row.callback_raw_observation)})
            return value
        except BaseException as exc:
            row.callback_raw_reference = exc
            row.callback_raw_observation = raw_exception(exc)
            self._calls.append({"action": detached(action),
                                "raw": detached(row.callback_raw_observation)})
            raise

    def report(self):
        return {
            "scope": "P17_DIRECT_CHILD_PROVIDER_CUSTODY",
            "rows": [row.report() for row in self._rows.values()],
            "calls": detached(self._calls),
            "raw_integer_retained": self._raw_capture is not None,
            "owning_handle_constructions": 0,
            "automatic_retry_actions": [],
        }
