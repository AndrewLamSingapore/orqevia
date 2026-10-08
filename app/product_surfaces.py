"""Read-only product boundary over existing server-owned PWA identity.

This is not the loopback operational console and does not translate a browser
session into the internal Owner bearer or grant new operational capabilities.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import pwa_sessions

router = APIRouter(tags=['product-surfaces'])


def owner_session(request: Request):
    if (request.method != 'GET' or not pwa_sessions.origin_valid(request)
            or len(request.headers.getlist('host')) != 1
            or len(request.headers.getlist('origin')) > 1
            or len(request.headers.getlist('sec-fetch-site')) > 1):
        raise HTTPException(403, 'Same-origin HTTPS required')
    # Do not accept role/identity assertions supplied in browser headers.
    if any(name in request.headers for name in (
            'authorization', 'x-client-id', 'x-jarvis-client-id', 'x-role', 'x-owner')):
        raise HTTPException(403, 'Caller authority headers forbidden')
    current = pwa_sessions.require_session(request)
    if current.get('role') != 'OWNER':
        raise HTTPException(403, 'Owner session required')
    device_status, bound = pwa_sessions.device_state(request)
    # Keep legacy valid sessions usable, but do not accept a revoked/mismatched
    # trusted-device binding; get_session owns issuance/refresh, not this route.
    if device_status != 'MISSING' and (device_status != 'VALID' or any(
            current[key] != bound[key] for key in ('clientId', 'role', 'ownerAccountId'))):
        raise HTTPException(401, 'Device binding unavailable')
    return current


@router.get('/pwa/api/control-center')
def control_center_status(request: Request):
    owner_session(request)
    return {
        'schema': 'prime.product-surfaces.v1',
        'surface': 'PRIME_CONTROL_CENTER',
        'authority': {'role': 'OWNER', 'session': 'VERIFIED',
                      'scope': 'READ_ONLY_SESSION_STATUS',
                      'grants_operational_authority': False},
        'workspace': '/pwa/',
        'operational_projections': 'NOT_CONNECTED',
        'runtime_health': 'UNMEASURED',
        'agent_certification': 'UNMEASURED',
        'authentication_migration': 'LEGACY_RECOVERY_PAIRING_RETAINED',
    }


@router.get('/pwa/control-center', response_class=HTMLResponse)
def control_center(request: Request):
    owner_session(request)
    # Fixed public copy only: no credentials, account identifiers, arbitrary
    # proxy URLs, model output, inline scripts/styles or operational controls.
    return HTMLResponse('''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#101714"><title>PRIME Control Center</title>
<link rel="stylesheet" href="/pwa/style.css"></head><body><div class="app-shell">
<header class="topbar"><a class="brand" href="/pwa/">JARVIS<span class="brand-sub">WORKSPACE</span></a>
<span class="connection">Owner · read only</span></header><main>
<section class="intro"><div><p class="eyebrow">PRIVATE OWNER SURFACE</p>
<h1>PRIME<br>Control Center</h1><p class="intro-copy">A separate boundary for Owner inspection.</p></div></section>
<section class="panel"><h2>Owner session verified</h2>
<p>This page uses your current server-verified Owner session. It grants no additional operational authority.</p>
<p class="helper">Runtime, certification and operational domain projections are not connected to this surface yet. Their status is not measured here.</p>
<a class="secondary" href="/pwa/api/control-center">Inspect this boundary's read-only status</a></section>
<section class="panel"><h2>Your Workspace</h2><p>Continue tasks, files and results in JARVIS Workspace.</p>
<a class="primary" href="/pwa/">Open Workspace</a></section>
<footer>Private Owner access · no new admin permissions</footer></main></div></body></html>''',
        headers={'Cache-Control': 'no-store'})
