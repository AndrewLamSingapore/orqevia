import pytest
from app.action_harness import ActionEnvelopeIssuer,ActionHarness,utcnow
from app.connector_sdk import LegacyConnectorRegistry as ConnectorRegistry,Sink,payload_digest
from app.host_guard import effect_digest


def test_registered_sink_uses_existing_authority_and_denies_bypasses(tmp_path):
    key=b'isolated-connector-authority-key!'
    issuer=ActionEnvelopeIssuer(key)
    harness=ActionHarness(tmp_path/'harness.db',{issuer.key_id:key})
    registry=ConnectorRegistry()
    calls=[]
    registry.register(Sink('test','web.search','R0','test fixture read',True,'LOCAL_ONLY','read'),
                      lambda payload:calls.append(payload) or {'read':'ok'})
    registry.register(Sink('test','executor.run','consequential','fixture-only effect',True,'LOCAL_ONLY','execute'),
                      lambda payload:calls.append(payload) or {'effect':'fixture only'})
    payload={'value':42}
    def envelope(action='web.search',capability='read',approval=None):
        proposal=dict(tenant_id='personal',actor_id='a14',actor_type='reasoner',action=action,
                      parameters={'connector_id':'test','payload_sha256':payload_digest(payload),'capability':capability},
                      context={'risk':'advisory'},correlation_id='test',idempotency_key=str(utcnow()),
                      schema_version='1.0.0',timestamp=utcnow().isoformat())
        if approval:
            proposal['context']['effect_class']='HOST_HIGH_RISK'
            proposal['context']['approved_effect_digest']=effect_digest(proposal)
        result=issuer.issue(proposal,decision_id='test',policy_version='harness-v0',owner_approval_id=approval)
        harness.authorize(result)
        return result
    signed=envelope()
    assert registry.execute(harness,signed,payload)=={'read':'ok'}
    with pytest.raises(PermissionError):registry.execute(harness,signed,payload)
    with pytest.raises(PermissionError):registry.execute(harness,envelope(),{'value':43})
    with pytest.raises(PermissionError):registry.execute(harness,envelope('unknown'),payload)
    with pytest.raises(PermissionError):registry.execute(harness,envelope(capability='wrong'),payload)
    with pytest.raises(PermissionError):registry.execute(harness,envelope('executor.run','execute'),payload)
    revoked=envelope()
    harness.revoke(revoked['authorization']['lease_id'],reason='stop',revoked_by='test')
    with pytest.raises(PermissionError):registry.execute(harness,revoked,payload)
    assert registry.execute(harness,envelope('executor.run','execute','fixture-owner-grant'),payload)['effect']=='fixture only'
    assert len(calls)==2
