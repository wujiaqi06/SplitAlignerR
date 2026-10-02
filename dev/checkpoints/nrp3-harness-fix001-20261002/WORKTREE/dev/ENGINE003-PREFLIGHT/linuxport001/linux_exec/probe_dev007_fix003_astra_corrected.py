"""Astra's three FIX002 defect probes (A007F2-1/2/3), corrected to the FIX003
journal API (independent progression store).  Same mutations, pure memory
storage, audit hook denies native effects.  Each record asserts REFUSAL."""
import json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)


def deny(event, args):
    if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.kill', 'os.killpg',
                 'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect'}:
        raise AssertionError('FORBIDDEN_NATIVE_EFFECT:' + event)
    if event == 'open' and isinstance(args[0], (str, bytes)) and \
            os.fsdecode(args[0]).startswith('/proc'):
        raise AssertionError('FORBIDDEN_PROC_READ')


sys.addaudithook(deny)
import run_dev006_pure as runner  # noqa: E402
runner.block_host_effects()
import test_dev007_fix001 as V  # noqa: E402
import test_dev006 as T  # noqa: E402
J = T.C.journal_protocol
rows = []


def fresh():
    j = J.DispatchJournal(J.MemoryStorage(), run_generation=1, input_identity='I',
                          dispatcher_owner='O', progression=J.MemoryStorage())
    j.initialize_scope()
    return j


def restart(j):
    return J.DispatchJournal(J.MemoryStorage(records=j.storage.records), **j.scope,
                             progression=J.MemoryStorage(records=j.progression.records))


j = fresh()
seq = j.begin('ORIGINAL', '0' * 64, 'raw', 'out')
del j.storage.records['000001.IN_FLIGHT']
r = restart(j)
state = r.state()
assert not state['ready'], state
try:
    r.begin('NEW-RUN', '1' * 64, 'newraw', 'newout')
    raise AssertionError('begin reused scope')
except J.JournalRefused as e:
    refused = e.code
rows.append({'case': 'A007F2_1_tail_record_loss', 'refused': True,
             'state_reason': state['reason'], 'begin_refusal': refused})

j = fresh()
j.begin('ORIGINAL', '0' * 64, 'raw', 'out')
try:
    j.reconcile(1, 'ORIGINAL', {'cited_run_id': 'ORIGINAL', 'resolved_facts': [
        {'kind': 'STILL_LIVE', 'resolved': False}]})
    raise AssertionError('unresolved reconciliation accepted')
except J.JournalRefused as e:
    code = e.code
state = j.state()
assert not state['ready']
rows.append({'case': 'A007F2_2_explicit_unresolved_reconciliation', 'refused': True,
             'reconcile_refusal': code, 'state_reason': state['reason']})

run, stop, calls = V.launch()
assert stop is None
J.verify_controller_acceptance(run.output_path, run.journal)
cleanup_present = '000001.CLEANUP' in run.journal.storage.records
del run.journal.storage.records['ANCHOR']
del run.journal.storage.records['000001.IN_FLIGHT']
state = run.journal.state()
try:
    J.verify_controller_acceptance(run.output_path, run.journal)
    raise AssertionError('acceptance verified without anchor/flight')
except J.JournalRefused as e:
    code = e.code
rows.append({'case': 'A007F2_3_acceptance_missing_scope_flight', 'refused': True,
             'cleanup_record_persisted_before_mutation': cleanup_present,
             'journal_state_reason': state['reason'], 'consumer_refusal': code})
out = {'method': 'CORRECTED_COPY_OF_ASTRA_FIX002_PROBES_PURE', 'native_effects': 0,
       'cases': rows}
print(json.dumps(out, indent=2))
