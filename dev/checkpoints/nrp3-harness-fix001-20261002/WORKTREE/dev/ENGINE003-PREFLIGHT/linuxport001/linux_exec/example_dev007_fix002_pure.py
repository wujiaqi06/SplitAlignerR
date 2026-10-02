"""Runnable portable pure example for DEV007_FIX002 (no native effects).

python3 example_dev007_fix002_pure.py
Shows: known-live descendant refused (fresh controller refused too),
genuinely exited descendant accepted with a verified envelope, and an
uninitialized journal scope refused with zero spawn.
"""
import json
import sys

import run_dev006_pure as runner
import test_dev006 as T
import test_dev007_fix001 as V

runner.block_host_effects()
C, J = T.C, T.C.journal_protocol
out = {}

k, root, child = T.world(descendant=True)
run = T.Launch(k, root, pipe_holders={root.pid})
V.finish(run)
with V.valid_worker([]):
    stop = run.run()
fresh = T.Launch(*T.world(descendant=False)[:2], journal=run.journal, run_id="FRESH")
out["known_live_child"] = {
    "stop": stop.stop_id, "reasons": stop.cleanup["unresolved_reasons"],
    "child_state": k.procs[child.pid].state, "context_closed": run.context.closed,
    "raw_preserved": json.loads(run.raw_path.read_text()) == V.WORKER_RESULT,
    "fresh_controller": fresh.run().stop_id, "fresh_popen_calls": fresh.popen_calls,
    "journal_state": run.journal.state()}

k, root, child = T.world(descendant=True)
run = T.Launch(k, root)
V.finish(run, hook=lambda r: r.k.exit(child.pid, 0))
with V.valid_worker([]):
    stop = run.run()
env = J.verify_controller_acceptance(run.output_path, run.journal)
out["dead_descendant_control"] = {"stop": stop, "envelope_status": env["status"],
                                  "raw_sha256": env["raw_worker_result_sha256"],
                                  "journal_state": run.journal.state()}

j = J.DispatchJournal(J.MemoryStorage(), run_generation=1, input_identity="I",
                      dispatcher_owner="D")
run = T.Launch(*T.world(descendant=False)[:2], journal=j)
out["uninitialized_scope"] = {"stop": run.run().stop_id, "popen_calls": run.popen_calls}
print(json.dumps(out, indent=2, default=str))
ok = (out["known_live_child"]["stop"] == V.STOP
      and out["known_live_child"]["fresh_popen_calls"] == 0
      and out["dead_descendant_control"]["stop"] is None
      and out["uninitialized_scope"]["popen_calls"] == 0)
sys.exit(0 if ok else 1)
