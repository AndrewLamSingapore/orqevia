"""Governed, persistent shared compute queue for all ORQEVIA agents."""
from __future__ import annotations

import json
import hashlib
import re
import math
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent_registry import RegistryError, canonical_agent_id
from .observability import record_counter, record_duration, span, traced


TERMINAL = {"completed", "failed", "cancelled", "budget_blocked"}
PRIORITIES = {"background": 10, "low": 25, "normal": 50, "high": 75, "critical": 100}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueuePolicy:
    # Production remains at one inference slot. Candidate N>1 needs a measured
    # profile and bounded Owner reserve before monitored acceptance.
    global_concurrency: int = 1
    per_agent_concurrency: int = 1
    # Zero disables reservation. A positive value caps simultaneous local
    # noncritical inference and leaves capacity for an arriving Owner request.
    background_concurrency: int = 0
    local_ram_mb: int = 32768
    local_vram_mb: int = 0
    cloud_wait_seconds: int = 300
    starvation_interval_seconds: int = 300
    starvation_boost_per_interval: int = 10
    starvation_boost_cap: int = 100
    max_job_cost_usd: float = 2.0
    daily_cost_ceiling_usd: float = 10.0
    # A separate upper bound also covers inline governed cloud requests. It
    # never increases the measured global/local worker limit.
    cloud_concurrency: int = 1
    coordinated: bool = False
    max_waiting_jobs: int = 64

    @classmethod
    def from_env(cls) -> "QueuePolicy":
        def integer(name: str, default: int, low: int, high: int) -> int:
            try: value = int(os.getenv(name, str(default)))
            except ValueError: value = default
            return max(low, min(high, value))
        def decimal(name: str, default: float, low: float, high: float) -> float:
            try: value = float(os.getenv(name, str(default)))
            except ValueError: value = default
            return max(low, min(high, value))
        return cls(
            global_concurrency=integer("ORQEVIA_QUEUE_CONCURRENCY", 1, 1, 29),
            per_agent_concurrency=integer("ORQEVIA_AGENT_CONCURRENCY", 1, 1, 8),
            background_concurrency=integer("ORQEVIA_BACKGROUND_INFERENCE_LIMIT", 0, 0, 29),
            local_ram_mb=integer("ORQEVIA_LOCAL_RAM_MB", 32768, 1024, 1048576),
            local_vram_mb=integer("ORQEVIA_LOCAL_VRAM_MB", 0, 0, 1048576),
            cloud_wait_seconds=integer("ORQEVIA_CLOUD_WAIT_SECONDS", 300, 0, 86400),
            starvation_interval_seconds=integer("ORQEVIA_STARVATION_INTERVAL_SECONDS", 300, 1, 86400),
            starvation_boost_per_interval=integer("ORQEVIA_STARVATION_BOOST", 10, 1, 100),
            starvation_boost_cap=integer("ORQEVIA_STARVATION_BOOST_CAP", 100, 1, 1000),
            max_job_cost_usd=decimal("ORQEVIA_MAX_JOB_COST_USD", 2.0, 0, 10000),
            daily_cost_ceiling_usd=decimal("ORQEVIA_DAILY_COST_USD", 10.0, 0, 100000),
            cloud_concurrency=integer("ORQEVIA_CLOUD_REQUEST_CAPACITY", 1, 1, 4),
            coordinated=os.getenv('ORQEVIA_OUTPUT_QUEUE_MODE') == 'home_eco',
            max_waiting_jobs=integer('ORQEVIA_MAX_WAITING_JOBS', 64, 1, 4096),
        )


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str  # local | cloud
    model: str
    ram_mb: int
    vram_mb: int
    concurrency: int
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    max_output_tokens: int = 4096
    explicit_selection_required: bool = False
    # Trusted fixed-price request contracts, never a client-supplied rate.
    maximum_charge_usd: str | None = None


class JobQueue:
    """SQLite queue with atomic leases and resource/cost admission control."""

    def __init__(self, db_path: str | Path, policy: QueuePolicy | None = None, *, guardian=None):
        self.db_path = str(db_path)
        self.policy = policy or QueuePolicy.from_env()
        self.backend_endpoint = os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434').rstrip('/')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self._init()
        from .resource_guardian import ResourceGuardian
        self.guardian = guardian if guardian is not None else ResourceGuardian.from_environment()
        if self.guardian is not None:
            with self.connect() as connection:
                self.guardian.install(connection)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back, then release the connection on every exit."""
        c = sqlite3.connect(self.db_path, timeout=20, check_same_thread=False)
        try:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=15000")
            with c:
                yield c
        finally:
            c.close()

    def _init(self) -> None:
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS compute_jobs(
              id TEXT PRIMARY KEY, agent TEXT NOT NULL, prompt TEXT NOT NULL,
              priority INTEGER NOT NULL, model_role TEXT NOT NULL, model TEXT,
              ram_mb INTEGER NOT NULL, vram_mb INTEGER NOT NULL,
              timeout_seconds INTEGER NOT NULL, max_retries INTEGER NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, max_cost_usd REAL NOT NULL,
              allow_cloud INTEGER NOT NULL DEFAULT 0, external_execution INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL, approval_status TEXT NOT NULL, approval_reason TEXT,
              provider TEXT, route_reason TEXT, lease_until REAL, estimated_cost_usd REAL DEFAULT 0,
              actual_cost_usd REAL DEFAULT 0, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
              result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              started_at TEXT, completed_at TEXT);
            CREATE INDEX IF NOT EXISTS idx_compute_claim ON compute_jobs(status,priority DESC,created_at);
            CREATE INDEX IF NOT EXISTS idx_compute_agent ON compute_jobs(agent,status);
            CREATE TABLE IF NOT EXISTS compute_approvals(
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL, decision TEXT NOT NULL,
              actor TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_events(
              id TEXT PRIMARY KEY, job_id TEXT, event_type TEXT NOT NULL,
              details_json TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_submission_keys(
              agent TEXT NOT NULL, key_sha256 TEXT NOT NULL, request_sha256 TEXT NOT NULL,
              job_id TEXT NOT NULL, PRIMARY KEY(agent,key_sha256));
            """)
            # executescript commits implicitly; keep the column upgrades in one
            # SQLite write transaction.
            c.execute("BEGIN IMMEDIATE")

            if 'classification' not in {r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}:
                c.execute("ALTER TABLE compute_jobs ADD COLUMN classification TEXT DEFAULT 'R0'")
            if 'harness_envelope' not in {r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}:
                c.execute('ALTER TABLE compute_jobs ADD COLUMN harness_envelope TEXT')
            columns={r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}
            for name,definition in [('preferred_provider','TEXT'),('data_classification',"TEXT DEFAULT 'LOCAL_ONLY'"),('task_class',"TEXT DEFAULT 'auto'"),('response_format',"TEXT DEFAULT 'text'"),('response_schema','TEXT'),('response_schema_order',"TEXT DEFAULT 'canonical'"),('inference_receipt','TEXT')]:
                if name not in columns:c.execute(f'ALTER TABLE compute_jobs ADD COLUMN {name} {definition}')
            if 'cloud_inflight' not in columns:
                c.execute('ALTER TABLE compute_jobs ADD COLUMN cloud_inflight INTEGER NOT NULL DEFAULT 0')
                # Legacy rows have no reliable dispatch-kind evidence. NULL
                # identities or a cloud provider named like a local one cannot
                # prove cleanup; conservatively retain all cloud-eligible work.
                c.execute("UPDATE compute_jobs SET cloud_inflight=1 WHERE status='running' AND allow_cloud=1")
            for name, definition in [('lifecycle_state', 'TEXT'), ('timings_json', 'TEXT'),
                                     ('local_inflight', 'INTEGER NOT NULL DEFAULT 0'),
                                     ('not_before', 'REAL NOT NULL DEFAULT 0')]:
                if name not in columns:
                    c.execute(f'ALTER TABLE compute_jobs ADD COLUMN {name} {definition}')

    def _event(self, c: sqlite3.Connection, job_id: str | None, event: str, details: dict) -> None:
        c.execute("INSERT INTO compute_events VALUES(?,?,?,?,?)",
                  (str(uuid.uuid4()), job_id, event, json.dumps(details, separators=(",", ":")), utcnow()))

    def submit(self, *, agent: str, prompt: str, priority: str | int = "normal",
               model_role: str = "auto", model: str = "", ram_mb: int = 1024,
               vram_mb: int = 0, timeout_seconds: int = 300, max_retries: int = 2,
               max_cost_usd: float = 0.0, allow_cloud: bool = False,
               external_execution: bool = False, harness_envelope: dict | None = None, classification: str = "R0", preferred_provider: str | None = None, data_classification: str = 'LOCAL_ONLY', task_class: str = 'auto', response_format: str = 'text', response_schema: dict | None = None, response_schema_order: str = 'canonical', idempotency_key: str | None = None, request_digest: str | None = None) -> dict:
        # Bind the complete submitted request before local normalization. Reusing
        # a key with a changed request must never disclose or dispatch a new job.
        if idempotency_key is not None:
            if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',idempotency_key):
                raise ValueError('invalid idempotency_key')
            submitted={key:value for key,value in locals().items() if key not in {'self','idempotency_key','request_digest'}
                       and not (key == 'response_schema' and value is None)
                       and not (key == 'response_schema_order' and value == 'canonical')}
            request_hash=(request_digest if isinstance(request_digest,str) and re.fullmatch('[0-9a-f]{64}',request_digest)
                          else hashlib.sha256(json.dumps(submitted,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest())
            key_hash=hashlib.sha256(idempotency_key.encode()).hexdigest()
        if not agent.strip() or not prompt.strip(): raise ValueError("agent and prompt are required")
        if response_format not in {'text', 'strict_json'}: raise ValueError('invalid response_format')
        if type(response_schema_order) is not str or response_schema_order not in {'canonical', 'declared'}:
            raise ValueError('invalid response_schema_order')
        if response_schema is None and response_schema_order != 'canonical':
            raise ValueError('Declared schema order requires a response schema')
        if response_schema is not None:
            from .response_schema import canonicalize_schema, validated_wire_schema
            if response_format != 'strict_json' or allow_cloud or external_execution:
                raise ValueError('Response schema requires local strict_json execution')
            response_schema = (validated_wire_schema(response_schema) if response_schema_order == 'declared'
                               else canonicalize_schema(response_schema))
        try:
            canonical_agent = canonical_agent_id(agent)
        except RegistryError as exc:
            raise ValueError(str(exc)) from exc
        p = PRIORITIES.get(priority, 50) if isinstance(priority, str) else max(0, min(100, int(priority)))
        role = model_role.lower()
        if role not in {"auto", "fast", "deep", "embedding", "evaluator"}: raise ValueError("invalid model_role")
        job_cap = min(max(0.0, float(max_cost_usd)), self.policy.max_job_cost_usd)
        status = "queued"
        approval = "not_required"  # retained database column; never a prerequisite
        jid, ts = str(uuid.uuid4()), utcnow()
        with self.lock, self.connect() as c:
            if self.policy.coordinated:
                c.execute('BEGIN IMMEDIATE')
            if idempotency_key is not None:
                # Serialize competing submissions across independent processes,
                # before reading the key. The binding and job commit atomically.
                if not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                prior=c.execute('SELECT request_sha256,job_id FROM compute_submission_keys WHERE agent=? AND key_sha256=?',(canonical_agent,key_hash)).fetchone()
                if prior:
                    if prior['request_sha256']!=request_hash:raise ValueError('idempotency_key conflicts with an existing request')
                    return dict(c.execute('SELECT * FROM compute_jobs WHERE id=?',(prior['job_id'],)).fetchone())
            if self.policy.coordinated and c.execute("SELECT count(*) FROM compute_jobs WHERE status='queued'").fetchone()[0] >= self.policy.max_waiting_jobs:
                raise ValueError('INFERENCE_QUEUE_FULL')
            c.execute("""INSERT INTO compute_jobs
              (id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,timeout_seconds,max_retries,
               max_cost_usd,allow_cloud,external_execution,status,approval_status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (jid,canonical_agent,prompt,p,role,model.strip(),max(0,int(ram_mb)),max(0,int(vram_mb)),
               max(1,min(86400,int(timeout_seconds))),max(0,min(10,int(max_retries))),job_cap,
               int(allow_cloud),int(external_execution),status,approval,ts,ts))
            self._event(c,jid,"submitted",{"status":status,"priority":p,"approval":approval,"agent":canonical_agent})
            if self.policy.coordinated:
                c.execute("UPDATE compute_jobs SET lifecycle_state='QUEUED',timings_json=? WHERE id=?",
                          (json.dumps({'created_at': time.time(), 'queued_at': time.time()}), jid))
                for phase in ('CREATED', 'VALIDATED', 'QUEUED'):
                    self._event(c, jid, 'lifecycle', {'phase': phase})
            c.execute('UPDATE compute_jobs SET classification=? WHERE id=?',(classification,jid))
            c.execute('UPDATE compute_jobs SET preferred_provider=?,data_classification=?,task_class=? WHERE id=?',(preferred_provider,data_classification,task_class,jid))
            c.execute('UPDATE compute_jobs SET response_format=? WHERE id=?',(response_format,jid))
            if response_schema_order != 'canonical':
                c.execute('UPDATE compute_jobs SET response_schema_order=? WHERE id=?',(response_schema_order,jid))
            if response_schema is not None:
                c.execute('UPDATE compute_jobs SET response_schema=? WHERE id=?',
                          (json.dumps(response_schema,sort_keys=True,separators=(',',':')),jid))
            if harness_envelope is not None:
                c.execute('UPDATE compute_jobs SET harness_envelope=? WHERE id=?',
                          (json.dumps(harness_envelope,sort_keys=True),jid))
            if idempotency_key is not None:
                c.execute('INSERT INTO compute_submission_keys VALUES(?,?,?,?)',(canonical_agent,key_hash,request_hash,jid))
        self.wake.set()
        return self.get(jid)

    def cancel(self,job_id):
        with self.lock,self.connect() as c:
            self.cancel_in_connection(c, job_id)
        self.wake.set()
        return self.get(job_id)

    def cancel_in_connection(self, c, job_id):
        """Keep consumer cancellation and the final shared-job decision atomic."""
        row=c.execute('SELECT status,provider FROM compute_jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise KeyError(job_id)
        if row['status'] not in TERMINAL:
            c.execute("UPDATE compute_jobs SET status='cancelled',actual_cost_usd=CASE WHEN status='held' THEN 0 ELSE actual_cost_usd END,updated_at=?,completed_at=? WHERE id=?",(utcnow(),utcnow(),job_id))
            if self.policy.coordinated:
                c.execute("UPDATE compute_jobs SET lifecycle_state='CANCELLED' WHERE id=?", (job_id,))
            self._event(c,job_id,'cancelled',{'reason':'client cancellation'})

    def abort(self, job_id: str, error: str) -> dict:
        """Mark a deadline-exceeded local job terminal without an executor claim."""
        with self.lock, self.connect() as c:
            row = c.execute("SELECT status FROM compute_jobs WHERE id=?", (job_id,)).fetchone()
            if not row: raise KeyError(job_id)
            if row["status"] == "running":
                ts = utcnow()
                c.execute("UPDATE compute_jobs SET status='failed',error=?,lease_until=CASE WHEN local_inflight=1 THEN lease_until ELSE NULL END,cloud_inflight=0,updated_at=?,completed_at=? WHERE id=?",
                          (error, ts, ts, job_id))
                self._event(c, job_id, "aborted_deadline", {"error": error})
                if self.policy.coordinated:
                    c.execute("UPDATE compute_jobs SET lifecycle_state='TIMED_OUT' WHERE id=?", (job_id,))
        self.wake.set()
        return self.get(job_id)

    def approve(self, job_id: str, decision: str, actor: str, reason: str = "") -> dict:
        decision = decision.lower()
        if decision not in {"approved", "rejected"}: raise ValueError("decision must be approved or rejected")
        with self.lock, self.connect() as c:
            row=c.execute("SELECT status FROM compute_jobs WHERE id=?",(job_id,)).fetchone()
            if not row: raise KeyError(job_id)
            if row["status"] != "awaiting_approval": raise ValueError("job is not awaiting approval")
            status="queued" if decision == "approved" else "cancelled"
            ts=utcnow()
            c.execute("UPDATE compute_jobs SET status=?,approval_status=?,approval_reason=?,updated_at=?,completed_at=? WHERE id=?",
                      (status,decision,reason,ts,ts if status=="cancelled" else None,job_id))
            c.execute("INSERT INTO compute_approvals VALUES(?,?,?,?,?,?)",
                      (str(uuid.uuid4()),job_id,decision,actor,reason,ts))
            self._event(c,job_id,"approval_decision",{"decision":decision,"actor":actor,"reason":reason})
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self.connect() as c: row=c.execute("SELECT * FROM compute_jobs WHERE id=?",(job_id,)).fetchone()
        if not row: raise KeyError(job_id)
        return dict(row)

    def update_progress(self, job_id: str, result: str) -> bool:
        """Expose bounded partial model output while a job remains running."""
        if not isinstance(result, str) or len(result) > 128000:
            return False
        with self.lock, self.connect() as c:
            changed=c.execute(
                "UPDATE compute_jobs SET result=?,updated_at=? WHERE id=? AND status='running'",
                (result,utcnow(),job_id),
            ).rowcount
        return changed==1

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        with self.connect() as c:
            if status: rows=c.execute("SELECT * FROM compute_jobs WHERE status=? ORDER BY priority DESC,created_at LIMIT ?",(status,min(limit,500))).fetchall()
            else: rows=c.execute("SELECT * FROM compute_jobs ORDER BY created_at DESC LIMIT ?",(min(limit,500),)).fetchall()
        return [dict(r) for r in rows]

    def _daily_spend(self, c: sqlite3.Connection) -> float:
        row=c.execute("SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) FROM compute_jobs WHERE julianday(completed_at)>=julianday('now','-1 day')").fetchone()
        return float(row[0] or 0)

    @staticmethod
    def estimate_cost(row: sqlite3.Row, provider: Provider) -> float:
        estimated_input=max(1,len(row["prompt"].encode())+16)
        estimated_output=provider.max_output_tokens
        try:
            exact=(Decimal(provider.maximum_charge_usd) if provider.maximum_charge_usd is not None else
                   (Decimal(estimated_input)*Decimal(str(provider.input_cost_per_mtok))
                   +Decimal(estimated_output)*Decimal(str(provider.output_cost_per_mtok)))/Decimal(1_000_000))
            if not exact.is_finite() or exact < 0:
                return math.inf
            reserved=float(exact)
            if not math.isfinite(reserved):
                return math.inf
            # SQLite stores REAL. Persist an upper bound so the protected
            # provider admission never sees less than the queue reserved.
            if Decimal(str(reserved)) < exact:
                reserved=math.nextafter(reserved, math.inf)
            if Decimal(str(reserved)) < exact:
                return math.inf
            return reserved
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return math.inf

    def reserve_cloud_chain(self, *, agent: str, requests: list[dict],
                            timeout_seconds: float, binding: dict,
                            task_class: str = 'classification') -> list[dict]:
        """Atomically hold at most two trusted requests before any disclosure.

        Held jobs are invisible to ordinary workers. Their caps count against
        daily admission; only a targeted claim can dispatch one. A never-claimed
        hold expires unspent, whereas running/ambiguous work retains its cap.
        """
        actor = canonical_agent_id(agent)
        if actor != agent or actor == 'prime' or not 1 <= len(requests) <= 2:
            raise ValueError('invalid cloud reservation identity')
        if task_class not in {'classification', 'question_answering'}:
            raise ValueError('invalid cloud reservation task scope')
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
            raise ValueError('invalid cloud reservation timeout')
        prepared = []
        from .tier_router import classify_for_cloud
        for request in requests:
            provider, prompt = request['provider'], request['prompt']
            cap = Decimal(str(request['max_cost_usd']))
            if (provider.kind != 'cloud' or not classify_for_cloud('CLOUD_PERMITTED', prompt)
                    or not cap.is_finite() or not 0 < cap <= Decimal(str(self.policy.max_job_cost_usd))):
                raise ValueError('invalid cloud reservation scope or cap')
            estimate = self.estimate_cost({'prompt': prompt}, provider)
            if Decimal(str(estimate)) > cap:
                raise ValueError('cloud reservation cap is insufficient')
            prepared.append((str(uuid.uuid4()), provider, prompt, float(cap), estimate))
        with self.lock, self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM compute_events WHERE event_type='cloud_reserved' AND json_extract(details_json,'$.parent_task_id')=? LIMIT 1",
                         (binding.get('parent_task_id'),)).fetchone():
                raise ValueError('cloud request already reserved')
            reserved = c.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM compute_jobs WHERE status IN ('running','held')").fetchone()[0]
            if self._daily_spend(c) + reserved + sum(item[4] for item in prepared) > self.policy.daily_cost_ceiling_usd:
                raise ValueError('daily cloud cost ceiling reached')
            ts = utcnow()
            for jid, provider, prompt, cap, estimate in prepared:
                c.execute("""INSERT INTO compute_jobs
                    (id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,timeout_seconds,max_retries,
                     max_cost_usd,allow_cloud,external_execution,status,approval_status,provider,
                     estimated_cost_usd,actual_cost_usd,lease_until,created_at,updated_at,
                     preferred_provider,data_classification,task_class)
                    VALUES(?,?,?,50,'deep',?,0,0,?,0,?,1,0,'held','not_required',?, ?,NULL,?,?,?,?,'CLOUD_PERMITTED',?)""",
                    (jid, actor, prompt, provider.model, timeout_seconds, cap, provider.name,
                     estimate, time.time() + timeout_seconds + 30, ts, ts, provider.name, task_class))
                self._event(c, jid, 'cloud_reserved', binding)
        return [self.get(item[0]) for item in prepared]

    def _route(self, c: sqlite3.Connection, row: sqlite3.Row, providers: list[Provider], *, direct_local=False) -> tuple[Provider | None,str,float]:
        local_names={p.name for p in providers if p.kind=="local"}
        if row['preferred_provider']:
            providers=[p for p in providers if p.name==row['preferred_provider']]
        if direct_local:
            # Direct requests share the existing local model service. Its own
            # one-resident-model / one-inference configuration owns physical
            # scheduling. Legacy journal admission must not starve an Owner
            # request while a coaching session immediately submits its next job.
            # Keep per-request model/memory requirements and cloud cost rules.
            for p in providers:
                if p.kind!='local' or p.concurrency<1:continue
                if row['ram_mb']>min(p.ram_mb,self.policy.local_ram_mb):continue
                if row['vram_mb']>min(p.vram_mb,self.policy.local_vram_mb):continue
                if row['model'] and row['model']!=p.model:continue
                if not row['model'] and row['model_role']!='auto' and not p.name.endswith('-'+row['model_role']):continue
                return p,'direct local request; model service owns inference scheduling',0
        active=c.execute("SELECT provider,agent,ram_mb,vram_mb,priority,cloud_inflight FROM compute_jobs WHERE status='running' OR cloud_inflight=1 OR local_inflight=1").fetchall()
        if len(active)>=self.policy.global_concurrency:return None,"global concurrency limit",0
        def identity(value: str) -> str:
            try: return canonical_agent_id(value)
            except RegistryError: return value
        if sum(1 for x in active if identity(x["agent"])==row["agent"])>=self.policy.per_agent_concurrency:return None,"per-agent concurrency limit",0
        used_ram=sum(int(x["ram_mb"]) for x in active if x["provider"] in local_names)
        used_vram=sum(int(x["vram_mb"]) for x in active if x["provider"] in local_names)
        # Reserve a worker for Owner-critical work, regardless of whether the
        # other workers are executing local or cloud jobs. A cloud fallback
        # must not bypass the reserve after local capacity is exhausted.
        background_at_limit=(self.policy.background_concurrency>0 and
            row["priority"]<PRIORITIES["critical"] and
            sum(1 for x in active if x["priority"]<PRIORITIES["critical"])
            >=self.policy.background_concurrency)
        if background_at_limit:return None,"owner inference reserve",0
        local=[]
        for p in providers:
            if p.kind!="local":continue
            if sum(1 for x in active if x["provider"]==p.name)>=p.concurrency:continue
            if row["ram_mb"]+used_ram>min(p.ram_mb,self.policy.local_ram_mb):continue
            if row["vram_mb"]+used_vram>min(p.vram_mb,self.policy.local_vram_mb):continue
            if row["model"] and row["model"]!=p.model:continue
            if not row["model"] and row["model_role"]!="auto" and not p.name.endswith("-"+row["model_role"]):continue
            local.append(p)
        if local:return local[0],"local capacity available",0
        if not row["allow_cloud"]:
            return None,"local capacity unavailable; cloud not permitted",0
        from .tier_router import classify_for_cloud
        if not classify_for_cloud(row['data_classification'],row['prompt']):return None,'data locality excludes cloud',0
        waited=max(0,time.time()-datetime.fromisoformat(row["created_at"]).timestamp())
        hard_need=row["vram_mb"]>self.policy.local_vram_mb or bool(row["model"] and not any(p.model==row["model"] for p in providers if p.kind=="local"))
        if not hard_need and waited<self.policy.cloud_wait_seconds:return None,"waiting for local capacity before cloud fallback",0
        for p in providers:
            if p.kind!="cloud":continue
            if sum(1 for x in active if x['cloud_inflight'] or x['provider'] not in local_names) >= self.policy.cloud_concurrency:
                return None,"cloud request capacity limit",0
            if p.explicit_selection_required and row['preferred_provider'] != p.name:continue
            if sum(1 for x in active if x["provider"]==p.name)>=p.concurrency:continue
            if row["model"] and row["model"]!=p.model:continue
            if not row["model"] and row["model_role"] not in {"auto","deep"}:continue
            estimate=self.estimate_cost(row,p)
            if estimate>row["max_cost_usd"]:return None,"estimated job cost exceeds job ceiling",estimate
            reserved=c.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM compute_jobs WHERE status IN ('running','held') AND id!=?", (row['id'],)).fetchone()[0]
            if self._daily_spend(c)+reserved+estimate>self.policy.daily_cost_ceiling_usd:return None,"daily cloud cost ceiling reached",estimate
            return p,("local VRAM/model insufficient" if hard_need else "local wait threshold exceeded"),estimate
        return None,"no eligible provider",0

    def _effective_priority(self, row: sqlite3.Row, now_epoch: float) -> float:
        """Age noncritical work without displacing the Owner-critical lane."""
        if row["priority"] >= PRIORITIES["critical"]:
            return float(PRIORITIES["critical"])
        waited = max(0.0, now_epoch - datetime.fromisoformat(row["created_at"]).timestamp())
        if self.policy.coordinated and waited >= self.policy.starvation_interval_seconds * 6:
            # Bounded aging can eventually outrank a continuous interactive
            # stream; active work is never preempted.
            return 101.0
        intervals = int(waited // self.policy.starvation_interval_seconds)
        boost = min(
            self.policy.starvation_boost_cap,
            intervals * self.policy.starvation_boost_per_interval,
        )
        return float(min(PRIORITIES["critical"] - 1, row["priority"] + boost))

    @traced('queue.claim',{'component':'compute-queue','operation':'claim'})
    def claim(self, worker_id: str, providers: list[Provider], *, held_job_id: str | None = None) -> dict | None:
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            claim_time = time.time()
            if self.policy.coordinated:
                from .home_eco import resource_observation
                if resource_observation()['admission'] in {'WAITING_FOR_CAPACITY', 'INVALID_CONFIGURATION'}:
                    return None
            c.create_function(
                "effective_priority", 2,
                lambda priority, created_at: self._effective_priority(
                    {"priority": priority, "created_at": created_at}, claim_time
                ),
            )
            # Rank the complete queue, then stream rows to bound Python memory.
            # A blocked oldest job must not conceal eligible work in its lane.
            # Equal timestamps must tie-break by insertion order (rowid), never
            # by the random job id, so FIFO scheduling stays deterministic.
            where = "status='queued'" if held_job_id is None else "status='held' AND id=?"
            if self.policy.coordinated:
                where += " AND not_before <= " + str(claim_time)
                where += " AND COALESCE(lifecycle_state,'QUEUED') NOT IN ('PAUSED','BLOCKED')"
            cursor=c.execute("""SELECT * FROM compute_jobs WHERE """ + where + """
                ORDER BY effective_priority(priority,created_at) DESC,
                         priority DESC,created_at,rowid""", () if held_job_id is None else (held_job_id,))
            def candidates():
                while rows := cursor.fetchmany(1000):
                    yield from rows
            for row in candidates():
                if row['status'] == 'held' and row['lease_until'] <= claim_time:
                    continue
                # Revalidate persisted identities under the current registry before
                # admission. Never reinterpret a retired legacy ID as a new role.
                try:
                    canonical = canonical_agent_id(row["agent"])
                except RegistryError:
                    c.execute("UPDATE compute_jobs SET status='failed',error='agent retired or unregistered',updated_at=?,completed_at=? WHERE id=?",
                              (utcnow(), utcnow(), row["id"]))
                    self._event(c, row["id"], "registry_denied", {"agent": row["agent"]})
                    continue
                if canonical != row["agent"]:
                    self._event(c, row["id"], "registry_migrated", {"from": row["agent"], "to": canonical})
                    c.execute("UPDATE compute_jobs SET agent=? WHERE id=?", (canonical, row["id"]))
                    row = c.execute("SELECT * FROM compute_jobs WHERE id=?", (row["id"],)).fetchone()
                provider,reason,estimate=self._route(c,row,providers)
                if not provider:
                    if "cost ceiling" in reason or "job ceiling" in reason:
                        c.execute("UPDATE compute_jobs SET status='budget_blocked',route_reason=?,estimated_cost_usd=?,updated_at=?,completed_at=? WHERE id=?",
                                  (reason,estimate,utcnow(),utcnow(),row["id"]))
                        self._event(c,row["id"],"budget_blocked",{"reason":reason,"estimate":estimate})
                    continue
                ts=utcnow();lease=time.time()+row["timeout_seconds"]+30
                if self.guardian is not None:
                    decision = self.guardian.admit(c, dict(row), provider)
                    if not decision.admitted:
                        continue
                changed=c.execute("""UPDATE compute_jobs SET status='running',provider=?,route_reason=?,estimated_cost_usd=?,
                             actual_cost_usd=NULL,input_tokens=NULL,output_tokens=NULL,
                             lease_until=?,cloud_inflight=?,attempts=attempts+1,started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND status IN ('queued','held')""",
                          (provider.name,reason,estimate,lease,int(provider.kind=='cloud'),ts,ts,row["id"]))
                if changed.rowcount:
                    if self.policy.coordinated:
                        from .home_eco import ExecutionBudget
                        budget = ExecutionBudget.for_job(dict(row))
                        timing = json.loads(row['timings_json'] or '{}')
                        timing.update(admitted_at=claim_time,
                                      queue_wait_seconds=max(0, claim_time-timing.get('queued_at', claim_time)),
                                      budget=asdict(budget))
                        c.execute("UPDATE compute_jobs SET lifecycle_state='ADMITTED',timings_json=?,local_inflight=?,lease_until=?,started_at=? WHERE id=?",
                                  (json.dumps(timing), int(provider.kind == 'local'), claim_time+budget.total+30, ts, row['id']))
                        self._event(c, row['id'], 'lifecycle', {'phase': 'ADMITTED', 'queue_wait_seconds': timing['queue_wait_seconds']})
                    self._event(c,row["id"],"claimed",{"worker":worker_id,"provider":provider.name,"reason":reason})
                    return dict(c.execute("SELECT * FROM compute_jobs WHERE id=?",(row["id"],)).fetchone())
        return None

    @traced('queue.claim',{'component':'compute-queue','operation':'claim-direct'})
    def claim_direct(self, job_id: str, providers: list[Provider]) -> dict | None:
        """Route and start one named job immediately; it never rests queued."""
        if self.policy.coordinated:
            # A caller cannot bypass HOME_ECO priority/admission by choosing a
            # particular ID. The shared worker claims the next eligible job.
            self.wake.set()
            return None
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM compute_jobs WHERE id=? AND status='queued'", (job_id,)).fetchone()
            if row is None:
                return None
            try:
                canonical = canonical_agent_id(row["agent"])
            except RegistryError:
                c.execute("UPDATE compute_jobs SET status='failed',error='agent retired or unregistered',updated_at=?,completed_at=? WHERE id=?",
                          (utcnow(), utcnow(), row["id"]))
                self._event(c, row["id"], "registry_denied", {"agent": row["agent"]})
                return None
            if canonical != row["agent"]:
                self._event(c, row["id"], "registry_migrated", {"from": row["agent"], "to": canonical})
                c.execute("UPDATE compute_jobs SET agent=? WHERE id=?", (canonical, row["id"]))
                row = c.execute("SELECT * FROM compute_jobs WHERE id=?", (row["id"],)).fetchone()
            provider, reason, estimate = self._route(c, row, providers, direct_local=True)
            if not provider:
                if "cost ceiling" in reason or "job ceiling" in reason:
                    c.execute("UPDATE compute_jobs SET status='budget_blocked',route_reason=?,estimated_cost_usd=?,updated_at=?,completed_at=? WHERE id=?",
                              (reason, estimate, utcnow(), utcnow(), row["id"]))
                    self._event(c, row["id"], "budget_blocked", {"reason": reason, "estimate": estimate})
                return None
            ts = utcnow()
            if self.guardian is not None:
                decision = self.guardian.admit(c, dict(row), provider)
                if not decision.admitted:
                    return None
            lease = time.time() + row["timeout_seconds"] + 30
            changed = c.execute("""UPDATE compute_jobs SET status='running',provider=?,route_reason=?,estimated_cost_usd=?,
                             actual_cost_usd=NULL,input_tokens=NULL,output_tokens=NULL,
                             lease_until=?,cloud_inflight=?,attempts=attempts+1,started_at=COALESCE(started_at,?),updated_at=?
                             WHERE id=? AND status='queued'""",
                          (provider.name, reason, estimate, lease, int(provider.kind == 'cloud'), ts, ts, row["id"]))
            if changed.rowcount:
                self._event(c, row["id"], "claimed", {"worker": "direct", "provider": provider.name, "reason": reason})
                return dict(c.execute("SELECT * FROM compute_jobs WHERE id=?", (row["id"],)).fetchone())
        return None

    @traced('queue.finish',{'component':'compute-queue','operation':'finish'})
    def finish(self, job_id: str, *, result: str = "", error: str = "", input_tokens: int = 0,
               output_tokens: int = 0, actual_cost_usd: float = 0.0, retryable: bool = True,
               model_load_ns: int = 0, inference_ns: int = 0,
                inference_receipt: dict | None = None, timing_metrics: dict | None = None) -> dict:
        with self.lock, self.connect() as c:
            row=c.execute("SELECT * FROM compute_jobs WHERE id=?",(job_id,)).fetchone()
            if not row: raise KeyError(job_id)
            if row['status'] == 'cancelled' or (row['cloud_inflight'] and row['status'] in TERMINAL):
                # Only the trusted worker/executor calls finish after its HTTP
                # coroutine and cancellation cleanup have settled. Cancellation
                # itself cannot free a still-running request slot. Unknown remote
                # billing remains reserved; this records client-request cleanup.
                cost = row['actual_cost_usd'] if actual_cost_usd is None else max(0.0, float(actual_cost_usd))
                c.execute("UPDATE compute_jobs SET cloud_inflight=0,local_inflight=0,lease_until=NULL,actual_cost_usd=?,input_tokens=?,output_tokens=?,updated_at=? WHERE id=?",
                          (cost, input_tokens, output_tokens, utcnow(), job_id))
                self._event(c, job_id, 'terminal_cloud_execution_settled', {'cost_usd': cost})
                return dict(c.execute('SELECT * FROM compute_jobs WHERE id=?', (job_id,)).fetchone())
            if row["status"]!="running": raise ValueError("job is not running")
            if self.policy.coordinated:
                timing = json.loads(row['timings_json'] or '{}')
                timing.update(timing_metrics or {})
                timing['execution_finished_at'] = time.time()
                c.execute('UPDATE compute_jobs SET timings_json=? WHERE id=?', (json.dumps(timing), job_id))
            if inference_receipt is not None:
                c.execute('UPDATE compute_jobs SET inference_receipt=? WHERE id=?',
                          (json.dumps(inference_receipt,sort_keys=True,separators=(',',':'),allow_nan=False),job_id))
            cost=None if actual_cost_usd is None else max(0.0,float(actual_cost_usd)); ts=utcnow()
            budget_cost=row['estimated_cost_usd'] if cost is None else cost
            over=budget_cost>row["max_cost_usd"] or self._daily_spend(c)+budget_cost>self.policy.daily_cost_ceiling_usd
            if over: status="budget_blocked"; error=error or "actual cost ceiling reached"
            elif error and retryable and row["attempts"]<=row["max_retries"]: status="queued"
            elif error: status="failed"
            else: status="completed"
            c.execute("""UPDATE compute_jobs SET status=?,result=?,error=?,actual_cost_usd=?,input_tokens=?,output_tokens=?,
                         provider=CASE WHEN ?='queued' THEN NULL ELSE provider END,cloud_inflight=0,local_inflight=0,lease_until=NULL,updated_at=?,completed_at=? WHERE id=?""",
                      (status,result,error,cost,None if input_tokens is None else int(input_tokens),None if output_tokens is None else int(output_tokens),status,ts,ts if status in TERMINAL else None,job_id))
            self._event(c,job_id,status,{"error":error,"cost_usd":cost,"attempt":row["attempts"],
                                       "model_load_ns":model_load_ns,"inference_ns":inference_ns})
            if self.guardian is not None:
                self.guardian.record_outcome(c, dict(row), cost)
            if self.policy.coordinated:
                phase = 'QUEUED' if status == 'queued' else status.upper()
                if error and 'TIMEOUT' in error:
                    phase = 'TIMED_OUT'
                delay = min(120, 5 * 2 ** max(0, row['attempts']-1)) if status == 'queued' else 0
                c.execute('UPDATE compute_jobs SET lifecycle_state=?,not_before=? WHERE id=?',
                          (phase, time.time()+delay, job_id))
                self._event(c, job_id, 'lifecycle', {'phase': phase, 'retry_backoff_seconds': delay})
        # Completion frees capacity immediately for the existing dispatcher;
        # resource deferral must not introduce a polling-sized extra wait.
        self.wake.set()
        return self.get(job_id)

    def recover_expired(self) -> int:
        with self.lock, self.connect() as c:
            if self.policy.coordinated:
                # A dead executor may have persisted a terminal state before
                # releasing ownership. Keep the lease until its finite cleanup
                # deadline; never free an actively executing cancellation early.
                c.execute("UPDATE compute_jobs SET local_inflight=0 WHERE local_inflight=1 AND status IN ('failed','cancelled','completed') AND lease_until IS NOT NULL AND lease_until<?", (time.time(),))
            held=c.execute("SELECT id FROM compute_jobs WHERE status='held' AND lease_until<?", (time.time(),)).fetchall()
            for row in held:
                c.execute("UPDATE compute_jobs SET status='cancelled',actual_cost_usd=0,lease_until=NULL,error='undispatched reservation expired',updated_at=?,completed_at=? WHERE id=?",
                          (utcnow(), utcnow(), row['id']))
                self._event(c, row['id'], 'reservation_expired', {'dispatched': False})
            rows=c.execute("SELECT * FROM compute_jobs WHERE status='running' AND lease_until<?",(time.time(),)).fetchall()
            for row in rows:
                status="queued" if not row['allow_cloud'] and row["attempts"]<=row["max_retries"] else "failed"
                # Worker expiry cannot prove HTTP cleanup. Cloud identity and
                # occupancy survive until its trusted executor actually settles;
                # cost remains unknown/reserved and no replay is authorized.
                c.execute("UPDATE compute_jobs SET status=?,provider=CASE WHEN cloud_inflight=1 THEN provider ELSE NULL END,lease_until=NULL,error='worker lease expired',updated_at=?,completed_at=? WHERE id=?",
                          (status,utcnow(),utcnow() if status=="failed" else None,row["id"]))
                self._event(c,row["id"],"lease_expired",{"next_status":status})
                if self.policy.coordinated and not row['cloud_inflight']:
                    c.execute('UPDATE compute_jobs SET local_inflight=0,lifecycle_state=? WHERE id=?',
                              ('RECOVERING' if status == 'queued' else 'FAILED', row['id']))
        return len(rows) + len(held)

    def requeue_orphaned_local(self, job_ids: list[str], *, reason: str = "worker process restarted") -> int:
        """Requeue named local jobs whose worker process was restarted.

        This is called only with jobs owned by a durable workflow during startup
        recovery. Cloud jobs are never replayed because remote side effects cannot
        be proven absent.
        """
        ids = [str(job_id) for job_id in job_ids if job_id]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.lock, self.connect() as c:
            rows = c.execute(
                f"""SELECT id FROM compute_jobs
                WHERE id IN ({placeholders}) AND status='running'
                  AND allow_cloud=0 AND cloud_inflight=0""",
                tuple(ids),
            ).fetchall()
            for row in rows:
                c.execute(
                    """UPDATE compute_jobs SET status='queued',provider=NULL,lease_until=NULL,
                    error=?,updated_at=?,completed_at=NULL WHERE id=? AND status='running'
                    AND allow_cloud=0 AND cloud_inflight=0""",
                    (reason[:200], utcnow(), row["id"]),
                )
                self._event(c, row["id"], "orphaned_worker_requeued", {"reason": reason[:200]})
        self.wake.set()
        return len(rows)

    def metrics(self) -> dict:
        with self.connect() as c:
            statuses={r[0]:r[1] for r in c.execute("SELECT status,COUNT(*) FROM compute_jobs GROUP BY status")}
            spend=self._daily_spend(c)
            running=[dict(r) for r in c.execute("SELECT id,agent,provider,ram_mb,vram_mb,started_at FROM compute_jobs WHERE status='running'")]
            inflight=[dict(r) for r in c.execute("SELECT id,agent,provider,status,lease_until FROM compute_jobs WHERE cloud_inflight=1")]
            stages=[dict(r) for r in c.execute("SELECT id,agent,lifecycle_state,local_inflight,timings_json FROM compute_jobs WHERE status IN ('queued','running') OR local_inflight=1")]
            oldest=c.execute("SELECT min(created_at) FROM compute_jobs WHERE status='queued'").fetchone()[0]
            resource_guardian = self.guardian.status(c) if self.guardian is not None else {'configured': False}
            resource_estimates = self.guardian.estimates(c) if self.guardian is not None else []
        return {"statuses":statuses,"running":running,"cloud_inflight":inflight,"daily_spend_usd":spend,"policy":asdict(self.policy),
                'inference_lifecycle': stages, 'actual_local_slot_owners': sum(r['local_inflight'] for r in stages),
                'oldest_queued_at': oldest, 'resource_guardian': resource_guardian, 'resource_estimates': resource_estimates}

    def transition(self, job_id: str, phase: str) -> None:
        if not self.policy.coordinated:
            return
        allowed = {'MODEL_LOADING', 'INFERENCING', 'POSTPROCESSING', 'PERSISTING'}
        if phase not in allowed:
            raise ValueError('Invalid execution phase')
        with self.lock, self.connect() as c:
            row = c.execute('SELECT status,lifecycle_state,timings_json FROM compute_jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] != 'running' or row['lifecycle_state'] == phase:
                return
            timing = json.loads(row['timings_json'] or '{}')
            timing[phase.lower()+'_at'] = time.time()
            c.execute('UPDATE compute_jobs SET lifecycle_state=?,timings_json=? WHERE id=?',
                      (phase, json.dumps(timing), job_id))
            self._event(c, job_id, 'lifecycle', {'phase': phase})

    def settle_local(self, job_id: str) -> None:
        """Release ownership only after the executing HTTP coroutine settled."""
        if not self.policy.coordinated:
            return
        with self.lock, self.connect() as c:
            c.execute('UPDATE compute_jobs SET local_inflight=0 WHERE id=?', (job_id,))
        self.wake.set()


class WorkerPool:
    def __init__(self, queue: JobQueue, providers: list[Provider], execute: Callable[[dict,Provider],dict],
                 on_complete: Callable[[str], None] | None = None):
        self.queue,self.providers,self.execute=queue,providers,execute
        self.on_complete=on_complete
        try:
            self.pace=min(60.0,max(0.0,float(os.getenv("ORQEVIA_QUEUE_PACE_SECONDS","0"))))
        except (TypeError,ValueError):
            self.pace=0.0
        try:
            self.deep_spacing=min(300.0,max(0.0,float(os.getenv("ORQEVIA_DEEP_JOB_SPACING_SECONDS","0"))))
        except (TypeError,ValueError):
            self.deep_spacing=0.0
        self.stop_event=threading.Event(); self.threads:list[threading.Thread]=[]

    def start(self) -> None:
        if self.threads:return
        for index in range(self.queue.policy.global_concurrency):
            t=threading.Thread(target=self._run,args=(f"worker-{index+1}",),daemon=True);t.start();self.threads.append(t)
        t=threading.Thread(target=self._reap_loop,args=("reaper",),daemon=True);t.start();self.threads.append(t)

    def _reap_loop(self, name: str) -> None:
        """Independent stale-job reaper: recovers wedged/dead workers even when
        every worker thread is blocked inside a generation."""
        while not self.stop_event.is_set():
            try:
                self.queue.recover_expired()
            except Exception:
                pass
            self.stop_event.wait(15)

    def stop(self) -> None:
        self.stop_event.set()
        self.queue.wake.set()
        for t in self.threads:t.join(timeout=3)
        self.threads=[]

    def _run(self, worker_id: str) -> None:
        while not self.stop_event.is_set():
            self.queue.wake.clear()
            self.queue.recover_expired();job=self.queue.claim(worker_id,self.providers)
            if not job:
                self.queue.wake.wait(5 if self.queue.policy.coordinated else .5)
                continue
            provider=next(p for p in self.providers if p.name==job["provider"])
            if self.deep_spacing>0 and job.get("model_role","") in {"deep","evaluator"}:
                self.stop_event.wait(self.deep_spacing)
            started=time.perf_counter()
            outcome='ERROR'
            with span('agent.job.execute',{'component':'compute-queue','provider':provider.name,
                                          'job_type':job.get('task_class','auto')}) as current:
                try:
                    if self.queue.policy.coordinated:
                        from .home_eco import ExecutionBudget
                        deadline = ExecutionBudget.for_job(job).total
                    else:
                        deadline=max(30,int(job.get("timeout_seconds") or 300))
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future=executor.submit(self.execute,job,provider)
                        try:
                            result=future.result(timeout=deadline+30)
                        except FutureTimeout:
                            self.queue.abort(job["id"],'LOCAL_EXECUTION_TIMEOUT')
                            outcome='TIMEOUT'
                            current.set_attribute('status','TIMEOUT')
                            continue
                    self.queue.transition(job['id'], 'PERSISTING')
                    self.queue.finish(job["id"],**result)
                    outcome='OK'
                    current.set_attribute('status','OK')
                except ValueError:
                    outcome='ALREADY_TERMINAL'
                except Exception as exc:
                    current.set_attribute('status','ERROR')
                    if provider.kind=='cloud':
                        # Unknown billing remains reserved; no blind replay of an
                        # ambiguous external request, and no raw upstream error body.
                        from .provider_runtime import ProviderFailure
                        code=exc.code if isinstance(exc,ProviderFailure) else 'EXTERNAL_EXECUTION_FAILED'
                        try:
                            self.queue.finish(job['id'],error=code,retryable=False,
                                actual_cost_usd=None,input_tokens=None,output_tokens=None)
                        except ValueError:
                            pass
                    else:
                        try:
                            timeout = isinstance(exc, TimeoutError)
                            self.queue.finish(job["id"],error='LOCAL_EXECUTION_TIMEOUT' if timeout else 'LOCAL_EXECUTION_FAILED',retryable=not isinstance(exc,(PermissionError, TimeoutError)))
                        except ValueError:
                            pass
                finally:
                    self.queue.settle_local(job['id'])
                    attributes={'component':'compute-queue','provider':provider.name,
                                'job_type':job.get('task_class','auto'),'status':outcome}
                    record_counter('orqevia.agent.jobs',1,attributes)
                    record_duration('orqevia.agent.job.duration',(time.perf_counter()-started)*1000,attributes)
            # The optional knowledge adapter runs only after the authoritative
            # terminal transaction. Its outage cannot change execution status.
            if self.on_complete is not None:
                try:
                    if self.queue.get(job['id'])['status'] == 'completed':
                        self.on_complete(job['id'])
                except Exception:
                    record_counter('orqevia.collective.publication_failures',1,{'component':'collective-board'})
                    try:
                        with self.queue.lock,self.queue.connect() as connection:
                            self.queue._event(connection,job['id'],'collective_publication_unavailable',{'retry':'bounded_reconciliation'})
                    except Exception:
                        pass
            if self.pace>0:
                self.stop_event.wait(self.pace)
