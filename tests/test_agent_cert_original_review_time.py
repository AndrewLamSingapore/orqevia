"""Original temporary event clocks, not live evidence, keys, signing or L7."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.client
import json
import socket
import subprocess
from types import SimpleNamespace
import urllib.request

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import agent_cert_initialization as initialization, agent_registry
from app.agent_cert_identity_review import canonical, sha, read_action_span, utc
from app.agent_cert_initialization_review import InitializationReviewError, validate_initialization_execution
from app.artifact_factory import ArtifactFactory
from scripts import agent_cert_reviewed_signing as bridge
from tests.test_agent_cert_initialization_fleet import PAIRS
from tests.test_agent_cert_initialization_fleet_events import fleet_event, review
from tests.test_agent_cert_authority_chain import runtime, collect, signer_row, recompute
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE
from tests.test_agent_cert_reviewed_signing import REVIEWER_CODE


@pytest.fixture(autouse=True)
def forbidden_external_operations(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Pure original-review checks cannot access network, processes, keys or signer')
    for owner, name in ((socket, 'create_connection'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect'), (httpx.HTTPTransport, 'handle_request'),
                        (subprocess, 'run'), (ec, 'generate_private_key'),
                        (bridge, 'ProtectedAzureES256Signer')):
        monkeypatch.setattr(owner, name, forbidden)


def initialization_input(item):
    """Reuse owning temporary producer/reviewer and their untouched original lines."""
    dispatch = review(item)
    metadata, raw = ArtifactFactory(item.root / 'artifacts').retrieve(dispatch['artifact']['artifact_id'])
    assert metadata == dispatch['artifact']
    content = json.loads(raw)
    joined = content['subject_domain_join']
    primary = canonical(item.execution)
    now = datetime.now(timezone.utc)
    reviewer, _ = initialization.initialization_reviewer(item.agent, item.cap)
    oracle = initialization.initialization_oracle_id(item.agent, item.cap)
    row = dict(agent_id=item.agent, capability_id=item.cap, dimension='baseline',
        test_case='initialization', certification_test='baseline-initialization', test_version=oracle,
        test_result='PASS', verifier=reviewer, executor_identity=item.agent,
        evidence='execution.json', evidence_sha256=sha(primary), certified_at=now.isoformat(),
        last_revalidated=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
        source_revision=SOURCE, authority_scope=agent_registry.agent_record(item.agent)['authority'],
        review_evidence='review.json', review_evidence_sha256='',
        review_run_id='temporary-original-time-review', review_test_version=oracle,
        review_source_revision=SOURCE, reviewer_code_revision=REVIEWER_CODE)
    envelope = dict(schema_version='prime.agent-certification.review.v1', reviewer_identity=reviewer,
        review_run_id=row['review_run_id'], source_revision=SOURCE, agent_id=item.agent,
        capability_id=item.cap, dimension='baseline', test_case='initialization',
        execution_evidence_sha256=sha(primary), test_result='PASS', review_test_version=oracle,
        observations=dict(execution_task_id=joined['task_id'], result_sha256=joined['result_sha256'],
            case_spec_sha256=joined['case_spec_sha256'], runtime_image_id=IMAGE,
            registry_sha256=item.registry_sha, reviewer_code_revision=REVIEWER_CODE,
            oracle_id=oracle, oracle_pass=True, reviewer_execution=dict(dispatch=dispatch,
                artifact_content_utf8=raw.decode(), action_records=read_action_span(item.ledger.path,
                    dispatch['task_id'], 'agent.certification.initialization.review'),
                transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
                    artifact_http_status=200, runtime_source_revision=SOURCE, actual_runtime_image=IMAGE))))
    reviewed = canonical(envelope)
    row['review_evidence_sha256'] = sha(reviewed)
    return SimpleNamespace(row=row, primary=primary, reviewed=reviewed, envelope=envelope, now=now)


def check(item, **changes):
    return bridge._review(item.row, item.primary, item.reviewed, source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE,
        now=changes.get('now', item.now + timedelta(minutes=6)))


def change_review_time(envelope, stamp, *, bind_metadata=False):
    proof = envelope['observations']['reviewer_execution']
    content = json.loads(proof['artifact_content_utf8'])
    content['reviewed_at'] = stamp.isoformat()
    proof['artifact_content_utf8'] = canonical(content).decode()
    if bind_metadata:
        raw = proof['artifact_content_utf8'].encode()
        proof['dispatch']['artifact'].update(sha256=sha(raw), bytes=len(raw))


@pytest.mark.parametrize('fleet_event', PAIRS, indirect=True,
    ids=[agent + '-' + capability for agent, capability in PAIRS])
def test_later_initialization_review_preserves_each_owned_original(fleet_event):
    item = initialization_input(fleet_event)
    original = deepcopy(item.row), item.primary, item.reviewed
    assert check(item) is True
    assert (item.row, item.primary, item.reviewed) == original
    proof = item.envelope['observations']['reviewer_execution']
    reviewer, capability = initialization.initialization_reviewer(fleet_event.agent, fleet_event.cap)
    assert proof['dispatch']['agent_id'] == reviewer != fleet_event.agent
    assert proof['dispatch']['capability'] == capability
    assert proof['dispatch']['task_id'] != fleet_event.execution['dispatch']['task_id']
    if fleet_event.agent == 'a26':
        assert (reviewer, capability) == ('a18', 'responsibility.a27')
    with pytest.raises(InitializationReviewError, match='IDENTITY_EVENT_REJECTED'):
        validate_initialization_execution(fleet_event.execution, source_revision=SOURCE,
            runtime_image_id=IMAGE, registry_sha256=fleet_event.registry_sha,
            agent_id=fleet_event.agent, capability_id=fleet_event.cap, now=item.now + timedelta(minutes=6))


@pytest.mark.parametrize('case_id', ('authority:complete', 'unauthorized_rejection:authorized'))
def test_later_authority_review_preserves_original_interval(runtime, case_id):
    from app import agent_cert_authority_events as events
    result = collect(runtime, case_id)
    row = signer_row(result)
    original = deepcopy(row), result.execution_bytes, result.review_bytes
    later = utc(row['certified_at']) + timedelta(minutes=6)
    assert recompute(row, result.execution_bytes, result.review_bytes, now=later) is True
    assert (row, result.execution_bytes, result.review_bytes) == original
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_EVENT_STALE_OR_UNBOUNDED'):
        events.validate_authority_execution(json.loads(result.execution_bytes), source_revision=SOURCE,
            runtime_image_id=IMAGE, registry_sha256=runtime.registry_sha, now=later)


def test_original_initialization_review_still_cannot_consume_stale_report(fleet_event):
    item = initialization_input(fleet_event)
    report = json.loads(fleet_event.execution['artifact_content_utf8'])
    change_review_time(item.envelope, utc(report['captured_at']) + timedelta(seconds=301))
    item.reviewed = canonical(item.envelope)
    with pytest.raises(InitializationReviewError, match='IDENTITY_EVENT_REJECTED'):
        check(item)
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_TIME_UNBOUND'):
        initialization.validate_initialization_report(fleet_event.execution['artifact_content_utf8'],
            task_id=fleet_event.execution['dispatch']['task_id'], runtime=fleet_event.execution['runtime'],
            source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=fleet_event.registry_sha,
            agent_id=fleet_event.agent, capability_id=fleet_event.cap,
            now=utc(report['captured_at']) + timedelta(seconds=301))


@pytest.mark.parametrize('defect', ('self_review', 'source', 'runtime', 'future_review',
    'unbound_timestamp', 'review_after_artifact', 'review_after_certified',
    'current_expiry', 'future_revalidation', 'missing_review_actions'))
def test_later_initialization_verifier_rejects_binding_and_clock_tamper(fleet_event, defect):
    item = initialization_input(fleet_event)
    proof = item.envelope['observations']['reviewer_execution']
    content = json.loads(proof['artifact_content_utf8'])
    later = item.now + timedelta(minutes=6)
    if defect == 'self_review':
        item.row['verifier'] = fleet_event.agent
    elif defect == 'source':
        item.row['source_revision'] = 'c' * 40
    elif defect == 'runtime':
        execution = json.loads(item.primary)
        execution['runtime']['image_digest'] = 'sha256:' + 'c' * 64
        item.primary = canonical(execution)
    elif defect == 'future_review':
        change_review_time(item.envelope, later + timedelta(seconds=1))
    elif defect == 'unbound_timestamp':
        change_review_time(item.envelope, utc(content['reviewed_at']) + timedelta(microseconds=1))
    elif defect == 'review_after_artifact':
        change_review_time(item.envelope, utc(proof['dispatch']['artifact']['timestamp']) +
            timedelta(seconds=1), bind_metadata=True)
    elif defect == 'review_after_certified':
        item.row['certified_at'] = (utc(content['reviewed_at']) - timedelta(microseconds=1)).isoformat()
    elif defect == 'current_expiry':
        item.row['expires_at'] = later.isoformat()
    elif defect == 'future_revalidation':
        item.row['last_revalidated'] = (later + timedelta(microseconds=1)).isoformat()
    else:
        proof['action_records'] = []
    item.reviewed = canonical(item.envelope)
    with pytest.raises(ValueError):
        check(item, now=later)


@pytest.mark.parametrize('target', ('execution', 'review'))
def test_original_byte_tamper_never_reaches_signer(fleet_event, tmp_path, target):
    item = initialization_input(fleet_event)
    directory = tmp_path / 'protected-evidence' / fleet_event.agent
    directory.mkdir(parents=True)
    for name, raw in (('execution', item.primary), ('review', item.reviewed)):
        (directory / (name + '.json')).write_bytes(raw + (b'\n' if name == target else b''))
    with pytest.raises(bridge.CertificationReviewError, match='APPROVED_ARTIFACT_MISMATCH'):
        bridge.sign_reviewed_case(item.row, evidence_root=directory.parent,
            execution_sha256=sha(item.primary), review_sha256=sha(item.reviewed),
            execution_source_revision=SOURCE, runtime_image_id=IMAGE,
            reviewer_code_revision=REVIEWER_CODE,
            public_pin={'key_id': 'unreachable-test-only', 'jwk': {}},
            sign_digest=lambda _: pytest.fail('Original-byte tamper cannot reach signing'),
            now=item.now + timedelta(minutes=6))


def test_population_and_owning_age_limits_are_not_expanded():
    from app import agent_cert_authority_events as authority, agent_cert_artifact_events as artifact
    from scripts.sign_admitted_agent_cases import CODE_FILES, RUNTIME_REVIEW_CODE_FILES
    assert len(PAIRS) == 29 and len({agent for agent, _ in PAIRS}) == 21
    assert initialization.MAX_AGE_SECONDS == authority.MAX_AGE_SECONDS == artifact.MAX_AGE_SECONDS == 300
    assert len(CODE_FILES) == 51 and len(RUNTIME_REVIEW_CODE_FILES) == 50
    assert set(CODE_FILES) - set(RUNTIME_REVIEW_CODE_FILES) == {'scripts/agent_cert_reviewed_signing.py'}
