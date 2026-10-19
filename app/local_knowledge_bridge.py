"""Owner-scoped private document/RAG adapter behind the existing TLS gateway."""
import asyncio
import hashlib
import json
import os
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from . import orqevia_bridge as existing
from .observability import trace_headers

router=APIRouter()
PATHS={'health':{'GET'},'documents':{'GET'},'ingest':{'POST'},'retrieve':{'POST'},'answer':{'POST'},'reindex':{'POST'},
    'workspace':{'GET'},'ideas':{'GET','POST'},'scaffold':{'POST'},'validate':{'POST'}}

def identity(request):
    actor=existing.access(request,mutation=True)
    if existing.pwa_sessions.COOKIE in request.cookies:
        account=existing.pwa_sessions.require_session(request).get('ownerAccountId')
    else:account=existing.client_policy(actor).get('owner_account_id')
    if not isinstance(account,str) or not account:raise HTTPException(403,'A bound owner account is required for private documents')
    return actor,hashlib.sha256(account.encode()).hexdigest()

@router.api_route('/api/orqevia/knowledge/{path:path}',methods=['GET','POST'])
async def knowledge(request:Request,path:str):
    if path not in PATHS:raise HTTPException(404,'Unavailable knowledge route')
    if request.method not in PATHS[path]:raise HTTPException(405,'Unavailable method')
    actor,owner=identity(request)
    base=os.getenv('ORQEVIA_LOCAL_INTELLIGENCE_URL','http://host.docker.internal:8150')
    parsed=urlsplit(base)
    if parsed.scheme!='http' or parsed.netloc!='host.docker.internal:8150' or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503,'Local intelligence target unavailable')
    token=os.getenv('PRIME_SPINE_TOKEN','').strip()
    if len(token)<16:raise HTTPException(503,'Service authority unavailable')
    try:
        limit=8*1024*1024 if path=='ingest' else 16000
        body=await asyncio.wait_for(existing.pwa_sessions.bounded_body(request,limit),10) if request.method=='POST' else b''
        timeout=170 if path=='answer' else 100 if path in {'ingest','reindex','retrieve','validate'} else 15
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=3),trust_env=False,follow_redirects=False) as client:
                if path=='answer':
                    value=json.loads(body)
                    if not isinstance(value,dict) or set(value)-{'question','top_k','document_ids','include_observations'}:raise HTTPException(422,'Invalid knowledge answer request')
                    include=value.pop('include_observations',False)
                    if type(include) is not bool:raise HTTPException(422,'Invalid observation option')
                    if include:
                        # Actual existing observation service; caller cannot
                        # inject fabricated observations into grounded context.
                        source=await client.get('http://intelligence:8100/api/orqevia/intelligence/geo/events?limit=3',headers={'Authorization':'Bearer '+token})
                        if source.status_code!=200:raise HTTPException(503,'Observation context unavailable')
                        value['observations']=source.json().get('records',[])
                    body=json.dumps(value).encode()
                upstream_headers=trace_headers({
                    'Authorization':'Bearer '+token,'X-ORQEVIA-Owner':owner,
                    'X-Document-Name':request.headers.get('x-document-name','')[:1000],
                    'Content-Type':'application/octet-stream' if path=='ingest' else 'application/json'})
                async with client.stream(request.method,base+'/'+path,content=body,headers=upstream_headers) as upstream:
                    chunks=[];size=0
                    async for chunk in upstream.aiter_bytes():
                        size+=len(chunk)
                        if size>2_000_000:raise ValueError('Knowledge response bound exceeded')
                        chunks.append(chunk)
                    return Response(b''.join(chunks),status_code=upstream.status_code,
                        headers={'Content-Type':'application/json','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    except (httpx.HTTPError,TimeoutError,OSError):raise HTTPException(503,'Local intelligence service unavailable; retry when ready') from None
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid bounded knowledge request') from None
