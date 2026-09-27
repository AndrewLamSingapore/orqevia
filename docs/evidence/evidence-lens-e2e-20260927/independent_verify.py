"""Independent GET-only evidence challenge. No objective/artifact creation or repair.

Only new local receipt files are written. Production queries use GET, Docker
inspection, SQLite mode=ro plus query_only, and source-file metadata reads.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
RUN_ID = dt.datetime.now(dt.timezone.utc).strftime('%H%M%S')
CONTAINER = 'prime-epoch-20260919-prime-1'
SOURCE = 'b171253566e7c879283d2aacf699ae6c1ec8988e'
IMAGE = 'sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5'
TASKS = {
    'A': '0d23cfb7-362b-4e9e-aaa7-a77848483c9a',
    'B': 'df319f44-4832-45a3-8602-e786bda257ca',
    'C': '016f927b-1a69-44ec-ab6a-e939214e220a',
    'D': '8774a8ab-5961-40e1-9ca6-f49a34ba04b3',
    'E': '6e0c6b3d-e20b-42d8-bfe5-6180c5c06f8e',
    'F': '31117c8d-dd30-494b-94c2-bc456eb29387',
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def load(path):
    return json.loads(path.read_bytes())

def run(args, raw=None):
    p = subprocess.run(args, input=raw, capture_output=True, timeout=45)
    if p.returncode:
        raise RuntimeError(f'Command failed {p.returncode}: {p.stderr[:500]!r}')
    return p.stdout

def inside(program):
    return json.loads(run(['docker', 'exec', '-i', CONTAINER, 'python', '-B', '-'], program.encode()))

def save(name, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode() + b'\n'
    with (ROOT/name).open('xb') as f:
        f.write(raw)
    return {'file': name, 'bytes': len(raw), 'sha256': sha(raw)}

def get(path, artifact=False):
    if not path.startswith(('/control/api/objectives/', '/control/api/artifacts/')):
        raise ValueError('GET path out of scope')
    return inside('''import hashlib,json,urllib.request
request=urllib.request.Request('http://127.0.0.1:8000'+%r,method='GET',headers={'Origin':'http://127.0.0.1:8000'})
with urllib.request.urlopen(request,timeout=25) as r:
 raw=r.read()
 out={'http_status':r.status,'bytes':len(raw),'body_sha256':hashlib.sha256(raw).hexdigest()}
 try:out['body']=json.loads(raw)
 except ValueError as e:
  out['json_error']=str(e)
  if %r:out['text']=raw.decode('utf-8')
 if %r:out['artifact_sha256_header']=r.headers.get('X-Artifact-SHA256')
print(json.dumps(out,ensure_ascii=False))
''' % (path, artifact, artifact))

def containers():
    names=[CONTAINER, 'prime-epoch-20260919-interface-1', 'prime-epoch-20260919-ollama-1']
    values=json.loads(run(['docker','inspect',*names]))
    return [{
        'name':v['Name'], 'id':v['Id'], 'image_id':v['Image'],
        'image_tag':v['Config']['Image'],
        'source_revision':v['Config'].get('Labels',{}).get('org.opencontainers.image.revision'),
        'running':v['State']['Running'], 'started_at':v['State']['StartedAt'],
        'health':v['State'].get('Health',{}).get('Status'),
        'oom_killed':v['State']['OOMKilled'], 'restart_count':v['RestartCount'],
    } for v in values]

receipt={'at':dt.datetime.now(dt.timezone.utc).isoformat(),
         'verifier':'INDEPENDENT_SUBAGENT_GET_ONLY',
         'production_mutated':False, 'new_objectives_submitted':0,
         'before':containers(), 'cases':[], 'preserved_inputs':[]}
for v in receipt['before'][:2]:
    assert v['image_id']==IMAGE and v['source_revision']==SOURCE
    assert v['running'] and v['health']=='healthy' and not v['oom_killed']

for key,task in TASKS.items():
    oldpath=sorted(ROOT.glob(f'{key}-read-*.json'))[-1]
    old=load(oldpath)['response']['body']
    live=get('/control/api/objectives/'+task)
    saved=save('independent-'+RUN_ID+'-'+key+'-live-task.json',live)
    result=live['body']['result']; metadata=live['body']['execution_metadata']
    creation=load(ROOT/f'{key}-artifact-created.json')['response']['body']
    artifact=get('/control/api/artifacts/'+creation['artifact_id'],artifact=True)
    artifact_saved=save('independent-'+RUN_ID+'-'+key+'-live-artifact.json',artifact)
    original=(ROOT/f'{key}-artifact.bin').read_bytes()
    if creation['type']=='json':
        body_binding=artifact.get('body',{}).get('id')==task and artifact.get('body',{}).get('execution_metadata',{}).get('task_id')==task
    elif creation['type']=='markdown':
        header=artifact.get('text','').split('## Model-generated content',1)[0]
        body_binding=(re.findall(r'^- Task UUID: `([^`]+)`$',header,re.M)==[task]
                      and re.findall(r'^- Runtime source revision: `([^`]+)`$',header,re.M)==[SOURCE]
                      and 'These fields come from PRIME system records.' in header)
    else:
        body_binding=False
    checks={
        'task_uuid_matches':live['body']['id']==task==metadata['task_id'],
        'complete_response_matches_preserved':live['body']==old,
        'execution_metadata_matches_preserved':metadata==old['execution_metadata'],
        'result_matches_preserved':result==old['result'],
        'runtime_matches_live':metadata['runtime']['source_revision']==SOURCE and metadata['runtime']['image_digest']==IMAGE,
        'artifact_sha256_matches':artifact['body_sha256']==sha(original)==creation['sha256']==artifact['artifact_sha256_header'],
        'artifact_size_matches':artifact['bytes']==len(original)==creation['bytes'],
        'artifact_creation_bound_to_task':creation['task_id']==task,
        'artifact_body_bound_to_task':body_binding,
        'model_cannot_promote_truth':result.get('type')!='MODEL_CONTENT' or (result.get('authoritative') is False and result.get('may_update_truth_plane') is False and result.get('verification_status')=='VERIFY_REQUIRED'),
    }
    receipt['cases'].append({'case':key,'task_id':task,'checks':checks,
        'state':live['body']['state'],'result_type':result.get('type'),
        'verification_status':result.get('verification_status'),
        'system_fact_statuses':[s.get('dispatch',{}).get('system_fact',{}).get('status') for s in live['body']['steps']],
        'live_task_receipt':saved,'live_artifact_receipt':artifact_saved,
        'original_artifact_sha256':sha(original),'original_artifact_bytes':len(original)})
    for path in sorted(ROOT.glob(key+'-*')):
        if path.is_file():
            raw=path.read_bytes()
            receipt['preserved_inputs'].append({'file':path.name,'bytes':len(raw),'sha256':sha(raw)})

receipt['database']=inside('''import json,sqlite3,time
out={}
for name in ['objectives.db','compute-queue.db','compute-ledger.db','offline-queue.db','jarvis-memory.db','prime-spine.db','pwa-sessions.db','interface.db']:
 with sqlite3.connect('file:/data/'+name+'?mode=ro',uri=True,timeout=3) as db:
  db.execute('PRAGMA query_only=ON')
  db.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,10000)
  deadline=time.monotonic()+6
  out[name]={'quick_check':[r[0] for r in db.execute('PRAGMA quick_check')]}
  if name=='compute-queue.db':
   out[name]['tables']=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
  if name=='pwa-sessions.db':
   now=time.time()
   for table in ['devices','sessions']:
    out[name][table+'_by_role']=[{'role':r[0],'total':r[1],'valid':r[2],'canonical_accounts':r[3]} for r in db.execute('SELECT role,count(*),sum(CASE WHEN revoked=0 AND expires>? THEN 1 ELSE 0 END),count(distinct owner_account_id) FROM '+table+' GROUP BY role',(now,))]
   out[name]['unused_unexpired_enrollment_codes']=db.execute('SELECT count(*) FROM pairing WHERE used=0 AND expires>?',(now,)).fetchone()[0]
print(json.dumps(out))
''')
receipt['runtime_governance_paths']=inside('''import json,hashlib
from pathlib import Path
root=Path('/app')
out={}
for name in ['governance/golden-gen1-manifest.json','governance/golden-gen2-manifest.json','governance/phase2-state.json','config/agent_registry.json']:
 p=root/name
 out[name]={'exists':p.exists()}
 if p.is_file():
  raw=p.read_bytes();out[name].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
  if name.endswith('agent_registry.json'):out[name]['agents']=len(json.loads(raw)['agents'])
print(json.dumps(out))
''')
receipt['after']=containers()
receipt['same_runtime_before_after']=receipt['before']==receipt['after']
receipt['transport_binding_integrity_pass']=all(all(x['checks'].values()) for x in receipt['cases'])
receipt['semantic_qualification_verdict']='FAIL'
receipt['semantic_note']='C/E/F fabricate or accept unsupported evidence within non-authoritative MODEL_CONTENT; B/D abstain rather than retrieve canonical evidence; A count is supported but no complete claim-record envelope is returned. COMPLETED and artifact integrity are not semantic verification.'
receipt['verifier_correction']='Prior independent receipt preserved. Its artifact body checks incorrectly assumed every artifact was JSON. C/E/F are declared Markdown and have canonical task UUID/runtime source headers separated from model content. This v2 validates both declared formats; artifact hash and byte equality checks are unchanged.'
stamp=save('INDEPENDENT-GET-VERIFICATION-V2-20260927.json',receipt)
print(json.dumps({'receipt':stamp,'transport_binding_integrity_pass':receipt['transport_binding_integrity_pass'],'same_runtime_before_after':receipt['same_runtime_before_after'],'semantic_verdict':receipt['semantic_qualification_verdict'],'cases':receipt['cases'],'database':receipt['database'],'runtime_governance_paths':receipt['runtime_governance_paths']},ensure_ascii=False,indent=2))
