"""Authenticated debate and judge-resolution API."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .client_auth import authenticate_owner
from .debate import DebateStore, Position, resolve_debate


router = APIRouter(prefix="/api/debates", tags=["debate"])


class PositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=80)
    proposition: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0.5, ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    objections: list[str] = Field(default_factory=list, max_length=100)


class DebateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=4000)
    positions: list[PositionInput] = Field(min_length=2, max_length=21)
    judge_agent: str = Field(default="a26", min_length=1, max_length=80)
    consensus_threshold: float = Field(default=0.66, ge=0.5, le=1)


def _owner(authorization: str | None) -> None:
    authenticate_owner(authorization)


@router.post("", status_code=201)
def create(body: DebateInput, authorization: str | None = Header(default=None)):
    _owner(authorization)
    try:
        positions = [
            Position(
                agent_id=item.agent_id,
                proposition=item.proposition,
                evidence_refs=tuple(item.evidence_refs),
                confidence=item.confidence,
                assumptions=tuple(item.assumptions),
                objections=tuple(item.objections),
            )
            for item in body.positions
        ]
        resolution = resolve_debate(
            body.question,
            positions,
            judge_agent=body.judge_agent,
            consensus_threshold=body.consensus_threshold,
        )
        return DebateStore().record(resolution)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("")
def list_debates(limit: int = 100, authorization: str | None = Header(default=None)):
    _owner(authorization)
    return {"debates": DebateStore().list(limit)}


@router.get("/{debate_id}")
def get_debate(debate_id: str, authorization: str | None = Header(default=None)):
    _owner(authorization)
    try:
        return DebateStore().get(debate_id)
    except KeyError:
        raise HTTPException(404, "debate not found") from None
