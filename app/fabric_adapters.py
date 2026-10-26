"""Fixed local fabric integrations and read-only cloud execution observation.

No discovered record selects code, URLs, model paths, permissions or training.
Cloud observation never initiates an inference or spends money.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading

from .mlp_fabric import MLPCapabilityFabric, validate_artifact

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = ROOT / "config/mlp/quadratic-reference-v1.json"
REFERENCE_SHA256 = "d602f5a9436fcf6dfad47d33df16e422956114cd6942ef0f3439bf88c1dd72ac"
_MLP_LOCK = threading.RLock()
_EVENT_LOCK = threading.RLock()
_MLP = None


def _sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def get_mlp():
    """Only the exact reviewed reference artifact is admitted by this release."""
    global _MLP
    with _MLP_LOCK:
        content = REFERENCE_PATH.read_bytes()
        if hashlib.sha256(content).hexdigest() != REFERENCE_SHA256:
            raise ValueError("reference artifact integrity failed")
        if _MLP is None:
            # Parse the exact verified bytes without a second filesystem read.
            artifact = json.loads(content)
            validate_artifact(artifact)
            expected = artifact["approval"]
            fabric = MLPCapabilityFabric(verify_approval=lambda approval: approval == expected)
            fabric.register(artifact)
            _MLP = fabric
        return _MLP


def mlp_infer(rows, trace_id):
    # This owner-invoked reference is never an alternative to infer_for_agent's
    # certification and verified capability-decision gates.
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("reference inference requires 1-32 rows")
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"x"}
            or isinstance(row["x"], bool)
            or not isinstance(row["x"], (int, float))
            or not math.isfinite(row["x"])
            or not -3.0 <= row["x"] <= 2.9
        ):
            raise ValueError("reference domain is finite x between -3.0 and 2.9")
    with _MLP_LOCK:
        fabric = get_mlp()
        model_id = next(iter(fabric.models))
        result = fabric.infer(model_id, rows, trace_id=trace_id)
    return {
        **result,
        "scope": "SYNTHETIC_QUADRATIC_REFERENCE_ONLY",
        "approximation": True,
        "grants_agent_authority": False,
        "automatic_training": False,
    }


def mlp_observation():
    result = mlp_infer([{"x": -0.5}, {"x": 0.5}, {"x": 1.5}], "fixed-fabric-readiness")
    expected = [0.25, 0.25, 2.25]
    errors = [abs(x - y) for x, y in zip(result["output"], expected)]
    if max(errors) >= 0.6:
        raise ValueError("numerical reference check failed")
    return {
        "model_id": result["model_id"],
        "artifact_hash": result["artifact_hash"],
        "artifact_file_sha256": REFERENCE_SHA256,
        "device": "cpu",
        "points": 3,
        "max_absolute_error": max(errors),
        "output_sha256": _sha(result["output"]),
        "health_scope": "ACTUAL_BOUNDED_REFERENCE_INFERENCE",
        "qualification": "NO_DOMAIN_OR_AGENT_CERTIFICATION",
        "automatic_training": False,
        "grants_agent_authority": False,
    }


def publish_event(job):
    """Publish hashes and provenance from a re-read actual completed execution."""
    from .runtime import events

    event = {
        "schema_version": "1.0.0",
        "event_id": "queue-execution:" + job["id"],
        "event_type": "compute.execution.completed",
        # Frozen contract's compatibility identifier; not another product.
        "source": "prime",
        "occurred_at": job["completed_at"],
        "evidence_level": "E1",
        "correlation_id": job["id"],
        "subject_id": "queue-job:" + job["id"],
        "provenance": ["authoritative-compute-queue:" + job["id"]],
        "payload": {
            "agent_id": job["agent"],
            "provider": job.get("provider"),
            "result_sha256": hashlib.sha256(job["result"].encode()).hexdigest(),
            "classification": "EXECUTION_OBSERVATION_NOT_VERIFIED_FACT",
        },
    }
    with _EVENT_LOCK:
        return events.ingest(event)


def event_observation():
    """Verify queue binding and persisted outputs of all four real projectors."""
    from .runtime import events
    from .compute_queue_api import queue

    with events.connect() as db:
        row = db.execute(
            "SELECT * FROM portfolio_events WHERE event_type='compute.execution.completed' AND source='prime' ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("no completed queue event has been integrated")
        event = dict(row)
        projections = [
            dict(p) for p in db.execute("SELECT * FROM event_projections WHERE event_id=?", (row["event_id"],))
        ]
        review = db.execute("SELECT status FROM cognitive_review_queue WHERE event_id=?", (row["event_id"],)).fetchone()
        evaluation = db.execute("SELECT * FROM event_evaluations WHERE event_id=?", (row["event_id"],)).fetchone()
        graph = db.execute("SELECT * FROM semantic_graph_nodes WHERE node_id=?", (row["subject_id"],)).fetchone()
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
    payload = json.loads(event["payload_json"])
    job = queue.get(event["correlation_id"])
    if (
        job["status"] != "completed"
        or payload["result_sha256"] != hashlib.sha256(job["result"].encode()).hexdigest()
        or payload["agent_id"] != job["agent"]
        or event["occurred_at"] != job["completed_at"]
        or event["event_id"] != "queue-execution:" + job["id"]
        or event["subject_id"] != "queue-job:" + job["id"]
        or event["evidence_level"] != "E1"
        or event["schema_version"] != "1.0.0"
        or json.loads(event["provenance_json"]) != ["authoritative-compute-queue:" + job["id"]]
        or integrity != "ok"
    ):
        raise ValueError("persisted event is not bound to its actual execution")
    required = {"governed_memory_candidate", "semantic_graph", "bounded_cognitive_review", "evaluation_record"}
    if {p["projector"] for p in projections if p["status"] == "projected"} != required:
        raise ValueError("event projections are incomplete")
    memory_projection = next(p for p in projections if p["projector"] == "governed_memory_candidate")
    details = json.loads(memory_projection["details_json"])
    with events.memory.connect() as db:
        memory = db.execute(
            "SELECT content_json,durable_kind FROM episodic_memory WHERE episode_id=?", (details["episode_id"],)
        ).fetchone()
    if (
        not memory
        or json.loads(memory["content_json"])
        != {
            "event_id": event["event_id"],
            "payload": payload,
            "provenance": json.loads(event["provenance_json"]),
            "evidence_level": event["evidence_level"],
        }
        or memory["durable_kind"]
        or details.get("auto_promoted") is not False
        or not graph
        or graph["last_event_id"] != event["event_id"]
        or graph["node_type"] != "compute"
        or json.loads(graph["attributes_json"])
        != {
            "source": event["source"],
            "event_type": event["event_type"],
            "evidence_level": event["evidence_level"],
            "payload": payload,
        }
        or not review
        or review[0] != "not_required"
        or not evaluation
        or evaluation["review_required"]
        or evaluation["evidence_level"] != event["evidence_level"]
        or evaluation["provenance_count"] != len(json.loads(event["provenance_json"]))
        or evaluation["payload_fields"] != len(payload)
    ):
        raise ValueError("event projector output verification failed")
    return {
        "event_id": event["event_id"],
        "job_id": job["id"],
        "result_sha256": payload["result_sha256"],
        "projectors_verified": 4,
        "persistence_integrity": "PASS",
        "auto_promoted": False,
        "health_scope": "PERSISTED_EXECUTION_AND_FOUR_PROJECTOR_READBACK",
    }


def hf_observation(entry):
    """Observe the most recent terminal cloud execution; never submit one."""
    from .compute_queue_api import queue

    if entry.get("enabled") is not True:
        raise ValueError("provider is not enabled")
    with queue.connect() as db:
        row = db.execute(
            "SELECT * FROM compute_jobs WHERE provider=? AND status IN ('completed','failed','cancelled','denied') ORDER BY created_at DESC LIMIT 1",
            (entry["id"],),
        ).fetchone()
    if row is None:
        raise ValueError("no actual provider execution is available")
    job = dict(row)
    cost, cap = job.get("actual_cost_usd"), job.get("max_cost_usd")
    # Queue.provider/model describe the selected primary, which can fail over.
    # The independent task/agent-bound ledger records the actual executed route.
    ledger_path = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "compute-ledger.db"
    with sqlite3.connect(ledger_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        attempt = db.execute(
            "SELECT id,cost,details FROM reasoning_attempts WHERE task_id=? ORDER BY rowid DESC LIMIT 1", (job["id"],)
        ).fetchone()
    if attempt is None:
        raise ValueError("task-bound cloud execution receipt is missing")
    details = json.loads(attempt[2])
    if not isinstance(details, dict):
        raise ValueError("cloud execution ledger details are not an object")
    actual_model = details.get("model")
    if (
        job["status"] != "completed"
        or not job.get("result")
        or job.get("allow_cloud") != 1
        or job.get("data_classification") != "CLOUD_PERMITTED"
        or actual_model != entry.get("model")
        or isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or not isinstance(cap, (int, float))
        or not math.isfinite(cap)
        or not 0 <= cost <= cap
        or cap <= 0
    ):
        raise ValueError("latest provider execution does not satisfy its governed contract")
    if (
        details.get("success") is not True
        or details.get("provider") != entry["id"]
        or details.get("requested_provider") != entry["id"]
        or details.get("agent_id") != job["agent"]
        or details.get("input_tokens") != job.get("input_tokens")
        or details.get("output_tokens") != job.get("output_tokens")
        or attempt[1] is None
        or abs(attempt[1] - cost) > 1e-12
    ):
        raise ValueError("actual cloud route attribution or usage disagrees with the queue")
    completed = datetime.fromisoformat(job["completed_at"])
    if completed.utcoffset() is None or completed > datetime.now(timezone.utc):
        raise ValueError("provider execution observation timestamp is invalid")
    return {
        "job_id": job["id"],
        "provider": entry["id"],
        "model": actual_model,
        "result_sha256": hashlib.sha256(job["result"].encode()).hexdigest(),
        "completed_at": job["completed_at"],
        "actual_cost_usd": cost,
        "max_cost_usd": cap,
        "input_tokens": job.get("input_tokens"),
        "output_tokens": job.get("output_tokens"),
        "execution_ledger_id": attempt[0],
        "execution_ledger_sha256": _sha(details),
        "billing_status": details.get("billing_status", "NOT_RECONCILED"),
        "health_scope": "LAST_GOVERNED_INFERENCE_VALID_UNTIL_REPLACED_NOT_CONTINUOUS_PROVIDER_SLA",
        "probe_spends_money": False,
    }
