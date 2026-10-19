import asyncio
import json
import subprocess
import sys
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.higgsfield_media import (
    HiggsfieldApiProvider,
    HiggsfieldCliDiscovery,
    HiggsfieldMediaService,
    HiggsfieldMediaSettings,
)
from app.media_generation import MediaEstimate, MediaJob, MediaJobRequest, MediaJobStore, MediaProviderError


REQUEST_ID = "d7e6c0f3-6699-4f6c-bb45-2ad7fd9158ff"
STATUS_URL = f"https://api.higgsfield.ai/requests/{REQUEST_ID}/status"
CANCEL_URL = f"https://api.higgsfield.ai/requests/{REQUEST_ID}/cancel"


def settings(**changes):
    values = {
        "enabled": True,
        "api_key_ref": "env:ORQEVIA_HIGGSFIELD_API_KEY",
        "max_cost_usd": Decimal("0.25"),
        "max_jobs_per_day": 3,
        "max_concurrent_jobs": 1,
        "database_path": ":memory:",
    }
    values.update(changes)
    return HiggsfieldMediaSettings(**values)


def media_request(key="fixture-key", **changes):
    values = {
        "task_id": "task-higgsfield-1",
        "operation": "image",
        "model_path": "official/model/path",
        "payload": {"prompt": "a neutral fixture"},
        "data_classification": "CLOUD_PERMITTED",
        "max_cost_usd": Decimal("0.10"),
        "charge_authorized": True,
        "idempotency_key": key,
    }
    values.update(changes)
    return MediaJobRequest.create(**values)


def submit_body():
    return {
        "status": "queued",
        "request_id": REQUEST_ID,
        "status_url": STATUS_URL,
        "cancel_url": CANCEL_URL,
    }


def status_body(status="queued"):
    body = {"status": status, "request_id": REQUEST_ID}
    if status == "completed":
        body["images"] = [{"url": "https://cdn.example.com/result.png"}]
    return body


def test_api_provider_estimate_and_submit_use_documented_contracts():
    observed = []

    def handler(request):
        observed.append(request)
        if request.url.path.startswith("/estimate/"):
            return httpx.Response(200, json={"credits": "1.500", "usd": "0.094"})
        return httpx.Response(200, json=submit_body(), headers={"X-Correlation-ID": "correlation-1"})

    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "key-id:key-secret",
        transport=httpx.MockTransport(handler),
    )
    request = media_request()
    estimate = asyncio.run(provider.estimate(request))
    job = asyncio.run(provider.submit(request, estimate))
    assert estimate.usd == Decimal("0.094") and estimate.credits == Decimal("1.500")
    assert job.request_id == REQUEST_ID and job.status == "queued" and job.correlation_id == "correlation-1"
    assert observed[0].headers["authorization"] == "Key key-id:key-secret"
    assert observed[1].headers["idempotency-key"] == "fixture-key"
    assert json.loads(observed[1].content) == {"prompt": "a neutral fixture"}
    assert "key-secret" not in str(job.as_public_dict())


def test_api_provider_fails_closed_without_credentials():
    provider = HiggsfieldApiProvider(settings(), secret_resolver=lambda _: "")
    assert provider.health()["readiness"] == "CREDENTIAL_UNAVAILABLE"
    with pytest.raises(MediaProviderError, match="CREDENTIAL_UNAVAILABLE"):
        asyncio.run(provider.estimate(media_request()))


def test_api_provider_requires_cloud_permission_and_charge_authorization():
    provider = HiggsfieldApiProvider(settings(), secret_resolver=lambda _: "id:secret")
    with pytest.raises(MediaProviderError, match="DATA_LOCALITY"):
        asyncio.run(provider.estimate(media_request(data_classification="LOCAL_ONLY")))
    with pytest.raises(MediaProviderError, match="CHARGE_NOT_AUTHORIZED"):
        asyncio.run(provider.submit(media_request(charge_authorized=False), MediaEstimate(Decimal("0.01"))))


def test_api_provider_rejects_off_origin_status_and_cancel_urls():
    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200,
            json={**submit_body(), "status_url": "https://evil.invalid/status"},
        )),
    )
    with pytest.raises(MediaProviderError, match="INVALID_PROVIDER_URL"):
        asyncio.run(provider.submit(media_request(), MediaEstimate(Decimal("0.01"))))


def test_api_provider_retries_status_with_backoff_and_maps_outputs():
    calls = []
    delays = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, json={"detail": "provider fault"})
        if request.method == "GET":
            return httpx.Response(200, json=status_body("completed"))
        return httpx.Response(202)

    async def sleep(delay):
        delays.append(delay)

    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(handler),
        sleeper=sleep,
    )
    job = asyncio.run(provider.status(REQUEST_ID, status_url=STATUS_URL))
    assert job.status == "completed"
    assert job.outputs == ({"type": "image", "url": "https://cdn.example.com/result.png", "retention": "PROVIDER_MANAGED_AT_LEAST_7_DAYS"},)
    assert delays == [1]


def test_api_provider_cancel_requires_queued_state_and_returns_202():
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.method == "GET":
            return httpx.Response(200, json=status_body("queued"))
        return httpx.Response(202)

    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(handler),
    )
    job = asyncio.run(provider.cancel(REQUEST_ID, cancel_url=CANCEL_URL))
    assert job.status == "canceled"
    assert calls[-1][0] == "POST"


def test_service_uses_estimate_limits_and_durable_idempotency(tmp_path):
    class Provider:
        provider_id = "higgsfield"
        def __init__(self):
            self.estimates = 0
            self.submits = 0
        def health(self):
            return {"readiness": "READY"}
        async def estimate(self, request):
            self.estimates += 1
            return MediaEstimate(Decimal("0.09"), Decimal("1.5"))
        async def submit(self, request, estimate):
            self.submits += 1
            return MediaJob(
                request_id=REQUEST_ID,
                status="queued",
                provider="higgsfield",
                operation=request.operation,
                model_path=request.model_path,
                task_id=request.task_id,
                estimated_usd=estimate.usd,
            )
        async def status(self, request_id, *, status_url=None):
            return MediaJob(request_id=request_id, status="completed", provider="higgsfield",
                            operation="image", model_path="official/model/path", task_id="task-higgsfield-1")
        async def cancel(self, request_id, *, cancel_url=None):
            return MediaJob(request_id=request_id, status="canceled", provider="higgsfield",
                            operation="image", model_path="official/model/path", task_id="task-higgsfield-1")

    provider = Provider()
    service = HiggsfieldMediaService(
        settings(database_path=str(tmp_path / "media.db"), max_concurrent_jobs=10),
        provider=provider,
        store=MediaJobStore(tmp_path / "media.db"),
    )
    request = media_request()
    first = asyncio.run(service.submit(request, owner_id="owner"))
    second = asyncio.run(service.submit(request, owner_id="owner"))
    assert first["request_id"] == REQUEST_ID and second["request_id"] == REQUEST_ID
    assert provider.estimates == 1 and provider.submits == 1
    with pytest.raises(MediaProviderError, match="DAILY_JOB_LIMIT"):
        second_request = media_request(key="second-key")
        service.settings = HiggsfieldMediaSettings(**{**service.settings.__dict__, "max_jobs_per_day": 1})
        asyncio.run(service.submit(second_request, owner_id="owner"))


def test_cli_discovery_is_read_only_and_sanitizes_account_email():
    calls = []

    def runner(arguments, timeout):
        calls.append(arguments)
        values = {
            ("workspace", "status", "--json"): {
                "id": "866bb96e-494f-47aa-87a2-9530b1da977b",
                "plan_type": "free",
                "credits": 10,
                "is_selected": True,
                "user_role": "owner",
                "email": "private@example.invalid",
            },
            ("account", "status", "--json"): {
                "credits": 10,
                "subscription_plan_type": "free",
                "email": "private@example.invalid",
            },
            ("model", "list", "--json"): [
                {"display_name": "Image", "job_type": "image_model", "type": "image"},
                {"display_name": "Bad", "job_type": "../../unsafe", "type": "image"},
            ],
            ("workflow", "list", "--json"): [
                {"display_name": "Marketing", "job_type": "marketing_studio_image", "type": "image"},
            ],
        }
        return subprocess.CompletedProcess(arguments, 0, json.dumps(values[tuple(arguments)]), "")

    discovery = HiggsfieldCliDiscovery(sys.executable, runner=runner)
    result = discovery.snapshot()
    assert result["workspace"]["id"] == "866bb96e-494f-47aa-87a2-9530b1da977b"
    assert result["workspace"]["selected"] is True
    assert result["model_count"] == 1 and result["workflow_count"] == 1
    assert "email" not in json.dumps(result).lower()
    assert calls == [
        ["workspace", "status", "--json"],
        ["account", "status", "--json"],
        ["model", "list", "--json"],
        ["workflow", "list", "--json"],
    ]
    with pytest.raises(MediaProviderError, match="INVALID_MODEL_ID"):
        discovery.model("../../escape")


def test_media_routes_require_owner_auth(monkeypatch):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-owner-token")
    from app import media_api

    class FakeService:
        def health(self):
            return {"provider": "higgsfield", "enabled": False}

    monkeypatch.setattr(media_api, "_SERVICE", FakeService())
    app = FastAPI()
    app.include_router(media_api.router)
    client = TestClient(app)
    assert client.get("/media/v1/health").status_code == 401
    response = client.get("/media/v1/health", headers={"Authorization": "Bearer fixture-owner-token"})
    assert response.status_code == 200
    assert response.json()["provider"] == "higgsfield"

