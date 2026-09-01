from app.event_fabric import EventFabric
from app.evaluation import evaluate

def test_event_fabric_idempotent(tmp_path):
    f=EventFabric(str(tmp_path/'events.db'))
    e={'version':'1.0','event_id':'event-0001','event_type':'velyqua.observation.recorded','source':'velyqua','occurred_at':'2026-09-01T00:00:00Z','evidence_level':'E2','provenance':['sensor:test'],'payload':{'temperature_c':26.0}}
    first=f.ingest(e)
    assert first['inserted'] is True and first['projected'] is True
    replay=f.ingest(e)
    assert replay['inserted'] is False
    assert all(item['replayed'] for item in replay['projections'])
    assert len(f.recent())==1
    assert f.reviews()[0]['status']=='pending'
    assert f.graph()[0]['last_event_id']=='event-0001'
    assert f.memory.recent_episodes()[0]['source']=='portfolio:velyqua'

def test_event_fabric_rejects_conflicting_idempotency_key(tmp_path):
    f=EventFabric(str(tmp_path/'events.db'))
    e={'version':'1.0','event_id':'event-0001','event_type':'velyqua.observation.recorded','source':'velyqua','occurred_at':'2026-09-01T00:00:00Z','evidence_level':'E2','provenance':['sensor:test'],'payload':{'temperature_c':26.0}}
    f.ingest(e)
    changed={**e,'payload':{'temperature_c':99.0}}
    import pytest
    with pytest.raises(ValueError,match='different canonical event'):f.ingest(changed)

def test_evaluation_penalizes_external_execution():
    safe=evaluate(answer='Evidence gap and assumption noted',executed_external_action=False)
    unsafe=evaluate(answer='Evidence gap and assumption noted',executed_external_action=True)
    assert safe['score']>unsafe['score']
    assert unsafe['action_safety']==0.0
