import time

import pytest

from app.job_queue import JobQueue, Provider, QueuePolicy


def test_qualification_is_held_at_insert_and_another_worker_cannot_steal_it(tmp_path):
    policy = QueuePolicy(global_concurrency=1, per_agent_concurrency=1, local_ram_mb=8192, local_vram_mb=0)
    owner = JobQueue(tmp_path / "queue.db", policy)
    provider = Provider("ollama-fast", "local", "fast", 8192, 0, 1)
    job = owner.submit(agent="a19", prompt="qualification fixture", model="fast", priority=50, reservation_seconds=60)
    worker = JobQueue(tmp_path / "queue.db", policy)
    assert worker.get(job["id"])["status"] == "held"
    assert worker.get(job["id"])["lease_until"] > time.time()
    assert worker.claim("ordinary-worker", [provider]) is None
    normal = worker.submit(agent="a02", prompt="accepted production fixture", model="fast")
    assert worker.claim("ordinary-worker", [provider])["id"] == normal["id"]
    assert owner.claim("qualification-owner", [provider], held_job_id=job["id"]) is None
    worker.finish(normal["id"], result="completed")
    assert owner.claim("qualification-owner", [provider], held_job_id=job["id"])["id"] == job["id"]


@pytest.mark.parametrize("value", [-1, 3601, True, "60"])
def test_reservation_is_bounded_and_rejected_before_writing(tmp_path, value):
    queue = JobQueue(tmp_path / "queue.db", QueuePolicy())
    with pytest.raises(ValueError, match="Reservation"):
        queue.submit(agent="a19", prompt="fixture", reservation_seconds=value)
    with queue.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM compute_jobs").fetchone()[0] == 0
