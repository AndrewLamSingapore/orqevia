"""Durable local backend admission, with measured multi-lease accounting.

Golden N=1 uses only an atomic lease. Measured admission additionally requires
an operator-side receipt produced outside PRIME. A path alone is not an
attestation: deployment must make it atomic and read-only to PRIME, and the
producer must verify effective ancestor and VM limits.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path


SCHEMA = 'prime.backend-memory.v1'
PARALLEL_SCHEMA = 'prime.backend-memory.v2'
MAX_AGE_SECONDS = 2.0
RESERVE_MIB = 2048
BASELINE_MAX_DEMAND_MIB = 1024
GOLDEN_MODELS = frozenset(('gemma3:1b', 'gemma3:4b', 'embeddinggemma:300m-qat-q4_0'))


def admission_mode() -> str:
    """Require an explicit opt-in for measured guards and reject mixed modes."""
    mode = os.getenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    if mode not in ('golden_n1', 'measured'):
        raise PermissionError('invalid local inference admission mode')
    if mode == 'golden_n1' and any(os.getenv(name, '').strip() for name in (
            'PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
            'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE')):
        raise PermissionError('measured admission settings require measured mode')
    return mode


def require_model(model: str) -> None:
    if admission_mode() == 'golden_n1' and (type(model) is not str or model not in GOLDEN_MODELS):
        raise PermissionError('model requires measured local inference admission')


def _unique_object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate backend receipt field')
        value[key] = item
    return value


def observation(endpoint: str, *, now: float | None = None) -> dict:
    path = os.getenv('PRIME_BACKEND_MEMORY_RECEIPT', '')
    if not path or not Path(path).is_absolute():
        raise PermissionError('trusted backend memory receipt unavailable')
    try:
        sample = json.loads(Path(path).read_text(encoding='utf-8'),
                            object_pairs_hook=_unique_object_pairs)
    except (OSError, ValueError, UnicodeError) as exc:
        raise PermissionError('trusted backend memory receipt unavailable') from exc
    now = time.time() if now is None else now
    if (not isinstance(sample, dict) or sample.get('schema') not in (SCHEMA, PARALLEL_SCHEMA)
            or sample.get('endpoint') != endpoint):
        raise PermissionError('backend receipt scope mismatch')
    if not all(isinstance(sample.get(k), str) and sample[k] for k in ('instance', 'boot_id')):
        raise PermissionError('backend identity unknown')
    if sample.get('scope_complete') is not True:
        raise PermissionError('effective backend memory scope unknown')
    cap, free, captured = (sample.get(k) for k in ('capacity_mib', 'available_mib', 'captured_at'))
    if (type(cap) is not int or cap <= 0 or type(free) is not int or not 0 <= free <= cap
            or type(captured) not in (int, float) or not math.isfinite(captured)
            or type(now) not in (int, float) or not math.isfinite(now)
            or not 0 <= now - captured <= MAX_AGE_SECONDS):
        raise PermissionError('invalid or stale backend memory receipt')
    if sample['schema'] == PARALLEL_SCHEMA:
        residents = sample.get('resident_leases')
        if (not isinstance(residents, list) or
                any(not isinstance(value, str) or not value for value in residents) or
                len(residents) != len(set(residents))):
            raise PermissionError('invalid backend resident lease receipt')
    return sample


def init(c: sqlite3.Connection) -> None:
    c.execute('''CREATE TABLE IF NOT EXISTS backend_admission (
        endpoint TEXT NOT NULL, job_id TEXT NOT NULL, instance TEXT NOT NULL,
        boot_id TEXT NOT NULL, state TEXT NOT NULL, demand_mib INTEGER NOT NULL,
        refresh_after REAL NOT NULL DEFAULT 0, dispatched_at REAL NOT NULL DEFAULT 0,
        max_leases INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(endpoint,job_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS backend_admission_refresh (
        endpoint TEXT PRIMARY KEY, captured_after REAL NOT NULL)''')
    # Pre-release databases may contain leases without a recorded peak. Leave
    # those leases in place and fail closed rather than inventing their demand.
    if 'demand_mib' not in {row[1] for row in c.execute('PRAGMA table_info(backend_admission)')}:
        c.execute('ALTER TABLE backend_admission ADD COLUMN demand_mib INTEGER')
    columns = {row[1]: row[5] for row in c.execute('PRAGMA table_info(backend_admission)')}
    if 'dispatched_at' not in columns:
        c.execute('ALTER TABLE backend_admission ADD COLUMN dispatched_at REAL NOT NULL DEFAULT 0')
    if 'max_leases' not in columns:
        c.execute('ALTER TABLE backend_admission ADD COLUMN max_leases INTEGER NOT NULL DEFAULT 1')
    if columns.get('endpoint') == 1 and columns.get('job_id') == 0:
        # Preserve legacy endpoint leases, including uncertain ones, while
        # replacing the endpoint-only key under the caller's SQLite transaction.
        c.execute('''CREATE TABLE backend_admission_multi (
            endpoint TEXT NOT NULL, job_id TEXT NOT NULL, instance TEXT NOT NULL,
            boot_id TEXT NOT NULL, state TEXT NOT NULL, demand_mib INTEGER,
            refresh_after REAL NOT NULL DEFAULT 0, dispatched_at REAL NOT NULL DEFAULT 0,
            max_leases INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(endpoint,job_id))''')
        c.execute('''INSERT INTO backend_admission_multi
            (endpoint,job_id,instance,boot_id,state,demand_mib,refresh_after,dispatched_at,max_leases)
            SELECT endpoint,job_id,instance,boot_id,state,demand_mib,refresh_after,dispatched_at,max_leases
            FROM backend_admission''')
        c.execute('DROP TABLE backend_admission')
        c.execute('ALTER TABLE backend_admission_multi RENAME TO backend_admission')
    elif columns.get('endpoint') != 1 or columns.get('job_id') != 2:
        raise PermissionError('unsupported backend admission lease schema')


def _parallel_receipt(sample: dict, profile: dict | None) -> set[str]:
    """Accept only a fresh operator report that binds residents and model bytes."""
    if sample.get('schema') != PARALLEL_SCHEMA or not profile:
        raise PermissionError('parallel backend resident receipt required')
    residents = sample.get('resident_leases')
    if (not isinstance(residents, list) or
            any(not isinstance(value, str) or not value for value in residents) or
            len(residents) != len(set(residents))):
        raise PermissionError('invalid backend resident lease receipt')
    if (sample.get('runtime_version') != profile['runtime_version'] or
            not isinstance(sample.get('model_digests'), dict) or
            any(sample['model_digests'].get(name) != details['digest']
                for name, details in profile['models'].items())):
        raise PermissionError('backend runtime identity differs from measured envelope')
    return set(residents)


def _active_demand(c: sqlite3.Connection, endpoint: str, sample: dict,
                   max_leases: int) -> tuple[int, int]:
    rows = c.execute('''SELECT job_id,instance,boot_id,state,demand_mib,dispatched_at,max_leases
                        FROM backend_admission WHERE endpoint=?''', (endpoint,)).fetchall()
    if any(row[6] != max_leases for row in rows):
        raise PermissionError('backend inference lease mode mismatch')
    residents: set[str] = set()
    if max_leases > 1:
        from .compute_profile import runtime_compute_profile
        residents = _parallel_receipt(sample, runtime_compute_profile())
    demand = 0
    for job_id, instance, boot_id, state, peak, dispatched_at, _ in rows:
        if (instance != sample['instance'] or boot_id != sample['boot_id'] or
                state not in ('pending', 'running', 'uncertain') or
                type(peak) is not int or peak <= 0):
            raise PermissionError('backend inference lease or instance mismatch')
        if (max_leases > 1 and state in ('running', 'uncertain') and
                type(dispatched_at) in (int, float) and dispatched_at > 0 and
                sample['captured_at'] > dispatched_at and job_id in residents):
            continue  # Free memory already reflects this resident allocation.
        if max_leases == 1 and state in ('running', 'uncertain'):
            continue  # Legacy N=1 has no competing local lease to admit.
        demand += peak
    return len(rows), demand


def reserve(c: sqlite3.Connection, endpoint: str, job_id: str, demand_mib: int | None,
            sample: dict | None = None, *, model: str | None = None,
            max_leases: int = 1) -> None:
    mode = admission_mode()
    if mode == 'golden_n1':
        require_model(model)
        if sample is not None:
            raise PermissionError('measured backend sample requires measured admission')
        # Empty identity fields mean no backend identity was observed. The
        # endpoint row is still one atomic lease shared by every local caller.
        # This caps declared demand, not the observed memory use of a model.
        if demand_mib is None:
            demand_mib = 0  # ModelGateway has no caller-declared demand.
        if type(demand_mib) is not int or not 0 <= demand_mib <= BASELINE_MAX_DEMAND_MIB:
            raise PermissionError('declared memory demand requires measured admission')
        if c.execute('SELECT 1 FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone():
            raise PermissionError('backend inference lease occupied')
        c.execute('INSERT INTO backend_admission(endpoint,job_id,instance,boot_id,state,demand_mib) VALUES(?,?,?,?,?,?)',
                  (endpoint, job_id, '', '', 'pending', demand_mib))
        return
    sample = observation(endpoint) if sample is None else sample
    # Injected samples are only for tests; production always uses observation().
    if type(demand_mib) is not int or demand_mib <= 0:
        raise PermissionError('verified peak memory demand required')
    if type(max_leases) is not int or not 1 <= max_leases <= 3:
        raise PermissionError('invalid measured backend lease limit')
    from .ssd_thermal import require_for_demand
    require_for_demand(demand_mib)
    count, pending = _active_demand(c, endpoint, sample, max_leases)
    if count >= max_leases or c.execute(
            'SELECT 1 FROM backend_admission WHERE endpoint=? AND job_id=?',
            (endpoint, job_id)).fetchone():
        raise PermissionError('backend inference lease occupied')
    prior = c.execute('SELECT captured_after FROM backend_admission_refresh WHERE endpoint=?', (endpoint,)).fetchone()
    if prior and sample['captured_at'] <= prior[0]:
        raise PermissionError('new backend observation required after completion')
    if pending + demand_mib > min(sample['capacity_mib'], sample['available_mib']) - RESERVE_MIB:
        raise PermissionError('insufficient backend memory')
    c.execute('''INSERT INTO backend_admission
                 (endpoint,job_id,instance,boot_id,state,demand_mib,max_leases)
                 VALUES(?,?,?,?,?,?,?)''',
              (endpoint, job_id, sample['instance'], sample['boot_id'], 'pending', demand_mib, max_leases))


def reserve_model(c: sqlite3.Connection, endpoint: str, job_id: str,
                  model: str, requested_mib: int, *, global_concurrency: int = 1) -> None:
    """Reserve at least the measured peak; an untrusted job estimate cannot lower it."""
    if admission_mode() == 'golden_n1':
        if global_concurrency != 1:
            raise PermissionError('N>1 local inference requires measured admission')
        return reserve(c, endpoint, job_id, requested_mib, model=model)
    from .compute_profile import runtime_compute_profile, verify_runtime_identity

    profile = runtime_compute_profile()
    details = profile.get('models', {}).get(model) if profile else None
    peak = details.get('peak_mib') if isinstance(details, dict) else None
    if type(peak) is not int or peak <= 0:
        raise PermissionError('verified model peak memory demand required')
    if type(requested_mib) is not int or requested_mib < 0:
        raise PermissionError('invalid requested memory demand')
    if (type(global_concurrency) is not int or not 1 <= global_concurrency <= 3 or
            global_concurrency > profile['normal_concurrency']):
        raise PermissionError('local concurrency exceeds measured envelope')
    if global_concurrency > 1:
        try:
            parallel = int(os.getenv('OLLAMA_NUM_PARALLEL', ''))
        except ValueError:
            parallel = 0
        if parallel < global_concurrency:
            raise PermissionError('backend parallel limit below measured admission')
    try:
        # Claim holds SQLite's write lock; bound both live identity probes.
        verify_runtime_identity(profile, endpoint, timeout=1)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise PermissionError('measured backend runtime identity unavailable or mismatched') from exc
    reserve(c, endpoint, job_id, max(peak, requested_mib), max_leases=global_concurrency)


def check(c: sqlite3.Connection, endpoint: str, job_id: str, sample: dict | None = None) -> None:
    if admission_mode() == 'golden_n1':
        row = c.execute('SELECT job_id,instance,boot_id,state,demand_mib FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone()
        if (not row or row[0] != job_id or row[1:3] != ('', '') or
                row[3] not in ('pending', 'running') or
                type(row[4]) is not int or not 0 <= row[4] <= BASELINE_MAX_DEMAND_MIB):
            raise PermissionError('backend inference lease or mode mismatch')
        return
    sample = observation(endpoint) if sample is None else sample
    row = c.execute('''SELECT job_id,instance,boot_id,state,demand_mib,max_leases
                       FROM backend_admission WHERE endpoint=? AND job_id=?''', (endpoint, job_id)).fetchone()
    if not row or tuple(row[:3]) != (job_id, sample['instance'], sample['boot_id']) or row[3] not in ('pending', 'running'):
        raise PermissionError('backend inference lease or instance mismatch')
    from .ssd_thermal import require_for_demand
    require_for_demand(row[4])
    if row[3] == 'pending' and (type(row[4]) is not int or row[4] <= 0):
        raise PermissionError('verified pending memory demand required')
    _, pending = _active_demand(c, endpoint, sample, row[5])
    required = RESERVE_MIB + pending
    if sample['available_mib'] < required:
        raise PermissionError('backend memory reserve reached')


def dispatch(c: sqlite3.Connection, endpoint: str, job_id: str) -> None:
    # Recheck a fresh observation at the transition, not only at reservation.
    check(c, endpoint, job_id)
    changed = c.execute("""UPDATE backend_admission SET state='running',dispatched_at=?
                         WHERE endpoint=? AND job_id=? AND state='pending'""",
                        (time.time(), endpoint, job_id))
    if changed.rowcount != 1:
        raise PermissionError('backend pending lease required')


def cancel(c: sqlite3.Connection, endpoint: str, job_id: str) -> None:
    c.execute("DELETE FROM backend_admission WHERE endpoint=? AND job_id=? AND state='pending'", (endpoint, job_id))
    c.execute("UPDATE backend_admission SET state='uncertain' WHERE endpoint=? AND job_id=? AND state='running'",
              (endpoint, job_id))


def completed(c: sqlite3.Connection, endpoint: str, job_id: str, *, at: float | None = None) -> None:
    at = time.time() if at is None else at
    if type(at) not in (int, float) or not math.isfinite(at):
        raise PermissionError('valid completion time required')
    row = c.execute("SELECT state FROM backend_admission WHERE endpoint=? AND job_id=?", (endpoint, job_id)).fetchone()
    if not row or row[0] not in ('running', 'uncertain'):
        raise PermissionError('backend completion evidence required')
    c.execute('DELETE FROM backend_admission WHERE endpoint=? AND job_id=?', (endpoint, job_id))
    c.execute('''INSERT INTO backend_admission_refresh(endpoint,captured_after) VALUES(?,?)
                 ON CONFLICT(endpoint) DO UPDATE SET captured_after=max(captured_after,excluded.captured_after)''',
              (endpoint, at))


def database_path() -> str:
    return os.getenv('PRIME_COMPUTE_QUEUE_DB', os.path.join(os.getenv('PRIME_DATA_DIR', '/data'), 'compute-queue.db'))


def transaction(db_path: str | None = None):
    c = sqlite3.connect(db_path or database_path(), timeout=20)
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('BEGIN IMMEDIATE')
    init(c)
    return c
