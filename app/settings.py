"""Single source of truth for PRIME runtime configuration."""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


def _env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value or default


@dataclass(frozen=True)
class PrimeSettings:
    ollama_base_url: str
    fast_model: str
    deep_model: str
    embedding_model: str
    multi_specialist_workers: int

    @classmethod
    def from_env(cls) -> "PrimeSettings":
        fast = _env("PRIME_FAST_MODEL", "gemma3:1b")
        return cls(
            ollama_base_url=_env("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/"),
            fast_model=fast,
            deep_model=_env("PRIME_DEEP_MODEL", fast),
            embedding_model=_env("PRIME_EMBED_MODEL", "embeddinggemma:300m-qat-q4_0"),
            multi_specialist_workers=max(1, min(6, int(_env("PRIME_MULTI_SPECIALIST_WORKERS", "2")))),
        )

    @property
    def required_models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.fast_model, self.deep_model, self.embedding_model)))

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
