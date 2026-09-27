"""Real isolated thread/process lifecycle checks, never production queues."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool


LOCAL = Provider('isolated-test', 'local', 'test-model', 8192, 0, 1)


def build(tmp_path, handler):
    queue = JobQueue(tmp_path / 'isolated-queue.db', QueuePolicy(
        global_concurrency=1, per_agent_concurrency=1,
        local_ram_mb=8192, local_vram_mb=0,
    ))
    return queue, WorkerPool(queue, [LOCAL], handler)


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'isolated worker did not reach the expected state'


def submit(queue, text):
    return queue.submit(agent='planner', prompt=text, model='test-model', max_retries=0)


def test_same_pool_stop_start_processes_new_job_once(tmp_path):
    calls = []
    queue, pool = build(tmp_path, lambda job, provider: (calls.append(job['id']) or {'result': 'ok'}))
    try:
        first = submit(queue, 'first')
        pool.start()
        wait_for(lambda: queue.get(first['id'])['status'] == 'completed')
        pool.stop()
        second = submit(queue, 'second')
        pool.start()
        wait_for(lambda: queue.get(second['id'])['status'] == 'completed')
        assert calls == [first['id'], second['id']]
        assert queue.get(first['id'])['attempts'] == queue.get(second['id'])['attempts'] == 1
    finally:
        pool.stop()


def test_duplicate_start_and_stop_are_idempotent(tmp_path):
    queue, pool = build(tmp_path, lambda job, provider: {'result': 'ok'})
    try:
        pool.start()
        original = tuple(pool.threads)
        pool.start()
        assert tuple(pool.threads) == original
        assert len(original) == 1 and original[0].is_alive()
        pool.stop()
        pool.stop()
        assert not any(t.is_alive() for t in original)
        assert not pool.threads
    finally:
        pool.stop()


def test_stop_retains_inflight_worker_and_refuses_unsafe_restart(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def handler(job, provider):
        calls.append(job['id'])
        if job['prompt'] == 'first':
            entered.set()
            assert release.wait(12), 'test failed to release its isolated handler'
        return {'result': 'ok'}

    queue, pool = build(tmp_path, handler)
    original = ()
    try:
        first = submit(queue, 'first')
        second = submit(queue, 'second')
        pool.start()
        assert entered.wait(3)
        original = tuple(pool.threads)
        started = time.monotonic()
        pool.stop()
        assert time.monotonic() - started < 4.5, 'stop must remain bounded'
        assert tuple(pool.threads) == original and original[0].is_alive()
        assert pool.stop_event.is_set()
        with pytest.raises(RuntimeError, match='still stopping'):
            pool.start()
        assert pool.stop_event.is_set(), 'never revive a worker whose stop is pending'
        assert queue.get(second['id'])['status'] == 'queued'
        release.set()
        original[0].join(3)
        assert not original[0].is_alive()
        assert queue.get(first['id'])['status'] == 'completed'
        pool.start()
        wait_for(lambda: queue.get(second['id'])['status'] == 'completed')
        assert calls == [first['id'], second['id']]
        assert queue.get(first['id'])['attempts'] == queue.get(second['id'])['attempts'] == 1
    finally:
        release.set()
        for thread in original:
            thread.join(3)
        pool.stop()


def test_worker_can_request_stop_without_self_join_or_failed_effect(tmp_path):
    holder = {}
    calls = []

    def handler(job, provider):
        calls.append(job['id'])
        holder['pool'].stop()
        return {'result': 'completed-before-stop'}

    queue, pool = build(tmp_path, handler)
    holder['pool'] = pool
    try:
        job = submit(queue, 'single effect')
        pool.start()
        wait_for(lambda: queue.get(job['id'])['status'] in {'completed', 'failed'})
        assert queue.get(job['id'])['status'] == 'completed'
        assert calls == [job['id']]
        assert queue.get(job['id'])['attempts'] == 1
    finally:
        pool.stop()


def test_concurrent_start_calls_create_one_worker(tmp_path):
    queue, pool = build(tmp_path, lambda job, provider: {'result': 'ok'})
    barrier = threading.Barrier(9)
    errors = []

    def starter():
        barrier.wait()
        try:
            pool.start()
        except Exception as exc:
            errors.append(type(exc).__name__)

    starters = [threading.Thread(target=starter) for _ in range(8)]
    try:
        for thread in starters:
            thread.start()
        barrier.wait()
        for thread in starters:
            thread.join(3)
        assert not errors
        assert len(pool.threads) == 1
        assert pool.threads[0].is_alive()
    finally:
        pool.stop()


def test_stop_before_claim_admission_keeps_job_queued_without_effect(tmp_path):
    at_claim, release = threading.Event(), threading.Event()
    effects = []
    queue, pool = build(tmp_path, lambda job, provider: (effects.append(job['id']) or {'result': 'ok'}))
    original_claim = queue.claim

    def paused_claim(*args, **kwargs):
        at_claim.set()
        assert release.wait(5)
        return original_claim(*args, **kwargs)

    queue.claim = paused_claim
    job = submit(queue, 'must remain queued after stop')
    stopper = threading.Thread(target=pool.stop)
    try:
        pool.start()
        assert at_claim.wait(3)
        stopper.start()
        assert pool.stop_event.wait(3)
        release.set()
        stopper.join(5)
        assert not stopper.is_alive()
        assert effects == []
        assert queue.get(job['id'])['status'] == 'queued'
        assert queue.get(job['id'])['attempts'] == 0
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(5)
        pool.stop()


def test_external_stop_does_not_hold_lifecycle_lock_while_joining_worker(tmp_path):
    entered, request_stop = threading.Event(), threading.Event()
    holder = {}

    def handler(job, provider):
        entered.set()
        assert request_stop.wait(5)
        holder['pool'].stop()
        return {'result': 'completed effect'}

    queue, pool = build(tmp_path, handler)
    holder['pool'] = pool
    job = submit(queue, 'worker stops itself during external stop')
    stopper = threading.Thread(target=pool.stop)
    try:
        pool.start()
        assert entered.wait(3)
        stopper.start()
        assert pool.stop_event.wait(3)
        request_stop.set()
        stopper.join(1.5)
        assert not stopper.is_alive(), 'join must not hold the lock required by worker stop'
        assert queue.get(job['id'])['status'] == 'completed'
    finally:
        request_stop.set()
        if stopper.ident is not None:
            stopper.join(5)
        pool.stop()


def test_real_child_process_reuses_pool_without_external_services(tmp_path):
    program = r'''
import json,sys,time
from pathlib import Path
from app.job_queue import JobQueue,Provider,QueuePolicy,WorkerPool
root=Path(sys.argv[1]); root.mkdir(exist_ok=True)
queue=JobQueue(root/'child-queue.db',QueuePolicy(global_concurrency=1,local_ram_mb=8192,local_vram_mb=0))
provider=Provider('child-isolated','local','test-model',8192,0,1)
effects=[]
pool=WorkerPool(queue,[provider],lambda job,provider:(effects.append(job['id']) or {'result':'ok'}))
try:
 for n in range(2):
  job=queue.submit(agent='planner',prompt=str(n),model='test-model',max_retries=0)
  pool.start(); deadline=time.monotonic()+3
  while queue.get(job['id'])['status']!='completed' and time.monotonic()<deadline: time.sleep(.01)
  assert queue.get(job['id'])['status']=='completed', 'stop/start left a persisted job queued'
  pool.stop()
 assert len(effects)==len(set(effects))==2
 print(json.dumps({'effects':len(effects),'unique_effects':len(set(effects)),'completed':queue.metrics()['statuses'].get('completed')}))
finally: pool.stop()
'''
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env['PRIME_DATA_DIR'] = str(tmp_path / 'child-data')
    env['PRIME_COMPUTE_QUEUE_DB'] = str(tmp_path / 'unused-queue.db')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-B', '-c', program, str(tmp_path / 'child')],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'effects': 2, 'unique_effects': 2, 'completed': 2}


def test_interrupted_child_never_replays_ambiguous_external_job(tmp_path, monkeypatch):
    """Kill only our test child after a fake effect; recovery must not replay it.

    The executor is local deterministic test code, not a cloud request. This
    tests the real process/SQLite crash boundary, not external-service recovery.
    """
    queue, unused_pool = build(tmp_path, lambda job, provider: {'result': 'unused'})
    job = queue.submit(agent='planner', prompt='ambiguous isolated fake effect',
                       model='test-model', allow_cloud=True,
                       data_classification='CLOUD_PERMITTED', max_retries=3)
    effect_path = tmp_path / 'fake-effect.txt'
    program = r'''
import sys,time
from pathlib import Path
from app.job_queue import JobQueue,Provider,QueuePolicy,WorkerPool
queue=JobQueue(Path(sys.argv[1]),QueuePolicy(global_concurrency=1,local_ram_mb=8192,local_vram_mb=0,cloud_wait_seconds=0))
provider=Provider('fake-external','cloud','test-model',0,0,1,0.0,0.0)
def effect(job,provider):
 with Path(sys.argv[2]).open('x',encoding='utf-8') as f: f.write(job['id'])
 time.sleep(15)
 return {'result':'not reached by this test'}
pool=WorkerPool(queue,[provider],effect)
pool.start()
time.sleep(15)
'''
    env = dict(os.environ)
    env['PRIME_DATA_DIR'] = str(tmp_path / 'child-data')
    env['PRIME_COMPUTE_QUEUE_DB'] = str(tmp_path / 'unused-queue.db')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    child = subprocess.Popen([sys.executable, '-B', '-c', program, queue.db_path, str(effect_path)],
                             cwd=Path(__file__).resolve().parents[1], env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_for(lambda: effect_path.exists(), seconds=5)
        assert effect_path.read_text(encoding='utf-8') == job['id']
        before = queue.get(job['id'])
        assert before['status'] == 'running' and before['attempts'] == 1
        child.terminate()  # Exactly the isolated Popen child, never a host/service process.
        child.communicate(timeout=5)
        reopened = JobQueue(queue.db_path, queue.policy)
        with monkeypatch.context() as patch:
            patch.setattr('app.job_queue.time.time', lambda: before['lease_until'] + 1)
            assert reopened.recover_expired() == 1
        after = reopened.get(job['id'])
        assert after['status'] == 'failed' and after['attempts'] == 1
        assert after['error'] == 'worker lease expired' and after['completed_at']
        assert reopened.claim('replacement', [Provider('fake-external', 'cloud', 'test-model', 0, 0, 1)]) is None
        assert effect_path.read_text(encoding='utf-8') == job['id']
    finally:
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=5)
