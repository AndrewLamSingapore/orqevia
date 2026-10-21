"""Authenticated per-agent notebook and behavioral-profile API."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .agent_conditioning import BehaviorProfile, BehaviorProfileStore
from .agent_notebooks import (
    AgentNotebookStore,
    NotebookConflict,
    NotebookNotFound,
    NotebookPermissionDenied,
    NotebookPrincipal,
    get_notebook_store,
)
from .agent_registry import RegistryError, canonical_agent_id
from . import open_access


class RecordWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    record_type: str | None = None
    content: Any
    source: str = Field(min_length=1, max_length=500)
    source_ref: str | None = Field(default=None, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    scope: Literal["private", "project", "organization"] = "private"
    project_id: str | None = Field(default=None, max_length=128)
    logical_key: str | None = Field(default=None, max_length=200)
    task_id: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=0.8, ge=0, le=1)
    verification_status: str = "agent_reported"
    retention_class: str | None = None
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class RecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Any
    source: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=1)
    change_reason: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] | None = Field(default=None, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: str | None = None


class RecordCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Any
    source: str = Field(min_length=1, max_length=500)
    change_reason: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0.9, ge=0, le=1)


class RecordDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    agent_id: str | None = None
    project_id: str | None = None
    sections: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    name: str = Field(min_length=1, max_length=200)


class ProjectGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=80)
    permission: Literal["read", "write"]
    expires_at: str | None = Field(default=None, max_length=100)


class BehaviorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    profile_id: str = Field(default="custom", min_length=1, max_length=80)
    decision_style: Literal["analytical", "balanced", "empathetic"] = "balanced"
    directness: float = Field(default=0.5, ge=0, le=1)
    exploration: float = Field(default=0.5, ge=0, le=1)
    collaboration: float = Field(default=0.5, ge=0, le=1)
    verbosity: float = Field(default=0.4, ge=0, le=1)
    challenge_style: Literal["constructive", "skeptical", "none"] = "constructive"
    mbti_tag: str | None = Field(default=None, min_length=4, max_length=4)


router = APIRouter(prefix="/api/agent-notebooks", tags=["agent-notebooks"])


def _admin_key() -> str:
    explicit = os.getenv("ORQEVIA_NOTEBOOK_ADMIN_TOKEN", "").strip()
    if explicit:
        return explicit
    spine = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if len(spine) < 16:
        return ""
    return hmac.new(spine.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256).hexdigest()


def _principal(authorization: str | None, actor: str | None, role: str | None, admin: str | None) -> NotebookPrincipal:
    if open_access.enabled():
        return NotebookPrincipal(actor or "owner", "OWNER")
    expected = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    supplied = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not expected:
        raise HTTPException(503, "Notebook authentication is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Notebook authorization required")
    normalized = (role or "").strip().upper()
    if normalized == "OWNER":
        key = _admin_key()
        if not key or not admin or not hmac.compare_digest(admin, key):
            raise HTTPException(403, "Notebook owner authority required")
        return NotebookPrincipal(actor or "owner", "OWNER")
    if normalized == "AGENT" and actor:
        try:
            canonical_agent_id(actor)
        except RegistryError:
            raise HTTPException(403, "Unknown agent identity") from None
        return NotebookPrincipal(actor, "AGENT", actor)
    raise HTTPException(403, "Notebook actor identity required")


def _store() -> AgentNotebookStore:
    return get_notebook_store()


@router.get("/health")
def health(
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    return _store().health(principal)


@router.get("")
def directory(
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    return _store().list_notebooks(principal)


@router.post("/index")
def index_pending(
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    if principal.role != "OWNER":
        raise HTTPException(403, "owner authority required")
    return _store().index_pending(limit=256)


@router.post("/search")
def search(
    body: SearchRequest,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().search(
            principal,
            body.query,
            agent_id=body.agent_id,
            project_id=body.project_id,
            sections=body.sections,
            limit=body.limit,
        )
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().project_create(principal, body.project_id, body.name)
    except (NotebookPermissionDenied, ValueError) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 422, str(exc)) from None


@router.get("/projects")
def list_projects(
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().project_list(principal)
    except NotebookPermissionDenied as exc:
        raise HTTPException(403, str(exc)) from None


@router.post("/projects/{project_id}/members", status_code=201)
def grant_project_member(
    project_id: str,
    body: ProjectGrant,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().project_grant(
            principal,
            project_id,
            body.agent_id,
            body.permission,
            expires_at=body.expires_at,
        )
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/projects/{project_id}/members")
def project_members(
    project_id: str,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().project_members(principal, project_id)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None


@router.get("/{agent_id}")
def notebook(
    agent_id: str,
    section: str | None = None,
    limit: int = 100,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().list_records(principal, agent_id, section=section, limit=limit)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None


@router.post("/{agent_id}/records", status_code=201)
def add_record(
    agent_id: str,
    body: RecordWrite,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        return _store().add_record(principal, agent_id=agent_id, **body.model_dump())
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/{agent_id}/records/{memory_id}")
def record(
    agent_id: str,
    memory_id: str,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        value = _store().get_record(principal, memory_id)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    if value["agent_id"] != canonical_agent_id(agent_id):
        raise HTTPException(404, "notebook record not found")
    return value


@router.patch("/{agent_id}/records/{memory_id}")
def update_record(
    agent_id: str,
    memory_id: str,
    body: RecordUpdate,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        value = _store().update_record(principal, memory_id, **body.model_dump())
    except NotebookConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if value["agent_id"] != canonical_agent_id(agent_id):
        raise HTTPException(404, "notebook record not found")
    return value


@router.post("/{agent_id}/records/{memory_id}/correct", status_code=201)
def correct_record(
    agent_id: str,
    memory_id: str,
    body: RecordCorrection,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        value = _store().correct_record(principal, memory_id, **body.model_dump())
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    if value["agent_id"] != canonical_agent_id(agent_id):
        raise HTTPException(404, "notebook record not found")
    return value


@router.delete("/{agent_id}/records/{memory_id}")
def delete_record(
    agent_id: str,
    memory_id: str,
    body: RecordDelete,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        value = _store().delete_record(principal, memory_id, reason=body.reason)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    if value["memory_id"] != memory_id:
        raise HTTPException(409, "deletion confirmation mismatch")
    return value


@router.get("/{agent_id}/records/{memory_id}/history")
def history(
    agent_id: str,
    memory_id: str,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        value = _store().version_history(principal, memory_id)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    if value["agent_id"] != canonical_agent_id(agent_id):
        raise HTTPException(404, "notebook record not found")
    return value


@router.get("/{agent_id}/export")
def export(
    agent_id: str,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    try:
        payload = _store().export_notebook(principal, agent_id)
    except (NotebookPermissionDenied, NotebookNotFound) as exc:
        raise HTTPException(403 if isinstance(exc, NotebookPermissionDenied) else 404, str(exc)) from None
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{agent_id}-notebook.json"'})


@router.get("/conditioning/{agent_id}")
def get_conditioning(
    agent_id: str,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    if principal.role != "OWNER":
        raise HTTPException(403, "owner authority required")
    return {"agent_id": canonical_agent_id(agent_id), "profile": BehaviorProfileStore().get(agent_id).as_dict()}


@router.put("/conditioning/{agent_id}")
def set_conditioning(
    agent_id: str,
    body: BehaviorUpdate,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-ORQEVIA-Actor"),
    role: str | None = Header(default=None, alias="X-ORQEVIA-Role"),
    admin: str | None = Header(default=None, alias="X-ORQEVIA-Notebook-Admin"),
):
    principal = _principal(authorization, actor, role, admin)
    if principal.role != "OWNER":
        raise HTTPException(403, "owner authority required")
    try:
        profile = BehaviorProfile(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return BehaviorProfileStore().set(agent_id, profile, updated_by=principal.actor_id)
