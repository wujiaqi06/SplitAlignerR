#!/usr/bin/env python3
"""Run exactly 12 P17-FIX001 cases from extracted pure production definitions."""
import ast
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


EXTRACTION = {
    "ledger.py": [
        "MAX_RESOURCES", "MAX_EVENTS", "LABEL_CHARS", "TOKEN_FIELDS", "STATES",
        "LedgerError", "require", "fields", "label", "integer", "digest",
        "freeze", "thaw", "token_types", "outcome_types", "event_types", "Ledger",
    ],
    "common.py": ["immutable", "materialize", "detached", "raw_return", "raw_exception"],
    "direct_child_pidfd.py": [
        "ACQUISITION_PRECONDITIONS", "DIRECT_CHILD_SCOPE",
        "CapabilityAuthority", "_OpaqueOneUseCapability",
        "PreOpenPrepareCapability", "RawCaptureCapability",
        "PostRegisterProofCapability", "NonOwningViewCapability",
        "PreparedDirectChild", "DirectChildProof", "DirectChildPidfdView",
    ],
    "integrated_native_effects.py": [
        "RawDirectChildCustody", "RegisteredDirectChildCustody",
        "PureCustodyTransitions",
    ],
    "integrated_native_adapter.py": [
        "DIRECT_CHILD_POLICY", "normalize_native", "PureRollbackAdapter",
    ],
    "native_owner_controller.py": [
        "AUTHENTIC_CAUGHT_EXCEPTION", "SUPPLIED_STATIC_REJECTION",
        "PrimaryFailureRecord", "PureDirectChildController",
    ],
}
FORBIDDEN_MODULES = {
    "ctypes", "socket", "_socket", "subprocess", "multiprocessing",
    "pidfd_primitives", "parsers", "native_syscalls_factory",
    "runtime_bindings", "development_guard", "recorded_native",
    "integrated_native_effects", "integrated_native_adapter",
    "direct_child_pidfd", "native_owner_controller", "ledger", "common",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def node_name(node):
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 \
            and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def mapping(path, names):
    value = path.read_bytes()
    source = value.decode("utf-8")
    tree = ast.parse(source, filename=str(path))
    by_name = {node_name(node): node for node in tree.body if node_name(node)}
    lines = source.splitlines(keepends=True)
    definitions = []
    for name in names:
        node = by_name[name]
        segment = "".join(lines[node.lineno - 1:node.end_lineno]).encode("utf-8")
        definitions.append({
            "qualified_name": name,
            "kind": type(node).__name__,
            "line_start": node.lineno,
            "line_end": node.end_lineno,
            "source_bytes": len(segment),
            "source_sha256": sha(segment),
            "ast_sha256": sha(ast.dump(node, include_attributes=False).encode("utf-8")),
        })
    return {
        "file": path.name, "bytes": len(value), "sha256": sha(value),
        "definitions": definitions,
    }, tree, by_name


def extract_namespace(source, frozen_manifest):
    namespace = {"__name__": "p17_source_isolated_pure"}
    observed = []
    executed_nodes = 0
    for name, names in EXTRACTION.items():
        current, tree, by_name = mapping(source / name, names)
        expected = frozen_manifest["extraction"][name]
        if current != expected:
            raise RuntimeError("EXTRACTION_MANIFEST_MISMATCH:" + name)
        nodes = [copy.deepcopy(by_name[item]) for item in names]
        module = ast.Module(body=nodes, type_ignores=[])
        if any(isinstance(item, (ast.Import, ast.ImportFrom))
               for item in ast.walk(module)):
            raise RuntimeError("IMPORT_IN_EXTRACTED_AST:" + name)
        ast.fix_missing_locations(module)
        exec(compile(module, "<p17-extracted:" + name + ">", "exec"),
             namespace, namespace)
        observed.append(current)
        executed_nodes += len(nodes)
    return namespace, observed, executed_nodes


class Checks:
    def __init__(self):
        self.rows = []

    def equal(self, name, actual, expected):
        self.rows.append({
            "name": name, "actual": jsonable(actual),
            "expected": jsonable(expected),
            "passed": actual == expected,
        })

    def true(self, name, actual):
        self.equal(name, bool(actual), True)


def jsonable(value):
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(jsonable(item) for item in value)
    if isinstance(value, type):
        return value.__module__ + "." + value.__qualname__
    return value


def caught_code(call):
    try:
        call()
    except BaseException as exc:
        return {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                "text": str(exc)}
    return {"type": "NO_EXCEPTION", "code": None, "text": None}


def proof_data(pid):
    return {
        "pid": pid, "ppid": 1, "starttime_ticks": 1,
        "zombie_before": False, "zombie_after": False, "fdinfo_pid": pid,
    }


def public_observation(adapter):
    if adapter is None:
        return None
    return {
        "begin_request": adapter.begin_request,
        "begin_reply": adapter.begin_reply,
        "complete_request": adapter.complete_request,
        "complete_reply": adapter.complete_reply,
    }


def run_case(trace, namespace, source_pins, checks, case_index):
    Ledger = namespace["Ledger"]
    Prepared = namespace["PreparedDirectChild"]
    Raw = namespace["RawDirectChildCustody"]
    Controller = namespace["PureDirectChildController"]
    View = namespace["DirectChildPidfdView"]
    detached = namespace["detached"]

    case_id = trace["trace_id"]
    ledger = Ledger(detached(trace["config"]))
    native_object = object()
    policy_object = object()
    provider_object = object()
    provider_identity = id(provider_object)
    native_identity = id(native_object)
    policy_identity = id(policy_object)
    controller = Controller(ledger, provider_identity, source_pins)
    prepare_capability = controller.issue_prepare_capability(
        native_object, policy_object, trace["fixture_metadata"]["pid"])
    wrong_authority = namespace["CapabilityAuthority"](object())
    checks.equal(case_id + ":prepare_wrong_authority",
                 caught_code(lambda: prepare_capability.consume(
                     wrong_authority, native_object=native_object,
                     policy_object=policy_object,
                     pid=trace["fixture_metadata"]["pid"])),
                 {"type": "LedgerError", "code": "CAPABILITY_FOREIGN_AUTHORITY",
                  "text": "CAPABILITY_FOREIGN_AUTHORITY"})
    checks.equal(case_id + ":prepare_wrong_object",
                 caught_code(lambda: prepare_capability.consume(
                     controller._capability_authority, native_object=object(),
                     policy_object=policy_object,
                     pid=trace["fixture_metadata"]["pid"])),
                 {"type": "LedgerError", "code": "CAPABILITY_NATIVE_OBJECT",
                  "text": "CAPABILITY_NATIVE_OBJECT"})
    prepare_capability.consume(
        controller._capability_authority, native_object=native_object,
        policy_object=policy_object, pid=trace["fixture_metadata"]["pid"])
    prepared = Prepared(
        trace["fixture_metadata"]["pid"],
        (trace["fixture_metadata"]["pid"], 1, 1),
        {"supplied": True}, False, {"supplied": True},
        native_identity, policy_identity, prepare_capability.identity)
    capture_capability = controller.issue_capture_capability(
        prepared, native_object, provider_object)
    capture_capability.consume(
        controller._capability_authority, controller_object=controller,
        native_object=native_object, prepared_object=prepared,
        provider_object=provider_object, native_identity=native_identity,
        prepared_identity=prepared.identity,
        provider_identity=provider_identity)
    raw = Raw(
        provider_identity, 57000 + case_index, trace["token"],
        trace["fixture_metadata"]["captured_fd"], prepared.identity,
        native_identity, 0)
    checks.equal(case_id + ":S0", controller.snapshot(), trace["states"]["S0"])
    observations = []
    public_rows = []
    callback_entries = 0
    capability = None
    registered_row_identity = None

    for position, step in enumerate(trace["steps"]):
        before = controller.snapshot()
        checks.equal(case_id + ":step" + str(position + 1) + ":before",
                     before, trace["states"][step["before_state_ref"]])
        operation = step["step"]
        actual_result = None
        if operation == "RESERVE":
            actual_result = controller.reserve("reservation." + case_id[:3])
            checks.equal(case_id + ":reserve_result",
                         {key: actual_result[key] for key in
                          ("admitted", "resources", "credits")},
                         step["supplied_result"])
        elif operation == "RAW_OPEN_CAPTURE":
            actual_result = controller.attach_raw_custody(
                prepared, raw, post_open_pending=True)
        elif operation == "RESERVE_AND_RAW_CAPTURE":
            reserve = controller.reserve("reservation." + case_id[:3])
            capture = controller.attach_raw_custody(
                prepared, raw, post_open_pending=False)
            actual_result = {"reserve": reserve, "capture": capture}
        elif operation in ("REGISTER", "REGISTER_REJECTED"):
            expected_request = detached(step["public_request"])
            if case_id == "D06_REGISTER_REJECT_UNREGISTERED_CUSTODY":
                baseline = controller.registration_submission_baseline()
                actual_reply = ledger.submit(detached(expected_request))
                actual_result = controller.reconcile_registration_result(
                    expected_request, actual_reply, baseline)
                checks.equal(case_id + ":single_fixture_substitution", {
                    "custody_fd": raw.fd,
                    "submitted_fd": actual_result["request"]["fd"],
                    "request_keys": sorted(actual_result["request"]),
                }, {
                    "custody_fd": 41, "submitted_fd": -1,
                    "request_keys": ["event_id", "fd", "kind", "token"],
                })
            else:
                actual_result = controller.register_captured(
                    expected_request["event_id"])
            checks.equal(case_id + ":register_request",
                         actual_result["request"], expected_request)
            checks.equal(case_id + ":register_reply",
                         actual_result["reply"], step["proposed_public_reply"])
            public_rows.append({
                "request": actual_result["request"],
                "reply": actual_result["reply"],
            })
            if actual_result["reply"]["accepted"]:
                registered_row_identity = id(raw)
                capability = controller.derive_post_register_proof_capability(
                    native_object, policy_object)
                checks.equal(case_id + ":same_provider_row_after_register",
                             [id(raw), id(controller._row)],
                             [registered_row_identity, registered_row_identity])
        elif operation == "POST_OPEN_PROOF_AND_VIEW":
            actual_result = controller.accept_supplied_proof_and_view(
                capability, proof_data(prepared.pid),
                native_object, policy_object)
            checks.equal(case_id + ":view_exact_type", type(actual_result), View)
            checks.equal(case_id + ":view_forbidden_members",
                         sorted(set(View.__dict__) & {
                             "close", "__enter__", "__exit__", "__del__",
                             "receive", "transfer"}), [])
            checks.equal(case_id + ":view_borrowed_row",
                         [actual_result.borrowed_fd, actual_result.token],
                         [raw.fd, raw.token])
            checks.equal(case_id + ":proof_capability_consumed",
                         capability.consumed, True)
            checks.equal(case_id + ":proof_capability_one_use",
                         caught_code(lambda: capability.consume(
                             controller._capability_authority)),
                         {"type": "LedgerError", "code": "CAPABILITY_ALREADY_CONSUMED",
                          "text": "CAPABILITY_ALREADY_CONSUMED"})
        elif operation == "POST_OPEN_PROOF":
            supplied_primary = trace["fixture_metadata"]["primary_failure"]
            actual_result = controller.capture_primary_failure(
                trace["token"], supplied_primary,
                namespace["SUPPLIED_STATIC_REJECTION"],
                "POST_REGISTER_PROOF", {
                    "supplied_trace": case_id,
                    "native_identity_validity": "DECLARED_SUPPLIED_PREMISE",
                }, capability)
            checks.true(case_id + ":capture_returns_retained_record",
                        actual_result is controller._primary_record)
            checks.equal(case_id + ":capture_return_is_not_a_report",
                         isinstance(actual_result, dict), False)
            checks.true(case_id + ":capture_report_logged_separately",
                        controller._operations[-1]["operation"]
                        == "CAPTURE_PRIMARY_FAILURE")
            checks.true(case_id + ":raw_primary_same_reference",
                        controller._primary_record.raw_primary_reference
                        is supplied_primary)
            checks.equal(case_id + ":primary_origin",
                         controller._primary_record.origin,
                         "SUPPLIED_STATIC_REJECTION")
            checks.equal(case_id + ":primary_runtime_flags", [
                controller._primary_record.runtime_failure_observed,
                controller._primary_record.static_fixture_only,
                controller._primary_record.primary_error_preserved,
            ], [False, True, True])
            checks.equal(case_id + ":rollback_capability_provenance",
                         capability.validate_provenance(
                             controller._capability_authority,
                             controller_object=controller,
                             ledger_object=ledger, prepared_object=prepared,
                             custody_object=raw,
                             native_object=native_object,
                             policy_object=policy_object), True)
        elif operation in ("BEGIN_LATER_CLOSE", "ROLLBACK_BEGIN",
                           "ROLLBACK_BEGIN_REJECTED"):
            request = step["public_request"]
            rollback = operation != "BEGIN_LATER_CLOSE"
            actual_result = controller.begin_close(
                request["attempt_id"], request["event_id"], rollback)
            adapter = controller._adapter
            checks.equal(case_id + ":begin_request",
                         adapter.begin_request, request)
            checks.equal(case_id + ":begin_reply",
                         actual_result, step["proposed_public_reply"])
            public_rows.append({"request": adapter.begin_request,
                                "reply": actual_result})
            if not actual_result["accepted"]:
                checks.equal(case_id + ":rejected_begin_callback_entries",
                             adapter.callback_entries, 0)
                checks.equal(case_id + ":rejected_begin_complete", 
                             adapter.complete_request, None)
        elif operation in ("PROVIDER_CALLBACK_AND_NORMALIZE",
                           "ROLLBACK_CALLBACK_AND_NORMALIZE"):
            local_count = {"entries": 0}
            if case_id == "D03_PROOF_REJECT_ROLLBACK_ERROR":
                def callback(action):
                    local_count["entries"] += 1
                    raise OSError(5, "supplied error")
            else:
                def callback(action):
                    local_count["entries"] += 1
                    return None
            actual_result = controller.invoke_and_normalize(
                callback, operation.startswith("ROLLBACK"))
            callback_entries += local_count["entries"]
            checks.equal(case_id + ":callback_entry_once",
                         local_count["entries"], 1)
            checks.equal(case_id + ":normalization", {
                "valid": actual_result["valid"],
                "outcome": actual_result["model_outcome"],
            }, step["normalization"])
            checks.true(case_id + ":raw_reference_retained",
                        controller._adapter.report()["raw_reference_retained"])
            if case_id == "D03_PROOF_REJECT_ROLLBACK_ERROR":
                checks.equal(case_id + ":fresh_oserror_reference", [
                    type(controller._adapter.raw_reference).__name__,
                    controller._adapter.raw_reference.errno,
                    controller._adapter.raw_reference.args,
                ], ["OSError", 5, (5, "supplied error")])
        elif operation in ("COMPLETE", "ROLLBACK_COMPLETE",
                           "ROLLBACK_COMPLETE_REJECTED"):
            request = step["public_request"]
            actual_result = controller.complete_close(
                request["event_id"], operation != "COMPLETE")
            adapter = controller._adapter
            checks.equal(case_id + ":complete_request",
                         adapter.complete_request, request)
            checks.equal(case_id + ":complete_reply",
                         actual_result, step["proposed_public_reply"])
            public_rows.append({"request": adapter.complete_request,
                                "reply": actual_result})
        else:
            raise RuntimeError("UNKNOWN_SUPPLIED_STEP:" + operation)
        after = controller.snapshot()
        checks.equal(case_id + ":step" + str(position + 1) + ":after",
                     after, trace["states"][step["after_state_ref"]])
        observations.append({
            "position": position + 1, "operation": operation,
            "before": before, "after": after,
            "public": public_rows[-1] if public_rows and
                public_rows[-1]["request"].get("event_id")
                == step.get("public_request", {}).get("event_id") else None,
            "adapter": public_observation(controller._adapter),
        })

    accepted_history = [item["request"] for item in public_rows
                        if item["reply"]["accepted"]]
    checks.equal(case_id + ":accepted_immutable_history",
                 ledger.report()["history"], accepted_history)
    checks.equal(case_id + ":submission_slots_include_rejections",
                 ledger.admission_report()["submission_slots"], len(public_rows))
    checks.true(case_id + ":budget_nonnegative",
                controller.snapshot()["unreserved_submission_slots"] >= 0)
    checks.equal(case_id + ":automatic_retries",
                 controller.report()["automatic_retry_actions"], [])
    return {
        "case_id": case_id,
        "config": detached(trace["config"]), "token": detached(trace["token"]),
        "fixture_metadata": detached(trace["fixture_metadata"]),
        "observations": observations, "public_events": public_rows,
        "final_ledger": ledger.report(),
        "final_controller": controller.report(),
        "callback_entries": callback_entries,
        "ledger_instances": 1,
    }


def fresh_context(case, namespace, source_pins, case_index):
    """Build one fresh supplied-identity context through shared production core."""
    detached = namespace["detached"]
    ledger = namespace["Ledger"](detached(case["config"]))
    native_object = object()
    policy_object = object()
    provider_object = object()
    controller = namespace["PureDirectChildController"](
        ledger, id(provider_object), source_pins)
    pid = case["fixture_metadata"]["pid"]
    prepare_capability = controller.issue_prepare_capability(
        native_object, policy_object, pid)
    prepare_capability.consume(
        controller._capability_authority,
        native_object=native_object, policy_object=policy_object, pid=pid)
    prepared = namespace["PreparedDirectChild"](
        pid, (pid, 1, 1), {"supplied": True}, False, {"supplied": True},
        id(native_object), id(policy_object), prepare_capability.identity)
    capture_capability = controller.issue_capture_capability(
        prepared, native_object, provider_object)
    capture_capability.consume(
        controller._capability_authority,
        controller_object=controller, native_object=native_object,
        prepared_object=prepared, provider_object=provider_object,
        native_identity=id(native_object), prepared_identity=prepared.identity,
        provider_identity=id(provider_object))
    row = namespace["RawDirectChildCustody"](
        id(provider_object), 58000 + case_index, case["token"],
        case["fixture_metadata"]["captured_fd"], prepared.identity,
        id(native_object), 0)
    controller.reserve("reservation." + case["case_id"][:3])
    controller.attach_raw_custody(prepared, row, post_open_pending=False)
    registration = controller.register_captured(
        case["register"]["request"]["event_id"])
    proof_capability = controller.derive_post_register_proof_capability(
        native_object, policy_object)
    return {
        "ledger": ledger, "controller": controller, "prepared": prepared,
        "row": row, "native_object": native_object,
        "policy_object": policy_object,
        "proof_capability": proof_capability,
        "registration": registration,
    }


def run_hold_case(case, namespace, source_pins, checks, case_index):
    detached = namespace["detached"]
    context = fresh_context(case, namespace, source_pins, case_index)
    ledger = context["ledger"]
    controller = context["controller"]
    capability = context["proof_capability"]
    registration = context["registration"]
    public_rows = [{"request": registration["request"],
                    "reply": registration["reply"]}]
    checks.equal(case["case_id"] + ":register_request",
                 registration["request"], case["register"]["request"])
    checks.equal(case["case_id"] + ":register_reply",
                 registration["reply"], case["register"]["reply"])

    if case["blocked_phase"] != "PROOF_AND_VIEW":
        view = controller.accept_supplied_proof_and_view(
            capability, proof_data(context["prepared"].pid),
            context["native_object"], context["policy_object"])
        checks.true(case["case_id"] + ":view_created_before_external",
                    view is controller._view)
    if case["blocked_phase"] in ("CALLBACK", "COMPLETE"):
        begin_request = case["begin"]["request"]
        begin_reply = controller.begin_close(
            begin_request["attempt_id"], begin_request["event_id"], False)
        public_rows.append({"request": detached(controller._adapter.begin_request),
                            "reply": detached(begin_reply)})
        checks.equal(case["case_id"] + ":begin_request",
                     controller._adapter.begin_request, begin_request)
        checks.equal(case["case_id"] + ":begin_reply",
                     begin_reply, case["begin"]["reply"])

    callback_entries = 0
    if case["blocked_phase"] == "COMPLETE":
        local = {"entries": 0}

        def callback(action):
            local["entries"] += 1
            return None

        normalization = controller.invoke_and_normalize(callback, False)
        callback_entries = local["entries"]
        checks.equal(case["case_id"] + ":pre_external_normalization",
                     [normalization["valid"],
                      normalization["model_outcome"]["result"]],
                     [True, "SUCCESS"])

    external_request = detached(case["external"]["request"])
    external_reply = ledger.submit(detached(external_request))
    public_rows.append({"request": external_request,
                        "reply": detached(external_reply)})
    checks.equal(case["case_id"] + ":external_reply",
                 external_reply, case["external"]["reply"])
    owned_slots_before = controller._expected_slots
    owned_history_before = detached(controller._expected_history)
    callbacks_before_blocked_call = (
        controller._adapter.callback_entries if controller._adapter else 0)
    if case["blocked_phase"] == "PROOF_AND_VIEW":
        blocked = caught_code(lambda: controller.accept_supplied_proof_and_view(
            capability, proof_data(context["prepared"].pid),
            context["native_object"], context["policy_object"]))
    elif case["blocked_phase"] == "BEGIN":
        blocked = caught_code(lambda: controller.begin_close(
            case["case_id"] + ".attempt.blocked",
            case["case_id"] + ".begin.blocked", False))
    elif case["blocked_phase"] == "CALLBACK":
        local = {"entries": 0}

        def blocked_callback(action):
            local["entries"] += 1
            return None

        blocked = caught_code(
            lambda: controller.invoke_and_normalize(blocked_callback, False))
        callback_entries += local["entries"]
    else:
        blocked = caught_code(lambda: controller.complete_close(
            case["case_id"] + ".complete.blocked", False))
    checks.equal(case["case_id"] + ":controlled_stop", blocked,
                 {"type": "LedgerError", "code": "EFFECT_STOPPED_BY_HOLD",
                  "text": "EFFECT_STOPPED_BY_HOLD"})
    first_stop = controller.snapshot()
    second_stop = controller.snapshot()
    checks.equal(case["case_id"] + ":persistent_stop_snapshots",
                 second_stop, first_stop)
    checks.equal(case["case_id"] + ":sticky_holds",
                 first_stop["holds"], case["expected"]["sticky_holds"])
    checks.equal(case["case_id"] + ":stop_and_confirmation",
                 [first_stop["stop"], first_stop["controller_confirmed"]],
                 [case["expected"]["stop"],
                  case["expected"]["controller_confirmed"]])
    checks.equal(case["case_id"] + ":last_owned_baseline_unchanged",
                 [controller._expected_slots, controller._expected_history],
                 [owned_slots_before, owned_history_before])
    checks.equal(case["case_id"] + ":blocked_callback_count",
                 controller._adapter.callback_entries
                 if controller._adapter else 0,
                 callbacks_before_blocked_call)
    checks.equal(case["case_id"] + ":proof_consumption",
                 capability.consumed,
                 case["blocked_phase"] != "PROOF_AND_VIEW")
    checks.equal(case["case_id"] + ":no_blocked_complete",
                 controller._adapter.complete_request
                 if controller._adapter else None, None)
    checks.equal(case["case_id"] + ":public_submission_count",
                 ledger.admission_report()["submission_slots"],
                 case["expected"]["public_submissions"])
    checks.equal(case["case_id"] + ":callback_count",
                 callback_entries, case["expected"]["inert_callbacks"])
    checks.equal(case["case_id"] + ":accepted_history_excludes_external",
                 ledger.report()["history"],
                 [row["request"] for row in public_rows
                  if row["reply"]["accepted"]])
    return {
        "case_id": case["case_id"], "config": detached(case["config"]),
        "token": detached(case["token"]), "fixture_metadata": detached(
            case["fixture_metadata"]), "observations": [],
        "public_events": public_rows, "final_ledger": ledger.report(),
        "final_controller": controller.report(),
        "blocked_observation": blocked,
        "callback_entries": callback_entries, "ledger_instances": 1,
    }


def run_normalization_case(case, namespace, source_pins, checks, case_index):
    detached = namespace["detached"]
    context = fresh_context(case, namespace, source_pins, case_index)
    ledger = context["ledger"]
    controller = context["controller"]
    capability = context["proof_capability"]
    supplied_primary = case["fixture_metadata"]["primary_failure"]
    # Exercise the producer-to-consumer handoff: the value returned by the
    # public capture call is the authority passed to the rollback consumer.
    handed_off_record = controller.capture_primary_failure(
        case["token"], supplied_primary,
        namespace["SUPPLIED_STATIC_REJECTION"], "POST_REGISTER_PROOF",
        {"supplied_trace": case["case_id"],
         "native_identity_validity": "DECLARED_SUPPLIED_PREMISE"},
        capability)
    original_record = controller._primary_record
    checks.true(case["case_id"] + ":capture_returns_retained_record",
                handed_off_record is original_record)
    checks.equal(case["case_id"] + ":capture_return_is_not_a_report",
                 isinstance(handed_off_record, dict), False)
    local = {"entries": 0}

    if case["callback_mode"] == "RETURN_INTEGER_ZERO":
        def callback(action):
            local["entries"] += 1
            return 0
    else:
        def callback(action):
            local["entries"] += 1
            raise ValueError("supplied invalid rollback exception")

    returned = controller.record_primary_and_rollback(
        case["token"], handed_off_record, capability,
        detached(case["rollback_ids"]), callback)
    adapter = controller._adapter
    public_rows = [
        {"request": context["registration"]["request"],
         "reply": context["registration"]["reply"]},
        {"request": detached(adapter.begin_request),
         "reply": detached(adapter.begin_reply)},
    ]
    final = controller.snapshot()
    expected = case["expected"]
    checks.true(case["case_id"] + ":same_primary_returned",
                returned is original_record)
    checks.true(case["case_id"] + ":same_primary_raw_reference",
                original_record.raw_primary_reference is supplied_primary)
    checks.true(case["case_id"] + ":controller_primary_unchanged",
                controller._primary_record is original_record)
    checks.equal(case["case_id"] + ":begin_request",
                 adapter.begin_request, case["begin"]["request"])
    checks.equal(case["case_id"] + ":begin_reply",
                 adapter.begin_reply, case["begin"]["reply"])
    checks.equal(case["case_id"] + ":invalid_normalization",
                 [adapter.normalization["valid"],
                  adapter.normalization["model_outcome"]],
                 [expected["normalization_valid"], expected["model_outcome"]])
    checks.equal(case["case_id"] + ":no_complete",
                 adapter.complete_request, None)
    checks.equal(case["case_id"] + ":ledger_state",
                 ledger.report()["obligations"][0]["state"],
                 expected["ledger_state"])
    checks.equal(case["case_id"] + ":rollback_disposition",
                 controller._rollback, expected["rollback"])
    checks.equal(case["case_id"] + ":stop",
                 final["stop"], expected["stop"])
    checks.equal(case["case_id"] + ":rollback_unconfirmed",
                 original_record.rollback_confirmed, False)
    checks.equal(case["case_id"] + ":one_callback",
                 local["entries"], expected["inert_callbacks"])
    checks.equal(case["case_id"] + ":public_submission_count",
                 ledger.admission_report()["submission_slots"],
                 expected["public_submissions"])
    checks.equal(case["case_id"] + ":no_retry",
                 controller.report()["automatic_retry_actions"], [])
    return {
        "case_id": case["case_id"], "config": detached(case["config"]),
        "token": detached(case["token"]), "fixture_metadata": detached(
            case["fixture_metadata"]), "observations": [],
        "public_events": public_rows, "final_ledger": ledger.report(),
        "final_controller": controller.report(),
        "callback_entries": local["entries"], "ledger_instances": 1,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: pure_candidate_runner.py RUN_DIRECTORY")
    candidate_started_utc = now()
    run = Path(sys.argv[1]).resolve()
    source = run / "SOURCE"
    manifest = load(source / "SOURCE_ISOLATION_MANIFEST.json")
    fixtures = load(source / "SUPPLIED_FIXTURES.json")
    start_forbidden = sorted(name for name in sys.modules
                             if name.split(".")[0] in FORBIDDEN_MODULES)
    namespace, observed_mapping, extracted_nodes = extract_namespace(
        source, manifest)
    after_forbidden = sorted(name for name in sys.modules
                             if name.split(".")[0] in FORBIDDEN_MODULES)
    checks = Checks()
    checks.equal("argv", sys.argv,
                 [str(source / "pure_candidate_runner.py"), str(run)])
    checks.equal("forbidden_modules_before_extraction", start_forbidden, [])
    checks.equal("forbidden_modules_after_extraction", after_forbidden, [])
    fixture_bytes = (source / "SUPPLIED_FIXTURES.json").read_bytes()
    fixture_pin = next(item for item in manifest["source_files"]
                       if item["path"] == "SUPPLIED_FIXTURES.json")
    checks.equal("fixture_pin", [len(fixture_bytes), sha(fixture_bytes)],
                 [fixture_pin["bytes"], fixture_pin["sha256"]])
    checks.equal("p17_regression_provenance",
                 fixtures["p17_regression_provenance"], {
                     "bytes": 43835,
                     "representation": "lossless nested JSON object",
                     "sha256": "78ba822025a6ccfbca37dfd06cddaef97c8fc3dff98c03046f0518bae78afc1c",
                 })
    regression = fixtures["regression_D01_D06"]
    checks.equal("regression_case_ids",
                 [item["trace_id"] for item in regression["traces"]], [
        "D01_NORMAL_REGISTER_PROVE_CLOSE",
        "D02_PROOF_REJECT_ROLLBACK_SUCCESS",
        "D03_PROOF_REJECT_ROLLBACK_ERROR",
        "D04_PROOF_REJECT_BEGIN_DUPLICATE",
        "D05_PROOF_REJECT_COMPLETE_DUPLICATE",
        "D06_REGISTER_REJECT_UNREGISTERED_CUSTODY",
    ])
    source_pins = {item["path"]: item["sha256"]
                   for item in manifest["source_files"]}
    cases = [run_case(trace, namespace, source_pins, checks, index)
             for index, trace in enumerate(regression["traces"], 1)]
    cases.extend(run_hold_case(case, namespace, source_pins, checks, index)
                 for index, case in enumerate(fixtures["hold_cases"], 7))
    cases.extend(run_normalization_case(
        case, namespace, source_pins, checks, index)
        for index, case in enumerate(fixtures["normalization_cases"], 11))
    checks.equal("all_case_ids", [case["case_id"] for case in cases], [
        "D01_NORMAL_REGISTER_PROVE_CLOSE",
        "D02_PROOF_REJECT_ROLLBACK_SUCCESS",
        "D03_PROOF_REJECT_ROLLBACK_ERROR",
        "D04_PROOF_REJECT_BEGIN_DUPLICATE",
        "D05_PROOF_REJECT_COMPLETE_DUPLICATE",
        "D06_REGISTER_REJECT_UNREGISTERED_CUSTODY",
        "H01_EXTERNAL_BEFORE_PROOF", "H02_EXTERNAL_BEFORE_BEGIN",
        "H03_EXTERNAL_BEFORE_CALLBACK", "H04_EXTERNAL_BEFORE_COMPLETE",
        "N01_INVALID_ROLLBACK_RETURN", "N02_INVALID_ROLLBACK_EXCEPTION",
    ])
    public = [row for case in cases for row in case["public_events"]]
    accepted = [row for row in public if row["reply"]["accepted"]]
    rejected = [row for row in public if not row["reply"]["accepted"]]
    reasons = {}
    kinds = {}
    accepted_kinds = {}
    for row in public:
        kind = row["request"]["kind"]
        kinds[kind] = kinds.get(kind, 0) + 1
        if row["reply"]["accepted"]:
            accepted_kinds[kind] = accepted_kinds.get(kind, 0) + 1
        else:
            reason = row["reply"]["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
    totals = {
        "ledger_instances": sum(case["ledger_instances"] for case in cases),
        "public_submissions": len(public), "accepted": len(accepted),
        "rejected": len(rejected), "submissions_by_kind": kinds,
        "accepted_by_kind": accepted_kinds, "rejection_reasons": reasons,
        "inert_callback_entries": sum(case["callback_entries"] for case in cases),
        "step_after_states": sum(len(case["observations"]) for case in cases),
    }
    checks.equal("aggregate_totals", totals, {
        "ledger_instances": 12, "public_submissions": 29,
        "accepted": 22, "rejected": 7,
        "submissions_by_kind": {"REGISTER": 16, "BEGIN": 9, "COMPLETE": 4},
        "accepted_by_kind": {"REGISTER": 11, "BEGIN": 8, "COMPLETE": 3},
        "rejection_reasons": {"DUPLICATE_EVENT_ID": 2, "FD_RANGE": 5},
        "inert_callback_entries": 7, "step_after_states": 32,
    })
    failed = [row for row in checks.rows if not row["passed"]]
    effects = {
        "candidate_processes": 1, "ledger_instances": 12,
        "ledger_public_submissions": len(public),
        "inert_callback_entries": totals["inert_callback_entries"],
        "full_native_module_imports": 0, "native_syscalls_constructions": 0,
        "runtime_bindings_constructions": 0, "native_provider_constructions": 0,
        "development_guard_constructions": 0, "owning_handle_constructions": 0,
        "pidfd_opens": 0, "os_close_calls": 0, "pipes": 0, "sockets": 0,
        "forks": 0, "test_children": 0, "host_proof_queries": 0,
        "waits": 0, "reaps": 0, "signals": 0, "receives": 0,
        "transfers": 0, "network_calls": 0, "formal_executions": 0,
        "formal008_paths_created": 0, "watchdog_terminations": 0,
    }
    result = {
        "schema": "ENGINE003_LINUXPORT001_P17_FIX001_SOURCE_ISOLATED_RESULT_V1",
        "status": "PASS_P17_FIX001_TWELVE_SOURCE_ISOLATED_CASES" if not failed
                  else "FAIL_P17_FIX001_SOURCE_ISOLATED_CASES",
        "started_utc": candidate_started_utc, "ended_utc": now(),
        "source_isolation_manifest": manifest,
        "observed_extraction_mapping": observed_mapping,
        "extracted_ast_nodes_executed": extracted_nodes,
        "full_source_modules_imported_or_executed": 0,
        "cases": cases, "totals": totals, "effects": effects,
        "checks": checks.rows, "check_count": len(checks.rows),
        "failed_count": len(failed), "failed_checks": failed,
        "claim_ceiling": "source-isolated pure implementation only; native/authentic paths static-only",
    }
    write_json(run / "RESULT.json", result)
    print(json.dumps({
        "status": result["status"], "checks": len(checks.rows),
        "failed": len(failed), "totals": totals,
    }, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
