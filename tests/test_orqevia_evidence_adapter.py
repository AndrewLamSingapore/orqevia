import pytest

from app.evidence_product import validate_envelope
from app.orqevia_evidence_adapter import adapt_task


def test_prime_adapter_preserves_canonical_metadata_without_model_override():
    task={'task_id':'task-system-1','objective':'回答问题','actor_id':'owner-1','actor_type':'OWNER',
          'authority_scope':'objective.execute','authority_source':'prime-identity-db','created_at':'2026-09-26T00:00:00Z',
          'completed_at':'2026-09-26T00:01:00Z','status':'COMPLETED','runtime_identity':'sha-candidate'}
    obs=[{'observation_id':'obs-1','source':'task-system','value':{'status':'COMPLETED'},'observed_at':task['completed_at'],'verification_ref':'db:task-system-1'}]
    claims=[{'claim_id':'claim-1','text':'MODEL says task id fake-123 at 2024','state':'INFERRED','evidence_refs':[]}]
    envelope=adapt_task(task,claims=claims,observations=obs,effects=[],artifacts=[],verification={'state':'UNVERIFIED','evidence':['obs-1']})
    assert envelope['action_id']=='task-system-1' and envelope['started_at']==task['created_at']
    assert not envelope['provenance']['model_content_authoritative']
    assert validate_envelope(envelope)['verdict']=='UNVERIFIED'


def test_prime_adapter_fails_closed_without_authority_source():
    with pytest.raises(ValueError,match='authority_source'):
        adapt_task({'task_id':'x','objective':'x','actor_id':'x','actor_type':'OWNER','authority_scope':'x','created_at':'x','status':'REQUESTED'},claims=[],observations=[],effects=[],artifacts=[],verification={'state':'UNVERIFIED','evidence':[]})
