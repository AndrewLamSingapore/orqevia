"""Authenticated, source-bound Evidence Lens projection of a real objective."""
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import evidence_lens_api, objective_api, production_entry

ORIGIN = 'http://127.0.0.1:8000'


@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-owner-token')
    return TestClient(production_entry.app,base_url=ORIGIN,client=('127.0.0.1',43000))


def _objective(client):
    response=client.post('/control/api/objectives',
                         json={'objective':'How many agents do you have?'},
                         headers={'Origin':ORIGIN})
    assert response.status_code==202, response.text
    return response.json()['id']


def test_authenticated_materialize_read_deduplicate_and_no_model_text(client,tmp_path):
    task_id=_objective(client)
    path=f'/control/api/evidence/from-objective/{task_id}'
    assert client.get(path).status_code==404
    assert not (tmp_path/'evidence-lens.db').exists()  # Read cannot initialize storage.
    assert client.post(path).status_code==403  # Same-origin mutation boundary.
    first=client.post(path,headers={'Origin':ORIGIN})
    assert first.status_code==201, first.text
    result=first.json()
    assert result['integrity']=='VALID' and result['currentness']=='CURRENT'
    assert result['verification']=='UNVERIFIED'  # Ledger integrity is not claim verification.
    assert result['result_state']=='COMPLETED'
    assert result['observed']['runtime']['source_revision']=='UNKNOWN'
    assert result['observed']['claim_verification']=='VERIFIED'
    assert result['proof']['producer']=='PRIME_OBJECTIVE_STORE'
    assert result['proof']['captured_at']
    assert result['proof']['runtime']==result['observed']['runtime']
    assert 'independent_claim_verification' in result['proof']['unproven']
    assert 'production_acceptance' in result['proof']['unproven']
    assert 'source_revision_binding' in result['proof']['unproven']
    assert result['proof']['currentness_basis']=='OBJECTIVE_SNAPSHOT_EQUALITY'
    assert result['proof']['time_freshness']=='UNKNOWN'
    assert 'time_freshness' in result['proof']['unproven']
    assert 'REGISTERED AGENTS: 21' not in first.text  # Digest/reference, not copied content.
    assert client.get(path).json()==result
    assert client.post(path,headers={'Origin':ORIGIN}).json()==result
    with sqlite3.connect(tmp_path/'evidence-lens.db') as db:
        assert db.execute('select count(*) from evidence_actions').fetchone()[0]==1
        assert db.execute('select count(*) from evidence_events').fetchone()[0]==2


def test_tamper_and_source_drift_never_appear_current(client,tmp_path):
    task_id=_objective(client)
    path=f'/control/api/evidence/from-objective/{task_id}'
    assert client.post(path,headers={'Origin':ORIGIN}).status_code==201
    with sqlite3.connect(tmp_path/'objectives.db') as db:
        db.execute('update objective_metadata set updated_at=? where task=?',
                   ('2099-01-01T00:00:00+00:00',task_id))
    stale=client.get(path).json()
    assert stale['integrity']=='VALID' and stale['currentness']=='STALE'
    assert client.post(path,headers={'Origin':ORIGIN}).json()['currentness']=='STALE'
    with sqlite3.connect(tmp_path/'evidence-lens.db') as db:
        db.execute('update evidence_events set event_digest=? where sequence=1',('0'*64,))
    tampered=client.get(path).json()
    assert tampered['integrity']=='INVALID'
    assert tampered['currentness']=='UNKNOWN'
    assert client.post(path,headers={'Origin':ORIGIN}).status_code==409


def test_reported_runtime_identifiers_are_not_independent_binding(client,monkeypatch):
    monkeypatch.setenv('PRIME_RUNTIME_REVISION','a'*40)
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST','sha256:'+'b'*64)
    task_id=_objective(client)
    response=client.post(f'/control/api/evidence/from-objective/{task_id}',headers={'Origin':ORIGIN})
    assert response.status_code==201, response.text
    result=response.json()
    assert result['observed']['runtime']['source_revision']=='a'*40
    assert result['observed']['runtime']['image_digest']=='sha256:'+'b'*64
    assert {'source_revision_binding','runtime_image_binding'} <= set(result['proof']['unproven'])
    assert result['verification']=='UNVERIFIED'


def test_deleted_entire_event_chain_is_invalid_not_current(client,tmp_path):
    task_id=_objective(client)
    path=f'/control/api/evidence/from-objective/{task_id}'
    assert client.post(path,headers={'Origin':ORIGIN}).status_code==201
    with sqlite3.connect(tmp_path/'evidence-lens.db') as db:
        db.execute('delete from evidence_events')
    missing_chain=client.get(path).json()
    assert missing_chain['integrity']=='INVALID'
    assert missing_chain['currentness']=='UNKNOWN'
    assert client.post(path,headers={'Origin':ORIGIN}).status_code==409


@pytest.mark.parametrize('field,value',[
    ('observation_source','OTHER_SYSTEM'),
    ('actor',{'type':'SYSTEM','id':'OTHER_SYSTEM'}),
    ('authority',{'scope':'objective.result.projection','source':'OTHER_SYSTEM'}),
    ('inputs',[{'task_id':'wrong-task','revision':0}]),
])
def test_valid_internal_chain_cannot_launder_wrong_producer(client,field,value):
    task_id=_objective(client)
    path=f'/control/api/evidence/from-objective/{task_id}'
    assert client.post(path,headers={'Origin':ORIGIN}).status_code==201
    record_id=f'objective:{task_id}:r0'
    ledger=evidence_lens_api._ledger()
    def change(envelope):
        if field=='observation_source':
            envelope['observations'][0]['source']=value
        else:
            envelope[field]=value
    ledger.mutate(record_id,namespace=evidence_lens_api.NAMESPACE,
                  event_type='TEST_WRONG_PROVENANCE',idempotency_key=f'test:{field}:{task_id}',apply=change)
    assert ledger.verify_chain(record_id,namespace=evidence_lens_api.NAMESPACE)['verdict']=='VALID'
    result=client.get(path).json()
    assert result['integrity']=='INVALID'
    assert result['currentness']=='UNKNOWN'
    assert 'source' not in result


def test_failed_execution_remains_failed_in_ledger(client,tmp_path):
    task_id=str(uuid.uuid4())
    with objective_api.connect() as db:
        db.execute('insert into objectives values(?,?,?,?)',
                   (task_id,'digest','submitted',json.dumps([{'capability':'responsibility.a02',
                     'state':'blocked','reason':'NO_BACKEND'}])))
        db.execute('insert into objective_metadata values(?,?,?,?)',
                   (task_id,0,'2026-10-06T00:00:00+00:00','2026-10-06T00:00:01+00:00'))
    path=f'/control/api/evidence/from-objective/{task_id}'
    response=client.post(path,headers={'Origin':ORIGIN})
    assert response.status_code==201, response.text
    assert response.json()['result_state']=='COMPLETED_WITH_FAILURES'
    assert response.json()['verification']=='UNVERIFIED'
    assert 'production_acceptance' in response.json()['proof']['unproven']
    with sqlite3.connect(tmp_path/'evidence-lens.db') as db:
        envelope=json.loads(db.execute('select envelope_json from evidence_actions').fetchone()[0])
    assert envelope['status']=='FAILED'
    assert envelope['verification']['state']=='UNVERIFIED'


def test_parallel_duplicate_capture_is_one_logical_record(client,tmp_path):
    task_id=_objective(client)
    path=f'/control/api/evidence/from-objective/{task_id}'
    def capture(_):
        worker=TestClient(production_entry.app,base_url=ORIGIN,client=('127.0.0.1',43000))
        return worker.post(path,headers={'Origin':ORIGIN})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(capture,range(4)))
    assert [response.status_code for response in responses]==[201]*4
    assert all(response.json()['integrity']=='VALID' for response in responses)
    with sqlite3.connect(tmp_path/'evidence-lens.db') as db:
        assert db.execute('select count(*) from evidence_actions').fetchone()[0]==1
        assert db.execute('select count(*) from evidence_events').fetchone()[0]==2


def test_untrusted_peer_and_invalid_task_are_rejected(client):
    assert client.get('/control/api/evidence/from-objective/not-a-uuid').status_code==404
    remote=TestClient(production_entry.app,base_url=ORIGIN,client=('192.0.2.10',43000))
    assert remote.get('/control/api/evidence/from-objective/not-a-uuid').status_code==403
    assert remote.post('/control/api/evidence/from-objective/not-a-uuid',
                       headers={'Origin':ORIGIN}).status_code==403


def test_unknown_read_does_not_initialize_objective_or_lens_storage(client,tmp_path):
    unknown=str(uuid.uuid4())
    response=client.get('/control/api/evidence/from-objective/'+unknown)
    assert response.status_code==404
    assert not (tmp_path/'objectives.db').exists()
    assert not (tmp_path/'evidence-lens.db').exists()


def test_owner_control_exposes_explicit_capture_and_read_only_proof(client):
    page=client.get('/control')
    script=client.get('/control/app.js')
    assert page.status_code==200 and script.status_code==200
    assert 'id="what-happened"' in page.text
    assert 'id="record-proof"' in page.text
    assert 'id="prove-it"' in page.text
    assert 'Record proof explicitly' in script.text
    assert "response.status===404 && method==='prove'" in script.text
    assert "'Objective not found.'" in script.text
    assert "el('record-proof').onclick=()=>lens('record')" in script.text
    assert "el('prove-it').onclick=()=>lens('prove')" in script.text
    assert 'innerHTML' not in script.text
    assert 'Evidence producer:' in script.text
    assert 'Not proven:' in script.text
    assert 'Time freshness:' in script.text
    source=Path(production_entry.__file__).with_name('production_control.js').read_text(encoding='utf-8')
    assert "method==='record' ? {method:'POST'" in source
    assert "method==='happened' ? 'objectives/' : 'evidence/from-objective/'" in source


def test_one_shot_live_canary_records_only_unverified_synthetic_proof(client, monkeypatch):
    from scripts import lens_live_canary

    def local_transport(base, method, path, *, payload=None, origin=None):
        assert base == ORIGIN
        headers = {'Origin': origin} if origin else {}
        response = client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.content

    monkeypatch.setattr(lens_live_canary, '_request', local_transport)
    result = lens_live_canary.run(ORIGIN)
    assert result['integrity'] == 'VALID'
    assert result['currentness'] == 'CURRENT'
    assert result['verification'] == 'UNVERIFIED'
    assert result['model_invoked'] is False
    assert result['scope'] == 'ONE_DETERMINISTIC_LOCAL_SYNTHETIC_OBJECTIVE'
    readback = client.get('/control/api/evidence/from-objective/' + result['task_id'])
    assert readback.status_code == 200
    assert readback.json()['record_id'] == result['record_id']
    assert readback.json()['proof']['time_freshness'] == 'UNKNOWN'
