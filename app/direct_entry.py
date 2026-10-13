"""Candidate entrypoint. Legacy authority endpoints are not mounted here."""
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header,HTTPException
from .agent_dispatch_api import router as agents
from .objective_api import router as objectives
from .engineering_api import router as engineering
from .artifact_delivery import router as artifacts
from .interface_node import router as interface
from .interface_contract import router as dell_interface
from .compute_queue_api import router as compute,start_compute_queue,stop_compute_queue
from .action_records import action_ledger,close_ledgers
from .client_auth import authenticate_owner
from .agent_registry import registered_agent_ids
from .agent_cert_event_api import router as certification_events
from .capability_broker import router as capability_services
from .collective_api import router as collective_workspace


@asynccontextmanager
async def lifespan(app):
    start_compute_queue()
    try:yield
    finally:
        stop_compute_queue()
        close_ledgers()


app=FastAPI(title='ORQEVIA · 奥启维亚 — direct execution',lifespan=lifespan)
for router in (agents,objectives,engineering,artifacts,interface,dell_interface,compute,certification_events,capability_services,collective_workspace):app.include_router(router)
SERVICE_BODY_BYTES=300000
SERVICE_BODY_SECONDS=5
SERVICE_JSON_DEPTH=16

@app.middleware('http')
async def bounded_service_requests(request,call_next):
    if request.url.path.startswith(('/api/capabilities','/api/collective','/api/agent-tool-bridge')):
        try:authenticate_owner(request.headers.get('authorization'))
        except HTTPException as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Service authentication required'},status_code=exc.status_code)
        if request.method=='POST':
            from fastapi.responses import JSONResponse
            import asyncio
            lengths=request.headers.getlist('content-length')
            if lengths:
                if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    return JSONResponse({'detail':'Invalid service content length'},status_code=422)
                declared=lengths[0].lstrip('0') or '0'
                if len(declared)>len(str(SERVICE_BODY_BYTES)) or int(declared)>SERVICE_BODY_BYTES:
                    return JSONResponse({'detail':'Service body exceeds limit'},status_code=413)
            async def read_body():
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>SERVICE_BODY_BYTES:raise ValueError('Body limit')
                    chunks.append(chunk)
                return b''.join(chunks)
            try:request._body=await asyncio.wait_for(read_body(),timeout=SERVICE_BODY_SECONDS)
            except TimeoutError:return JSONResponse({'detail':'Service upload deadline exceeded'},status_code=408)
            except ValueError:return JSONResponse({'detail':'Service body exceeds limit'},status_code=413)
            import json
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError('Duplicate field')
                    result[key]=value
                return result
            try:
                value=json.loads(request._body,object_pairs_hook=unique,
                    parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite')))
                if not isinstance(value,dict):raise ValueError('Object required')
                stack=[(value,0)]
                while stack:
                    item,depth=stack.pop()
                    if depth>SERVICE_JSON_DEPTH:raise ValueError('JSON depth limit')
                    if isinstance(item,dict):stack.extend((child,depth+1) for child in item.values())
                    elif isinstance(item,list):stack.extend((child,depth+1) for child in item)
            except (ValueError,RecursionError):
                return JSONResponse({'detail':'Invalid bounded service JSON'},status_code=422)
    return await call_next(request)


@app.get('/health')
def health(authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    return {'state':'READY','execution_model':'DIRECT_OBSERVED',
        'agents':len(registered_agent_ids(include_orchestrator=False)),'logging':action_ledger().status()}


@app.post('/api/observability/flush')
def flush(authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    ledger=action_ledger()
    return {'flushed':ledger.flush(),'logging':ledger.status()}
