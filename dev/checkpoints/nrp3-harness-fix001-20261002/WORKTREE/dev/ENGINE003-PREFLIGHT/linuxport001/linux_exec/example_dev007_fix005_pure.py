"""DEV007_FIX005 portable pure example (no native effects; audit-hook enforced).

Pro/Astra REVIEW_Q1: fix request R, let an injected launcher execute R'
(timeout+1) on a new seq/path, then reconstruct the controller from the same
two stores and try the next legitimate request.  Also shows a legitimate
A -> B with the same display run id, and read-only recovery after a lost
return.  Runs unchanged against the FIX004 tree (reproduces the defect) and
the FIX005 tree (durable refusal).  Prints one JSON document.
"""
import json
import os
import sys
from pathlib import Path

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

C = W.C
J = C.journal_protocol
rows = []


def attempt(launcher, j, request, paths, stem):
    try:
        out = paths.call(launcher, j, request, stem=stem)
        return {"decision": "ACCEPTED", "status": out.get("status")}
    except C.StopSignal as stop:
        return {"decision": stop.stop_id, "detail": stop.detail[:160]}


# Q1: wrong request R' executed for R
j, p = W.journal(), X.Paths("q1")
req = W.orch_request(0, p.tmp)
real = W.HarnessLauncher(["ACCEPT"] * 4)


def mutate(repo, rt, rp, dp, request, *rest, **kw):
    return real(repo, rt, rp, dp, dict(request, timeout_seconds=request["timeout_seconds"] + 1),
                *rest, **kw)


current = attempt(mutate, j, req, p, "wrong-request")
final = j.storage.records.get("000001.FINAL")
rebuilt = W.rebuilt(j)
nxt = W.HarnessLauncher(["ACCEPT"])
after = attempt(nxt, rebuilt, W.orch_request(1, p.tmp), p, "after-refusal")
rows.append({"case": "REVIEW_Q1_wrong_request_then_reconstructed_next_dispatch",
             "current_decision": current,
             "durable_final_seq1": None if final is None else json.loads(final).get("status"),
             "durable_final_reason": None if final is None else json.loads(final).get("reason"),
             "wrong_request_fake_spawns": real.spawns,
             "reconstructed_ready": rebuilt.state()["ready"] if after["decision"] != "ACCEPTED"
             else True,
             "next_launcher_calls": nxt.calls, "next_fake_spawns": nxt.spawns,
             "next_decision": after["decision"]})

# Legitimate A then B, same display run id (FIX005 API only)
if hasattr(J, "reserve_current_dispatch"):
    j2, p2 = W.journal(), X.Paths("ab")
    ok = W.HarnessLauncher(["ACCEPT"] * 3)
    a = attempt(ok, j2, W.orch_request(0, p2.tmp), p2, "a")
    b = attempt(ok, j2, W.orch_request(1, p2.tmp), p2, "b")
    tickets = [json.loads(j2.storage.records[f"00000{n}.FINAL"])["ticket_sha256"]
               for n in (1, 2)]
    rows.append({"case": "A_then_B_same_run_label", "a": a["decision"], "b": b["decision"],
                 "run_ids": [json.loads(j2.storage.records[f"00000{n}.IN_FLIGHT"])["run_id"]
                             for n in (1, 2)],
                 "distinct_tickets": tickets[0] != tickets[1],
                 "history": [h["status"] for h in W.rebuilt(j2).state()["history"]]})
    env = J.recover_committed_dispatch(
        W.rebuilt(j2), 2, request_sha256=X.request_sha(W.orch_request(1, p2.tmp)),
        output_path=p2.output("b"))
    rows.append({"case": "read_only_recovery_same_ticket", "seq": env["seq"],
                 "spawns_total": ok.spawns})

print(json.dumps({"method": "PURE_SIMULATION_INJECTED_FAKE_KERNEL",
                  "native_effects": 0,
                  "has_fix005_protocol": hasattr(J, "reserve_current_dispatch"),
                  "cases": rows}, indent=2))
