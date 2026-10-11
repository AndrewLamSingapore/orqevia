import json
import pytest
from app import agent_cert_owned_contract as producer
from app import agent_cert_owned_contract_review as review
from app.agent_registry import REGISTRY_PATH,load_agent_registry
from app.agent_cert_artifact_events import canonical

PAIRS=[(a['id'],c) for a in load_agent_registry()['agents'] for c in a['capability_requirements'] if a['id']!='a19']

@pytest.mark.parametrize('agent,capability',PAIRS)
def test_independent_original_registry_structural_calculation(agent,capability):
    raw=producer.supplied_bytes(agent,capability);registry=REGISTRY_PATH.read_bytes()
    actual=review.independent_report(raw,registry,task_id='00000000-0000-4000-8000-000000000001',
        agent_id=agent,capability_id=capability)
    expected=producer.build_report(raw,task_id=actual['task_id'],agent_id=agent,
        capability_id=capability,registry_sha256=review.sha(registry))
    assert actual==expected
    assert actual['samples'][0]['structural_conformance'] is True
    assert actual['samples'][1]['structural_conformance'] is False
    assert actual['samples'][1]['missing_input']==['data_classification']
    assert actual['samples'][1]['missing_output']==['uncertainty']
    assert actual['prose_semantics']==actual['role_result_quality']=='NOT_ESTABLISHED'
    assert actual['actual_service_health']=='UNKNOWN'


def test_independent_checker_never_calls_corrupted_producer(monkeypatch):
    monkeypatch.setattr(producer,'inspect_supplied',lambda *a:pytest.fail('producer oracle reused'))
    monkeypatch.setattr(producer,'build_report',lambda *a,**k:pytest.fail('producer report reused'))
    registry=REGISTRY_PATH.read_bytes();raw=producer.supplied_bytes('a01','responsibility.a01')
    result=review.independent_report(raw,registry,task_id='00000000-0000-4000-8000-000000000001',
        agent_id='a01',capability_id='responsibility.a01')
    assert result['samples'][1]['structural_conformance'] is False


@pytest.mark.parametrize('field,value,violation',[
    ('objective','', 'input.objective.bounds'),('context',False,'input.context.bounds'),
    ('data_classification','AUTO','input.data_classification.enum')])
def test_raw_input_changes_independently_detected(field,value,violation):
    raw=json.loads(producer.supplied_bytes('a01','responsibility.a01'));sample=raw['samples'][0]
    original=json.loads(sample['input_utf8']);original[field]=value;sample['input_utf8']=canonical(original).decode()
    result=review.independent_report(canonical(raw),REGISTRY_PATH.read_bytes(),task_id='t',
        agent_id='a01',capability_id='responsibility.a01')
    assert violation in result['samples'][0]['violations']
    assert result['samples'][0]['input_sha256']==review.sha(sample['input_utf8'].encode())


@pytest.mark.parametrize('field,value,violation',[
    ('status','executed','output.status.enum'),('agent_id','a02','output.agent_id.identity')])
def test_raw_output_changes_independently_detected(field,value,violation):
    raw=json.loads(producer.supplied_bytes('a01','responsibility.a01'));sample=raw['samples'][0]
    original=json.loads(sample['output_utf8']);original[field]=value;sample['output_utf8']=canonical(original).decode()
    result=review.independent_report(canonical(raw),REGISTRY_PATH.read_bytes(),task_id='t',
        agent_id='a01',capability_id='responsibility.a01')
    assert violation in result['samples'][0]['violations']


@pytest.mark.parametrize('agent,capability',[('a19','responsibility.a19'),('a01','responsibility.a02')])
def test_a19_original_case_and_foreign_ownership_rejected(agent,capability):
    with pytest.raises(review.OwnedContractReviewError):
        review.independent_domains(REGISTRY_PATH.read_bytes(),agent,capability)


@pytest.mark.parametrize('mutation',['duplicate','missing','oversized'])
def test_original_raw_samples_fail_closed(mutation):
    raw=json.loads(producer.supplied_bytes('a01','responsibility.a01'))
    if mutation=='duplicate':raw['samples'].append(raw['samples'][0])
    elif mutation=='missing':del raw['samples'][0]['input_utf8']
    else:raw['samples'][0]['input_utf8']='x'*16385
    with pytest.raises(ValueError):
        review.independent_report(canonical(raw),REGISTRY_PATH.read_bytes(),task_id='t',
            agent_id='a01',capability_id='responsibility.a01')


from tests.test_agent_cert_owned_contract_events import events,configured
from tests.test_agent_cert_review_dispatch import SOURCE,IMAGE
from datetime import datetime,timezone
import time


def test_real_original_native_two_read_oracle(events):
    execution=events.produce()
    report=review.validate_original_execution(execution,root=events.root,runtime=execution['runtime'],
        registry_sha256=producer.registry_digest(),deadline=time.monotonic()+5)
    assert report==json.loads(execution['artifact_content_utf8'])
    assert report['role_result_quality']=='NOT_ESTABLISHED'


@pytest.mark.parametrize('field',['prose_semantics','role_result_quality','actual_service_health'])
def test_actual_wrong_report_rejected_without_peer_writes(events,monkeypatch,field):
    original=producer.build_report
    def wrong(*args,**kwargs):
        result=original(*args,**kwargs);result[field]='CONFIRMED';return result
    monkeypatch.setattr(producer,'build_report',wrong)
    execution=events.produce();before=events.ledger.status()['persisted']
    with pytest.raises(review.OwnedContractReviewError,match='INDEPENDENT_ORACLE_REJECTED'):
        review.validate_original_execution(execution,root=events.root,runtime=execution['runtime'],
            registry_sha256=producer.registry_digest(),deadline=time.monotonic()+5)
    assert events.ledger.status()['persisted']==before==6


@pytest.mark.parametrize('fault',['borrowed_actor','missing_row','request','artifact_hash','expired_budget'])
def test_original_execution_join_faults_rejected(events,fault):
    execution=events.produce();deadline=time.monotonic()+5
    if fault=='borrowed_actor':execution['dispatch']['agent_id']='a02'
    elif fault=='missing_row':execution['original_action_records'].pop()
    elif fault=='request':execution['submitted_request']['context']='{}'
    elif fault=='artifact_hash':execution['artifact_metadata']['sha256']='0'*64
    else:deadline=time.monotonic()-1
    with pytest.raises(ValueError):
        review.validate_original_execution(execution,root=events.root,runtime=execution['runtime'],
            registry_sha256=producer.registry_digest(),deadline=deadline)


def test_actual_original_input_artifact_modified_rejected(events):
    execution=events.produce();meta=execution['dispatch']['owned_contract_event']['input_artifact_metadata']
    path=events.root/'artifacts'/meta['artifact_id']/'artifact.json';path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):
        review.validate_original_execution(execution,root=events.root,runtime=execution['runtime'],
            registry_sha256=producer.registry_digest(),deadline=time.monotonic()+5)


def test_registry_second_read_mutation_rejected(events,monkeypatch):
    execution=events.produce();original=review._registry_original;calls=[]
    def mutate(expected):
        raw=original(expected);calls.append(1)
        return raw if len(calls)<3 else raw+b' '
    monkeypatch.setattr(review,'_registry_original',mutate)
    with pytest.raises(ValueError):
        review.validate_original_execution(execution,root=events.root,runtime=execution['runtime'],
            registry_sha256=producer.registry_digest(),deadline=time.monotonic()+5)
    assert len(calls)==3


@pytest.mark.parametrize('executed,denied',[(True,True),(False,False),('true',False),(1,False)])
def test_literal_unsupported_execution_claim_is_independently_identified(executed,denied):
    supplied=json.loads(producer.supplied_bytes('a01','responsibility.a01'))
    sample=supplied['samples'][0];output=json.loads(sample['output_utf8'])
    output['proposed_actions']=[dict(action='PUBLIC_SYNTHETIC_ADVICE',executed=executed)]
    sample['output_utf8']=canonical(output).decode()
    report=review.independent_report(canonical(supplied),REGISTRY_PATH.read_bytes(),task_id='t',
        agent_id='a01',capability_id='responsibility.a01')
    assert ('output.proposed_actions.execution_claim' in report['samples'][0]['violations']) is denied
    assert report['role_result_quality']==report['prose_semantics']=='NOT_ESTABLISHED'


@pytest.mark.parametrize('counterexample',['credential_label','ungrounded_result'])
def test_semantic_counterexamples_never_become_full_contract_proof(counterexample):
    supplied=json.loads(producer.supplied_bytes('a01','responsibility.a01'));sample=supplied['samples'][0]
    if counterexample=='credential_label':
        value=json.loads(sample['input_utf8']);value['context']='PUBLIC_TEST_FAKE_CREDENTIAL_LABEL; no actual credential'
        sample['input_utf8']=canonical(value).decode()
    else:
        value=json.loads(sample['output_utf8']);value['result']='PUBLIC_TEST_UNSUPPORTED: every service healthy without evidence'
        sample['output_utf8']=canonical(value).decode()
    report=review.independent_report(canonical(supplied),REGISTRY_PATH.read_bytes(),task_id='t',
        agent_id='a01',capability_id='responsibility.a01')
    assert report['samples'][0]['structural_conformance'] is True
    assert report['prose_semantics']==report['role_result_quality']=='NOT_ESTABLISHED'
    assert report['actual_service_health']=='UNKNOWN' and report['certification']=='UNVERIFIED'
    assert report['execution_authority']=='NOT_GRANTED'
