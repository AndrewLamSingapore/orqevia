"""Optional efficiency inventory/experiment API; never replaces a model route."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .collective_api import _principal, _response
from .mel import MELService

router = APIRouter(prefix="/api/collective/v1/intelligence/mel", tags=["model-efficiency"])


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    evidence: dict[str, Any]


def scope(request: Request):
    principal = _principal(request, require_enabled=False)
    tenant = hashlib.sha256((principal.tenant_id + ":" + principal.owner_id).encode()).hexdigest()
    return "owner:" + tenant, principal.actor_id


def result(request: Request, operation):
    try:
        return _response(request, operation())
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "Invalid model efficiency evidence contract") from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Model efficiency evidence unavailable") from None


@router.get("/status")
def status(request: Request):
    scope(request)
    return result(request, MELService().health)


@router.get("/inventory")
def inventory(request: Request):
    scope(request)
    return result(request, MELService().inventory)


@router.get("/experiments")
def experiments(request: Request):
    tenant, _ = scope(request)
    return result(request, lambda: MELService().experiments(tenant))


@router.post("/experiments")
def record(request: Request, body: Experiment):
    tenant, actor = scope(request)
    return result(request, lambda: MELService().record_experiment(body.evidence, tenant_id=tenant, actor=actor))


@router.get("/recommendation")
def recommendation(request: Request, model_id: str = "minilm-onnx", max_quality_loss: float = 0.01):
    tenant, _ = scope(request)
    return result(
        request, lambda: MELService().recommend(model_id, tenant_id=tenant, max_quality_loss=max_quality_loss)
    )
