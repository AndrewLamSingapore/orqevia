"""Governed, persistent shared compute queue for all PRIME agents."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent_registry import RegistryError, canonical_agent_id


TERMINAL = {"completed", "failed", "cancelled", "budget_blocked"}
PRIORITIES = {"background": 10, "low": 25, "normal": 50, "high": 75, "critical": 100}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueuePolicy:
    # The current Dell-class local host is intentionally conservative: two
    # concurrent jobs is the default ceiling unless the owner explicitly tunes it.
    global_concurrency: int = 2
    per_agent_concurrency: int = 1
    local_ram_mb: int = 32768
    local_vram_mb: int = 0
    cloud_wait_seconds: int = 300
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
            global_concurrency=integer("PRIME_QUEUE_CONCURRENCY", 2, 1, 29),
            per_agent_concurrency=integer("PRIME_AGENT_CONCURRENCY", 1, 1, 8),
            local_ram_mb=integer("PRIME_LOCAL_RAM_MB", 32768, 1024, 1048576),
            local_vram_mb=integer("PRIME_LOCAL_VRAM_MB", 0, 0, 1048576),
            cloud_wait_seconds=integer("PRIME_CLOUD_WAIT_SECONDS", 300, 0, 86400),
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


class JobQueue:
    """SQLite queue with atomic leases and resource/cost admission control."""

    def __init__(self, db_path: str | Path, policy: QueuePolicy | None = None):
        self.db_path = str(db_path)
        self.policy = policy or QueuePolicy.from_env()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._init()

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=20, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        return c

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

    def _event(self, c: sqlite3.Connection, job_id: str | None, event: str, details: dict) -> None:
        c.execute("INSERT INTO compute_events VALUES(?,?,?,?,?)",
                  (str(uuid.uuid4()), job_id, event, json.dumps(details, separators=(",", ":")), utcnow()))

    def submit(self, *, agent: str, prompt: str, priority: str | int = "normal",
               model_role: str = "auto", model: str = "", ram_mb: int = 1024,
               vram_mb: int = 0, timeout_seconds: int = 300, max_retries: int = 2,
               max_cost_usd: float = 0.0, allow_cloud: bool = False,
               external_execution: bool = False) -> dict:
        if not agent.strip() or not prompt.strip(): raise ValueError("agent and prompt are required")
        try:
            canonical_agent = canonical_agent_id(agent)
        except RegistryError as exc:
            raise ValueError(str(exc)) from exc
        p = PRIORITIES.get(priority, 50) if isinstance(priority, str) else max(0, min(100, int(priority)))
        role = model_role.lower()
        if role not in {"auto", "fast", "deep", "embedding", "evaluator"}: raise ValueError("invalid model_role")
        job_cap = min(max(0.0, float(max_cost_usd)), self.policy.max_job_cost_usd)
        needs_approval = bool(external_execution or allow_cloud)
        status = "awaiting_approval" if needs_approval else "queued"
        approval = "pending" if needs_approval else "not_required"
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
        return self.get(jid)

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
        row=c.execute("SELECT COALESCE(SUM(actual_cost_usd),0) FROM compute_jobs WHERE completed_at>=datetime('now','-1 day')").fetchone()
        return float(row[0] or 0)

    @staticmethod
    def estimate_cost(row: sqlite3.Row, provider: Provider) -> float:
        estimated_input=max(1,len(row["prompt"])//4)
        estimated_output=max(128,min(4096,estimated_input//2))
        return (estimated_input*provider.input_cost_per_mtok + estimated_output*provider.output_cost_per_mtok)/1_000_000

    def _route(self, c: sqlite3.Connection, row: sqlite3.Row, providers: list[Provider]) -> tuple[Provider | None,str,float]:
        active=c.execute("SELECT provider,agent,ram_mb,vram_mb FROM compute_jobs WHERE status='running'").fetchall()
        if len(active)>=self.policy.global_concurrency:return None,"global concurrency limit",0
        if sum(1 for x in active if x["agent"]==row["agent"])>=self.policy.per_agent_concurrency:return None,"per-agent concurrency limit",0
        local_names={p.name for p in providers if p.kind=="local"}
        used_ram=sum(int(x["ram_mb"]) for x in active if x["provider"] in local_names)
        used_vram=sum(int(x["vram_mb"]) for x in active if x["provider"] in local_names)
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
        if not row["allow_cloud"]:return None,"local capacity unavailable; cloud not permitted",0
        if row["approval_status"]!="approved":return None,"cloud approval required",0
        waited=max(0,time.time()-datetime.fromisoformat(row["created_at"]).timestamp())
        hard_need=row["vram_mb"]>self.policy.local_vram_mb or bool(row["model"] and not any(p.model==row["model"] for p in providers if p.kind=="local"))
        if not hard_need and waited<self.policy.cloud_wait_seconds:return None,"waiting for local capacity before cloud fallback",0
        for p in providers:
            if p.kind!="cloud":continue
            if sum(1 for x in active if x["provider"]==p.name)>=p.concurrency:continue
            if row["model"] and row["model"]!=p.model:continue
            if not row["model"] and row["model_role"] not in {"auto","deep"}:continue
            estimate=self.estimate_cost(row,p)
            if estimate>row["max_cost_usd"]:return None,"estimated job cost exceeds job ceiling",estimate
            if self._daily_spend(c)+estimate>self.policy.daily_cost_ceiling_usd:return None,"daily cloud cost ceiling reached",estimate
            return p,("local VRAM/model insufficient" if hard_need else "local wait threshold exceeded"),estimate
        return None,"no eligible provider",0

    def claim(self, worker_id: str, providers: list[Provider]) -> dict | None:
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("SELECT * FROM compute_jobs WHERE status='queued' ORDER BY priority DESC,created_at LIMIT 100").fetchall()
            for row in rows:
                provider,reason,estimate=self._route(c,row,providers)
                if not provider:
                    if "cost ceiling" in reason or "job ceiling" in reason:
                        c.execute("UPDATE compute_jobs SET status='budget_blocked',route_reason=?,estimated_cost_usd=?,updated_at=?,completed_at=? WHERE id=?",
                                  (reason,estimate,utcnow(),utcnow(),row["id"]))
                        self._event(c,row["id"],"budget_blocked",{"reason":reason,"estimate":estimate})
                    continue
                ts=utcnow();lease=time.time()+row["timeout_seconds"]+30
                changed=c.execute("""UPDATE compute_jobs SET status='running',provider=?,route_reason=?,estimated_cost_usd=?,
                             lease_until=?,attempts=attempts+1,started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND status='queued'""",
                          (provider.name,reason,estimate,lease,ts,ts,row["id"]))
                if changed.rowcount:
                    self._event(c,row["id"],"claimed",{"worker":worker_id,"provider":provider.name,"reason":reason})
                    return dict(c.execute("SELECT * FROM compute_jobs WHERE id=?",(row["id"],)).fetchone())
        return None

    def finish(self, job_id: str, *, result: str = "", error: str = "", input_tokens: int = 0,
               output_tokens: int = 0, actual_cost_usd: float = 0.0) -> dict:
        with self.lock, self.connect() as c:
            row=c.execute("SELECT * FROM compute_jobs WHERE id=?",(job_id,)).fetchone()
            if not row: raise KeyError(job_id)
            if row["status"]!="running": raise ValueError("job is not running")
            cost=max(0.0,float(actual_cost_usd)); ts=utcnow()
            over=cost>row["max_cost_usd"] or self._daily_spend(c)+cost>self.policy.daily_cost_ceiling_usd
            if over: status="budget_blocked"; error=error or "actual cost ceiling reached"
            elif error and row["attempts"]<=row["max_retries"]: status="queued"
            elif error: status="failed"
            else: status="completed"
            c.execute("""UPDATE compute_jobs SET status=?,result=?,error=?,actual_cost_usd=?,input_tokens=?,output_tokens=?,
                         provider=CASE WHEN ?='queued' THEN NULL ELSE provider END,lease_until=NULL,updated_at=?,completed_at=? WHERE id=?""",
                      (status,result,error,cost,int(input_tokens),int(output_tokens),status,ts,ts if status in TERMINAL else None,job_id))
            self._event(c,job_id,status,{"error":error,"cost_usd":cost,"attempt":row["attempts"]})
        return self.get(job_id)

    def recover_expired(self) -> int:
        with self.lock, self.connect() as c:
            rows=c.execute("SELECT * FROM compute_jobs WHERE status='running' AND lease_until<?",(time.time(),)).fetchall()
            for row in rows:
                status="queued" if row["attempts"]<=row["max_retries"] else "failed"
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
        for t in self.threads:t.join(timeout=3)
        self.threads=[]

    def _run(self, worker_id: str) -> None:
        while not self.stop_event.wait(.5):
            self.queue.recover_expired();job=self.queue.claim(worker_id,self.providers)
            if not job:continue
            provider=next(p for p in self.providers if p.name==job["provider"])
            try:self.queue.finish(job["id"],**self.execute(job,provider))
            except Exception as exc:self.queue.finish(job["id"],error=f"{type(exc).__name__}: {exc}"[:2000])
