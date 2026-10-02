"""Runnable pure example (no git, no /proc, no signals): the two DEV007_FIX001
repairs through the controller's own launch_request on virtual time,
printed as JSON.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 example_dev007_fix001_pure.py
"""
import json
import sys
import types
from unittest import mock

import run_dev006_pure
import test_dev006 as T
import test_dev007_fix001 as F


def launch_summary(run, stop, calls):
    out = {"stop": None if stop is None else [stop.stop_id, stop.detail],
           "validation_reached": bool(calls),
           "authoritative_output_status": json.loads(run.output_path.read_text())["status"],
           "worker_only_result_present": run.output_path.with_suffix(
               ".worker-unaccepted.json").exists(),
           "completion_record_persisted": run.output_path.with_suffix(
               ".completion-cleanup.json").exists(),
           "context_closed": run.context.closed, "latch_blocked": run.latch.blocked}
    if stop is not None:
        out["unresolved_reasons"] = stop.cleanup["unresolved_reasons"]
    return out


def main():
    run_dev006_pure.block_host_effects()
    out = {}

    # A007-1: resolved normal finish is accepted; unresolved is not.
    out["resolved_normal_finish"] = launch_summary(*F.launch())
    out["root_close_eio"] = launch_summary(*F.launch(route_kwargs=dict(
        close_errors={3: OSError(5, "fake close EIO")})))
    out["held_lease"] = launch_summary(*F.launch(F.hold_lease))
    out["completion_budget_exhausted"] = launch_summary(*F.launch(F.budget_exhausted))

    # A007-2: newer cumulative output carried on a collector exception.
    c = T.C.CumulativeOutputCollector()
    c.timeout_snapshot(b"prefix", "prior")
    e = OSError(5, "collector")
    e.output = b"prefix-more"
    p = types.SimpleNamespace(stdout=None, communicate=mock.Mock(side_effect=e))
    text, rec = T.C._bounded_collect(p, 1, c)
    out["collector_exception_snapshot"] = {
        "text": text, "output_complete": rec["output_complete"],
        "kinds": [s["kind"] for s in rec["output_contract"]["snapshots"]],
        "text_normalization": rec["output_contract"]["text_normalization"]}
    json.dump(out, sys.stdout, indent=2, sort_keys=True, default=list)
    print()


if __name__ == "__main__":
    main()
