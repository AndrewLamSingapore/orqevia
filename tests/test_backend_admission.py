"""Local-only admission checks with a synthetic operator receipt; no model calls."""
import asyncio
import hashlib
import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app import backend_admission as admission
from app import compute_profile
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


def receipt_after_completion(path, db):
    with sqlite3.connect(db) as c:
        completed_at = c.execute('SELECT captured_after FROM backend_admission_refresh WHERE endpoint=?',
                                 (ENDPOINT,)).fetchone()[0]
    # Windows time.time() can return the same tick as completion. A measured
    # admission requires a strictly newer sample, not an equal timestamp.
    while time.time() <= completed_at:
        time.sleep(0.001)
    receipt(path)


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'measured')
    path = tmp_path / 'backend-receipt.json'
    monkeypatch.setenv('PRIME_BACKEND_MEMORY_RECEIPT', str(path))
    monkeypatch.setenv('OLLAMA_BASE_URL', ENDPOINT)
    raw = json.dumps({'schema':'abex.measured-compute.v1','normal_concurrency':1,
                      'minimum_available_mib':1,'context_tokens':128,'output_limit':8,
                      'models':{'gemma3:1b':{'peak_mib':1024}}}).encode()
    profile = tmp_path / 'measured-profile.json'
    profile.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE',str(profile))
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()
    yield path
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()


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


def test_stale_receipt_holds_measured_claim(tmp_path, backend):
    q = queue(tmp_path)
    q.submit(agent='planner', prompt='fixture', ram_mb=1024)
    receipt(backend, captured=time.time() - admission.MAX_AGE_SECONDS - 1)
    assert q.claim('one', [LOCAL]) is None


def test_golden_n1_runs_without_telemetry_and_retains_one_lease(tmp_path, monkeypatch):
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE', 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('OLLAMA_BASE_URL', ENDPOINT)
    q = queue(tmp_path)
    first = q.submit(agent='planner', prompt='baseline', ram_mb=1024)
    assert q.claim('one', [LOCAL])['id'] == first['id']
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT instance,boot_id,state,demand_mib FROM backend_admission').fetchone() == ('', '', 'pending', 1024)
    second = q.submit(agent='critic', prompt='waiting', ram_mb=1024)
    assert q.claim('two', [LOCAL]) is None
    c = admission.transaction(q.db_path)
    try:
        admission.dispatch(c, ENDPOINT, first['id'])
        admission.check(c, ENDPOINT, first['id'])
        admission.completed(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    q.finish(first['id'], result='ok')
    assert q.claim('two', [LOCAL])['id'] == second['id']


def test_golden_n1_rejects_heavy_and_n2_without_measured_telemetry(tmp_path, monkeypatch):
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE', 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('OLLAMA_BASE_URL', ENDPOINT)
    q = queue(tmp_path)
    heavy = q.submit(agent='planner', prompt='heavy', ram_mb=1025)
    assert q.claim('one', [LOCAL]) is None
    assert q.get(heavy['id'])['status'] == 'queued'
    n2 = JobQueue(tmp_path / 'n2.db', QueuePolicy(global_concurrency=2, local_ram_mb=32768))
    n2.submit(agent='planner', prompt='n2', ram_mb=1024)
    assert n2.claim('one', [LOCAL]) is None


def test_golden_n1_rejects_underdeclared_unobserved_model(tmp_path, monkeypatch):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv('OLLAMA_BASE_URL', ENDPOINT)
    q = queue(tmp_path)
    job = q.submit(agent='planner', prompt='underdeclared', model_role='deep', ram_mb=1024)
    unobserved = Provider('ollama-deep', 'local', 'qwen3:14b', 32768, 0, 1)
    assert q.claim('one', [unobserved]) is None
    assert q.get(job['id'])['status'] == 'queued'
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT COUNT(*) FROM backend_admission').fetchone() == (0,)


@pytest.mark.parametrize('model', sorted(admission.GOLDEN_MODELS))
def test_golden_n1_accepts_only_observed_model_names(tmp_path, monkeypatch, model):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    c = admission.transaction(str(tmp_path / 'models.db'))
    try:
        admission.reserve_model(c, ENDPOINT, 'one', model, 1024)
        assert c.execute('SELECT demand_mib FROM backend_admission').fetchone() == (1024,)
    finally:
        c.close()


def test_golden_n1_refuses_unidentified_direct_reservation(tmp_path, monkeypatch):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    c = admission.transaction(str(tmp_path / 'unidentified.db'))
    try:
        with pytest.raises(PermissionError, match='requires measured'):
            admission.reserve(c, ENDPOINT, 'one', 1024)
    finally:
        c.close()


def test_invalid_mode_fails_closed(monkeypatch):
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'invalid')
    with pytest.raises(PermissionError, match='invalid local inference admission mode'):
        admission.admission_mode()


@pytest.mark.parametrize('guard', ('PRIME_BACKEND_MEMORY_RECEIPT',
                                   'PRIME_MEASURED_COMPUTE_PROFILE',
                                   'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                                   'PRIME_SSD_THERMAL_ENFORCE'))
def test_golden_mode_refuses_explicit_measured_guard(monkeypatch, guard):
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv(guard, '1')
    with pytest.raises(PermissionError, match='measured admission settings'):
        admission.admission_mode()


def test_queue_uses_measured_peak_not_underdeclared_job_ram(tmp_path, backend, monkeypatch):
    profile = tmp_path / 'measured-profile.json'
    value = json.loads(profile.read_text(encoding='utf-8'))
    value['models']['gemma3:1b']['peak_mib'] = 6000
    raw = json.dumps(value).encode()
    profile.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()
    q = queue(tmp_path)
    job = q.submit(agent='planner', prompt='underdeclared', ram_mb=1024)
    receipt(backend, available=7000)
    assert q.claim('one', [LOCAL]) is None
    assert q.get(job['id'])['status'] == 'queued'
    receipt(backend, available=9000)
    assert q.claim('one', [LOCAL])['id'] == job['id']
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT demand_mib FROM backend_admission').fetchone() == (6000,)


def test_missing_measured_peak_holds_local_claim(tmp_path, backend):
    receipt(backend)
    (tmp_path / 'measured-profile.json').unlink()
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()
    q = queue(tmp_path)
    job = q.submit(agent='planner', prompt='no measured peak', ram_mb=1024)
    assert q.claim('one', [LOCAL]) is None
    assert q.get(job['id'])['status'] == 'queued'


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
                # Allow Windows CI time for SQLite and receipt setup; the
                # assertion below tests lease completion, not a 1s deadline.
                return await infer({'timeout_seconds': 10, 'prompt': 'fixture', 'ram_mb': 1024},
                                   provider, settings=settings, capacity=lambda _: None,
                                   options=lambda: {})
        finally:
            await client.aclose()

    good = httpx.Response(200, text='{"done":true,"message":{"content":"ok"}}\n')
    assert asyncio.run(call(good))['result'] == 'ok'
    receipt_after_completion(backend, tmp_path / 'direct.db')
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
