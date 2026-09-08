"""Disposable-container contract smoke, not operator pilot acceptance.

Uses the packaged HTTP dispatcher/worker with one identity and a fake model.
The ledger reader is read-only; no new authority, signature or test API is made.
Run inside the isolated CI container with this file supplied over stdin.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path


def read_evidence(data_dir, spine_path, job_id):
    def rows(path, sql, args=()):
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]

    queue = rows(Path(data_dir) / "compute-queue.db", "SELECT * FROM compute_jobs WHERE id=?", (job_id,))[0]
    envelope = json.loads(queue["authorization_envelope"])
    auth = envelope["authorization"]
    harness = Path(data_dir) / "action-harness.db"
    return {
        "queue": queue,
        "binding": rows(harness, "SELECT * FROM harness_jobs WHERE job_id=?", (job_id,))[0],
        "decision": rows(spine_path, "SELECT * FROM audit_trail WHERE idempotency_key=?", (envelope["idempotency_key"],))[0],
        "events": rows(harness, "SELECT * FROM harness_events WHERE lease_id=? ORDER BY event_sequence", (auth["lease_id"],)),
        "executions": rows(harness, "SELECT * FROM harness_executions WHERE lease_id=?", (auth["lease_id"],)),
        "nonce": rows(harness, "SELECT * FROM harness_nonces WHERE nonce=?", (auth["nonce"],))[0],
    }


def verify_evidence(evidence, key):
    queue, binding = evidence["queue"], evidence["binding"]
    envelope = json.loads(queue["authorization_envelope"])
    auth = envelope["authorization"]
    signed = json.loads(json.dumps(envelope))
    signature = signed["authorization"].pop("signature")
    payload = json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hmac.compare_digest(signature, hmac.new(key, payload, hashlib.sha256).hexdigest())
    assert json.loads(binding["envelope_json"]) == envelope
    assert binding["decision_id"] == auth["decision_id"]
    assert binding["lease_id"] == auth["lease_id"]
    assert binding["state"] == "completed" and binding["verification_ref"] is None
    proposal = {k: v for k, v in envelope.items() if k != "authorization"}
    proposal["schema_version"] = "1.0.0"
    assert json.loads(evidence["decision"]["envelope_json"]) == proposal
    assert evidence["decision"]["execution_status"] == "AUTHORIZED"
    assert json.loads(evidence["decision"]["decision_record_json"])["decision_id"] == auth["decision_id"]
    assert evidence["nonce"]["lease_id"] == auth["lease_id"]
    assert evidence["nonce"]["correlation_id"] == envelope["correlation_id"]
    assert [e["event_type"] for e in evidence["events"]] == [
        "authorization.accepted", "execution.queued", "execution.started",
        "execution.permitted", "execution.completed",
    ]
    assert len(evidence["executions"]) == 1
    consumed = datetime.fromisoformat(evidence["executions"][0]["consumed_at"])
    assert datetime.fromisoformat(evidence["events"][1]["created_at"]) <= consumed
    assert consumed < datetime.fromisoformat(auth["expires_at"])
    assert consumed < datetime.fromisoformat(auth["lease_expires_at"])
    assert queue["status"] == "completed" and queue["attempts"] == 1
    assert queue["provider"].startswith("ollama-")
    assert not queue["allow_cloud"] and not queue["external_execution"]
    assert queue["max_retries"] == 0 and queue["actual_cost_usd"] == 0
    assert hashlib.sha256(queue["prompt"].encode()).hexdigest() == envelope["parameters"]["prompt_sha256"]
    result = {"result": queue["result"], "input_tokens": queue["input_tokens"],
              "output_tokens": queue["output_tokens"], "actual_cost_usd": 0}
    assert binding["result_digest"] == hashlib.sha256(
        json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run_smoke(request, evidence_reader, key):
    for path in ("/api/cognitive/reason", "/api/cognitive/multi-reason"):
        status, denial = request(path, {"intent": "Review release acceptance architecture"})
        assert status == 409 and "Inference requires Stable Spine" in denial["detail"]
    status, _ = request("/api/compute-queue/jobs", {"agent": "a16", "prompt": "unsigned"})
    assert status == 409
    status, before = request("/api/harness/status")
    assert status == 200 and before["local_concurrency"] == 1
    assert before["cloud_overflow"] is False and before["acceptance_ready"] is False
    payload = {"actor_id": "a16", "prompt": "Review bounded fixture evidence; state uncertainty.",
               "model_role": "fast", "max_retries": 0, "timeout_seconds": 30,
               "idempotency_key": "container-smoke-" + str(uuid.uuid4())}
    status, submitted = request("/api/harness/pilot/dispatch", payload)
    assert status == 202 and submitted["harness"]["status"] == "QUEUED"
    assert submitted["cloud_allowed"] is False
    job_id = submitted["job"]["id"]
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status, job = request("/api/compute-queue/jobs/" + job_id)
        assert status == 200 and "authorization_envelope" not in job
        assert job["status"] not in {"failed", "budget_blocked", "cancelled"}
        if job["status"] == "completed":
            break
        time.sleep(.1)
    else:
        raise AssertionError("governed smoke timed out")
    assert job["result"]
    verify_evidence(evidence_reader(job_id), key)
    status, _ = request("/api/harness/pilot/dispatch", payload)
    assert status == 409  # same request cannot issue another execution
    status, after = request("/api/harness/status")
    assert status == 200 and after["acceptance_ready"] is False
    for state in ("authorized", "started", "completed"):
        assert after["counts"][state] == before["counts"][state] + 1
    assert after["counts"]["verified"] == before["counts"]["verified"]
    assert after["counts"]["uncertain"] == before["counts"]["uncertain"]
    return job_id


def main():
    token = os.environ["PRIME_SPINE_TOKEN"]
    explicit = os.getenv("PRIME_HARNESS_SIGNING_SECRET", "").strip()
    key = explicit.encode() if explicit else hashlib.sha256(b"JARVIS-HARNESS-V0\0" + token.encode()).digest()

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data,
              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    run_smoke(request, lambda job: read_evidence(os.environ["PRIME_DATA_DIR"], os.environ["PRIME_SPINE_DB"], job), key)
    print("Governed container smoke passed; operator pilot acceptance remains pending")


if __name__ == "__main__":
    main()
