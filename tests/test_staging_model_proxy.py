"""Security fixtures for sharing local inference without administrative authority."""

import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
import pytest

from scripts import staging_model_proxy as proxy


def test_staging_denies_model_administration_and_unconfigured_models():
    with TestClient(proxy.app) as client:
        for method, path in (
            ("post", "/api/pull"),
            ("delete", "/api/delete"),
            ("post", "/api/create"),
            ("get", "/api/tags?target=elsewhere"),
        ):
            assert getattr(client, method)(path).status_code == 404
        for body in (
            {"model": "unconfigured"},
            {"model": "gemma3:12b", "options": {"num_ctx": 131072}},
            {"model": "gemma3:12b", "options": {"num_gpu": 1000}},
            {"model": "gemma3:12b", "tools": []},
        ):
            assert client.post("/api/chat", json=body).status_code == 422
        assert client.post("/api/chat", content=b"x" * (proxy.BODY_LIMIT + 1)).status_code == 413


def test_staging_forwards_only_fixed_inference_target_and_bounds_keepalive():
    actual_client = httpx.AsyncClient
    seen = []

    def upstream(request):
        seen.append(request)
        assert str(request.url) == proxy.TARGET + "/api/generate"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["keep_alive"] == "2m"
        assert body["options"]["num_ctx"] == 8192
        return httpx.Response(
            200, content=b'{"response":"fixture","done":true}\n', headers={"Content-Type": "application/x-ndjson"}
        )

    with patch.object(
        proxy.httpx,
        "AsyncClient",
        side_effect=lambda **kw: actual_client(transport=httpx.MockTransport(upstream), **kw),
    ):
        with TestClient(proxy.app) as client:
            response = client.post(
                "/api/generate",
                json={"model": "gemma3:12b", "prompt": "fixture", "keep_alive": -1},
                headers={"Authorization": "Bearer must-not-forward"},
            )
    assert response.status_code == 200 and response.json()["done"] is True
    assert response.headers["cache-control"] == "no-store" and len(seen) == 1


@pytest.mark.parametrize("upstream_status", [301, 401, 500])
def test_staging_sanitizes_upstream_failure(upstream_status):
    actual_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(upstream_status, text="private upstream credentials")
    )
    with patch.object(proxy.httpx, "AsyncClient", side_effect=lambda **kw: actual_client(transport=transport, **kw)):
        with TestClient(proxy.app) as client:
            response = client.get("/api/tags")
    assert response.status_code == 503 and "credentials" not in response.text


def test_brief_inference_overlap_waits_without_running_parallel_requests(monkeypatch):
    actual_client = httpx.AsyncClient

    async def scenario():
        monkeypatch.setattr(proxy, "_slot", asyncio.Semaphore(1))
        active, maximum = 0, 0

        async def upstream(request):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.2)
                return httpx.Response(200, content=b'{"done":true}\n')
            finally:
                active -= 1

        async with actual_client(transport=httpx.ASGITransport(app=proxy.app), base_url="http://stage") as client:
            with patch.object(
                proxy.httpx,
                "AsyncClient",
                side_effect=lambda **kw: actual_client(transport=httpx.MockTransport(upstream), **kw),
            ):
                body = {"model": "gemma3:12b", "prompt": "fixture"}
                responses = await asyncio.gather(
                    client.post("/api/chat", json=body), client.post("/api/chat", json=body)
                )
        assert [r.status_code for r in responses] == [200, 200]
        assert maximum == 1

    asyncio.run(scenario())
