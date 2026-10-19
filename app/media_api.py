"""Owner-authenticated optional media API.

Routes remain present but fail closed unless the optional provider is explicitly
enabled and configured. No endpoint grants media tools to the 21 agents.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .client_auth import authenticate_owner
from .higgsfield_media import (
    HiggsfieldCliDiscovery,
    HiggsfieldMediaService,
    HiggsfieldMediaSettings,
)
from .media_generation import MediaJobRequest, MediaProviderError


router = APIRouter(prefix="/media/v1", tags=["media"])
_SERVICE: HiggsfieldMediaService | None = None


class MediaSubmission(BaseModel):
    task_id: str = Field(min_length=1, max_length=256)
    operation: Literal["image", "video", "audio", "workflow", "3d"]
    model_path: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
    data_classification: Literal["LOCAL_ONLY", "CLOUD_PERMITTED", "SENSITIVE", "RESTRICTED"]
    max_cost_usd: Decimal = Field(gt=0, le=Decimal("100"))
    charge_authorized: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    timeout_seconds: int = Field(default=900, ge=30, le=3600)

    def request(self) -> MediaJobRequest:
        return MediaJobRequest.create(
            task_id=self.task_id,
            operation=self.operation,
            model_path=self.model_path,
            payload=self.payload,
            data_classification=self.data_classification,
            max_cost_usd=self.max_cost_usd,
            charge_authorized=self.charge_authorized,
            idempotency_key=self.idempotency_key,
            timeout_seconds=self.timeout_seconds,
        )


def _service() -> HiggsfieldMediaService:
    global _SERVICE
    if _SERVICE is None:
        settings = HiggsfieldMediaSettings.from_env()
        discovery = None
        if settings.cli_executable:
            try:
                discovery = HiggsfieldCliDiscovery(settings.cli_executable)
            except MediaProviderError:
                discovery = None
        _SERVICE = HiggsfieldMediaService(settings, discovery=discovery)
    return _SERVICE


def _owner(authorization: str | None) -> str:
    authenticate_owner(authorization)
    return "owner"


def _http_error(error: MediaProviderError) -> HTTPException:
    status = {
        "PROVIDER_DISABLED": 503,
        "CREDENTIAL_UNAVAILABLE": 503,
        "CLI_UNAVAILABLE": 503,
        "PROVIDER_AUTHENTICATION": 502,
        "PROVIDER_INSUFFICIENT_CREDITS": 402,
        "PROVIDER_CONCURRENCY": 429,
        "PROVIDER_RATE_LIMIT": 429,
        "MAX_CONCURRENT_JOBS": 429,
        "DAILY_JOB_LIMIT": 429,
        "JOB_NOT_FOUND": 404,
        "PROVIDER_NOT_FOUND": 404,
        "JOB_NOT_CANCELABLE": 409,
        "IDEMPOTENCY_CONFLICT": 409,
        "PROVIDER_MODEL_BLOCKED": 423,
        "PROVIDER_MODEL_UNAVAILABLE": 503,
    }.get(error.code, 422 if error.pre_execution else 502)
    return HTTPException(
        status,
        {
            "error": error.code,
            "retryable": error.retryable,
            "correlation_id": error.correlation_id,
        },
    )


@router.get("/health")
def media_health(authorization: str | None = Header(default=None)):
    _owner(authorization)
    return _service().health()


@router.get("/catalog")
def media_catalog(authorization: str | None = Header(default=None)):
    _owner(authorization)
    try:
        return _service().discover()
    except MediaProviderError as error:
        raise _http_error(error) from None


@router.post("/estimate")
async def media_estimate(body: MediaSubmission, authorization: str | None = Header(default=None)):
    owner = _owner(authorization)
    try:
        estimate = await _service().estimate(body.request(), owner_id=owner)
        return estimate.as_public_dict()
    except MediaProviderError as error:
        raise _http_error(error) from None


@router.post("/jobs", status_code=202)
async def media_submit(body: MediaSubmission, authorization: str | None = Header(default=None)):
    owner = _owner(authorization)
    try:
        return await _service().submit(body.request(), owner_id=owner)
    except MediaProviderError as error:
        raise _http_error(error) from None


@router.get("/jobs/{request_id}")
async def media_status(request_id: str, authorization: str | None = Header(default=None)):
    owner = _owner(authorization)
    try:
        return await _service().status(request_id, owner_id=owner)
    except MediaProviderError as error:
        raise _http_error(error) from None


@router.post("/jobs/{request_id}/cancel")
async def media_cancel(request_id: str, authorization: str | None = Header(default=None)):
    owner = _owner(authorization)
    try:
        return await _service().cancel(request_id, owner_id=owner)
    except MediaProviderError as error:
        raise _http_error(error) from None
