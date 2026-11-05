"""Owned-task Evidence Lens access through the existing authenticated interface.

Reuse the current objective and evidence stores on the shared data volume. The
browser receives no server credential and cannot select a backend or authority.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import evidence_lens_api, interface_node as node, objective_api, pwa_sessions
from .interface_contract import authorize

router = APIRouter(prefix="/interface/v1/lens", tags=["owned-task-evidence"])


def _owned_task(request: Request, task_id: str, *, mutation: bool = False) -> str:
    if not pwa_sessions.origin_valid(request, mutation):
        raise HTTPException(403, "Same-origin HTTPS access required")
    client, _ = authorize(request, "authority.owner.verify")
    if node.client_policy(client).get("role") != "OWNER":
        raise HTTPException(403, "Owner session required")
    try:
        if str(UUID(task_id)) != task_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Task not found") from None
    node.own_task(task_id, client)
    return node.owner_transport()


def _response(value: dict, *, status: int = 200) -> JSONResponse:
    return JSONResponse(
        value,
        status_code=status,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/objectives/{task_id}")
def objective(task_id: str, request: Request):
    authorization = _owned_task(request, task_id)
    return _response(objective_api.get_read_only(task_id, authorization))


@router.get("/evidence/from-objective/{task_id}")
def evidence(task_id: str, request: Request):
    authorization = _owned_task(request, task_id)
    return _response(evidence_lens_api.read(task_id, authorization))


@router.post("/evidence/from-objective/{task_id}", status_code=201)
async def capture(task_id: str, request: Request):
    authorization = _owned_task(request, task_id, mutation=True)
    raw = await pwa_sessions.bounded_body(request, 1024)
    try:
        value = json.loads(raw) if raw.strip() else {}
    except (ValueError, UnicodeError):
        raise HTTPException(422, "An empty evidence capture request is required") from None
    if value != {} or not isinstance(value, dict):
        raise HTTPException(422, "Evidence capture accepts no execution parameters")
    return _response(evidence_lens_api.materialize(task_id, authorization), status=201)
