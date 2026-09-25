"""Static Vision LAB evidence boundaries; visual content never grants authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VisionEvidence:
    source_kind: str
    source_sha256: str
    observed: tuple[str, ...]
    interpreted: tuple[str, ...]
    inferred: tuple[str, ...]
    unknown: tuple[str, ...]
    contradictions: tuple[str, ...]
    content_is_authority: bool = False
    may_trigger_tool: bool = False


def evaluate_static_visual(*, source_kind: str, source_bytes: bytes, ocr_text: str | None, interpretations: list[str] | None = None, inferences: list[str] | None = None, authoritative: dict[str, Any] | None = None, visual_claims: dict[str, Any] | None = None) -> VisionEvidence:
    if source_kind not in {"screenshot", "photo", "document"}:
        raise ValueError("unsupported static visual source")
    if not source_bytes:
        raise ValueError("empty visual source")
    observed = [f"source_kind={source_kind}", f"bytes={len(source_bytes)}"]
    unknown: list[str] = []
    if ocr_text is None:
        unknown.append("ocr_text_unavailable")
    else:
        observed.append(f"ocr_text={ocr_text}")
    contradictions: list[str] = []
    for key, visual_value in (visual_claims or {}).items():
        if authoritative is None or key not in authoritative:
            unknown.append(f"authoritative:{key}")
        elif authoritative[key] != visual_value:
            contradictions.append(f"{key}:visual={visual_value!r}:authoritative={authoritative[key]!r}")
    return VisionEvidence(
        source_kind,
        hashlib.sha256(source_bytes).hexdigest(),
        tuple(observed), tuple(interpretations or ()), tuple(inferences or ()),
        tuple(unknown), tuple(contradictions), False, False,
    )
