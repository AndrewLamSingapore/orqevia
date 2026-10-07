"""Tiny temporary-SQLite admission tests; no runtime, model or worker execution."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time

import pytest

from app import backend_admission
from app.job_queue import JobQueue, QueueAdmissionFull, QueuePolicy, utcnow


def bounded(tmp_path, limit=3, reserve=1):
    return JobQueue(tmp_path / 'queue.db', QueuePolicy(
        pending_job_limit=limit, pending_owner_reserve=reserve))


def submit(queue, priority='normal', **extra):
    return queue.submit(agent='a20', prompt='public synthetic pending-cap case',
                        priority=priority, **extra)


def lease(queue, job_id, *, endpoint='fixture-backend', state='uncertain'):
    with queue.connect() as db:
        db.execute('''INSERT INTO backend_admission
            (endpoint,job_id,instance,boot_id,state,demand_mib)
            VALUES(?,?,?,?,?,?)''', (endpoint, job_id, 'fixture', 'boot', state, 1))


def running_cloud(queue, *, priority='normal'):
    job = submit(queue, priority, allow_cloud=True, max_cost_usd=1)
    with queue.connect() as db:
        db.execute('''UPDATE compute_jobs SET status='running',provider='fixture-cloud',
            started_at=?,lease_until=?,estimated_cost_usd=.1 WHERE id=?''',
            (utcnow(), time.time() + 60, job['id']))
    return job


@pytest.mark.parametrize('limit,reserve', [
    (None, 1), (1, None), (True, 1), (2, True), (0, 1), (3, 0),
    (2, 3), (2.0, 1), (3, 1.0), ('3', 1), (1_000_001, 1), (float('inf'), 1)])
def test_invalid_policy_cannot_silently_disable_bound(limit, reserve):
    with pytest.raises(ValueError, match='explicit pending queue policy'):
        QueuePolicy(pending_job_limit=limit, pending_owner_reserve=reserve)


@pytest.mark.parametrize('value', ['bad', '1.5', '-1', 'NaN', '1e2', '٥', '10000000'])
def test_invalid_environment_policy_fails_closed(monkeypatch, value):
    monkeypatch.setenv('PRIME_QUEUE_PENDING_LIMIT', value)
    monkeypatch.setenv('PRIME_QUEUE_OWNER_PENDING_RESERVE', '1')
    with pytest.raises(ValueError):
        QueuePolicy.from_env()


def test_paired_explicit_environment_and_unset_compatibility(monkeypatch, tmp_path):
    monkeypatch.delenv('PRIME_QUEUE_PENDING_LIMIT', raising=False)
    monkeypatch.delenv('PRIME_QUEUE_OWNER_PENDING_RESERVE', raising=False)
    policy = QueuePolicy.from_env()
    queue = JobQueue(tmp_path / 'legacy.db', policy)
    for _ in range(4):
        submit(queue)
    assert queue.metrics()['pending_admission']['state'] == 'UNCONFIGURED'
    assert policy.pending_job_limit is None
    monkeypatch.setenv('PRIME_QUEUE_PENDING_LIMIT', '3')
    with pytest.raises(ValueError):
        QueuePolicy.from_env()
    monkeypatch.setenv('PRIME_QUEUE_OWNER_PENDING_RESERVE', '1')
    assert QueuePolicy.from_env().pending_job_limit == 3


def test_owner_reserve_and_total_cap_are_separate(tmp_path):
    queue = bounded(tmp_path)
    submit(queue, 'background')
    submit(queue, 'high')
    with pytest.raises(QueueAdmissionFull, match='OWNER_PENDING_RESERVE'):
        submit(queue, 'normal')
    submit(queue, 'critical')
    with pytest.raises(QueueAdmissionFull, match='PENDING_QUEUE_FULL'):
        submit(queue, 'critical')
    assert queue.metrics()['pending_admission']['held_jobs'] == 3


def test_one_slot_policy_can_be_owner_only(tmp_path):
    queue = bounded(tmp_path, 1, 1)
    with pytest.raises(QueueAdmissionFull):
        submit(queue)
    submit(queue, 'critical')
    with pytest.raises(QueueAdmissionFull):
        submit(queue, 'critical')


def test_rejection_has_no_job_event_or_budget_side_effect(tmp_path):
    queue = bounded(tmp_path, 2, 1)
    first = submit(queue)
    with queue.connect() as db:
        before = tuple(db.execute('''SELECT
            (SELECT COUNT(*) FROM compute_jobs),
            (SELECT COUNT(*) FROM compute_events),
            (SELECT SUM(estimated_cost_usd) FROM compute_jobs)''').fetchone())
    with pytest.raises(QueueAdmissionFull):
        submit(queue)
    with queue.connect() as db:
        after = tuple(db.execute('''SELECT
            (SELECT COUNT(*) FROM compute_jobs),
            (SELECT COUNT(*) FROM compute_events),
            (SELECT SUM(estimated_cost_usd) FROM compute_jobs)''').fetchone())
    assert after == before
    queue.cancel(first['id'])
    assert submit(queue)['status'] == 'queued'  # Failed admission released its lock.


@pytest.mark.parametrize('status', ['queued', 'running', 'awaiting_approval', 'uncertain'])
def test_nonterminal_status_cannot_bypass_cap(tmp_path, status):
    queue = bounded(tmp_path, 1, 1)
    job = submit(queue, 'critical')
    with queue.connect() as db:
        db.execute('UPDATE compute_jobs SET status=? WHERE id=?', (status, job['id']))
    with pytest.raises(QueueAdmissionFull):
        submit(queue, 'critical')


@pytest.mark.parametrize('state', ['pending', 'running', 'uncertain'])
def test_retained_local_leases_count_once_and_need_completion(tmp_path, state):
    queue = bounded(tmp_path, 2, 1)
    job = submit(queue)
    lease(queue, job['id'], state=state)
    lease(queue, job['id'], endpoint='other-fixture', state=state)
    assert queue.metrics()['pending_admission']['held_jobs'] == 1
    queue.cancel(job['id'])
    assert queue.metrics()['pending_admission']['held_jobs'] == 1
    with pytest.raises(QueueAdmissionFull, match='OWNER_PENDING_RESERVE'):
        submit(queue)
    submit(queue, 'critical')
    with queue.connect() as db:
        # Explicit fixture completion, never elapsed time or cancelled status.
        for endpoint in ('fixture-backend', 'other-fixture'):
            db.execute("UPDATE backend_admission SET state='uncertain' WHERE endpoint=?", (endpoint,))
            backend_admission.completed(db, endpoint, job['id'])
    assert queue.metrics()['pending_admission']['held_jobs'] == 1
    assert submit(queue)['status'] == 'queued'


def test_orphan_lease_is_not_free_capacity_or_owner_authority(tmp_path):
    queue = bounded(tmp_path, 2, 1)
    lease(queue, 'unknown-public-job')
    with pytest.raises(QueueAdmissionFull, match='OWNER_PENDING_RESERVE'):
        submit(queue)
    assert submit(queue, 'critical')['status'] == 'queued'


def test_malformed_persisted_priority_cannot_consume_owner_reserve_as_owner(tmp_path):
    queue = bounded(tmp_path, 2, 1)
    job = submit(queue)
    with queue.connect() as db:
        db.execute("UPDATE compute_jobs SET priority='critical' WHERE id=?", (job['id'],))
    assert queue.metrics()['pending_admission']['noncritical_held_jobs'] == 1
    with pytest.raises(QueueAdmissionFull):
        submit(queue)
    submit(queue, 'critical')


def test_cancelled_running_cloud_is_retained_without_completion_claim(tmp_path):
    queue = bounded(tmp_path, 2, 1)
    job = running_cloud(queue)
    queue.cancel(job['id'])
    assert queue.metrics()['pending_admission']['held_jobs'] == 1
    queue.finish(job['id'], result='36', actual_cost_usd=.001)
    # Existing cancelled finish does not persist trustworthy completion. Hold.
    assert queue.metrics()['pending_admission']['held_jobs'] == 1
    with pytest.raises(QueueAdmissionFull, match='OWNER_PENDING_RESERVE'):
        submit(queue)
    submit(queue, 'critical')


def test_ambiguous_failed_cloud_and_expired_cloud_are_retained(tmp_path):
    queue = bounded(tmp_path, 3, 1)
    failed = running_cloud(queue)
    queue.finish(failed['id'], error='PROVIDER_TIMEOUT', retryable=False,
                 actual_cost_usd=None, input_tokens=None, output_tokens=None)
    expired = running_cloud(queue)
    with queue.connect() as db:
        db.execute('UPDATE compute_jobs SET lease_until=? WHERE id=?',
                   (time.time() - 1, expired['id']))
    assert queue.recover_expired() == 1
    assert queue.metrics()['pending_admission']['held_jobs'] == 2
    with pytest.raises(QueueAdmissionFull, match='OWNER_PENDING_RESERVE'):
        submit(queue)
    submit(queue, 'critical')


@pytest.mark.parametrize('actual_cost', [0, None])
def test_successful_terminal_cloud_is_not_pending_despite_unknown_billing(tmp_path, actual_cost):
    queue = bounded(tmp_path, 2, 1)
    job = running_cloud(queue)
    result = queue.finish(job['id'], result='36', actual_cost_usd=actual_cost)
    assert result['status'] == 'completed'
    assert queue.metrics()['pending_admission']['held_jobs'] == 0
    submit(queue)


def test_queued_cloud_cancelled_before_dispatch_releases_capacity(tmp_path):
    queue = bounded(tmp_path, 2, 1)
    job = submit(queue, allow_cloud=True)
    queue.cancel(job['id'])
    assert queue.metrics()['pending_admission']['held_jobs'] == 0
    submit(queue)


def test_shared_sqlite_submit_race_cannot_exceed_explicit_limit(tmp_path):
    policy = QueuePolicy(pending_job_limit=3, pending_owner_reserve=1)
    queues = [JobQueue(tmp_path / 'race.db', policy) for _ in range(6)]
    ready = threading.Barrier(len(queues))

    def attempt(queue):
        ready.wait(timeout=2)
        try:
            submit(queue, 'critical')
            return 'accepted'
        except QueueAdmissionFull:
            return 'blocked'

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, queues))
    assert outcomes.count('accepted') == 3
    assert outcomes.count('blocked') == 3
    assert queues[0].metrics()['pending_admission']['held_jobs'] == 3


def test_background_race_cannot_fill_critical_reserve(tmp_path):
    policy = QueuePolicy(pending_job_limit=3, pending_owner_reserve=1)
    queues = [JobQueue(tmp_path / 'mixed-race.db', policy) for _ in range(4)]
    ready = threading.Barrier(4)

    def attempt(pair):
        queue, priority = pair
        ready.wait(timeout=2)
        try:
            submit(queue, priority)
            return priority
        except QueueAdmissionFull:
            return 'blocked'

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, zip(queues, ['background'] * 3 + ['critical'])))
    assert outcomes.count('critical') == 1
    assert outcomes.count('background') == 2
    assert queues[0].metrics()['pending_admission']['held_jobs'] == 3
