"""DEV_PHASE_EVIDENCE001 portable pure example (no native effects; audit-hook enforced).

After an authentic accepted A, three B dispatches on fresh scopes:
  1. genuine pre-effect lower-controller admission failure (RunContext.admit
     refused inside the exact launch_request): CLOSED_ZERO_EFFECT slot; the
     restart still refuses; an explicit, cause-bound ROOT_NEVER_SPAWNED
     reconciliation is accepted without any identity; the next dispatch is a
     separate explicit act;
  2. the same generic RuntimeError raised by a launcher BEFORE the controller:
     no slot, COORDINATOR_REFUSED, ROOT_NEVER_SPAWNED refused;
  3. the same RuntimeError AFTER the effect handoff (post-spawn): slot
     EFFECT_PERMITTED, ROOT_NEVER_SPAWNED refused.
Fake kernel / FakePopen / MemoryStorage only.  Prints one JSON document.
"""
import json
import os
import sys
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)


def deny(event, args):
    if event in {"subprocess.Popen", "os.fork", "os.forkpty", "os.kill", "os.killpg",
                 "os.system", "os.exec", "os.posix_spawn", "socket.connect"}:
        raise AssertionError("FORBIDDEN_NATIVE_EFFECT:" + event)
    if event == "open" and isinstance(args[0], (str, bytes)) and \
            os.fsdecode(args[0]).startswith("/proc"):
        raise AssertionError("FORBIDDEN_PROC_READ")


sys.addaudithook(deny)
import run_dev006_pure as runner  # noqa: E402
runner.block_host_effects()
if hasattr(os, "pidfd_open"):
    os.pidfd_open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("PIDFD"))

import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix004 as X  # noqa: E402
import test_dev_phase_evidence001 as P  # noqa: E402

C = W.C
J = C.journal_protocol
rows = []


def scenario(name, launcher_for):
    j, p = W.journal(), X.Paths("example")
    real = W.HarnessLauncher(["ACCEPT"] * 4)
    p.call(real, j, W.orch_request(0, p.tmp), stem="a")
    try:
        p.call(launcher_for(real), j, W.orch_request(1, p.tmp), stem="b")
        decision = "ACCEPTED_UNEXPECTED"
    except C.StopSignal as stop:
        decision = stop.stop_id
    ph = P.phase(j)
    final = P.record(j, "000002.FINAL")
    rebuilt = W.rebuilt(j)
    row = {"case": name, "decision": decision,
           "slot": None if ph is None else ph["phase"],
           "slot_cause_phase": None if ph is None or "cause" not in ph
           else ph["cause"]["controller_phase"],
           "stop_reason": final["reason"], "fake_spawns_total": real.spawns,
           "restart_ready": rebuilt.state()["ready"],
           "restart_reason": rebuilt.state()["reason"],
           "next_before_reconcile": list(P.next_dispatch(j))}
    try:
        rebuilt.reconcile(2, P.LABEL, P.never_evidence(rebuilt))
        row["root_never_spawned_reconciliation"] = "ACCEPTED_EXPLICIT"
        row["A_still_accepted"] = J.verify_controller_acceptance(
            p.output("a"), rebuilt)["seq"] == 1
        row["next_after_reconcile_separate_act"] = list(P.next_dispatch(rebuilt))
    except J.JournalRefused as refused:
        row["root_never_spawned_reconciliation"] = f"REFUSED:{refused.code}:{refused.detail}"
    rows.append(row)


def admission(real):
    def launcher(*a, **k):
        with mock.patch.object(C.RunContext, "admit",
                               side_effect=RuntimeError("GENERIC_BOOM")):
            return real(*a, **k)
    return launcher


def before_controller(real):
    def launcher(*a, **k):
        raise RuntimeError("GENERIC_BOOM")
    return launcher


def after_handoff(real):
    def launcher(*a, **k):
        with mock.patch.object(C.CumulativeOutputCollector, "final",
                               side_effect=RuntimeError("GENERIC_BOOM")):
            return real(*a, **k)
    return launcher


scenario("pre_effect_controller_admission", admission)
scenario("generic_error_before_controller", before_controller)
scenario("generic_error_after_effect_handoff", after_handoff)
expect = {"pre_effect_controller_admission": "ACCEPTED_EXPLICIT"}
ok = all(r["root_never_spawned_reconciliation"].startswith(
    expect.get(r["case"], "REFUSED")) and r["next_before_reconcile"] == [True, 0, 0]
    for r in rows)
print(json.dumps({"example": "DEV_PHASE_EVIDENCE001", "native_effects": 0,
                  "all_expectations_met": ok, "rows": rows}, indent=2, default=str))
sys.exit(0 if ok else 1)
