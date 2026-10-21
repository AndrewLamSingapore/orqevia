"""Bounded forwarding through the existing TLS client/session boundary."""
import os
import asyncio
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, RedirectResponse
from . import pwa_sessions
from .interface_contract import authorize
from .interface_node import client_policy
from . import open_access

router = APIRouter()
API_PATHS = {
    'manifest': {'GET'}, 'gods-eye': {'GET'},
    'intelligence/sources': {'GET'}, 'intelligence/health': {'GET'},
    'intelligence/geo/events': {'GET'}, 'intelligence/geo/distance': {'GET'},
    'intelligence/geo/radius': {'GET'}, 'intelligence/rag/retrieve': {'POST'},
    'intelligence/geo/features': {'GET'}, 'intelligence/geo/regions': {'GET'},
    'intelligence/ingest/run': {'POST'}, 'intelligence/detection/alerts': {'GET'},
    'intelligence/history/timeline': {'GET'}, 'intelligence/predictive/baseline': {'GET'},
}

def access(request, *, mutation=False):
    if open_access.enabled() and pwa_sessions.COOKIE not in request.cookies:
        return open_access.OPEN_OWNER_ID
    if pwa_sessions.COOKIE in request.cookies:
        if any(k in request.headers for k in ('authorization', 'x-client-id', 'x-orqevia-client-id')):
            raise HTTPException(400, 'Ambiguous client identity')
        if not pwa_sessions.origin_valid(request, request.method not in {'GET','HEAD'}):
            raise HTTPException(403, 'Same-origin access required')
        current = pwa_sessions.require_session(request)
        actor, role = current['clientId'], current['role']
    else:
        actor, _ = authorize(request, 'authority.owner.verify' if mutation else 'health.read')
        role = client_policy(actor).get('role')
    if mutation and role != 'OWNER':
        raise HTTPException(403, 'Owner authority required')
    return actor

async def forward(request, path, *, mutation=False):
    actor = access(request, mutation=mutation)
    base = os.getenv('ORQEVIA_INTELLIGENCE_BASE_URL', 'http://intelligence:8100')
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.netloc != 'intelligence:8100' or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, 'Intelligence service target unavailable')
    token = os.getenv('ORQEVIA_SPINE_TOKEN', '').strip()
    if len(token) < 16:
        raise HTTPException(503, 'Intelligence service authority unavailable')
    try:
        body = await asyncio.wait_for(pwa_sessions.bounded_body(request, 16384),3) if request.method == 'POST' else b''
        async with httpx.AsyncClient(timeout=httpx.Timeout(25,connect=3),follow_redirects=False,trust_env=False) as client:
            async with client.stream(request.method,base+path,params=request.query_params,
                    content=body,headers={'Authorization':'Bearer '+token,'X-ORQEVIA-Actor':actor,
                    'Content-Type':'application/json','Accept':'application/json,text/html;q=0.8'}) as upstream:
                chunks=[];size=0
                async for chunk in upstream.aiter_bytes():
                    size+=len(chunk)
                    if size>5_000_000:raise ValueError('Response exceeds bound')
                    chunks.append(chunk)
                return Response(b''.join(chunks),status_code=upstream.status_code,
                    headers={'Content-Type':upstream.headers.get('content-type','application/octet-stream'),
                    'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                    'Referrer-Policy':'no-referrer',
                    'Content-Security-Policy':"default-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'"})
    except (httpx.HTTPError,ValueError,TimeoutError):
        raise HTTPException(503,'Intelligence service unavailable') from None

@router.api_route('/api/orqevia/{path:path}',methods=['GET','POST'])
async def intelligence_api(request: Request,path: str):
    if path not in API_PATHS:raise HTTPException(404,'Unavailable route')
    if request.method not in API_PATHS[path]:raise HTTPException(405,'Unavailable method')
    return await forward(request,'/api/orqevia/'+path,mutation=path=='intelligence/ingest/run')

@router.get('/orqevia/{path:path}')
async def intelligence_ui(request: Request,path: str):
    if not path:
        return RedirectResponse('/pwa/?view=gods-eye',status_code=307)
    if any(part in {'..','.'} for part in path.split('/')) or '\\' in path or ':' in path:
        raise HTTPException(404,'Unavailable asset')
    if path and not path.endswith(('.html','.js','.mjs','.css','.png','.webmanifest')):
        raise HTTPException(404,'Unavailable asset')
    return await forward(request,'/'+path)
