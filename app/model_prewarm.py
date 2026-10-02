"""Opt-in, nonblocking Ollama prewarm candidate.

This module is deliberately not imported by the production startup path.
Calling ``start_optional_prewarm`` after application startup is safe when
disabled (the default): no thread or network request is created.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .settings import PrimeSettings


MAX_WALL_SECONDS = 20.0
MAX_BODY_BYTES = 1_000_000
MAX_KEEP_ALIVE_SECONDS = 7200


@dataclass
class PrewarmHandle:
    """Local diagnostic state; never includes endpoint URLs or error bodies."""

    status: str = "disabled"
    error_type: str | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)


def _json_request(url: str, timeout: float, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="GET" if payload is None else "POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("response_too_large")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("invalid_response")
    return result


def _prewarm(settings: PrimeSettings, model: str, keep_alive: str, timeout: float) -> None:
    """Verify the selected configured model is installed, then load only it."""
    root = settings.ollama_base_url.rstrip("/")
    tags = _json_request(f"{root}/api/tags", timeout)
    models = tags.get("models")
    if not isinstance(models, list) or not any(
        isinstance(item, dict) and model in (item.get("name"), item.get("model"))
        for item in models
    ):
        raise LookupError("selected_model_not_installed")
    result = _json_request(
        f"{root}/api/generate", timeout,
        {"model": model, "stream": False, "keep_alive": keep_alive},
    )
    if result.get("done") is not True or result.get("response") not in (None, ""):
        raise ValueError("unexpected_prewarm_response")


def start_optional_prewarm(
    settings: PrimeSettings,
    environ: Mapping[str, str] | None = None,
    *,
    probe: Callable[[PrimeSettings, str, str, float], None] = _prewarm,
) -> PrewarmHandle:
    """Schedule at most one post-start prewarm, without delaying the caller.

    Only the exact environment value ``1`` enables it. The daemon supervisor
    caps its observation at 20 seconds. The HTTP worker is also daemonized so a
    misbehaving endpoint cannot hold shutdown; socket operations use a 10-second
    timeout. No exception is re-raised or logged with request/secret content.
    """
    values = os.environ if environ is None else environ
    handle = PrewarmHandle()
    if values.get("PRIME_PREWARM_ENABLED") != "1":
        handle.done.set()
        return handle

    selector = values.get("PRIME_PREWARM_MODEL", "deep")
    models = {"fast": settings.fast_model, "deep": settings.deep_model, "evaluator": settings.evaluator_model}
    model = models.get(selector)
    keep_alive = settings.keep_alive
    match = re.fullmatch(r"([1-9][0-9]*)([smh])", keep_alive)
    factor = {"s": 1, "m": 60, "h": 3600}
    if not model or not match or int(match.group(1)) * factor[match.group(2)] > MAX_KEEP_ALIVE_SECONDS:
        handle.status = "failed"
        handle.error_type = "InvalidConfiguration"
        handle.done.set()
        return handle

    handle.status = "scheduled"

    def supervise() -> None:
        outcome: dict[str, str | None] = {"error_type": None}
        finished = threading.Event()

        def run_probe() -> None:
            try:
                probe(settings, model, keep_alive, 10.0)
            except Exception as exc:  # Boot must survive all optional probe failures.
                outcome["error_type"] = type(exc).__name__
            finally:
                finished.set()

        try:
            worker = threading.Thread(target=run_probe, name="prime-prewarm-http", daemon=True)
            worker.start()
            if not finished.wait(MAX_WALL_SECONDS):
                handle.status = "timed_out"
            elif outcome["error_type"] is not None:
                handle.status = "failed"
                handle.error_type = outcome["error_type"]
            else:
                handle.status = "completed"
        except Exception as exc:  # Thread creation is optional too.
            handle.status = "failed"
            handle.error_type = type(exc).__name__
        finally:
            handle.done.set()

    try:
        threading.Thread(target=supervise, name="prime-prewarm-supervisor", daemon=True).start()
    except Exception as exc:
        handle.status = "failed"
        handle.error_type = type(exc).__name__
        handle.done.set()
    return handle
