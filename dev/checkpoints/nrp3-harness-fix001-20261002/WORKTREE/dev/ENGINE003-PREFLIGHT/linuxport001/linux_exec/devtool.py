#!/usr/bin/env python3
"""Developer entry point for the Linux execution/lifecycle layer (development only).

    python3 devtool.py test                    # unit + adverse synthetic tests (both suites)
    python3 devtool.py example [--out DIR]     # synthetic end-to-end lifecycle, then
                                               # the shared controller's timeout
                                               # state machine on the Linux
                                               # development route (synthetic signals)
    python3 devtool.py preflight --out DIR     # native admission only: no fork
    python3 devtool.py native --out DIR        # one native lifecycle attempt

`native` forks one harmless owned child, acquires one provider pidfd through
the unchanged p18 NativeOwnerController, samples the owned process group with
the unchanged control-plane ProcessTreeRssSampler on the Linux /proc backend,
stops the child by a control-pipe message (never a signal), observes the exit
through the borrowed pidfd, performs the one public normal close and reaps.
`run_lifecycle` performs that admission itself immediately before any pipe
or fork; no caller-supplied approval is accepted. Evidence goes to DIR/evidence.json;
an existing DIR is refused. `--pins` defaults to DEV_BUILD001 INPUTS/SOURCE_PINS.json.

Nothing here is formal host, boot, timing, resource or durability authority.
"""
import argparse
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lifecycle  # noqa: E402
import wiring  # noqa: E402
from lifecycle import LifecycleConfig, describe_exception, safe  # noqa: E402


def emit(ev, evidence):
    ev["overall_ok"] = (ev.get("primary_failure") is None and bool(ev["checks"])
                        and all(c["ok"] for c in ev["checks"]))
    if evidence is not None:
        json.dump(safe(ev), evidence, indent=1, sort_keys=True)
        evidence.close()
    for c in ev["checks"]:
        print(("ok   " if c["ok"] else "FAIL ") + c["name"])
    if ev.get("primary_failure"):
        print("primary_failure:", json.dumps(safe(ev["primary_failure"])), file=sys.stderr)
    result = ev.get("result") or {}
    if result.get("primary_failure"):
        print("lifecycle_failure:", json.dumps(result["primary_failure"]), file=sys.stderr)
    for failure in (result.get("cleanup") or {}).get("failures", []):
        print("cleanup_failure:", json.dumps(safe(failure)), file=sys.stderr)
    print("overall_ok:", ev["overall_ok"])
    return 0 if ev["overall_ok"] else 1


def open_evidence(out):
    out = os.path.realpath(out)
    if os.path.exists(out):
        raise SystemExit("refusing to reuse evidence dir " + out)
    os.makedirs(out)
    # Opened before any fork or guard, so evidence is writable even if a
    # guard is later left installed outside IDLE.
    return out, open(os.path.join(out, "evidence.json"), "x")


def cmd_example(args):
    out, evidence = open_evidence(args.out) if args.out else (None, None)
    cfg = LifecycleConfig()
    ev = {"mode": "synthetic_example", "primary_failure": None, "checks": [],
          "claim": "SYNTHETIC_FAKE_KERNEL_AND_CUSTODY_DOUBLE_NO_HOST_EFFECTS"}
    try:
        ports, _kernel = wiring.synthetic_ports()
        ev["result"] = lifecycle.run_lifecycle(cfg, ports)
        ev["checks"] = lifecycle.evaluate(cfg, ev["result"])
        ev["checks"] += ports.custody.evaluate(ev["result"]["custody"], ev["result"]["pid"])
        ev["timeout_route"] = synthetic_timeout_route()
        ev["checks"] += ev["timeout_route"]["checks"]
    except BaseException as exc:
        ev["primary_failure"] = describe_exception(exc)
    return emit(ev, evidence)


def synthetic_timeout_route():
    """Shared controller exact_timeout_state_machine on the registered Linux
    development route: root obeys SIGTERM, a descendant ignores it, so the
    validated SIGKILL path runs. Signals are SYNTHETIC (fake kernel); this
    says nothing about Linux native signal behaviour."""
    import control_plane
    import termination
    from synthetic import SELF_PID, FakeGroupSignals, FakeKernel, FakePopen, \
        FakeProcSource
    controller, _sha = control_plane.load_controller()
    k = FakeKernel()
    root = k.spawn(SELF_PID)
    desc = k.spawn(root.pid, pgid=root.pid, session=root.pid)
    backend = control_plane.linux_backend(controller, FakeProcSource(k),
                                          wiring.load_verified_parsers().parse_proc_stat,
                                          sleep=lambda s: None)
    sampler = control_plane.make_sampler(controller, root.pid, backend)
    control_plane.sample_once(sampler)
    route = termination.LinuxDevelopmentRoute(controller, FakeGroupSignals(k, {desc.pid}))
    controller.register_linux_development_route(route)
    try:
        result = controller.exact_timeout_state_machine(
            FakePopen(k, root.pid), lambda proc, seconds: proc.poll() is not None,
            sampler.owned_identity_snapshot, backend)
    finally:
        controller.register_linux_development_route(None)
    sent = [(e["pgid"], e["signal"]) for e in route.log if e["outcome"] == "SENT"]
    checks = [
        {"name": "timeout_route_term_then_validated_kill", "observed": sent,
         "ok": sent == [(root.pid, 15), (root.pid, 9)]},
        {"name": "timeout_route_descendant_survived_grace_then_quiescent",
         "observed": result["survivor_pids_after_grace"],
         "ok": result["survivor_pids_after_grace"] == [desc.pid]
         and result["whole_process_tree_quiescent"] is True},
        {"name": "timeout_route_unregistered_after_example",
         "observed": None, "ok": controller._LINUX_DEVELOPMENT_ROUTE is None},
    ]
    return {"claim": "SYNTHETIC_SIGNALS_NOT_LINUX_NATIVE_SIGNAL_VALIDATION",
            "result": result, "route_log": route.log, "checks": checks}


def cmd_native(args, run):
    out, evidence = open_evidence(args.out)
    cfg = LifecycleConfig()
    ev = {"mode": "native" if run else "preflight", "primary_failure": None,
          "checks": [], "forks": 0, "stage": "SETUP",
          "claim": "DEVELOPMENT_EVIDENCE_ONLY_NOT_HOST_OR_PLATFORM_AUTHORITY"}
    try:
        ev["files"] = wiring.file_digests()
        ports, ev["setup"] = wiring.native_ports(cfg, args.pins, out)
        ev["stage"] = "PREFLIGHT"
        if not run:
            ev["admission"] = lifecycle.preflight(cfg, ports)
            # Census counters/timings of the unguarded preflight scans.
            ev["preflight_backend"] = ports.backend.authority_evidence()
            ev["checks"] = [dict(c, name="preflight_" + c["name"])
                            for c in ev["admission"]["checks"]]
        else:
            # run_lifecycle admits internally on these exact cfg/ports.
            ev["stage"] = "LIFECYCLE"
            try:
                ev["result"] = lifecycle.run_lifecycle(cfg, ports)
            except lifecycle.LifecycleError as exc:
                ev["admission"] = exc.admission
                raise
            ev["admission"] = ev["result"]["admission"]
            ev["forks"] = ev["result"]["forks"]
            ev["checks"] = lifecycle.evaluate(cfg, ev["result"])
            ev["checks"] += ports.custody.evaluate(ev["result"]["custody"],
                                                   ev["result"]["pid"])
    except BaseException as exc:
        ev["primary_failure"] = describe_exception(exc, ev["stage"])
    return emit(ev, evidence)


def cmd_test(args):
    """This layer's suite, then the smoke-driver suite whose helpers it reuses."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    rc = 0
    for cwd, module in ((HERE, "test_linux_exec"), (HERE, "test_controller_dispatch"),
                        (lifecycle.DEV_BUILD001, "test_native_close_smoke")):
        rc |= subprocess.call([sys.executable, "-m", "unittest", "-v", module],
                              cwd=cwd, env=env)
    return rc


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("test")
    e = sub.add_parser("example")
    e.add_argument("--out")
    for name in ("preflight", "native"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--pins", default=wiring.DEFAULT_PINS)
    args = ap.parse_args(argv)
    if args.command == "test":
        return cmd_test(args)
    if args.command == "example":
        return cmd_example(args)
    return cmd_native(args, run=args.command == "native")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
