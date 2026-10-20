"""Project stored execution errors without exposing provider exception text.

Historical private rows/artifact bytes stay intact. Only defined task error
fields are projected; successful model result content is left untouched.
"""
from copy import deepcopy
import json
import re
from .tier_router import SECRET


# Only fixed, non-sensitive classifications are suitable for owner-facing records.
_SAFE_DISPATCH_REASONS = frozenset({
    'AUTHENTICATION', 'CAPACITY', 'CREDENTIAL_UNAVAILABLE',
    'DATA_LOCALITY', 'MODEL_PROVIDER_UNPINNED', 'PROVIDER_UNAVAILABLE',
    'PROVIDER_TIMEOUT', 'RATE_LIMIT', 'TASK_TIMEOUT',
    'NO_AUTHORIZED_ROUTE', 'PROVIDER_CIRCUIT_OPEN',
    'EMPTY_OR_INCOMPLETE_RESPONSE', 'STEP_DISPATCH_FAILED',
})


def _public_failure_code(value, fallback):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}', value):
        return fallback
    return value if value in _SAFE_DISPATCH_REASONS else fallback


def public_task(task):
    value=deepcopy(task)
    for step in value.get('steps',[]):
        if not isinstance(step,dict):continue
        if step.get('reason'):step['reason']=_public_failure_code(step['reason'], 'STEP_DISPATCH_FAILED')
        for candidate in (step.get('job'),step.get('dispatch',{}).get('job') if isinstance(step.get('dispatch'),dict) else None):
            if isinstance(candidate,dict) and candidate.get('error'):candidate['error']=_public_failure_code(candidate['error'], 'EXECUTION_FAILED')
    return value


def publishable_task_artifact(metadata,raw):
    if metadata.get('provenance')=='Source-labelled governed model result':
        try:text=raw.decode('utf-8')
        except UnicodeError:return False
        return metadata.get('type')=='markdown' and bool(text.strip()) and not SECRET.search(text)
    if metadata.get('provenance')!='Source-labelled governed objective results':return True
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):return False
    if not isinstance(value,dict) or not isinstance(value.get('steps'),list):return False
    return public_task(value)==value
