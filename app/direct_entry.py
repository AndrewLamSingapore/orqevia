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


app=FastAPI(title='PRIME direct-execution candidate',lifespan=lifespan)
for router in (agents,objectives,engineering,artifacts,interface,dell_interface,compute,certification_events,capability_services,collective_workspace):app.include_router(router)

@app.middleware('http')
async def bounded_service_requests(request,call_next):
    if request.url.path.startswith(('/api/capabilities','/api/collective')):
        try:authenticate_owner(request.headers.get('authorization'))
        except HTTPException as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Service authentication required'},status_code=exc.status_code)
        if request.method=='POST':
            from fastapi.responses import JSONResponse
            import asyncio
            async def read_body():
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>300000:raise ValueError('Body limit')
                    chunks.append(chunk)
                return b''.join(chunks)
            try:request._body=await asyncio.wait_for(read_body(),timeout=5)
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
