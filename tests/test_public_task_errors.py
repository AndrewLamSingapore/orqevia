import json
import pytest
from fastapi import HTTPException
from app.public_task_errors import public_task,publishable_task_artifact

FAKE='fixture-credential-value-not-a-real-secret'

def snapshot():
    return {'id':'task','state':'COMPLETED_WITH_FAILURES','steps':[{'job':{'id':'job','status':'failed',
        'error':'Provider URL https://example.invalid/?key='+FAKE,'result':'Legitimate result text'},
        'reason':'Exception containing '+FAKE}]}

def test_projection_does_not_mutate_private_record_or_result():
    original=snapshot();projected=public_task(original)
    assert FAKE not in json.dumps(projected)
    assert FAKE in json.dumps(original)
    assert projected['steps'][0]['job']['result']=='Legitimate result text'
    assert projected['steps'][0]['job']['error']=='EXECUTION_FAILED'

def test_historical_artifact_hidden_without_rewriting_bytes():
    raw=json.dumps(snapshot()).encode();meta={'provenance':'Source-labelled governed objective results'}
    assert not publishable_task_artifact(meta,raw)
    assert FAKE.encode() in raw
    assert publishable_task_artifact(meta,json.dumps(public_task(snapshot())).encode())

def test_unrelated_artifact_content_not_scrubbed():
    assert publishable_task_artifact({'provenance':'User document'},json.dumps({'error':'legitimate discussion'}).encode())

def test_successful_model_result_materializes_as_markdown(tmp_path,monkeypatch):
    from app import artifact_delivery
    task={'id':'task','revision':0,'state':'COMPLETED',
        'execution_metadata':{'task_id':'task','revision':0,'state':'COMPLETED','created_at':None,
            'started_at':None,'completed_at':None,'runtime':{'host_id':'UNKNOWN','source_revision':'UNKNOWN'}},
        'steps':[{'revision':0,'capability':'responsibility.a02',
        'job':{'status':'completed','result':'# 中文结果\n\n- 第一项'}}]}
    class DB:
        def execute(self,*args):return self
        def rollback(self):pass
        def close(self):pass
    monkeypatch.setattr(artifact_delivery,'authenticate_owner',lambda *_:None)
    monkeypatch.setattr(artifact_delivery.objective_api,'connect',DB)
    monkeypatch.setattr(artifact_delivery.objective_api,'get',lambda *_:task)
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    first=artifact_delivery.create_task_artifact('task','fixture')
    again=artifact_delivery.create_task_artifact('task','fixture')
    metadata,raw=artifact_delivery.ArtifactFactory(tmp_path/'artifacts').retrieve(first['artifact_id'])
    assert first['artifact_id']==again['artifact_id']
    rendered=raw.decode()
    assert metadata['type']=='markdown'
    assert '## Authoritative execution metadata' in rendered
    assert '- Task UUID: `task`' in rendered
    assert '## Model-generated content\n# 中文结果\n\n- 第一项\n' in rendered
    assert publishable_task_artifact(metadata,raw)

def test_failed_turn_without_text_remains_truthful_json_snapshot(tmp_path,monkeypatch):
    from app import artifact_delivery
    task={'id':'task','revision':0,'state':'COMPLETED_WITH_FAILURES','steps':[{'revision':0,'state':'blocked'}]}
    class DB:
        def execute(self,*args):return self
        def rollback(self):pass
        def close(self):pass
    monkeypatch.setattr(artifact_delivery,'authenticate_owner',lambda *_:None)
    monkeypatch.setattr(artifact_delivery.objective_api,'connect',DB)
    monkeypatch.setattr(artifact_delivery.objective_api,'get',lambda *_:task)
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    item=artifact_delivery.create_task_artifact('task','fixture')
    assert item['type']=='json'

@pytest.mark.parametrize('surface',['interface','owner'])
def test_download_denies_historical_unsafe_snapshot(monkeypatch,surface):
    from app import interface_node,artifact_delivery
    module=interface_node if surface=='interface' else artifact_delivery
    class Factory:
        def __init__(self,*args):pass
        def retrieve(self,*args):return {'task_id':'task','provenance':'Source-labelled governed objective results'},json.dumps(snapshot()).encode()
    monkeypatch.setattr(module,'ArtifactFactory',Factory)
    if surface=='interface':
        monkeypatch.setattr(module,'client_identity',lambda *args:'dell')
        monkeypatch.setattr(module,'own_task',lambda *args:None)
        call=lambda:module.artifact('a'*32,'dell','fixture-auth')
    else:
        monkeypatch.setattr(module,'authenticate_owner',lambda *args:None)
        call=lambda:module.retrieve('a'*32,'fixture-auth')
    with pytest.raises(HTTPException) as error:call()
    assert error.value.status_code==404
    assert FAKE not in str(error.value.detail)

def test_objective_status_projects_stored_job_error(monkeypatch):
    from app import objective_api
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda *args:None)
    class Cursor:
        def fetchone(self):return ('submitted',json.dumps([{'dispatch':{'job':{'id':'job'}}}]))
        def fetchall(self):return []  # Original task has no continuation turns.
    class DB:
        def execute(self,*args):return Cursor()
        def close(self):pass
    monkeypatch.setattr(objective_api,'connect',DB)
    monkeypatch.setattr(objective_api.compute_queue_api.queue,'get',lambda _:snapshot()['steps'][0]['job'])
    value=objective_api.get('task','fixture-auth')
    assert value['state']=='COMPLETED_WITH_FAILURES'
    assert value['steps'][0]['job']['error']=='EXECUTION_FAILED'
    assert FAKE not in json.dumps(value)
