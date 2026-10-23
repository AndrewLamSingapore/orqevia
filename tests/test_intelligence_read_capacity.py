"""Ordinary page-load bursts queue while authentication and slot bounds hold."""

import asyncio

from fastapi import FastAPI
import httpx

from app.orqevia.security import install


def test_authenticated_read_burst_queues_without_raising_the_concurrency_limit(monkeypatch, tmp_path):
    token = "fixture-intelligence-owner-token-only"
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", token)
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    app = FastAPI()
    install(app)
    active = 0
    peak = 0

    @app.get("/probe")
    async def probe():
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        try:
            await asyncio.sleep(0.1)
            return {"ok": True}
        finally:
            active -= 1

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            assert (await client.get("/probe")).status_code == 401
            responses = await asyncio.gather(
                *[client.get("/probe", headers={"Authorization": "Bearer " + token}) for _ in range(6)]
            )
            assert all(response.status_code == 200 and response.json() == {"ok": True} for response in responses)
        assert peak == 2
        assert active == 0

    asyncio.run(exercise())
