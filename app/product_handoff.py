"""Temporary, peer-bounded public bundle and authenticated physical-client proof.

Disabled unless the local runtime has an explicit finite handoff configuration.
No enrollment, credential transport, or new execution authority is provided.
"""
import hashlib,json,math,os,time
import threading
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from .interface_contract import authorize
from .interface_node import own_task
from .artifact_factory import ArtifactFactory

router=APIRouter(prefix='/integration')
_proof_lock=threading.Lock()

def configuration(request, *, version=1):
    if request.url.scheme!='https' or not request.client or request.client.host!='192.168.1.17':raise HTTPException(404)
    try:
        local=Path(os.environ['ORQEVIA_DATA_DIR']).resolve().parent
        filename={1:'product-handoff.json',2:'product-handoff-v2.json'}[version]
        config=json.loads((local/filename).read_text())
        expiry=config['expires_at'];issued=config['issued_at']
        root=Path(config['directory']).resolve()
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (expiry,issued)):raise ValueError()
        if not issued<=time.time()<expiry or expiry-issued>86400:raise ValueError()
        if not root.is_relative_to(local.parent/'outputs'):raise ValueError()
        return root
    except (OSError,KeyError,ValueError,TypeError):raise HTTPException(404) from None

@router.get('/production-client.zip')
def bundle(request:Request):
    root=configuration(request)
    if (root/'TRANSFER_CLOSED').exists():raise HTTPException(404)
    path=root/'ORQEVIA-DELL-PRODUCTION-RECONNECT.zip'
    if not path.is_file() or path.is_symlink():raise HTTPException(404)
    return FileResponse(path,media_type='application/zip')

@router.get('/production-client-v2.zip')
def bundle_v2(request:Request):
    # Separate delivery configuration; proof ownership and receipts remain v1.
    root=configuration(request,version=2)
    proof_root=configuration(request)
    if (root/'TRANSFER_CLOSED').exists() or (proof_root/'TRANSFER_CLOSED').exists():raise HTTPException(404)
    path=root/'ORQEVIA-DELL-PRODUCTION-RECONNECT.zip'
    if not path.is_file() or path.is_symlink():raise HTTPException(404)
    return FileResponse(path,media_type='application/zip')

@router.post('/production-proof')
async def proof(request:Request):
    root=configuration(request)
    client,_=authorize(request,'task.read')
    if client!='dell:DESKTOP-IPV4PH9':raise HTTPException(403)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>8192:raise HTTPException(413)
    digest=hashlib.sha256(raw).hexdigest()
    if request.headers.get('x-content-sha256')!=digest:raise HTTPException(422)
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate proof field')
            value[key]=item
        return value
    try:value=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,UnicodeError):raise HTTPException(422) from None
    required={'host','client_id','task_id','artifact_id','sha256','download_sha256','readback_sha256','identity_pass','tls_pass','health_pass','reconnect_pass','idempotency_pass','status'}
    if not isinstance(value,dict) or set(value)!=required:raise HTTPException(422)
    if value['host']!='DESKTOP-IPV4PH9' or value['client_id']!=client or value['status']!='PASS':raise HTTPException(422)
    if any(value[k] is not True for k in ('identity_pass','tls_pass','health_pass','reconnect_pass','idempotency_pass')):raise HTTPException(422)
    if not all(isinstance(value[k],str) and 1<=len(value[k])<=128 for k in ('task_id','artifact_id')):raise HTTPException(422)
    own_task(value['task_id'],client)
    try:metadata,content=ArtifactFactory(Path(os.environ['ORQEVIA_DATA_DIR'])/'artifacts').retrieve(value['artifact_id'])
    except (ValueError,KeyError,OSError):raise HTTPException(404) from None
    actual=hashlib.sha256(content).hexdigest()
    if metadata.get('task_id')!=value['task_id'] or any(value[k]!=actual for k in ('sha256','download_sha256','readback_sha256')):raise HTTPException(422)
    target=root/('DELL-PROOF-'+digest+'.json')
    # One runtime serializes proof acceptance. An interrupted durable receipt can
    # close the transfer on retry; an existing receipt must still match exactly.
    with _proof_lock:
        if target.exists():
            if target.read_bytes()!=raw:raise HTTPException(409)
        else:
            if (root/'TRANSFER_CLOSED').exists():raise HTTPException(409)
            with target.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:
            with (root/'TRANSFER_CLOSED').open('xb') as stream:
                stream.write(b'Physical Dell proof accepted; public transfer closed.')
                stream.flush();os.fsync(stream.fileno())
        except FileExistsError:pass
    return {'received':True,'sha256':digest,'artifact_sha256':actual}
