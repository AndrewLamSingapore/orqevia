import hashlib
import json
import os
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import interface_contract as contract
from app.artifact_factory import ArtifactFactory


class ContractTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(os.environ['PRIME_DATA_DIR']).parent / ('interface-case-' + uuid.uuid4().hex)
        fixture.mkdir(parents=True)
        self.tmp = SimpleNamespace(name=str(fixture))
        self.policies = {name: {'token_sha256': hashlib.sha256(name.encode()).hexdigest(),
            'expires_at': time.time() + 300, 'capabilities': ['identity.read', 'objective.submit',
                'task.read', 'task.cancel', 'artifact.read']} for name in ('dell', 'other')}
        self.env = patch.dict(os.environ, {'PRIME_DATA_DIR': self.tmp.name,
            'PRIME_SPINE_TOKEN': 'fixture-only', 'PRIME_INTERFACE_SPKI_SHA256': 'a' * 64,
            'PRIME_INTERFACE_HOST_ID': 'ABEX-TEST',
            'PRIME_INTERFACE_CLIENTS_JSON': json.dumps(self.policies)})
        self.env.start()
        app = FastAPI()
        app.include_router(contract.router)
        app.include_router(contract.node.router)
        # Explicit ASGI fixture: no TLS socket, server, credential or network changes.
        self.client = TestClient(app, base_url='https://testserver')
        self.headers = {'X-Client-ID': 'dell', 'Authorization': 'Bearer dell'}
        self.sub = patch.object(contract.node.objective_api, 'submit', return_value={'id': 'task-fixture'})
        self.dispatch = self.sub.start()
        self.get = patch.object(contract.node.objective_api, 'get', return_value={
            'id': 'task-fixture', 'state': 'COMPLETED', 'steps': []})
        self.get.start()

    def tearDown(self):
        self.get.stop()
        self.sub.stop()
        self.client.close()
        self.env.stop()
        # Retain disposable fixtures as test evidence; no recursive deletion.

    def submit(self):
        return self.client.post('/interface/v1/objectives', headers=self.headers,
            json={'objective': 'fixture supplied facts', 'idempotency_key': 'one'})

    def test_identity_transport_pin_auth_scope(self):
        assert self.client.get('/interface/v1/identity', headers=self.headers).json()['role'] == 'AUTHORITATIVE_PRIME_HOST'
        assert self.client.get('http://testserver/interface/v1/identity', headers={**self.headers, 'X-Forwarded-Proto': 'https'}).status_code == 426
        assert self.client.get('/interface/v1/identity').status_code == 401
        with patch.dict(os.environ, {'PRIME_INTERFACE_SPKI_SHA256': ''}):
            assert self.client.get('/interface/v1/identity', headers=self.headers).status_code == 503
        self.policies['dell']['expires_at'] = time.time() - 1
        with patch.dict(os.environ, {'PRIME_INTERFACE_CLIENTS_JSON': json.dumps(self.policies)}):
            assert self.submit().status_code == 403
            assert self.client.get('/api/interface/v1/health', headers=self.headers).status_code == 403
        self.policies['dell']['expires_at'] = time.time() + 300
        self.policies['dell']['capabilities'] = ['identity.read']
        with patch.dict(os.environ, {'PRIME_INTERFACE_CLIENTS_JSON': json.dumps(self.policies)}):
            body = {'objective': 'fixture', 'idempotency_key': 'scoped'}
            for prefix in ('/interface/v1', '/api/interface/v1'):
                assert self.client.post(prefix + '/objectives', headers=self.headers, json=body).status_code == 403

    def test_explicit_runtime_identity_has_honest_unknown_defaults(self):
        with patch.dict(os.environ, {'PRIME_INTERFACE_RUNTIME_VERSION': 'UNKNOWN', 'PRIME_INTERFACE_CANDIDATE_STATUS': 'UNKNOWN'}):
            value=self.client.get('/interface/v1/identity',headers=self.headers).json()
            assert value['runtime_version']=='UNKNOWN' and value['candidate_status']=='UNKNOWN'
        with patch.dict(os.environ, {'PRIME_INTERFACE_RUNTIME_VERSION': 'prime-next.20260914', 'PRIME_INTERFACE_CANDIDATE_STATUS': 'QUALIFICATION_RUNTIME'}):
            value=self.client.get('/interface/v1/identity',headers=self.headers).json()
            assert value['runtime_version']=='prime-next.20260914' and value['candidate_status']=='QUALIFICATION_RUNTIME'
        with patch.dict(os.environ, {'PRIME_INTERFACE_RUNTIME_VERSION': 'https://private.invalid/fixture', 'PRIME_INTERFACE_CANDIDATE_STATUS': 'invented'}):
            value=self.client.get('/interface/v1/identity',headers=self.headers).json()
            assert value['runtime_version']=='UNKNOWN' and value['candidate_status']=='UNKNOWN'

    def test_shared_idempotency_ownership_snapshot_cancel(self):
        assert self.submit().status_code == 202
        assert self.submit().json()['idempotent_replay']
        assert self.dispatch.call_count == 1
        changed = self.client.post('/interface/v1/objectives', headers=self.headers,
            json={'objective': 'changed', 'idempotency_key': 'one'})
        assert changed.status_code == 409
        other = {'X-Client-ID': 'other', 'Authorization': 'Bearer other'}
        for suffix in ('', '/events', '/artifacts'):
            assert self.client.get('/interface/v1/tasks/task-fixture' + suffix, headers=other).status_code == 404
        response = self.client.get('/interface/v1/tasks/task-fixture/events', headers=self.headers)
        assert response.status_code == 200 and 'task.status' in response.text
        cursor = response.text.splitlines()[0][4:]
        assert self.client.get('/interface/v1/tasks/task-fixture/events', headers={**self.headers, 'Last-Event-ID': cursor}).text == ''
        assert self.client.post('/interface/v1/tasks/task-fixture/cancel', headers=self.headers).status_code == 200

    def test_artifact_integrity_and_cross_client_isolation(self):
        self.submit()
        factory = ArtifactFactory(Path(self.tmp.name) / 'artifacts')
        item = factory.create(kind='json', content='{"fixture":true}', task_id='task-fixture', creator='fixture', provenance='test')
        listing = self.client.get('/interface/v1/tasks/task-fixture/artifacts', headers=self.headers).json()
        assert any(row['sha256'] == item['sha256'] for row in listing['artifacts'])
        assert 'location' not in listing['artifacts'][0]
        path = '/interface/v1/artifacts/' + item['artifact_id']
        response = self.client.get(path, headers=self.headers)
        assert hashlib.sha256(response.content).hexdigest() == response.headers['X-Artifact-SHA256']
        assert self.client.get(path, headers={'X-Client-ID': 'other', 'Authorization': 'Bearer other'}).status_code == 404
        (factory.root / item['artifact_id'] / item['location']).write_text('tamper')
        assert self.client.get(path, headers=self.headers).status_code == 404

    def test_terminal_artifact_materializes_once_through_adopted_get(self):
        self.submit()
        url = '/interface/v1/tasks/task-fixture/artifacts'
        first = self.client.get(url, headers=self.headers)
        assert first.status_code == 200, first.text
        items = first.json()['artifacts']
        assert len(items) == 1
        again = self.client.get(url, headers=self.headers).json()['artifacts']
        assert again == items
        downloaded = self.client.get('/interface/v1/artifacts/' + items[0]['artifact_id'], headers=self.headers)
        assert downloaded.json()['state'] == 'COMPLETED'
        assert hashlib.sha256(downloaded.content).hexdigest() == items[0]['sha256']

    def test_running_task_does_not_materialize_placeholder(self):
        self.submit()
        with patch.object(contract.node.objective_api, 'get', return_value={
                'id': 'task-fixture', 'state': 'RUNNING', 'steps': []}):
            result = self.client.get('/interface/v1/tasks/task-fixture/artifacts', headers=self.headers)
        assert result.status_code == 200 and result.json()['artifacts'] == []

    def test_canonical_dell_identity_and_header_authentication(self):
        headers = {'X-Jarvis-Client-ID': 'dell', 'Authorization': 'Bearer dell'}
        with patch.dict(os.environ, {'PRIME_INTERFACE_PUBLIC_KEY': 'fixture-public-SPKI'}):
            response = self.client.get('/interface/v1/identity', headers=headers)
            assert response.status_code == 200
            body = response.json()
            canonical = {key: body[key] for key in ('hostname', 'role', 'protocolVersion', 'publicKey')}
            assert canonical == {'hostname': 'ABEX-TEST', 'role': 'AUTHORITATIVE_PRIME',
                'protocolVersion': '1', 'publicKey': 'fixture-public-SPKI'}
            assert body['identity_sha256'] == hashlib.sha256(json.dumps(canonical,
                separators=(',', ':')).encode()).hexdigest().upper()
            assert self.client.get('/interface/v1/identity', headers={**headers, 'X-Client-ID': 'other'}).status_code == 400
            assert self.client.get('/interface/v1/identity', headers={**headers, 'Authorization': 'Bearer wrong'}).status_code == 401
        with patch.dict(os.environ, {'PRIME_INTERFACE_PUBLIC_KEY': ''}):
            assert self.client.get('/interface/v1/identity', headers=headers).status_code == 503
        with patch.dict(os.environ, {'PRIME_INTERFACE_HOST_ID': ''}):
            assert self.client.get('/interface/v1/identity', headers=headers).status_code == 503

    def test_canonical_dell_objective_task_events_and_artifact(self):
        headers = {'X-Jarvis-Client-ID': 'dell', 'Authorization': 'Bearer dell', 'Idempotency-Key': 'dell-fixture-one'}
        response = self.client.post('/interface/v1/objectives', headers=headers, json={'objective': 'fixture supplied facts'})
        assert response.status_code == 202 and response.json()['taskId'] == 'task-fixture'
        assert self.client.post('/interface/v1/objectives', headers=headers,
            json={'objective': 'fixture supplied facts'}).json()['idempotent_replay']
        assert self.dispatch.call_count == 1
        assert self.client.post('/interface/v1/objectives', headers=headers,
            json={'objective': 'fixture', 'idempotency_key': 'different'}).status_code == 400
        assert self.client.post('/interface/v1/objectives', headers=headers, json={}).status_code == 422
        assert self.client.get('/interface/v1/tasks/task-fixture', headers=headers).json()['taskId'] == 'task-fixture'
        sse = self.client.get('/interface/v1/tasks/task-fixture/events', headers=headers).text
        assert '"taskId":"task-fixture"' in sse and 'event: task.status' not in sse
        items = self.client.get('/interface/v1/tasks/task-fixture/artifacts', headers=headers).json()['artifacts']
        assert items[0]['artifactId'] == items[0]['artifact_id']
        downloaded = self.client.get('/interface/v1/artifacts/' + items[0]['artifactId'], headers=headers)
        assert hashlib.sha256(downloaded.content).hexdigest() == downloaded.headers['x-artifact-sha256']
        assert self.client.post('/interface/v1/tasks/task-fixture/cancel', headers=headers).json()['state'] == 'WAITING'
        with patch.object(contract.node.objective_api, 'get', return_value={'id': 'task-fixture', 'state': 'COMPLETED_WITH_FAILURES'}):
            assert self.client.get('/interface/v1/tasks/task-fixture', headers=headers).json()['state'] == 'FAILED'

    def test_canonical_health_retains_explicit_scope(self):
        headers = {'X-Jarvis-Client-ID': 'dell', 'Authorization': 'Bearer dell'}
        assert self.client.get('/interface/v1/health', headers=headers).status_code == 403
        self.policies['dell']['capabilities'].append('health.read')
        with patch.dict(os.environ, {'PRIME_INTERFACE_CLIENTS_JSON': json.dumps(self.policies)}), patch.object(contract.node, 'health', return_value={'state': 'READY'}) as health:
            assert self.client.get('/interface/v1/health', headers=headers).json()['state'] == 'READY'
            health.assert_called_once_with('dell', 'Bearer dell')

    def test_real_objective_store_concurrent_materialization_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        self.submit()
        db = contract.node.objective_api.connect()
        db.execute('INSERT INTO objectives VALUES(?,?,?,?)', ('task-fixture', 'fixture', 'submitted', '[]'))
        db.commit()
        db.close()
        self.get.stop()
        url = '/interface/v1/tasks/task-fixture/artifacts'
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.client.get(url, headers=self.headers), range(3)))
        assert all(result.status_code == 200 for result in results), [result.text for result in results]
        ids = [result.json()['artifacts'][0]['artifact_id'] for result in results]
        assert len(set(ids)) == 1


if __name__ == '__main__':
    unittest.main()
