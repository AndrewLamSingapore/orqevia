"""Failure injection in disposable queues; no production workers or inference."""
from asyncio import CancelledError
import ast
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import os
from pathlib import Path
import time

import pytest

from app.execution_diagnostics import failure_details
from app.job_queue import JobQueue,Provider,QueuePolicy,WorkerPool
from app.observability import record_counter,record_duration,span

MODEL=Provider('fixture','local','fixture-model',1024,0,1)


@pytest.fixture(autouse=True)
def no_live_guardian(monkeypatch):
    monkeypatch.delenv('ORQEVIA_RESOURCE_GUARDIAN_PROFILE',raising=False)


def events(queue,job):
    with queue.connect() as db:
        return [json.loads(r[0]) for r in db.execute(
            "SELECT details_json FROM compute_events WHERE job_id=? AND event_type='execution_failure' ORDER BY created_at",
            (job['id'],))]


def test_execution_value_error_terminalizes_and_preserves_redacted_chain_and_stage(tmp_path):
    queue=JobQueue(tmp_path/'queue.db',QueuePolicy(coordinated=True))
    job=queue.submit(agent='a17',prompt='fixture',model='fixture-model',max_retries=0)
    def fail(current,provider):
        pool.stop_event.set()
        queue.transition(current['id'],'MODEL_LOADING')
        queue.update_progress(current['id'],'retained partial output')
        try:raise KeyError('private-path Bearer fixture-secret')
        except KeyError as cause:raise ValueError('private request text') from cause
    pool=WorkerPool(queue,[MODEL],fail)
    pool._run('fixture-worker')
    result=queue.get(job['id'])
    assert result['status']=='failed' and result['error']=='LOCAL_EXECUTION_FAILED'
    assert result['local_inflight']==0
    assert result['result']=='retained partial output'
    diagnostics=events(queue,job)
    assert len(diagnostics)==1 and diagnostics[0]['stage']=='MODEL_LOADING'
    assert [c['class'] for c in diagnostics[0]['cause_chain']]==['ValueError','KeyError']
    assert 'fixture-secret' not in json.dumps(diagnostics) and 'private request text' not in json.dumps(diagnostics)
    assert diagnostics[0]['message_recorded'] is False


def test_retry_is_bounded_and_reuses_the_original_idempotent_job(tmp_path):
    queue=JobQueue(tmp_path/'queue.db',QueuePolicy())
    job=queue.submit(agent='a17',prompt='fixture',model='fixture-model',max_retries=1,idempotency_key='same-request')
    executed=[]
    def fail(current,provider):
        executed.append(current['id'])
        if len(executed)==2:pool.stop_event.set()
        raise ValueError('malformed synthetic model chunk')
    pool=WorkerPool(queue,[MODEL],fail)
    pool._run('fixture-worker')
    assert queue.get(job['id'])['status']=='failed'
    assert executed==[job['id'],job['id']]
    repeated=queue.submit(agent='a17',prompt='fixture',model='fixture-model',max_retries=1,idempotency_key='same-request')
    assert repeated['id']==job['id'] and len(queue.list())==1 and len(events(queue,job))==2


def test_cancelled_coroutine_is_recorded_and_does_not_create_an_automatic_retry(tmp_path):
    queue=JobQueue(tmp_path/'queue.db',QueuePolicy())
    job=queue.submit(agent='a17',prompt='fixture',model='fixture-model',max_retries=2)
    def cancel(current,provider):
        pool.stop_event.set()
        raise CancelledError('untrusted cancellation detail')
    pool=WorkerPool(queue,[MODEL],cancel)
    pool._run('fixture-worker')
    assert queue.get(job['id'])['status']=='failed'
    assert events(queue,job)[0]['reason_code']=='EXECUTION_CANCELLED'


def test_direct_executor_execution_value_error_is_not_mistaken_for_terminal_state(tmp_path):
    queue=JobQueue(tmp_path/'queue.db',QueuePolicy())
    job=queue.submit(agent='a17',prompt='fixture',model='fixture-model',max_retries=0)
    def fail(current,provider):
        queue.update_progress(current['id'],'retained direct partial')
        raise ValueError('private malformed response')
    source=Path(__file__).resolve().parents[1]/'app'/'compute_queue_api.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_direct')
    namespace={'queue':queue,'providers':lambda:[MODEL],'_execute':fail,'time':time,
        'span':span,'ThreadPoolExecutor':ThreadPoolExecutor,'FutureTimeout':FutureTimeout,
        'CancelledError':CancelledError,'record_counter':record_counter,'record_duration':record_duration,
        '_publish_completed_job':None,'DATA':tmp_path,'os':os}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
    namespace['_run_direct'](job['id'])
    assert queue.get(job['id'])['status']=='failed'
    assert queue.get(job['id'])['result']=='retained direct partial'
    assert events(queue,job)[0]['exception_class']=='ValueError'


def test_reason_codes_are_fixed_and_unknown_permission_messages_are_never_copied():
    known=failure_details(PermissionError('Measured Compute Profile memory reserve reached; local inference held'),
        stage='MODEL_LOADING',provider_kind='local')
    assert known['reason_code']=='MEMORY_ADMISSION_RESERVE'
    private=failure_details(PermissionError('/private/credential?token=fixture-secret'))
    assert private['reason_code']=='UNCLASSIFIED_EXECUTION_FAILURE'
    assert 'fixture-secret' not in json.dumps(private)
