"""Disposable authenticated owning Objectives; never live certification evidence."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch, agent_registry
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from app.agent_cert_owned_contract import (canonical_case, registry_digest, review_request,
    action_type, canonical, build_report, inspect_supplied, OwnedContractError)
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE

PAIRS = [(a['id'],cap) for a in agent_registry.load_agent_registry()['agents']
    for cap in a['capability_requirements'] if a['id'] != 'a19']


@pytest.fixture
def events(configured,monkeypatch):
    from app import objective_api,compute_queue_api
    compute_queue_api.queue.policy=SimpleNamespace(global_concurrency=1)
    ledger=ActionLedger(configured.root/'action-records.jsonl')
    monkeypatch.setattr(dispatch,'action_ledger',lambda:ledger)
    def produce(pair=('a01','responsibility.a01')):
        spec=canonical_case(*pair); before=objective_api.runtime_snapshot()
        began=datetime.now(timezone.utc)
        reply=objective_api.submit(objective_api.ObjectiveRequest(**spec['request']),'fixture-owner')
        assert reply.get('steps') and isinstance(reply['steps'][0],dict),reply
        assert 'dispatch' in reply['steps'][0],reply
        produced=reply['steps'][0]['dispatch'];task=produced['task_id']
        factory=ArtifactFactory(configured.root/'artifacts')
        metadata,raw=factory.retrieve(produced['artifact']['artifact_id'])
        _,input_raw=factory.retrieve(produced['owned_contract_event']['input_artifact_metadata']['artifact_id'])
        lines=[line for line in ledger.path.read_text().splitlines(keepends=True)
            if json.loads(line)['task_id']==task]
        value=dict(case_spec=spec,submitted_request=spec['request'],runtime=before,
            runtime_after=objective_api.runtime_snapshot(),runtime_current=objective_api.runtime_snapshot(),
            submission=[202,reply],dispatch=produced,artifact_metadata=metadata,artifact_content_utf8=raw.decode(),
            input_content_utf8=input_raw.decode(),objective_read=[200,objective_api.get_read_only(task,'fixture-owner')],
            original_action_records=lines,observation=dict(started_at=began.isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat()))
        return json.loads(canonical(value))
    def review(value):
        body=review_request(value,str(uuid.uuid4()))
        reply=objective_api.submit(objective_api.ObjectiveRequest(**body),'fixture-owner')
        assert reply.get('steps') and isinstance(reply['steps'][0],dict),reply
        assert 'dispatch' in reply['steps'][0],reply
        return reply['steps'][0]['dispatch']
    yield SimpleNamespace(produce=produce,review=review,root=configured.root,ledger=ledger)
    ledger.close()


@pytest.mark.parametrize('pair',PAIRS)
def test_actual_owned_contract_and_distinct_persisted_peer(events,pair):
    assert len(PAIRS)==28
    value=events.produce(pair)
    assert len(value['original_action_records'])==6
    report=json.loads(value['artifact_content_utf8'])
    assert report['samples'][0]['structural_conformance'] is True
    assert report['samples'][1]['missing_input']==['data_classification']
    assert report['samples'][1]['missing_output']==['uncertainty']
    assert report['samples'][1]['violations']==['output.status.enum','output.proposed_actions.execution_claim']
    assert report['prose_semantics']==report['role_result_quality']=='NOT_ESTABLISHED'
    assert value['dispatch']['model_calls']==0
    reviewed=events.review(value)
    expected=('a18','responsibility.a27') if pair[0]=='a26' else ('a26','responsibility.a26')
    assert (reviewed['agent_id'],reviewed['capability'])==expected
    assert reviewed['task_id']!=value['dispatch']['task_id']
    metadata,raw=ArtifactFactory(events.root/'artifacts').retrieve(reviewed['artifact']['artifact_id'])
    assert metadata['creator_agents']==[expected[0]]
    grade=json.loads(raw)
    assert grade['original_join']==report
    assert grade['certification']=='UNVERIFIED'


def test_authentication_and_foreign_capability_fail_before_case_writes(events):
    body=canonical_case('a01','responsibility.a01')['request']
    with pytest.raises(HTTPException) as rejected:
        dispatch.dispatch_request(dispatch.AgentRequest(**body),'foreign-owner')
    assert rejected.value.status_code==401
    with pytest.raises(ValueError):canonical_case('a01','responsibility.a03')
    with pytest.raises(ValueError):canonical_case('a19','responsibility.a19')
    assert not events.ledger.path.exists() or not events.ledger.path.read_bytes()


def test_partial_structural_adapter_is_not_a_full_canonical_case_oracle():
    from app.agent_cert_role_review import canonical_case_spec
    for agent,capability in PAIRS:
        assert canonical_case(agent,capability)['scope']=='STRUCTURAL_INSPECTION_ONLY'
        with pytest.raises(ValueError):canonical_case_spec(agent,capability,'baseline:contract')
    legacy=canonical_case_spec('a19','responsibility.a19','baseline:contract')
    assert legacy['request'].get('deterministic_operation') is None


@pytest.mark.parametrize('field',['prose_semantics','role_result_quality','actual_service_health'])
def test_genuinely_wrong_producer_report_is_rejected_by_actual_peer(events,monkeypatch,field):
    from app import agent_cert_owned_contract as owning
    original=owning.build_report
    def corrupt(*args,**kwargs):
        report=original(*args,**kwargs);report[field]='CONFIRMED';return report
    monkeypatch.setattr(owning,'build_report',corrupt)
    value=events.produce()
    assert json.loads(value['artifact_content_utf8'])[field]=='CONFIRMED'
    body=review_request(value,str(uuid.uuid4()))
    from app import objective_api
    reply=objective_api.submit(objective_api.ObjectiveRequest(**body),'fixture-owner')
    assert 'dispatch' not in reply['steps'][0]
    assert len([json.loads(line) for line in events.ledger.path.read_text().splitlines()])==6


def test_borrowed_task_and_request_are_rejected(events):
    value=events.produce();value['submitted_request']['context']='{}'
    from app import objective_api
    body=review_request(value,str(uuid.uuid4()))
    reply=objective_api.submit(objective_api.ObjectiveRequest(**body),'fixture-owner')
    assert 'dispatch' not in reply['steps'][0]
    assert len(events.ledger.path.read_text().splitlines())==6


def test_real_slow_fsync_subject_and_peer_keep_original_five_second_task_budgets(events,monkeypatch):
    import os,time,threading
    from app import agent_cert_owned_contract as owning
    fsync=os.fsync; delayed=[];phase=[None];budgets=[];flush=ActionLedger.flush
    producer,reviewer=owning.execute_producer,owning.execute_review
    def producing(*args,**kwargs):
        phase[0]='subject'
        try:return producer(*args,**kwargs)
        finally:phase[0]=None
    def reviewing(*args,**kwargs):
        phase[0]='peer'
        try:return reviewer(*args,**kwargs)
        finally:phase[0]=None
    def slow(fd):
        if phase[0] and phase[0] not in delayed and threading.current_thread().name=='action-observability':
            delayed.append(phase[0]);time.sleep(1.2)
        return fsync(fd)
    def observed(self,timeout=5):
        if phase[0]:budgets.append(timeout)
        return flush(self,timeout=timeout)
    monkeypatch.setattr(owning,'execute_producer',producing)
    monkeypatch.setattr(owning,'execute_review',reviewing)
    monkeypatch.setattr(os,'fsync',slow);monkeypatch.setattr(ActionLedger,'flush',observed)
    value=events.produce();events.review(value)
    assert delayed==['subject','peer'] and len(budgets)==2 and all(1<timeout<=5 for timeout in budgets)


def test_real_failed_writer_never_returns_successful_contract_evidence(events,monkeypatch):
    import os,threading
    from app import objective_api
    fsync=os.fsync
    def failed(fd):
        if threading.current_thread().name=='action-observability':raise OSError('source fixture failed fsync')
        return fsync(fd)
    monkeypatch.setattr(os,'fsync',failed)
    body=canonical_case('a01','responsibility.a01')['request']
    reply=objective_api.submit(objective_api.ObjectiveRequest(**body),'fixture-owner')
    assert 'dispatch' not in reply['steps'][0]
    assert events.ledger.status()['healthy'] is False
    assert events.ledger.close() is False


def test_actual_expired_original_task_is_rejected_before_artifacts_or_actions(events,monkeypatch):
    from datetime import timedelta
    from contextlib import closing
    from app import agent_cert_fresh_input,objective_api
    original=agent_cert_fresh_input.read_task
    def expired(root,task,body,runtime,**kwargs):
        with closing(objective_api.connect()) as db:
            old=(datetime.now(timezone.utc)-timedelta(seconds=6)).isoformat()
            db.execute('UPDATE objective_metadata SET created_at=?,updated_at=? WHERE task=?',(old,old,task))
            db.commit()
        return original(root,task,body,runtime,**kwargs)
    monkeypatch.setattr(agent_cert_fresh_input,'read_task',expired)
    body=canonical_case('a01','responsibility.a01')['request']
    reply=objective_api.submit(objective_api.ObjectiveRequest(**body),'fixture-owner')
    assert 'dispatch' not in reply['steps'][0]
    assert not events.ledger.path.exists()
    assert not (events.root/'artifacts').exists()


def test_completed_original_task_cannot_replay_producer(events):
    from app import objective_api
    from app.agent_cert_owned_contract import execute_producer
    value=events.produce();before=events.ledger.path.read_bytes()
    with pytest.raises(OwnedContractError):
        execute_producer(value['dispatch']['task_id'],actor='a01',submitted_request=value['submitted_request'],
            data_root=events.root,ledger=events.ledger,runtime=value['runtime'],
            read_runtime=objective_api.runtime_snapshot,source_revision=SOURCE,runtime_image_id=IMAGE,
            registry_sha256=registry_digest())
    assert events.ledger.path.read_bytes()==before


def test_transport_unknown_post_consumes_claim_and_never_retries():
    from scripts.agent_cert_operator_io import OwnedContractPhaseOperatorIO,OperatorBindingError
    from tests.test_agent_cert_operator_io import FakeResponse,FakeTransport,FakeTimer,TOKEN
    def handler(method,path,body):
        if method=='POST':raise RuntimeError('fixture uncertain mutation')
        return FakeResponse()
    transport=FakeTransport(handler)
    operator=OwnedContractPhaseOperatorIO(owner_token=TOKEN,agent_id='a01',capability_id='responsibility.a01',
        which='subject',expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        connection_factory=transport,timer_factory=FakeTimer)
    operator.authorize()
    for _ in range(2):
        with pytest.raises(OperatorBindingError):operator.submit_objective(operator._submitted_request)
    assert sum(method=='POST' for method,_,_ in transport.calls)==1


def test_transport_rejects_foreign_body_before_any_connection():
    from scripts.agent_cert_operator_io import OwnedContractPhaseOperatorIO,OperatorBindingError
    from tests.test_agent_cert_operator_io import FakeTransport,FakeTimer,TOKEN
    transport=FakeTransport()
    operator=OwnedContractPhaseOperatorIO(owner_token=TOKEN,agent_id='a01',capability_id='responsibility.a01',
        which='subject',expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        connection_factory=transport,timer_factory=FakeTimer)
    with pytest.raises(OperatorBindingError):operator.submit_objective({**operator._submitted_request,'max_cost_usd':1})
    assert transport.calls==[]


def test_collector_uses_two_exact_objective_posts_and_original_authenticated_feeds(events,monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    from fastapi import Response
    from app import objective_api,agent_cert_event_api
    from scripts.agent_cert_operator_io import OwnedContractPhaseOperatorIO,RUNTIME_PATH
    from scripts.collect_agent_cert_event import collect_owned_contract_case
    from tests.test_agent_cert_operator_io import FakeResponse,FakeTransport,FakeTimer,raw,TOKEN
    monkeypatch.setattr(agent_cert_event_api,'authenticate_owner',lambda _:None)
    def handler(method,path,body):
        if path==RUNTIME_PATH:return FakeResponse(body=raw(objective_api.runtime_snapshot()))
        if path=='/api/agents/objectives':
            reply=objective_api.submit(objective_api.ObjectiveRequest(**json.loads(body)),'fixture-owner')
            return FakeResponse(202,raw(reply))
        if path.startswith('/api/agents/objectives/'):
            return FakeResponse(body=raw(objective_api.get_read_only(path.rsplit('/',1)[1],'fixture-owner')))
        if path.startswith('/api/artifacts/'):
            metadata,content=ArtifactFactory(events.root/'artifacts').retrieve(path.rsplit('/',1)[1])
            return FakeResponse(200,content,{'X-Artifact-SHA256':metadata['sha256']})
        parsed=urlsplit(path);kind=parse_qs(parsed.query)['action_type'][0]
        return FakeResponse(body=raw(agent_cert_event_api.actions(parsed.path.rsplit('/',1)[1],Response(),kind,'fixture-owner')))
    diagnostics=[]
    def diagnostic_handler(*args):
        try:return handler(*args)
        except Exception as error:
            diagnostics.append((type(error).__name__,str(error)));raise
    transport=FakeTransport(diagnostic_handler)
    def factory(**kwargs):
        return OwnedContractPhaseOperatorIO(owner_token=TOKEN,expected_source_revision=SOURCE,
            expected_runtime_image=IMAGE,connection_factory=transport,timer_factory=FakeTimer,**kwargs)
    result=collect_owned_contract_case(operator_factory=factory,agent_id='a26',capability_id='responsibility.a25',
        expected_source_revision=SOURCE,expected_runtime_image=IMAGE,expected_registry_sha256=registry_digest())
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',(canonical(result.summary).decode(),diagnostics)
    assert result.execution_bytes and result.peer_execution_bytes
    assert json.loads(result.peer_execution_bytes)['dispatch']['agent_id']=='a18'
    assert sum(method=='POST' for method,_,_ in transport.calls)==2
    assert result.summary['original_producer_rows']==6 and result.summary['original_peer_rows']==2
    assert all(reply.body_complete for reply in result.original_http_replies)
    assert TOKEN not in repr(result.original_http_replies)
