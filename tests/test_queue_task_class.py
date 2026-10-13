"""The HTTP boundary must retain the classification used by HF admission."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import compute_queue_api
from app.job_queue import JobQueue, Provider

@pytest.fixture
def client(tmp_path,monkeypatch):
    queue=JobQueue(tmp_path/'queue.db')
    monkeypatch.setattr(compute_queue_api,'queue',queue)
    monkeypatch.setattr(compute_queue_api,'authorize',lambda _:None)
    monkeypatch.setattr(compute_queue_api,'providers',lambda:[Provider('test-hf','cloud','fixture',0,0,1)])
    import app.compute_catalog
    monkeypatch.setattr(app.compute_catalog,'load_catalog',lambda:[{'id':'test-hf','provider_kind':'huggingface'}])
    app=FastAPI();app.include_router(compute_queue_api.router)
    with TestClient(app) as http:
        yield http,queue

@pytest.mark.parametrize('task_class',['classification','planning'])
def test_http_cloud_submission_persists_qualified_task_class(client,task_class):
    http,queue=client
    response=http.post('/api/compute-queue/jobs',json={'agent':'a13','prompt':'Public synthetic exercise',
        'task_class':task_class,'allow_cloud':True,'data_classification':'CLOUD_PERMITTED',
        'preferred_provider':'test-hf','max_cost_usd':0.002,'max_retries':0})
    assert response.status_code==202
    assert response.json()['task_class']==task_class
    assert queue.get(response.json()['id'])['task_class']==task_class

def test_unrecognized_task_class_is_rejected_before_queue_write(client):
    http,queue=client
    response=http.post('/api/compute-queue/jobs',json={'agent':'a13','prompt':'Public synthetic exercise','task_class':'invented'})
    assert response.status_code==422
    assert queue.list()==[]

def test_omitted_task_class_preserves_auto_compatibility(client):
    http,queue=client
    response=http.post('/api/compute-queue/jobs',json={'agent':'a13','prompt':'Public synthetic exercise'})
    assert response.status_code==202
    assert queue.get(response.json()['id'])['task_class']=='auto'
