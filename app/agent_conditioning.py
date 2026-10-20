"""Optional, bounded behavioral conditioning for registered ORQEVIA agents.

Conditioning changes expression and interaction style only. Registered role,
task instructions, evidence requirements, permissions and security policy retain
strict priority. MBTI or other psychological labels are optional research tags,
not evidence of capability or authority.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .agent_notebooks import AgentNotebookStore, get_notebook_store
from .agent_registry import canonical_agent_id


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BehaviorProfile:
    profile_id: str = "neutral"
    enabled: bool = False
    decision_style: str = "balanced"
    directness: float = 0.5
    exploration: float = 0.5
    collaboration: float = 0.5
    verbosity: float = 0.4
    challenge_style: str = "constructive"
    mbti_tag: str | None = None

    def __post_init__(self) -> None:
        if self.decision_style not in {"analytical", "balanced", "empathetic"}:
            raise ValueError("unsupported decision style")
        if self.challenge_style not in {"constructive", "skeptical", "none"}:
            raise ValueError("unsupported challenge style")
        for name in ("directness", "exploration", "collaboration", "verbosity"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.mbti_tag and (
            len(self.mbti_tag) != 4 or any(letter not in "EISNTFJP" for letter in self.mbti_tag.upper())
        ):
            raise ValueError("mbti_tag must be four valid letters or null")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BehaviorProfileStore:
    def __init__(self, notebook_store: AgentNotebookStore | None = None) -> None:
        self.notebooks = notebook_store or get_notebook_store()
        self.path = self.notebooks.path
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS notebook_conditioning_profiles(
                agent_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
                )"""
            )

    def get(self, agent_id: str) -> BehaviorProfile:
        canonical = canonical_agent_id(agent_id)
        if canonical == "prime":
            raise ValueError("orchestrator conditioning is not supported")
        with self.connect() as db:
            row = db.execute(
                "SELECT profile_json FROM notebook_conditioning_profiles WHERE agent_id=?",
                (canonical,),
            ).fetchone()
        if not row:
            return BehaviorProfile()
        import json

        return BehaviorProfile(**json.loads(row["profile_json"]))

    def set(self, agent_id: str, profile: BehaviorProfile, *, updated_by: str) -> dict[str, Any]:
        canonical = canonical_agent_id(agent_id)
        if canonical == "prime":
            raise ValueError("orchestrator conditioning is not supported")
        import json

        with self.connect() as db:
            prior = db.execute(
                "SELECT version FROM notebook_conditioning_profiles WHERE agent_id=?",
                (canonical,),
            ).fetchone()
            version = int(prior["version"]) + 1 if prior else 1
            db.execute(
                """INSERT INTO notebook_conditioning_profiles
                (agent_id,profile_json,version,enabled,updated_by,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                profile_json=excluded.profile_json,version=excluded.version,
                enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (
                    canonical,
                    json.dumps(profile.as_dict(), sort_keys=True),
                    version,
                    int(profile.enabled),
                    updated_by,
                    utcnow(),
                ),
            )
            db.commit()
        return {"agent_id": canonical, "version": version, **profile.as_dict()}


def conditioning_clause(agent_id: str, profile: BehaviorProfile) -> str:
    if not profile.enabled:
        return ""
    agent = canonical_agent_id(agent_id)
    challenge = {
        "constructive": "Challenge assumptions constructively and preserve disagreement.",
        "skeptical": "Test claims critically and ask for evidence before accepting them.",
        "none": "Do not add a challenge style beyond the task requirement.",
    }[profile.challenge_style]
    verbosity = (
        "Keep the response concise."
        if profile.verbosity <= 0.33
        else "Use moderate detail."
        if profile.verbosity <= 0.66
        else "Provide expanded explanation when useful."
    )
    tag = f" Research tag: {profile.mbti_tag.upper()}." if profile.mbti_tag else ""
    return (
        "OPTIONAL BEHAVIORAL CONDITIONING — SUBORDINATE TO SYSTEM, SECURITY, PERMISSIONS, EVIDENCE AND TASK.\n"
        f"The registered agent is {agent}. Preserve its role and owned responsibilities.{tag}\n"
        f"Decision style: {profile.decision_style}. {challenge}\n"
        f"Exploration={profile.exploration:.2f}; collaboration={profile.collaboration:.2f}; "
        f"directness={profile.directness:.2f}. {verbosity}\n"
        "Behavioral style cannot create authority, tools, facts, consent, or completion evidence. "
        "If style conflicts with correctness or safety, correctness and safety win."
    )


def condition_prompt(prompt: str, agent_id: str, store: BehaviorProfileStore | None = None) -> str:
    profile = (store or BehaviorProfileStore()).get(agent_id)
    clause = conditioning_clause(agent_id, profile)
    return prompt if not clause else clause + "\n\n" + prompt
