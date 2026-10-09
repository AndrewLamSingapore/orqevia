"""Original temporary domains/fake HTTP only; no live/signature/L7 proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest

from app import agent_cert_artifact_events as events
from app import agent_cert_role_review as contracts
from app import agent_cert_event_api as api
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span
from scripts import agent_cert_reviewed_signing as bridge
from scripts import sign_admitted_agent_cases as admission
from tests.test_agent_cert_artifact_events import domain, execute_and_collect
from tests.test_agent_cert_artifact_paths import operator, collect, rejected_review_has_no_new_effect
from tests.test_agent_cert_recovery_events import fake_transport
from tests.test_agent_cert_operator_io import client
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE


CASE = events.INTEGRITY_CASE


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No network, key generation, protected signer or model operation permitted')
    monkeypatch.setattr('socket.create_connection', forbidden)
    monkeypatch.setattr('http.client.HTTPConnection.connect', forbidden)
    monkeypatch.setattr('http.client.HTTPSConnection.connect', forbidden)
    monkeypatch.setattr('cryptography.hazmat.primitives.asymmetric.ec.generate_private_key', forbidden)
    monkeypatch.setattr(bridge, 'ProtectedAzureES256Signer', forbidden)


def test_only_existing_case_has_distinct_oracle_dimension_and_action_names():
    spec = contracts.canonical_case_spec('a19', 'responsibility.a19', CASE)
    assert spec == events.canonical_artifact_case(CASE)
    assert spec['oracle_id'] == events.INTEGRITY_ORACLE_ID != events.ORACLE_ID
    assert spec['request']['max_cost_usd'] == 0 and spec['request']['preferred_provider'] is None
    assert len({events.artifact_action_type(CASE, prior=True), events.artifact_action_type(CASE, setup=True),
        events.artifact_action_type(CASE), 'agent.certification.artifact.evidence_integrity.complete.read'}) == 4
    assert all('evidence_integrity.complete.' in events.artifact_action_type(CASE, **options)
        for options in ({}, {'setup': True}, {'prior': True}))
    for unknown in ('general:complete', 'context_integrity:complete', 'evidence_integrity:other'):
        with pytest.raises(ValueError):
            events.canonical_artifact_case(unknown)


def test_exact_admission_case_forbids_cloud_policy_before_any_signer():
    from pathlib import Path
    manifest = json.loads((Path(__file__).parents[1] / admission.MANIFEST).read_bytes())
    entry = manifest['cases'][0]
    entry['record'].update(dimension='evidence_integrity', test_case='complete')
    assert admission.parse(events.canonical(manifest))[0]['record']['dimension'] == 'evidence_integrity'
    for key in ('cloud_policy', 'owner_policy_sha256'):
        changed = deepcopy(manifest)
        changed['cases'][0][key] = {} if key == 'cloud_policy' else 'f' * 64
        with pytest.raises(ValueError):
            admission.parse(events.canonical(changed))


def test_real_two_intact_revisions_stale_digest_read_and_distinct_a26_bounded_http(operator, monkeypatch):
    original_retrieve, original_review = ArtifactFactory.retrieve, operator.reviewer
    reviewing, readbacks = [], []
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
    monkeypatch.setattr(ArtifactFactory, 'retrieve', retrieve)
    monkeypatch.setattr(operator, 'reviewer', review)
    transport = fake_transport(operator)
    item = client(transport, spec=events.canonical_artifact_case(CASE))
    result = collect(operator, CASE, io=item.io(), actions=item.read_subject_actions)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['artifact_event']
    report = json.loads(result.subject_artifact_bytes)
    assert result.prior_artifact_bytes != result.input_artifact_bytes
    assert report['expected_sha256'] == events.sha(result.prior_artifact_bytes)
    assert report['observed_sha256'] == events.sha(result.input_artifact_bytes)
    assert report['expected_sha256'] != report['observed_sha256']
    assert report['cited_artifacts'] == [] and report['assessment'] == 'UNKNOWN_UNTRUSTED_REVISION'
    assert report['storage_corruption_tested'] is False
    assert len(result.prior_actions) == len(result.input_actions) == 2 and len(result.subject_actions) == 4
    read = [json.loads(line) for line in result.subject_actions][1:3]
    assert read[1]['success'] is False and read[1]['error'] == 'CitationDigestMismatch'
    assert read[0]['target'] == event['input_artifact_metadata']['artifact_id']
    for metadata in (event['prior_artifact_metadata'], event['input_artifact_metadata'], execution['artifact_metadata']):
        assert readbacks.count(metadata['artifact_id']) >= 2
        actual_metadata, actual = original_retrieve(ArtifactFactory(operator.root / 'artifacts'), metadata['artifact_id'])
        assert actual_metadata == metadata and events.sha(actual) == metadata['sha256']
    reviewer = json.loads(result.reviewer_artifact_bytes)
    assert reviewer['dimension'] == 'evidence_integrity' and reviewer['test_case'] == 'complete'
    assert reviewer['oracle_id'] == events.INTEGRITY_ORACLE_ID and reviewer['reviewer_id'] == 'a26'
    assert reviewer['task_id'] != event['task_id'] and result.summary['signature'] == 'NOT_PERFORMED'
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert len(item.original_replies()) == len(transport.calls) == item._response_limit == 26
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 2
    assert all(connection.closed and connection.response.closed for connection in transport.connections)
    original_ledger = operator.ledger.path.read_bytes()
    for options in ({}, {'setup': True}, {'prior': True}):
        from fastapi import Response
        api.actions(event['task_id'], Response(), action_type=events.artifact_action_type(CASE, **options),
            authorization='fixture-owner')
    assert operator.ledger.path.read_bytes() == original_ledger


@pytest.mark.parametrize('defect', ['absence', 'permission', 'metadata_corruption', 'wrong_mismatch_code', 'no_mismatch'])
def test_only_actual_intact_b_stale_pin_mismatch_is_accepted(operator, monkeypatch, defect):
    original = events.checked_citation_read
    def checked(factory, manifest, **pins):
        if defect == 'absence':
            raise FileNotFoundError('public fixture')
        if defect == 'permission':
            raise PermissionError('public fixture')
        if defect == 'metadata_corruption':
            raise ValueError('Artifact integrity mismatch')
        if defect == 'wrong_mismatch_code':
            raise events.CitationDigestMismatch('NOT_THE_SOURCE_OWNED_MISMATCH')
        if defect == 'no_mismatch':
            return factory.retrieve(manifest['target_artifact_id'])[1]
        return original(factory, manifest, **pins)
    monkeypatch.setattr(events, 'checked_citation_read', checked)
    result = collect(operator, CASE)
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert operator.ledger.path.exists()  # Failed originals remain; no replay/cleanup.


@pytest.mark.parametrize('defect', ['cited_content', 'swapped_digests', 'invented_recovery', 'extra_retry', 'wrong_revision_fact'])
def test_independent_hash_and_content_oracle_rejects_shared_generator_defect(operator, monkeypatch, defect):
    helper = 'integrity_revision_bytes' if defect == 'wrong_revision_fact' else '_integrity_result_bytes'
    original = getattr(events, helper)
    def broken(*args, **kwargs):
        value = json.loads(original(*args, **kwargs))
        if defect == 'wrong_revision_fact':
            value['observation']['observations'] = ['INVENTED_RECOVERY']
        elif defect == 'cited_content':
            value['cited_artifacts'] = ['B']; value['assessment'] = 'RECOVERED'
        elif defect == 'swapped_digests':
            value['expected_sha256'], value['observed_sha256'] = value['observed_sha256'], value['expected_sha256']
        elif defect == 'invented_recovery':
            value['recovery_proven'] = True
        else:
            value['retries'] = 1
        return events.canonical(value)
    monkeypatch.setattr(events, helper, broken)
    result = collect(operator, CASE)
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.prior_artifact_bytes and result.input_artifact_bytes and result.subject_artifact_bytes


def rehash_subject_span(execution):
    event = execution['dispatch']['artifact_event']
    previous = json.loads(execution['action_records'][0])['previous_sha256']
    rewritten = []
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


@pytest.mark.parametrize('defect', ['success_true', 'wrong_error', 'wrong_target', 'wrong_pin', 'wrong_read_id',
    'extra_read', 'strict_order', 'missing_a', 'runtime_drift', 'stale'])
def test_rehashed_original_failure_chain_and_source_boundaries_fail_closed(domain, defect):
    execution, pins = execute_and_collect(domain, CASE)
    records = [json.loads(line) for line in execution['action_records']]
    if defect == 'success_true':
        records[2]['success'] = True
    elif defect == 'wrong_error':
        records[2]['error'] = 'FileNotFoundError'
    elif defect == 'wrong_target':
        records[1]['target'] = records[2]['target'] = 'f' * 32
    elif defect == 'wrong_pin':
        for record in records[1:3]:
            record['parameters_summary']['expected_sha256'] = 'f' * 64
    elif defect == 'wrong_read_id':
        records[1]['action_id'] = records[2]['action_id'] = str(uuid.uuid4())
    elif defect == 'extra_read':
        records[3:3] = deepcopy(records[1:3])
        first_sequence = records[0]['sequence']
        for i, record in enumerate(records):
            record['sequence'] = first_sequence + i
    elif defect == 'strict_order':
        assert events._utc(execution['dispatch']['artifact_event']['started_at']) < pins['now']
        records[1]['timestamp'] = (pins['now'] + timedelta(seconds=1)).isoformat()
    elif defect == 'missing_a':
        execution['prior_artifact_content_utf8'] = None
    elif defect == 'runtime_drift':
        execution['runtime_current']['source_revision'] = 'f' * 40
    else:
        pins['now'] += timedelta(minutes=6)
    execution['action_records'] = [json.dumps(record, sort_keys=True) + '\n' for record in records]
    rehash_subject_span(execution)
    with pytest.raises(events.ArtifactEventError):
        events.validate_artifact_execution(execution, **pins)


def review_row(result):
    now = datetime.now(timezone.utc)
    return dict(agent_id='a19', capability_id='responsibility.a19', dimension='evidence_integrity',
        test_case='complete', verifier='a26', executor_identity='a19', source_revision=SOURCE,
        review_source_revision=SOURCE, reviewer_code_revision='f' * 40, authority_scope='advisory',
        test_result='PASS', review_test_version=events.INTEGRITY_ORACLE_ID,
        certification_test='evidence-integrity-complete', test_version=events.CASE_VERSION,
        review_run_id=result.summary['review_run_id'] if 'review_run_id' in result.summary else 'temporary-artifact-review',
        certified_at=now.isoformat(), last_revalidated=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())


def test_pure_protected_review_maps_exact_dimension_no_signing_and_rejects_expiry_or_case_swap(operator):
    result = collect(operator, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    row = review_row(result)
    now = datetime.now(timezone.utc)
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE, reviewer_code_revision='f' * 40, now=now)
    assert bridge._review(row, result.execution_bytes, result.review_bytes, **pins) is True
    for changed in (dict(row, dimension='general'), dict(row, test_case='other'),
            dict(row, expires_at=(now - timedelta(seconds=1)).isoformat()), dict(row, verifier='a19')):
        with pytest.raises(bridge.CertificationReviewError):
            bridge._review(changed, result.execution_bytes, result.review_bytes, **pins)


@pytest.mark.parametrize('target', ['a', 'b', 'result'])
def test_actual_original_artifacts_rechecked_after_final_objective_read(operator, monkeypatch, target):
    result = collect(operator, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(operator.review_request['context'])['execution']
    original = operator.objectives.get_read_only
    reads = []
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
