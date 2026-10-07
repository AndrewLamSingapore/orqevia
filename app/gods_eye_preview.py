"""Temporary loopback preview of actual existing production GET observations.

No execution lifespan, workers, model calls, producer writes, or public binding.
Missing formal engines remain explicitly UNAVAILABLE, not an imitation graph.
This is an isolated source preview, never production deployment acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from uuid import UUID
import urllib.request

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from .gods_eye_api import project_snapshot, semantic_projection

_LOCK = threading.BoundedSemaphore(1)
_LAST = None
_AT = 0.0
_SCOPE = None
_BASE = 'http://127.0.0.1:8000'


def read_domain(path, authorization):
    # Fixed local origin and fixed path construction; no caller URL or redirect.
    if not path.startswith('/control/api/') or '#' in path:
        raise ValueError('PREVIEW_DOMAIN_PATH_INVALID')
    if '?' in path:
        base, query = path.split('?', 1)
        identity = query.removeprefix('task_id=')
        try:
            if (base != '/control/api/hf-observation' or query != 'task_id=' + identity
                    or str(UUID(identity)) != identity):
                raise ValueError()
        except ValueError:
            raise ValueError('PREVIEW_DOMAIN_PATH_INVALID') from None
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(_BASE + path, headers={'Authorization': authorization, 'Accept': 'application/json'})
    with opener.open(request, timeout=2) as response:
        payload = response.read(1048577)
        if response.status != 200 or len(payload) > 1048576:
            raise ValueError('PREVIEW_DOMAIN_RESPONSE_INVALID')
    return json.loads(payload)


def collect(authorization, *, protected_domains=False):
    capabilities = read_domain('/control/api/agent-capabilities', authorization) if protected_domains else {}
    jobs = read_domain('/control/api/jobs', authorization).get('jobs', [])
    source = capabilities.get('reported_source_revision') if protected_domains else os.getenv('PRIME_GODS_EYE_OBSERVED_SOURCE', 'UNKNOWN')
    cert = [{'agent_id': row['agent_id'], 'level': row['proven']['level'],
             'trust_state': row['proven']['trust_state'], 'missing': row.get('missing_cases', {})}
            for row in capabilities.get('agents', [])] if protected_domains else []
    objectives, lens = [], {}
    # Explicit existing objective seeds, not invented tasks or repeated canaries.
    for identity in os.getenv('PRIME_GODS_EYE_PREVIEW_TASK_IDS', '').split(',')[:12]:
        if not identity:
            continue
        if str(UUID(identity)) != identity:
            raise ValueError('PREVIEW_TASK_ID_INVALID')
        evidence = read_domain('/control/api/evidence/from-objective/' + identity, authorization)
        value = evidence.get('observed') or {}
        if value.get('task_id') != identity or evidence.get('task_id') != identity:
            raise ValueError('PREVIEW_TASK_EVIDENCE_BINDING_INVALID')
        lens[identity] = evidence
        objectives.append({'id': identity, 'revision': evidence['revision'], 'state': value['execution_state'],
            'execution_metadata': {'task_id': identity, 'runtime': value.get('runtime'),
                'completed_at': value.get('completed_at'),
                'agent_execution': [{'selected_agent_id': agent, 'registry_binding': 'VERIFIED'}
                                    for agent in value.get('agent_ids', [])]}})
    # Existing authenticated HF GET contract; no probe or model invocation.
    # This optional domain cannot make the remaining preview unavailable.
    hf_observation = None
    if protected_domains:
        try:
            identity = next(iter(lens), None)
            hf_observation = read_domain('/control/api/hf-observation' + ('?task_id=' + identity if identity else ''), authorization)
        except Exception:
            pass
    result = project_snapshot(runtime={'source_revision': source}, certification_rows=cert,
                              jobs=jobs, objectives=objectives, lens=lens, hf_observation=hf_observation)
    result['status'] = 'ISOLATED_LIVE_READ_ONLY_PREVIEW'
    result['preview'] = {'source_revision': os.getenv('PRIME_GODS_EYE_PREVIEW_REVISION', 'UNKNOWN'),
        'domain_transport': 'FIXED_LOOPBACK_GET', 'production_changed': False,
        'task_scope': 'EXPLICIT_EXISTING_OBJECTIVES_ONLY', 'models_invoked': 0}
    result['certification']['independent_verifier'] = capabilities.get('independent_verifier', 'UNKNOWN')
    result['protected_domain_access'] = 'EXPLICIT_BEARER' if protected_domains else 'NOT_REQUESTED'
    try:
        from .semantic_fabric import build_semantics, SemanticError
        result['semantics'] = build_semantics(semantic_projection(result))
    except SemanticError:
        result['semantics'] = {'status': 'UNAVAILABLE', 'source': 'SEMANTIC_FABRIC', 'currentness': 'UNKNOWN',
                               'reason': 'Formal acceptance is separate from this preview.'}
    return result


def observation(authorization, *, protected_domains=False):
    from .client_auth import authenticate_owner
    authenticate_owner(authorization)
    global _LAST, _AT, _SCOPE
    if not _LOCK.acquire(blocking=False):
        raise HTTPException(503, 'Observation busy')
    try:
        if _LAST is not None and _SCOPE == protected_domains and time.monotonic() - _AT < 5:
            return json.loads(json.dumps(_LAST))
        try:
            result = collect(authorization, protected_domains=protected_domains)
            if len(json.dumps(result).encode()) > 262144:
                raise ValueError('budget')
        except Exception:
            raise HTTPException(503, 'Live source observation unavailable') from None
        _LAST, _AT, _SCOPE = json.loads(json.dumps(result)), time.monotonic(), protected_domains
        return result
    finally:
        _LOCK.release()


def build_app(authorize):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def protected_scope(request, authorization):
        supplied = request.headers.getlist('authorization')
        if not supplied:
            return False
        from .client_auth import authenticate_owner
        if len(supplied) != 1:
            raise HTTPException(401, 'Owner authorization required')
        authenticate_owner(supplied[0])
        return True

    @app.middleware('http')
    async def private_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
        return response

    @app.get('/control/gods-eye', dependencies=[Depends(authorize)])
    def page():
        return HTMLResponse(Path(__file__).with_name('gods_eye.html').read_text(encoding='utf-8'))

    @app.get('/control', dependencies=[Depends(authorize)])
    def existing_workbench():
        return RedirectResponse(_BASE + '/control', status_code=307)

    @app.get('/control/gods-eye.js', dependencies=[Depends(authorize)])
    def script():
        return Response(Path(__file__).with_name('gods_eye.js').read_text(encoding='utf-8'), media_type='text/javascript')

    @app.get('/control/gods-eye.css', dependencies=[Depends(authorize)])
    def style():
        return Response(Path(__file__).with_name('gods_eye.css').read_text(encoding='utf-8'), media_type='text/css')

    @app.get('/control/api/gods-eye')
    def snapshot(request: Request, authorization=Depends(authorize)):
        return observation(authorization, protected_domains=protected_scope(request, authorization))

    @app.get('/control/api/evidence/from-objective/{task_id}')
    def evidence(request: Request, task_id: str, authorization=Depends(authorize)):
        current = observation(authorization, protected_domains=protected_scope(request, authorization))
        if task_id not in {row['task_id'] for row in current['results']}:
            raise HTTPException(404, 'Evidence is outside preview scope')
        return read_domain('/control/api/evidence/from-objective/' + task_id, authorization)

    @app.get('/control/api/gods-eye/why')
    def why(request: Request, agent_id: str, authorization=Depends(authorize)):
        current = observation(authorization, protected_domains=protected_scope(request, authorization))
        from .semantic_fabric import query_semantics, SemanticError
        try:
            result = query_semantics(semantic_projection(current), 'why', agent_id)
            result['metrics'] = [m for m in current['metrics'] if m['agent_id'] == agent_id]
            return result
        except SemanticError:
            raise HTTPException(422, 'Formal semantic view unavailable or invalid') from None

    @app.get('/control/api/gods-eye/dependencies')
    def dependencies(request: Request, subject: str, authorization=Depends(authorize)):
        current = observation(authorization, protected_domains=protected_scope(request, authorization))
        from .semantic_fabric import query_semantics, SemanticError
        try:
            return query_semantics(semantic_projection(current), 'depends_on', subject)
        except SemanticError:
            raise HTTPException(422, 'Formal semantic view unavailable or invalid') from None

    return app


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-config', required=True)
    parser.add_argument('--preview-data', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--task-id', required=True)
    args = parser.parse_args()
    # Private material stays server-side and is never printed, logged or put in argv.
    config = json.loads(Path(args.private_config).read_text(encoding='utf-8-sig'))
    if type(config) is list and len(config) == 1:
        config = config[0]
    if type(config) is not dict:
        raise RuntimeError('PREVIEW_OPERATOR_CONFIGURATION_INVALID')
    env = dict(item.split('=', 1) for item in config['Config']['Env'] if '=' in item)
    token = env.get('PRIME_SPINE_TOKEN', '').strip()
    if not token:
        raise RuntimeError('PREVIEW_OPERATOR_CONFIGURATION_UNAVAILABLE')
    os.environ['PRIME_SPINE_TOKEN'] = token
    os.environ['PRIME_DATA_DIR'] = args.preview_data
    os.environ['PRIME_COMPUTE_QUEUE_DB'] = str(Path(args.preview_data) / 'preview-queue.db')
    os.environ['PRIME_GODS_EYE_PREVIEW_REVISION'] = args.revision
    os.environ['PRIME_GODS_EYE_OBSERVED_SOURCE'] = env.get('PRIME_RUNTIME_REVISION', 'UNKNOWN')
    os.environ['PRIME_GODS_EYE_PREVIEW_TASK_IDS'] = args.task_id
    # Reuse exactly the accepted control access predicate, never its lifespan.
    from .production_entry import local_authorization
    import uvicorn
    uvicorn.run(build_app(local_authorization), host='127.0.0.1', port=18080,
                proxy_headers=False, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
