"""Local worker boundary. No network call occurs before durable PEP consumption."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .action_harness import ActionHarness, HarnessUnavailable, HarnessedExecutor
from .job_queue import PRIORITIES, Provider, JobQueue
from .spine import StableSpine, classify_action
from .inference_boundary import worker_call


@contextmanager
def _spine_authorized(spine: StableSpine, envelope: dict):
    """Read the original PDP decision and apply today's tighter policy; never reissue."""
    proposal = {key: value for key, value in envelope.items() if key != "authorization"}
    proposal["schema_version"] = "1.0.0"
    try:
        with spine.store.connect() as db:
            # Pin the policy and original decision until the admitted call has
            # returned. A concurrent writer must fail/wait, never invalidate a
            # snapshot between PDP validation and durable PEP consumption.
            db.execute("PRAGMA busy_timeout=0")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM audit_trail WHERE idempotency_key=?",
                (envelope["idempotency_key"],),
            ).fetchone()
            if (not row or row["execution_status"] != "AUTHORIZED"
                    or json.loads(row["envelope_json"]) != proposal
                    or json.loads(row["decision_record_json"]).get("decision_id")
                    != envelope["authorization"]["decision_id"]):
                raise PermissionError("durable Stable Spine decision is missing or changed")
            trust = db.execute("SELECT * FROM trust_registry WHERE action_type=?",
                               (envelope["action"],)).fetchone()
            if classify_action(proposal, dict(trust) if trust else None)["state"] not in {"AUTO", "BOUNDED_AUTO"}:
                raise PermissionError("current Stable Spine policy no longer authorizes inference")
            yield
    except sqlite3.Error as exc:
        raise HarnessUnavailable("Stable Spine ledger unavailable") from exc


def execute_job(job: dict, provider: Provider, harness: ActionHarness,
                spine: StableSpine, infer: Callable, *, queue: JobQueue) -> dict:
    """Pin the durable claim and policy in a fixed queue -> Spine -> PEP order.

    PEP consumption commits before inference. A crash releases the read fences
    but never rolls back that consumed authority. This assumes intact shared
    stores; it is deliberately not a checkpoint-rollback or provider fence.
    """
    paths = {str(Path(path).resolve()).casefold() for path in
             (queue.db_path, spine.store.path, harness.db_path)}
    if len(paths) != 3:
        raise PermissionError("admission stores must have distinct paths")
    try:
        with queue.connect() as db:
            db.execute("PRAGMA busy_timeout=0")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM compute_jobs WHERE id=?", (job["id"],)).fetchone()
            if not row or dict(row) != job:
                raise PermissionError("worker claim changed or missing")
            envelope = json.loads(job.get("authorization_envelope") or "null")
            if not isinstance(envelope, dict):
                raise PermissionError("worker requires a complete signed authorization")
            with _spine_authorized(spine, envelope):
                if (job.get("lease_until") or 0) <= time.time():
                    raise PermissionError("worker claim expired")
                harness.record_claim(job["id"], envelope)
                return _execute_bound_job(job, provider, harness, infer)
    except sqlite3.Error as exc:
        raise HarnessUnavailable("admission store unavailable or busy") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("malformed queued authorization") from exc


def _execute_bound_job(job: dict, provider: Provider, harness: ActionHarness,
                       infer: Callable) -> dict:
    """Three pilot identities only; retries require a new PDP decision and lease."""
    try:
        envelope = json.loads(job.get("authorization_envelope") or "null")
        if not isinstance(envelope, dict):
            raise PermissionError("worker requires a complete signed authorization")
        params = envelope["parameters"]
        if (envelope["actor_id"] not in harness.policy.pilot_agents
                or job["agent"] != envelope["actor_id"] or envelope["action"] != "agent.infer"
                or provider.kind != "local" or job.get("status") != "running"
                or job.get("provider") != provider.name
                or job.get("attempts") != 1
                or params.get("allow_cloud") is not False
                or params.get("external_execution") is not False
                or job.get("allow_cloud") or job.get("external_execution")
                or job.get("max_cost_usd") != 0 or job.get("model")
                or job.get("max_retries") != 0 or params.get("max_retries") != 0
                or envelope["context"].get("policy_limits") != {"cloud": False, "local_concurrency": 1}):
            raise PermissionError("job is outside the signed local pilot boundary")
        if hashlib.sha256(job["prompt"].encode()).hexdigest() != params["prompt_sha256"]:
            raise PermissionError("queued prompt differs from signed digest")
        expected_priority = PRIORITIES[params["priority"]]
        if job["priority"] != expected_priority:
            raise PermissionError("queued priority differs from signed policy")
        for key in ("model_role", "ram_mb", "vram_mb", "timeout_seconds"):
            if job[key] != params[key]:
                raise PermissionError("queued parameters differ from signed envelope")
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("malformed queued authorization") from exc

    def invoke(_signed):
        try:
            # Waiting for PEP's durable consumption may outlast the queue claim.
            # Consumption is deliberately retained if this final check fails.
            if (job.get("lease_until") or 0) <= time.time():
                raise PermissionError("worker claim expired after consumption")
            with worker_call(job):
                result = infer(job, provider)
        except Exception:
            # A timeout or worker error cannot prove inference stopped remotely.
            # Preserve the single slot until explicit operator reconciliation.
            harness.record_outcome(job["id"], uncertain=True)
            raise
        harness.record_outcome(job["id"], result=result)
        return result

    # No captured dispatch timestamp: signature/expiry/policy/revocation and
    # nonce/lease/job binding are checked at the actual worker boundary.
    return HarnessedExecutor(harness, invoke).execute(envelope, job_id=job["id"])
