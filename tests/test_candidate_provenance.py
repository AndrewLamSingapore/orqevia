import hashlib,json,subprocess
from pathlib import Path

import pytest

from app.candidate_provenance import verify_candidate_package


def git(path,*args):
    return subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True,text=True).stdout.strip()


def write_receipt(root,name,value):
    path=root/name;path.write_text(json.dumps(value,sort_keys=True),encoding='utf-8')
    return {'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def package_fixture(tmp_path):
    repo=tmp_path/'repo';remote=tmp_path/'remote.git';evidence=tmp_path/'evidence';evidence.mkdir()
    subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
    subprocess.run(['git','init','-b','candidate',str(repo)],check=True,capture_output=True)
    git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','user.name','Fixture')
    (repo/'source.txt').write_text('candidate',encoding='utf-8');git(repo,'add','.');git(repo,'commit','-m','candidate')
    source=git(repo,'rev-parse','HEAD');git(repo,'remote','add','origin',str(remote));git(repo,'push','-u','origin','candidate')
    artifact=tmp_path/'candidate.tar';artifact.write_bytes(b'immutable candidate')
    digest='sha256:'+hashlib.sha256(artifact.read_bytes()).hexdigest()
    common={'source_sha':source}
    tests=write_receipt(evidence,'tests.json',{**common,'exit_code':0,'passed':12,'failed':0,'skipped':0})
    verifier=write_receipt(evidence,'verifier.json',{**common,'verdict':'ACCEPT','independent':True,'artifact_digest':digest})
    security=write_receipt(evidence,'security.json',{**common,'verdict':'ACCEPT','secret_findings':0,'artifact_digest':digest})
    package={'schema_version':'2.0','source_sha':source,'branch':'candidate','artifact_digest':digest,
        'remote_sha':source,'test_receipts':[tests],'verifier_receipt':verifier,'security_receipt':security}
    canonical={key:package[key] for key in sorted(package)}
    package['manifest_sha256']=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return package,repo,artifact,evidence,str(remote)


def verify(values):
    package,repo,artifact,evidence,remote=values
    return verify_candidate_package(package=package,repo=repo,artifact=artifact,evidence_root=evidence,remote_url=remote)


def resign_manifest(package):
    canonical={key:package[key] for key in sorted(package) if key!='manifest_sha256'}
    package['manifest_sha256']=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def test_complete_effect_bound_package_is_accepted(package_fixture):
    assert verify(package_fixture)['verdict']=='ACCEPT'


@pytest.mark.parametrize('mutation',[
    'wrong_source','stale_remote','artifact_changed','fabricated_tests','hidden_skip',
    'builder_verifier','security_secret','manifest_changed',
])
def test_aef_red_team_rejects_false_success(package_fixture,mutation):
    package,repo,artifact,evidence,remote=package_fixture
    if mutation=='wrong_source':package['source_sha']='0'*40
    elif mutation=='stale_remote':package['remote_sha']='1'*40
    elif mutation=='artifact_changed':artifact.write_bytes(b'changed')
    elif mutation=='fabricated_tests':package['test_receipts'][0]['sha256']='2'*64
    elif mutation=='hidden_skip':
        value=json.loads((evidence/'tests.json').read_text());value['skipped']=1
        package['test_receipts'][0]=write_receipt(evidence,'tests.json',value)
    elif mutation=='builder_verifier':
        value=json.loads((evidence/'verifier.json').read_text());value['independent']=False
        package['verifier_receipt']=write_receipt(evidence,'verifier.json',value)
    elif mutation=='security_secret':
        value=json.loads((evidence/'security.json').read_text());value['secret_findings']=1
        package['security_receipt']=write_receipt(evidence,'security.json',value)
    elif mutation=='manifest_changed':package['manifest_sha256']='3'*64
    if mutation!='manifest_changed':resign_manifest(package)
    assert verify((package,repo,artifact,evidence,remote))['verdict']=='REJECT'
