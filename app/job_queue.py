"""Governed, persistent shared compute queue for all PRIME agents."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent_registry import RegistryError, canonical_agent_id
from . import backend_admission


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
            global_concurrency=integer("PRIME_QUEUE_CONCURRENCY", 1, 1, 29),
            per_agent_concurrency=integer("PRIME_AGENT_CONCURRENCY", 1, 1, 8),
            background_concurrency=integer("PRIME_BACKGROUND_INFERENCE_LIMIT", 0, 0, 29),
            local_ram_mb=integer("PRIME_LOCAL_RAM_MB", 32768, 1024, 1048576),
            local_vram_mb=integer("PRIME_LOCAL_VRAM_MB", 0, 0, 1048576),
            cloud_wait_seconds=integer("PRIME_CLOUD_WAIT_SECONDS", 300, 0, 86400),
            starvation_interval_seconds=integer("PRIME_STARVATION_INTERVAL_SECONDS", 300, 1, 86400),
            starvation_boost_per_interval=integer("PRIME_STARVATION_BOOST", 10, 1, 100),
            starvation_boost_cap=integer("PRIME_STARVATION_BOOST_CAP", 100, 1, 1000),
            max_job_cost_usd=decimal("PRIME_MAX_JOB_COST_USD", 2.0, 0, 10000),
            daily_cost_ceiling_usd=decimal("PRIME_DAILY_COST_USD", 10.0, 0, 100000),
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


class JobQueue:
    """SQLite queue with atomic leases and resource/cost admission control."""

    def __init__(self, db_path: str | Path, policy: QueuePolicy | None = None):
        self.db_path = str(db_path)
        self.policy = policy or QueuePolicy.from_env()
        self.backend_endpoint = os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434').rstrip('/')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self._init()

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
            """)
            # executescript commits implicitly; keep the admission key migration
            # and subsequent column upgrades in one SQLite write transaction.
            c.execute("BEGIN IMMEDIATE")
            backend_admission.init(c)

            if 'classification' not in {r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}:
                c.execute("ALTER TABLE compute_jobs ADD COLUMN classification TEXT DEFAULT 'R0'")
            if 'harness_envelope' not in {r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}:
                c.execute('ALTER TABLE compute_jobs ADD COLUMN harness_envelope TEXT')
            columns={r[1] for r in c.execute('PRAGMA table_info(compute_jobs)')}
            for name,definition in [('preferred_provider','TEXT'),('data_classification',"TEXT DEFAULT 'LOCAL_ONLY'"),('task_class',"TEXT DEFAULT 'auto'"),('response_format',"TEXT DEFAULT 'text'")]:
                if name not in columns:c.execute(f'ALTER TABLE compute_jobs ADD COLUMN {name} {definition}')

    def _event(self, c: sqlite3.Connection, job_id: str | None, event: str, details: dict) -> None:
        c.execute("INSERT INTO compute_events VALUES(?,?,?,?,?)",
                  (str(uuid.uuid4()), job_id, event, json.dumps(details, separators=(",", ":")), utcnow()))

    def submit(self, *, agent: str, prompt: str, priority: str | int = "normal",
               model_role: str = "auto", model: str = "", ram_mb: int = 1024,
               vram_mb: int = 0, timeout_seconds: int = 300, max_retries: int = 2,
               max_cost_usd: float = 0.0, allow_cloud: bool = False,
               external_execution: bool = False, harness_envelope: dict | None = None, classification: str = "R0", preferred_provider: str | None = None, data_classification: str = 'LOCAL_ONLY', task_class: str = 'auto', response_format: str = 'text') -> dict:
        if not agent.strip() or not prompt.strip(): raise ValueError("agent and prompt are required")
        if response_format not in {'text', 'strict_json'}: raise ValueError('invalid response_format')
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
            c.execute("""INSERT INTO compute_jobs
              (id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,timeout_seconds,max_retries,
               max_cost_usd,allow_cloud,external_execution,status,approval_status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (jid,canonical_agent,prompt,p,role,model.strip(),max(0,int(ram_mb)),max(0,int(vram_mb)),
               max(1,min(86400,int(timeout_seconds))),max(0,min(10,int(max_retries))),job_cap,
               int(allow_cloud),int(external_execution),status,approval,ts,ts))
            self._event(c,jid,"submitted",{"status":status,"priority":p,"approval":approval,"agent":canonical_agent})
            c.execute('UPDATE compute_jobs SET classification=? WHERE id=?',(classification,jid))
            c.execute('UPDATE compute_jobs SET preferred_provider=?,data_classification=?,task_class=? WHERE id=?',(preferred_provider,data_classification,task_class,jid))
            c.execute('UPDATE compute_jobs SET response_format=? WHERE id=?',(response_format,jid))
            if harness_envelope is not None:
                c.execute('UPDATE compute_jobs SET harness_envelope=? WHERE id=?',
                          (json.dumps(harness_envelope,sort_keys=True),jid))
        self.wake.set()
        return self.get(jid)

    def cancel(self,job_id):
        with self.lock,self.connect() as c:
            row=c.execute('SELECT status,provider FROM compute_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise KeyError(job_id)
            if row['status'] not in TERMINAL:
                if row['status']=='running':
                    backend_admission.cancel(c,self.backend_endpoint,job_id)
                c.execute("UPDATE compute_jobs SET status='cancelled',updated_at=?,completed_at=? WHERE id=?",(utcnow(),utcnow(),job_id))
                self._event(c,job_id,'cancelled',{'reason':'client cancellation'})
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
            exact=(Decimal(estimated_input)*Decimal(str(provider.input_cost_per_mtok))
                   +Decimal(estimated_output)*Decimal(str(provider.output_cost_per_mtok)))/Decimal(1_000_000)
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

    def _route(self, c: sqlite3.Connection, row: sqlite3.Row, providers: list[Provider],
               *, local_unavailable: bool = False) -> tuple[Provider | None,str,float]:
        local_names={p.name for p in providers if p.kind=="local"}
        if row['preferred_provider']:
            providers=[p for p in providers if p.name==row['preferred_provider']]
        active=c.execute("SELECT provider,agent,ram_mb,vram_mb,priority FROM compute_jobs WHERE status='running'").fetchall()
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
        if local and not local_unavailable:return local[0],"local capacity available",0
        if not row["allow_cloud"]:
            return None,"local capacity unavailable; cloud not permitted",0
        from .tier_router import classify_for_cloud
        if not classify_for_cloud(row['data_classification'],row['prompt']):return None,'data locality excludes cloud',0
        waited=max(0,time.time()-datetime.fromisoformat(row["created_at"]).timestamp())
        hard_need=row["vram_mb"]>self.policy.local_vram_mb or bool(row["model"] and not any(p.model==row["model"] for p in providers if p.kind=="local"))
        if not hard_need and waited<self.policy.cloud_wait_seconds:return None,"waiting for local capacity before cloud fallback",0
        for p in providers:
            if p.kind!="cloud":continue
            if p.explicit_selection_required and row['preferred_provider'] != p.name:continue
            if sum(1 for x in active if x["provider"]==p.name)>=p.concurrency:continue
            if row["model"] and row["model"]!=p.model:continue
            if not row["model"] and row["model_role"] not in {"auto","deep"}:continue
            estimate=self.estimate_cost(row,p)
            if estimate>row["max_cost_usd"]:return None,"estimated job cost exceeds job ceiling",estimate
            reserved=c.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM compute_jobs WHERE status='running'").fetchone()[0]
            if self._daily_spend(c)+reserved+estimate>self.policy.daily_cost_ceiling_usd:return None,"daily cloud cost ceiling reached",estimate
            return p,("local VRAM/model insufficient" if hard_need else "local wait threshold exceeded"),estimate
        return None,"no eligible provider",0

    def _effective_priority(self, row: sqlite3.Row, now_epoch: float) -> float:
        """Age noncritical work without displacing the Owner-critical lane."""
        if row["priority"] >= PRIORITIES["critical"]:
            return float(PRIORITIES["critical"])
        waited = max(0.0, now_epoch - datetime.fromisoformat(row["created_at"]).timestamp())
        intervals = int(waited // self.policy.starvation_interval_seconds)
        boost = min(
            self.policy.starvation_boost_cap,
            intervals * self.policy.starvation_boost_per_interval,
        )
        return float(min(PRIORITIES["critical"] - 1, row["priority"] + boost))

    def claim(self, worker_id: str, providers: list[Provider]) -> dict | None:
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            claim_time = time.time()
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
            cursor=c.execute("""SELECT * FROM compute_jobs WHERE status='queued'
                ORDER BY effective_priority(priority,created_at) DESC,
                         priority DESC,created_at,rowid""")
            def candidates():
                while rows := cursor.fetchmany(1000):
                    yield from rows
            for row in candidates():
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
                if provider.kind=='local':
                    # The SQLite write transaction makes this reservation atomic
                    # with the scheduler claim across workers and processes.
                    try:
                        backend_admission.reserve_model(c,self.backend_endpoint,row['id'],
                                                        provider.model,row['ram_mb'],
                                                        global_concurrency=self.policy.global_concurrency)
                    except PermissionError:
                        provider,reason,estimate=self._route(c,row,providers,local_unavailable=True)
                        if not provider:
                            continue
                changed=c.execute("""UPDATE compute_jobs SET status='running',provider=?,route_reason=?,estimated_cost_usd=?,
                             actual_cost_usd=NULL,input_tokens=NULL,output_tokens=NULL,
                             lease_until=?,attempts=attempts+1,started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND status='queued'""",
                          (provider.name,reason,estimate,lease,ts,ts,row["id"]))
                if changed.rowcount:
                    self._event(c,row["id"],"claimed",{"worker":worker_id,"provider":provider.name,"reason":reason})
                    return dict(c.execute("SELECT * FROM compute_jobs WHERE id=?",(row["id"],)).fetchone())
                if provider.kind=='local':
                    backend_admission.cancel(c,self.backend_endpoint,row['id'])
        return None

    def finish(self, job_id: str, *, result: str = "", error: str = "", input_tokens: int = 0,
               output_tokens: int = 0, actual_cost_usd: float = 0.0, retryable: bool = True,
               model_load_ns: int = 0, inference_ns: int = 0) -> dict:
        with self.lock, self.connect() as c:
            row=c.execute("SELECT * FROM compute_jobs WHERE id=?",(job_id,)).fetchone()
            if not row: raise KeyError(job_id)
            if row["status"]=="cancelled":return dict(row)
            if row["status"]!="running": raise ValueError("job is not running")
            backend_admission.cancel(c,self.backend_endpoint,job_id)
            cost=None if actual_cost_usd is None else max(0.0,float(actual_cost_usd)); ts=utcnow()
            budget_cost=row['estimated_cost_usd'] if cost is None else cost
            over=budget_cost>row["max_cost_usd"] or self._daily_spend(c)+budget_cost>self.policy.daily_cost_ceiling_usd
            if over: status="budget_blocked"; error=error or "actual cost ceiling reached"
            elif error and retryable and row["attempts"]<=row["max_retries"]: status="queued"
            elif error: status="failed"
            else: status="completed"
            c.execute("""UPDATE compute_jobs SET status=?,result=?,error=?,actual_cost_usd=?,input_tokens=?,output_tokens=?,
                         provider=CASE WHEN ?='queued' THEN NULL ELSE provider END,lease_until=NULL,updated_at=?,completed_at=? WHERE id=?""",
                      (status,result,error,cost,None if input_tokens is None else int(input_tokens),None if output_tokens is None else int(output_tokens),status,ts,ts if status in TERMINAL else None,job_id))
            self._event(c,job_id,status,{"error":error,"cost_usd":cost,"attempt":row["attempts"],
                                       "model_load_ns":model_load_ns,"inference_ns":inference_ns})
        return self.get(job_id)

    def recover_expired(self) -> int:
        with self.lock, self.connect() as c:
            rows=c.execute("SELECT * FROM compute_jobs WHERE status='running' AND lease_until<?",(time.time(),)).fetchall()
            for row in rows:
                backend_admission.cancel(c,self.backend_endpoint,row['id'])
                status="queued" if not row['allow_cloud'] and row["attempts"]<=row["max_retries"] else "failed"
                c.execute("UPDATE compute_jobs SET status=?,provider=NULL,lease_until=NULL,error='worker lease expired',updated_at=?,completed_at=? WHERE id=?",
                          (status,utcnow(),utcnow() if status=="failed" else None,row["id"]))
                self._event(c,row["id"],"lease_expired",{"next_status":status})
        return len(rows)

    def metrics(self) -> dict:
        with self.connect() as c:
            statuses={r[0]:r[1] for r in c.execute("SELECT status,COUNT(*) FROM compute_jobs GROUP BY status")}
            spend=self._daily_spend(c)
            running=[dict(r) for r in c.execute("SELECT id,agent,provider,ram_mb,vram_mb,started_at FROM compute_jobs WHERE status='running'")]
        return {"statuses":statuses,"running":running,"daily_spend_usd":spend,"policy":asdict(self.policy)}


class WorkerPool:
    def __init__(self, queue: JobQueue, providers: list[Provider], execute: Callable[[dict,Provider],dict]):
        self.queue,self.providers,self.execute=queue,providers,execute
        self.stop_event=threading.Event(); self.threads:list[threading.Thread]=[]

    def start(self) -> None:
        if self.threads:return
        for index in range(self.queue.policy.global_concurrency):
            t=threading.Thread(target=self._run,args=(f"worker-{index+1}",),daemon=True);t.start();self.threads.append(t)

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
                self.queue.wake.wait(.5)
                continue
            provider=next(p for p in self.providers if p.name==job["provider"])
            try:
                job['_admission_db'] = self.queue.db_path
                self.queue.finish(job["id"],**self.execute(job,provider))
            except Exception as exc:
                if provider.kind=='cloud':
                    # Unknown billing remains reserved; no blind replay of an
                    # ambiguous external request, and no raw upstream error body.
                    from .provider_runtime import ProviderFailure
                    code=exc.code if isinstance(exc,ProviderFailure) else 'EXTERNAL_EXECUTION_FAILED'
                    self.queue.finish(job['id'],error=code,retryable=False,
                        actual_cost_usd=None,input_tokens=None,output_tokens=None)
                else:
                    self.queue.finish(job["id"],error='LOCAL_EXECUTION_FAILED',retryable=not isinstance(exc,PermissionError))
