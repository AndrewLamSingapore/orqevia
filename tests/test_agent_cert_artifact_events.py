"""Temporary original-domain exercises only; not authenticated runtime/L7 proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
import uuid

import pytest

from app import agent_cert_artifact_events as events
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span, IdentityReviewError


SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
RUNTIME = {'host_id': 'test-domain', 'version': 'test-only-v1',
    'source_revision': SOURCE, 'image_digest': IMAGE}


@pytest.fixture
def domain(tmp_path, monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'compute-queue.db'))
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', SOURCE)
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST', IMAGE)
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID', RUNTIME['host_id'])
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_VERSION', RUNTIME['version'])
    from app import agent_registry, objective_api
    # Authentication is outside this unwired substrate. Never call submit,
    # dispatch, queue/model, a service or an external endpoint in these tests.
    monkeypatch.setattr(objective_api, 'authenticate_owner', lambda _: None)
    ledger = ActionLedger(tmp_path / 'action-records.jsonl')
    pin = hashlib.sha256(agent_registry.REGISTRY_PATH.read_bytes()).hexdigest()
    def prepare(case_id):
        spec = events.canonical_artifact_case(case_id)
        task = str(uuid.uuid4())
        db = objective_api.connect()
        try:
            # Schema/bootstrap is fixture setup, not the owning objective's
            # observation. Start before its first write; still include runtime
            # binding, actual execution and all original-domain readbacks.
            created = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
                (task, events.sha(spec['request']['objective'].encode()), 'dispatching', json.dumps([events.CAPABILITY_ID])))
            db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)', (task, 0, created, created))
            objective_api.store_runtime(db, task, 0)
            db.commit()
        finally:
            db.close()
        args = dict(submitted_request=deepcopy(spec['request']), data_root=tmp_path,
            ledger=ledger, runtime=deepcopy(RUNTIME), source_revision=SOURCE,
            read_runtime=objective_api.runtime_snapshot, runtime_image_id=IMAGE, registry_sha256=pin)
        return spec, task, args, created
    yield tmp_path, ledger, prepare, objective_api
    assert ledger.close()


def action_failure_metrics(lines, **binding):
    """Discriminating failure-only flags/timing; never original content or IDs."""
    first, last = [json.loads(line) for line in (lines[0], lines[-1])]
    metadata = binding['metadata']
    stamps = [binding['began'], events._utc(first['timestamp']),
        events._utc(metadata['timestamp']), events._utc(last['timestamp']), binding['ended']]
    deltas = [(right - left).total_seconds() * 1_000_000
        for left, right in zip(stamps, stamps[1:])]
    duration = last['duration_ms']
    numeric_duration = type(duration) in (int, float) and math.isfinite(duration)
    return {'original_line_count': len(lines), 'order_deltas_us': deltas,
        'timestamp_ordered': all(value >= 0 for value in deltas),
        'action_duration_ms': duration if numeric_duration else None,
        'action_duration_type': type(duration).__name__,
        'duration_within_bound': numeric_duration
            and 0 <= duration <= binding.get('duration_limit_ms', 5000),
        'started_phase': first.get('phase') == 'started',
        'completed_phase': last.get('phase') == 'completed',
        'success_is_true': last.get('success') is True,
        'actor_fields_match': all(item.get('agent_id') == binding['agent_id']
            and item.get('task_id') == binding['task_id']
            and item.get('action_type') == binding['action_type'] for item in (first, last)),
        'result_summary_matches_artifact': last.get('result_summary') == {
            'type': 'dict', 'artifact_id': metadata['artifact_id'],
            'sha256': metadata['sha256'], 'location': 'artifact.json'}}


def observed_action_span(lines, **binding):
    try:
        return action_span(lines, **binding)
    except IdentityReviewError as error:
        try:
            note = json.dumps(action_failure_metrics(lines, **binding), sort_keys=True, allow_nan=False)
        except Exception:
            note = 'ACTION_DIAGNOSTIC_UNAVAILABLE'
        error.add_note(note)
        raise


def execute_and_collect(domain, case_id):
    root, ledger, prepare, objective_api = domain
    spec, task, args, created = prepare(case_id)
    runtime_before = objective_api.runtime_snapshot()
    dispatch = events.execute_artifact_case(spec, task, **args)
    runtime_after = objective_api.runtime_snapshot()
    steps = [{'capability': events.CAPABILITY_ID, 'dispatch': dispatch}]
    db = objective_api.connect()
    try:
        db.execute('UPDATE objectives SET state=?,steps_json=? WHERE id=?', ('submitted', json.dumps(steps), task))
        db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=0',
            (datetime.now(timezone.utc).isoformat(), task))
        db.commit()
    finally:
        db.close()
    original_read = objective_api._get(task, None, read_only=True)
    factory = ArtifactFactory(root / 'artifacts')
    metadata, raw = factory.retrieve(dispatch['artifact']['artifact_id'])
    receipt = dispatch['artifact_event']
    lines = events.read_artifact_action_span(root, task, case_id)
    chain = observed_action_span(lines, task_id=task, agent_id=events.AGENT_ID,
        action_type=events.artifact_action_type(case_id), schema=events.RESULT_SCHEMA,
        metadata=metadata, began=events._utc(receipt['started_at']), ended=events._utc(receipt['completed_at']),
        action_id=receipt['subject_action_id'])
    input_raw, input_lines, input_chain = None, [], None
    if receipt['input_artifact_metadata'] is not None:
        input_metadata, input_raw = factory.retrieve(receipt['input_artifact_metadata']['artifact_id'])
        input_lines = events.read_artifact_action_span(root, task, case_id, setup=True)
        input_chain = observed_action_span(input_lines, task_id=task, agent_id=events.AGENT_ID,
            action_type=events.artifact_action_type(case_id, setup=True), schema=events.INPUT_SCHEMA,
            metadata=input_metadata, began=events._utc(receipt['started_at']), ended=events._utc(receipt['completed_at']),
            action_id=receipt['input_action_id'])
    ended = datetime.now(timezone.utc)
    execution = {'case_spec': spec, 'runtime': runtime_before, 'runtime_after': runtime_after,
        'runtime_current': objective_api.runtime_snapshot(), 'submission': [202, {'id': task, 'steps': steps}],
        'dispatch': dispatch, 'artifact_metadata': metadata, 'artifact_content_utf8': raw.decode(),
        'input_content_utf8': input_raw.decode() if input_raw else None, 'objective_read': [200, original_read],
        'action_records': lines, 'action_chain_join': chain, 'input_action_records': input_lines,
        'input_action_chain_join': input_chain, 'observation': {'started_at': created, 'completed_at': ended.isoformat()}}
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=args['registry_sha256'], now=ended)
    return execution, pins


def observation_failure_metrics(execution, now):
    """Failure-only timing diagnostics, without artifact/context/credential data."""
    observation = execution['observation']
    event = execution['dispatch']['artifact_event']
    first, last = events._utc(observation['started_at']), events._utc(observation['completed_at'])
    began, ended = events._utc(event['started_at']), events._utc(event['completed_at'])
    return {'observation_seconds': (last - first).total_seconds(),
        'execution_seconds': (ended - began).total_seconds(),
        'setup_seconds': (began - first).total_seconds(),
        'readback_seconds': (last - ended).total_seconds(),
        'age_seconds': (now - last).total_seconds(),
        'ordered': first <= began <= ended <= last <= now,
        'within_five_seconds': 0 <= (last - first).total_seconds() <= 5}


def test_fixture_bootstrap_precedes_objective_observation_without_retiming_event(domain, monkeypatch):
    root, _, _, objective_api = domain
    original_connect = objective_api.connect
    connected_at = []
    def observed_connect(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        connected_at.append(datetime.now(timezone.utc))
        return db
    monkeypatch.setattr(objective_api, 'connect', observed_connect)
    execution, pins = execute_and_collect(domain, events.SUPPORTED_CASES[0])
    start = events._utc(execution['observation']['started_at'])
    with sqlite3.connect(root / 'objectives.db') as db:
        original_created = db.execute('SELECT created_at FROM objective_metadata WHERE task=? AND revision=0',
            (execution['dispatch']['task_id'],)).fetchone()[0]
    assert connected_at[0] <= start
    assert original_created == execution['observation']['started_at']
    assert start <= events._utc(execution['dispatch']['artifact_event']['started_at'])
    assert events.validate_artifact_execution(execution, **pins)['certification'] == 'UNVERIFIED'


def test_long_observation_still_rejected_and_failure_metrics_do_not_retime_evidence(domain):
    execution, pins = execute_and_collect(domain, events.SUPPORTED_CASES[0])
    execution['observation']['started_at'] = (events._utc(execution['observation']['completed_at'])
        - timedelta(seconds=6)).isoformat()
    original = deepcopy(execution)
    metrics = observation_failure_metrics(execution, pins['now'])
    assert metrics['observation_seconds'] == 6 and metrics['within_five_seconds'] is False
    assert execution == original
    with pytest.raises(events.ArtifactEventError, match='ARTIFACT_OBSERVATION_UNBOUND'):
        events.validate_artifact_execution(execution, **pins)


def test_action_span_rejection_preserves_original_exception_and_records(domain, monkeypatch):
    original = IdentityReviewError('ACTION_BINDING_INVALID')
    def rejected(*args, **kwargs):
        raise original
    monkeypatch.setitem(globals(), 'action_span', rejected)
    with pytest.raises(IdentityReviewError, match='ACTION_BINDING_INVALID') as caught:
        execute_and_collect(domain, events.SUPPORTED_CASES[1])
    assert caught.value is original
    note = json.loads(original.__notes__[0])
    root, ledger, _, _ = domain
    before = ledger.path.read_bytes()
    records = [json.loads(line) for line in before.decode().splitlines()]
    assert note['timestamp_ordered'] and note['result_summary_matches_artifact']
    assert note['original_line_count'] == 2 and note['duration_within_bound']
    assert all(record['task_id'] not in original.__notes__[0]
        and record['action_id'] not in original.__notes__[0] for record in records)
    assert ledger.path.read_bytes() == before


def test_action_clock_rollback_retains_rejection_and_discriminating_timing(domain, monkeypatch):
    from app import action_records
    original = action_records.datetime
    ticks = []
    def now(zone):
        stamp = original.now(zone) if not ticks else ticks[0] - timedelta(milliseconds=1)
        ticks.append(stamp)
        return stamp
    monkeypatch.setattr(action_records, 'datetime', SimpleNamespace(now=now))
    with pytest.raises(IdentityReviewError, match='ACTION_BINDING_INVALID') as caught:
        execute_and_collect(domain, events.SUPPORTED_CASES[1])
    note = json.loads(caught.value.__notes__[0])
    assert not note['timestamp_ordered'] and note['order_deltas_us'][2] < 0
    assert note['success_is_true'] and note['actor_fields_match'] and note['result_summary_matches_artifact']
    assert note['duration_within_bound']
    _, ledger, _, _ = domain
    records = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    assert len(records) == 2 and events._utc(records[1]['timestamp']) < events._utc(records[0]['timestamp'])


def test_action_diagnostic_failure_does_not_mask_original_rejection(domain, monkeypatch):
    original = IdentityReviewError('ACTION_BINDING_INVALID')
    def rejected(*args, **kwargs):
        raise original
    def unavailable(*args, **kwargs):
        raise ValueError('private malformed diagnostic input')
    monkeypatch.setitem(globals(), 'action_span', rejected)
    monkeypatch.setitem(globals(), 'action_failure_metrics', unavailable)
    with pytest.raises(IdentityReviewError, match='ACTION_BINDING_INVALID') as caught:
        execute_and_collect(domain, events.SUPPORTED_CASES[1])
    assert caught.value is original
    assert original.__notes__ == ['ACTION_DIAGNOSTIC_UNAVAILABLE']


def test_action_diagnostics_never_reflect_invalid_duration_content(domain):
    execution, _ = execute_and_collect(domain, events.SUPPORTED_CASES[1])
    lines = list(execution['action_records'])
    last = json.loads(lines[-1])
    last['duration_ms'] = 'private invalid duration content'
    last['sha256'] = events.sha(events.canonical({key: value for key, value in last.items() if key != 'sha256'}))
    lines[-1] = json.dumps(last, sort_keys=True) + '\n'
    receipt = execution['dispatch']['artifact_event']
    with pytest.raises(IdentityReviewError, match='ACTION_BINDING_INVALID') as caught:
        observed_action_span(lines, task_id=receipt['task_id'], agent_id=events.AGENT_ID,
            action_type=events.artifact_action_type(events.SUPPORTED_CASES[1]), schema=events.RESULT_SCHEMA,
            metadata=execution['artifact_metadata'], began=events._utc(receipt['started_at']),
            ended=events._utc(receipt['completed_at']), action_id=receipt['subject_action_id'])
    note = json.loads(caught.value.__notes__[0])
    assert note['action_duration_ms'] is None and note['action_duration_type'] == 'str'
    assert not note['duration_within_bound']
    assert 'private invalid duration content' not in caught.value.__notes__[0]


def test_import_executes_no_domain_or_file_io(monkeypatch):
    source = Path(events.__file__).read_text(encoding='utf-8')
    code = compile(source, '<source-only-no-io-check>', 'exec')
    def forbidden(*a, **k):
        pytest.fail('import performed I/O')
    monkeypatch.setattr('builtins.open', forbidden)
    for name in ('open', 'read_bytes', 'read_text', 'mkdir'):
        monkeypatch.setattr(Path, name, forbidden)
    namespace = {'__name__': 'source_only_check', '__package__': 'app'}
    exec(code, namespace)
    assert namespace['SUPPORTED_CASES'] == events.SUPPORTED_CASES


def test_source_cases_have_distinct_exact_bytes_hashes_and_no_answer_in_request():
    specs = [events.canonical_artifact_case(case) for case in events.SUPPORTED_CASES]
    outputs = [events.expected_artifact_bytes(case) for case in events.SUPPORTED_CASES]
    assert len({spec['case_input_sha256'] for spec in specs}) == 3
    assert len({events.sha(raw) for raw in outputs}) == 3
    assert [json.loads(raw)['assessment'].get('failure_basis_points') for raw in outputs] == [500, None, None]
    assert json.loads(outputs[2])['assessment']['observed_success_basis_points'] == 9500
    assert all(spec['certification'] == 'UNVERIFIED' and spec['request']['max_cost_usd'] == 0 for spec in specs)
    assert all('assessment' not in json.loads(spec['request']['context']) for spec in specs)
    specs[0]['request']['context'] = 'mutated'
    assert events.canonical_artifact_case(events.SUPPORTED_CASES[0])['request']['context'] != 'mutated'


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_actual_factory_durable_executor_and_original_objective_readback_join(domain, case_id):
    execution, pins = execute_and_collect(domain, case_id)
    result = events.validate_artifact_execution(execution, **pins)
    assert result['certification'] == 'UNVERIFIED'
    assert result['result_sha256'] == events.sha(events.expected_artifact_bytes(case_id))
    assert 'ORIGIN_AND_INDEPENDENT_ACCEPTANCE_REQUIRED' in result['event_verification']
    assert (result['input_action_sha256'] is None) == (case_id == events.SUPPORTED_CASES[1])
    root, ledger, _, _ = domain
    assert ledger.status()['persisted'] == (2 if case_id == events.SUPPORTED_CASES[1] else 4)
    assert not list(root.glob('*.sign*'))


@pytest.mark.parametrize('defect', ['actor', 'capability', 'objective', 'context', 'extra_request',
    'classification', 'runtime', 'current_runtime', 'registry', 'task', 'objective_owner', 'objective_hash', 'objective_state',
    'objective_runtime', 'objective_revision', 'old_objective', 'ledger_path'])
def test_wrong_owning_task_or_submitted_spec_rejected_before_artifact_and_action_side_effects(domain, defect):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[0])
    if defect == 'actor':
        spec['agent_id'] = 'a26'
    elif defect == 'capability':
        args['submitted_request']['capability'] = 'responsibility.a26'
    elif defect in {'objective', 'context', 'classification'}:
        args['submitted_request'][defect] = 'unauthorized drift'
    elif defect == 'extra_request':
        args['submitted_request']['extra'] = True
    elif defect == 'runtime':
        args['runtime']['image_digest'] = 'sha256:' + 'c' * 64
    elif defect == 'current_runtime':
        args['read_runtime'] = lambda: {**RUNTIME, 'source_revision': 'c' * 40}
    elif defect == 'registry':
        args['registry_sha256'] = 'f' * 64
    elif defect == 'task':
        task = str(uuid.uuid4())
    elif defect == 'ledger_path':
        ledger.path = root / 'wrong-ledger.jsonl'
    else:
        with sqlite3.connect(root / 'objectives.db') as db:
            if defect == 'objective_owner':
                db.execute('UPDATE objectives SET steps_json=? WHERE id=?', (json.dumps(['responsibility.a26']), task))
            elif defect == 'objective_hash':
                db.execute('UPDATE objectives SET objective_hash=? WHERE id=?', ('e' * 64, task))
            elif defect == 'objective_state':
                db.execute('UPDATE objectives SET state=? WHERE id=?', ('submitted', task))
            elif defect == 'objective_runtime':
                db.execute('UPDATE objective_runtime SET image_digest=? WHERE task=?', ('sha256:' + 'd' * 64, task))
            elif defect == 'objective_revision':
                db.execute('UPDATE objective_metadata SET revision=1 WHERE task=?', (task,))
            elif defect == 'old_objective':
                old = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
                db.execute('UPDATE objective_metadata SET created_at=?,updated_at=? WHERE task=?', (old, old, task))
    with pytest.raises(events.ArtifactEventError):
        events.execute_artifact_case(spec, task, **args)
    assert not (root / 'artifacts').exists()
    assert ledger.status()['persisted'] == 0 and ledger.status()['pending'] == 0


def test_repeated_same_objective_rejected_without_replay(domain):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    events.execute_artifact_case(spec, task, **args)
    before = (root / 'action-records.jsonl').read_bytes()
    with pytest.raises(events.ArtifactEventError, match='ALREADY_ATTEMPTED'):
        events.execute_artifact_case(spec, task, **args)
    assert (root / 'action-records.jsonl').read_bytes() == before
    assert len(list((root / 'artifacts').iterdir())) == 1


@pytest.mark.parametrize('defect', ['text_only', 'wrong_case', 'result_whitespace', 'input_drift',
    'missing_input', 'input_other_task', 'creator', 'image', 'tokens', 'model_calls_bool',
    'revision_bool', 'different_dispatch', 'action_tamper', 'action_id', 'not_durable', 'runtime_after', 'runtime_current',
    'stale', 'input_not_before_subject', 'timestamp_type', 'output_hash', 'approval_claim', 'action_newline', 'input_action_newline'])
def test_invalid_custody_origin_joins_and_laundered_execution_claims_fail_closed(domain, defect):
    execution, pins = execute_and_collect(domain, events.SUPPORTED_CASES[0])
    if defect == 'text_only':
        execution = {'text': execution['artifact_content_utf8'], 'status': 'PASS'}
    elif defect == 'wrong_case':
        execution['case_spec']['case'] = events.SUPPORTED_CASES[1]
    elif defect == 'result_whitespace':
        execution['artifact_content_utf8'] += '\n'
    elif defect == 'input_drift':
        execution['input_content_utf8'] = execution['input_content_utf8'].replace('"failures":1', '"failures":0')
    elif defect == 'missing_input':
        execution['input_action_records'] = []
    elif defect == 'input_other_task':
        execution['dispatch']['artifact_event']['input_artifact_metadata']['task_id'] = str(uuid.uuid4())
    elif defect == 'creator':
        execution['artifact_metadata']['creator_agents'] = ['a26']
    elif defect == 'image':
        execution['objective_read'][1]['execution_metadata']['runtime']['image_digest'] = 'sha256:' + 'c' * 64
    elif defect == 'tokens':
        execution['objective_read'][1]['execution_metadata']['inference_attempts']['attempts'] = [{'input_tokens': 1}]
    elif defect == 'model_calls_bool':
        execution['dispatch']['model_calls'] = False
    elif defect == 'revision_bool':
        execution['objective_read'][1]['revision'] = False
    elif defect == 'different_dispatch':
        execution['objective_read'][1]['steps'][0]['dispatch'] = {'state': 'COMPLETED'}
    elif defect == 'action_tamper':
        execution['action_records'][0] = execution['action_records'][0].replace('"agent_id": "a19"', '"agent_id": "a26"')
    elif defect == 'action_id':
        execution['dispatch']['artifact_event']['subject_action_id'] = str(uuid.uuid4())
    elif defect == 'not_durable':
        execution['dispatch']['artifact_event']['durable_action_delivery'] = False
    elif defect in {'runtime_after', 'runtime_current'}:
        execution[defect]['source_revision'] = 'c' * 40
    elif defect == 'stale':
        pins['now'] += timedelta(minutes=6)
    elif defect == 'input_not_before_subject':
        execution['input_action_chain_join']['last_sequence'] = execution['action_chain_join']['first_sequence']
    elif defect == 'timestamp_type':
        execution['dispatch']['artifact_event']['started_at'] = 123
    elif defect == 'output_hash':
        execution['artifact_metadata']['sha256'] = 'f' * 64
    elif defect == 'approval_claim':
        execution['dispatch']['artifact_event']['certification'] = 'L7'
    elif defect in {'action_newline', 'input_action_newline'}:
        key = 'action_records' if defect == 'action_newline' else 'input_action_records'
        execution[key][-1] = execution[key][-1].rstrip('\n')
    with pytest.raises(events.ArtifactEventError):
        events.validate_artifact_execution(execution, **pins)


@pytest.mark.parametrize('raw', [b'{"a":1,"\\u0061":2}', b'{"a":NaN}', b'{"a":1e9999}', b'[]', b'x' * 65537],
    ids=['decoded-duplicate', 'nan', 'overflow', 'array', 'oversized'])
def test_strict_original_json_rejects_duplicate_decoded_nonfinite_and_oversized(raw):
    with pytest.raises(events.ArtifactEventError):
        events.parse(raw)


def test_delivery_failure_retains_real_events_but_cannot_return_completed(domain, monkeypatch):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    real_flush = ledger.flush
    monkeypatch.setattr(ledger, 'flush', lambda **_: False)
    with pytest.raises(events.ArtifactEventError, match='DURABLE_ACTION_REQUIRED'):
        events.execute_artifact_case(spec, task, **args)
    monkeypatch.setattr(ledger, 'flush', real_flush)
    assert ledger.flush(timeout=1)
    assert len(events.read_artifact_action_span(root, task, spec['case'])) == 2
    assert len(list((root / 'artifacts').iterdir())) == 1


def test_real_operation_failure_is_failed_action_and_not_generic_completion(domain, monkeypatch):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    def failure(*a, **k):
        raise ValueError('private diagnostic that must not escape')
    monkeypatch.setattr(ArtifactFactory, 'retrieve', failure)
    with pytest.raises(events.ArtifactEventError, match='^ARTIFACT_EXECUTION_FAILED$'):
        events.execute_artifact_case(spec, task, **args)
    assert ledger.flush(timeout=1)
    original = events.read_artifact_action_span(root, task, spec['case'])
    assert json.loads(original[-1])['success'] is False
    assert 'private diagnostic' not in ''.join(original)


def test_observer_reader_keeps_original_bytes_and_never_flushes(domain, monkeypatch):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    events.execute_artifact_case(spec, task, **args)
    original = (root / 'action-records.jsonl').read_bytes()
    monkeypatch.setattr(ledger, 'flush', lambda *a, **k: pytest.fail('read flushed ledger'))
    assert ''.join(events.read_artifact_action_span(root, task, spec['case'])).encode() == original
    monkeypatch.undo()


@pytest.mark.parametrize('point', ['root', 'artifacts', 'objective_db', 'ledger'])
@pytest.mark.parametrize('kind', ['junction', 'reparse_attribute'])
def test_windows_reparse_points_rejected_before_writes(domain, monkeypatch, point, kind):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    target = {'root': root, 'artifacts': root / 'artifacts',
        'objective_db': root / 'objectives.db', 'ledger': ledger.path}[point]
    if kind == 'junction':
        original = getattr(Path, 'is_junction', lambda self: False)
        monkeypatch.setattr(Path, 'is_junction', lambda self: self == target or original(self), raising=False)
    else:
        original = Path.lstat
        monkeypatch.setattr(Path, 'lstat', lambda self: SimpleNamespace(st_file_attributes=0x400)
            if self == target else original(self))
    with pytest.raises(events.ArtifactEventError, match='DOMAIN_PATH_INVALID'):
        events.execute_artifact_case(spec, task, **args)
    assert ledger.status()['persisted'] == 0 and ledger.status()['pending'] == 0
    # The patched nonexistent artifact point does not create an actual store.
    assert not (root / 'artifacts').exists()


def test_real_symlink_domain_rejected_where_available(domain, tmp_path):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    linked = root / 'linked-artifacts'
    actual = root / 'actual-artifacts'
    actual.mkdir()
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip('Unprivileged Windows symlink creation unavailable; no elevation requested')
    with pytest.raises(events.ArtifactEventError, match='DOMAIN_PATH_INVALID'):
        events._path(linked)
    assert ledger.status()['persisted'] == 0


def test_runtime_change_after_real_actions_does_not_return_completion(domain):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    snapshots = iter((deepcopy(RUNTIME), {**RUNTIME, 'source_revision': 'c' * 40}))
    args['read_runtime'] = lambda: next(snapshots)
    with pytest.raises(events.ArtifactEventError, match='RUNTIME_CHANGED'):
        events.execute_artifact_case(spec, task, **args)
    assert ledger.status()['persisted'] == 2 and len(list((root / 'artifacts').iterdir())) == 1


def test_canonical_request_matches_actual_agent_request_normalized_types(domain):
    from app.agent_dispatch_api import AgentRequest
    request = events.canonical_artifact_case(events.SUPPORTED_CASES[1])['request']
    assert type(request['max_cost_usd']) is float and request['max_cost_usd'] == 0.0
    # The new operation is intentionally NOT mounted/allowed by this module.
    # Check all existing real schema defaults/types without falsely enabling it.
    existing = {**request, 'deterministic_operation': None}
    assert events.canonical(AgentRequest(**existing).model_dump()) == events.canonical(existing)


@pytest.mark.parametrize('case_id', [events.SUPPORTED_CASES[0], events.SUPPORTED_CASES[2]])
@pytest.mark.parametrize('defect', ['unrelated_predecessor', 'unobserved_gap'])
def test_independently_rehashed_subject_pair_cannot_borrow_input_chain_continuity(domain, case_id, defect):
    execution, pins = execute_and_collect(domain, case_id)
    rewritten = []
    previous = 'f' * 64 if defect == 'unrelated_predecessor' else execution['input_action_chain_join']['last_sha256']
    for line in execution['action_records']:
        event = json.loads(line)
        if defect == 'unobserved_gap':
            event['sequence'] += 1
        event['previous_sha256'] = previous
        event['sha256'] = events.sha(events.canonical({key: value for key, value in event.items() if key != 'sha256'}))
        previous = event['sha256']
        rewritten.append(json.dumps(event, sort_keys=True) + '\n')
    execution['action_records'] = rewritten
    first, last = [json.loads(line) for line in rewritten]
    execution['action_chain_join'].update(first_sequence=first['sequence'], last_sequence=last['sequence'],
        first_sha256=first['sha256'], last_sha256=last['sha256'])
    code = 'CROSS_OPERATION_CHAIN_INVALID' if defect == 'unrelated_predecessor' else 'ORIGINAL_BRIDGE_REQUIRED'
    with pytest.raises(events.ArtifactEventError, match=code):
        events.validate_artifact_execution(execution, **pins)


def test_failed_attempt_cannot_replay_while_real_writer_has_dequeued_unfinished_event(domain, monkeypatch):
    root, ledger, prepare, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[1])
    entered, release = threading.Event(), threading.Event()
    original_open, original_retrieve = Path.open, ArtifactFactory.retrieve
    calls = []
    def held_open(path, *a, **k):
        mode = a[0] if a else k.get('mode', 'r')
        if path == ledger.path and mode == 'a' and not entered.is_set():
            entered.set()
            assert release.wait(2)
        return original_open(path, *a, **k)
    def first_read_failure(factory, artifact_id):
        calls.append(artifact_id)
        if len(calls) == 1:
            raise ValueError('temporary readback failure')
        return original_retrieve(factory, artifact_id)
    monkeypatch.setattr(Path, 'open', held_open)
    monkeypatch.setattr(ArtifactFactory, 'retrieve', first_read_failure)
    try:
        with pytest.raises(events.ArtifactEventError, match='EXECUTION_FAILED'):
            events.execute_artifact_case(spec, task, **args)
        assert entered.wait(1)
        artifacts = set((root / 'artifacts').iterdir())
        with pytest.raises(events.ArtifactEventError, match='PRIOR_ACTION_PENDING'):
            events.execute_artifact_case(spec, task, **args)
        assert set((root / 'artifacts').iterdir()) == artifacts and len(artifacts) == 1
    finally:
        release.set()
        assert ledger.flush(timeout=1)
