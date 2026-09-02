"""Authenticated pull consumer for the Portal portfolio event outbox."""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from typing import Any, Callable

LOGGER = logging.getLogger("prime.portfolio_relay")


class PortfolioRelayPoller:
    def __init__(self, event_fabric: Any, *, url: str | None = None, token: str | None = None,
                 interval_seconds: int | None = None, opener: Callable[..., Any] = urllib.request.urlopen):
        self.event_fabric = event_fabric
        self.url = (url if url is not None else os.getenv("PORTFOLIO_RELAY_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("PORTFOLIO_RELAY_TOKEN", "").strip()
        raw_interval = interval_seconds if interval_seconds is not None else int(os.getenv("PORTFOLIO_RELAY_INTERVAL_SECONDS", "15"))
        self.interval_seconds = max(5, min(int(raw_interval), 300))
        self.opener = opener
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def _request(self, method: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.url
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"})
        with self.opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def pull_once(self, limit: int = 20) -> dict[str, int]:
        if not self.enabled:
            return {"claimed": 0, "ingested": 0, "acknowledged": 0}
        payload = self._request("GET", query={"limit": max(1, min(limit, 100)), "visibility_seconds": max(60, self.interval_seconds * 4)})
        events = payload.get("events") if isinstance(payload, dict) else []
        events = events if isinstance(events, list) else []
        acknowledged = []
        for event in events:
            try:
                result = self.event_fabric.ingest(event)
                if result.get("accepted"):
                    acknowledged.append(str(event["event_id"]))
            except Exception as exc:
                event_id = event.get("event_id", "") if isinstance(event, dict) else ""
                LOGGER.warning("portfolio_relay_ingest_failed event_id=%s error=%s", str(event_id)[:100], type(exc).__name__)
        if acknowledged:
            self._request("POST", body={"action": "ack", "event_ids": acknowledged})
        return {"claimed": len(events), "ingested": len(acknowledged), "acknowledged": len(acknowledged)}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.pull_once()
                if result["claimed"]:
                    LOGGER.info("portfolio_relay_cycle claimed=%s acknowledged=%s", result["claimed"], result["acknowledged"])
            except Exception as exc:
                LOGGER.warning("portfolio_relay_cycle_failed error=%s", type(exc).__name__)
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="prime-portfolio-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
