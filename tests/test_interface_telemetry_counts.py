"""Read-only store fixture checks; no live application or model calls."""
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

@pytest.fixture
def draft(monkeypatch,tmp_path):
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    from app import interface_telemetry
    return interface_telemetry,tmp_path

def test_missing_stores_are_unavailable_and_not_created(draft):
    module,root=draft
    values=module.telemetry_store_counts()
    assert values['objectives']=={'status':'UNAVAILABLE','count':None}
    assert values['compute_jobs']=={'status':'UNAVAILABLE','count':None,'active_count':None}
    assert not list(root.iterdir())

def test_complete_read_only_counts_and_no_unrelated_evidence_access(draft,monkeypatch):
    module,root=draft
    with sqlite3.connect(root/'objectives.db') as db:
        db.execute('CREATE TABLE objectives(id TEXT)');db.executemany('INSERT INTO objectives VALUES(?)',[('x',),('y',)])
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
        db.executemany('INSERT INTO compute_jobs VALUES(?,?)',[(str(i),state) for i,state in enumerate(['queued','running','awaiting_approval','completed','failed'])])
    (root/'artifacts').mkdir();(root/'action-records.jsonl').write_text('invalid unrelated evidence',encoding='utf8')
    original_iterdir=Path.iterdir;original_open=Path.open
    def guarded_iterdir(path):
        if path.name=='artifacts':raise AssertionError('Telemetry scanned unrelated artifact files')
        return original_iterdir(path)
    def guarded_open(path,*args,**kwargs):
        if path.name in ('action-records.jsonl','metadata.json','pwa-sessions.db'):raise AssertionError('Telemetry opened unrelated evidence')
        return original_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'iterdir',guarded_iterdir);monkeypatch.setattr(Path,'open',guarded_open)
    from app import interface_node
    monkeypatch.setattr(interface_node,'evidence_aggregates',lambda: pytest.fail('Full evidence aggregation invoked'))
    values=module.telemetry_store_counts()
    assert values['objectives']=={'status':'OBSERVED','count':2}
    assert values['compute_jobs']=={'status':'OBSERVED','count':5,'active_count':3}

def test_empty_existing_stores_are_observed_zero(draft):
    module,root=draft
    with sqlite3.connect(root/'objectives.db') as db:db.execute('CREATE TABLE objectives(id TEXT)')
    with sqlite3.connect(root/'compute-queue.db') as db:db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
    values=module.telemetry_store_counts()
    assert values['objectives']['count']==0 and values['objectives']['status']=='OBSERVED'
    assert values['compute_jobs']['active_count']==0 and values['compute_jobs']['status']=='OBSERVED'

def test_corrupt_or_wrong_schema_database_is_unavailable_not_zero(draft):
    module,root=draft
    (root/'objectives.db').write_bytes(b'not a database')
    with sqlite3.connect(root/'compute-queue.db') as db:db.execute('CREATE TABLE other_table(id TEXT)')
    values=module.telemetry_store_counts()
    assert values['objectives']['count'] is None and values['objectives']['status']=='UNAVAILABLE'
    assert values['compute_jobs']['active_count'] is None and values['compute_jobs']['status']=='UNAVAILABLE'


def test_locked_store_is_bounded_and_unavailable_without_mutation(draft):
    import time
    module,root=draft
    path=root/'compute-queue.db'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
    locked=sqlite3.connect(path)
    try:
        locked.execute('BEGIN EXCLUSIVE')
        started=time.monotonic();values=module.telemetry_store_counts();elapsed=time.monotonic()-started
        assert values['compute_jobs']=={'status':'UNAVAILABLE','count':None,'active_count':None}
        assert elapsed<1.5
    finally:
        locked.rollback();locked.close()


def test_query_budget_interruption_never_becomes_a_partial_or_zero_count(draft,monkeypatch):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
        db.executemany('INSERT INTO compute_jobs VALUES(?,?)',[(str(i),'running') for i in range(10000)])
    ticks=iter([0.0,1.0])
    monkeypatch.setattr(module.time,'monotonic',lambda: next(ticks,1.0))
    values=module.telemetry_store_counts()
    assert values['compute_jobs']=={'status':'UNAVAILABLE','count':None,'active_count':None}


def test_agent_activity_classifies_queue_state_without_inventing_liveness(draft):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,updated_at TEXT)')
        db.executemany('INSERT INTO compute_jobs VALUES(?,?,?,?)',[
            ('1','a01','completed','2026-10-15T01:00:00Z'),
            ('2','a01','running','2026-10-15T02:00:00Z'),
            ('3','a02','queued','2026-10-15T03:00:00Z')])
    activity=module.agent_activity()
    assert {aid:(row['status'],row['observed_at']) for aid,row in activity.items()}=={
        'a01':('running','2026-10-15T02:00:00Z'),
        'a02':('queued','2026-10-15T03:00:00Z')}
    assert activity['a01']['last_success']['job_id']=='1'
    assert activity['a01']['latest_task']['job_id']=='2'
    assert activity['a02']['last_failure'] is None


def test_later_transition_of_older_job_supersedes_last_inserted_row_and_joins_parent_task(draft):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,updated_at TEXT,completed_at TEXT)')
        db.executemany('INSERT INTO compute_jobs VALUES(?,?,?,?,?)',[
            ('older-insert','a01','completed','2026-10-15T03:00:00Z','2026-10-15T03:00:00Z'),
            ('later-insert','a01','failed','2026-10-15T02:00:00Z','2026-10-15T02:00:00Z')])
    with sqlite3.connect(root/'objectives.db') as db:
        db.execute('CREATE TABLE objectives(id TEXT,steps_json TEXT)')
        db.execute('INSERT INTO objectives VALUES(?,?)',('parent-task','[{"dispatch":{"job":{"id":"older-insert"}}}]'))
    activity=module.agent_activity()['a01']
    assert activity['latest_task']['job_id']=='older-insert'
    assert activity['latest_task']['task_id']=='parent-task'
    assert activity['latest_task']['task_id_status']=='OBJECTIVE_STORE_JOIN'
    assert activity['last_failure']['job_id']=='later-insert'
    assert activity['last_failure']['task_id'] is None
    assert activity['history_count']==2


def test_unorderable_newest_insertion_does_not_resurrect_older_success(draft):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,updated_at TEXT)')
        db.executemany('INSERT INTO compute_jobs VALUES(?,?,?,?)',[
            ('valid-old','a01','completed','2026-10-15T03:00:00Z'),
            ('invalid-new','a01','failed','2026-10-15T04:00:00')])
    activity=module.agent_activity()['a01']
    assert activity['latest_task']['job_id']=='invalid-new'
    assert activity['ordering']=='LATEST_INSERTED_TASK_TIMESTAMP_UNORDERABLE'
    assert activity['last_success']['job_id']=='valid-old'


def test_activity_errors_are_fixed_classifications_and_store_is_read_only(draft):
    module,root=draft
    path=root/'compute-queue.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,updated_at TEXT,error TEXT,prompt TEXT,result TEXT)')
        db.execute('INSERT INTO compute_jobs VALUES(?,?,?,?,?,?,?)',
                   ('failed','a01','failed','2026-10-15T03:00:00Z','private server body','private prompt','private answer'))
    before=path.read_bytes()
    activity=module.agent_activity()['a01']
    assert activity['last_failure']['error_code']=='EXECUTION_FAILURE'
    assert 'private' not in str(activity)
    assert path.read_bytes()==before


def test_agent_activity_requires_agent_identity_column(draft):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
    assert module.agent_activity() is None
