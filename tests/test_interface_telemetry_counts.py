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
    assert module.agent_activity()=={
        'a01':{'status':'running','observed_at':'2026-10-15T02:00:00Z'},
        'a02':{'status':'queued','observed_at':'2026-10-15T03:00:00Z'}}


def test_agent_activity_requires_agent_identity_column(draft):
    module,root=draft
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,status TEXT)')
    assert module.agent_activity() is None
