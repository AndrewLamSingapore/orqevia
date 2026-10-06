"""Durable N=1 admission for one local backend endpoint.

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
MAX_AGE_SECONDS = 2.0
RESERVE_MIB = 2048
BASELINE_MAX_DEMAND_MIB = 1024


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


def observation(endpoint: str, *, now: float | None = None) -> dict:
    path = os.getenv('PRIME_BACKEND_MEMORY_RECEIPT', '')
    if not path or not Path(path).is_absolute():
        raise PermissionError('trusted backend memory receipt unavailable')
    try:
        sample = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise PermissionError('trusted backend memory receipt unavailable') from exc
    now = time.time() if now is None else now
    if not isinstance(sample, dict) or sample.get('schema') != SCHEMA or sample.get('endpoint') != endpoint:
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
    return sample


def init(c: sqlite3.Connection) -> None:
    c.execute('''CREATE TABLE IF NOT EXISTS backend_admission (
        endpoint TEXT PRIMARY KEY, job_id TEXT NOT NULL, instance TEXT NOT NULL,
        boot_id TEXT NOT NULL, state TEXT NOT NULL, demand_mib INTEGER NOT NULL,
        refresh_after REAL NOT NULL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS backend_admission_refresh (
        endpoint TEXT PRIMARY KEY, captured_after REAL NOT NULL)''')
    # Pre-release databases may contain leases without a recorded peak. Leave
    # those leases in place and fail closed rather than inventing their demand.
    if 'demand_mib' not in {row[1] for row in c.execute('PRAGMA table_info(backend_admission)')}:
        c.execute('ALTER TABLE backend_admission ADD COLUMN demand_mib INTEGER')


def reserve(c: sqlite3.Connection, endpoint: str, job_id: str, demand_mib: int | None,
            sample: dict | None = None) -> None:
    mode = admission_mode()
    if mode == 'golden_n1':
        if sample is not None:
            raise PermissionError('measured backend sample requires measured admission')
        # Empty identity fields mean no backend identity was observed. The
        # endpoint row is still one atomic lease shared by every local caller.
        if demand_mib is None:
            demand_mib = 0  # ModelGateway has no caller-declared demand.
        if type(demand_mib) is not int or not 0 <= demand_mib <= BASELINE_MAX_DEMAND_MIB:
            raise PermissionError('heavy local inference requires measured admission')
        if c.execute('SELECT 1 FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone():
            raise PermissionError('backend inference lease occupied')
        c.execute('INSERT INTO backend_admission(endpoint,job_id,instance,boot_id,state,demand_mib) VALUES(?,?,?,?,?,?)',
                  (endpoint, job_id, '', '', 'pending', demand_mib))
        return
    sample = observation(endpoint) if sample is None else sample
    # Injected samples are only for tests; production always uses observation().
    if type(demand_mib) is not int or demand_mib <= 0:
        raise PermissionError('verified peak memory demand required')
    from .ssd_thermal import require_for_demand
    require_for_demand(demand_mib)
    if c.execute('SELECT 1 FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone():
        raise PermissionError('backend inference lease occupied')
    prior = c.execute('SELECT captured_after FROM backend_admission_refresh WHERE endpoint=?', (endpoint,)).fetchone()
    if prior and sample['captured_at'] <= prior[0]:
        raise PermissionError('new backend observation required after completion')
    if demand_mib > min(sample['capacity_mib'], sample['available_mib']) - RESERVE_MIB:
        raise PermissionError('insufficient backend memory')
    c.execute('INSERT INTO backend_admission(endpoint,job_id,instance,boot_id,state,demand_mib) VALUES(?,?,?,?,?,?)',
              (endpoint, job_id, sample['instance'], sample['boot_id'], 'pending', demand_mib))


def reserve_model(c: sqlite3.Connection, endpoint: str, job_id: str,
                  model: str, requested_mib: int, *, global_concurrency: int = 1) -> None:
    """Reserve at least the measured peak; an untrusted job estimate cannot lower it."""
    if admission_mode() == 'golden_n1':
        if global_concurrency != 1:
            raise PermissionError('N>1 local inference requires measured admission')
        return reserve(c, endpoint, job_id, requested_mib)
    from .compute_profile import runtime_compute_profile

    profile = runtime_compute_profile()
    details = profile.get('models', {}).get(model) if profile else None
    peak = details.get('peak_mib') if isinstance(details, dict) else None
    if type(peak) is not int or peak <= 0:
        raise PermissionError('verified model peak memory demand required')
    if type(requested_mib) is not int or requested_mib < 0:
        raise PermissionError('invalid requested memory demand')
    reserve(c, endpoint, job_id, max(peak, requested_mib))


def check(c: sqlite3.Connection, endpoint: str, job_id: str, sample: dict | None = None) -> None:
    if admission_mode() == 'golden_n1':
        row = c.execute('SELECT job_id,instance,boot_id,state,demand_mib FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone()
        if (not row or row[0] != job_id or row[1:3] != ('', '') or
                row[3] not in ('pending', 'running') or
                type(row[4]) is not int or not 0 <= row[4] <= BASELINE_MAX_DEMAND_MIB):
            raise PermissionError('backend inference lease or mode mismatch')
        return
    sample = observation(endpoint) if sample is None else sample
    row = c.execute('SELECT job_id,instance,boot_id,state,demand_mib FROM backend_admission WHERE endpoint=?', (endpoint,)).fetchone()
    if not row or tuple(row[:3]) != (job_id, sample['instance'], sample['boot_id']) or row[3] not in ('pending', 'running'):
        raise PermissionError('backend inference lease or instance mismatch')
    from .ssd_thermal import require_for_demand
    require_for_demand(row[4])
    # Pending demand has not become resident. Once dispatched, the backend's
    # free-memory observation already includes it, so do not subtract twice.
    if row[3] == 'pending' and (type(row[4]) is not int or row[4] <= 0):
        raise PermissionError('verified pending memory demand required')
    required = RESERVE_MIB + (row[4] if row[3] == 'pending' else 0)
    if sample['available_mib'] < required:
        raise PermissionError('backend memory reserve reached')


def dispatch(c: sqlite3.Connection, endpoint: str, job_id: str) -> None:
    # Recheck a fresh observation at the transition, not only at reservation.
    check(c, endpoint, job_id)
    changed = c.execute("UPDATE backend_admission SET state='running' WHERE endpoint=? AND job_id=? AND state='pending'",
                        (endpoint, job_id))
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
