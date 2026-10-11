"""Local-only admission checks with a synthetic operator receipt; no model calls."""
import asyncio
import concurrent.futures
import hashlib
import json
import sqlite3
import threading
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


def parallel_receipt(path, *, residents=(), version='fixture-ollama', digests=None,
                     **kwargs):
    value = receipt(path, **kwargs)
    value.update(schema=admission.PARALLEL_SCHEMA, resident_leases=list(residents),
                 runtime_version=version,
                 model_digests={'gemma3:1b': 'a' * 64} if digests is None else digests)
    path.write_text(json.dumps(value), encoding='utf-8')
    return value


def measured_slots(tmp_path, monkeypatch, slots):
    profile = tmp_path / 'measured-profile.json'
    value = json.loads(profile.read_text(encoding='utf-8'))
    value['normal_concurrency'] = slots
    raw = json.dumps(value).encode()
    profile.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('OLLAMA_NUM_PARALLEL', str(slots))
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()


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
                      'runtime_version':'fixture-ollama',
                      'models':{'gemma3:1b':{'peak_mib':1024,'digest':'a'*64}}}).encode()
    profile = tmp_path / 'measured-profile.json'
    profile.write_bytes(raw)
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE',str(profile))
    monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    compute_profile.load_compute_profile.cache_clear()
    compute_profile.runtime_compute_profile.cache_clear()
    monkeypatch.setattr(compute_profile, 'verify_runtime_identity', lambda *_, **__: None)
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


def test_measured_claim_rechecks_live_runtime_identity(tmp_path, backend, monkeypatch):
    receipt(backend)
    def changed_runtime(*_args, **kwargs):
        assert kwargs['timeout'] == 1
        raise RuntimeError('Model digest differs from measured envelope')
    monkeypatch.setattr(compute_profile, 'verify_runtime_identity', changed_runtime)
    q = queue(tmp_path)
    job = q.submit(agent='planner', prompt='identity drift', ram_mb=1024)
    assert q.claim('one', [LOCAL]) is None
    assert q.get(job['id'])['status'] == 'queued'
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT COUNT(*) FROM backend_admission').fetchone() == (0,)


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
    # Windows time.time() can return the same tick as completion above, which
    # would make the receipt appear not-strictly-newer and skip the completed
    # job's memory credit. Wait until the clock advances past completion, then
    # write a strictly-newer observation with the intended headroom.
    with sqlite3.connect(q.db_path) as db:
        completed_at = db.execute(
            'SELECT captured_after FROM backend_admission_refresh WHERE endpoint=?',
            (ENDPOINT,)).fetchone()[0]
    while time.time() <= completed_at:
        time.sleep(0.001)
    receipt(backend, available=4000)
    assert q.claim('two', [LOCAL])['id'] == next_job['id']


@pytest.mark.parametrize('slots', [2, 3])
def test_measured_queue_claims_exact_parallel_slots_atomically(tmp_path, backend, monkeypatch, slots):
    measured_slots(tmp_path, monkeypatch, slots)
    parallel_receipt(backend, available=11000)
    q = JobQueue(tmp_path / 'parallel.db', QueuePolicy(global_concurrency=slots,
                                                      local_ram_mb=32768))
    provider = Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, slots)
    jobs = [q.submit(agent=agent, prompt=agent, ram_mb=2500)
            for agent in ('planner', 'critic', 'research')[:slots]]
    claimed = [q.claim(f'worker-{index}', [provider]) for index in range(slots)]
    assert {job['id'] for job in claimed} == {job['id'] for job in jobs}
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT COUNT(*),SUM(demand_mib) FROM backend_admission').fetchone() == (slots, slots * 2500)
    c = admission.transaction(q.db_path)
    try:
        with pytest.raises(PermissionError, match='occupied'):
            admission.reserve(c, ENDPOINT, 'extra', 2500,
                              max_leases=slots)
        c.rollback()
    finally:
        c.close()


def test_independent_sqlite_claimers_cannot_exceed_measured_n2(tmp_path, backend, monkeypatch):
    measured_slots(tmp_path, monkeypatch, 2)
    parallel_receipt(backend, available=11000)
    policy = QueuePolicy(global_concurrency=2, local_ram_mb=32768)
    db = tmp_path / 'atomic.db'
    queues = [JobQueue(db, policy) for _ in range(3)]
    provider = Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 3)
    jobs = [queues[0].submit(agent=agent, prompt=agent, ram_mb=2500)
            for agent in ('planner', 'critic', 'research')]
    gate = threading.Barrier(3)
    def claim(index):
        gate.wait(timeout=5)
        return queues[index].claim(f'worker-{index}', [provider])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        claims = list(pool.map(claim, range(3)))
    assert sum(job is not None for job in claims) == 2
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT COUNT(*) FROM backend_admission').fetchone() == (2,)
        assert c.execute("SELECT COUNT(*) FROM compute_jobs WHERE status='running'").fetchone() == (2,)
    assert len({job['id'] for job in claims if job}) == 2
    assert {job['id'] for job in claims if job}.issubset({job['id'] for job in jobs})


def test_parallel_pending_demands_accumulate_before_backend_allocation(tmp_path, backend, monkeypatch):
    measured_slots(tmp_path, monkeypatch, 2)
    parallel_receipt(backend, available=7000)
    q = JobQueue(tmp_path / 'pending-sum.db', QueuePolicy(global_concurrency=2,
                                                         local_ram_mb=32768))
    provider = Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 2)
    first = q.submit(agent='planner', prompt='first', ram_mb=4000)
    second = q.submit(agent='critic', prompt='second', ram_mb=4000)
    assert q.claim('one', [provider])['id'] == first['id']
    assert q.claim('two', [provider]) is None
    assert q.get(second['id'])['status'] == 'queued'
    with sqlite3.connect(q.db_path) as c:
        assert c.execute('SELECT COUNT(*) FROM backend_admission').fetchone() == (1,)


def test_parallel_receipt_credits_only_confirmed_residents_and_retains_cancelled_lease(tmp_path, backend, monkeypatch):
    measured_slots(tmp_path, monkeypatch, 2)
    parallel_receipt(backend, available=11000)
    q = JobQueue(tmp_path / 'resident.db', QueuePolicy(global_concurrency=2,
                                                      local_ram_mb=32768))
    provider = Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 2)
    first = q.submit(agent='planner', prompt='first', ram_mb=4000)
    second = q.submit(agent='critic', prompt='second', ram_mb=4000)
    assert q.claim('one', [provider])['id'] == first['id']
    assert q.claim('two', [provider])['id'] == second['id']
    c = admission.transaction(q.db_path)
    try:
        admission.dispatch(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    # A marker captured before dispatch cannot make its allocation disappear.
    with sqlite3.connect(q.db_path) as db:
        dispatched_at = db.execute('SELECT dispatched_at FROM backend_admission WHERE job_id=?',
                                   (first['id'],)).fetchone()[0]
    parallel_receipt(backend, residents=[first['id']], available=7000,
                     captured=dispatched_at)
    c = admission.transaction(q.db_path)
    try:
        with pytest.raises(PermissionError, match='reserve reached'):
            admission.check(c, ENDPOINT, second['id'])
        c.rollback()
    finally:
        c.close()
    parallel_receipt(backend, residents=[], available=7000)
    c = admission.transaction(q.db_path)
    try:
        with pytest.raises(PermissionError, match='reserve reached'):
            admission.check(c, ENDPOINT, second['id'])
        c.rollback()
    finally:
        c.close()
    parallel_receipt(backend, residents=[first['id']], available=7000)
    c = admission.transaction(q.db_path)
    try:
        admission.check(c, ENDPOINT, second['id'])
        admission.dispatch(c, ENDPOINT, second['id'])
        c.commit()
    finally:
        c.close()
    # Windows time.time() can return the same tick as the dispatch above,
    # which would make the receipt appear not-strictly-newer and skip the
    # second job's resident credit. Wait until the clock advances past it.
    with sqlite3.connect(q.db_path) as db:
        second_dispatched_at = db.execute(
            'SELECT dispatched_at FROM backend_admission WHERE job_id=?',
            (second['id'],)).fetchone()[0]
    while time.time() <= second_dispatched_at:
        time.sleep(0.001)
    parallel_receipt(backend, residents=[first['id'], second['id']], available=3000)
    c = admission.transaction(q.db_path)
    try:
        admission.check(c, ENDPOINT, first['id'])
        admission.check(c, ENDPOINT, second['id'])
        c.commit()
    finally:
        c.close()
    q.cancel(first['id'])
    third = q.submit(agent='research', prompt='third', ram_mb=4000)
    assert q.claim('three', [provider]) is None
    with sqlite3.connect(q.db_path) as c:
        assert c.execute("SELECT state FROM backend_admission WHERE job_id=?", (first['id'],)).fetchone() == ('uncertain',)
    c = admission.transaction(q.db_path)
    try:
        admission.completed(c, ENDPOINT, first['id'])
        c.commit()
    finally:
        c.close()
    assert q.claim('three', [provider]) is None  # receipt predates completion
    receipt_after = parallel_receipt(backend, residents=[second['id']], available=7000)
    with sqlite3.connect(q.db_path) as c:
        completed_at = c.execute('SELECT captured_after FROM backend_admission_refresh').fetchone()[0]
    if receipt_after['captured_at'] <= completed_at:
        while time.time() <= completed_at:
            time.sleep(0.001)
        parallel_receipt(backend, residents=[second['id']], available=7000)
    assert q.claim('three', [provider])['id'] == third['id']


@pytest.mark.parametrize('mutation', [
    {'resident_leases': ['duplicate', 'duplicate']},
    {'resident_leases': 'not-a-list'},
    {'runtime_version': 'wrong-version'},
    {'model_digests': {'gemma3:1b': 'b' * 64}},
    {'scope_complete': False},
    {'captured_at': 0},
])
def test_parallel_claim_fails_closed_on_bad_receipt(tmp_path, backend, monkeypatch, mutation):
    measured_slots(tmp_path, monkeypatch, 2)
    value = parallel_receipt(backend)
    value.update(mutation)
    backend.write_text(json.dumps(value), encoding='utf-8')
    q = JobQueue(tmp_path / 'bad-parallel.db', QueuePolicy(global_concurrency=2,
                                                          local_ram_mb=32768))
    job = q.submit(agent='planner', prompt='held', ram_mb=1024)
    assert q.claim('one', [Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 2)]) is None
    assert q.get(job['id'])['status'] == 'queued'


def test_parallel_duplicate_json_field_is_rejected(tmp_path, backend, monkeypatch):
    measured_slots(tmp_path, monkeypatch, 2)
    value = parallel_receipt(backend)
    backend.write_text(json.dumps(value)[:-1] + ',"resident_leases":[]}', encoding='utf-8')
    with pytest.raises(PermissionError, match='receipt unavailable'):
        admission.observation(ENDPOINT)


def test_v1_receipt_keeps_measured_n1_but_cannot_admit_parallel(tmp_path, backend, monkeypatch):
    measured_slots(tmp_path, monkeypatch, 2)
    receipt(backend)
    q = JobQueue(tmp_path / 'v1.db', QueuePolicy(global_concurrency=2, local_ram_mb=32768))
    job = q.submit(agent='planner', prompt='parallel held', ram_mb=1024)
    assert q.claim('one', [Provider('ollama-fast', 'local', 'gemma3:1b', 32768, 0, 2)]) is None
    assert q.get(job['id'])['status'] == 'queued'
    direct = admission.transaction(str(tmp_path / 'v1-direct.db'))
    try:
        admission.reserve_model(direct, ENDPOINT, 'single', 'gemma3:1b', 1024)
        admission.dispatch(direct, ENDPOINT, 'single')
        direct.commit()
    finally:
        direct.close()


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
        assert {row[1]: row[5] for row in c.execute('PRAGMA table_info(backend_admission)')}['job_id'] == 2
        assert c.execute('SELECT job_id FROM backend_admission').fetchone() == ('legacy',)
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
