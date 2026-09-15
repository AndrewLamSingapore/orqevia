import time
from app.job_queue import JobQueue,Provider,QueuePolicy


def setup_queue(tmp_path,ceiling=1):
    return JobQueue(tmp_path/'queue.db',QueuePolicy(global_concurrency=2,per_agent_concurrency=1,
        cloud_wait_seconds=0,max_job_cost_usd=1,daily_cost_ceiling_usd=ceiling))


def submit(q,agent='a02'):
    return q.submit(agent=agent,prompt='fixture',model='fixture-model',allow_cloud=True,
        data_classification='CLOUD_PERMITTED',preferred_provider='fixture-cloud',max_cost_usd=1,max_retries=2)


PROVIDER=Provider('fixture-cloud','cloud','fixture-model',0,0,2,1,1,16)


def test_running_reservation_prevents_overcommit(tmp_path):
    q=setup_queue(tmp_path,ceiling=.00006)
    first=submit(q);second=submit(q,'a17')
    claim=q.claim('one',[PROVIDER])
    assert claim['id']==first['id'] and claim['actual_cost_usd'] is None
    assert q.claim('two',[PROVIDER]) is None
    assert q.get(second['id'])['status']=='budget_blocked'


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
