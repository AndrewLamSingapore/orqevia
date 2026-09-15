import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.provider_runtime import ModelSpec,Chunk,Usage,ProviderFailure
from app.reasoning_budgets import select_budget,verify_reserved_cost

MODEL=ModelSpec('fixture','fixture','MINI',4096,128,Decimal('1'),Decimal('2'))

def fixture(monkeypatch, *, extension=None, reserve=.01, prompt='safe fixture', mode='success'):
    from app import cloud_execution as cloud
    calls=[];receipts=[];metrics=[]
    policy={'output_tokens':8,'context_tokens':256,'timeout_seconds':.5,
            'extensions':{'reviewed':{'output_tokens':16,'context_tokens':512,'timeout_seconds':1}}}
    entry=dict(id='fixture',model='fixture',tier='MINI',location='cloud',enabled=True,context_tokens=4096,output_tokens=128,
               input_usd_million='1',output_usd_million='2',endpoint='https://fixture.invalid',secret_ref='fixture',
               task_budgets={'coding':policy})
    job=dict(id='task',agent='a12',prompt=prompt,data_classification='CLOUD_PERMITTED',allow_cloud=True,
             timeout_seconds=2,task_class='coding',estimated_cost_usd=reserve,max_cost_usd=.01)
    if extension is not None:job['reasoning_budget_extension']=extension
    class Adapter:
        def __init__(self,*a,**kw):pass
        async def stream(self,model,messages,output):
            calls.append((model.context_tokens,output))
            if mode=='timeout':await asyncio.sleep(1)
            if mode=='exhaust':raise ProviderFailure('OUTPUT_BUDGET_EXHAUSTED')
            yield Chunk(text='fixture complete',usage=Usage(10,2,0))
            yield Chunk(complete=True)
    class Metrics:
        def __init__(self,*a):pass
        def record(self,**kw):metrics.append(kw)
    def execute(self,record,operation):
        try:return operation()
        finally:receipts.append(record.parameters_summary)
    monkeypatch.setattr(cloud,'load_catalog',lambda:[entry])
    monkeypatch.setattr(cloud,'ChatCompletionProvider',Adapter)
    monkeypatch.setattr(cloud,'OutcomeMetrics',Metrics)
    monkeypatch.setattr(cloud,'action_ledger',lambda:None)
    monkeypatch.setattr(cloud.DirectExecutor,'execute',execute)
    return lambda:cloud.execute_cloud(job,SimpleNamespace(name='fixture'),Path('.'),lambda:False),calls,receipts,metrics,policy


def test_task_class_caps_reach_actual_adapter(monkeypatch):
    run,calls,receipts,metrics,_=fixture(monkeypatch)
    assert run()['result']=='fixture complete'
    assert calls==[(256,8)]
    assert receipts[0]['reasoning_budget']['extension'] is None
    assert metrics[0]['success']


def test_named_extension_is_explicit_and_bounded(monkeypatch):
    run,calls,receipts,_,_=fixture(monkeypatch,extension='reviewed')
    run()
    assert calls==[(512,16)] and receipts[0]['reasoning_budget']['extension']=='reviewed'
    run,calls,_,_,_=fixture(monkeypatch,extension='unapproved')
    with pytest.raises(ProviderFailure,match='EXTENSION_DENIED'):run()
    assert calls==[]


@pytest.mark.parametrize('reserve,prompt,code',[(.000001,'safe','COST_EXCEEDED'),(.01,'x'*300,'CONTEXT_BUDGET_EXCEEDED')])
def test_budget_failure_stops_before_request(monkeypatch,reserve,prompt,code):
    run,calls,_,_,_=fixture(monkeypatch,reserve=reserve,prompt=prompt)
    with pytest.raises(ProviderFailure,match=code):run()
    assert calls==[]


@pytest.mark.parametrize('mode,code',[('timeout','TASK_TIMEOUT'),('exhaust','OUTPUT_BUDGET_EXHAUSTED')])
def test_exhaustion_never_extends_or_returns_success(monkeypatch,mode,code):
    run,calls,_,metrics,_=fixture(monkeypatch,mode=mode)
    with pytest.raises(ProviderFailure,match=code):run()
    assert len(calls)==1 and not metrics[-1]['success']


def test_config_extension_cannot_exceed_model_or_job_caps():
    job={'task_class':'coding','timeout_seconds':2}
    entry={'task_budgets':{'coding':{'output_tokens':256,'context_tokens':1024,'timeout_seconds':1}}}
    with pytest.raises(ProviderFailure,match='CONFIG_INVALID'):select_budget(entry,job,MODEL)
    entry['task_budgets']['coding']['output_tokens']=32
    entry['task_budgets']['coding']['timeout_seconds']=3
    with pytest.raises(ProviderFailure,match='CONFIG_INVALID'):select_budget(entry,job,MODEL)


def test_configured_extension_selection_and_absent_policy():
    job={'task_class':'coding','timeout_seconds':2}
    entry={'task_budgets':{'coding':{'selected_extension':'reviewed','extensions':{'reviewed':{'output_tokens':16,'context_tokens':512,'timeout_seconds':1}}}}}
    assert select_budget(entry,job,MODEL).extension=='reviewed'
    assert not select_budget({},job,MODEL).configured
