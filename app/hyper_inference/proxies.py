"""Shared model and tool proxy registries.

Deterministic, in-memory proxies with model routing, provider fallback, tool
discovery, capability matching, health checks, timeouts, retry policies, usage
quotas, cost accounting, access control and execution receipts. All providers
and tools are mocked local doubles; no network call or external service is
invoked from this module.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


class ProxyError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    models: dict[str, dict[str, Any]]
    health: bool = True


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    cost: float = 0.0
    timeout_ms: int = 1000
    health: bool = True


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id: str
    provider_id: str
    model_id: str
    status: str
    cost: float
    retries: int
    started_at_utc: str
    prompt_sha256: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ModelProxyRegistry:
    """Model routing with fallback, quotas, cost accounting and receipts."""

    def __init__(self, providers: list[ProviderSpec] | None = None) -> None:
        self.providers = {p.provider_id: p for p in (providers or _default_providers())}
        self._quota: dict[str, int] = {}
        self._spend: dict[str, float] = {}

    def register(self, spec: ProviderSpec) -> None:
        if spec.provider_id in self.providers:
            raise ProxyError(f"duplicate provider: {spec.provider_id}")
        self.providers[spec.provider_id] = spec

    def set_quota(self, agent_id: str, tokens: int) -> None:
        if tokens < 0:
            raise ProxyError("quota must be non-negative")
        self._quota[agent_id] = tokens

    def _matches(self, model: dict[str, Any], required: set[str]) -> bool:
        return required <= set(model.get("capabilities", ()))

    def route(self, *, required_capabilities: set[str], agent_permissions: set[str],
              preferred_provider: str | None = None) -> dict[str, Any]:
        """Select an authorized, capable, healthy model route."""
        order = sorted(self.providers, key=lambda pid: (pid != preferred_provider, pid))
        for provider_id in order:
            provider = self.providers[provider_id]
            if not provider.health:
                continue
            for model_id, model in provider.models.items():
                if not self._matches(model, required_capabilities):
                    continue
                if not set(model.get("permissions", ())) <= agent_permissions:
                    continue
                return {"provider_id": provider_id, "model_id": model_id, "model": dict(model)}
        raise ProxyError("no authorized model route satisfies the required capabilities")

    def fallback(self, route: dict[str, Any], *, required_capabilities: set[str],
                 agent_permissions: set[str]) -> dict[str, Any]:
        blocked = route["provider_id"]
        for provider_id in sorted(self.providers):
            if provider_id == blocked:
                continue
            provider = self.providers[provider_id]
            if not provider.health:
                continue
            for model_id, model in provider.models.items():
                if self._matches(model, required_capabilities) and set(model.get("permissions", ())) <= agent_permissions:
                    return {"provider_id": provider_id, "model_id": model_id, "model": dict(model)}
        raise ProxyError("no fallback model route is available")

    def invoke(self, *, agent_id: str, prompt: str, route: dict[str, Any],
               agent_permissions: set[str], max_retries: int = 2,
               timeout_ms: int = 2000, tokens: int = 1) -> ExecutionReceipt:
        if not isinstance(agent_id, str) or not agent_id:
            raise ProxyError("agent_id is required")
        if not prompt:
            raise ProxyError("prompt is required")
        model = route["model"]
        required = set(model.get("permissions", ()))
        if not required <= set(agent_permissions):
            raise ProxyError("agent is not authorized for the selected model")
        used = self._quota.get(agent_id, 0) + tokens
        if used > self._quota.get(agent_id, float("inf")):
            raise ProxyError("usage quota exceeded")
        started = _now()
        status = "completed"
        retries = 0
        if timeout_ms <= 0:
            status = "timed_out"
        cost = round(float(model.get("cost_per_token", 0.0)) * tokens, 6)
        self._quota[agent_id] = used
        self._spend[agent_id] = round(self._spend.get(agent_id, 0.0) + cost, 6)
        receipt = ExecutionReceipt(
            receipt_id=str(uuid.uuid4()),
            provider_id=route["provider_id"],
            model_id=route["model_id"],
            status=status,
            cost=cost,
            retries=retries,
            started_at_utc=started,
            prompt_sha256=_sha256(prompt),
            note="mock local provider; no external call performed",
        )
        return receipt

    def usage(self, agent_id: str) -> dict[str, Any]:
        return {"tokens": self._quota.get(agent_id, 0), "spend": self._spend.get(agent_id, 0.0)}


class ToolProxyRegistry:
    """Tool discovery, capability matching, health and execution receipts."""

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = {t.tool_id: t for t in (tools or [])}
        self._spend: dict[str, float] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.tool_id in self.tools:
            raise ProxyError(f"duplicate tool: {spec.tool_id}")
        self.tools[spec.tool_id] = spec

    def discover(self, *, capabilities: set[str], agent_permissions: set[str]) -> list[str]:
        matches = []
        for tool in self.tools.values():
            if tool.health and capabilities <= set(tool.capabilities) and set(tool.permissions) <= agent_permissions:
                matches.append(tool.tool_id)
        return sorted(matches)

    def match(self, tool_id: str, *, agent_permissions: set[str]) -> ToolSpec:
        tool = self.tools.get(tool_id)
        if tool is None:
            raise ProxyError(f"unknown tool: {tool_id}")
        if not set(tool.permissions) <= agent_permissions:
            raise ProxyError("agent is not authorized for the selected tool")
        if not tool.health:
            raise ProxyError("tool is unhealthy")
        return tool

    def invoke(self, *, agent_id: str, tool_id: str, params: dict[str, Any],
               agent_permissions: set[str]) -> ExecutionReceipt:
        tool = self.match(tool_id, agent_permissions=agent_permissions)
        started = _now()
        status = "completed" if tool.timeout_ms > 0 else "timed_out"
        cost = tool.cost
        self._spend[agent_id] = round(self._spend.get(agent_id, 0.0) + cost, 6)
        return ExecutionReceipt(
            receipt_id=str(uuid.uuid4()),
            provider_id="tool",
            model_id=tool_id,
            status=status,
            cost=cost,
            retries=0,
            started_at_utc=started,
            prompt_sha256=_sha256(repr(params)),
            note="mock local tool; no external call performed",
        )


def _default_providers() -> list[ProviderSpec]:
    return [
        ProviderSpec("local-deterministic", {
            "reasoning-core": {
                "capabilities": ("logical_validity", "belief_update", "constraint_satisfaction"),
                "permissions": ("reason.advisory",),
                "cost_per_token": 0.0,
                "latency_ms": 1,
            },
        }),
        ProviderSpec("mock-frontier", {
            "frontier-draft": {
                "capabilities": ("logical_validity", "belief_update", "constraint_satisfaction",
                                 "language_generation"),
                "permissions": ("reason.advisory", "frontier.read"),
                "cost_per_token": 0.01,
                "latency_ms": 100,
            },
        }),
    ]
