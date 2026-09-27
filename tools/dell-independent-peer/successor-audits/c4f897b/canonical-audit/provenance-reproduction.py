"""Offline independent counterexamples; no source mutation or production access."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
SOURCE=Path('/workspace/scratch/e46efedd3273/successor-c4f897b/source')
sys.path.insert(0,str(SOURCE))
from app.candidate_provenance import verify_candidate_package

BASE=Path(__file__).resolve().parent
WORK=Path(tempfile.mkdtemp(prefix='provenance-fixture-',dir=BASE))
ENV={'PATH':os.environ['PATH'],'HOME':str(WORK),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0','GIT_ALLOW_PROTOCOL':'file'}
os.environ.clear();os.environ.update(ENV)

def git(repo,*args):
    return subprocess.run(['git','-C',str(repo),*args],env=ENV,check=True,capture_output=True,text=True).stdout.strip()

def receipt(name,body):
    path=evidence/name;path.write_text(json.dumps(body,sort_keys=True))
    return {'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def resign(package):
    body={k:v for k,v in package.items() if k!='manifest_sha256'}
    package['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

repo=WORK/'repo';remote=WORK/'remote.git';evidence=WORK/'evidence'
repo.mkdir();remote.mkdir();evidence.mkdir()
git(remote,'init','--bare');git(repo,'init','-b','candidate');git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','user.name','Offline Fixture')
(repo/'source.txt').write_text('approved frozen source\n');git(repo,'add','.');git(repo,'commit','-m','Frozen fixture')
sha=git(repo,'rev-parse','HEAD');git(repo,'remote','add','origin',str(remote));git(repo,'push','origin','candidate')
artifact=WORK/'artifact.bin';artifact.write_bytes(b'Arbitrary artifact, not produced by any build of source.txt')
digest='sha256:'+hashlib.sha256(artifact.read_bytes()).hexdigest()
# Every receipt is fabricated here by the same actor. No test, verifier, security scan,
# image build, or independent reviewer produced any of these assertions.
package={'schema_version':'2.0','source_sha':sha,'branch':'candidate','artifact_digest':digest,'remote_sha':sha,
 'test_receipts':[receipt('tests.json',{'source_sha':sha,'exit_code':0,'passed':999,'failed':0,'skipped':0})],
 'verifier_receipt':receipt('verifier.json',{'source_sha':sha,'verdict':'ACCEPT','independent':True,'artifact_digest':digest}),
 'security_receipt':receipt('security.json',{'source_sha':sha,'verdict':'ACCEPT','secret_findings':0,'artifact_digest':digest})}
resign(package)
def check():
    return verify_candidate_package(package=package,repo=repo,artifact=artifact,evidence_root=evidence,remote_url=str(remote))
results=[]
results.append({'case':'fabricated_all_receipts_and_unbuilt_artifact','expected':'REJECT when establishing independent verification','actual':check(),'independent_actor_used':False,'tests_executed':0,'artifact_built':False})
(repo/'source.txt').write_text('tampered uncommitted contents\n')
results.append({'case':'dirty_checkout','expected':'REJECT when establishing frozen source integrity','worktree_status':git(repo,'status','--porcelain=v1'),'actual':check()})
git(repo,'add','.');git(repo,'commit','-m','Different checkout revision')
results.append({'case':'wrong_checkout_head','expected':'REJECT when establishing exact frozen checkout','actual_head':git(repo,'rev-parse','HEAD'),'claimed_source':sha,'actual':check()})
for field,bad_value in [('source_sha',[]),('remote_sha',42),('branch',42)]:
    original=package[field];package[field]=bad_value;resign(package)
    try: result=check()
    except Exception as e: result={'uncaught_exception':type(e).__name__,'message':str(e)}
    results.append({'case':'malformed_'+field,'expected':'REJECT without crash','actual':result})
    package[field]=original;resign(package)
report={'tested_candidate_sha':'c4f897b0d311a4c15be27df52f14d4c9e6ab5702','host':'Linux cloud, not physical Dell','production_touched':False,'network_used':False,'scope':'app.candidate_provenance.verify_candidate_package public function only; no production route to this function found','results':results}
(BASE/'provenance-reproduction.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
