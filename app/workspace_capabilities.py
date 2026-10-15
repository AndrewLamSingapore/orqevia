"""Existing safe construction capabilities and persisted owner workspace drafts.

No arbitrary command, path, agent activation or deployment is accepted here.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from .local_knowledge import atomic_json,now,worker_python,worker_options

LOCK=threading.RLock()

def ideas(root,value=None):
    path=Path(root)/'operations/workspace-ideas.json'
    with LOCK:
        records=json.loads(path.read_text(encoding='utf8')) if path.exists() else []
        if value is not None:
            if not isinstance(value,dict) or set(value)!={'title','body'} or not isinstance(value['title'],str) or not isinstance(value['body'],str):raise ValueError('An idea title and body are required')
            if not 1<=len(value['title'].strip())<=200 or len(value['body'])>8000 or len(records)>=200:raise ValueError('Idea length or storage budget exceeded')
            records.append({'id':uuid.uuid4().hex,'title':value['title'].strip(),'body':value['body'],'created_at':now(),'state':'DRAFT'})
            atomic_json(path,records)
        return {'ideas':records}

def scaffold(value):
    from .scaffolding import ScaffoldingEngine
    if not isinstance(value,dict) or set(value)-{'kind','name','description'} or value.get('kind') not in {'project','verification'}:raise ValueError('Supported generators: project and verification')
    name=value.get('name');description=value.get('description','')
    if not isinstance(name,str) or not 1<=len(name)<=100 or not isinstance(description,str) or len(description)>2000:raise ValueError('A bounded project name and description are required')
    engine=ScaffoldingEngine()
    result=engine.project({'name':name,'description':description}) if value['kind']=='project' else engine.verification({'target_name':name})
    return {'kind':result.kind,'artifact_id':result.artifact_id,'fingerprint':result.fingerprint(),
        'files':result.files,'warnings':result.warnings,'execution_performed':False,
        'disclosure':'Reviewable generated candidate. Code and placeholder test templates have not been executed or deployed.'}

def validate_local_pipeline(root):
    base=Path(__file__).resolve().parents[1]
    target=Path(root)/'operations/validation'/uuid.uuid4().hex;target.mkdir(parents=True,exist_ok=False)
    command=[worker_python(),'-B','-m','pytest','tests/test_local_knowledge.py','-q','--basetemp='+str(target/'fixtures')]
    p=subprocess.run(command,cwd=base,capture_output=True,text=True,encoding='utf8',timeout=75,**worker_options())
    result={'at_utc':now(),'status':'PASS' if p.returncode==0 else 'FAIL','exit_code':p.returncode,
        'suite':'fixed local document/index regression tests','output_tail':(p.stdout+'\n'+p.stderr)[-12000:],
        'classification':'ISOLATED_FIXTURES_NOT_PRODUCTION_CORPUS_OR_MODEL_ACCEPTANCE'}
    atomic_json(target/'result.json',result);atomic_json(Path(root)/'operations/latest-validation.json',result)
    return result

def workspace_status(root):
    root=Path(root)
    def read(name):
        p=root/'operations'/name
        return json.loads(p.read_text(encoding='utf8')) if p.is_file() else {'status':'UNAVAILABLE','reason':'No measured release record supplied'}
    return {'observed_at':now(),'primary_interface':'/pwa/','local_knowledge':'SHARED_EXISTING_V2_V3_PIPELINE',
        'construction':'EXISTING_SCAFFOLDING_ENGINE_CANDIDATES_ONLY','validation':read('latest-validation.json'),
        'release':read('workspace-release.json'),
        'boundaries':{'arbitrary_shell':False,'remote_deploy':False,'agent_registry_required':False,'cloud_required':False}}
