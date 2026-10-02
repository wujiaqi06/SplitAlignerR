"""Runnable pure example (no git, no /proc, no signals): three DEV006 paths
through the controller's own launch_request on virtual time, printed as JSON.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 example_dev006_pure.py
"""
import json
import sys

import run_dev006_pure
import test_dev006 as T
from synthetic import advance


def summary(run, stop):
    rec = getattr(stop, "cleanup", None) or run.evidence()["termination"]
    keys = ("original_failure", "signal_outcomes", "root_process_reaped",
            "residual_owned_targets", "output_complete", "collector_state",
            "sampler_stop", "custody_close_outcome", "cleanup_deadline_exhausted",
            "unresolved_reasons", "dispatch_blocked", "whole_process_tree_quiescent")
    return {"stop": [stop.stop_id, stop.detail], "virtual_elapsed_seconds": run.elapsed,
            "record": {k: rec[k] for k in keys if k in rec},
            "delivered_signals": T.delivered(run.route.port)
            if hasattr(run.route.port, "effects") else [],
            "latch_blocked": run.latch.blocked}


def main():
    run_dev006_pure.block_host_effects()
    out = {}
    k, root, desc = T.world()
    run = T.Launch(k, root)
    out["timeout_cooperative_resolved"] = summary(run, run.run())

    k, root, _ = T.world(descendant=False, root_leader=False)
    run = T.Launch(k, root, route_factory=lambda: T.termination.LinuxDevelopmentRoute(
        T.C, T.termination.NativeTerminationUnavailable(T.Refused), run_id="RUN-A"))
    out["init_failure_native_port_denied"] = summary(run, run.run())
    nxt = T.Launch(*T.world()[:2], latch=run.latch)
    stop = nxt.run()
    out["next_request_after_unresolved"] = {"stop": [stop.stop_id, stop.detail],
                                            "popen_calls": nxt.popen_calls}

    k, root, desc = T.world()
    run = T.Launch(k, root, pipe_holders={root.pid, desc.pid},
                   route_factory=lambda: T.sim_route(k, ignore_term={desc.pid}))

    def waiter(process, seconds):
        k.procs[desc.pid].pgid = 5700
        advance(k, seconds)
        return process.poll() is not None
    run.waiter = waiter
    out["escape_during_grace_pipe_held"] = summary(run, run.run())
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
