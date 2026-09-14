"""Small structured facts/results handoffs; no reasoning-history transport."""
import json

FIELDS = {'schema_version', 'task_id', 'facts', 'results', 'evidence_refs',
          'artifact_refs', 'acceptance_criteria'}
EXTENDED_FIELDS = FIELDS | {'objective', 'constraints', 'changed_state', 'open_questions'}


def validate_handoff(value):
    if not isinstance(value, dict):
        raise ValueError('Exact structured handoff fields required')
    version = value.get('schema_version')
    fields = FIELDS if version == '1.0' else EXTENDED_FIELDS if version == '1.1' else set()
    if not fields or set(value) != fields:
        raise ValueError('Exact structured handoff fields required')
    if not isinstance(value['task_id'], str) or not 1 <= len(value['task_id']) <= 128:
        raise ValueError('Invalid handoff version/task')
    if version == '1.1' and (not isinstance(value['objective'], str) or not 1 <= len(value['objective']) <= 2048):
        raise ValueError('Bounded handoff objective required')
    for field in fields - {'schema_version', 'task_id', 'objective'}:
        items = value[field]
        if not isinstance(items, list) or len(items) > 32 or any(not isinstance(x, str) or len(x) > 1024 for x in items):
            raise ValueError('Handoff list exceeds structured bounds')
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 16384:
        raise ValueError('Handoff exceeds byte budget')
    return json.loads(encoded)
