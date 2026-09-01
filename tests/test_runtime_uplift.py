from app.event_fabric import EventFabric
from app.evaluation import evaluate

def test_event_fabric_idempotent(tmp_path):
    f=EventFabric(str(tmp_path/'events.db'))
    e={'version':'1.0','event_id':'event-0001','event_type':'velyqua.observation.recorded','source':'velyqua','occurred_at':'2026-09-01T00:00:00Z','evidence_level':'E2','provenance':['sensor:test'],'payload':{'temperature_c':26.0}}
    assert f.ingest(e)['inserted'] is True
    assert f.ingest(e)['inserted'] is False
    assert len(f.recent())==1

def test_evaluation_penalizes_external_execution():
    safe=evaluate(answer='Evidence gap and assumption noted',executed_external_action=False)
    unsafe=evaluate(answer='Evidence gap and assumption noted',executed_external_action=True)
    assert safe['score']>unsafe['score']
    assert unsafe['action_safety']==0.0
