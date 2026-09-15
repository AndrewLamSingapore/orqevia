import pytest
from app.action_harness import ActionEnvelopeIssuer,ActionHarness,HarnessPolicy,utcnow
from app.agent_registry import registered_agent_ids


@pytest.mark.parametrize('actor',sorted(registered_agent_ids(include_orchestrator=False)))
def test_every_agent_can_receive_only_independently_signed_advisory_authority(tmp_path,actor):
    key=b'isolated-registry-authority-test-key'
    issuer=ActionEnvelopeIssuer(key)
    harness=ActionHarness(tmp_path/'harness.db',{issuer.key_id:key},
                          HarnessPolicy(advisory_agents=frozenset(registered_agent_ids(include_orchestrator=False))))
    proposal=dict(tenant_id='personal',actor_id=actor,actor_type='reasoner',action='agent.infer',
                  parameters={'allow_cloud':False,'external_execution':False},context={'risk':'advisory'},
                  correlation_id=actor,idempotency_key=actor,schema_version='1.0.0',timestamp=utcnow().isoformat())
    envelope=issuer.issue(proposal,decision_id=actor,policy_version='harness-v0')
    assert harness.authorize(envelope).authorized
    assert harness.revalidate_for_execution(envelope).authorized
    assert not harness.revalidate_for_execution(envelope).authorized
    if actor not in harness.policy.pilot_agents:
        for action in ['executor.run','web.search','email.send']:
            proposal['action']=action
            signed=issuer.issue(proposal,decision_id=actor,policy_version='harness-v0',owner_approval_id='not-a-grant')
            assert not harness.authorize(signed).authorized
        proposal['action']='agent.infer'
        proposal['parameters']['allow_cloud']=True
        assert not harness.authorize(issuer.issue(proposal,decision_id=actor,policy_version='harness-v0')).authorized
