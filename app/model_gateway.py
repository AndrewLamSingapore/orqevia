"""Capability-based model gateway for PRIME.

The gateway keeps provider details behind one boundary, executes only inference,
and never grants action authority. Local Ollama is preferred; optional frontier
inference is explicit and separately configured.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, asdict
from typing import Any

from .compute_ledger import ComputeLedger
from .settings import SETTINGS, PrimeSettings


@dataclass(frozen=True)
class ModelResult:
    task_id: str
    stage: str
    provider: str
    model: str
    text: str
    latency_ms: int
    usage: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelGateway:
    def __init__(self, ledger: ComputeLedger | None = None, settings: PrimeSettings | None = None):
        self.ledger = ledger or ComputeLedger()
        self.settings = settings or SETTINGS
        self.ollama_url = self.settings.ollama_base_url
        self.local_fast = self.settings.fast_model
        self.local_deep = self.settings.deep_model
        import os
        self.frontier_url = os.getenv("PRIME_FRONTIER_URL", "").rstrip("/")
        self.frontier_key = os.getenv("PRIME_FRONTIER_API_KEY", "")
        self.frontier_model = os.getenv("PRIME_FRONTIER_MODEL", "")

    @property
    def frontier_available(self) -> bool:
        return bool(self.frontier_url and self.frontier_key and self.frontier_model)

    def manifest(self) -> dict[str, Any]:
        readiness = self.settings.ollama_readiness()
        return {
            "local": {"available": readiness["ready"], "provider": "ollama", "fast_model": self.local_fast, "deep_model": self.local_deep,
                      "embedding_model": self.settings.embedding_model, "readiness": readiness},
            "frontier": {"available": self.frontier_available, "provider": "openai-compatible" if self.frontier_available else None,
                         "model": self.frontier_model or None},
            "authority": "inference-only",
        }

    @staticmethod
    def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json", **headers}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def local(self, *, prompt: str, deep: bool = False, task_id: str | None = None,
              stage: str = "local_ai", timeout: float = 120.0) -> ModelResult:
        task_id = task_id or str(uuid.uuid4())
        model = self.local_deep if deep else self.local_fast
        started = time.monotonic()
        try:
            data = self._post(f"{self.ollama_url}/api/generate", {"model": model, "prompt": prompt, "stream": False}, {}, timeout)
            latency = int((time.monotonic() - started) * 1000)
            text = str(data.get("response") or "").strip()
            if not text:
                raise RuntimeError("local model returned an empty response")
            usage = {"prompt_eval_count": data.get("prompt_eval_count"), "eval_count": data.get("eval_count")}
            self.ledger.record(task_id=task_id, stage=stage, provider="ollama", model=model, latency_ms=latency,
                               success=True, input_units=usage["prompt_eval_count"], output_units=usage["eval_count"])
            return ModelResult(task_id, stage, "ollama", model, text, latency, usage)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            self.ledger.record(task_id=task_id, stage=stage, provider="ollama", model=model, latency_ms=latency,
                               success=False, metadata={"error": type(exc).__name__})
            raise

    def frontier(self, *, prompt: str, task_id: str | None = None, timeout: float = 120.0) -> ModelResult:
        if not self.frontier_available:
            raise RuntimeError("frontier inference is not configured")
        task_id = task_id or str(uuid.uuid4())
        started = time.monotonic()
        try:
            data = self._post(f"{self.frontier_url}/chat/completions",
                              {"model": self.frontier_model, "messages": [{"role": "user", "content": prompt}]},
                              {"Authorization": f"Bearer {self.frontier_key}"}, timeout)
            latency = int((time.monotonic() - started) * 1000)
            text = str(data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if not text:
                raise RuntimeError("frontier model returned an empty response")
            usage = data.get("usage") or {}
            self.ledger.record(task_id=task_id, stage="frontier_ai", provider="frontier", model=self.frontier_model,
                               latency_ms=latency, success=True, input_units=usage.get("prompt_tokens"),
                               output_units=usage.get("completion_tokens"))
            return ModelResult(task_id, "frontier_ai", "frontier", self.frontier_model, text, latency, usage)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            self.ledger.record(task_id=task_id, stage="frontier_ai", provider="frontier", model=self.frontier_model,
                               latency_ms=latency, success=False, metadata={"error": type(exc).__name__})
            raise
