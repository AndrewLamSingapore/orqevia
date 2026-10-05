import time
import pytest
from app import backend_admission
from app.job_queue import JobQueue, Provider, QueuePolicy


@pytest.fixture(autouse=True)
def scheduler_only_without_backend_allocation(monkeypatch):
    # These tests prove queue order/budgets, including hypothetical N>1 policy.
    # Backend allocation is separately exercised by test_backend_admission.
    monkeypatch.setattr(backend_admission, 'reserve_model', lambda *_args, **_kw: None)

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
    assert low["agent"] == "a02"
    assert high["agent"] == "a26"
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

def test_cloud_is_direct_and_only_fallback(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="analyst",prompt="large",model="large",vram_mb=8000,allow_cloud=True,
                 data_classification="CLOUD_PERMITTED",max_cost_usd=1)
    assert job["status"]=="queued"
    assert job["approval_status"]=="not_required"
    claimed=q.claim("w",[LOCAL,CLOUD])
    assert claimed["provider"]=="gpu-cloud"
    assert claimed["route_reason"]=="local VRAM/model insufficient"

def test_operational_cancellation_is_audited(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="research",prompt="external",external_execution=True)
    out=q.cancel(job["id"])
    assert out["status"]=="cancelled"

def test_retry_then_failure(tmp_path):
    q=queue(tmp_path)
    job=q.submit(agent="coding",prompt="work",max_retries=1)
    q.claim("w",[LOCAL]); assert q.finish(job["id"],error="boom")["status"]=="queued"
    q.claim("w",[LOCAL]); assert q.finish(job["id"],error="boom again")["status"]=="failed"

def test_job_cost_ceiling_blocks_cloud(tmp_path):
    q=queue(tmp_path)
    expensive=Provider("expensive","cloud","large",131072,81920,2,10000,10000)
    job=q.submit(agent="analyst",prompt="x"*10000,model="large",vram_mb=8000,allow_cloud=True,
                 data_classification="CLOUD_PERMITTED",max_cost_usd=.01)
    assert q.claim("w",[LOCAL,expensive]) is None
    assert q.get(job["id"])["status"]=="budget_blocked"

def test_persisted_legacy_jobs_migrate_semantically_and_retired_jobs_fail(tmp_path):
    q=queue(tmp_path)
    retired=q.submit(agent='planner',prompt='retired job',priority='critical')
    preserved=q.submit(agent='architecture',prompt='existing architecture job')
    with q.connect() as db:
        db.execute('UPDATE compute_jobs SET agent=? WHERE id=?', ('A10', retired['id']))
        db.execute('UPDATE compute_jobs SET agent=? WHERE id=?', ('A17', preserved['id']))
    claimed=q.claim('w', [LOCAL])
    assert claimed['id']==preserved['id']
    assert claimed['agent']=='a16'
    assert q.get(retired['id'])['status']=='failed'
    with q.connect() as db:
        events={r[0] for r in db.execute('SELECT event_type FROM compute_events')}
    assert {'registry_denied','registry_migrated'}.issubset(events)


def test_harness_v0_defaults_to_one_local_inference_job(monkeypatch):
    monkeypatch.delenv("PRIME_QUEUE_CONCURRENCY", raising=False)
    assert QueuePolicy.from_env().global_concurrency == 1


def test_old_low_priority_job_ages_out_of_starvation(tmp_path):
    policy = QueuePolicy(
        global_concurrency=1,
        per_agent_concurrency=1,
        local_ram_mb=8192,
        local_vram_mb=4096,
        cloud_wait_seconds=0,
        starvation_interval_seconds=1,
        starvation_boost_per_interval=10,
        starvation_boost_cap=100,
        max_job_cost_usd=2,
        daily_cost_ceiling_usd=3,
    )
    q = JobQueue(tmp_path / "fair.db", policy)
    old = q.submit(agent="planner", prompt="old", priority="background")
    urgent = q.submit(agent="critic", prompt="new", priority="high")
    with q.connect() as db:
        db.execute(
            "UPDATE compute_jobs SET created_at=datetime('now','-20 seconds') WHERE id=?",
            (old["id"],),
        )
    assert q.claim("w", [LOCAL])["id"] == old["id"]
    assert q.get(urgent["id"])["status"] == "queued"


def test_aged_background_never_overtakes_owner_critical(tmp_path):
    q = queue(tmp_path, **{"global": 1})
    old = q.submit(agent="planner", prompt="old", priority="background")
    owner = q.submit(agent="critic", prompt="owner", priority="critical")
    with q.connect() as db:
        db.execute("UPDATE compute_jobs SET created_at=datetime('now','-10000 seconds') WHERE id=?",
                   (old["id"],))
    assert q.claim("owner-worker", [LOCAL])["id"] == owner["id"]


def test_owner_critical_is_visible_after_large_background_backlog(tmp_path):
    q = queue(tmp_path, **{"global": 1})
    for index in range(1001):
        q.submit(agent="planner", prompt=f"background-{index}", priority="background")
    owner = q.submit(agent="critic", prompt="owner", priority="critical")
    assert q.claim("owner-worker", [LOCAL])["id"] == owner["id"]


def test_blocked_same_agent_critical_backlog_does_not_hide_other_agent(tmp_path):
    q = queue(tmp_path)
    first = q.submit(agent="a02", prompt="first", priority="critical")
    assert q.claim("w1", [LOCAL])["id"] == first["id"]
    for index in range(1001):
        q.submit(agent="a02", prompt=f"blocked-{index}", priority="critical")
    another = q.submit(agent="a26", prompt="independent-owner-work", priority="critical")
    assert q.claim("w2", [LOCAL])["id"] == another["id"]


def test_background_reserve_keeps_one_local_slot_for_arriving_owner(tmp_path):
    policy = QueuePolicy(global_concurrency=3, per_agent_concurrency=1,
                         background_concurrency=2, local_ram_mb=8192,
                         local_vram_mb=4096)
    q = JobQueue(tmp_path / "owner-reserve.db", policy)
    backend = Provider("ollama", "local", "fast", 8192, 4096, 3)
    first = q.submit(agent="a01", prompt="background-1", priority="background")
    second = q.submit(agent="a02", prompt="background-2", priority="background")
    third = q.submit(agent="a04", prompt="background-3", priority="background")
    assert q.claim("w1", [backend])["id"] == first["id"]
    assert q.claim("w2", [backend])["id"] == second["id"]
    assert q.claim("w3", [backend]) is None
    owner = q.submit(agent="a26", prompt="owner", priority="critical")
    assert q.claim("w3", [backend])["id"] == owner["id"]
    assert q.get(third["id"])["status"] == "queued"
    q.finish(first["id"], result="done")
    assert q.claim("w1", [backend])["id"] == third["id"]


def test_background_reserve_counts_mixed_local_and_cloud_jobs(tmp_path):
    policy = QueuePolicy(global_concurrency=3, per_agent_concurrency=1,
                         background_concurrency=2, local_ram_mb=8192,
                         local_vram_mb=4096, cloud_wait_seconds=0,
                         max_job_cost_usd=2, daily_cost_ceiling_usd=3)
    q = JobQueue(tmp_path / "mixed-owner-reserve.db", policy)
    backend = Provider("ollama", "local", "fast", 8192, 4096, 3)
    providers = [backend, CLOUD]
    local = q.submit(agent="a01", prompt="local", priority="background")
    cloud = q.submit(agent="a02", prompt="cloud", priority="background",
                     model="large", vram_mb=8000, allow_cloud=True,
                     data_classification="CLOUD_PERMITTED", max_cost_usd=1)
    extra = q.submit(agent="a04", prompt="extra cloud", priority="background",
                     model="large", vram_mb=8000, allow_cloud=True,
                     data_classification="CLOUD_PERMITTED", max_cost_usd=1)
    assert q.claim("w1", providers)["id"] == local["id"]
    assert q.claim("w2", providers)["id"] == cloud["id"]
    assert q.get(cloud["id"])["provider"] == "gpu-cloud"
    assert q.claim("w3", providers) is None
    assert q.get(extra["id"])["status"] == "queued"
    owner = q.submit(agent="a26", prompt="owner", priority="critical")
    assert q.claim("w3", providers)["id"] == owner["id"]
    assert q.get(owner["id"])["provider"] == "ollama"
    q.finish(cloud["id"], result="done")
    assert q.claim("w2", providers)["id"] == extra["id"]


def test_n1_baseline_has_no_background_reserve(tmp_path):
    policy = QueuePolicy(global_concurrency=1, per_agent_concurrency=1,
                         background_concurrency=0, local_ram_mb=8192,
                         local_vram_mb=4096, cloud_wait_seconds=0,
                         max_job_cost_usd=2, daily_cost_ceiling_usd=3)
    q = JobQueue(tmp_path / "n1-reserve.db", policy)
    background = q.submit(agent="a01", prompt="cloud", priority="background",
                          model="large", vram_mb=8000, allow_cloud=True,
                          data_classification="CLOUD_PERMITTED", max_cost_usd=1)
    assert q.claim("w1", [LOCAL, CLOUD])["id"] == background["id"]
    owner = q.submit(agent="a26", prompt="owner", priority="critical")
    assert q.claim("w2", [LOCAL, CLOUD]) is None
    q.finish(background["id"], result="done")
    assert q.claim("w1", [LOCAL, CLOUD])["id"] == owner["id"]
