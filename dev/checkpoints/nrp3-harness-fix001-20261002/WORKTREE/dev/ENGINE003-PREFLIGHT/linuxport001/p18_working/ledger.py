"""P07 bounded incremental close-outcome model. No imports or host operations."""
MAX_RESOURCES = 8
MAX_EVENTS = 64
LABEL_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-'
TOKEN_FIELDS = frozenset(('run_id','owner_id','resource_id','generation',
                          'acquisition_id','source_id','source_sha256'))
STATES = ('PENDING_OWNERSHIP','ATTEMPTED_WITHOUT_COMPLETION',
          'CONFIRMED_CLOSE','UNRESOLVED_ERROR')

class LedgerError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def require(ok, code):
    if not ok:
        raise LedgerError(code)

def fields(value, expected, code):
    require(type(value) is dict and set(value) == set(expected), code)

def label(value, field):
    require(type(value) is str, field + '_TYPE')
    require(1 <= len(value) <= 64 and all(c in LABEL_CHARS for c in value), field + '_FORMAT')

def integer(value, low, high, field):
    require(type(value) is int, field + '_TYPE')
    require(low <= value <= high, field + '_RANGE')

def digest(value):
    require(type(value) is str and len(value) == 64
            and all(c in '0123456789abcdef' for c in value), 'SOURCE_DIGEST')

def freeze(value):
    """Validated event dictionaries contain only nested dicts and scalar data."""
    return tuple((k, freeze(v) if type(v) is dict else v) for k,v in sorted(value.items()))

def thaw(value):
    return {k:(thaw(v) if type(v) is tuple else v) for k,v in value}

def token_types(token):
    fields(token, TOKEN_FIELDS, 'TOKEN_SCHEMA')
    for key in ('run_id','owner_id','resource_id','acquisition_id','source_id'):
        label(token[key], key.upper())
    integer(token['generation'], 1, 2147483647, 'GENERATION')
    digest(token['source_sha256'])

def outcome_types(outcome):
    fields(outcome, ('result','return_value','errno','diagnostic'), 'OUTCOME_SCHEMA')
    require(type(outcome['result']) is str and outcome['result'] in ('SUCCESS','ERROR'), 'OUTCOME_RESULT')
    integer(outcome['return_value'], -1, 0, 'RETURN_VALUE')
    require(type(outcome['diagnostic']) is str and len(outcome['diagnostic']) <= 256
            and all(32 <= ord(c) <= 126 for c in outcome['diagnostic']), 'DIAGNOSTIC')
    if outcome['result'] == 'SUCCESS':
        require(outcome['return_value'] == 0 and outcome['errno'] is None, 'SUCCESS_OUTCOME')
    else:
        integer(outcome['errno'], 1, 4095, 'ERRNO')
        require(outcome['return_value'] == -1, 'ERROR_OUTCOME')

def event_types(event):
    require(type(event) is dict, 'EVENT_TYPE')
    require(type(event.get('kind')) is str and event['kind'] in ('REGISTER','BEGIN','COMPLETE'), 'EVENT_KIND')
    kind = event['kind']
    extra = ('fd',) if kind == 'REGISTER' else (('attempt_id',) if kind == 'BEGIN' else ('attempt_id','outcome'))
    fields(event, ('event_id','kind','token') + extra, 'EVENT_SCHEMA')
    label(event['event_id'], 'EVENT_ID')
    token_types(event['token'])
    if kind == 'REGISTER':
        integer(event['fd'], 0, 2147483647, 'FD')
    else:
        label(event['attempt_id'], 'ATTEMPT_ID')
    if kind == 'COMPLETE':
        outcome_types(event['outcome'])
    # Every required identifier/type is validated before any catalog/index lookup.

class Ledger:
    """Bounded lifetime submissions, followed by arbitrary detached report reads."""
    def __init__(self, config):
        require(not hasattr(self, '_submission_slots'), 'ALREADY_INITIALIZED')
        fields(config, ('run_id','owner_id','sources'), 'CONFIG_SCHEMA')
        label(config['run_id'], 'RUN_ID')
        label(config['owner_id'], 'OWNER_ID')
        sources = config['sources']
        require(type(sources) is list and 1 <= len(sources) <= MAX_RESOURCES, 'SOURCE_CATALOG_BOUND')
        for source in sources:
            fields(source, ('source_id','sha256'), 'SOURCE_SCHEMA')
            label(source['source_id'], 'SOURCE_ID')
            digest(source['sha256'])
        require(len({x['source_id'] for x in sources}) == len(sources), 'DUPLICATE_SOURCE_ID')
        self._run, self._owner = config['run_id'], config['owner_id']
        self._sources = tuple((x['source_id'],x['sha256']) for x in sources)
        self._records, self._attempts = {}, {}
        self._event_ids, self._history = frozenset(), ()
        self._submission_slots = 0

    def _apply(self, event):
        event_types(event)
        token = event['token']
        require(token['run_id'] == self._run and token['owner_id'] == self._owner, 'OWNERSHIP_CONTEXT')
        require((token['source_id'],token['source_sha256']) in self._sources, 'SOURCE_REFERENCE')
        key = freeze(token)
        eid, kind = event['event_id'], event['kind']
        require(eid not in self._event_ids, 'DUPLICATE_EVENT_ID')
        require(len(self._history) < MAX_EVENTS, 'EVENT_HISTORY_LIMIT')
        records, attempts = dict(self._records), dict(self._attempts)
        action = None
        if kind == 'REGISTER':
            require(key not in records, 'DUPLICATE_TOKEN')
            base = (token['resource_id'],token['generation'])
            require(not any((thaw(k)['resource_id'],thaw(k)['generation']) == base for k in records),
                    'DUPLICATE_RESOURCE_GENERATION')
            require(not any(thaw(k)['acquisition_id'] == token['acquisition_id'] for k in records),
                    'DUPLICATE_ACQUISITION_ID')
            require(len(records) < MAX_RESOURCES, 'RESOURCE_LIMIT')
            require(not any(r['fd'] == event['fd'] and r['state'] in STATES[:2] for r in records.values()),
                    'ACTIVE_FD_COLLISION')
            records[key] = dict(fd=event['fd'],state='PENDING_OWNERSHIP',
                                attempt_id=None,outcome=None,registration_event_id=eid)
        else:
            require(key in records, 'UNKNOWN_TOKEN')
            old = records[key]
            aid = event['attempt_id']
            if kind == 'BEGIN':
                require(aid not in attempts, 'DUPLICATE_ATTEMPT_ID')
                require(old['state'] == 'PENDING_OWNERSHIP', 'ALREADY_ATTEMPTED')
                attempts[aid] = key
                records[key] = dict(old,state='ATTEMPTED_WITHOUT_COMPLETION',attempt_id=aid)
                action = dict(kind='SIMULATED_CLOSE_ONCE',token=thaw(key),
                              attempt_id=aid,fd=old['fd'],source_event_id=eid)
            else:
                require(aid in attempts, 'UNKNOWN_ATTEMPT')
                require(attempts[aid] == key and old['attempt_id'] == aid, 'ATTEMPT_TOKEN_MISMATCH')
                require(old['state'] == 'ATTEMPTED_WITHOUT_COMPLETION', 'DUPLICATE_COMPLETION')
                state = 'CONFIRMED_CLOSE' if event['outcome']['result'] == 'SUCCESS' else 'UNRESOLVED_ERROR'
                records[key] = dict(old,state=state,outcome=freeze(event['outcome']))
        # Build all replacement values before committing; typed rejections mutate nothing.
        history = self._history + (freeze(event),)
        event_ids = self._event_ids | frozenset((eid,))
        self._records, self._attempts = records, attempts
        self._history, self._event_ids = history, event_ids
        return dict(accepted=True,reason=None,action=action)

    def submit(self, event):
        """One lifetime submission slot, including a typed/lifecycle rejection."""
        if self._submission_slots >= MAX_EVENTS:
            return dict(accepted=False,reason='SUBMISSION_LIMIT',action=None,
                        submission_slot=None,admission=self.admission_report())
        self._submission_slots += 1
        try:
            result = self._apply(event)
        except LedgerError as exc:
            result = dict(accepted=False,reason=exc.code,action=None)
        return dict(result,submission_slot=self._submission_slots,admission=self.admission_report())

    def admission_report(self):
        """Instrumentation is separate from immutable accepted lifecycle state."""
        return dict(submission_slots=self._submission_slots,submission_limit=MAX_EVENTS,
                    remaining_submission_slots=MAX_EVENTS-self._submission_slots)

    def report(self):
        records = []
        for token,row in self._records.items():
            records.append(dict(token=thaw(token),fd=row['fd'],state=row['state'],
                 registration_event_id=row['registration_event_id'],attempt_id=row['attempt_id'],
                 raw_outcome=thaw(row['outcome']) if row['outcome'] is not None else None,
                 descriptor_state='NOT_INFERRED'))
        counts = {state:sum(r['state'] == state for r in records) for state in STATES}
        total = len(records)
        return dict(scope='P07_SUPPLIED_INCREMENTAL_MODEL_ONLY',registered_total=total,counts=counts,
             obligations=records,history=[thaw(x) for x in self._history],
             accepted_event_count=len(self._history),
             eligible_first_attempt_tokens=[thaw(k) for k,r in self._records.items() if r['state']=='PENDING_OWNERSHIP'],
             automatic_retry_actions=[],
             all_close_outcomes_confirmed=bool(total) and counts['CONFIRMED_CLOSE']==total,
             unresolved_obligation_count=total-counts['CONFIRMED_CLOSE'],
             kernel_state_observed=False)
