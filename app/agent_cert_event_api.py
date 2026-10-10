"""Owner-only, bounded original event reads; no dispatch, signing or certificate.

The runtime owns its identity and persisted action ledger. These endpoints do
not install telemetry, grant agents ledger access, flush/rewrite audit records,
or claim that returned evidence is independently verified. A protected caller
must still bind the observed image/source and verify the full event joins.
"""
import os
from pathlib import Path
import re
import threading

from fastapi import APIRouter, Header, HTTPException, Response

from .client_auth import authenticate_owner
from .agent_cert_identity_review import (
    IdentityReviewError, canonical, parse, read_action_span, sha, valid_uuid,
)
from .agent_cert_artifact_events import (
    SUPPORTED_CASES as ARTIFACT_CASES, artifact_action_type, read_artifact_action_span,
)
from .agent_cert_authority_events import (
    SUPPORTED_CASES as AUTHORITY_CASES, authority_action_type, read_authority_action_span,
)
from .agent_cert_role_review import AUTHORITY_REVIEW_ACTION, read_authority_review_action_span
from .agent_cert_tool_events import (SUPPORTED_CASES as TOOL_CASES, tool_action_type,
    read_tool_action_span, validate_full_span)
from .agent_cert_role_review import TOOL_REVIEW_ACTION, read_tool_review_action_span

router = APIRouter(prefix='/api/agent-cert-events', tags=['owner-certification-evidence'])
_read_slot = threading.BoundedSemaphore(1)
_ARTIFACT_ACTIONS = {
    artifact_action_type(case): (case, False, False) for case in ARTIFACT_CASES
}
_ARTIFACT_ACTIONS.update({artifact_action_type(case, setup=True): (case, True, False)
    for case in ARTIFACT_CASES if case != 'general:artifact_produce'})
_ARTIFACT_ACTIONS[artifact_action_type('general:recovery', prior=True)] = ('general:recovery', False, True)
_ARTIFACT_ACTIONS[artifact_action_type('evidence_integrity:complete', prior=True)] = ('evidence_integrity:complete', False, True)
_ARTIFACT_ACTIONS[artifact_action_type('context_integrity:complete', prior=True)] = ('context_integrity:complete', False, True)
_AUTHORITY_ACTIONS = {authority_action_type(case): case for case in AUTHORITY_CASES}
_TOOL_ACTIONS = {tool_action_type(case, phase=phase): (case, phase)
    for case in TOOL_CASES for phase in ('setup', 'read', 'result', 'full')}
_ACTIONS = frozenset({
    'runtime.status.artifact', 'agent.certification.identity.review',
    'agent.certification.initialization.artifact',
    'agent.certification.initialization.review',
    AUTHORITY_REVIEW_ACTION, TOOL_REVIEW_ACTION,
} | set(_ARTIFACT_ACTIONS) | set(_AUTHORITY_ACTIONS) | set(_TOOL_ACTIONS))


def _headers(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'


@router.get('/runtime')
def runtime(response: Response, authorization: str | None = Header(None)):
    authenticate_owner(authorization)
    _headers(response)
    from .objective_api import runtime_snapshot
    # This is the existing runtime-domain observation, not independent image
    # admission or hardware/model/agent health evidence.
    return runtime_snapshot()


def _original_chain(lines, task_id, action_type):
    if (type(lines) is not list or not 2 <= len(lines) <= 128 or
            any(type(line) is not str or not line.endswith('\n') or
                not 0 < len(line.encode('utf-8')) <= 65536 for line in lines) or
            sum(len(line.encode('utf-8')) for line in lines) > 1024 * 1024):
        raise ValueError('Original event bounds exceeded')
    previous = None
    owned = []
    for index, line in enumerate(lines):
        if type(line) is not str or not line.endswith('\n'):
            raise ValueError('Original event line unavailable')
        event = parse(line.encode('utf-8'))
        sequence = event.get('sequence')
        digest = event.get('sha256')
        prior = event.get('previous_sha256')
        if (type(sequence) is not int or not 1 <= sequence < 2**63 or
                type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None or
                type(prior) is not str or re.fullmatch('[0-9a-f]{64}', prior) is None or
                sha(canonical({key: value for key, value in event.items()
                               if key != 'sha256'})) != digest):
            raise ValueError('Original event chain unavailable')
        if previous and (sequence != previous['sequence'] + 1 or
                         prior != previous['sha256']):
            raise ValueError('Original event chain unavailable')
        if event.get('task_id') == task_id and event.get('action_type') == action_type:
            owned.append((index, event))
        previous = event
    if (len(owned) != 2 or owned[0][0] != 0 or owned[-1][0] != len(lines) - 1 or
            owned[0][1].get('phase') != 'started' or
            owned[1][1].get('phase') != 'completed' or
            not valid_uuid(owned[0][1].get('action_id')) or
            owned[0][1]['action_id'] != owned[1][1].get('action_id')):
        raise ValueError('Original event pair unavailable')


@router.get('/actions/{task_id}')
def actions(task_id: str, response: Response, action_type: str = '',
            authorization: str | None = Header(None)):
    # Authenticate before interpreting identifiers or opening the ledger.
    authenticate_owner(authorization)
    _headers(response)
    if not valid_uuid(task_id) or action_type not in _ACTIONS:
        raise HTTPException(422, 'A fixed certification event binding is required')
    if not _read_slot.acquire(blocking=False):
        raise HTTPException(429, 'Certification event read is busy')
    try:
        from .objective_api import runtime_snapshot
        before = runtime_snapshot()
        root = Path(os.getenv('PRIME_DATA_DIR', '/data'))
        if action_type in _TOOL_ACTIONS:
            case, phase = _TOOL_ACTIONS[action_type]
            lines = read_tool_action_span(root, task_id, case, phase=phase)
        elif action_type == TOOL_REVIEW_ACTION:
            lines = read_tool_review_action_span(root, task_id)
        elif action_type in _AUTHORITY_ACTIONS:
            lines = read_authority_action_span(root, task_id, _AUTHORITY_ACTIONS[action_type])
        elif action_type == AUTHORITY_REVIEW_ACTION:
            lines = read_authority_review_action_span(root, task_id)
        elif action_type in _ARTIFACT_ACTIONS:
            case, setup, prior = _ARTIFACT_ACTIONS[action_type]
            lines = read_artifact_action_span(root, task_id, case, setup=setup, prior=prior)
        else:
            lines = read_action_span(root / 'action-records.jsonl', task_id, action_type)
        if action_type in _TOOL_ACTIONS and _TOOL_ACTIONS[action_type][1] == 'full':
            validate_full_span(lines, task_id, _TOOL_ACTIONS[action_type][0])
        else:
            _original_chain(lines, task_id, action_type)
        after = runtime_snapshot()
        if canonical(before) != canonical(after) or before.get('source_revision') == 'UNKNOWN':
            raise ValueError('Runtime identity unavailable')
        return {'schema': 'prime.original-action-span.v1', 'task_id': task_id,
                'action_type': action_type, 'source_revision': before['source_revision'],
                'original_lines': lines}
    except (IdentityReviewError, OSError, ValueError, TypeError, UnicodeError,
            RecursionError, OverflowError, KeyError):
        # Do not expose ledger paths, content, model text, or callback errors.
        raise HTTPException(503, 'Original certification event evidence is unavailable') from None
    finally:
        _read_slot.release()
