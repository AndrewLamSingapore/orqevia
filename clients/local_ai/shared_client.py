"""Internal diagnostic client of the primary workspace's shared application API.

Uses existing local OS/service authority only. Never place headers in Streamlit
session state, browser code, command arguments or printed diagnostics.
"""
import hashlib,json,pathlib,subprocess,urllib.request

class SharedKnowledgeClient:
    def __init__(self):
        self.base='http://127.0.0.1:8150/'
        p=subprocess.run(['C:/Program Files/Docker/Docker/resources/bin/docker.exe','inspect','prime-epoch-20260919-interface-1'],capture_output=True,text=True,timeout=20,check=True)
        env=dict(item.split('=',1) for item in json.loads(p.stdout)[0]['Config']['Env'])
        token=env.get('PRIME_SPINE_TOKEN','');owner=env.get('PRIME_PWA_OWNER_ACCOUNT_ID','')
        if len(token)<16 or not owner:raise RuntimeError('Existing local service authority unavailable')
        self._headers={'Authorization':'Bearer '+token,'X-ORQEVIA-Owner':hashlib.sha256(owner.encode()).hexdigest()}
    def call(self,action,value=None,*,file=None):
        if action not in {'health','documents','retrieve','answer','reindex','ingest'}:raise ValueError('Unsupported diagnostic operation')
        headers={**self._headers,'Content-Type':'application/json'}
        body=json.dumps(value).encode() if value is not None else None
        if action=='ingest':
            from urllib.parse import quote
            path=pathlib.Path(file);size=path.stat().st_size
            if not 0<size<=8*1024*1024:raise ValueError('Document exceeds upload bounds')
            body=path.read_bytes();headers.update({'X-Document-Name':quote(path.name),'Content-Type':'application/octet-stream'})
        request=urllib.request.Request(self.base+action,headers=headers,data=body)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=175) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('Response bound exceeded')
            return json.loads(raw)
