"""Tiny pure packaging validators; the actual engine/image gate is off-host."""
from pathlib import Path

import pytest

from scripts import smoke_gods_eye_image as smoke
from app.agent_registry import load_agent_registry


REVISION = 'a' * 40


def formal_fixture():
    registry = load_agent_registry()
    summary = {'status': 'READY', 'source_revision': REVISION, 'permanent_agent_count': 21,
        'rdf': 'PASS', 'shacl': 'PASS_ACCEPTED_PROJECTION',
        'reasoning': 'PASS_FIXED_OWL2_RL_SUBSET', 'accepted_results': 1,
        'accepted_metrics': 1, 'l7_awarded': False, 'production_acceptance': 'UNVERIFIED'}
    return dict(summary=summary, overview={'agents': [{'id': a['id']} for a in registry['agents']]},
        why={'agent_id': 'a20', 'l7_awarded': False, 'verified_capabilities': []},
        proof={'status': 'READY', 'result_id': smoke.RESULT, 'rows': [{'digest': smoke.PUBLIC_RESULT_DIGEST,
            'verification': 'UNVERIFIED'}]}, dependencies={'status': 'READY', 'result_id': smoke.RESULT,
            'rows': [{'metric_id': 'ci-public-count', 'agent_id': 'a20'}]},
        registry=registry, revision=REVISION)


def test_valid_public_fixture_no_execution_or_certification():
    fixture = formal_fixture()
    smoke.validate_formal(**fixture)
    projection = smoke.synthetic_projection(fixture['registry'], REVISION)
    assert len(projection['agents']) == 21
    assert projection['results'][0]['environment'] == 'CI'
    assert projection['results'][0]['verification'] == 'UNVERIFIED'


@pytest.mark.parametrize('field,value', [('status', 'UNAVAILABLE'), ('source_revision', 'b' * 40),
    ('permanent_agent_count', 20), ('rdf', 'UNKNOWN'), ('shacl', 'MOCK_PASS'),
    ('reasoning', 'UNAVAILABLE'), ('accepted_results', True), ('accepted_metrics', True),
    ('l7_awarded', True), ('production_acceptance', 'VERIFIED')])
def test_bad_formal_claims_fail_closed(field, value):
    args = formal_fixture(); args['summary'][field] = value
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_formal(**args)


@pytest.mark.parametrize('where,field,value', [('why', 'verified_capabilities', ['invented']),
    ('why', 'agent_id', 'a03'), ('proof', 'result_id', 'result:other'),
    ('dependencies', 'rows', [{'metric_id': 'private', 'agent_id': 'a18'}])])
def test_wrong_query_binding_or_authority_uplift_rejected(where, field, value):
    args = formal_fixture(); args[where][field] = value
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_formal(**args)


def test_wrong_proof_digest_or_verification_rejected():
    args = formal_fixture(); args['proof']['rows'][0]['digest'] = '0' * 64
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_formal(**args)
    args = formal_fixture(); args['proof']['rows'][0]['verification'] = 'VERIFIED'
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_formal(**args)


@pytest.mark.parametrize('expected,configured', [('short', 'short'), ('A' * 40, 'A' * 40),
    (REVISION, 'UNKNOWN'), (REVISION, 'b' * 40), (None, None)])
def test_image_source_binding_rejects_unknown_mismatch_or_noncanonical(expected, configured):
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_revision(expected, configured)


def test_unchanged_fixture_bytes_and_only_zero_wal_coordination_allowed(tmp_path):
    path = tmp_path / 'queue.db'; path.write_bytes(b'public-fixture')
    before = smoke.inventory(tmp_path)
    smoke.validate_read_only(before, tmp_path)
    (tmp_path / 'queue.db-shm').write_bytes(b'\0' * 32768)
    (tmp_path / 'queue.db-wal').write_bytes(b'')
    smoke.validate_read_only(before, tmp_path)
    (tmp_path / 'queue.db-wal').write_bytes(b'nonempty')
    with pytest.raises(smoke.SmokeFailure, match='UNEXPECTED_SQLITE_COORDINATION'):
        smoke.validate_read_only(before, tmp_path)


def test_changed_or_added_domain_bytes_rejected(tmp_path):
    path = tmp_path / 'queue.db'; path.write_bytes(b'public-fixture')
    before = smoke.inventory(tmp_path)
    path.write_bytes(b'changed')
    with pytest.raises(smoke.SmokeFailure, match='READ_ROUTE_CHANGED_DOMAIN_BYTES'):
        smoke.validate_read_only(before, tmp_path)
    path.write_bytes(b'public-fixture')
    (tmp_path / 'unexpected.db').write_bytes(b'new')
    with pytest.raises(smoke.SmokeFailure, match='READ_ROUTE_CREATED_DOMAIN_STATE'):
        smoke.validate_read_only(before, tmp_path)


def test_source_export_includes_only_three_public_governance_runtime_inputs(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    import build_source_release as release
    assert len(release.PUBLIC_RUNTIME_GOVERNANCE) == 3
    assert all(release.runtime_source_file(name) for name in release.PUBLIC_RUNTIME_GOVERNANCE)
    for name in ('governance/private-key.json', 'governance/old-receipt.json',
                 'governance/agent-cert-verifier-azure-pins.json.backup', '.env', '.git/config'):
        assert not release.runtime_source_file(name)
    for name in ('app/gods_eye_api.py', 'app/semantic/shapes.ttl', 'requirements-semantic.txt'):
        assert release.runtime_source_file(name)


def public_snapshot():
    registry = load_agent_registry()
    return registry, {'schema_version': 'jarvis.gods-eye.v1', 'source_revision': REVISION,
        'access_scope': 'LOOPBACK_OPERATOR_NOT_PWA_IDENTITY_PROOF',
        'registry': {'agent_ids': sorted(a['id'] for a in registry['agents'])},
        'agents': [{'agent_id': a['id'], 'l7_status': 'UNKNOWN'} for a in registry['agents']],
        'certification': {'l7_count': None}, 'semantics': {'status': 'READY'}}


def test_public_browser_snapshot_does_not_inherit_private_certification_read():
    registry, snapshot = public_snapshot()
    smoke.validate_snapshot(snapshot, registry, REVISION)
    snapshot['certification']['l7_count'] = 0
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_snapshot(snapshot, registry, REVISION)


@pytest.mark.parametrize('change', ['empty', 'duplicate', 'l7', 'missing-count', 'wrong-source'])
def test_false_snapshot_count_empty_agents_or_certification_uplift_cannot_pass(change):
    registry, snapshot = public_snapshot()
    if change == 'empty': snapshot['agents'] = []
    elif change == 'duplicate': snapshot['agents'][-1] = snapshot['agents'][0]
    elif change == 'l7': snapshot['agents'][0]['l7_status'] = 'L7-CURRENT'
    elif change == 'missing-count': snapshot['certification'] = {}
    else: snapshot['source_revision'] = 'b' * 40
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_snapshot(snapshot, registry, REVISION)
