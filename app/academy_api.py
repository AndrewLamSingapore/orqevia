"""Native Academy catalog, durable learning evidence and executor notification."""

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Header, HTTPException

from .client_auth import authenticate_owner
from .coaching_observation import coaching_snapshot
from .probability_curriculum import catalog, learning_path, LESSONS, VERSION
from .agent_registry import RegistryError, registered_agent_ids
from .settings import SETTINGS

router = APIRouter(prefix="/api/academy", tags=["academy"])


def data_root():
    return Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))


def retained_methods(agent, root=None):
    """Read only fixed lesson methods backed by an original PASS event."""
    learning_path(agent)  # Canonical registry validation.
    path = Path(root or data_root()) / "agent-coaching.db"
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT m.* FROM academy_retained_methods m JOIN coaching_events e "
                "ON e.id=m.assessment_event_id WHERE m.agent=? AND m.version=? AND e.agent=m.agent "
                "AND e.job_id=m.assessment_job_id AND e.source_revision=m.source_revision "
                "AND e.phase='acceptance' AND e.outcome='PASS' LIMIT 14",
                (agent, VERSION),
            ).fetchall()
            known = {topic: method for topic, _, method in LESSONS}
            return [
                {**dict(row), "grants_execution_authority": False}
                for row in rows
                if known.get(row["topic_id"]) == row["method"]
            ]
    except (OSError, sqlite3.Error):
        return []


@router.get("/probability")
def probability(authorization: str | None = Header(None)):
    authenticate_owner(authorization)
    return {
        **catalog(),
        "coaching": coaching_snapshot(data_root()),
        "agents": sorted(registered_agent_ids(include_orchestrator=False)),
    }


@router.get("/agents/{agent}")
def agent_learning(agent: str, authorization: str | None = Header(None)):
    authenticate_owner(authorization)
    try:
        return {
            **learning_path(agent),
            "retained_methods": retained_methods(agent),
            "retention_policy": "METHODS_ONLY_AFTER_INDEPENDENT_UNSEEN_PASS",
        }
    except (ValueError, RegistryError):
        raise HTTPException(404, "Unknown registered agent") from None


@router.post("/notify/{job_id}")
def notify(job_id: str, authorization: str | None = Header(None)):
    """Wake the existing direct executor; never create or resubmit a job."""
    authenticate_owner(authorization)
    if len(job_id) != 36:
        raise HTTPException(404, "Unknown coaching job")
    try:
        path = data_root() / "agent-coaching.db"
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT s.agent,s.prompt_sha256,c.source_revision FROM coaching_sessions s "
                "JOIN coaching_cohorts c ON c.id=s.cohort_id WHERE s.job_id=? AND s.state='WAITING'",
                (job_id,),
            ).fetchone()
        if row is None or row["source_revision"] != os.getenv("ORQEVIA_RUNTIME_REVISION", ""):
            raise HTTPException(409, "Coaching source binding unavailable")
        from .compute_queue_api import queue, dispatch

        job = queue.get(job_id)
        if (
            job["agent"] != row["agent"]
            or job["model"] != SETTINGS.deep_model
            or hashlib.sha256(job["prompt"].encode()).hexdigest() != row["prompt_sha256"]
            or job["allow_cloud"]
            or job["external_execution"]
            or job["max_cost_usd"] != 0
        ):
            raise HTTPException(409, "Coaching execution binding changed")
        if job["status"] == "queued":
            dispatch(job_id)
        return {
            "job_id": job_id,
            "state": job["status"],
            "executor": "EXISTING_DIRECT_EXECUTOR",
            "new_job_created": False,
        }
    except KeyError:
        raise HTTPException(404, "Unknown coaching job") from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Coaching store unavailable") from None
