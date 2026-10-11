"""Actual disposable source selection, never installed-model health or inference."""
import json
import pytest
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_tool_events import collect,no_external_operations
from app import agent_cert_model_selection as models
from app.tier_router import Backend,Tier
from app.agent_dispatch_api import AgentRequest
from app.model_selection import select_final_model


@pytest.fixture(autouse=True)
def original_metadata_only(runtime,configured,monkeypatch):
    from app import compute_queue_api
    # Keep the inherited disposable queue and every inference/network prohibition.
    # This case needs the real metadata inventory, not the authority fixture's ban.
    monkeypatch.setattr(compute_queue_api,'providers',configured.original_provider_metadata)
    monkeypatch.delenv('PRIME_PROVIDER_CATALOG',raising=False)


def test_original_full_final_selection_and_distinct_original_peer_review(runtime,monkeypatch):
    from app import model_selection
    original=model_selection.select_final_model
    calls=[]
    def measured(*args,**kwargs):
        calls.append(args[0])
        return original(*args,**kwargs)
    monkeypatch.setattr(model_selection,'select_final_model',measured)
    result=collect(runtime,models.CASE)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes)
    report=json.loads(execution['artifact_content_utf8'])
    assert len(calls)==1
    assert report['selected_tier']=='NANO'
    assert report['requested_minimum_tier']=='NANO'
    assert report['selected_model']!=report['agent_id']
    assert report['model_calls']==0 and report['inference']=='NOT_PERFORMED'
    assert report['model_health']=='NOT_OBSERVED'
    assert len(execution['original_action_records'])==6
    from tests.test_agent_cert_operator_io import TOKEN
    from app.agent_cert_tool_events import tool_action_type
    response=runtime.client.get('/api/agent-cert-events/actions/'+execution['dispatch']['task_id'],
        params={'action_type':tool_action_type(models.CASE,phase='full')},
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==200 and response.json()['original_lines']==execution['original_action_records']
    assert len([p for m,p in runtime.requests if m=='POST'])==2
    assert execution['dispatch']['task_id']!=result.summary['review_task_id']


@pytest.mark.parametrize('field,value',[
    ('selected_tier','FLAGSHIP'),('selected_model','a19'),('agent_is_model',True),
    ('inference','PERFORMED'),('model_health','HEALTHY'),('model_calls',1),
    ('reasoning_scope','GENERAL_REASONING_PROVEN')])
def test_independent_original_oracle_rejects_wrong_report_without_shared_selector(runtime,monkeypatch,field,value):
    result=collect(runtime,models.CASE)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes)
    report=json.loads(execution['artifact_content_utf8']);report[field]=value
    def forbidden(*args,**kwargs):pytest.fail('Peer borrowed producer/shared final selector')
    monkeypatch.setattr(models,'produce_report',forbidden)
    monkeypatch.setattr(__import__('app.model_selection',fromlist=['select_final_model']),'select_final_model',forbidden)
    with pytest.raises(ValueError,match='MODEL_ORIGINAL_INDEPENDENT_REPORT_REJECTED'):
        models.independently_validate_report(models.canonical(report),execution['input_content_utf8'].encode(),
            execution['dispatch']['tool_event']['original_model_snapshot'])


def request(**changes):
    return AgentRequest(**dict(models.routing_request(),**changes))


def entry(name,tier='NANO',**changes):
    return dict(id=name,model=name+'-model',tier=tier,location='local',enabled=True,
        provider_kind='local',measurement_evidence={'source':'original-public-measurement'},
        expected_seconds=1,expected_cost_usd=0,**changes)


def test_full_selector_does_not_treat_unmeasured_available_local_as_slower():
    configured=[entry('measured')]
    route,tier=select_final_model(request(),configured=configured,available={'measured'},
        local_backends=(Backend('original-unmeasured','local-model',Tier.NANO,'local'),))
    assert tier==Tier.NANO and route.backend.name=='measured'
    # Alphabetical baseline chooses measured, but no measured override claim is justified.
    assert route.reason=='Lowest sufficient local tier'


def test_full_selector_measured_override_requires_complete_eligible_coverage():
    slow=entry('a-slow');slow['expected_seconds']=2
    fast=entry('z-fast')
    route,tier=select_final_model(request(),configured=[slow,fast],available={'a-slow','z-fast'},local_backends=())
    assert route.backend.name=='z-fast'
    assert route.reason=='Fastest measured sufficient backend within data locality'


def test_preferred_provider_and_explicit_higher_requirement_preserved():
    configured=[entry('nano'),entry('mini','MINI')]
    route,tier=select_final_model(request(minimum_tier='MINI',preferred_provider='nano'),
        configured=configured,available={'nano','mini'},local_backends=())
    assert tier==Tier.MINI and route.state=='UNAVAILABLE' and route.backend is None


def test_unavailable_preferred_rejects_before_local_metadata_read():
    def forbidden():pytest.fail('Unavailable provider must reject before local metadata query')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        select_final_model(request(preferred_provider='missing'),configured=[],available=set(),local_backends=forbidden)
    assert error.value.status_code==422


def test_huggingface_optin_is_still_required_before_route():
    item=entry('hf');item.update(provider_kind='huggingface',location='cloud')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        select_final_model(request(preferred_provider='hf'),configured=[item],available={'hf'},local_backends=())
    assert error.value.status_code==422


def test_native_provider_metadata_drift_is_rejected_without_inference(runtime,monkeypatch):
    result=collect(runtime,models.CASE)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    snapshot=json.loads(result.execution_bytes)['dispatch']['tool_event']['original_model_snapshot']
    from app import compute_queue_api
    monkeypatch.setattr(compute_queue_api,'providers',lambda **kwargs:[])
    with pytest.raises(ValueError,match='MODEL_ORIGINAL_NATIVE_CONFIGURATION_CHANGED'):
        models.reread_native_snapshot(snapshot,deadline=__import__('time').monotonic()+1)


def test_real_oversized_catalog_rejected_before_parsing_or_provider_query(runtime,monkeypatch):
    path=runtime.root/'oversized-original-catalog.json'
    path.write_bytes(b' '*(131072+1))
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG',str(path))
    from app import compute_queue_api
    monkeypatch.setattr(compute_queue_api,'providers',lambda **kwargs:pytest.fail('Oversized catalog queried provider'))
    with pytest.raises(ValueError,match='MODEL_ORIGINAL_CATALOG_BOUND'):
        models.capture_native_snapshot(deadline=__import__('time').monotonic()+1)


def test_original_budget_is_not_refreshed_after_elapsed_time():
    from datetime import datetime,timezone,timedelta
    import time
    assert models.case_remaining(dict(deadline=time.monotonic()+5,
        started_at=datetime.now(timezone.utc)-timedelta(seconds=6)))==0


def test_fixed_public_report_cannot_use_generic_expected_output_builder():
    from app.agent_cert_tool_events import expected_artifact_bytes,input_bytes
    with pytest.raises(ValueError,match='MODEL_REPORT_REQUIRES_ORIGINAL_NATIVE_SELECTION'):
        expected_artifact_bytes(models.CASE,available_bytes=input_bytes(models.CASE))


@pytest.mark.parametrize('field,value',[('selected_tier','FLAGSHIP'),('inference','PERFORMED'),
                                     ('model_health','HEALTHY'),('agent_is_model',True)])
def test_actual_wrong_producer_is_denied_by_distinct_original_peer(runtime,monkeypatch,field,value):
    producer=models.produce_report
    def faulty(*args,**kwargs):
        report=json.loads(producer(*args,**kwargs));report[field]=value
        return models.canonical(report)
    monkeypatch.setattr(models,'produce_report',faulty)
    oracle=models.independently_validate_report;checks=[]
    def skip_only_early_observer(*args):
        checks.append(True)
        return True if len(checks)==1 else oracle(*args)
    # Only the independent early observer is bypassed for this discriminator.
    # The actual A26 route must reject originally wrong, rehashed producer bytes.
    monkeypatch.setattr(models,'independently_validate_report',skip_only_early_observer)
    result=collect(runtime,models.CASE)
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    execution=json.loads(result.execution_bytes)
    assert json.loads(execution['artifact_content_utf8'])[field]==value
    assert len(execution['original_action_records'])==6
    # Collector independently refuses before submission too. Restore the oracle
    # and submit that originally wrong evidence to the real registered A26 route.
    monkeypatch.setattr(models,'independently_validate_report',oracle)
    from app.agent_cert_tool_events import cross_peer_request
    from tests.test_agent_cert_review_dispatch import NONCE,SOURCE
    from tests.test_agent_cert_operator_io import TOKEN
    request=cross_peer_request(execution,NONCE,SOURCE)
    response=runtime.client.post('/api/agents/objectives',json=request,
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202,response.json()
    assert response.json()['steps'][0]['state']=='blocked'
    from app.objective_api import get_read_only
    original=get_read_only(response.json()['id'],'Bearer '+TOKEN)
    assert original['state']=='COMPLETED_WITH_FAILURES'
    assert len(checks)>=2
    rows=[json.loads(line) for line in (runtime.root/'action-records.jsonl').read_text().splitlines()]
    assert not any(row['agent_id']=='a26' for row in rows)


@pytest.mark.parametrize('mutation',['growth','swap'])
def test_actual_original_catalog_change_during_bounded_read_rejects_before_provider(runtime,monkeypatch,mutation):
    from pathlib import Path
    from app import compute_queue_api
    path=runtime.root/'catalog.json';path.write_bytes(b'{"models":[]}')
    replacement=runtime.root/'replacement.json';replacement.write_bytes(b'{"models":[]} ')
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG',str(path))
    monkeypatch.setattr(compute_queue_api,'providers',lambda **kwargs:pytest.fail('Changed catalog queried provider'))
    original=Path.open;reads=[]
    class OriginalReader:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):
            result=self.stream.__exit__(*args)
            if mutation=='swap':
                path.replace(runtime.root/'retained-original.json')
                replacement.replace(path)
            return result
        def fileno(self):return self.stream.fileno()
        def read(self,count):
            reads.append(count)
            assert count==131073
            if mutation=='growth':
                with original(path,'ab') as writer:writer.write(b' '*131073)
                return self.stream.read(count)
            return self.stream.read(count)
    def changed(self,*args,**kwargs):
        stream=original(self,*args,**kwargs)
        return OriginalReader(stream) if self==path and args and args[0]=='rb' else stream
    monkeypatch.setattr(Path,'open',changed)
    with pytest.raises(ValueError,match='MODEL_ORIGINAL_CATALOG'):
        models.capture_native_snapshot(deadline=__import__('time').monotonic()+1)
    assert reads==[131073]


def test_actual_windows_catalog_parent_junction_rejected_before_provider(runtime,monkeypatch):
    import os,subprocess
    if os.name!='nt':pytest.skip('Actual Windows catalog junction requires Windows')
    actual=runtime.root/'actual-catalog';actual.mkdir();(actual/'catalog.json').write_bytes(b'{"models":[]}')
    redirected=runtime.root/'redirected-catalog'
    result=subprocess.run(['cmd','/c','mklink','/J',str(redirected),str(actual)],capture_output=True)
    assert result.returncode==0,'Disposable junction creation failed'
    try:
        monkeypatch.setenv('PRIME_PROVIDER_CATALOG',str(redirected/'catalog.json'))
        from app import compute_queue_api
        monkeypatch.setattr(compute_queue_api,'providers',lambda **kwargs:pytest.fail('Redirected catalog queried provider'))
        with pytest.raises(ValueError):
            models.capture_native_snapshot(deadline=__import__('time').monotonic()+1)
    finally:os.rmdir(redirected)


def test_exact_captured_catalog_validated_without_unbounded_reopen(runtime,monkeypatch):
    from pathlib import Path
    path=runtime.root/'original-catalog.json';path.write_bytes(b'{"models":[]}')
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG',str(path))
    original=Path.read_text
    def forbidden_reopen(self,*args,**kwargs):
        if self==path:pytest.fail('Captured catalog reopened with unbounded text read')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',forbidden_reopen)
    snapshot,configured,available,locals=models.capture_native_snapshot(deadline=__import__('time').monotonic()+1)
    assert snapshot['catalog_original_sha256']==models.sha(path.read_bytes())
    assert configured==[] and available and locals
