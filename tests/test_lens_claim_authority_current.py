"""A completed deterministic lookup is not automatically a verified claim."""
import json

import pytest

from app import objective_api, system_architecture


def _step(text, fact=None, *, revision=0):
    dispatch={'state':'COMPLETED','model_backend':'none','result':text}
    if fact is not None:dispatch['system_fact']=fact
    return {'revision':revision,'capability':'system.architecture','dispatch':dispatch}


@pytest.fixture
def objectives(monkeypatch,tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setattr(objective_api,'authenticate_owner',lambda _:None)
    monkeypatch.setattr(objective_api,'dispatch_request',
                        lambda *args,**kwargs:pytest.fail('canonical lookup must not dispatch a model'))
    return tmp_path


@pytest.mark.parametrize('question,status',[
    ('Is Phase 2 Golden and accepted?','UNVERIFIED'),
    ('Explain the ABEX, Dell, and PRIME architecture relationship','UNAVAILABLE'),
])
def test_missing_governance_does_not_gain_claim_authority(objectives,monkeypatch,question,status):
    monkeypatch.setattr(system_architecture,'ROOT',objectives/'missing')
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective=question))
    task=objective_api.get(submitted['id'])
    assert task['state']=='COMPLETED'
    assert task['execution_metadata']['authoritative'] is True  # Execution metadata only.
    assert task['steps'][0]['dispatch']['system_fact']['status']==status
    assert task['result']['type']=='SYSTEM_FACT'  # Existing consumer shape.
    assert task['result']['authoritative'] is False
    assert task['result']['verification_status']==status
    assert task['result']['provenance']==task['steps'][0]['dispatch']['system_fact']['provenance']
    assert task['result']['may_update_truth_plane'] is False
    assert objective_api.get(submitted['id'])['result']==task['result']


def test_verified_registry_fact_remains_verified_without_mutation_right(objectives):
    submitted=objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?'))
    result=objective_api.get(submitted['id'])['result']
    assert result['verification_status']=='VERIFIED'
    assert result['authoritative'] is True
    assert 'REGISTERED AGENTS: 21' in result['text']
    assert result['provenance']=='CANONICAL_REGISTRY_AND_RUNTIME'
    assert result['may_update_truth_plane'] is False


@pytest.mark.parametrize('status',['UNVERIFIED','UNAVAILABLE','PARTIAL','STALE','CONTRADICTED'])
def test_nonverified_status_and_provenance_survive_projection(status):
    fact={'status':status,'provenance':'GOVERNANCE_MANIFEST','text':'Evidence is not current'}
    result=objective_api.system_result([_step(fact['text'],fact)],0)
    assert result['verification_status']==status
    assert result['provenance']==fact['provenance']
    assert result['authoritative'] is False


@pytest.mark.parametrize('fact',[None,{},'VERIFIED',
    {'status':'VERIFIED','text':'Claim'},
    {'status':'VERIFIED','provenance':'CANONICAL_REGISTRY','text':'Other claim'},
    {'status':'VERIFIED','provenance':'arbitrary-source','text':'Claim'},
    {'status':'UNKNOWN','provenance':'CANONICAL_REGISTRY','text':'Claim'},
])
def test_missing_malformed_or_unbound_fact_fails_closed(fact):
    result=objective_api.system_result([_step('Claim',fact)],0)
    assert result['text']=='Claim'
    assert result['verification_status']=='UNVERIFIED'
    assert result['authoritative'] is False
    assert result['provenance']=='UNAVAILABLE'


def test_mixed_sources_are_partial_and_revision_isolated():
    verified={'status':'VERIFIED','provenance':'CANONICAL_REGISTRY','text':'Registered agents'}
    unavailable={'status':'UNAVAILABLE','provenance':'GOVERNANCE_MANIFEST','text':'Missing manifest'}
    steps=[_step(verified['text'],verified),_step(unavailable['text'],unavailable),
           _step('Old response',verified,revision=1)]
    result=objective_api.system_result(steps,0)
    assert result['verification_status']=='PARTIAL'
    assert result['authoritative'] is False
    assert result['provenance']=='MULTIPLE_SYSTEM_SOURCES'
    assert result['text']=='Registered agents\n\nMissing manifest'


def test_stored_latest_turn_cannot_borrow_previous_verification(objectives):
    verified={'status':'VERIFIED','provenance':'CANONICAL_REGISTRY','text':'Registered agents'}
    unavailable={'status':'UNAVAILABLE','provenance':'GOVERNANCE_MANIFEST','text':'Missing manifest'}
    with objective_api.connect() as db:
        db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
                   ('lens-turn','digest','submitted',json.dumps([_step(verified['text'],verified)])))
        db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
                   ('lens-turn',1,'turn-key','digest','submitted',
                    json.dumps([_step(unavailable['text'],unavailable)])))
    result=objective_api.get('lens-turn')['result']
    assert result['verification_status']=='UNAVAILABLE'
    assert result['authoritative'] is False
    assert result['text']=='Missing manifest'
