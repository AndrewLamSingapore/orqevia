"""Optional forecasting over observed queue events; no execution authorization."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .collective_api import _principal, _response
from .pif import PIFService
from .pif.history import QUEUE_ABSORBING, QUEUE_EDGES, QUEUE_STATES, read_compute_history

router = APIRouter(prefix="/api/collective/v1/intelligence/pif", tags=["probabilistic-intelligence"])


class Forecast(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: str | dict[str, float] = "queued"
    steps: int = Field(default=2, ge=0, strict=True)
    model_id: str = "queue-state"
    version: str | None = None


class Scenario(Forecast):
    samples: int = Field(default=100, ge=1, strict=True)
    seed: int = Field(default=0, strict=True)


class Fit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    agent: str | None = None
    since: str | None = None
    until: str | None = None
    validation_cutoff: str | None = None


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = "queue-state"
    version: str


def service(request: Request) -> PIFService:
    principal = _principal(request, require_enabled=False)
    scope = hashlib.sha256((principal.tenant_id + ":" + principal.owner_id).encode()).hexdigest()
    return PIFService(tenant_id="owner:" + scope)


def result(request: Request, operation):
    try:
        return _response(request, operation())
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "Invalid probabilistic intelligence contract") from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Probabilistic intelligence unavailable") from None


@router.get("/status")
def status(request: Request):
    return result(request, service(request).health)


@router.post("/fit")
def fit(request: Request, body: Fit):
    current = service(request)

    def observed_fit():
        if not current.enabled:
            return {"status": "DISABLED", "reason": "PIF_FLAG_DISABLED", "grants_execution_authority": False}
        queue = Path(
            os.getenv("ORQEVIA_COMPUTE_QUEUE_DB") or Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "compute-queue.db"
        )
        histories, diagnostics = read_compute_history(queue, agent=body.agent, since=body.since, until=body.until)
        revision = os.getenv("ORQEVIA_RUNTIME_REVISION", "")
        value = current.fit_history(
            histories,
            states=QUEUE_STATES,
            absorbing_states=QUEUE_ABSORBING,
            allowed_edges=QUEUE_EDGES,
            validation_cutoff=body.validation_cutoff,
            source_revision=revision if len(revision) == 40 else None,
            evidence_source="COMPUTE_EVENT_LEDGER_UNCLASSIFIED",
        )
        value["ingestion"] = diagnostics
        return value

    return result(request, observed_fit)


@router.post("/forecast")
@router.post("/transition")
@router.post("/risk")
def forecast(request: Request, body: Forecast):
    current = service(request)
    operation = request.url.path.rsplit("/", 1)[-1]

    def invoke():
        kwargs = {"model_id": body.model_id, "version": body.version}
        if operation == "transition":
            return current.predict_transition(body.start, **kwargs)
        if operation == "risk":
            return current.estimate_failure_risk(body.start, steps=body.steps, **kwargs)
        return current.forecast_state(body.start, steps=body.steps, **kwargs)

    return result(request, invoke)


@router.post("/scenario")
def scenario(request: Request, body: Scenario):
    current = service(request)
    return result(
        request,
        lambda: current.simulate_scenario(
            body.start,
            steps=body.steps,
            samples=body.samples,
            seed=body.seed,
            model_id=body.model_id,
            version=body.version,
        ),
    )


@router.get("/model")
def model(request: Request, model_id: str = "queue-state", version: str | None = None):
    current = service(request)
    return result(request, lambda: current.get_model_metadata(model_id=model_id, version=version))


@router.get("/evidence/{trace_id}")
def evidence(request: Request, trace_id: str):
    current = service(request)
    return result(request, lambda: current.get_prediction_evidence(trace_id))


@router.post("/hidden-state")
def hidden_state(request: Request):
    return result(request, service(request).infer_hidden_state)


@router.post("/intervention")
def intervention(request: Request):
    return result(request, service(request).evaluate_intervention)


@router.post("/rollback")
def rollback(request: Request, body: Selection):
    current = service(request)
    return result(request, lambda: current.select_model_version(body.model_id, body.version))
