import asyncio
import datetime
import hashlib
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
    HiggsfieldCatalogSnapshot,
    HiggsfieldCliDiscovery,
    HiggsfieldGenerationReceipt,
    HiggsfieldMediaService,
    HiggsfieldMediaSettings,
    HiggsfieldValidationReceipt,
    higgsfield_generation_contract_sha256,
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


def write_signed_json(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    path.with_name(path.name + ".sha256").write_text(
        hashlib.sha256(raw).hexdigest(),
        encoding="ascii",
    )


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


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (404, "PROVIDER_NOT_FOUND"),
        (429, "PROVIDER_RATE_LIMIT"),
        (500, "PROVIDER_FAILURE"),
    ),
)
def test_api_provider_classifies_http_failures(status, code):
    calls = []

    async def sleep(delay):
        return None

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"detail": "provider"})

    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(handler),
        sleeper=sleep,
    )
    with pytest.raises(MediaProviderError, match=code):
        asyncio.run(provider.estimate(media_request()))
    assert len(calls) == (2 if status in {429, 500} else 1)


def test_api_provider_classifies_network_failure():
    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    async def sleep(delay):
        return None

    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(fail),
        sleeper=sleep,
    )
    with pytest.raises(MediaProviderError, match="PROVIDER_TRANSPORT_FAILURE"):
        asyncio.run(provider.estimate(media_request()))


def test_api_provider_requires_cloud_permission_and_charge_authorization():
    provider = HiggsfieldApiProvider(settings(), secret_resolver=lambda _: "id:secret")
    with pytest.raises(MediaProviderError, match="DATA_LOCALITY"):
        asyncio.run(provider.estimate(media_request(data_classification="LOCAL_ONLY")))
    with pytest.raises(MediaProviderError, match="CHARGE_NOT_AUTHORIZED"):
        asyncio.run(provider.submit(media_request(charge_authorized=False), MediaEstimate(Decimal("0.01"))))


def test_service_blocks_when_provider_is_disabled():
    service = HiggsfieldMediaService(
        settings(enabled=False, database_path=":memory:"),
    )
    with pytest.raises(MediaProviderError, match="PROVIDER_DISABLED"):
        asyncio.run(service.estimate(media_request(), owner_id="owner"))


def test_api_provider_rejects_off_origin_status_and_cancel_urls():
    provider = HiggsfieldApiProvider(
        settings(),
        secret_resolver=lambda _: "id:secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={**submit_body(), "status_url": "https://evil.invalid/status"},
            )
        ),
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
    assert job.outputs == (
        {"type": "image", "url": "https://cdn.example.com/result.png", "retention": "PROVIDER_MANAGED_AT_LEAST_7_DAYS"},
    )
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
            return MediaJob(
                request_id=request_id,
                status="completed",
                provider="higgsfield",
                operation="image",
                model_path="official/model/path",
                task_id="task-higgsfield-1",
            )

        async def cancel(self, request_id, *, cancel_url=None):
            return MediaJob(
                request_id=request_id,
                status="canceled",
                provider="higgsfield",
                operation="image",
                model_path="official/model/path",
                task_id="task-higgsfield-1",
            )

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


def test_cli_discovery_fails_safely_for_missing_expired_and_invalid_auth(tmp_path):
    with pytest.raises(MediaProviderError, match="CLI_UNAVAILABLE"):
        HiggsfieldCliDiscovery(str(tmp_path / "missing-hf.exe"))

    expired = HiggsfieldCliDiscovery(
        sys.executable,
        runner=lambda arguments, timeout: subprocess.CompletedProcess(
            arguments, 1, "", "Session expired"
        ),
    )
    with pytest.raises(MediaProviderError, match="CLI_COMMAND_FAILED"):
        expired.snapshot()

    invalid = HiggsfieldCliDiscovery(
        sys.executable,
        runner=lambda arguments, timeout: subprocess.CompletedProcess(
            arguments, 0, "not-json", ""
        ),
    )
    with pytest.raises(MediaProviderError, match="CLI_RESPONSE_INVALID"):
        invalid.snapshot()


def test_host_catalog_snapshot_is_digest_verified_and_read_only(tmp_path):
    snapshot = {
        "schema_version": "orqevia.higgsfield-catalog.v1",
        "generated_at_utc": "2026-10-19T06:00:00+00:00",
        "cli_version": "higgsfield 1.2.2",
        "catalog": {
            "status": "AUTHENTICATED",
            "workspace": {
                "id": "866bb96e-494f-47aa-87a2-9530b1da977b",
                "name": "Private workspace",
                "plan": "free",
                "credits": 10,
                "role": "owner",
                "selected": True,
                "email": "must-not-be-returned@example.invalid",
            },
            "account": {"plan": "free", "credits": 10},
            "models": [{"display_name": "Image", "job_type": "image_model", "type": "image"}],
            "workflows": [{"display_name": "Marketing", "job_type": "marketing_studio_image", "type": "image"}],
        },
    }
    raw = json.dumps(snapshot, sort_keys=True).encode()
    catalog = tmp_path / "catalog.json"
    digest = tmp_path / "catalog.json.sha256"
    catalog.write_bytes(raw)
    digest.write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")

    discovery = HiggsfieldCatalogSnapshot(str(catalog), str(digest))
    result = discovery.snapshot()
    assert result["source"] == "WINDOWS_CLI_SNAPSHOT"
    assert result["model_count"] == 1 and result["workflow_count"] == 1
    assert "email" not in json.dumps(result).lower()
    stale = HiggsfieldCatalogSnapshot(str(catalog), str(digest), max_age_seconds=1)
    assert stale.health()["status"] == "STALE"
    with pytest.raises(MediaProviderError, match="CATALOG_STALE"):
        stale.snapshot()
    with pytest.raises(MediaProviderError, match="CATALOG_UNAVAILABLE"):
        HiggsfieldCatalogSnapshot(str(catalog), str(tmp_path / "missing.sha256")).snapshot()
    digest.write_text("0" * 64, encoding="ascii")
    with pytest.raises(MediaProviderError, match="CATALOG_UNAVAILABLE"):
        discovery.snapshot()


def test_non_billable_validation_receipt_and_health_states(tmp_path):
    receipt = {
        "schema_version": "orqevia.higgsfield-provider-validation.v1",
        "result": "PASSED",
        "validated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "credential_format_verified": True,
        "credential_fingerprint_sha256": "a" * 64,
        "provider_authentication_verified": True,
        "estimate_verified": True,
        "quota_entitlement_verified": False,
        "generation_execution_verified": False,
        "billable_generation_submitted": False,
        "network_probe_performed": True,
        "model_path": "higgsfield-ai/soul/v2/standard",
        "estimated_usd": "0.10",
        "estimated_credits": "1.5",
        "error_code": None,
    }
    raw = json.dumps(receipt, sort_keys=True).encode()
    path = tmp_path / "validation.json"
    digest = tmp_path / "validation.json.sha256"
    path.write_bytes(raw)
    digest.write_text(hashlib.sha256(raw).hexdigest(), encoding="ascii")
    validation = HiggsfieldValidationReceipt(str(path), str(digest))
    assert validation.health()["status"] == "VALID"
    assert validation.health()["billable_generation_submitted"] is False

    class ReadyProvider:
        def health(self):
            return {"readiness": "READY", "enabled": False}

        def credential_fingerprint(self):
            return "a" * 64

    disabled = HiggsfieldMediaService(
        settings(enabled=False, database_path=":memory:"),
        provider=ReadyProvider(),
        validation=validation,
    ).health()
    assert disabled["status"] == "DISABLED"
    assert disabled["rest_credentials"] == "VALID"
    assert disabled["rest_execution_ready"] is False

    class DifferentKeyProvider(ReadyProvider):
        def credential_fingerprint(self):
            return "b" * 64

    mismatch = HiggsfieldMediaService(
        settings(enabled=False, database_path=":memory:"),
        provider=DifferentKeyProvider(),
        validation=validation,
    ).health()
    assert mismatch["rest_credentials_valid"] is False
    assert mismatch["credential_matches_validation"] is False

    receipt.update(result="FAILED", provider_authentication_verified=False, estimate_verified=False)
    raw = json.dumps(receipt, sort_keys=True).encode()
    path.write_bytes(raw)
    digest.write_text(hashlib.sha256(raw).hexdigest(), encoding="ascii")
    assert validation.health()["status"] == "FAILED"

    digest.write_text("0" * 64, encoding="ascii")
    assert validation.health()["status"] == "INVALID"


def test_live_generation_receipt_is_digest_contract_and_store_bound(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    request_id = "f315a087-24e9-4f6c-b58a-05f91b421cdf"
    idempotency_key = "fixture-generation-acceptance"
    output_hash = "c" * 64
    contract_hash = higgsfield_generation_contract_sha256()

    catalog_path = tmp_path / "catalog.json"
    write_signed_json(catalog_path, {
        "schema_version": "orqevia.higgsfield-catalog.v1",
        "generated_at_utc": now,
        "cli_version": "higgsfield 1.2.2",
        "catalog": {
            "status": "AUTHENTICATED",
            "workspace": {
                "id": "866bb96e-494f-47aa-87a2-9530b1da977b",
                "name": "Private workspace",
                "plan": "free",
                "credits": 10,
                "role": "owner",
                "selected": True,
            },
            "account": {"plan": "free", "credits": 10},
            "models": [],
            "workflows": [],
        },
    })
    validation_path = tmp_path / "validation.json"
    write_signed_json(validation_path, {
        "schema_version": "orqevia.higgsfield-provider-validation.v1",
        "result": "PASSED",
        "validated_at_utc": now,
        "credential_format_verified": True,
        "credential_fingerprint_sha256": "a" * 64,
        "provider_authentication_verified": True,
        "estimate_verified": True,
        "quota_entitlement_verified": False,
        "generation_execution_verified": False,
        "billable_generation_submitted": False,
        "network_probe_performed": True,
        "model_path": "higgsfield-ai/soul/v2/standard",
        "estimated_usd": "0.004",
        "estimated_credits": "0.050",
        "error_code": None,
    })
    generation_path = tmp_path / "generation.json"
    generation_payload = {
        "schema_version": "orqevia.higgsfield-generation-acceptance.v1",
        "provider": "higgsfield",
        "observed_at_utc": now,
        "request_id": request_id,
        "task_id": "higgsfield-acceptance-fixture",
        "model": "higgsfield-ai/soul/v2/standard",
        "idempotency_key": idempotency_key,
        "terminal_status": "completed",
        "polls": 5,
        "error_code": None,
        "estimated_usd": "0.004",
        "maximum_cost_usd": "0.25",
        "outputs": [{"bytes": 10, "sha256": output_hash, "host": "cdn.example.invalid"}],
        "result_urls_exported": False,
        "credential_fingerprint_sha256": "a" * 64,
        "provider_contract_sha256": contract_hash,
        "entitlement_scope": "SELECTED_MODEL_EXECUTION",
    }
    write_signed_json(generation_path, generation_payload)
    generation = HiggsfieldGenerationReceipt(
        str(generation_path),
        str(generation_path.with_name(generation_path.name + ".sha256")),
    )
    assert generation.health()["status"] == "VALID"

    class ReadyProvider:
        def health(self):
            return {"readiness": "READY", "enabled": True}

        def credential_fingerprint(self):
            return "a" * 64

    class MatchingStore:
        def get_by_idempotency(self, key, *, owner_id):
            assert key == idempotency_key and owner_id == "owner"
            return {
                "provider_id": "higgsfield",
                "request_id": request_id,
                "task_id": "higgsfield-acceptance-fixture",
                "model_path": "higgsfield-ai/soul/v2/standard",
                "status": "completed",
                "estimated_usd": "0.004",
                "outputs_json": json.dumps([{"url": "https://cdn.example.invalid/output.png"}]),
            }

    service = HiggsfieldMediaService(
        settings(database_path=":memory:"),
        provider=ReadyProvider(),
        discovery=HiggsfieldCatalogSnapshot(
            str(catalog_path),
            str(catalog_path.with_name(catalog_path.name + ".sha256")),
        ),
        validation=HiggsfieldValidationReceipt(
            str(validation_path),
            str(validation_path.with_name(validation_path.name + ".sha256")),
        ),
        generation=generation,
        store=MatchingStore(),
    )
    health = service.health()
    assert health["status"] == "READY"
    assert health["rest_execution_ready"] is True
    assert health["generation_execution_verified"] is True
    assert health["quota_entitlement_verified"] is True
    assert health["quota_entitlement_scope"] == "SELECTED_MODEL_EXECUTION"
    assert health["generation"]["request_id"] == request_id
    assert "credential_fingerprint_sha256" not in health["generation"]

    generation_payload.update(credential_fingerprint_sha256="b" * 64)
    write_signed_json(generation_path, generation_payload)
    key_mismatch = service.health()
    assert key_mismatch["status"] == "DEGRADED"
    assert key_mismatch["generation_execution_verified"] is False

    generation_payload.update(
        credential_fingerprint_sha256="a" * 64,
        provider_contract_sha256="b" * 64,
    )
    write_signed_json(generation_path, generation_payload)
    contract_mismatch = service.health()
    assert contract_mismatch["status"] == "DEGRADED"
    assert contract_mismatch["rest_execution_ready"] is False

    generation_payload.update(provider_contract_sha256=contract_hash)
    generation_payload.update(terminal_status="failed", error_code="PROVIDER_GENERATION_FAILED")
    write_signed_json(generation_path, generation_payload)
    assert generation.health()["status"] == "FAILED"

    generation_payload.update(terminal_status="completed", error_code=None)
    write_signed_json(generation_path, generation_payload)
    generation_path.with_name(generation_path.name + ".sha256").write_text(
        "0" * 64,
        encoding="ascii",
    )
    assert generation.health()["status"] == "INVALID"
    failed_binding = service.health()
    assert failed_binding["status"] == "DEGRADED"
    assert failed_binding["rest_execution_ready"] is False
    assert failed_binding["generation_execution_verified"] is False


def test_media_routes_require_owner_auth(monkeypatch):
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "fixture-owner-token")
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
