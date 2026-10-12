"""Opt-in, data-only receipts for work executed outside PRIME.

Importing this module does not start a worker, call a model, or mount its router.
An authenticated, local adapter may mount the router explicitly after qualification.
Receipts report observations; they never grant execution or acceptance authority.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agent_registry import registered_agent_ids
from .client_auth import authenticate_owner


HEX64 = re.compile(r"[0-9a-f]{64}\Z")
WORK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
REPOSITORY = re.compile(r"AndrewLamSingapore/[A-Za-z0-9._-]{1,80}\Z")
CONTROL_REPOSITORY = "AndrewLamSingapore/orqevia"
CANONICAL_AUDITED_REPOSITORIES = frozenset({
    CONTROL_REPOSITORY, "AndrewLamSingapore/velyqua",
    "AndrewLamSingapore/the-portal", "AndrewLamSingapore/sky-tablet",
    "AndrewLamSingapore/game-platform", "AndrewLamSingapore/authority-engine",
    "AndrewLamSingapore/AndrewLamSingapore",
})
# The verified rename retained GitHub repository ID 1345668764. This one
# historical spelling is the same control-plane identity, never another product.
# Keep exact recorded names/URLs; normalization is only for caps and selection.
HISTORICAL_REPOSITORY_ALIASES = {"AndrewLamSingapore/prime": CONTROL_REPOSITORY}
AUDITED_REPOSITORIES = CANONICAL_AUDITED_REPOSITORIES | frozenset(HISTORICAL_REPOSITORY_ALIASES)


def _repository_identity(repository: str) -> str:
    return HISTORICAL_REPOSITORY_ALIASES.get(repository, repository)


# Scope selection is a narrow advisory routing default, not tool eligibility.
ROLE_SCOPES = {
    "a01": frozenset({"SOURCE", "CI", "PR", "DEPLOYMENT"}),
    "a05": frozenset({"SOURCE", "DEPLOYMENT"}),
    "a06": frozenset({"SOURCE", "PR"}), "a07": frozenset({"SOURCE", "CI"}),
    "a08": frozenset({"SOURCE", "CI"}), "a09": frozenset({"SOURCE", "PR"}),
    "a14": frozenset({"SOURCE", "CI"}),
    "a15": frozenset({"SOURCE", "CI", "PR"}),
    "a16": frozenset({"SOURCE", "PR"}), "a17": frozenset({"SOURCE", "PR"}),
    "a18": frozenset({"CI", "PR"}), "a19": frozenset({"CI", "DEPLOYMENT"}),
    "a25": frozenset({"CI", "PR"}), "a26": frozenset({"PR", "CI"}),
    "a27": frozenset({"CI", "DEPLOYMENT"}), "a28": frozenset({"PR", "DEPLOYMENT"}),
    "a29": frozenset({"CI", "DEPLOYMENT"}),
}
STATES = ("RECEIVED", "DELEGATED", "RETURNED", "FAILED")
TRANSITIONS = {None: {"RECEIVED"}, "RECEIVED": {"DELEGATED", "FAILED"},
               "DELEGATED": {"RETURNED", "FAILED"}, "RETURNED": set(), "FAILED": set()}

router = APIRouter(prefix="/api/external-work", tags=["external-work-candidate"])


class ExternalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_id: str = Field(max_length=96)
    objective_sha256: str = Field(min_length=64, max_length=64)
    agent_id: str = Field(max_length=8)
    state: Literal["RECEIVED", "DELEGATED", "RETURNED", "FAILED"]
    source: Literal["OWNER_REQUEST", "CODEX_TASK", "GITHUB_ACTIONS", "APPROVED_ADAPTER"]
    evidence_sha256: str = Field(min_length=64, max_length=64)
    # An executor label is routing metadata, not proof that execution happened.
    executor: Literal["NONE", "CODEX", "GITHUB_ACTIONS", "APPROVED_OTHER"] = "NONE"


class GithubAuditSnapshot(BaseModel):
    """A narrow reference to an observed repository fact, never raw source data."""
    model_config = ConfigDict(extra="forbid")

    work_id: str = Field(max_length=96)
    repository: str = Field(max_length=100)
    source_url: str = Field(max_length=260)
    commit_sha: str = Field(min_length=40, max_length=40)
    observed_at: datetime
    confidence: Literal["OBSERVED", "INFERRED", "UNVERIFIED"]
    scope: Literal["SOURCE", "CI", "PR", "DEPLOYMENT"]
    check_state: Literal["PASS", "FAIL", "PENDING", "UNKNOWN"]
    evidence_sha256: str = Field(min_length=64, max_length=64)


def _validate_audit(item: GithubAuditSnapshot) -> None:
    if (not WORK_ID.fullmatch(item.work_id) or not REPOSITORY.fullmatch(item.repository)
            or item.repository not in AUDITED_REPOSITORIES):
        raise ValueError("invalid audit binding")
    if not re.fullmatch(r"[0-9a-f]{40}", item.commit_sha) or not HEX64.fullmatch(item.evidence_sha256):
        raise ValueError("invalid audit digest")
    if item.observed_at.tzinfo is None or item.observed_at.utcoffset() is None:
        raise ValueError("audit observation requires timezone")
    url = urlsplit(item.source_url)
    prefix = "/" + item.repository + "/"
    suffix = url.path[len(prefix):] if url.path.startswith(prefix) else ""
    source_shape = (suffix in {"commit/" + item.commit_sha, "tree/" + item.commit_sha}
                    or bool(re.fullmatch(r"(?:pull|actions/runs)/[1-9][0-9]{0,15}", suffix)))
    if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment
            or not source_shape):
        raise ValueError("audit source must be a credential-free GitHub repository URL")


def _validate(receipt: ExternalReceipt) -> None:
    if not WORK_ID.fullmatch(receipt.work_id):
        raise ValueError("invalid work id")
    if not HEX64.fullmatch(receipt.objective_sha256) or not HEX64.fullmatch(receipt.evidence_sha256):
        raise ValueError("invalid digest")
    if receipt.agent_id not in registered_agent_ids(include_orchestrator=False):
        raise ValueError("unregistered agent")
    if receipt.state == "RECEIVED" and receipt.executor != "NONE":
        raise ValueError("receipt cannot claim an executor")
    if receipt.state in {"DELEGATED", "RETURNED"} and receipt.executor == "NONE":
        raise ValueError("delegation requires an executor label")


def _db_path() -> Path:
    root = Path(os.getenv("PRIME_DATA_DIR", "/data"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "external-work-candidate.db"


def record_receipt(receipt: ExternalReceipt, *, db_path: Path | None = None) -> dict:
    """Persist one bounded state transition; no free-form text or secrets stored."""
    _validate(receipt)
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS external_work_receipts (
            work_id TEXT NOT NULL, sequence INTEGER NOT NULL, objective_sha256 TEXT NOT NULL,
            agent_id TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL, executor TEXT NOT NULL,
            PRIMARY KEY(work_id, sequence))""")
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("""SELECT sequence, objective_sha256, agent_id, state, executor
            FROM external_work_receipts WHERE work_id=? ORDER BY sequence DESC LIMIT 1""",
            (receipt.work_id,)).fetchone()
        prior_state = previous[3] if previous else None
        if receipt.state not in TRANSITIONS[prior_state]:
            raise ValueError("invalid receipt transition")
        if previous and (previous[1] != receipt.objective_sha256 or previous[2] != receipt.agent_id):
            raise ValueError("work binding changed")
        if previous and prior_state == "DELEGATED" and receipt.executor != previous[4]:
            raise ValueError("executor binding changed")
        sequence = previous[0] + 1 if previous else 1
        db.execute("INSERT INTO external_work_receipts VALUES(?,?,?,?,?,?,?,?)",
                   (receipt.work_id, sequence, receipt.objective_sha256, receipt.agent_id,
                    receipt.state, receipt.source, receipt.evidence_sha256, receipt.executor))
    return {"work_id": receipt.work_id, "sequence": sequence, "state": receipt.state,
            "authority": "REPORTED_DATA_ONLY_NOT_ACCEPTED"}


def owner_digest(work_id: str, *, db_path: Path | None = None) -> dict:
    """Return a concise evidence index, never prompts, result text, or credentials."""
    if not WORK_ID.fullmatch(work_id):
        raise ValueError("invalid work id")
    path = db_path or _db_path()
    if not path.exists():
        raise KeyError(work_id)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        rows = db.execute("""SELECT sequence, objective_sha256, agent_id, state, source,
            evidence_sha256, executor FROM external_work_receipts WHERE work_id=?
            ORDER BY sequence""", (work_id,)).fetchall()
    if not rows:
        raise KeyError(work_id)
    return {"work_id": work_id, "objective_sha256": rows[0][1], "agent_id": rows[0][2],
            "state": rows[-1][3], "authority": "REPORTED_DATA_ONLY_NOT_ACCEPTED",
            "evidence": [{"sequence": row[0], "state": row[3], "source": row[4],
                          "evidence_sha256": row[5], "executor": row[6]} for row in rows]}


def record_github_audit(item: GithubAuditSnapshot, *, db_path: Path | None = None) -> dict:
    """Attach one source-labelled repo snapshot to an existing work receipt.

    This does not fetch GitHub or establish its own private-repository access.
    The caller's reported check state is not an independently verified result.
    """
    _validate_audit(item)
    path = db_path or _db_path()
    if not path.exists():
        raise KeyError(item.work_id)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS external_github_audits (
            work_id TEXT NOT NULL, repository TEXT NOT NULL, source_url TEXT NOT NULL,
            commit_sha TEXT NOT NULL, observed_at TEXT NOT NULL, confidence TEXT NOT NULL,
            scope TEXT NOT NULL, check_state TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
            PRIMARY KEY(work_id, repository, scope))""")
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM external_work_receipts WHERE work_id=?", (item.work_id,)).fetchone():
            raise KeyError(item.work_id)
        identities = {_repository_identity(row[0]) for row in db.execute(
            "SELECT DISTINCT repository FROM external_github_audits WHERE work_id=?", (item.work_id,))}
        if len(identities) >= 7 and _repository_identity(item.repository) not in identities:
            raise ValueError("repository audit cap reached")
        try:
            db.execute("INSERT INTO external_github_audits VALUES(?,?,?,?,?,?,?,?,?)",
                       (item.work_id, item.repository, item.source_url, item.commit_sha,
                        item.observed_at.isoformat(), item.confidence, item.scope,
                        item.check_state, item.evidence_sha256))
        except sqlite3.IntegrityError:
            raise ValueError("audit snapshot already recorded") from None
    return {"work_id": item.work_id, "repository": item.repository,
            "scope": item.scope, "authority": "REPORTED_DATA_ONLY_NOT_ACCEPTED"}


def github_audit_digest(work_id: str, *, db_path: Path | None = None) -> dict:
    """Return at most 32 rows: seven identities, one historical alias, four scopes."""
    if not WORK_ID.fullmatch(work_id):
        raise ValueError("invalid work id")
    path = db_path or _db_path()
    if not path.exists():
        raise KeyError(work_id)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        try:
            rows = db.execute("""SELECT repository, source_url, commit_sha, observed_at,
                confidence, scope, check_state, evidence_sha256 FROM external_github_audits
                WHERE work_id=? ORDER BY repository, scope""", (work_id,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    return {"work_id": work_id, "authority": "REPORTED_DATA_ONLY_NOT_ACCEPTED",
            "snapshots": [{"repository": r[0], "source_url": r[1], "commit_sha": r[2],
                           "observed_at": r[3], "confidence": r[4], "scope": r[5],
                           "check_state": r[6], "evidence_sha256": r[7]} for r in rows]}


def select_github_audits(work_id: str, agent_id: str, repositories: tuple[str, ...],
                         *, db_path: Path | None = None, max_items: int = 4,
                         allow_private_prime: bool = False) -> dict:
    """Select task-specific cited facts; the private control plane is excluded by default.

    The caller must supply the repositories relevant to the task. This selector
    never injects raw source into prompts or grants the agent GitHub access.
    """
    if agent_id not in registered_agent_ids(include_orchestrator=False):
        raise ValueError("unregistered agent")
    if (not repositories or len(repositories) > 7 or
            any(repository not in AUDITED_REPOSITORIES for repository in repositories)):
        raise ValueError("explicit audited repository selection required")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 4:
        raise ValueError("max_items must be 1 to 4")
    scopes = ROLE_SCOPES.get(agent_id, frozenset())
    rows = github_audit_digest(work_id, db_path=db_path)["snapshots"]
    identities = {_repository_identity(repository) for repository in repositories}
    selected = [row for row in rows if _repository_identity(row["repository"]) in identities and row["scope"] in scopes
                and (allow_private_prime or _repository_identity(row["repository"]) != CONTROL_REPOSITORY)]
    return {"work_id": work_id, "agent_id": agent_id, "authority": "UNTRUSTED_CITED_DATA_ONLY",
            "citations": selected[:max_items], "omitted": len(selected[max_items:]),
            "private_prime_excluded": not allow_private_prime}


@router.post("/receipts", status_code=202)
def submit_receipt(receipt: ExternalReceipt, authorization: str | None = Header(default=None)):
    authenticate_owner(authorization)
    try:
        return record_receipt(receipt)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/{work_id}")
def get_digest(work_id: str, authorization: str | None = Header(default=None)):
    authenticate_owner(authorization)
    try:
        return owner_digest(work_id)
    except ValueError:
        raise HTTPException(422, "invalid work id") from None
    except KeyError:
        raise HTTPException(404, "work not found") from None


@router.post("/github-audits", status_code=202)
def submit_github_audit(item: GithubAuditSnapshot, authorization: str | None = Header(default=None)):
    authenticate_owner(authorization)
    try:
        return record_github_audit(item)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "work not found") from None


@router.get("/{work_id}/github-audits")
def get_github_audits(work_id: str, authorization: str | None = Header(default=None)):
    authenticate_owner(authorization)
    try:
        return github_audit_digest(work_id)
    except ValueError:
        raise HTTPException(422, "invalid work id") from None
    except KeyError:
        raise HTTPException(404, "work not found") from None
