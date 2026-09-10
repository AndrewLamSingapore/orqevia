import pytest
from app.job_queue import JobQueue, QueuePolicy, Provider


@pytest.mark.parametrize("blocked", [True, False])
def test_eligible_priority_selection_is_not_limited_to_first_thousand(tmp_path, blocked):
    queue = JobQueue(tmp_path / "queue.db", QueuePolicy())
    seed = queue.submit(agent="architecture", prompt="Review design", priority="high",
                        model="unavailable" if blocked else "")
    # Bulk seed real persisted rows, preserving the submit contract. These are
    # scheduler fixtures only, not signed privileged execution permissions.
    with queue.connect() as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(compute_jobs)")]
        for i in range(1000):
            row = {**seed, "id": f"queued-{i}"}
            db.execute(f"INSERT INTO compute_jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [row[c] for c in columns])
    eligible = queue.submit(agent="a14", prompt="Review quality", priority="low")
    if not blocked:
        # Existing aging policy makes this old low-priority job the winner,
        # even though the raw-priority SQLite index puts it beyond the cap.
        with queue.connect() as db:
            db.execute("UPDATE compute_jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (eligible["id"],))
    provider = Provider("ollama-fast", "local", "fixture", 8192, 0, 1)
    claimed = queue.claim("fixture", [provider])
    assert claimed is not None and claimed["id"] == eligible["id"]
    assert queue.get(seed["id"])["status"] == "queued"
    assert len(queue.metrics()["running"]) == 1
    assert queue.claim("second-worker", [provider]) is None

