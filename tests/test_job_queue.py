import time
from app.job_queue import JobQueue, Provider, QueuePolicy

LOCAL=Provider("ollama","local","fast",8192,4096,2)
CLOUD=Provider("gpu-cloud","cloud","large",131072,81920,4,1.0,2.0)

def queue(tmp_path,**kw):
    p=QueuePolicy(global_concurrency=kw.get("global",2),per_agent_concurrency=1,local_ram_mb=8192,
                  local_vram_mb=4096,cloud_wait_seconds=0,max_job_cost_usd=2,daily_cost_ceiling_usd=3)
    return JobQueue(tmp_path/"q.db",p)

def test_priority_and_agent_concurrency(tmp_path):
    q=queue(tmp_path)
    low=q.submit(agent="planner",prompt="low",priority="low")
    high=q.submit(agent="critic",prompt="high",priority="critical")
    same=q.submit(agent="critic",prompt="same agent",priority="high")
    assert low["agent"] == "A02"
    assert high["agent"] == "A27"
    assert q.claim("w1",[LOCAL])["id"]==high["id"]
    assert q.claim("w2",[LOCAL])["id"]==low["id"]
    assert q.get(same["id"])["status"]=="queued"

def test_unknown_agent_is_rejected(tmp_path):
    q=queue(tmp_path)
    try:
        q.submit(agent="free-form-unregistered-agent",prompt="work")
    except ValueError as exc:
        assert "unregistered agent identity" in str(exc)
    else:
        raise AssertionError("unregistered compute agent must fail closed")

def test_cloud_is_approval_gated_and_only_fallback(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="analyst",prompt="large",model="large",vram_mb=8000,allow_cloud=True,max_cost_usd=1)
    assert job["status"]=="awaiting_approval"
    assert q.claim("w",[LOCAL,CLOUD]) is None
    q.approve(job["id"],"approved","owner","large model required")
    claimed=q.claim("w",[LOCAL,CLOUD])
    assert claimed["provider"]=="gpu-cloud"
    assert claimed["route_reason"]=="local VRAM/model insufficient"

def test_rejection_cancels_and_is_audited(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="research",prompt="external",external_execution=True)
    out=q.approve(job["id"],"rejected","owner","not authorized")
    assert out["status"]=="cancelled"

def test_retry_then_failure(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="coding",prompt="work",max_retries=1)
    q.claim("w",[LOCAL]); assert q.finish(job["id"],error="boom")["status"]=="queued"
    q.claim("w",[LOCAL]); assert q.finish(job["id"],error="boom again")["status"]=="failed"

def test_job_cost_ceiling_blocks_cloud(tmp_path):
    q=queue(tmp_path)
    expensive=Provider("expensive","cloud","large",131072,81920,2,10000,10000)
    job=q.submit(agent="analyst",prompt="x"*10000,model="large",vram_mb=8000,allow_cloud=True,max_cost_usd=.01)
    q.approve(job["id"],"approved","owner")
    assert q.claim("w",[LOCAL,expensive]) is None
    assert q.get(job["id"])["status"]=="budget_blocked"
