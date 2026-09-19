"""Effect-based ABEX host protection enforced immediately before execution.

Names and caller-provided risk labels are never trusted to lower observed risk.
The guard classifies the complete signed envelope, including nested command text.
Destructive and otherwise privileged host effects require a fresh owner approval
bound to the exact action, executable, arguments and target digest.
"""
from __future__ import annotations

import hashlib
import json
import re
from enum import IntEnum
from typing import Any, Mapping


class EffectClass(IntEnum):
    READ_ONLY = 0
    APPLICATION_MUTATION = 1
    HOST_REVERSIBLE = 2
    HOST_HIGH_RISK = 3
    STORAGE_DESTRUCTIVE = 4
    BOOT_DESTRUCTIVE = 5
    FIRMWARE_DESTRUCTIVE = 6


_READ_ACTIONS = {"web.search", "agent.infer", "status.read", "filesystem.read"}
_APPLICATION_ACTIONS = {"artifact.create", "sandbox.wasm.execute"}
_HOST_ACTIONS = {"executor.run", "host.execute", "repair.run", "tool.execute"}

_STORAGE = (
    r"\bformat(?:\.com)?\b", r"\bclear-disk\b", r"\binitialize-disk\b",
    r"\bdiskpart\b[\s\S]*\bclean\b", r"\b(delete|create|resize)\s+partition\b",
    r"\b(convert|set)\s+(gpt|mbr)\b", r"\bmkfs(?:\.[a-z0-9]+)?\b",
    r"\bchkdsk\b[\s\S]*\/(f|r|x|b)\b",
)
_BOOT = (
    r"\bbcdboot\b", r"\bbcdedit\b", r"\bbootrec\b", r"\befi\b[\s\S]*\b(delete|remove|format|write|mount)\b",
)
_FIRMWARE = (
    r"\b(clear-tpm|initialize-tpm)\b", r"\bsecure\s*boot\b[\s\S]*\b(key|clear|delete|reset|update)\b",
    r"\b(bios|uefi|firmware|cmos)\b[\s\S]*\b(flash|update|reset|clear|write|set)\b",
)
_PROTECTED_DELETE = (
    r"\b(remove-item|del|erase|rmdir|rd|rm)\b[\s\S]*(recovery|backup|evidence|checkpoint|windows\.old)",
    r"\bgit\b[\s\S]*\b(push\s+--force|reset\s+--hard|clean\s+-[a-z]*f)",
)


def _flatten(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_flatten(item)}" for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")


def approval_subject(envelope: Mapping[str, Any]) -> dict[str, Any]:
    parameters = envelope.get("parameters")
    parameters = parameters if isinstance(parameters, Mapping) else {}
    return {
        "action": envelope.get("action"),
        "executable": parameters.get("executable") or parameters.get("command") or parameters.get("program"),
        "arguments": parameters.get("arguments") or parameters.get("args"),
        "target": parameters.get("target") or envelope.get("target"),
    }


def effect_digest(envelope: Mapping[str, Any]) -> str:
    raw = json.dumps(approval_subject(envelope), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classify_effect(envelope: Mapping[str, Any]) -> EffectClass:
    text = _flatten({"action": envelope.get("action"), "parameters": envelope.get("parameters", {})}).lower()
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _FIRMWARE):
        return EffectClass.FIRMWARE_DESTRUCTIVE
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _BOOT):
        return EffectClass.BOOT_DESTRUCTIVE
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _STORAGE + _PROTECTED_DELETE):
        return EffectClass.STORAGE_DESTRUCTIVE
    action = str(envelope.get("action", ""))
    if action in _READ_ACTIONS:
        return EffectClass.READ_ONLY
    if action in _APPLICATION_ACTIONS:
        return EffectClass.APPLICATION_MUTATION
    context = envelope.get("context")
    context = context if isinstance(context, Mapping) else {}
    if action in _HOST_ACTIONS or bool(context.get("external_execution")):
        return EffectClass.HOST_HIGH_RISK
    return EffectClass.HOST_HIGH_RISK


def enforce_at_execution(envelope: Mapping[str, Any]) -> EffectClass:
    observed = classify_effect(envelope)
    context = envelope.get("context")
    context = context if isinstance(context, Mapping) else {}
    authorization = envelope.get("authorization")
    authorization = authorization if isinstance(authorization, Mapping) else {}

    declared_name = str(context.get("effect_class", "")).upper()
    if declared_name:
        try:
            declared = EffectClass[declared_name]
        except KeyError as exc:
            raise PermissionError("unknown declared effect class") from exc
        if declared < observed:
            raise PermissionError("caller attempted to lower the observed effect class")
        observed = max(observed, declared)

    if observed >= EffectClass.HOST_HIGH_RISK:
        approval_id = authorization.get("owner_approval_id")
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise PermissionError(f"{observed.name} requires explicit owner approval")
        expected = effect_digest(envelope)
        if context.get("approved_effect_digest") != expected:
            raise PermissionError("owner approval is not bound to the exact execution effect")
    return observed
