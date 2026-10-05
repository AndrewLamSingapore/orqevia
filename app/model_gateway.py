"""Capability-based, inference-only model gateway for PRIME."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from .compute_ledger import ComputeLedger
from .settings import SETTINGS, PrimeSettings
from .compute_profile import require_compute_capacity, generation_options
from .compute_profile import runtime_compute_profile
from . import backend_admission


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


def _tokens_per_second(tokens: Any, duration_ns: Any) -> float | None:
    try:
        count, duration = int(tokens), int(duration_ns)
        return round(count / (duration / 1_000_000_000), 3) if count >= 0 and duration > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _bounded_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


class ModelGateway:
    def __init__(self, ledger: ComputeLedger | None = None, settings: PrimeSettings | None = None):
        self.ledger = ledger or ComputeLedger()
        self.settings = settings or SETTINGS
        self.ollama_url = self.settings.ollama_base_url
        self.local_fast = self.settings.fast_model
        self.local_deep = self.settings.deep_model
        self.local_evaluator = self.settings.evaluator_model
        self.frontier_url = os.getenv("PRIME_FRONTIER_URL", "").rstrip("/")
        self.frontier_key = os.getenv("PRIME_FRONTIER_API_KEY", "")
        self.frontier_model = os.getenv("PRIME_FRONTIER_MODEL", "")
        self.frontier_max_input_chars = _bounded_int(os.getenv("PRIME_FRONTIER_MAX_INPUT_CHARS", "60000"), 60000, 1000, 200000)

    @property
    def frontier_available(self) -> bool:
        return bool(self.frontier_url and self.frontier_key and self.frontier_model)

    def manifest(self) -> dict[str, Any]:
        readiness = self.settings.ollama_readiness()
        return {
            "local": {
                "available": readiness["ready"], "provider": "ollama",
                "fast_model": self.local_fast, "deep_model": self.local_deep,
                "evaluator_model": self.local_evaluator, "embedding_model": self.settings.embedding_model,
                "compute_profile": self.settings.compute_profile,
                "context_tokens": self.settings.context_tokens,
                "max_output_tokens": self.settings.max_output_tokens,
                "multi_specialist_workers": self.settings.multi_specialist_workers,
                "readiness": readiness,
            },
            "frontier": {
                "available": self.frontier_available,
                "provider": "openai-compatible" if self.frontier_available else None,
                "model": self.frontier_model or None,
                "max_input_chars": self.frontier_max_input_chars,
            },
            "authority": "inference-only",
        }

    @staticmethod
    def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def local(self, *, prompt: str, deep: bool = False, role: str | None = None,
              task_id: str | None = None, stage: str = "local_ai", timeout: float = 120.0) -> ModelResult:
        task_id = task_id or str(uuid.uuid4())
        model = self.local_evaluator if role == "evaluator" else (self.local_deep if deep else self.local_fast)
        require_compute_capacity(model)
        profile = runtime_compute_profile()
        demand = profile.get('models', {}).get(model, {}).get('peak_mib') if profile else None
        lease_id = str(uuid.uuid4())
        endpoint = self.ollama_url.rstrip('/')
        c = backend_admission.transaction()
        try:
            backend_admission.reserve(c, endpoint, lease_id, demand)
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
        started = time.monotonic()
        try:
            c = backend_admission.transaction()
            try:
                backend_admission.dispatch(c, endpoint, lease_id)
                c.commit()
            finally:
                c.close()
            data = self._post(
                f"{self.ollama_url}/api/generate",
                {
                    "model": model, "prompt": prompt, "stream": False,
                    "keep_alive": self.settings.keep_alive,
                    "options": {"num_ctx": self.settings.context_tokens, "num_predict": self.settings.max_output_tokens,**generation_options()},
                }, {}, timeout,
            )
            latency = int((time.monotonic() - started) * 1000)
            text = str(data.get("response") or "").strip()
            if not text or data.get('done') is not True:
                raise RuntimeError("local model returned an empty response")
            c = backend_admission.transaction()
            try:
                backend_admission.completed(c, endpoint, lease_id)
                c.commit()
            finally:
                c.close()
            usage = {
                key: data.get(key) for key in (
                    "prompt_eval_count", "eval_count", "total_duration", "load_duration",
                    "prompt_eval_duration", "eval_duration",
                )
            }
            usage["prompt_tokens_per_second"] = _tokens_per_second(usage["prompt_eval_count"], usage["prompt_eval_duration"])
            usage["output_tokens_per_second"] = _tokens_per_second(usage["eval_count"], usage["eval_duration"])
            self.ledger.record(
                task_id=task_id, stage=stage, provider="ollama", model=model, latency_ms=latency,
                success=True, input_units=usage["prompt_eval_count"], output_units=usage["eval_count"], metadata=usage,
            )
            return ModelResult(task_id, stage, "ollama", model, text, latency, usage)
        except Exception as exc:
            c = backend_admission.transaction()
            try:
                backend_admission.cancel(c, endpoint, lease_id)
                c.commit()
            finally:
                c.close()
            latency = int((time.monotonic() - started) * 1000)
            self.ledger.record(task_id=task_id, stage=stage, provider="ollama", model=model, latency_ms=latency, success=False, metadata={"error": type(exc).__name__})
            raise

    def frontier(self, *, prompt: str, task_id: str | None = None, timeout: float = 120.0) -> ModelResult:
        if not self.frontier_available:
            raise RuntimeError("frontier inference is not configured")
        if len(prompt) > self.frontier_max_input_chars:
            raise ValueError("frontier prompt exceeds configured input boundary")
        task_id = task_id or str(uuid.uuid4())
        started = time.monotonic()
        try:
            data = self._post(
                f"{self.frontier_url}/chat/completions",
                {"model": self.frontier_model, "messages": [{"role": "user", "content": prompt}], "max_tokens": self.settings.max_output_tokens},
                {"Authorization": f"Bearer {self.frontier_key}"}, timeout,
            )
            latency = int((time.monotonic() - started) * 1000)
            text = str(data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if not text:
                raise RuntimeError("frontier model returned an empty response")
            usage = data.get("usage") or {}
            self.ledger.record(task_id=task_id, stage="frontier_ai", provider="frontier", model=self.frontier_model, latency_ms=latency, success=True, input_units=usage.get("prompt_tokens"), output_units=usage.get("completion_tokens"), metadata=usage)
            return ModelResult(task_id, "frontier_ai", "frontier", self.frontier_model, text, latency, usage)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            self.ledger.record(task_id=task_id, stage="frontier_ai", provider="frontier", model=self.frontier_model, latency_ms=latency, success=False, metadata={"error": type(exc).__name__})
            raise
