"""Local-only admission checks with a synthetic operator receipt; no model calls."""
import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app import backend_admission as admission
from app.direct_stream import infer
from app.job_queue import JobQueue, Provider, QueuePolicy


ENDPOINT = 'http://fixture'
LOCAL = Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 1)


def receipt(path, *, available=12000, instance='backend-1', scope=True, captured=None):
    value = {'schema': admission.SCHEMA, 'endpoint': ENDPOINT, 'instance': instance,
             'boot_id': 'vm-1', 'scope_complete': scope, 'capacity_mib': 15654,
             'available_mib': available, 'captured_at': time.time() if captured is None else captured}
    path.write_text(json.dumps(value), encoding='utf-8')
    return value


@pytest.fixture
def backend(tmp_path, monkeypatch):
    path = tmp_path / 'backend-receipt.json'
    monkeypatch.setenv('PRIME_BACKEND_MEMORY_RECEIPT', str(path))
    monkeypatch.setenv('OLLAMA_BASE_URL', ENDPOINT)
    return path


def queue(tmp_path):
    return JobQueue(tmp_path / 'queue.db', QueuePolicy(global_concurrency=1, local_ram_mb=32768))


def test_missing_incomplete_and_mismatched_receipts_hold_claim(tmp_path, backend):
    q = queue(tmp_path)
    q.submit(agent='planner', prompt='fixture', ram_mb=1024)
    assert q.claim('one', [LOCAL]) is None
    receipt(backend, scope=False)
    assert q.claim('one', [LOCAL]) is None
    receipt(backend, instance='backend-2')
    # A valid identity and complete scope admit small declared work.
    assert q.claim('one', [LOCAL]) is not None


def test_backend_limit_and_cancellation_completion_accounting(tmp_path, backend):
    receipt(backend)
    q = queue(tmp_path)
    oversized = q.submit(agent='planner', prompt='fixture', ram_mb=20480)
    assert q.claim('one', [LOCAL]) is None
    q.cancel(oversized['id'])
    first = q.submit(agent='planner', prompt='fixture', ram_mb=6000)
    assert q.claim('one', [LOCAL])['id'] == first['id']
    c = admission.transaction(q.db_path)
    try:
        admission.dispatch(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    # Free headroom already includes resident model allocation. Only reserve
    # remains to check during a stream; subtracting 6000 again would reject.
    receipt(backend, available=4000)
    c = admission.transaction(q.db_path)
    try:
        admission.check(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    q.cancel(first['id'])
    next_job = q.submit(agent='critic', prompt='fixture', ram_mb=1024)
    assert q.claim('two', [LOCAL]) is None
    c = admission.transaction(q.db_path)
    try:
        admission.completed(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    assert q.claim('two', [LOCAL]) is None  # receipt predates completion
    receipt(backend, available=4000)
    assert q.claim('two', [LOCAL])['id'] == next_job['id']


def test_pending_demand_is_rechecked_at_dispatch(tmp_path, backend):
    receipt(backend, available=12000)
    c = admission.transaction(str(tmp_path / 'pending.db'))
    try:
        admission.reserve(c, ENDPOINT, 'pending', 6000)
        c.commit()
        receipt(backend, available=3000)
        with pytest.raises(PermissionError):
            admission.check(c, ENDPOINT, 'pending')
        with pytest.raises(PermissionError):
            admission.dispatch(c, ENDPOINT, 'pending')
        assert c.execute('SELECT state,demand_mib FROM backend_admission').fetchone() == ('pending', 6000)
    finally:
        c.close()


def test_legacy_pending_lease_without_demand_stays_held(tmp_path, backend):
    receipt(backend)
    db = tmp_path / 'legacy.db'
    with sqlite3.connect(db) as c:
        c.execute('''CREATE TABLE backend_admission (endpoint TEXT PRIMARY KEY,job_id TEXT,
                     instance TEXT,boot_id TEXT,state TEXT,refresh_after REAL DEFAULT 0)''')
        c.execute("INSERT INTO backend_admission(endpoint,job_id,instance,boot_id,state) VALUES(?,?,?,?,?)",
                  (ENDPOINT, 'legacy', 'backend-1', 'vm-1', 'pending'))
    c = admission.transaction(str(db))
    try:
        with pytest.raises(PermissionError, match='pending memory demand'):
            admission.dispatch(c, ENDPOINT, 'legacy')
        assert c.execute('SELECT state FROM backend_admission').fetchone() == ('pending',)
    finally:
        c.close()


def test_stream_terminal_releases_but_disconnect_retains_lease(tmp_path, backend, monkeypatch):
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'direct.db'))
    receipt(backend)
    settings = SimpleNamespace(ollama_base_url=ENDPOINT, keep_alive=0,
                               context_tokens=128, max_output_tokens=8)
    provider = SimpleNamespace(model='gemma3:1b')

    async def call(response):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
        try:
            with patch('app.direct_stream.httpx.AsyncClient', return_value=client):
                return await infer({'timeout_seconds': 1, 'prompt': 'fixture', 'ram_mb': 1024},
                                   provider, settings=settings, capacity=lambda _: None,
                                   options=lambda: {})
        finally:
            await client.aclose()

    good = httpx.Response(200, text='{"done":true,"message":{"content":"ok"}}\n')
    assert asyncio.run(call(good))['result'] == 'ok'
    receipt(backend)
    broken = httpx.Response(200, text='{"message":{"content":"partial"}}\n')
    with pytest.raises(RuntimeError, match='Incomplete'):
        asyncio.run(call(broken))
    receipt(backend)
    with pytest.raises(PermissionError, match='occupied'):
        asyncio.run(call(good))


def test_nonboolean_stream_done_retains_uncertain_lease(tmp_path, backend, monkeypatch):
    db = tmp_path / 'malformed.db'
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(db))
    receipt(backend)
    settings = SimpleNamespace(ollama_base_url=ENDPOINT, keep_alive=0,
                               context_tokens=128, max_output_tokens=8)
    provider = SimpleNamespace(model='gemma3:1b')

    async def call():
        response = httpx.Response(200, text='{"done":"false","message":{"content":"partial"}}\n')
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
        try:
            with patch('app.direct_stream.httpx.AsyncClient', return_value=client):
                with pytest.raises(RuntimeError, match='Malformed model completion'):
                    await infer({'id': 'job', 'timeout_seconds': 1, 'prompt': 'fixture', 'ram_mb': 1024},
                                provider, settings=settings, capacity=lambda _: None, options=lambda: {})
        finally:
            await client.aclose()

    asyncio.run(call())
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT state FROM backend_admission').fetchone() == ('uncertain',)
