"""Runnable portable pure example for DEV007_FIX003 (no native effects).

python3 example_dev007_fix003_pure.py   (from linux_exec/)
Shows: (1) latest IN_FLIGHT lost -> refused by the independent progression
store; (2) explicit unresolved reconciliation refused, complete typed
reconciliation reopens; (3) persisted CLEANUP record and strict consumer
verification, which refuses once ANCHOR+IN_FLIGHT are removed; (4) the
orchestrator adapter turns a raw PASS into a global STOP.
"""
import json
import sys

import run_dev006_pure as runner
import test_dev006 as T
import test_dev007_fix002 as F2
import test_dev007_fix003 as F3

runner.block_host_effects()
C, J = T.C, T.C.journal_protocol
out = {}

j = F3.journal()
j.begin("ORIGINAL", "0" * 64, "raw", "out")
del j.storage.records["000001.IN_FLIGHT"]
out["tail_loss"] = F3.rebuilt(j).state()

j = F3.journal()
run = F3.stopped_launch(j, "RUN-A")
try:
    j.reconcile(1, "RUN-A", {"cited_run_id": "RUN-A", "resolved_facts": [
        {"kind": "STILL_LIVE", "resolved": False}]})
    bad = "ACCEPTED"
except J.JournalRefused as error:
    bad = error.code
j.reconcile(1, "RUN-A", F2.reconciliation(j, "RUN-A"))
out["reconciliation"] = {"unresolved_fact": bad, "complete_typed": j.state()}

j = F3.journal()
run = F3.accepted_launch(j, "RUN-OK")
env = J.verify_controller_acceptance(run.output_path, F3.rebuilt(j))
cleanup = json.loads(j.storage.records["000001.CLEANUP"])
r = F3.rebuilt(j)
del r.storage.records["ANCHOR"], r.storage.records["000001.IN_FLIGHT"]
try:
    J.verify_controller_acceptance(run.output_path, r)
    after = "ACCEPTED"
except J.JournalRefused as error:
    after = error.code
out["acceptance"] = {"verified": env["status"], "cleanup_status": cleanup["status"],
                     "after_anchor_flight_removed": after}

case = F3.OrchestratorConsumerTests("test_raw_pass_is_not_accepted")
res, stop, launcher = case.run_protocol(["RAW_PASS_ONLY", "ACCEPT"], F3.journal())
out["orchestrator_raw_pass"] = {"stop": stop.stop_id, "launcher_calls": launcher.calls,
                                "spawns": launcher.spawns}
res, stop, launcher = case.run_protocol(["ACCEPT", "ACCEPT"], F3.journal())
out["orchestrator_accepted"] = {"status": res["status"],
                                "measured": res["measured_result_count"],
                                "spawns": launcher.spawns}
print(json.dumps(out, indent=2, default=str))
ok = (not out["tail_loss"]["ready"] and bad == "RECONCILIATION_INVALID"
      and out["reconciliation"]["complete_typed"]["ready"]
      and after == "ACCEPTANCE_NOT_JOURNALED"
      and out["orchestrator_raw_pass"]["spawns"] == 0
      and out["orchestrator_accepted"]["spawns"] == 2)
sys.exit(0 if ok else 1)
