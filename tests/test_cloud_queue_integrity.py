import time
import uuid
import pytest
from app.job_queue import JobQueue,Provider,QueuePolicy


def setup_queue(tmp_path,ceiling=1,cloud_concurrency=1):
    return JobQueue(tmp_path/'queue.db',QueuePolicy(global_concurrency=2,per_agent_concurrency=1,
        cloud_concurrency=cloud_concurrency,cloud_wait_seconds=0,
        max_job_cost_usd=1,daily_cost_ceiling_usd=ceiling))


def submit(q,agent='a02'):
    return q.submit(agent=agent,prompt='fixture',model='fixture-model',allow_cloud=True,
        data_classification='CLOUD_PERMITTED',preferred_provider='fixture-cloud',max_cost_usd=1,max_retries=2)


PROVIDER=Provider('fixture-cloud','cloud','fixture-model',0,0,2,1,1,16)


def test_running_reservation_prevents_overcommit(tmp_path):
    # Allow the second cloud candidate to reach the financial admission guard.
    q=setup_queue(tmp_path,ceiling=.00006,cloud_concurrency=2)
    first=submit(q);second=submit(q,'a17')
    claim=q.claim('one',[PROVIDER])
    assert claim['id']==first['id'] and claim['actual_cost_usd'] is None
    assert q.claim('two',[PROVIDER]) is None
    assert q.get(second['id'])['status']=='budget_blocked'


def test_default_cloud_capacity_stops_before_financial_admission(tmp_path):
    q=JobQueue(tmp_path/'default.db',QueuePolicy(global_concurrency=2,
        cloud_wait_seconds=0,daily_cost_ceiling_usd=.00006))
    first=submit(q);second=submit(q,'a17')
    assert q.policy.cloud_concurrency==1
    assert q.claim('one',[PROVIDER])['id']==first['id']
    assert q.claim('two',[PROVIDER]) is None
    assert q.get(second['id'])['status']=='queued'


def test_unknown_cancelled_charge_retains_reservation(tmp_path):
    q=setup_queue(tmp_path);job=submit(q)
    claim=q.claim('one',[PROVIDER]);q.cancel(job['id'])
    result=q.finish(job['id'],actual_cost_usd=None,input_tokens=None,output_tokens=None)
    assert result['status']=='cancelled' and result['actual_cost_usd'] is None
    assert q.metrics()['daily_spend_usd']==claim['estimated_cost_usd']


def test_cloud_lease_expiry_does_not_replay_ambiguous_call(tmp_path):
    q=setup_queue(tmp_path);job=submit(q);q.claim('one',[PROVIDER])
    with q.connect() as c:c.execute('UPDATE compute_jobs SET lease_until=? WHERE id=?',(time.time()-1,job['id']))
    assert q.recover_expired()==1
    assert q.get(job['id'])['status']=='failed'
    assert q.claim('two',[PROVIDER]) is None


@pytest.mark.parametrize('environment,field,default', [
    ('PRIME_MAX_JOB_COST_USD', 'max_job_cost_usd', 2),
    ('PRIME_DAILY_COST_USD', 'daily_cost_ceiling_usd', 10),
])
@pytest.mark.parametrize('value', ['nan', 'NaN', 'inf', '-inf'])
def test_nonfinite_cost_limits_retain_documented_defaults(monkeypatch, environment, field, default, value):
    monkeypatch.setenv(environment, value)
    assert getattr(QueuePolicy.from_env(), field) == default


@pytest.mark.parametrize('environment,field,high', [
    ('PRIME_MAX_JOB_COST_USD', 'max_job_cost_usd', 10000),
    ('PRIME_DAILY_COST_USD', 'daily_cost_ceiling_usd', 100000),
])
@pytest.mark.parametrize('value', ['-1', '.25', '200001'])
def test_finite_cost_limits_preserve_existing_clamping(monkeypatch, environment, field, high, value):
    monkeypatch.setenv(environment, value)
    assert getattr(QueuePolicy.from_env(), field) == max(0, min(high, float(value)))


def aged_unknown(q, terminal='failed'):
    first = submit(q)
    claim = q.claim('first', [PROVIDER])
    q.finish(first['id'], error='PROVIDER_HTTP_FAILURE', retryable=False,
             actual_cost_usd=None, input_tokens=None, output_tokens=None)
    # Synthetic historical terminal rows, never a billing settlement operation.
    with q.connect() as db:
        db.execute("UPDATE compute_jobs SET status=?,completed_at=datetime('now','-25 hours') WHERE id=?",
                   (terminal, first['id']))
    return claim


@pytest.mark.parametrize('terminal', ['completed', 'failed', 'cancelled', 'budget_blocked'])
@pytest.mark.parametrize('admission', ['claim', 'hold'])
def test_aged_unknown_terminal_reservation_blocks_financial_overcommit(tmp_path, terminal, admission):
    q = setup_queue(tmp_path, ceiling=.00006, cloud_concurrency=2)
    first = aged_unknown(q, terminal)
    assert q.get(first['id'])['actual_cost_usd'] is None
    if admission == 'claim':
        second = submit(q, 'a17')
        assert q.claim('second', [PROVIDER]) is None
        assert q.get(second['id'])['status'] == 'budget_blocked'
    else:
        with pytest.raises(ValueError, match='daily cloud cost ceiling reached'):
            q.reserve_cloud_chain(agent='a17', requests=[{'provider': PROVIDER,
                'prompt': 'fixture', 'max_cost_usd': '1'}], timeout_seconds=1,
                binding={'parent_task_id': str(uuid.uuid4())})
        assert len(q.list()) == 1
    assert q.metrics()['daily_spend_usd'] == first['estimated_cost_usd']


@pytest.mark.parametrize('known_cost', [0, .000039])
def test_known_cost_ages_normally_without_retaining_an_uncertain_reserve(tmp_path, known_cost):
    q = setup_queue(tmp_path, ceiling=.00006, cloud_concurrency=2)
    first = submit(q)
    q.claim('first', [PROVIDER])
    q.finish(first['id'], actual_cost_usd=known_cost)
    with q.connect() as db:
        db.execute("UPDATE compute_jobs SET completed_at=datetime('now','-25 hours') WHERE id=?", (first['id'],))
    assert q.metrics()['daily_spend_usd'] == 0
    second = submit(q, 'a17')
    assert q.claim('second', [PROVIDER])['id'] == second['id']


def test_aged_unknown_plus_held_or_running_reserve_is_counted_once(tmp_path):
    q = setup_queue(tmp_path, ceiling=.00009, cloud_concurrency=2)
    first = aged_unknown(q)
    held = q.reserve_cloud_chain(agent='a17', requests=[{'provider': PROVIDER,
        'prompt': 'fixture', 'max_cost_usd': '1'}], timeout_seconds=1,
        binding={'parent_task_id': str(uuid.uuid4())})[0]
    assert q.metrics()['daily_spend_usd'] == first['estimated_cost_usd']
    assert q.claim('held', [PROVIDER], held_job_id=held['id'])['id'] == held['id']
    assert q.metrics()['daily_spend_usd'] == first['estimated_cost_usd']
    third = submit(q, 'a20')
    assert q.claim('third', [PROVIDER]) is None
    assert q.get(third['id'])['status'] == 'budget_blocked'


def test_aged_uncertain_cloud_lease_retains_capacity_and_one_financial_reserve(tmp_path):
    q = setup_queue(tmp_path, ceiling=.00009, cloud_concurrency=2)
    first = submit(q)
    claimed = q.claim('first', [PROVIDER])
    with q.connect() as db:
        db.execute('UPDATE compute_jobs SET lease_until=? WHERE id=?', (time.time()-1, first['id']))
    assert q.recover_expired() == 1
    with q.connect() as db:
        db.execute("UPDATE compute_jobs SET completed_at=datetime('now','-25 hours') WHERE id=?", (first['id'],))
    assert q.get(first['id'])['cloud_inflight'] == 1
    assert q.metrics()['daily_spend_usd'] == claimed['estimated_cost_usd']
    second = submit(q, 'a17')
    assert q.claim('second', [PROVIDER])['id'] == second['id']
    third = submit(q, 'a20')
    assert q.claim('third', [PROVIDER]) is None
    assert q.get(third['id'])['status'] == 'queued'
    assert q.get(first['id'])['actual_cost_usd'] is None
