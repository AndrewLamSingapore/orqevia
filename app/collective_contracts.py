"""Versioned transport contracts for the governed collective board.

These contracts describe data, never caller authority. Principals are constructed
by the authenticated service, outside the request body.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

COLLECTIVE_API_VERSION = "1.0"

CollectiveOperation = Literal[
    "evidence.record",
    "claim.contribute",
    "claim.review",
    "claim.correct",
    "knowledge.link",
    "challenge.open",
    "challenge.transition",
    "challenge.resolve",
    "challenge.reopen",
    "gap.detect",
    "gap.transition",
    "gap.plan",
    "gap.execute",
    "gap.verify",
    "gap.reopen",
    "puzzle.create",
    "puzzle.contribute",
    "puzzle.complete",
    "puzzle.reopen",
    "registry.observe",
    "lesson.record",
]


class CollectiveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    api_version: Literal["1.0"] = "1.0"
    operation: CollectiveOperation
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    payload: dict[str, Any]


class CollectiveQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    api_version: Literal["1.0"] = "1.0"
    kind: str = Field(min_length=1, max_length=48)
    id: str | None = Field(default=None, max_length=160)
    state: str | None = Field(default=None, max_length=48)
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10000)
