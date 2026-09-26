import json
import sqlite3

import pytest

from app.evidence_product import EvidenceLedger, action, canonical_bytes, make_receipt, validate_envelope, validate_receipt


def build(tmp_path, *, health=True):
    ledger=EvidenceLedger(tmp_path/'evidence.db')
    artifact=tmp_path/'deploy.log'; artifact.write_bytes(b'deploy command exit=0\n')
    with action(ledger,namespace='demo',objective='Deploy build 17',actor={'type':'SERVICE','id':'deploy-bot'},
                authority={'scope':'staging.deploy','source':'iam:role/deployer'},idempotency_key='create:17') as item:
        item.invoke(tool_ref='deployment-cli:v1',idempotency_key='invoke:17')
        invocation=item.observe('deployment-cli',{'exit_code':0},verification_ref='proc:17',idempotency_key='observe:invoke:17')
        health_obs=item.observe('health-endpoint',{'status':200 if health else 503},verification_ref='http:17',idempotency_key='observe:health:17')
        art=item.attach(artifact,idempotency_key='artifact:17')
        item.claim('Deployment command completed',state='OBSERVED',evidence_refs=[invocation],idempotency_key='claim:invoke:17')
        item.effect('Service healthy',state='VERIFIED' if health else 'FAILED',observation_refs=[health_obs],idempotency_key='effect:health:17')
        item.claim('Service is available',state='SYSTEM_VERIFIED' if health else 'CONTRADICTED',evidence_refs=[health_obs],idempotency_key='claim:health:17')
        item.verify('VERIFIED' if health else 'FAILED',[invocation,health_obs,art],idempotency_key='verify:17')
        return ledger,item,artifact


def test_standalone_happy_path_receipt_is_deterministic_and_prime_free(tmp_path):
    ledger,item,artifact=build(tmp_path)
    receipt=item.receipt()
    assert receipt==make_receipt(item.envelope)
    result=validate_receipt(receipt,artifact_bytes={item.envelope['artifacts'][0]['artifact_id']:artifact.read_bytes()})
    assert result=={'verdict':'VALID','errors':[],'unresolved':[]}
    assert 'prime' not in canonical_bytes(receipt).decode().lower()
    assert ledger.verify_chain(item.action_id,namespace='demo')['verdict']=='VALID'


def test_false_tool_success_is_not_verified_effect(tmp_path):
    _,item,artifact=build(tmp_path,health=False)
    result=validate_receipt(item.receipt(),artifact_bytes={item.envelope['artifacts'][0]['artifact_id']:artifact.read_bytes()})
    assert result['verdict']=='VALID'
    assert item.envelope['verification']['state']=='FAILED'
    assert item.envelope['effects'][0]['state']=='FAILED'


def test_artifact_tamper_and_receipt_tamper_are_detected(tmp_path):
    _,item,artifact=build(tmp_path); receipt=item.receipt(); aid=item.envelope['artifacts'][0]['artifact_id']
    assert validate_receipt(receipt,artifact_bytes={aid:b'tampered'})['verdict']=='INVALID'
    changed=json.loads(json.dumps(receipt)); changed['envelope']['actor']['id']='attacker'
    assert validate_receipt(changed,artifact_bytes={aid:artifact.read_bytes()})['verdict']=='INVALID'


def test_claim_reference_and_verified_effect_require_real_binding(tmp_path):
    _,item,_=build(tmp_path)
    broken=json.loads(json.dumps(item.envelope)); broken['claims'][0]['evidence_refs']=['missing']
    assert 'INVALID_REFERENCE:claim_evidence' in validate_envelope(broken)['errors']
    broken=json.loads(json.dumps(item.envelope)); broken['effects'][0]['observation_refs']=[]
    assert 'INVALID_REFERENCE:verified_effect_without_observation' in validate_envelope(broken)['errors']
    broken=json.loads(json.dumps(item.envelope)); broken['effects'][0]['observation_refs']=['missing']
    assert 'INVALID_REFERENCE:effect_observation' in validate_envelope(broken)['errors']
    broken=json.loads(json.dumps(item.envelope)); broken['verification']['evidence']=['missing']
    assert 'INVALID_REFERENCE:verification_evidence' in validate_envelope(broken)['errors']


def test_append_history_idempotency_namespace_and_chain_tamper(tmp_path):
    ledger,item,_=build(tmp_path); count=len(ledger.events(item.action_id,namespace='demo'))
    item.observe('health-endpoint',{'status':200},verification_ref='http:17',idempotency_key='observe:health:17')
    assert len(ledger.events(item.action_id,namespace='demo'))==count
    with pytest.raises(KeyError): ledger.get(item.action_id,namespace='other-customer')
    with sqlite3.connect(ledger.path) as db: db.execute("update evidence_events set payload_json='{}' where action_id=? and sequence=(select max(sequence) from evidence_events where action_id=?)",(item.action_id,item.action_id))
    assert ledger.verify_chain(item.action_id,namespace='demo')['verdict']=='INVALID'


def test_direct_current_envelope_tamper_breaks_chain_binding(tmp_path):
    ledger,item,_=build(tmp_path)
    with sqlite3.connect(ledger.path) as db:
        raw=json.loads(db.execute('select envelope_json from evidence_actions where action_id=?',(item.action_id,)).fetchone()[0])
        raw['actor']['id']='attacker'
        db.execute('update evidence_actions set envelope_json=? where action_id=?',(json.dumps(raw),item.action_id))
    assert ledger.verify_chain(item.action_id,namespace='demo')['verdict']=='INVALID'


def test_partial_cannot_masquerade_as_verified(tmp_path):
    _,item,_=build(tmp_path)
    changed=json.loads(json.dumps(item.envelope)); changed['verification']={'state':'VERIFIED','evidence':[]}
    changed['claims'].append({'claim_id':'unbound','text':'user accepted','state':'SYSTEM_VERIFIED','evidence_refs':[]})
    assert validate_envelope(changed)['verdict']=='INVALID'


def test_sdk_rejects_nonexistent_verification_reference(tmp_path):
    ledger=EvidenceLedger(tmp_path/'evidence.db')
    with action(ledger,namespace='demo',objective='x',actor={'type':'SERVICE','id':'x'},authority={'scope':'x','source':'iam'},idempotency_key='x') as item:
        with pytest.raises(ValueError,match='verification_evidence'):
            item.verify('VERIFIED',['nonexistent'],idempotency_key='verify:x')


def test_supersession_appends_and_keeps_original(tmp_path):
    ledger,first,_=build(tmp_path,health=False)
    second=ledger.create(namespace='demo',objective='Correct verification context',actor={'type':'AUDITOR','id':'auditor-2'},
                         authority={'scope':'verify','source':'policy:v1'},idempotency_key='create:corrected')
    from app.evidence_product import EvidenceAction
    correction=EvidenceAction(ledger,'demo',second)
    correction.relate('CORRECTS',first.action_id,reason='first used wrong health endpoint',idempotency_key='relate:corrected')
    assert ledger.get(first.action_id,namespace='demo')['verification']['state']=='FAILED'
    assert correction.envelope['relations'][0]['record_id']==first.action_id
