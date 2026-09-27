import hashlib

import pytest

from app.engineering_loop import build_verify


def valid_receipt(path):
    return {
        'passed':True,
        'verdict':'ACCEPT',
        'verifier':'a18',
        'independent':True,
        'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'checks':[{'name':'content','status':'PASS','evidence_ref':'fixture:executed'}],
    }


def test_digest_bound_verifier_receipt_is_only_structurally_valid(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path/'data'))
    outcome=build_verify(root=tmp_path/'run',objective='fixture',builder=lambda *_:'candidate',
        verifier=valid_receipt,max_attempts=1)
    assert outcome['state']=='RECEIPT_STRUCTURALLY_VALID'
    assert outcome['independent_verification'] is False
    assert outcome['production_acceptance'] is False


def test_structured_fabricated_receipt_cannot_establish_independent_verification(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path/'data'))
    nonexistent=tmp_path/'never-executed-verification.json'
    def fabricated(path):
        value=valid_receipt(path)
        value['checks']=[{'name':'plausible-but-never-executed','status':'PASS','evidence_ref':str(nonexistent)}]
        return value
    outcome=build_verify(root=tmp_path/'run',objective='adversarial fixture',builder=lambda *_:'candidate',
        verifier=fabricated,max_attempts=1)
    assert not nonexistent.exists()
    assert outcome['state']=='RECEIPT_STRUCTURALLY_VALID'
    assert outcome['independent_verification'] is False
    assert outcome['production_acceptance'] is False
    assert outcome['attempts'][0]['verification']['independent_verification'] is False
    observation=outcome['attempts'][0]['observation']
    assert observation['receipt_structurally_valid'] is True
    assert observation['final_artifact_validation'] is None


@pytest.mark.parametrize('mutation',[
    {'passed':True},
    {'passed':True,'verdict':'ACCEPT','verifier':'a17','independent':True,
     'candidate_sha256':'0'*64,'checks':[{'name':'x','status':'PASS','evidence_ref':'claim'}]},
    {'passed':True,'verdict':'ACCEPT','verifier':'a18','independent':True,
     'candidate_sha256':'0'*64,'checks':[{'name':'x','status':'PASS','evidence_ref':'claim'}]},
    {'passed':True,'verdict':'ACCEPT','verifier':'a18','independent':True,
     'candidate_sha256':None,'checks':[]},
    {'passed':True,'verdict':'ACCEPT','verifier':'a18','independent':True,
     'candidate_sha256':None,'checks':[{'name':'x','status':'SKIPPED','evidence_ref':'claim'}]},
])
def test_fabricated_or_incomplete_verifier_success_fails_closed(tmp_path,monkeypatch,mutation):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path/'data'))
    def verifier(path):
        value=dict(mutation)
        if value.get('candidate_sha256') is None:
            value['candidate_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        return value
    outcome=build_verify(root=tmp_path/'run',objective='fixture',builder=lambda *_:'candidate',
        verifier=verifier,max_attempts=1)
    assert outcome['state']=='VALIDATION_FAILED'
    assert outcome['attempts'][0]['verification']['verdict']=='REJECT'
    assert outcome['attempts'][0]['verification']['violations']
