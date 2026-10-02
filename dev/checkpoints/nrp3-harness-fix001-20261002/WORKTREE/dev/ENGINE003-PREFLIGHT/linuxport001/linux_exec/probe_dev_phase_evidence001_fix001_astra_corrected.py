"""Corrected regression of Astra's PHASE_EVIDENCE001 independent probe
(portable, pure simulation; run from this directory:
PYTHONDONTWRITEBYTECODE=1 python3 -B probe_dev_phase_evidence001_fix001_astra_corrected.py).

Same scenarios as INPUTS/ASTRA_PROBE.py (kept unchanged as input).  Its
defect-characterization rows become hard assertions of the fixed behavior:
  APHASE001-1  a late copied ticket after a reconciliation without FINAL adds
               no record in either store, spawns nothing, scope stays ready;
               also after the next accepted C.
  APHASE001-2  the FIX005 history (A accepted, B lawfully reconciled under
               v3, C accepted) keeps C readable under the new reader, while
               new work stays refused (HISTORICAL_ONLY_RECONCILIATION).
Audit hook + block_host_effects: no fork/kill/Popen/pidfd//proc/socket.
"""
import copy
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def deny(event, args):
    if event in {"subprocess.Popen", "os.fork", "os.forkpty", "os.kill", "os.killpg",
                 "os.system", "os.exec", "os.posix_spawn", "socket.connect"}:
        raise AssertionError("NATIVE_EFFECT:" + event)
    if event == "open" and isinstance(args[0], (str, bytes)) and \
            os.fsdecode(args[0]).startswith("/proc"):
        raise AssertionError("PROC")


sys.addaudithook(deny)
import run_dev006_pure as runner  # noqa: E402
runner.block_host_effects()
if hasattr(os, "pidfd_open"):
    os.pidfd_open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("PIDFD"))
import test_dev007_fix003 as W  # noqa: E402
import test_dev007_fix004 as X  # noqa: E402
import test_dev_phase_evidence001 as P  # noqa: E402

C, J = P.C, P.J
rows = []


def late(real, p, b, ticket, j, stem):
    before, spawns = copy.deepcopy(P.records(j)), real.spawns
    try:
        real(p.tmp, p.tmp / "runtime", p.tmp / "res.json", p.tmp / "dur.json", b,
             p.tmp / "req/b.request.json", p.output("b"), p.tmp / f"logs/{stem}.txt",
             p.tmp / "branch.json", dispatch_ticket=ticket)
        raise AssertionError("late allowed")
    except C.StopSignal as stop:
        assert "DISPATCH_HISTORY_CLOSED" in stop.detail, stop.detail
    assert real.spawns == spawns, "late spawn"
    assert P.records(j) == before, "late write into terminal history"


for mode in ["real_pre_effect", "generic_before_entry", "real_post_effect",
             "closure_first_write_fails", "closure_mirror_fails", "closure_stop_fails"]:
    j = W.journal()
    p = X.Paths(mode)
    real = W.HarnessLauncher(["ACCEPT"] * 12)
    a, b = W.orch_request(0, p.tmp), W.orch_request(1, p.tmp)
    p.call(real, j, a, stem="a")
    old_final, held = j.storage.records["000001.FINAL"], []

    def launch(*args, **kw):
        held.append(kw["dispatch_ticket"])
        if mode == "generic_before_entry":
            raise RuntimeError("SAME_ERROR")
        if mode == "closure_first_write_fails":
            j.progression.fail[("create", "000002.PHASE")] = OSError(28, "SLOT_WRITE")
        if mode == "closure_mirror_fails":
            j.storage.fail[("create", "000002.PHASE")] = OSError(28, "MIRROR_WRITE")
        if mode == "closure_stop_fails":
            j.storage.fail[("create", "000002.FINAL")] = OSError(28, "FINAL_WRITE")
        target, attr = ((C.CumulativeOutputCollector, "final") if mode == "real_post_effect"
                        else (C.RunContext, "admit"))
        with mock.patch.object(target, attr, side_effect=RuntimeError("SAME_ERROR")):
            return real(*args, **kw)
    try:
        p.call(launch, j, b, stem="b")
        raise AssertionError("accepted")
    except C.StopSignal:
        pass
    j.storage.fail.clear()
    j.progression.fail.clear()
    assert P.next_dispatch(j) == (True, 0, 0)
    expected = mode in ["real_pre_effect", "closure_stop_fails"]
    rebuilt = W.rebuilt(j)
    try:
        rebuilt.reconcile(2, P.LABEL, P.never_evidence(rebuilt))
        reconciled = True
    except J.JournalRefused:
        reconciled = False
    assert reconciled == expected, mode
    if reconciled:
        assert rebuilt.state()["ready"]
        j.storage.records.update(rebuilt.storage.records)     # same durable stores
        for stem, t, jj in (("copy_reconstructed", J.DispatchTicket(rebuilt, held[0].binding),
                             rebuilt), ("retained", held[0], j)):
            late(real, p, b, t, jj, stem)
        assert P.next_dispatch(j) == (False, 1, 1)
        # the explicit next dispatch C, then the same late use again
        p.call(real, j, W.orch_request(5, p.tmp), stem="c")
        late(real, p, b, held[0], j, "retained_after_c")
        late(real, p, b, J.DispatchTicket(W.rebuilt(j), held[0].binding), j, "copy_after_c")
        assert J.verify_controller_acceptance(p.output("c"), W.rebuilt(j))["seq"] == 3
        assert W.rebuilt(j).state()["ready"]
    assert j.storage.records["000001.FINAL"] == old_final
    J.verify_controller_acceptance(p.output("a"), rebuilt)
    rows.append(dict(case=mode, passed=True, truthful_reconciliation=reconciled,
                     late_ticket_after_reconciliation=(
                         "NO_WRITE_NO_SPAWN_BEFORE_AND_AFTER_C" if reconciled else None)))

# Pinned FIX005 history: A accepted, B wrong-request refusal lawfully
# reconciled under v3, C accepted.
old = P.fix005_module()
j = old.DispatchJournal(J.MemoryStorage(), run_generation=1, input_identity="I",
                        dispatcher_owner="O", progression=J.MemoryStorage())
j.initialize_scope()
p = X.Paths("migration")
real = W.HarnessLauncher(["ACCEPT"] * 6)
a, b, c = (W.orch_request(i, p.tmp) for i in range(3))


def mutate(*args, **kw):
    aa = list(args)
    aa[4] = dict(aa[4], timeout_seconds=aa[4]["timeout_seconds"] + 1)
    return real(*aa, **kw)


with mock.patch.dict(sys.modules, {"stage_b_dispatch_journal": old}), \
        mock.patch.object(C, "journal_protocol", old):
    p.call(real, j, a, stem="a")
    try:
        p.call(mutate, j, b, stem="b")
        raise AssertionError("wrong accepted")
    except C.StopSignal:
        pass
    j.reconcile(2, P.LABEL, P.never_evidence(j))
    p.call(real, j, c, stem="c")
    assert old.verify_controller_acceptance(p.output("c"), j)["seq"] == 3
    before = P.records(j)
new = J.DispatchJournal(J.MemoryStorage(records=j.storage.records), **j.scope,
                        progression=J.MemoryStorage(records=j.progression.records))
env = J.verify_controller_acceptance(p.output("c"), new)
assert env["seq"] == 3
state = new.state()
assert (state["ready"], state["reason"]) == (False, "HISTORICAL_ONLY_RECONCILIATION")
assert P.next_dispatch(new) == (True, 0, 0)
assert P.records(j) == before and P.records(new) == before
rows.append(dict(case="previously_valid_FIX005_reconciled_B_then_accepted_C",
                 historical_C_readable=True, seq=env["seq"], new_state=state,
                 new_work_refused=True))

# New protocol no-effect check refuses a ticket retained from pre-phase version.
r = old.DispatchJournal(J.MemoryStorage(), run_generation=1, input_identity="OLD",
                        dispatcher_owner="O", progression=J.MemoryStorage())
r.initialize_scope()
ticket = r.reserve(P.LABEL, "1" * 64, "oldraw", "oldout")
nr = J.DispatchJournal(r.storage, **r.scope, progression=r.progression)
nt = J.DispatchTicket(nr, ticket.binding)
try:
    nt.check_execution(run_id=P.LABEL, request_sha256="1" * 64,
                       raw_path=Path("oldraw"), output_path=Path("oldout"))
    raise AssertionError("legacy effect permitted")
except J.JournalRefused as e:
    assert "phase_protocol" in str(e)
rows.append(dict(case="retained_prephase_ticket_cannot_authorize_new_effect", passed=True))
print(json.dumps(dict(method="CORRECTED_REGRESSION_OF_ASTRA_PROBE_PURE_MODEL",
                      native_effects=0, cases=rows), indent=2))
