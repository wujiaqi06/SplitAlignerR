"""Regression copy of Astra's executed FIX003 probe script
(INPUTS/CURRENT_ASTRA_FIX003_PROBES_EXECUTED.py; the original is preserved
unchanged and still ASSERTS the two defects exist).

Changes from the original, and nothing else:
  * CODE = this directory (WORKTREE) instead of Astra's independent tree;
  * results are written to the directory given as argv[1];
  * the two NEW_A007F3 cases assert the FIX004 behaviour instead of the
    defect: the same stale-launcher replay is refused with a global STOP
    and no launcher call, and the injected _timeout_stop_evidence OSError is
    a secondary failure next to the retained structured TimeoutExpired;
  * one extra case repeats the replay at a FRESH output path (the launcher
    is then called and its stale envelope is refused).
All earlier rows (D1-D5, A007F2-1/2/3, consumer harness) are verbatim.
"""
from pathlib import Path
import sys, json, os, types
from unittest import mock
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
CODE = HERE
sys.path.insert(0, str(CODE))
def deny(event, args):
    if event in {'subprocess.Popen','os.fork','os.forkpty','os.kill','os.killpg','os.system','os.exec','os.posix_spawn','socket.connect'}:
        raise AssertionError('FORBIDDEN_NATIVE_EFFECT:'+event)
    if event == 'open' and isinstance(args[0], (str,bytes)) and os.fsdecode(args[0]).startswith('/proc'):
        raise AssertionError('FORBIDDEN_PROC_READ')
sys.addaudithook(deny)
import run_dev006_pure as runner
runner.block_host_effects()
if hasattr(os,'pidfd_open'):
    os.pidfd_open = lambda *a,**k: (_ for _ in ()).throw(AssertionError('PIDFD_FORBIDDEN'))
import test_dev006 as T
import test_dev007_fix001 as V
C,J=T.C,T.C.journal_protocol
rows=[]

# Independent launch/cleanup assertions on exact candidate, fake processes only.
for live in (True, False):
    for member in (False,True):
        k,root,child=T.world(descendant=True)
        run=T.Launch(k,root,pipe_holders={root.pid});run.desc=child
        def hook(r):
            if member:V.member_acquired(r)
            if not live:k.exit(child.pid,0)
        V.finish(run,hook=hook)
        calls=[]
        with V.valid_worker(calls):stop=run.run()
        if live:
            assert stop.stop_id==V.STOP and not calls and run.latch.blocked and not run.context.closed
        else:
            assert stop is None and J.verify_controller_acceptance(run.output_path,run.journal)['status']=='CONTROLLER_ACCEPTED'
        rows.append({'case':'D1_known_descendant','alive':live,'member_cap':member,'passed':True})

k,root,_=T.world(descendant=False)
run=T.Launch(k,root,route_factory=lambda:T.sim_route(k,eperm={root.pid}))
primary=OSError(5,'PRIMARY');primary.output=b'valuable-only-snapshot';count=[0]
def collect(timeout=None):
    count[0]+=1
    raise primary if count[0]==1 else OSError(5,'SECONDARY_COLLECT')
run.popen.communicate=collect
run.popen.wait=mock.Mock(side_effect=OSError(5,'SECONDARY_WAIT'))
stop=run.run()
assert 'PRIMARY' in stop.cleanup['original_failure'] and 'SECONDARY_WAIT' in json.dumps(stop.cleanup)
assert run.log_path.read_text()=='valuable-only-snapshot' and run.latch.blocked and not run.context.closed
fresh=T.Launch(*T.world(descendant=False)[:2],journal=run.journal,run_id='FRESH-D2')
assert fresh.run().stop_id=='SB_STOP_DISPATCH_JOURNAL' and fresh.popen_calls==0
rows.append({'case':'D2_D5_primary_secondary_snapshot_and_restart','passed':True,'elapsed':run.elapsed})

k,root,_=T.world(descendant=False);route=T.sim_route(k,close_errors={3:OSError(5,'ROLLBACK_EIO')})
ctx=T.context_for(k,T.make_backend(k),route);ctx.admit();during={}
def verify(handle):
    during.update(close=ctx.close(),custody=ctx.custody)
    raise T.Refused(1,'VERIFY_REJECTED')
try:route.table.acquire(root.pid,'ROOT',T.ident(root),'P',verify)
except T.Refused as e:assert 'VERIFY_REJECTED' in str(e)
assert not during['custody']['resolved'] and not ctx.closed
assert route.table.report()['capabilities'][0]['state']=='CLOSE_FAILED'
rows.append({'case':'D3_pending_verify_teardown_rollback_error','passed':True})

k,root,_=T.world(descendant=False);run=T.Launch(k,root,stuck_sampler=True);V.finish(run)
with V.valid_worker([]),mock.patch.object(J,'publish_no_clobber',side_effect=OSError(28,'ALL_LATER_WRITES_FAIL')):
    stop=run.run()
assert json.loads(run.raw_path.read_text())==V.WORKER_RESULT
assert not run.journal.state()['ready'] and run.latch.blocked
rows.append({'case':'D4_raw_preserved_all_stop_writes_fail','passed':True})

def journal():
    j=J.DispatchJournal(J.MemoryStorage(),run_generation=1,input_identity='I',dispatcher_owner='O',progression=J.MemoryStorage())
    j.initialize_scope();return j

j=journal();j.begin('ORIGINAL','0'*64,'raw','out');del j.storage.records['000001.IN_FLIGHT']
new=J.DispatchJournal(J.MemoryStorage(records=j.storage.records),**j.scope,progression=J.MemoryStorage(records=j.progression.records))
assert not new.state()['ready']
try:new.begin('NEW-RUN','1'*64,'raw2','out2');raise AssertionError('reopened')
except J.JournalRefused as error:reason=error.code
rows.append({'case':'A007F2_1_missing_flight_after_restart','passed':True,'reason':reason})

j=journal();j.begin('ORIGINAL','0'*64,'raw','out')
try:j.reconcile(1,'ORIGINAL',{'cited_run_id':'ORIGINAL','resolved_facts':[{'kind':'STILL_LIVE','resolved':False}]});raise AssertionError('reconciled')
except J.JournalRefused:pass
assert not j.state()['ready']
rows.append({'case':'A007F2_2_unresolved_reconciliation_refused','passed':True})

run,stop,calls=V.launch();assert stop is None
assert '000001.CLEANUP' in run.journal.storage.records
assert J.verify_controller_acceptance(run.output_path,run.journal)['status']=='CONTROLLER_ACCEPTED'
del run.journal.storage.records['ANCHOR'];del run.journal.storage.records['000001.IN_FLIGHT']
try:J.verify_controller_acceptance(run.output_path,run.journal);raise AssertionError('accepted')
except J.JournalRefused as error:reason=error.code
rows.append({'case':'A007F2_3_persisted_cleanup_missing_anchor_flight_refused','passed':True,'reason':reason})

import test_dev007_fix003 as W
# Actual downstream flow, scientific authority/plan/kernel remain fake.
case=W.OrchestratorConsumerTests()
for modes in [['OK','OK'],['RAW_PASS_ONLY','OK']]:
    try:
        output=case.run_protocol(modes,W.journal())
    except AttributeError:
        raise
    rows.append({'case':'consumer_harness_'+modes[0],'output_summary':str(output)[:300]})

# FIX004 regression of the independent adapter counterexample: authentic old
# evidence for request A is replayed for a different current request B.
run,stop,calls=V.launch();assert stop is None
env=J.verify_controller_acceptance(run.output_path,run.journal)
request=json.loads((run.tmp/'request.json').read_text());request['timeout_seconds']+=1
O=W.orchestrator()
launcher_calls=[0]
def stale(*a,**k):
    launcher_calls[0]+=1;return env
before_state=run.journal.state()
try:
    O.journaled_exact_launch(stale,run.journal,run.tmp,run.tmp/'runtime',run.tmp/'res.json',run.tmp/'dur.json',request,run.tmp/'new-request.json',run.output_path,run.log_path,run.tmp/'res.json','INDEPENDENT_REPLAY')
    raise AssertionError('stale acceptance returned for current request')
except C.StopSignal as refused:
    assert refused.stop_id=='SB_STOP_GLOBAL' and 'later_launches=0' in refused.detail
    detail=refused.detail
assert env['request_sha256']!=J.sha256(C.canonical_json_bytes(request))
assert launcher_calls[0]==0 and run.journal.state()==before_state
rows.append({'case':'NEW_A007F3_1_current_request_mismatch_replay','defect_reproduced':False,'refused':True,'launcher_calls':launcher_calls[0],'detail':detail})
fresh_out=run.tmp/'out'/'fresh-b.json'
try:
    O.journaled_exact_launch(stale,run.journal,run.tmp,run.tmp/'runtime',run.tmp/'res.json',run.tmp/'dur.json',request,run.tmp/'new-request.json',fresh_out,run.log_path,run.tmp/'res.json','INDEPENDENT_REPLAY_FRESH_OUTPUT')
    raise AssertionError('stale acceptance returned for current request')
except C.StopSignal as refused:
    assert refused.stop_id=='SB_STOP_GLOBAL' and 'later_launches=0' in refused.detail
    detail=refused.detail
assert launcher_calls[0]==1 and run.journal.state()==before_state
rows.append({'case':'NEW_A007F3_1b_replay_at_fresh_output_path','defect_reproduced':False,'refused':True,'launcher_calls':launcher_calls[0],'detail':detail})

# FIX004 regression: the primary timeout is retained next to the secondary
# evidence-write error.
k,root,_=T.world();run=T.Launch(k,root)
with mock.patch.object(C,'_timeout_stop_evidence',side_effect=OSError(28,'SECONDARY_TIMEOUT_RECORD_WRITE')):
    stop=run.run()
rec=stop.cleanup
assert 'SECONDARY_TIMEOUT_RECORD_WRITE' not in rec['original_failure']
assert rec['primary_failure']['type']=='TimeoutExpired' and rec['original_failure']==rec['primary_failure']['label']
assert [s['step'] for s in rec['secondary_failures']]==['TIMEOUT_STOP_EVIDENCE_WRITE']
assert 'SECONDARY_TIMEOUT_RECORD_WRITE' in rec['secondary_failures'][0]['error']
assert rec['custody_close_outcome']=='CLOSED' and 'FAILURE_CLEANUP' not in [e['kind'] for e in run.context.evidence]
assert [e.get('label') for e in run.context.evidence if e['kind']=='DEADLINE_START']==['TIMEOUT']
if OUT is not None:
    OUT.mkdir(parents=True,exist_ok=True)
    Path(OUT/'dev007_fix004_timeout_primary_secondary_evidence.json').write_text(json.dumps(rec,indent=2,default=str)+'\n')
rows.append({'case':'NEW_A007F3_2_primary_timeout_replaced','defect_reproduced':False,'original_failure':rec['original_failure'],'primary_failure_type':rec['primary_failure']['type'],'secondary_failures':rec['secondary_failures'],'phase':rec.get('failure_phase'),'dispatch_refused':not run.journal.state()['ready'],'stop_id':stop.stop_id})

result={'method':'FIX004_REGRESSION_COPY_OF_ASTRA_PROBE_PURE_SIMULATION','native_effects':0,'cases':rows}
if OUT is not None:
    (OUT/'dev007_fix004_astra_regression_results.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
print(json.dumps(result,indent=2,default=str))
