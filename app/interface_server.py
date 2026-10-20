"""Dedicated thin-client ASGI surface; deliberately excludes owner/legacy routes.

Deploy only behind actual TLS with forwarded-header trust disabled. The owner
server remains responsible for starting the single shared worker pool. This
surface does not start a second pool or create a new Registry/queue authority.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from .interface_contract import router
from . import pwa_sessions
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .observability import PRIVACY_FASTAPI_TELEMETRY

app=FastAPI(title='ORQEVIA Thin-client Interface',docs_url=None,redoc_url=None,openapi_url=None,
    telemetry=PRIVACY_FASTAPI_TELEMETRY)
app.include_router(router)
app.include_router(pwa_sessions.router)
app.add_middleware(pwa_sessions.PWASessionMiddleware)
from .product_handoff import router as product_handoff_router
app.include_router(product_handoff_router)
from .local_knowledge_bridge import router as knowledge_bridge_router
app.include_router(knowledge_bridge_router)
from .orqevia_bridge import router as intelligence_bridge_router
app.include_router(intelligence_bridge_router)
from .workflow_bridge import router as workflow_bridge_router
app.include_router(workflow_bridge_router)
app.mount('/pwa', StaticFiles(directory=os.getenv('ORQEVIA_PWA_STATIC_DIR',
    str(Path(__file__).with_name('pwa_static'))), html=True, check_dir=False), name='pwa')

PROTOCOL = 'orqevia.interface.v1'
ERRORS = {
    401: ('AUTHENTICATION_REQUIRED', 'Client authentication required'),
    403: ('CLIENT_SCOPE_DENIED', 'Client scope expired or unavailable'),
    404: ('NOT_FOUND', 'Requested resource unavailable'),
    405: ('METHOD_NOT_ALLOWED', 'Method not available'),
    409: ('STATE_CONFLICT', 'Request conflicts with current state; do not automatically replay'),
    422: ('INVALID_REQUEST', 'Request does not match the interface schema'),
    426: ('HTTPS_REQUIRED', 'HTTPS required'),
    429: ('RATE_LIMITED', 'Request capacity unavailable'),
    503: ('SERVICE_UNAVAILABLE', 'Required server configuration or capability unavailable'),
}


def error_response(status: int):
    code, message = ERRORS.get(status, ('INTERNAL_ERROR', 'Request could not be completed'))
    # Do not reflect exception text, request inputs or validation context: these
    # may contain prompts, bearer credentials, private paths or provider errors.
    return JSONResponse({'protocol': PROTOCOL, 'error': {'code': code, 'message': message,
        'retryable': False}}, status_code=status, headers={'X-ORQEVIA-Protocol': PROTOCOL,
        'Cache-Control': 'no-store'})


@app.middleware('http')
async def transport_and_protocol(request: Request, call_next):
    if request.url.scheme != 'https':
        return error_response(426)
    response = await call_next(request)
    response.headers['X-ORQEVIA-Protocol'] = PROTOCOL
    response.headers['Cache-Control'] = 'no-store'
    if request.url.path == '/pwa/ORQEVIA-ABEX-HTTPS.mobileconfig' and response.status_code == 200:
        response.headers['Content-Type'] = 'application/x-apple-aspen-config'
        response.headers['Content-Disposition'] = 'attachment; filename="ORQEVIA-ABEX-HTTPS.mobileconfig"'
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return error_response(exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error_response(422)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return error_response(500)
