"""Outbound publisher for sanitized JARVIS authority telemetry.

The publisher is disabled unless ORQEVIA_PUBLIC_TRACE_SECRET is configured. It
sends only public-safe authority and aggregate release-gate metadata to the
trusted relay and authenticates each request with HMAC-SHA256. Prompts, model
outputs, rationale, claim text, credentials and private endpoints never cross
this boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Callable

from .release_gate import release_gates

LOGGER = logging.getLogger("prime.public_trace_publisher")
DEFAULT_RELAY_URL = "https://bksyjvppcwfgwoelnyvp.supabase.co/functions/v1/orqevia-trace-relay"
DEFAULT_PUBLISHER_ID = ""


class PublicTracePublisher:
    def __init__(
        self,
        authority_runtime: Any,
        *,
        url: str | None = None,
        secret: str | None = None,
        publisher_id: str | None = None,
        interval_seconds: int | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.authority_runtime = authority_runtime
        self.url = (url if url is not None else os.getenv("ORQEVIA_PUBLIC_TRACE_RELAY_URL", DEFAULT_RELAY_URL)).strip()
        self.secret = secret if secret is not None else os.getenv("ORQEVIA_PUBLIC_TRACE_SECRET", "").strip()
        self.publisher_id = (
            publisher_id if publisher_id is not None else os.getenv("ORQEVIA_PUBLIC_TRACE_PUBLISHER_ID", DEFAULT_PUBLISHER_ID)
        ).strip()
        raw_interval = interval_seconds if interval_seconds is not None else int(os.getenv("ORQEVIA_PUBLIC_TRACE_INTERVAL_SECONDS", "15"))
        self.interval_seconds = max(5, min(int(raw_interval), 300))
        self.opener = opener
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.secret and self.publisher_id)

    def _encoded_snapshot(self) -> bytes:
        snapshot = release_gates.enrich_snapshot(self.authority_runtime.public_snapshot(100))
        return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def publish_once(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": True, "state": "disabled", "accepted_events": 0}
        body = self._encoded_snapshot()
        timestamp = str(int(self.clock()))
        message = timestamp.encode("ascii") + b"." + body
        signature = hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-ORQEVIA-Publisher": self.publisher_id,
                "X-ORQEVIA-Timestamp": timestamp,
                "X-ORQEVIA-Signature": signature,
                "User-Agent": "orqevia-public-trace/1.1",
            },
        )
        with self.opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("public trace relay rejected sanitized snapshot")
        return payload

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.publish_once()
                if result.get("accepted_events"):
                    LOGGER.info("public_trace_published events=%s", result.get("accepted_events"))
            except Exception as exc:
                LOGGER.warning("public_trace_publish_failed error=%s", type(exc).__name__)
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="prime-public-trace", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
