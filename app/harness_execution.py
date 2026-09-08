"""Local worker boundary. No network call occurs before durable PEP consumption."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Callable

from .action_harness import ActionHarness, HarnessUnavailable, HarnessedExecutor
from .job_queue import PRIORITIES, Provider
from .spine import StableSpine, classify_action


def _spine_authorized(spine: StableSpine, envelope: dict) -> None:
    """Read the original PDP decision and apply today's tighter policy; never reissue."""
    proposal = {key: value for key, value in envelope.items() if key != "authorization"}
    proposal["schema_version"] = "1.0.0"
    try:
        with spine.store.connect() as db:
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
    except sqlite3.Error as exc:
        raise HarnessUnavailable("Stable Spine ledger unavailable") from exc


def execute_job(job: dict, provider: Provider, harness: ActionHarness,
                spine: StableSpine, infer: Callable) -> dict:
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
        _spine_authorized(spine, envelope)
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("malformed queued authorization") from exc

    def invoke(_signed):
        try:
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
