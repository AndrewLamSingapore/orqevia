"""Preview-only contract tests: mocked loopback transport, no worker or inference."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.request

from fastapi import Header, Request
from fastapi.testclient import TestClient
import pytest

from app import gods_eye_preview as preview
from app.agent_registry import load_agent_registry
from app.client_auth import authenticate_owner
from app.semantic_fabric import SemanticError


TASK = '687845ae-6032-4355-a5e2-f124c8b22e07'
OTHER = 'ee56994f-6078-4368-8247-7a89bc690073'
TOKEN = 'synthetic-preview-unit-test-token'
SOURCE = 'a' * 40
DIGEST = 'b' * 64


def domain_fixtures():
    agents = load_agent_registry()['agents']
    capabilities = {'reported_source_revision': SOURCE, 'independent_verifier': 'UNCONFIGURED',
        'agents': [{'agent_id': row['id'], 'proven': {'level': 'L0', 'trust_state': 'UNPROVEN'},
                    'missing_cases': {}} for row in agents]}
    observed = {'task_id': TASK, 'revision': 1, 'execution_state': 'COMPLETED',
        'agent_ids': ['a20'], 'runtime': {'source_revision': SOURCE},
        'result_digest': {'algorithm': 'sha256', 'value': DIGEST},
        'metadata_digest': {'algorithm': 'sha256', 'value': 'c' * 64},
        'completed_at': '2026-10-07T04:00:00Z'}
    evidence = {'record_id': f'objective:{TASK}:r1', 'task_id': TASK, 'revision': 1,
        'source': 'PRIME_OBJECTIVE_STORE', 'integrity': 'VALID', 'currentness': 'CURRENT',
        'verification': 'UNVERIFIED', 'observed': observed}
    return {'/control/api/agent-capabilities': capabilities, '/control/api/jobs': {'jobs': []},
        '/control/api/evidence/from-objective/' + TASK: evidence}


@pytest.fixture
def mock_domains(monkeypatch):
    from app import semantic_fabric
    fixtures = domain_fixtures()
    calls = []
    def read(path, authorization):
        assert authorization == 'Bearer ' + TOKEN
        calls.append(path)
        return json.loads(json.dumps(fixtures[path]))
    def unavailable(_):
        raise SemanticError('PRIVATE_ENGINE_ERROR_SENTINEL')
    monkeypatch.setattr(preview, 'read_domain', read)
    monkeypatch.setattr(semantic_fabric, 'build_semantics', unavailable)
    monkeypatch.setenv('PRIME_GODS_EYE_PREVIEW_TASK_IDS', TASK)
    monkeypatch.setenv('PRIME_GODS_EYE_PREVIEW_REVISION', 'd' * 40)
    monkeypatch.setenv('PRIME_SPINE_TOKEN', TOKEN)
    monkeypatch.setattr(preview, '_LAST', None)
    monkeypatch.setattr(preview, '_AT', 0.0)
    monkeypatch.setattr(preview, '_LOCK', threading.BoundedSemaphore(1))
    return fixtures, calls


def test_actual_lens_digest_shape_and_seeded_result_binding_are_preserved(mock_domains):
    _, calls = mock_domains
    result = preview.collect('Bearer ' + TOKEN, protected_domains=True)
    assert calls == ['/control/api/agent-capabilities', '/control/api/jobs',
                     '/control/api/evidence/from-objective/' + TASK,
                     '/control/api/hf-observation?task_id=' + TASK]
    assert len(result['agents']) == 21
    assert result['results'][0]['task_id'] == TASK
    assert result['results'][0]['agent_id'] == 'a20'
    assert result['results'][0]['result_sha256'] == DIGEST
    assert result['results'][0]['verification'] == 'UNVERIFIED'
    assert result['certification']['l7_count'] == 0
    assert result['preview']['models_invoked'] == 0
    assert result['preview']['production_changed'] is False


@pytest.mark.parametrize('digest', [{'algorithm': 'md5', 'value': DIGEST},
    {'algorithm': 'sha256', 'value': 'not-a-digest'}, {'algorithm': 'sha256', 'value': False}, DIGEST])
def test_unsupported_digest_contract_does_not_create_an_accepted_digest(mock_domains, digest):
    fixtures, _ = mock_domains
    fixtures['/control/api/evidence/from-objective/' + TASK]['observed']['result_digest'] = digest
    result = preview.collect('Bearer ' + TOKEN, protected_domains=True)
    assert result['results'][0]['result_sha256'] is None


@pytest.mark.parametrize('field', ['task_id', 'observed_task_id'])
def test_wrong_task_evidence_is_rejected_before_capture(mock_domains, field):
    fixtures, _ = mock_domains
    evidence = fixtures['/control/api/evidence/from-objective/' + TASK]
    if field == 'task_id':
        evidence['task_id'] = OTHER
    else:
        evidence['observed']['task_id'] = OTHER
    with pytest.raises(ValueError, match='PREVIEW_TASK_EVIDENCE_BINDING_INVALID'):
        preview.collect('Bearer ' + TOKEN, protected_domains=True)


@pytest.mark.parametrize('identity', ['../private', TASK.upper(), TASK + '?token=private', 'https://attacker.invalid'])
def test_seed_cannot_select_an_arbitrary_transport_path(mock_domains, monkeypatch, identity):
    _, calls = mock_domains
    monkeypatch.setenv('PRIME_GODS_EYE_PREVIEW_TASK_IDS', identity)
    with pytest.raises(ValueError):
        preview.collect('Bearer ' + TOKEN, protected_domains=True)
    assert calls == ['/control/api/agent-capabilities', '/control/api/jobs']


def test_private_fields_and_missing_formal_engines_do_not_leak_or_fake_acceptance(mock_domains):
    fixtures, _ = mock_domains
    for value in fixtures.values():
        value['private'] = 'PRIVATE_DATA_SENTINEL'
    result = preview.collect('Bearer ' + TOKEN, protected_domains=True)
    public = json.dumps(result)
    assert 'PRIVATE_DATA_SENTINEL' not in public
    assert TOKEN not in public
    assert 'PRIVATE_ENGINE_ERROR_SENTINEL' not in public
    assert result['semantics']['status'] == 'UNAVAILABLE'
    assert result['runtime']['verification'] == 'UNVERIFIED'
    assert result['status'] == 'ISOLATED_LIVE_READ_ONLY_PREVIEW'


def test_authentication_precedes_network_reads_and_cache_access(mock_domains):
    _, calls = mock_domains
    preview.observation('Bearer ' + TOKEN)
    total = len(calls)
    with pytest.raises(Exception) as failure:
        preview.observation('Bearer wrong-synthetic-token')
    assert failure.value.status_code == 401
    assert len(calls) == total
    copy = preview.observation('Bearer ' + TOKEN)
    assert len(calls) == total
    copy['agents'].clear()
    assert len(preview.observation('Bearer ' + TOKEN)['agents']) == 21


def test_ordinary_preview_does_not_proxy_protected_certification_or_hf_reads(mock_domains):
    _, calls = mock_domains
    result = preview.collect('Bearer ' + TOKEN)
    assert calls == ['/control/api/jobs', '/control/api/evidence/from-objective/' + TASK]
    assert result['certification']['l7_count'] is None
    assert all(row['l7_status'] == 'UNKNOWN' for row in result['agents'])
    assert result['hugging_face']['registration_status'] == 'UNKNOWN'


def test_preview_cache_cannot_leak_explicit_bearer_projection_to_ordinary_read(mock_domains):
    explicit = preview.observation('Bearer ' + TOKEN, protected_domains=True)
    assert explicit['certification']['l7_count'] == 0
    ordinary = preview.observation('Bearer ' + TOKEN)
    assert ordinary['certification']['l7_count'] is None
    assert ordinary['protected_domain_access'] == 'NOT_REQUESTED'


def test_busy_collection_fails_closed_without_starting_parallel_reads(mock_domains):
    _, calls = mock_domains
    preview._LOCK.acquire()
    try:
        with pytest.raises(Exception) as failure:
            preview.observation('Bearer ' + TOKEN)
        assert failure.value.status_code == 503
        assert calls == []
    finally:
        preview._LOCK.release()


def test_transport_errors_are_sanitized_and_collection_lock_is_released(mock_domains, monkeypatch):
    def broken(*_):
        raise RuntimeError(TOKEN + ' PRIVATE_SOURCE_ERROR')
    monkeypatch.setattr(preview, 'read_domain', broken)
    with pytest.raises(Exception) as failure:
        preview.observation('Bearer ' + TOKEN)
    assert failure.value.status_code == 503
    assert failure.value.detail == 'Live source observation unavailable'
    assert preview._LOCK.acquire(blocking=False)
    preview._LOCK.release()


def test_loopback_reader_is_get_only_proxy_free_bounded_and_redirect_denied(monkeypatch):
    captured = {}
    class Result:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, bound):
            captured['bound'] = bound
            return b'{"status":"OBSERVED"}'
    class Opener:
        def open(self, request, timeout):
            captured['request'], captured['timeout'] = request, timeout
            return Result()
    def opener(*handlers):
        captured['handlers'] = handlers
        return Opener()
    monkeypatch.setattr(urllib.request, 'build_opener', opener)
    value = preview.read_domain('/control/api/agent-capabilities', 'Bearer ' + TOKEN)
    request = captured['request']
    assert request.full_url == 'http://127.0.0.1:8000/control/api/agent-capabilities'
    assert request.get_method() == 'GET'
    assert request.get_header('Authorization') == 'Bearer ' + TOKEN
    assert request.data is None
    assert captured['timeout'] == 2
    assert captured['bound'] == 1048577
    assert captured['handlers'][0].proxies == {}
    redirect = captured['handlers'][1]
    assert redirect.redirect_request(None, None, 307, '', {}, 'https://attacker.invalid') is None
    assert value == {'status': 'OBSERVED'}


@pytest.mark.parametrize('kind', ['http-failure', 'oversized', 'malformed-json'])
def test_reader_rejects_failed_oversized_and_malformed_responses_without_retry(monkeypatch, kind):
    status = 503 if kind == 'http-failure' else 200
    payload = {'http-failure': b'{}', 'oversized': b'x' * 1048577,
               'malformed-json': b'{not-json'}[kind]
    calls = []
    class Result:
        def __init__(self): self.status = status
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, _): return payload
    class Opener:
        def open(self, request, timeout):
            calls.append(request.get_method())
            return Result()
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *_: Opener())
    with pytest.raises(ValueError):
        preview.read_domain('/control/api/jobs', 'Bearer ' + TOKEN)
    assert calls == ['GET']


@pytest.mark.parametrize('path', ['https://attacker.invalid', '//attacker.invalid/path',
    '/control/api/jobs?target=private', '/control/api/jobs#secret', '/private',
    '/control/api/hf-observation?task_id=' + TASK + '&token=private',
    '/control/api/hf-observation?task_id=../private'])
def test_invalid_reader_destination_is_denied_before_any_transport(monkeypatch, path):
    def no_transport(*_):
        pytest.fail('No transport may be built for invalid destination')
    monkeypatch.setattr(urllib.request, 'build_opener', no_transport)
    with pytest.raises(ValueError, match='PREVIEW_DOMAIN_PATH_INVALID'):
        preview.read_domain(path, 'Bearer ' + TOKEN)


def authorize_fixture(request: Request, authorization: str | None = Header(None)):
    """Synthetic unit-test seam, never an enrolled Owner or production credential."""
    authenticate_owner(authorization)
    return authorization


def test_preview_routes_require_auth_do_not_mount_execution_and_expose_no_lifespan(mock_domains):
    _, calls = mock_domains
    app = preview.build_app(authorize_fixture)
    assert app.router.on_startup == []
    client = TestClient(app, base_url='http://127.0.0.1:18080')  # No lifespan context.
    try:
        for path in ['/control/gods-eye', '/control/gods-eye.js', '/control/gods-eye.css', '/control/api/gods-eye']:
            assert client.get(path).status_code == 401
        assert calls == []
        headers = {'Authorization': 'Bearer ' + TOKEN}
        snapshot = client.get('/control/api/gods-eye', headers=headers)
        assert snapshot.status_code == 200
        assert TOKEN not in snapshot.text
        assert snapshot.headers['cache-control'] == 'no-store'
        assert snapshot.headers['x-frame-options'] == 'DENY'
        assert "form-action 'none'" in snapshot.headers['content-security-policy']
        for path in ['/control/api/gods-eye', '/control/api/objectives', '/control/api/dispatch']:
            assert client.post(path, headers=headers, json={'objective': 'MUST NOT EXECUTE'}).status_code in {404, 405}
        assert client.get('/control/api/evidence/from-objective/' + OTHER, headers=headers).status_code == 404
        assert calls.count('/control/api/evidence/from-objective/' + TASK) == 1
        redirect = client.get('/control', headers=headers, follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers['location'] == 'http://127.0.0.1:8000/control'
        assert TOKEN not in redirect.text
    finally:
        client.close()


def test_only_preview_main_contains_production_import_and_binding_is_explicit_loopback():
    # Source check complements the mocked app; this test never imports the production entry/lifespan.
    source = Path(preview.__file__).read_text(encoding='utf-8')
    assert 'host=\'127.0.0.1\', port=18080' in source
    assert 'proxy_headers=False, access_log=False' in source
    assert '.lifespan' not in source
    assert 'POST' not in source
