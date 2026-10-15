"""Start the private local AI adapter using existing device/runtime authority.

Intended for the existing local AI virtual environment and a hidden per-user
startup shortcut. Credentials stay in process memory and never enter argv/logs.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

RUNTIME=Path(os.environ.get('ORQEVIA_LOCAL_RUNTIME',str(Path.home()/'Documents/ABEX/runtime/orqevia-local-knowledge')))
DOCKER=Path('C:/Program Files/Docker/Docker/resources/bin/docker.exe')

def main():
    config=json.loads((RUNTIME/'CURRENT.json').read_text(encoding='utf8'))
    release=(RUNTIME/'releases'/config['release']).resolve()
    if not release.is_relative_to((RUNTIME/'releases').resolve()):raise RuntimeError('Invalid local release path')
    result=subprocess.run([str(DOCKER),'inspect','prime-epoch-20260919-interface-1'],capture_output=True,text=True,timeout=20,check=True)
    env=dict(item.split('=',1) for item in json.loads(result.stdout)[0]['Config']['Env'])
    token=env.get('PRIME_SPINE_TOKEN','');account=env.get('PRIME_PWA_OWNER_ACCOUNT_ID','')
    if len(token)<16 or not account:raise RuntimeError('Existing owner service authority unavailable')
    request=urllib.request.Request('http://127.0.0.1:8150/health',headers={'Authorization':'Bearer '+token,'X-ORQEVIA-Owner':hashlib.sha256(account.encode()).hexdigest()})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=3) as response:
            if response.status==200:return
    except OSError:pass
    child_env=os.environ.copy();child_env.update({
        'ORQEVIA_SERVICE_TOKEN':token,'ORQEVIA_OWNER_ACCOUNT':account,
        'ORQEVIA_LOCAL_AI_ROOT':config['data_root'],'HF_HUB_OFFLINE':'1',
        'ORQEVIA_LOCAL_RELEASE':config['release'],
        'TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
        'PYTHONUTF8':'1','OMP_NUM_THREADS':'2','TOKENIZERS_PARALLELISM':'false',
        'PYTHONDONTWRITEBYTECODE':'1'})
    logs=RUNTIME/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'service.stdout.log').open('ab') as out,(logs/'service.stderr.log').open('ab') as err:
        process=subprocess.Popen([sys.executable,'-B','-m','uvicorn','app.local_knowledge_service:app',
            '--host','127.0.0.1','--port','8150','--workers','1','--no-proxy-headers','--log-level','warning'],
            cwd=release,env=child_env,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (RUNTIME/'service.pid').write_text(str(process.pid),encoding='ascii')

if __name__=='__main__':main()
