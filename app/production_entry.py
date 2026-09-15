"""Loopback compatibility shell around the unchanged direct execution application.

Run with proxy-header processing disabled: trust the transport peer, not forwarded
headers. The shell owns no scheduler, task store, or execution policy.
"""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import direct_entry, objective_api, agent_dispatch_api, compute_queue_api, artifact_delivery
from .operational_workflows import router as operational_workflows
from .pwa_sessions import owner_router as pwa_owner_router


def local_request(request: Request):
    try:
        peer = ipaddress.ip_address(request.client.host)
        hosts = request.headers.getlist('host')
        if not peer.is_loopback or len(hosts) != 1:
            raise ValueError()
        host = urlsplit('//' + hosts[0])
        if host.hostname not in {'localhost', '127.0.0.1', '::1'} or host.username or host.password or host.path or host.query or host.fragment:
            raise ValueError()
        port = host.port or (443 if request.url.scheme == 'https' else 80)
        origins = request.headers.getlist('origin')
        if len(origins) > 1:
            raise ValueError()
        origin = origins[0] if origins else None
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not origin:
            raise ValueError()
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)) != (request.url.scheme, host.hostname, port):
                raise ValueError()
            if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise ValueError()
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(403, 'Local same-origin access required') from None


def local_authorization(request: Request):
    local_request(request)
    token = os.getenv('PRIME_SPINE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Local access is not configured')
    return 'Bearer ' + token


app = FastAPI(title='PRIME local control', lifespan=direct_entry.lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def private_control_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == '/health' or request.url.path.startswith('/control'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get('/health', dependencies=[Depends(local_request)])
def health():
    # Liveness/configuration readiness only; inference availability stays on the
    # authenticated candidate APIs. Never return registry, ledger, or provider data.
    ready = bool(os.getenv('PRIME_SPINE_TOKEN', '').strip())
    return JSONResponse({'ok': ready}, status_code=200 if ready else 503)


@app.get('/control', dependencies=[Depends(local_authorization)])
def control():
    return HTMLResponse(Path(__file__).with_name('production_control.html').read_text(encoding='utf-8'))


@app.get('/control/app.js', dependencies=[Depends(local_authorization)])
def control_script():
    from fastapi.responses import Response
    return Response(Path(__file__).with_name('production_control.js').read_text(encoding='utf-8'), media_type='text/javascript')


@app.post('/control/api/objectives', status_code=202)
def submit_objective(body: objective_api.ObjectiveRequest, authorization=Depends(local_authorization)):
    return objective_api.submit(body, authorization)


@app.post('/control/api/pwa-pairing')
async def pwa_pairing(request: Request, authorization=Depends(local_authorization)):
    from .pwa_sessions import pairing
    scope = dict(request.scope)
    scope['headers'] = [(key, value) for key, value in request.scope['headers']
                        if key.lower() != b'authorization']
    scope['headers'].append((b'authorization', authorization.encode('ascii')))
    return await pairing(Request(scope, request.receive))


@app.get('/control/api/objectives/{task_id}')
def objective(task_id: str, authorization=Depends(local_authorization)):
    return objective_api.get(task_id, authorization)


@app.post('/control/api/dispatch', status_code=202)
def dispatch(body: agent_dispatch_api.AgentRequest, authorization=Depends(local_authorization)):
    return agent_dispatch_api.dispatch(body, authorization)


@app.get('/control/api/jobs')
def jobs(status: str | None = None, limit: int = 30, authorization=Depends(local_authorization)):
    return compute_queue_api.list_jobs(status, limit, authorization)


@app.get('/control/api/jobs/{job_id}')
def job(job_id: str, authorization=Depends(local_authorization)):
    return compute_queue_api.get_job(job_id, authorization)


@app.post('/control/api/artifacts/from-task/{task_id}', status_code=201)
def materialize(task_id: str, authorization=Depends(local_authorization)):
    return artifact_delivery.materialize(task_id, authorization)


@app.get('/control/api/artifacts/{artifact_id}')
def artifact(artifact_id: str, authorization=Depends(local_authorization)):
    response = artifact_delivery.retrieve(artifact_id, authorization)
    response.headers['Content-Disposition'] = 'attachment'
    return response


# Original endpoints retain their original authentication and implementation.
app.include_router(operational_workflows)
app.include_router(pwa_owner_router)
app.mount('/', direct_entry.app)
