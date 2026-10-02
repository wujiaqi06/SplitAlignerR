"""Regression copy of the independent Pro boundary probes (DEV007_FIX001
review), adapted to the CORRECTED behaviour.  The original (which asserted
the defects) is archived unchanged in the stage BUILD/pro_probe_archive/.
Same eight records, same fake kernel/virtual time; corrected assertions.
Usage: python3 probe_dev007_fix002_pro_corrected.py --output OUT.json
"""
import argparse, json, os, sys
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()


def deny(event, a):
    if event in {"subprocess.Popen", "os.fork", "os.forkpty", "os.kill", "os.killpg",
                 "os.system", "os.exec", "os.posix_spawn", "socket.connect"}:
        raise AssertionError("FORBIDDEN_NATIVE_EFFECT:" + event)
    if event == "open" and isinstance(a[0], (str, bytes)):
        p = os.fsdecode(a[0])
        if p == "/proc" or p.startswith("/proc/"):
            raise AssertionError("FORBIDDEN_PROC_READ")


import run_dev006_pure as runner  # noqa: E402
runner.block_host_effects()
if hasattr(os, "pidfd_open"):
    os.pidfd_open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("FORBIDDEN_PIDFD"))
import test_dev006 as T, test_dev007_fix001 as V  # noqa: E402,E401
sys.addaudithook(deny)
C, J = T.C, T.C.journal_protocol
rows = []

for acquire_member in [False, True]:
    k, root, child = T.world(descendant=True)
    run = T.Launch(k, root, pipe_holders={root.pid})
    run.desc = child

    def hook(r):
        assert r.popen.eof()
        if acquire_member:
            V.member_acquired(r)
    V.finish(run, hook=hook)
    calls = []
    with V.valid_worker(calls):
        stop = run.run()
    fresh = T.Launch(*T.world(descendant=False)[:2], journal=run.journal, run_id="FRESH")
    fresh_stop = fresh.run()
    r = {"case": "normal_completion_known_live_child", "acquired_member_cap": acquire_member,
         "stop": stop.stop_id, "validated": calls, "reasons": stop.cleanup["unresolved_reasons"],
         "child_state": k.procs[child.pid].state, "context_closed": run.context.closed,
         "dispatch_blocked": run.latch.blocked, "fresh_controller": fresh_stop.stop_id,
         "fresh_popen_calls": fresh.popen_calls}
    assert r["stop"] == V.STOP and not calls and "KNOWN_DESCENDANT_LIVE" in r["reasons"]
    assert not r["context_closed"] and r["dispatch_blocked"] and r["fresh_popen_calls"] == 0
    rows.append(r)

k, root, _ = T.world(descendant=False)
route = T.sim_route(k, close_errors={3: OSError(5, "injected close EIO")})
ctx = T.context_for(k, T.make_backend(k), route)
ctx.admit()


def verify_reject(handle):
    raise T.Refused(1, "POST_OPEN_IDENTITY_MISMATCH")
try:
    route.table.acquire(root.pid, "ROOT", T.ident(root), "DIRECT_CHILD_PROOF", verify_reject)
except Exception as exc:
    err = f"{type(exc).__name__}:{exc}"
out = ctx.close()
cap = route.table.report()["capabilities"][0]
rows.append({"case": "acquisition_reject_close_error_untracked", "caught": err,
             "entry": cap, "context_close": out, "context_closed": ctx.closed})
assert "POST_OPEN_IDENTITY_MISMATCH" in err and cap["state"] == "CLOSE_FAILED"
assert not ctx.closed and "EIO" in cap["close_error"]

k, root, _ = T.world(descendant=False)
route = T.sim_route(k, close_errors={3: OSError(5, "rollback close EIO")})
ctx = T.context_for(k, T.make_backend(k), route)
ctx.admit()
boundary = {}


def teardown_during_verify(handle):
    boundary.update(fd_allocated=handle.fd, context_close=ctx.close(), custody_at_close=ctx.custody)
try:
    route.table.acquire(root.pid, "ROOT", T.ident(root), "DIRECT_CHILD_PROOF", teardown_during_verify)
except Exception as exc:
    err = f"{type(exc).__name__}:{exc}"
rows.append({"case": "inflight_open_not_counted_by_teardown", "boundary": boundary,
             "caught": err, "context_closed": ctx.closed, "table": route.table.report()})
assert not boundary["custody_at_close"]["resolved"] and not ctx.closed

k, root, _ = T.world(descendant=False)
run = T.Launch(k, root)
first = OSError(5, "watchdog collector EIO")
first.output = b"valuable-only-snapshot"
count = [0]


def broken_communicate(timeout=None):
    count[0] += 1
    raise first if count[0] == 1 else OSError(5, "cleanup collector EIO")
run.popen.communicate = broken_communicate
stop = run.run()
rows.append({"case": "watchdog_exception_snapshot_lost", "stop": stop.stop_id,
             "log": run.log_path.read_text(),
             "complete": stop.cleanup["output_contract"]["complete"]})
assert run.log_path.read_text() == "valuable-only-snapshot" and not rows[-1]["complete"]

for fail_stop in [False, True]:
    k, root, _ = T.world(descendant=False)
    run = T.Launch(k, root, stuck_sampler=True)
    V.finish(run)
    calls = []
    replaced = []
    real = J.publish_no_clobber

    def publish(path, data):
        if fail_stop and Path(path).parent == run.tmp / "out":
            raise OSError(28, "injected ENOSPC")
        return real(path, data)

    def replace(a, b):
        replaced.append((a, b))
        raise OSError(5, "injected move EIO")
    with V.valid_worker(calls), mock.patch.object(C.os, "replace", replace), \
            mock.patch.object(J, "publish_no_clobber", publish):
        stop = run.run()
    rows.append({"case": "raw_result_loss_after_failed_move", "stop_write_failed": fail_stop,
                 "raw_preserved": json.loads(run.raw_path.read_text()) == V.WORKER_RESULT,
                 "move_attempted": bool(replaced),
                 "disposition": stop.cleanup["worker_output_disposition"],
                 "evidence_write_failure": stop.cleanup.get("evidence_write_failure"),
                 "dispatch_blocked": run.latch.blocked})
    assert rows[-1]["raw_preserved"] and not replaced and run.latch.blocked

k, root, _ = T.world(descendant=False)
run = T.Launch(k, root, route_factory=lambda: T.sim_route(k, eperm={root.pid}))
run.popen.communicate = lambda timeout=None: (_ for _ in ()).throw(OSError(5, "PRIMARY_COLLECTOR_ERROR"))
run.popen.wait = lambda timeout=None: (_ for _ in ()).throw(OSError(5, "SECONDARY_WAIT_ERROR"))
stop = run.run()
nxt = T.Launch(*T.world(descendant=False)[:2], latch=run.latch, journal=run.journal)
nxt_stop = nxt.run()
rows.append({"case": "cleanup_secondary_error_escapes", "stop": stop.stop_id,
             "original_failure": stop.cleanup["original_failure"],
             "secondary": stop.cleanup["secondary_failures"],
             "dispatch_blocked": run.latch.blocked, "root_state": k.procs[root.pid].state,
             "held": len(run.route.table.held_caps()), "next": nxt_stop.stop_id,
             "next_popen_calls": nxt.popen_calls})
assert "PRIMARY_COLLECTOR_ERROR" in rows[-1]["original_failure"] and run.latch.blocked
assert rows[-1]["held"] == 1 and nxt.popen_calls == 0

result = {"basis": "corrected regression copy of Pro probes; FakeKernel/virtual time",
          "native_effects": 0, "cases": rows}
args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
print(json.dumps({"cases": len(rows), "all_corrected_assertions": True}))
