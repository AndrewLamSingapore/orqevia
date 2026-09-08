"""Actual interpreter loss and restart against persisted authorization ledgers."""
import os
import subprocess
import sys
import json
from pathlib import Path

from tests.test_harness_execution import rig, queued, SECRET


CHILD = '''
import json, os, sys, time
from pathlib import Path
from app.action_harness import ActionHarness
from app.spine import SpineStore, StableSpine
from app.job_queue import JobQueue, Provider
from app.harness_execution import execute_job
p=Path(sys.argv[1]); job=json.loads((p/'job.json').read_text())
h=ActionHarness(p/'h.db', {'authority-v0': b'isolated-test-key-never-a-production-key'})
s=StableSpine(SpineStore(str(p/'s.db')))
def infer(job, provider):
    with (p/'calls').open('a') as f: f.write(job['id']+'\\n'); f.flush(); os.fsync(f.fileno())
    if sys.argv[2]=='crash': os._exit(42)
    time.sleep(2 if sys.argv[2]=='hold' else .2)
    return {'result':'done'}
try:
    execute_job(job, Provider('ollama-fast','local','test-model',8192,0,1),h,s,infer)
except PermissionError: sys.exit(3)
'''


def command(tmp_path, mode):
    return [sys.executable, "-c", CHILD, str(tmp_path), mode]


def test_process_death_after_consumption_cannot_repeat_or_release_slot(rig, tmp_path):
    job, _ = queued(rig)
    (tmp_path / "job.json").write_text(json.dumps(job))
    assert subprocess.run(command(tmp_path, "crash"), timeout=20).returncode == 42
    assert subprocess.run(command(tmp_path, "restart"), timeout=20).returncode == 3
    assert (tmp_path / "calls").read_text().splitlines() == [job["id"]]
    with rig[1].connect() as db:
        assert db.execute("SELECT state FROM harness_jobs WHERE job_id=?", (job["id"],)).fetchone()[0] == "started"
    with rig[3].connect() as db:
        db.execute("UPDATE compute_jobs SET lease_until=0")
    rig[3].recover_expired()
    second, _ = queued(rig, "a16")
    (tmp_path / "job.json").write_text(json.dumps(second))
    assert subprocess.run(command(tmp_path, "restart"), timeout=20).returncode == 3
    assert (tmp_path / "calls").read_text().splitlines() == [job["id"]]


def test_two_processes_cannot_consume_one_authorization_twice(rig, tmp_path):
    job, _ = queued(rig)
    (tmp_path / "job.json").write_text(json.dumps(job))
    children = [subprocess.Popen(command(tmp_path, "run")) for _ in range(2)]
    results = [p.wait(timeout=20) for p in children]
    assert sorted(results) == [0, 3]
    assert (tmp_path / "calls").read_text().splitlines() == [job["id"]]
    assert subprocess.run(command(tmp_path, "restart"), timeout=20).returncode == 3


def test_distinct_queues_share_one_durable_inference_slot(rig, tmp_path):
    import time
    from app.job_queue import JobQueue
    first, _ = queued(rig)
    other = (*rig[:3], JobQueue(tmp_path / "other-queue.db"))
    second, _ = queued(other, "a16")
    (tmp_path / "job.json").write_text(json.dumps(first))
    child = subprocess.Popen(command(tmp_path, "hold"))
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "calls").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / "calls").exists()
        (tmp_path / "job.json").write_text(json.dumps(second))
        assert subprocess.run(command(tmp_path, "run"), timeout=20).returncode == 3
        assert child.wait(timeout=20) == 0
        assert (tmp_path / "calls").read_text().splitlines() == [first["id"]]
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
