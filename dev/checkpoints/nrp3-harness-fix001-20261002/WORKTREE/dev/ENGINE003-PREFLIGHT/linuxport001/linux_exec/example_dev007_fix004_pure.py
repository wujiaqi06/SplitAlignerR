"""DEV007_FIX004 portable pure example (no native effects; fake kernel,
FakePopen and MemoryStorage only).  Run: python3 example_dev007_fix004_pure.py

1. A007F3-1: request A is accepted; a stale launcher then returns A's valid
   envelope for request B (timeout changed): refused before launch.  A
   launcher that really dispatches a mutated request is refused after it.
   The legitimate fresh dispatch of B is accepted (seq 2).
2. Coupled consumer: execute_fresh_authorized_protocol with a stale replay at
   request 2: global STOP, no ledger, no later launch.
3. A007F3-2: timeout + failing timeout evidence write: the structured
   TimeoutExpired primary is kept, the write error is a separate secondary,
   no second cleanup, durable STOP, next dispatch zero spawn.
"""
import json
import os
import sys
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

import run_dev006_pure as runner  # noqa: E402
runner.block_host_effects()
import test_dev006 as T  # noqa: E402
import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix004 as X  # noqa: E402

C, J = T.C, T.C.journal_protocol


def show(label, value):
    print(f"{label}: {json.dumps(value, default=str)}")


# 1 -------------------------------------------------------------------------
j, p = W.journal(), X.Paths("a")
real = W.HarnessLauncher(["ACCEPT"] * 4)
req_a = W.orch_request(0, p.tmp)
p.call(real, j, req_a, stem="a")
env_a = J.verify_controller_acceptance(p.output("a"), j)
req_b = dict(req_a, timeout_seconds=req_a["timeout_seconds"] + 1)
try:
    p.call(lambda *a, **k: env_a, j, req_b, stem="b", output=p.output("a"))
except C.StopSignal as stop:
    show("1a stale envelope for B (Astra probe)", stop.detail)


def mutate(repo, rt, rp, dp, request, *rest, **k):
    return real(repo, rt, rp, dp, dict(request, timeout_seconds=99), *rest, **k)


try:
    p.call(mutate, j, req_b, stem="m")
except C.StopSignal as stop:
    show("1b real dispatch of a mutated request", stop.detail)
result = p.call(real, j, req_b, stem="b")
env_b = J.verify_controller_acceptance(p.output("b"), j)
show("1c fresh B accepted", {"seq": env_b["seq"],
                             "request_bound": env_b["request_sha256"] == X.request_sha(req_b),
                             "status": result["status"]})

# 2 -------------------------------------------------------------------------
out, stop, launcher = X.CoupledProtocolBindingTests().run_protocol(
    ["ACCEPT", "STALE_REPLAY", "ACCEPT"], 3)
show("2 protocol stale replay", {"ledger": out, "stop": stop.stop_id,
                                 "calls": launcher.calls, "spawns": launcher.spawns})

# 3 -------------------------------------------------------------------------
k, root, _ = T.world()
run = T.Launch(k, root)
with mock.patch.object(C, "_timeout_stop_evidence",
                       side_effect=OSError(28, "SECONDARY_TIMEOUT_RECORD_WRITE")):
    stop = run.run()
rec = stop.cleanup
show("3 timeout primary", rec["primary_failure"])
show("3 secondary", rec["secondary_failures"])
show("3 custody/cleanups", {"custody_close_outcome": rec["custody_close_outcome"],
                            "deadline_starts": [e["label"] for e in run.context.evidence
                                                if e["kind"] == "DEADLINE_START"],
                            "failure_cleanups": [e["kind"] for e in run.context.evidence]
                            .count("FAILURE_CLEANUP"),
                            "journal": run.journal.state()["reason"]})
fresh = T.Launch(*T.world(descendant=False)[:2], journal=W.rebuilt(run.journal),
                 run_id="NEXT")
show("3 next dispatch", {"stop": fresh.run().stop_id, "spawns": fresh.popen_calls})
print("EXAMPLE_DEV007_FIX004_OK")
