"""Crash-hygiene: a backend inference lease whose holder job is terminal must
be reclaimable at claim time (16 October 2026 stall: orphaned 'uncertain'
lease held by a failed job silently refused every claim)."""
import sqlite3

from app.job_queue import JobQueue, QueuePolicy

DDL = """
CREATE TABLE IF NOT EXISTS backend_admission(
    endpoint TEXT NOT NULL, job_id TEXT NOT NULL, instance TEXT DEFAULT '',
    boot_id TEXT DEFAULT '', state TEXT NOT NULL, demand_mib INTEGER NOT NULL,
    refresh_after REAL NOT NULL, dispatched_at REAL NOT NULL, max_leases INTEGER NOT NULL,
    PRIMARY KEY(endpoint, job_id)
)
"""


def _queue(tmp_path):
    queue = JobQueue(tmp_path / "queue.db", QueuePolicy())
    with queue.connect() as c:
        c.execute(DDL)
        c.execute(
            "INSERT OR IGNORE INTO compute_jobs(id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,"
            "timeout_seconds,max_retries,attempts,max_cost_usd,allow_cloud,external_execution,status,"
            "approval_status,created_at,updated_at) VALUES('failed-job','a01','p',100,'auto','gemma3:1b',"
            "512,0,300,0,0,0,0,0,'failed','not_required','t','t')"
        )
        c.execute(
            "INSERT OR IGNORE INTO compute_jobs(id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,"
            "timeout_seconds,max_retries,attempts,max_cost_usd,allow_cloud,external_execution,status,"
            "approval_status,created_at,updated_at) VALUES('running-job','a01','p',100,'auto','gemma3:1b',"
            "512,0,300,0,0,0,0,0,'running','not_required','t','t')"
        )
        c.execute("INSERT OR IGNORE INTO backend_admission VALUES('http://ollama:11434','failed-job','','','uncertain',512,0,1.0,1)")
        c.execute("INSERT OR IGNORE INTO backend_admission VALUES('http://ollama:11434','running-job','','','held',512,0,2.0,1)")
        c.commit()
    return queue


def test_terminal_holder_lease_is_reclaimed_running_holder_is_kept(tmp_path):
    queue = _queue(tmp_path)
    with queue.connect() as c:
        queue._reclaim_terminal_leases(c)
        c.commit()
        remaining = {row[0] for row in c.execute("SELECT job_id FROM backend_admission")}
    assert remaining == {"running-job"}


def test_unknown_holder_lease_is_reclaimed(tmp_path):
    queue = _queue(tmp_path)
    with queue.connect() as c:
        c.execute("INSERT OR IGNORE INTO backend_admission VALUES('http://ollama:11434','ghost-job','','','uncertain',512,0,3.0,1)")
        queue._reclaim_terminal_leases(c)
        c.commit()
        remaining = {row[0] for row in c.execute("SELECT job_id FROM backend_admission")}
    assert "ghost-job" not in remaining
