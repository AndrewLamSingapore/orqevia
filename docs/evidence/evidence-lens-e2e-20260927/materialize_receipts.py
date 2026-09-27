"""Preserve each completed qualification task via the existing artifact sink.
Artifact existence does not verify any contained claim. Never retries a POST.
"""
import base64
import hashlib
import json
from qualify import ROOT, CASES, CONTAINER, binding, command, now, request, save

for case in CASES:
    initial=json.loads((ROOT/f'{case}-submitted.json').read_text(encoding='utf-8'))
    task=initial['response']['body']['id']
    if (ROOT/f'{case}-artifact-intent.json').exists():
        raise RuntimeError('Existing intent: inspect existing outcome; no POST retry')
    save(f'{case}-artifact-intent.json',{'at':now(),'task_id':task,'binding':binding(),
         'scope':'Preserve failed qualification; no claim/SSOT acceptance'})
    response=request('POST','/control/api/artifacts/from-task/'+task)
    save(f'{case}-artifact-created.json',{'at':now(),'response':response})
    if response['http_status'] != 201:
        print(json.dumps({'case':case,'artifact_state':'FAILED','http_status':response['http_status']}))
        continue
    meta=response['body']
    artifact=meta['artifact_id']
    program="""import base64,json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/control/api/artifacts/'+%r,timeout=20) as r:
 print(json.dumps({'http_status':r.status,'sha256_header':r.headers.get('X-Artifact-SHA256'),'base64':base64.b64encode(r.read()).decode()}))
""" % artifact
    retrieved=json.loads(command(['docker','exec','-i',CONTAINER,'python','-B','-'],input=program.encode()))
    raw=base64.b64decode(retrieved.pop('base64'))
    digest=hashlib.sha256(raw).hexdigest()
    target=ROOT/f'{case}-artifact.bin'
    with target.open('xb') as f:f.write(raw)
    retrieval={'at':now(),'task_id':task,'artifact_id':artifact,'bytes':len(raw),'sha256':digest,
               'metadata_sha256':meta.get('sha256'),'task_binding':meta.get('task_id'),
               **retrieved,'result':'PASS' if digest==meta.get('sha256')==retrieved['sha256_header'] and meta.get('task_id')==task else 'FAIL',
               'meaning':'Artifact byte integrity only; not evidence that model claims are true'}
    save(f'{case}-artifact-readback.json',retrieval)
    print(json.dumps({'case':case,**retrieval}))
