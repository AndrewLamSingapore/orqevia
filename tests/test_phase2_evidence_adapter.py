from app.evidence_product import validate_envelope
from app.phase2_evidence_adapter import adapt_objective_snapshot
from app.phase2_intelligence import AuthorityEnvelope,Phase2Kernel


def test_phase2_snapshot_maps_without_losing_identity_authority_or_provenance(tmp_path):
    now=2_200_000_000.0; perms=frozenset({'objective.create','objective.read','objective.update','objective.control'})
    auth=AuthorityEnvelope('owner-evidence','OWNER',perms,now+100)
    kernel=Phase2Kernel(tmp_path/'phase2.db',clock=lambda:now)
    objective=kernel.create_objective(objective='Verify invoice',success_criteria=['verified'],constraints=['no duplicate'],authority=auth)
    kernel.checkpoint(objective['objective_id'],authority=auth,expected_version=1,
                      updates={'facts':[{'claim':'invoice exists','evidence':'db:invoice-1'}]},next_action='VERIFY')
    snapshot=kernel.snapshot(objective['objective_id'],authority=auth)
    envelope=adapt_objective_snapshot(snapshot)
    assert envelope['action_id']==objective['objective_id']
    assert envelope['actor']=={'type':'OWNER','id':'owner-evidence'}
    assert envelope['provenance']['snapshot_sha256']==snapshot['snapshot_sha256']
    assert not envelope['provenance']['model_content_authoritative']
    assert envelope['verification']['state']=='UNVERIFIED'
    assert validate_envelope(envelope)['verdict']=='VALID'
