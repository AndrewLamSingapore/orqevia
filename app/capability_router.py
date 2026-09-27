"""Evidence-backed model routing. Selection never grants execution authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "model_capabilities.v1.json"
PRIVATE_CLASSES = frozenset({"LOCAL_ONLY", "SENSITIVE", "RESTRICTED"})


@dataclass(frozen=True)
class CapabilityBackend:
    name: str
    model: str
    location: str
    median_latency_seconds: float
    verified_capabilities: frozenset[str]
    available: bool = True


@dataclass(frozen=True)
class CapabilityRoute:
    state: str
    capability: str
    reason: str
    backend: CapabilityBackend | None = None
    grants_execution_authority: bool = False


def load_capability_profiles(path: Path = PROFILE_PATH) -> tuple[CapabilityBackend, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0" or data.get("privacy") != "LOCAL_ONLY":
        raise ValueError("unsupported or unsafe capability profile")
    profiles = []
    seen = set()
    for raw in data.get("profiles", []):
        if raw.get("location") != "local":
            raise ValueError("v1 measured profiles must be local")
        name, model = str(raw.get("name", "")).strip(), str(raw.get("model", "")).strip()
        capabilities = frozenset(str(item).strip() for item in raw.get("verified_capabilities", []) if str(item).strip())
        failed = frozenset(str(item).strip() for item in raw.get("failed_capabilities", []) if str(item).strip())
        if not name or not model or not capabilities or capabilities & failed or (name, model) in seen:
            raise ValueError("invalid capability profile")
        latency = float(raw.get("median_latency_seconds", 0))
        if latency <= 0:
            raise ValueError("capability profile requires measured positive latency")
        seen.add((name, model))
        profiles.append(CapabilityBackend(name, model, "local", latency, capabilities))
    if not profiles:
        raise ValueError("at least one measured capability profile is required")
    return tuple(profiles)


def select_capability_route(
    backends: tuple[CapabilityBackend, ...],
    *,
    capability: str,
    classification: str,
    local_saturated: bool = False,
) -> CapabilityRoute:
    wanted = capability.strip().lower()
    if not wanted:
        return CapabilityRoute("DENIED", wanted, "Capability is required")
    if classification not in {"LOCAL_ONLY", "CLOUD_PERMITTED", "SENSITIVE", "RESTRICTED"}:
        return CapabilityRoute("DENIED", wanted, "Unknown data classification")
    eligible = sorted(
        (backend for backend in backends if backend.available and wanted in backend.verified_capabilities),
        key=lambda backend: (backend.median_latency_seconds, backend.name),
    )
    local = [backend for backend in eligible if backend.location == "local"]
    if local and not local_saturated:
        return CapabilityRoute("READY", wanted, "Fastest locally measured backend that passed this capability", local[0])
    if local:
        return CapabilityRoute("QUEUED", wanted, "Verified local capability exists but governed local capacity is occupied", local[0])
    if wanted == "structured_output":
        return CapabilityRoute("VERIFY_REQUIRED", wanted, "No model passed strict JSON; use deterministic schema enforcement and verify before acceptance")
    privacy = " for private data" if classification in PRIVATE_CLASSES else ""
    return CapabilityRoute("UNAVAILABLE", wanted, f"No available benchmark-verified backend satisfies this capability{privacy}")
