"""Public-only local audit of original initialization evidence; never admission.

No signing callback, credentials, network, dispatch, timestamp renewal or
certification output. Local probe timestamps exist only in memory to exercise
the unchanged protected oracle; they are not protected validation timestamps.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from scripts.agent_cert_reviewed_signing import _contract_event_review
from scripts.sign_admitted_agent_cases import unchanged_reviewer_code, unchanged_runtime_reviewer_code

MAIN='d9a4e0bdd733a4908e9fa239f6b24bef3c2dce79'
ORIGINAL='61335a96293be627b240488debfb94294cdf9b34'
ROOT=Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def probe_case(entry, primary, reviewed, *, local_audit_at):
    """Transient local validation probe, not a certifiable record."""
    if type(local_audit_at) is not datetime or local_audit_at.tzinfo is None:
        raise ValueError('AWARE_LOCAL_AUDIT_TIME_REQUIRED')
    if (hashlib.sha256(primary).hexdigest()!=entry['execution_sha256']
            or hashlib.sha256(reviewed).hexdigest()!=entry['review_sha256']):
        raise ValueError('ORIGINAL_PACKAGE_HASH_CHANGED')
    row=dict(entry['record_established_fields'])
    stamp=local_audit_at.astimezone(timezone.utc)
    # Required only as oracle input, never emitted/installed/admitted. Actual
    # protected validation will independently establish its own fixed boundary.
    row.update(certification_test='baseline-initialization',
        test_version=json.loads(reviewed)['review_test_version'],
        certified_at=stamp.isoformat(),last_revalidated=stamp.isoformat(),
        expires_at=(stamp+timedelta(hours=24)).isoformat())
    _contract_event_review(row,primary,reviewed,
        source_revision=entry['execution_source_revision'],
        runtime_image_id=entry['runtime_image_id'],
        reviewer_code_revision=entry['reviewer_code_revision'],
        now=stamp,initialization=True)
    return {'agent_id':row['agent_id'],'capability_id':row['capability_id'],
        'execution_sha256':entry['execution_sha256'],'review_sha256':entry['review_sha256'],
        'original_oracle_validation':'PASS','signature':'NOT_PERFORMED',
        'certification_record_created':False}


def audit(plan, *, local_audit_at, root=ROOT):
    if len(plan['cases'])!=29 or plan['case_count']!=29:
        raise ValueError('EXACT_29_CASE_PACKAGE_REQUIRED')
    unchanged_reviewer_code(root,MAIN)
    unchanged_runtime_reviewer_code(root,ORIGINAL)
    results=[]
    seen=set()
    for entry in plan['cases']:
        row=entry['record_established_fields']
        key=(row['agent_id'],row['capability_id'])
        if key in seen:raise ValueError('DUPLICATE_OWNED_PAIR')
        seen.add(key)
        path=root/entry['evidence_directory']/row['agent_id']
        results.append(probe_case(entry,(path/'execution.json').read_bytes(),
                                  (path/'review.json').read_bytes(),local_audit_at=local_audit_at))
    from app.agent_registry import load_agent_registry
    expected={(a['id'],c) for a in load_agent_registry()['agents'] for c in a['capability_requirements']}
    if seen!=expected:raise ValueError('EXACT_OWNERSHIP_POPULATION_REQUIRED')
    return {'schema':'prime.initialization-local-oracle-audit.v1',
        'time_scope':'LOCAL_NONPROTECTED_AUDIT_ONLY',
        'local_audit_at':local_audit_at.isoformat(),'protected_validation_at':None,
        'cases':results,'source_closure':'47_VERIFIER_FILES_46_ORIGINAL_RUNTIME_FILES_PASS',
        'signatures':0,'certification_records':0,'runtime_calls':0,'l7_awarded':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    args=parser.parse_args()
    value=audit(json.loads(args.plan.read_bytes()),local_audit_at=datetime.now(timezone.utc))
    print(json.dumps(value,sort_keys=True))


if __name__=='__main__':main()
