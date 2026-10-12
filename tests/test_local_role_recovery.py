import json,sqlite3
from pathlib import Path
import pytest
from tests.test_direct_execution import isolated,api


def test_explicit_registered_release_case_reaches_its_model_queue(api,monkeypatch):
    from app.agent_cert_role_review import canonical_case_spec
    from app import agent_dispatch_api
    from dataclasses import replace
    client,compute=api
    # Match the existing candidate's distinct NANO/MINI local configuration.
    local_backends=agent_dispatch_api.local_model_backends
    configured=replace(agent_dispatch_api.SETTINGS,fast_model='gemma3:1b',deep_model='gemma3:4b')
    monkeypatch.setattr(agent_dispatch_api,'local_model_backends',lambda:local_backends(configured))
    spec=canonical_case_spec('a29','responsibility.a29','role:normal')
    response=client.post('/api/agents/objectives',headers={'Authorization':'Bearer isolated-test-owner'},json=spec['request'])
    assert response.status_code==202,response.text
    step=response.json()['steps'][0]
    assert step['capability']=='responsibility.a29'
    assert 'dispatch' in step,step
    assert step['dispatch']['job']['agent']=='a29'
    assert compute.queue.get(step['dispatch']['job']['id'])['status']=='queued'


@pytest.mark.parametrize('failure',[False,True])
def test_real_local_result_usage_precedes_queue_completion(tmp_path,monkeypatch,failure):
    from app import compute_queue_api as compute,direct_stream
    from app.agent_dispatch_api import local_model_backends
    from app.job_queue import Provider
    backend=local_model_backends()[-1]
    monkeypatch.setattr(compute,'DATA',tmp_path)
    async def infer(*args,**kwargs):
        if failure:raise RuntimeError('private failure must not enter metrics')
        return {'result':'{"answer":42}','input_tokens':11,'output_tokens':7,'actual_cost_usd':0}
    monkeypatch.setattr(direct_stream,'infer',infer)
    job={'id':'test-local-attempt','agent':'a16','classification':'R0','task_class':'planning'}
    provider=Provider(backend.name,'local',backend.model,32768,0,1)
    if failure:
        with pytest.raises(RuntimeError):compute._execute(job,provider)
    else:assert compute._execute(job,provider)['input_tokens']==11
    with sqlite3.connect(tmp_path/'compute-ledger.db') as db:
        rows=db.execute('SELECT task_id,tier,tokens,cost,verified,details FROM reasoning_attempts').fetchall()
    assert len(rows)==1
    task,tier,tokens,cost,verified,raw=rows[0];details=json.loads(raw)
    assert task==job['id'] and tier==backend.tier.name and cost==0 and verified==0
    assert tokens==(None if failure else 18)
    assert details['success'] is (not failure)
    assert details['retries']==0 and details['provider']==backend.name
    assert 'private' not in raw and 'answer' not in raw
