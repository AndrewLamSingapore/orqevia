"""Authenticated model-registry lifecycle API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .client_auth import authenticate_owner
from .model_registry import ModelRegistryStore, ModelVersion


router = APIRouter(prefix="/api/model-registry", tags=["model-registry"])


class ModelRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=256)
    location: str = Field(pattern="^(local|cloud)$")
    context_tokens: int = Field(gt=0, le=10_000_000)
    output_tokens: int = Field(gt=0, le=10_000_000)
    capabilities: list[str] = Field(min_length=1, max_length=64)
    artifact_sha256: str = Field(pattern="^[0-9a-fA-F]{64}$")
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(PASS|FAIL)$")
    evidence_ref: str = Field(min_length=1, max_length=1000)
    checks: list[Any] | dict[str, Any]
    summary: str | None = Field(default=None, max_length=2000)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)
    compatibility: dict[str, Any]


class Activation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    version: str


class Rollback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_version: str
    reason: str = Field(min_length=1, max_length=1000)


def _store() -> ModelRegistryStore:
    return ModelRegistryStore()


def _owner(authorization: str | None) -> str:
    authenticate_owner(authorization)
    return "owner"


@router.get("/health")
def health():
    return _store().health()


@router.post("/models", status_code=201)
def register(body: ModelRegistration, authorization: str | None = Header(default=None)):
    actor = _owner(authorization)
    try:
        model = ModelVersion(
            model_id=body.model_id,
            version=body.version,
            provider=body.provider,
            model_name=body.model_name,
            location=body.location,
            context_tokens=body.context_tokens,
            output_tokens=body.output_tokens,
            capabilities=tuple(body.capabilities),
            artifact_sha256=body.artifact_sha256,
            source_url=body.source_url,
            metadata=body.metadata,
        )
        return _store().register(model, actor=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/models")
def list_models(
    model_id: str | None = None,
    state: str | None = None,
    authorization: str | None = Header(default=None),
):
    _owner(authorization)
    try:
        return {"models": _store().list_models(model_id=model_id, state=state)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/models/{model_id}/{version}")
def get_model(model_id: str, version: str, authorization: str | None = Header(default=None)):
    _owner(authorization)
    try:
        return _store().get(model_id, version)
    except KeyError:
        raise HTTPException(404, "model version not found") from None


@router.post("/models/{model_id}/{version}/evaluate")
def evaluate(
    model_id: str,
    version: str,
    body: Evaluation,
    authorization: str | None = Header(default=None),
):
    actor = _owner(authorization)
    try:
        return _store().evaluate(model_id, version, body.model_dump(), actor=actor)
    except KeyError:
        raise HTTPException(404, "model version not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/models/{model_id}/{version}/approve")
def approve(
    model_id: str,
    version: str,
    body: Approval,
    authorization: str | None = Header(default=None),
):
    actor = _owner(authorization)
    try:
        return _store().approve(
            model_id,
            version,
            body.compatibility,
            actor=actor,
            reason=body.reason,
        )
    except KeyError:
        raise HTTPException(404, "model version not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/models/{model_id}/{version}/activate")
def activate(
    model_id: str,
    version: str,
    body: Activation,
    authorization: str | None = Header(default=None),
):
    actor = _owner(authorization)
    try:
        return _store().activate(model_id, version, actor=actor, reason=body.reason)
    except KeyError:
        raise HTTPException(404, "model version not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/models/{model_id}/rollback")
def rollback(
    model_id: str,
    body: Rollback,
    authorization: str | None = Header(default=None),
):
    actor = _owner(authorization)
    try:
        return _store().rollback(
            model_id,
            body.target_version,
            actor=actor,
            reason=body.reason,
        )
    except KeyError:
        raise HTTPException(404, "model version not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/assignments/{agent_id}")
def assign(
    agent_id: str,
    body: Assignment,
    authorization: str | None = Header(default=None),
):
    actor = _owner(authorization)
    try:
        return _store().assign(agent_id, body.model_id, body.version, actor=actor)
    except KeyError:
        raise HTTPException(404, "model version not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/models/{model_id}/{version}/history")
def history(model_id: str, version: str, authorization: str | None = Header(default=None)):
    _owner(authorization)
    try:
        return _store().history(model_id, version)
    except KeyError:
        raise HTTPException(404, "model version not found") from None
