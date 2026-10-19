"""Loopback compatibility shell around the unchanged direct execution application.

Run with proxy-header processing disabled: trust the transport peer, not forwarded
headers. The shell owns no scheduler, task store, or execution policy.
"""
import hmac
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import direct_entry, objective_api, agent_dispatch_api, compute_queue_api, artifact_delivery, evidence_lens_api
from .agent_capability_observatory import project_capability_observatory
from .agent_cert_azure_es256 import verifier_from_azure_es256_pin_file
from .agent_certification import AgentCertificationRegistry
from .operational_workflows import router as operational_workflows
from .pwa_sessions import owner_router as pwa_owner_router
from .production_survival import build_router as build_survival_router
from .observability import PRIVACY_FASTAPI_TELEMETRY, install_observability


def local_request(request: Request):
    try:
        peer = ipaddress.ip_address(request.client.host)
        configured_peers = {ipaddress.ip_address(value.strip()) for value in
                            os.getenv('ORQEVIA_OWNER_TRUSTED_PEERS', '').split(',') if value.strip()}
        hosts = request.headers.getlist('host')
        if not (peer.is_loopback or peer in configured_peers) or len(hosts) != 1:
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
    token = os.getenv('ORQEVIA_SPINE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Local access is not configured')
    return 'Bearer ' + token


def local_verifier_authorization(request: Request):
    """Keep certification projections behind explicit local bearer access."""
    expected = local_authorization(request)
    supplied = request.headers.getlist('authorization')
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0], expected):
        raise HTTPException(401, 'Owner authorization required')
    return expected


@asynccontextmanager
async def _lifespan(application):
    """Start the governed compute worker pool with the application.

    Idempotent (WorkerPool.start returns when threads exist). Without this the
    shared queue accepts jobs but nothing claims them until an operator starts
    a pool manually — the exact silent stall class observed on 16 October 2026.
    """
    async with direct_entry.lifespan(application) as state:
        compute_queue_api.start_compute_queue()
        yield state


app = FastAPI(title='ORQEVIA local control', lifespan=_lifespan, telemetry=PRIVACY_FASTAPI_TELEMETRY,
              docs_url=None, redoc_url=None, openapi_url=None)

_AZURE_CERT_PIN = Path(__file__).resolve().parent.parent / 'governance' / 'agent-cert-verifier-azure-pins.json'
_AZURE_CERT_PIN_SHA256 = '6cc238c7da9152519410a4cd731abd6e0e584d2cbd84c3c0863ca55b4e771bb0'


def _certification_verifier(data_root: Path):
    if os.getenv('ORQEVIA_AGENT_CERT_AZURE_ES256_ENABLED') != '1':
        return None
    override_path = os.getenv('ORQEVIA_AGENT_CERT_AZURE_ES256_PIN_FILE')
    override_sha256 = os.getenv('ORQEVIA_AGENT_CERT_AZURE_ES256_PIN_SHA256')
    source_pin = override_path is None and override_sha256 is None
    if override_path is not None or override_sha256 is not None:
        if not override_path or not override_sha256:
            return None
        pin_path, pin_sha256 = Path(override_path), override_sha256
    else:
        pin_path, pin_sha256 = _AZURE_CERT_PIN, _AZURE_CERT_PIN_SHA256
    try:
        return verifier_from_azure_es256_pin_file(
            pin_path, pin_sha256, untrusted_roots=(data_root,),
            normalize_crlf=source_pin)
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError):
        return None


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
    ready = bool(os.getenv('ORQEVIA_SPINE_TOKEN', '').strip())
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


@app.post('/control/api/evidence/from-objective/{task_id}', status_code=201)
def materialize_evidence(task_id: str, authorization=Depends(local_authorization)):
    return evidence_lens_api.materialize(task_id, authorization)


@app.get('/control/api/evidence/from-objective/{task_id}')
def objective_evidence(task_id: str, authorization=Depends(local_authorization)):
    return evidence_lens_api.read(task_id, authorization)


@app.post('/control/api/dispatch', status_code=202)
def dispatch(body: agent_dispatch_api.AgentRequest, authorization=Depends(local_authorization)):
    return agent_dispatch_api.dispatch(body, authorization)


@app.get('/control/api/jobs')
def jobs(status: str | None = None, limit: int = 30, authorization=Depends(local_authorization)):
    return compute_queue_api.list_jobs(status, limit, authorization)


@app.get('/control/api/agent-capabilities')
def agent_capabilities(authorization=Depends(local_verifier_authorization)):
    # Explicit bearer plus loopback control boundary, not a PWA-session endpoint.
    source = objective_api.runtime_snapshot()['source_revision']
    if source == 'UNKNOWN':
        raise HTTPException(503, 'Runtime source revision is unverified')
    data_root = Path(os.getenv('ORQEVIA_DATA_DIR', '/data'))
    verifier = _certification_verifier(data_root)
    certification = AgentCertificationRegistry(
        data_root / 'agent-certification', source_revision=source,
        verify_record=verifier)
    return {'reported_source_revision': source,
            'independent_verifier': 'CONFIGURED' if verifier else 'UNCONFIGURED',
            'agents': project_capability_observatory(certification)}


@app.get('/control/api/hf-observation')
def hf_observation(task_id: str | None = None,
                   authorization=Depends(local_verifier_authorization)):
    # Inspection never dispatches a model call or creates an evidence record.
    # Keep this behind explicit bearer access, not ambient Workbench access.
    from .hf_observation_api import inspect_hf
    return inspect_hf(authorization, task_id=task_id)


@app.get('/control/api/exposure-intelligence')
def exposure_intelligence(authorization=Depends(local_authorization)):
    # Same local Owner control boundary; no new public/PWA route or token.
    from .exposure_api import exposure_view
    return exposure_view()


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
app.include_router(build_survival_router(local_authorization))
app.mount('/', direct_entry.app)
OBSERVABILITY = install_observability(app)
