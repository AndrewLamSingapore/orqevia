"""Explicit, scoped single-flight contracts in the existing compute database.

Only equivalent requests for the same logical work identity may share execution.
There is deliberately no semantic matching or automatic completed-output cache.
Independent verification and different agents/configurations remain distinct.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(request, *, scope, work_key, model_digest, prompt_version, options, independent_key=None):
    if not isinstance(scope, str) or not 1 <= len(scope) <= 512:
        raise ValueError("Verified owner scope required")
    if not isinstance(work_key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", work_key):
        raise ValueError("Explicit logical work identity required")
    if not isinstance(model_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", model_digest):
        raise ValueError("Pinned actual model digest required")
    if not isinstance(prompt_version, str) or not 1 <= len(prompt_version) <= 128:
        raise ValueError("Prompt version required")
    if not isinstance(options, dict):
        raise ValueError("Actual inference options required")
    if request.get("allow_cloud") or request.get("external_execution"):
        raise ValueError("Single-flight is local inference only")
    if not request.get("model") or not request.get("agent") or not request.get("prompt"):
        raise ValueError("Explicit agent, model and prompt required")
    payload = {
        "request": request,
        "scope_sha256": hashlib.sha256(scope.encode()).hexdigest(),
        "work_key": work_key,
        "model_digest": model_digest,
        "prompt_version": prompt_version,
        "options": options,
        "independent_key": independent_key,
    }
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class SingleFlightQueue:
    def __init__(self, queue, *, clock=time.time, max_consumers=4096):
        if type(max_consumers) is not int or max_consumers < 1:
            raise ValueError("Bounded consumer capacity required")
        self.queue, self.clock, self.max_consumers = queue, clock, max_consumers
        with queue.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS compute_single_flights(
                  id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, scope_hash TEXT NOT NULL,
                  request_json TEXT, source_job_id TEXT, created_epoch REAL NOT NULL,
                  expires_epoch REAL NOT NULL, state TEXT NOT NULL, error_code TEXT);
                CREATE INDEX IF NOT EXISTS compute_flight_lookup
                  ON compute_single_flights(fingerprint,expires_epoch);
                CREATE TABLE IF NOT EXISTS compute_flight_consumers(
                  id TEXT PRIMARY KEY, scope_hash TEXT NOT NULL, consumer_hash TEXT NOT NULL,
                  flight_id TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
                  created_epoch REAL NOT NULL, UNIQUE(scope_hash,consumer_hash));
            """)

    def submit(
        self,
        request,
        *,
        scope,
        work_key,
        consumer_key,
        model_digest,
        prompt_version,
        options,
        freshness_seconds,
        independent=False,
    ):
        if type(freshness_seconds) is not int or not 1 <= freshness_seconds <= 3600:
            raise ValueError("Explicit bounded freshness contract required")
        if type(independent) is not bool:
            raise ValueError("Explicit independence policy required")
        if not isinstance(consumer_key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", consumer_key):
            raise ValueError("Stable owned consumer identity required")
        if "idempotency_key" in request or "request_digest" in request:
            raise ValueError("Single-flight owns its internal submission binding")
        # Separate work identities, permissions, agents, prompt/configuration
        # versions and freshness contracts cannot collide.
        request = dict(request)
        request.setdefault("max_retries", 0)
        key = fingerprint(
            request,
            scope=scope,
            work_key=work_key,
            model_digest=model_digest,
            prompt_version=prompt_version,
            options={**options, "freshness_seconds": freshness_seconds},
            independent_key=consumer_key if independent else None,
        )
        scope_hash = hashlib.sha256(scope.encode()).hexdigest()
        consumer_hash = hashlib.sha256(consumer_key.encode()).hexdigest()
        now = self.clock()
        with self.queue.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT c.id,c.flight_id,f.fingerprint FROM compute_flight_consumers c "
                "JOIN compute_single_flights f ON f.id=c.flight_id "
                "WHERE c.scope_hash=? AND c.consumer_hash=?",
                (scope_hash, consumer_hash),
            ).fetchone()
            if prior:
                if prior["fingerprint"] != key:
                    raise ValueError("Consumer identity conflicts with original request")
                consumer_id, flight_id = prior["id"], prior["flight_id"]
            else:
                if db.execute("SELECT count(*) FROM compute_flight_consumers").fetchone()[0] >= self.max_consumers:
                    raise ValueError("SINGLE_FLIGHT_CONSUMER_CAPACITY")
                flight = db.execute(
                    "SELECT f.id FROM compute_single_flights f LEFT JOIN compute_jobs j ON j.id=f.source_job_id "
                    "WHERE f.fingerprint=? AND f.expires_epoch>? AND f.state IN ('PENDING','ACTIVE') "
                    "AND (f.source_job_id IS NULL OR j.status IN ('queued','running')) ORDER BY f.created_epoch DESC LIMIT 1",
                    (key, now),
                ).fetchone()
                if flight:
                    flight_id = flight["id"]
                    from .observability import record_counter

                    record_counter("orqevia.singleflight.coalesced", 1, {"component": "compute-queue"})
                else:
                    if (
                        db.execute(
                            "SELECT count(*) FROM compute_single_flights WHERE source_job_id IS NULL AND state='PENDING'"
                        ).fetchone()[0]
                        >= self.queue.policy.max_waiting_jobs
                    ):
                        raise ValueError("SINGLE_FLIGHT_PENDING_CAPACITY")
                    flight_id = uuid.uuid4().hex
                    db.execute(
                        "INSERT INTO compute_single_flights VALUES(?,?,?,?,NULL,?,?,?,NULL)",
                        (flight_id, key, scope_hash, canonical(request), now, now + freshness_seconds, "PENDING"),
                    )
                consumer_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO compute_flight_consumers VALUES(?,?,?,?,0,?)",
                    (consumer_id, scope_hash, consumer_hash, flight_id, now),
                )
                self.queue._event(
                    db, None, "single_flight_consumer_accepted", {"consumer_id": consumer_id, "flight_id": flight_id}
                )
        self._ensure_source(flight_id)
        return self.get(consumer_id, scope=scope)

    def _ensure_source(self, flight_id):
        with self.queue.connect() as db:
            row = db.execute("SELECT * FROM compute_single_flights WHERE id=?", (flight_id,)).fetchone()
            if row is None or row["source_job_id"] or row["state"] != "PENDING":
                return
            if not db.execute(
                "SELECT 1 FROM compute_flight_consumers WHERE flight_id=? AND cancelled=0 LIMIT 1", (flight_id,)
            ).fetchone():
                db.execute(
                    "UPDATE compute_single_flights SET state='CANCELLED',request_json=NULL WHERE id=?", (flight_id,)
                )
                return
            request = json.loads(row["request_json"])
        try:
            # The existing atomic per-agent idempotency transaction closes the
            # crash/race window between flight reservation and job submission.
            job = self.queue.submit(**request, idempotency_key="sf-" + flight_id)
        except ValueError as exc:
            if str(exc) == "INFERENCE_QUEUE_FULL":
                return  # Durable accepted reservation; retry on executor wakeup.
            with self.queue.connect() as db:
                db.execute(
                    "UPDATE compute_single_flights SET state='FAILED',error_code='REQUEST_REJECTED' WHERE id=?",
                    (flight_id,),
                )
            raise
        with self.queue.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT source_job_id FROM compute_single_flights WHERE id=?", (flight_id,)).fetchone()
            if row["source_job_id"] not in (None, job["id"]):
                raise ValueError("Single-flight source binding changed")
            db.execute(
                "UPDATE compute_single_flights SET source_job_id=?,state='ACTIVE',request_json=NULL WHERE id=?",
                (job["id"], flight_id),
            )
            if not db.execute(
                "SELECT 1 FROM compute_flight_consumers WHERE flight_id=? AND cancelled=0 LIMIT 1", (flight_id,)
            ).fetchone():
                self.queue.cancel_in_connection(db, job["id"])
        self.queue.wake.set()

    def get(self, consumer_id, *, scope):
        scope_hash = hashlib.sha256(scope.encode()).hexdigest()
        with self.queue.connect() as db:
            row = db.execute(
                "SELECT c.id,c.cancelled,f.source_job_id,f.state,f.error_code "
                "FROM compute_flight_consumers c JOIN compute_single_flights f ON f.id=c.flight_id "
                "WHERE c.id=? AND c.scope_hash=?",
                (consumer_id, scope_hash),
            ).fetchone()
        if not row:
            raise KeyError("Consumer not found")
        job = self.queue.get(row["source_job_id"]) if row["source_job_id"] else None
        cancelled = bool(row["cancelled"])
        return {
            "consumer_id": consumer_id,
            "source_job_id": row["source_job_id"],
            "status": "cancelled" if cancelled else (job["status"] if job else row["state"].lower()),
            "result": None if cancelled or not job or job["status"] != "completed" else job["result"],
            "error": None if cancelled else (job["error"] if job else row["error_code"]),
            "evidence_scope": "SHARED_MODEL_CONTRIBUTION_NOT_INDEPENDENT_VERIFICATION",
        }

    def cancel(self, consumer_id, *, scope):
        scope_hash = hashlib.sha256(scope.encode()).hexdigest()
        with self.queue.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT c.flight_id,f.source_job_id FROM compute_flight_consumers c "
                "JOIN compute_single_flights f ON f.id=c.flight_id WHERE c.id=? AND c.scope_hash=?",
                (consumer_id, scope_hash),
            ).fetchone()
            if not row:
                raise KeyError("Consumer not found")
            db.execute("UPDATE compute_flight_consumers SET cancelled=1 WHERE id=?", (consumer_id,))
            remaining = db.execute(
                "SELECT count(*) FROM compute_flight_consumers WHERE flight_id=? AND cancelled=0", (row["flight_id"],)
            ).fetchone()[0]
            if not remaining and row["source_job_id"]:
                self.queue.cancel_in_connection(db, row["source_job_id"])
            self.queue._event(
                db,
                row["source_job_id"],
                "single_flight_consumer_cancelled",
                {"consumer_id": consumer_id, "remaining_consumers": remaining},
            )
        self.queue.wake.set()
        return self.get(consumer_id, scope=scope)

    def reconcile(self):
        with self.queue.connect() as db:
            rows = db.execute(
                "SELECT id FROM compute_single_flights WHERE state='PENDING' AND source_job_id IS NULL ORDER BY created_epoch LIMIT 64"
            ).fetchall()
        for row in rows:
            try:
                self._ensure_source(row["id"])
            except ValueError:
                continue  # Rejected reservation stays visible with a reason.
        return len(rows)

    def metrics(self):
        with self.queue.connect() as db:
            count = db.execute("SELECT count(*) FROM compute_flight_consumers").fetchone()[0]
            flights = db.execute("SELECT count(*) FROM compute_single_flights").fetchone()[0]
            avoided = db.execute(
                "SELECT coalesce(sum(n-1),0) FROM ("
                "SELECT count(*) n FROM compute_flight_consumers c JOIN compute_single_flights f ON f.id=c.flight_id "
                "JOIN compute_jobs j ON j.id=f.source_job_id WHERE c.cancelled=0 AND j.attempts>0 "
                "GROUP BY f.id HAVING count(*)>1)"
            ).fetchone()[0]
        return {
            "accepted_consumers": count,
            "physical_flights": flights,
            "eligible_duplicate_calls_avoided": avoided,
            "accounting_scope": "Executed flights with multiple non-cancelled equivalent consumers; no CPU/token savings inferred",
        }
