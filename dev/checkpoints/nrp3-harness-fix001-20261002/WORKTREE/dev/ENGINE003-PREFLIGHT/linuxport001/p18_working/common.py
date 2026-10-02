"""Bounded data snapshots and raw Python observation; no native resource operations."""
from ledger import require

def immutable(value):
    if type(value) is dict:
        return ('D', tuple((k, immutable(v)) for k, v in sorted(value.items())))
    if type(value) is list:
        return ('L', tuple(immutable(v) for v in value))
    require(type(value) in (str, int, bool, type(None)), 'EVIDENCE_DATA_TYPE')
    return ('V', value)

def materialize(value):
    tag, data = value
    if tag == 'D':
        return {k: materialize(v) for k, v in data}
    if tag == 'L':
        return [materialize(v) for v in data]
    return data

def detached(value):
    return materialize(immutable(value))

def raw_return(value):
    return dict(kind='RETURN', python_type=type(value).__name__,
                representation=repr(value), returned_normally=True)

def raw_exception(exc):
    eno = getattr(exc, 'errno', None)
    return dict(kind='EXCEPTION', python_type=type(exc).__name__,
                diagnostic=str(exc), errno=eno if type(eno) in (int,bool,str,type(None)) else None,
                errno_type=type(eno).__name__, errno_representation=repr(eno),
                code=getattr(exc, 'code', None), operation=getattr(exc, 'operation', None),
                original_context=repr(exc), returned_normally=False)
