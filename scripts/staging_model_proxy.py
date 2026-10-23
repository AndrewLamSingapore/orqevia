"""Share existing local inference with isolated staging without model administration.

Only this bounded adapter joins the production model network. Staging never
mounts production models, application databases, credentials or Docker's socket.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
import httpx

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TARGET = "http://orqevia-epoch-20261016-ollama-1:11434"
READS = {"/api/tags", "/api/version", "/api/ps"}
WRITES = {"/api/generate", "/api/chat", "/api/embed", "/api/embeddings"}
MODELS = {"gemma3:1b", "gemma3:12b", "embeddinggemma:300m-qat-q4_0"}
BODY_LIMIT = 1024 * 1024
RESPONSE_LIMIT = 16 * 1024 * 1024
_slot = asyncio.Semaphore(1)


def validate_body(body: bytes) -> bytes:
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Invalid model request") from None
    if not isinstance(value, dict) or value.get("model") not in MODELS:
        raise HTTPException(422, "Model is outside the existing staging role configuration")
    if set(value) - {
        "model",
        "messages",
        "prompt",
        "system",
        "stream",
        "format",
        "options",
        "keep_alive",
        "input",
        "truncate",
    }:
        raise HTTPException(422, "Unsupported staging model option")
    options = value.get("options", {})
    if not isinstance(options, dict):
        raise HTTPException(422, "Invalid generation options")
    if set(options) - {
        "num_ctx",
        "num_predict",
        "temperature",
        "top_p",
        "top_k",
        "repeat_penalty",
        "seed",
        "stop",
        "num_thread",
    }:
        raise HTTPException(422, "Unsupported staging generation option")
    for key, maximum in (("num_ctx", 8192), ("num_predict", 1024)):
        option = options.get(key, maximum)
        if type(option) is not int or not 1 <= option <= maximum:
            raise HTTPException(422, "Generation exceeds the staging resource budget")
    if "num_thread" in options and (type(options["num_thread"]) is not int or not 1 <= options["num_thread"] <= 4):
        raise HTTPException(422, "Generation exceeds the staging CPU budget")
    value["options"] = {
        **options,
        "num_ctx": options.get("num_ctx", 8192),
        "num_predict": options.get("num_predict", 512),
    }
    # A staging caller cannot unload production weights or pin them indefinitely.
    value["keep_alive"] = "2m"
    try:
        return json.dumps(value, allow_nan=False).encode()
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid model request") from None


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    route = "/" + path
    if request.query_params or not (
        (request.method == "GET" and route in READS) or (request.method == "POST" and route in WRITES)
    ):
        raise HTTPException(404, "Model administration is unavailable in staging")
    body = b""
    async for part in request.stream():
        body += part
        if len(body) > BODY_LIMIT:
            raise HTTPException(413, "Model request is too large")
    if request.method == "POST":
        body = validate_body(body)
        try:
            await asyncio.wait_for(_slot.acquire(), timeout=0.1)
        except TimeoutError:
            raise HTTPException(429, "Staging inference is already active") from None
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(150, connect=3))
    try:
        upstream = await client.send(
            client.build_request(
                request.method, TARGET + route, content=body, headers={"Content-Type": "application/json"}
            ),
            stream=True,
        )
    except httpx.HTTPError:
        await client.aclose()
        if request.method == "POST":
            _slot.release()
        raise HTTPException(503, "Shared local inference is unavailable") from None
    if not 200 <= upstream.status_code < 300:
        await upstream.aclose()
        await client.aclose()
        if request.method == "POST":
            _slot.release()
        return Response(
            status_code=503, content=b'{"error":"Shared model request failed"}', media_type="application/json"
        )

    async def chunks():
        count = 0
        started = time.monotonic()
        try:
            async for part in upstream.aiter_bytes():
                count += len(part)
                if count > RESPONSE_LIMIT or time.monotonic() - started > 150:
                    break
                yield part
        finally:
            await upstream.aclose()
            await client.aclose()
            if request.method == "POST":
                _slot.release()

    return StreamingResponse(
        chunks(),
        media_type=upstream.headers.get("content-type", "application/json"),
        headers={"Cache-Control": "no-store", "X-ORQEVIA-Inference-Scope": "SHARED_LOCAL_STAGE"},
    )
