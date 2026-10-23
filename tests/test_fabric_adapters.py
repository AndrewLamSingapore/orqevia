"""Real numerical/event persistence tests; cloud rows are declared fixtures."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json

import pytest

from app import fabric_adapters as fa
from app.job_queue import JobQueue, Provider


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    from app import runtime, compute_queue_api
    from app.event_fabric import EventFabric
    events = EventFabric(str(tmp_path/'events.db'))
    queue = JobQueue(tmp_path/'jobs.db')
    monkeypatch.setattr(runtime,'events',events)
    monkeypatch.setattr(compute_queue_api,'queue',queue)
    return events,queue


def complete(queue):
    job = queue.submit(agent='a01',prompt='Explicit fixture output',max_retries=0)
    queue.claim('fixture',[Provider('ollama-fast','local','fixture',32768,0,1)])
    return queue.finish(job['id'],result='An actual fixture execution, not a production claim.')


def test_event_projects_replays_reads_back_and_recovers_failure(local, monkeypatch):
    events, queue = local
    job = complete(queue)
    with pytest.raises(ValueError):
        fa.event_observation()
    first = fa.publish_event(job)
    assert first['inserted'] and first['projected']
    second = fa.publish_event(job)
    assert not second['inserted'] and all(p['replayed'] for p in second['projections'])
    assert fa.event_observation()['projectors_verified'] == 4
    with events.memory.connect() as db:
        assert db.execute('SELECT count(*) FROM episodic_memory').fetchone()[0] == 1
    with events.connect() as db:
        db.execute("UPDATE event_projections SET status='failed' WHERE projector='semantic_graph'")
    with pytest.raises(ValueError):
        fa.event_observation()
    assert fa.publish_event(job)['projected']
    assert fa.event_observation()['persistence_integrity']=='PASS'
    forged = {**job,'result':'Changed after completion'}
    with pytest.raises(ValueError):
        fa.publish_event(forged)


def test_event_rejects_forged_persisted_binding(local):
    events, queue = local
    fa.publish_event(complete(queue))
    with events.connect() as db:
        row = db.execute('SELECT event_id,payload_json FROM portfolio_events').fetchone()
        payload=json.loads(row['payload_json']);payload['result_sha256']='f'*64
        db.execute('UPDATE portfolio_events SET payload_json=? WHERE event_id=?',(json.dumps(payload),row['event_id']))
    with pytest.raises(ValueError):
        fa.event_observation()


def test_reviewed_reference_actual_inference_reload_and_no_agent_authority(monkeypatch):
    monkeypatch.setattr(fa,'_MLP',None)
    first=fa.mlp_infer([{'x':.5},{'x':1.5}],'fixture-reference')
    assert first['output'][0]==pytest.approx(.25,abs=.3)
    assert first['output'][1]==pytest.approx(2.25,abs=.6)
    assert first['grants_agent_authority'] is False and first['automatic_training'] is False
    fabric=fa.get_mlp();model=next(iter(fabric.models.values()))
    with pytest.raises(PermissionError):
        fabric.infer_for_agent('a12',model['model_id'],[{'x':.5}],trace_id='fixture-agent',
            certification={},capability_decision={},runtime_healthy=True)
    monkeypatch.setattr(fa,'_MLP',None)
    assert fa.mlp_infer([{'x':.5},{'x':1.5}],'fixture-reload')['output']==first['output']
    assert fa.mlp_observation()['qualification']=='NO_DOMAIN_OR_AGENT_CERTIFICATION'


@pytest.mark.parametrize('rows',[[{'x':True}],[{'x':float('nan')}],[{'x':3.0}],[{'z':1.0}],[],[{'x':.5}]*33])
def test_reference_rejects_bad_inputs(rows):
    with pytest.raises(ValueError):
        fa.mlp_infer(rows,'fixture-invalid')


def test_unreviewed_or_tampered_artifact_cannot_register(tmp_path,monkeypatch):
    content=fa.REFERENCE_PATH.read_bytes()
    forged=tmp_path/'forged.json';forged.write_bytes(content+b' ')
    monkeypatch.setattr(fa,'_MLP',None)
    monkeypatch.setattr(fa,'REFERENCE_PATH',forged)
    with pytest.raises(ValueError):
        fa.get_mlp()


def test_hf_observer_uses_actual_persisted_queue_contract_and_freshness(local):
    _,queue=local
    # Explicit SQL fixture, no provider call and no production success claim.
    job=complete(queue)
    now=datetime.now(timezone.utc).isoformat()
    with queue.connect() as db:
        db.execute("UPDATE compute_jobs SET provider='hf-fixture',model='fixture-model',allow_cloud=1,data_classification='CLOUD_PERMITTED',max_cost_usd=.01,actual_cost_usd=.00001,completed_at=? WHERE id=?",(now,job['id']))
    entry={'enabled':True,'id':'hf-fixture','model':'fixture-model'}
    assert fa.hf_observation(entry)['probe_spends_money'] is False
    for assignment in ["actual_cost_usd=NULL","actual_cost_usd=.1","data_classification='LOCAL_ONLY'","status='failed'"]:
        with queue.connect() as db:
            db.execute('UPDATE compute_jobs SET '+assignment+' WHERE id=?',(job['id'],))
        with pytest.raises(ValueError):
            fa.hf_observation(entry)
        with queue.connect() as db:
            db.execute("UPDATE compute_jobs SET actual_cost_usd=.00001,data_classification='CLOUD_PERMITTED',status='completed' WHERE id=?",(job['id'],))
    with queue.connect() as db:
        db.execute('UPDATE compute_jobs SET completed_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),job['id']))
    with pytest.raises(ValueError):
        fa.hf_observation(entry)
    with pytest.raises(ValueError):
        fa.hf_observation({**entry,'enabled':False})
