"""Runnable pure example (no git, no /proc, no signals): the four DEV007
repairs through the controller's own launch_request / capability table on
virtual time, printed as JSON.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 example_dev007_pure.py
"""
import json
import sys

import run_dev006_pure
import termination
import test_dev006 as T
import test_dev007 as D


def main():
    run_dev006_pure.block_host_effects()
    out = {}

    # A006-1 + A006-4: normal timeout, pre-timeout output only.
    k, root, desc = T.world()
    run = T.Launch(k, root)
    run.popen.write("prefix\n")
    stop = run.run()
    term = run.evidence()["termination"]
    out["timeout_custody_and_output"] = {
        "stop": [stop.stop_id, stop.detail],
        "custody_close_outcome": term["custody_close_outcome"],
        "root": [(r["pid"], r["state"]) for r in term["custody"]["root"]],
        "members": [(r["pid"], r["state"]) for r in term["custody"]["members"]],
        "context_closed": run.context.closed, "latch_blocked": run.latch.blocked,
        "log": run.log_path.read_text(),
        "open_fds_after": sorted(run.route.port.fd_pool.used)}

    # A006-2: closed context refused before any spawn.
    k, root, _ = T.world(descendant=False)
    run = T.Launch(k, root)
    factory = run.context_factory

    def closed(backend):
        ctx = factory(backend)
        ctx.close()
        return ctx
    run.context_factory = closed
    stop = run.run()
    out["closed_context_admission"] = {"stop": [stop.stop_id, stop.detail],
                                       "popen_calls": run.popen_calls,
                                       "latch_blocked": run.latch.blocked}

    # A006-2: normal exit with a sampler that never stops.
    k, root, _ = T.world(descendant=False)
    run = T.Launch(k, root, stuck_sampler=True)
    D.completed(run)
    stop = run.run()
    out["normal_exit_stuck_sampler"] = {
        "stop": [stop.stop_id, stop.detail],
        "unresolved_reasons": stop.cleanup["unresolved_reasons"],
        "custody_close_outcome": stop.cleanup["custody_close_outcome"],
        "context_closed": run.context.closed, "latch_blocked": run.latch.blocked}

    # A006-3: every lock-boundary interleaving of close+fd reuse vs a signal.
    out["lock_boundary_interleavings"] = [
        {key: row[key] for key in ("fire_at", "outcome", "actor", "signals",
                                   "bystander_state")}
        for row in D.boundary_interleavings(termination)]
    json.dump(out, sys.stdout, indent=2, sort_keys=True, default=list)
    print()


if __name__ == "__main__":
    main()
