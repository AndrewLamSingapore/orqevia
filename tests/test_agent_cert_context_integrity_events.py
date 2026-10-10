"""Real temporary artifacts/packer and fake HTTP only; never live/signing/L7 proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest

from app import agent_cert_artifact_events as events
from app import agent_cert_role_review as contracts
from app import agent_cert_event_api as api
from app import context_pack
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span
from scripts import agent_cert_reviewed_signing as bridge
from scripts import sign_admitted_agent_cases as admission
from tests.test_agent_cert_artifact_events import domain, execute_and_collect
from tests.test_agent_cert_artifact_paths import operator, collect, rejected_review_has_no_new_effect
from tests.test_agent_cert_recovery_events import fake_transport
from tests.test_agent_cert_operator_io import client
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE


CASE = events.CONTEXT_CASE


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No outbound network, key generation, protected signer or model operation permitted')
    monkeypatch.setattr('socket.create_connection', forbidden)
    monkeypatch.setattr('http.client.HTTPConnection.connect', forbidden)
    monkeypatch.setattr('http.client.HTTPSConnection.connect', forbidden)
    monkeypatch.setattr('cryptography.hazmat.primitives.asymmetric.ec.generate_private_key', forbidden)
    monkeypatch.setattr(bridge, 'ProtectedAzureES256Signer', forbidden)


def test_exact_existing_case_dimension_oracle_and_qualified_actions():
    spec = contracts.canonical_case_spec('a19', 'responsibility.a19', CASE)
    assert spec == events.canonical_artifact_case(CASE)
    assert spec['oracle_id'] == events.CONTEXT_ORACLE_ID != events.INTEGRITY_ORACLE_ID != events.ORACLE_ID
    assert spec['request']['max_cost_usd'] == 0 and spec['request']['preferred_provider'] is None
    assert len({events.artifact_action_type(CASE, **options) for options in ({}, {'setup': True}, {'prior': True})}) == 3
    assert all('context_integrity.complete.' in events.artifact_action_type(CASE, **options)
        for options in ({}, {'setup': True}, {'prior': True}))
    for unknown in ('general:complete', 'context_integrity:other', 'cross_agent_conflict:complete'):
        with pytest.raises(ValueError):
            events.canonical_artifact_case(unknown)


def test_real_once_receipt_only_pack_retained_conflicting_sources_and_distinct_a26_http(operator, monkeypatch):
    original_pack, original_retrieve, original_review = context_pack.build_context_pack, ArtifactFactory.retrieve, operator.reviewer
    pack_calls, reviewing, readbacks = [], [], []
    def pack(**kwargs):
        pack_calls.append(deepcopy(kwargs))
        candidates = kwargs['candidates']
        assert len(candidates) == 2 and {c.source_id for c in candidates} == {'CI1-A', 'CI1-B'}
        assert all(c.receipt_only is True and c.observed_at is c.max_age_seconds is None for c in candidates)
        assert {c.claim_value for c in candidates} == {'UP', 'DOWN'}
        assert len({c.claim_key for c in candidates}) == 1
        return original_pack(**kwargs)
    def retrieve(factory, identifier):
        if reviewing:
            readbacks.append(identifier)
        return original_retrieve(factory, identifier)
    def review(request):
        reviewing.append(True)
        try:
            return original_review(request)
        finally:
            reviewing.clear()
    monkeypatch.setattr(context_pack, 'build_context_pack', pack)
    monkeypatch.setattr(ArtifactFactory, 'retrieve', retrieve)
    monkeypatch.setattr(operator, 'reviewer', review)
    transport = fake_transport(operator)
    item = client(transport, spec=events.canonical_artifact_case(CASE))
    result = collect(operator, CASE, io=item.io(), actions=item.read_subject_actions)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution, report = json.loads(result.execution_bytes), json.loads(result.subject_artifact_bytes)
    event = execution['dispatch']['artifact_event']
    assert len(pack_calls) == report['pack_calls'] == 1  # Observer/reviewer never invoke packer again.
    assert report['context_pack']['context'] == [] and report['context_pack']['omitted']['conflict'] == 2
    assert report['winning_source_id'] is None and report['source_claim_truth'] == 'NOT_ESTABLISHED'
    assert report['source_freshness'] == 'UNKNOWN_RECEIPT_ONLY' and report['actions_executed'] == []
    index = report['conflict_source_index']
    assert [i['source_id'] for i in index] == ['CI1-A', 'CI1-B']
    assert index[0]['artifact_id'] != index[1]['artifact_id'] and index[0]['sha256'] != index[1]['sha256']
    assert index[0]['sha256'] == events.sha(result.prior_artifact_bytes)
    assert index[1]['sha256'] == events.sha(result.input_artifact_bytes)
    assert len(result.prior_actions) == len(result.input_actions) == 2 and len(result.subject_actions) == 4
    inner = [json.loads(line) for line in result.subject_actions][1:3]
    assert inner[1]['success'] is True and inner[1]['result_summary']['source_sha256'] == report['context_pack_sha256']
    for metadata in (event['prior_artifact_metadata'], event['input_artifact_metadata'], execution['artifact_metadata']):
        assert readbacks.count(metadata['artifact_id']) >= 2
        actual, raw = original_retrieve(ArtifactFactory(operator.root / 'artifacts'), metadata['artifact_id'])
        assert actual == metadata and events.sha(raw) == metadata['sha256']
    reviewer = json.loads(result.reviewer_artifact_bytes)
    assert (reviewer['dimension'], reviewer['test_case'], reviewer['reviewer_id']) == ('context_integrity', 'complete', 'a26')
    assert reviewer['oracle_id'] == events.CONTEXT_ORACLE_ID and reviewer['task_id'] != event['task_id']
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert len(item.original_replies()) == len(transport.calls) == item._response_limit == 26
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 2
    assert result.summary['signature'] == 'NOT_PERFORMED' and result.summary['certification'] == 'UNVERIFIED'
    original_ledger = operator.ledger.path.read_bytes()
    from fastapi import Response
    for options in ({}, {'setup': True}, {'prior': True}):
        api.actions(event['task_id'], Response(), action_type=events.artifact_action_type(CASE, **options), authorization='fixture-owner')
    assert operator.ledger.path.read_bytes() == original_ledger


@pytest.mark.parametrize('exception', [FileNotFoundError, PermissionError, context_pack.ContextPackError])
def test_pack_exception_is_not_laundered_into_conflict_success(operator, monkeypatch, exception):
    def fail(**kwargs):
        raise exception('public fixture')
    monkeypatch.setattr(context_pack, 'build_context_pack', fail)
    result = collect(operator, CASE)
    assert result.summary['state'] == 'REJECTED' and operator.calls.count('review') == 0
    assert operator.calls.count('submit') == 1 and operator.ledger.path.exists()


@pytest.mark.parametrize('defect', ['winner', 'freshness', 'executed_action', 'pack_calls', 'provenance', 'claim', 'omitted'])
def test_independent_literal_oracle_rejects_shared_generator_and_expected_bytes_defects(operator, monkeypatch, defect):
    helper = 'context_source_bytes' if defect in {'provenance', 'claim'} else '_context_result_bytes'
    original = getattr(events, helper)
    def broken(*args, **kwargs):
        value = json.loads(original(*args, **kwargs))
        if defect == 'provenance':
            value['source']['provenance'] = 'INVENTED_OWNER_AUTHORITY'
        elif defect == 'claim':
            # Preserve a real contradiction so exact expected pack bytes still
            # match: rejection must come from the independent literal oracle.
            if value['source']['source_id'] == 'CI1-A':
                value['source']['claim_value'] = 'INVENTED_UP_ALTERNATIVE'
        elif defect == 'winner':
            value['winning_source_id'] = 'CI1-A'
        elif defect == 'freshness':
            value['source_freshness'] = 'SOURCE_OBSERVED'
        elif defect == 'executed_action':
            value['actions_executed'] = ['restart']
        elif defect == 'pack_calls':
            value['pack_calls'] = 2
        else:
            value['context_pack']['omitted']['conflict'] = 1
            value['context_pack_sha256'] = events.sha(events.canonical(value['context_pack']))
        return events.canonical(value)
    monkeypatch.setattr(events, helper, broken)
    result = collect(operator, CASE)
    assert result.summary['state'] == 'REJECTED' and operator.calls.count('review') == 0
    assert operator.calls.count('submit') == 1 and result.prior_artifact_bytes and result.input_artifact_bytes


def rehash_subject_span(execution):
    event = execution['dispatch']['artifact_event']
    previous, rewritten = json.loads(execution['action_records'][0])['previous_sha256'], []
    for line in execution['action_records']:
        item = json.loads(line)
        item['previous_sha256'] = previous
        item['sha256'] = events.sha(events.canonical({k: v for k, v in item.items() if k != 'sha256'}))
        previous = item['sha256']
        rewritten.append(json.dumps(item, sort_keys=True) + '\n')
    execution['action_records'] = rewritten
    execution['action_chain_join'] = action_span(rewritten, task_id=event['task_id'], agent_id='a19',
        action_type=events.artifact_action_type(CASE), schema=events.RESULT_SCHEMA,
        metadata=execution['artifact_metadata'], began=events._utc(event['started_at']),
        ended=events._utc(event['completed_at']), action_id=event['subject_action_id'])


@pytest.mark.parametrize('defect', ['failed_pack', 'wrong_source', 'wrong_hash', 'wrong_action', 'extra_pack',
    'missing_pack', 'strict_order', 'missing_a', 'source_drift', 'runtime_drift', 'stale'])
def test_original_pack_chain_and_source_bindings_reject_rehashed_tampering(domain, defect):
    execution, pins = execute_and_collect(domain, CASE)
    records = [json.loads(line) for line in execution['action_records']]
    if defect == 'failed_pack':
        records[2]['success'] = False
    elif defect == 'wrong_source':
        for record in records[1:3]:
            record['parameters_summary']['source_artifacts'][0]['artifact_id'] = 'f' * 32
    elif defect == 'wrong_hash':
        records[2]['result_summary']['source_sha256'] = 'f' * 64
    elif defect == 'wrong_action':
        records[1]['action_id'] = records[2]['action_id'] = str(uuid.uuid4())
    elif defect in {'extra_pack', 'missing_pack'}:
        records[3:3] = deepcopy(records[1:3]) if defect == 'extra_pack' else []
        if defect == 'missing_pack':
            del records[1:3]
        for i, record in enumerate(records):
            record['sequence'] = records[0]['sequence'] + i
    elif defect == 'strict_order':
        event = execution['dispatch']['artifact_event']
        assert events._utc(event['started_at']) < events._utc(event['completed_at'])
        records[1]['timestamp'], records[2]['timestamp'] = event['completed_at'], event['started_at']
    elif defect == 'missing_a':
        execution['prior_artifact_content_utf8'] = None
    elif defect == 'source_drift':
        pins['source_revision'] = 'f' * 40
    elif defect == 'runtime_drift':
        execution['runtime_current']['image_digest'] = 'sha256:' + 'f' * 64
    else:
        pins['now'] += timedelta(minutes=6)
    execution['action_records'] = [json.dumps(record, sort_keys=True) + '\n' for record in records]
    rehash_subject_span(execution)
    with pytest.raises(events.ArtifactEventError):
        events.validate_artifact_execution(execution, **pins)


def test_exact_protected_mapping_real_expiry_self_review_and_complete_collision(operator):
    result = collect(operator, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    now = datetime.now(timezone.utc)
    row = dict(agent_id='a19', capability_id='responsibility.a19', dimension='context_integrity',
        test_case='complete', verifier='a26', executor_identity='a19', source_revision=SOURCE,
        review_source_revision=SOURCE, reviewer_code_revision='f' * 40, authority_scope='advisory',
        test_result='PASS', review_test_version=events.CONTEXT_ORACLE_ID,
        certification_test='context-integrity-complete', test_version=events.CASE_VERSION,
        review_run_id='temporary-artifact-review', certified_at=now.isoformat(), last_revalidated=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat())
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE, reviewer_code_revision='f' * 40, now=now)
    assert bridge._review(row, result.execution_bytes, result.review_bytes, **pins) is True
    for changed in (dict(row, dimension='evidence_integrity'), dict(row, verifier='a19'),
            dict(row, expires_at=(now - timedelta(seconds=1)).isoformat())):
        with pytest.raises(bridge.CertificationReviewError):
            bridge._review(changed, result.execution_bytes, result.review_bytes, **pins)
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / admission.MANIFEST).read_bytes())
    manifest['cases'][0]['record'].update(dimension='context_integrity', test_case='complete')
    assert admission.parse(events.canonical(manifest))[0]['record']['dimension'] == 'context_integrity'
    for key in ('cloud_policy', 'owner_policy_sha256'):
        altered = deepcopy(manifest)
        altered['cases'][0][key] = {} if key == 'cloud_policy' else 'f' * 64
        with pytest.raises(ValueError):
            admission.parse(events.canonical(altered))


@pytest.mark.parametrize('target', ['a', 'b', 'result'])
def test_actual_sources_and_conflict_index_reread_after_final_objective(operator, monkeypatch, target):
    result = collect(operator, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(operator.review_request['context'])['execution']
    original, reads = operator.objectives.get_read_only, []
    def read(task, authorization):
        reply = original(task, authorization)
        reads.append(task)
        if len(reads) == 2:
            event = execution['dispatch']['artifact_event']
            metadata = event['prior_artifact_metadata'] if target == 'a' else event['input_artifact_metadata'] if target == 'b' else execution['artifact_metadata']
            path = operator.root / 'artifacts' / metadata['artifact_id'] / 'artifact.json'
            path.write_bytes(path.read_bytes() + b' ')
        return reply
    monkeypatch.setattr(operator.objectives, 'get_read_only', read)
    rejected_review_has_no_new_effect(operator, deepcopy(operator.review_request))
