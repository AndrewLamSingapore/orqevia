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


def test_historical_package_rejects_current_changed_source_closure():
    plan,_,_,_=evidence()
    with pytest.raises(ValueError,match='Protected reviewed-case admission rejected'):
        audit(plan,local_audit_at=datetime.now(timezone.utc))


def test_all_29_historical_originals_are_intact_but_not_current_oracle_admissions():
    plan,_,_,_=evidence()
    now=datetime.now(timezone.utc)
    seen=set()
    for entry in plan['cases']:
        row=entry['record_established_fields']
        seen.add((row['agent_id'],row['capability_id']))
        path=ROOT/entry['evidence_directory']/row['agent_id']
        primary=(path/'execution.json').read_bytes()
        reviewed=(path/'review.json').read_bytes()
        assert hashlib.sha256(primary).hexdigest()==entry['execution_sha256']
        assert hashlib.sha256(reviewed).hexdigest()==entry['review_sha256']
        # Historical observations remain immutable, not fresh current admissions.
        with pytest.raises(ValueError,match='IDENTITY_ORACLE_FAILED'):
            probe_case(entry,primary,reviewed,local_audit_at=now)
    assert len(seen)==29


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
