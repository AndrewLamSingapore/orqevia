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


def test_evidence_bound_verifier_receipt_is_accepted(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path/'data'))
    outcome=build_verify(root=tmp_path/'run',objective='fixture',builder=lambda *_:'candidate',
        verifier=valid_receipt,max_attempts=1)
    assert outcome['state']=='VERIFIED_CANDIDATE'


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
