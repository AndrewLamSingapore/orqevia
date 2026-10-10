import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import pytest
from scripts.audit_initialization_package import audit,probe_case,ROOT

PLAN=ROOT/'governance/agent-cert-initialization-proposed-fields-20261010.json'


def evidence():
    plan=json.loads(PLAN.read_bytes())
    entry=plan['cases'][0]
    path=ROOT/entry['evidence_directory']/entry['record_established_fields']['agent_id']
    return plan,entry,(path/'execution.json').read_bytes(),(path/'review.json').read_bytes()


def test_all_29_original_cases_pass_unchanged_protected_oracle_without_claims():
    plan,_,_,_=evidence()
    result=audit(plan,local_audit_at=datetime.now(timezone.utc))
    assert len(result['cases'])==29
    assert result['signatures']==result['certification_records']==result['runtime_calls']==0
    assert result['protected_validation_at'] is None
    assert result['time_scope']=='LOCAL_NONPROTECTED_AUDIT_ONLY'


def test_raw_hash_tampering_denied():
    _,entry,primary,review=evidence()
    with pytest.raises(ValueError,match='HASH_CHANGED'):
        probe_case(entry,primary+b' ',review,local_audit_at=datetime.now(timezone.utc))


def test_rehashed_wrong_registered_peer_still_denied():
    _,entry,primary,review=evidence()
    entry=copy.deepcopy(entry)
    body=json.loads(review)
    body['observations']['reviewer_execution']['dispatch']['agent_id']='a01'
    changed=json.dumps(body,sort_keys=True).encode()
    entry['review_sha256']=hashlib.sha256(changed).hexdigest()
    with pytest.raises(ValueError):
        probe_case(entry,primary,changed,local_audit_at=datetime.now(timezone.utc))


def test_local_time_cannot_precede_original_peer_review():
    _,entry,primary,review=evidence()
    with pytest.raises(ValueError):
        probe_case(entry,primary,review,local_audit_at=datetime(2026,10,9,tzinfo=timezone.utc))
