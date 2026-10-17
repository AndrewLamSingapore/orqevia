"""ORQEVIA runtime configuration loader."""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


def _env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value or default


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _keep_alive_env(name: str, default: str) -> str | int:
    value = _env(name, default)
    try:
        numeric = int(value)
    except ValueError:
        return value
    return numeric


@dataclass(frozen=True)
class PrimeSettings:
    ollama_base_url: str
    fast_model: str
    deep_model: str
    embedding_model: str
    multi_specialist_workers: int
    evaluator_model: str = ""
    compute_profile: str = "compat"
    context_tokens: int = 8192
    max_output_tokens: int = 2048
    keep_alive: str | int = "10m"

    def __post_init__(self) -> None:
        if not self.evaluator_model:
            object.__setattr__(self, "evaluator_model", self.deep_model)

    @classmethod
    def from_env(cls) -> "PrimeSettings":
        fast = _env("PRIME_FAST_MODEL", "gemma3:1b")
        deep = _env("PRIME_DEEP_MODEL", fast)
        profile = _env("PRIME_COMPUTE_PROFILE", "balanced").lower()
        if profile not in {"compat", "balanced", "max"}:
            profile = "balanced"
        worker_default = {"compat": 2, "balanced": 3, "max": 4}[profile]
        context_default = {"compat": 8192, "balanced": 16384, "max": 32768}[profile]
        output_default = {"compat": 2048, "balanced": 4096, "max": 8192}[profile]
        return cls(
            ollama_base_url=_env("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/"),
            fast_model=fast,
            deep_model=deep,
            evaluator_model=_env("PRIME_EVALUATOR_MODEL", deep),
            embedding_model=_env("PRIME_EMBED_MODEL", "embeddinggemma:300m-qat-q4_0"),
            compute_profile=profile,
            multi_specialist_workers=_int_env("PRIME_MULTI_SPECIALIST_WORKERS", worker_default, 1, 6),
            context_tokens=_int_env("PRIME_CONTEXT_TOKENS", context_default, 2048, 131072),
            max_output_tokens=_int_env("PRIME_MAX_OUTPUT_TOKENS", output_default, 256, 32768),
            keep_alive=_keep_alive_env("PRIME_MODEL_KEEP_ALIVE", "10m"),
        )

    @property
    def required_models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.fast_model, self.deep_model, self.evaluator_model, self.embedding_model)))

    def as_public_dict(self) -> dict[str, Any]:
        return {**asdict(self), "required_models": list(self.required_models)}

    def ollama_readiness(self, timeout: float = 5.0) -> dict[str, Any]:
        try:
            request = urllib.request.Request(f"{self.ollama_base_url}/api/tags", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            installed = sorted({str(model.get("name") or model.get("model") or "") for model in payload.get("models", []) if isinstance(model, dict)})
            missing = [model for model in self.required_models if model not in installed]
            return {"ready": not missing, "installed_models": installed, "required_models": list(self.required_models), "missing_models": missing, "error": None}
        except Exception as exc:
            return {"ready": False, "installed_models": [], "required_models": list(self.required_models), "missing_models": list(self.required_models), "error": type(exc).__name__}


SETTINGS = PrimeSettings.from_env()
