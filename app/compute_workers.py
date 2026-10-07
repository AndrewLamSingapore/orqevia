"""Candidate fixed-workload worker domain on the existing compute queue.

The API must authorize a server-provisioned worker/client policy before calling
this adapter. No token custody, network, arbitrary command or hardware
attestation is provided here. External queue states deliberately cannot enter
the existing local-model claim/recovery path. An expired attempt is uncertain,
not permission to dispatch it again.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid

from .agent_registry import canonical_agent_id, registered_agent_ids
from .job_queue import PRIORITIES

STATE = 'CONTRACT_CANDIDATE_NOT_LIVE'
WORKLOAD = 'prime.dell-client-tests.v1'
HOSTNAME = 'DESKTOP-IPV4PH9'
FILES = frozenset(('clients/dell/lib/config.mjs', 'clients/dell/lib/upstream.mjs',
    'clients/dell/test/client.test.mjs', 'clients/dell/test/url-transport.test.mjs'))
TEST_FILES = FILES - {'clients/dell/lib/config.mjs', 'clients/dell/lib/upstream.mjs'}
MAX_SOURCE_BYTES = 65536
MAX_PENDING = 8
EXPECTED_TESTS = 11
MAX_DURATION_SECONDS = 45
ACTIVE = ('leased', 'uncertain', 'cancel_requested')
ERROR_CODES = frozenset(('NONE', 'SOURCE_MISMATCH', 'SOURCE_SIZE_EXCEEDED',
    'REVISION_MISMATCH', 'NODE_REQUIRED', 'TEST_FAILED', 'TEST_TIMEOUT',
    'CANCELLED', 'EXECUTION_FAILED'))
RESULT_FIELDS = frozenset(('schema', 'worker_id', 'client_id', 'job_id', 'attempt_id',
    'workload_id', 'source_revision', 'payload_sha256', 'manifest_sha256',
    'testfile_sha256', 'tests_total', 'tests_passed', 'tests_failed', 'tests_skipped',
    'exit_code', 'started_at', 'ended_at', 'duration_ms', 'source_bytes', 'terminal',
    'execution_stopped', 'cancelled', 'timed_out', 'execution_started', 'error_code'))


class ComputeWorkerError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if value is not True:
        raise ComputeWorkerError(code)


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ComputeWorkerError('INVALID_WORKER_JSON') from None


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _decode(value):
    if type(value) is dict:
        canonical_bytes(value)
        return value
    require(type(value) in (str, bytes) and len(value) <= MAX_SOURCE_BYTES,
        'INVALID_WORKER_JSON')
    def pairs(items):
        result = {}
        for key, item in items:
            require(key not in result, 'DUPLICATE_WORKER_JSON_KEY')
            result[key] = item
        return result
    try:
        result = json.loads(value, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ComputeWorkerError('INVALID_WORKER_JSON') from None
    require(type(result) is dict, 'INVALID_WORKER_JSON')
    canonical_bytes(result)  # Also rejects exponent overflow decoded as infinity.
    return result


def _name(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,127}', value) is not None


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _manifest(value):
    require(type(value) is dict and set(value) == FILES and
        all(_sha(item) for item in value.values()), 'INVALID_WORKER_MANIFEST')
    return dict(value)


def _stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _timestamp(value):
    require(type(value) is str and len(value) <= 40 and value.endswith('Z'),
        'INVALID_WORKER_RESULT_TIME')
    try:
        result = datetime.fromisoformat(value[:-1] + '+00:00').timestamp()
    except (ValueError, OverflowError):
        raise ComputeWorkerError('INVALID_WORKER_RESULT_TIME') from None
    require(math.isfinite(result), 'INVALID_WORKER_RESULT_TIME')
    return result


class ComputeWorkers:
    def __init__(self, queue, *, clock=time.time, heartbeat_ttl=60, lease_seconds=60):
        require(type(heartbeat_ttl) is int and 1 <= heartbeat_ttl <= 120 and
            type(lease_seconds) is int and MAX_DURATION_SECONDS < lease_seconds <= 120,
            'INVALID_WORKER_PROTOCOL_BOUNDS')
        self.queue, self.clock = queue, clock
        self.heartbeat_ttl, self.lease_seconds = heartbeat_ttl, lease_seconds
        with queue.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS compute_worker_registry(
                worker_id TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,
                hostname TEXT NOT NULL,workload_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,files_json TEXT NOT NULL,
                heartbeat_at REAL,inventory_json TEXT);
                CREATE TABLE IF NOT EXISTS compute_worker_attempts(
                attempt_id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL,
                worker_id TEXT NOT NULL,client_id TEXT NOT NULL,
                lease_sha256 TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
                leased_at REAL NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL,
                result_sha256 TEXT,completed_at REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_compute_worker_active
                ON compute_worker_attempts(worker_id)
                WHERE state IN ('leased','uncertain','cancel_requested');''')

    def _now(self):
        result = self.clock()
        require(type(result) in (int, float) and math.isfinite(result) and result > 0,
            'WORKER_CLOCK_UNAVAILABLE')
        return result

    @staticmethod
    def _worker(db, worker_id, client_id=None):
        require(_name(worker_id), 'INVALID_WORKER_ID')
        row = db.execute('SELECT * FROM compute_worker_registry WHERE worker_id=?', (worker_id,)).fetchone()
        require(row is not None, 'WORKER_NOT_PROVISIONED')
        if client_id is not None:
            require(type(client_id) is str and hmac.compare_digest(row['client_id'], client_id),
                'WORKER_CLIENT_MISMATCH')
        return row

    def register(self, *, worker_id, client_id, hostname, source_revision, file_sha256, workload_id=WORKLOAD):
        require(_name(worker_id) and _name(client_id) and hostname == HOSTNAME and
            type(hostname) is str and workload_id == WORKLOAD and
            type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision) is not None,
            'INVALID_WORKER_CONFIGURATION')
        files = canonical_bytes(_manifest(file_sha256)).decode()
        with self.queue.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM compute_worker_registry WHERE worker_id=?', (worker_id,)).fetchone()
            configuration = (client_id, hostname, workload_id, source_revision, files)
            if prior:
                require(tuple(prior[key] for key in ('client_id', 'hostname', 'workload_id',
                    'source_revision', 'files_json')) == configuration, 'WORKER_CONFIGURATION_CONFLICT')
            else:
                require(db.execute('SELECT 1 FROM compute_worker_registry WHERE client_id=?',
                    (client_id,)).fetchone() is None, 'WORKER_CLIENT_ALREADY_BOUND')
                db.execute('INSERT INTO compute_worker_registry VALUES(?,?,?,?,?,?,NULL,NULL)',
                    (worker_id,) + configuration)
                self.queue._event(db, None, 'worker_registered', {'worker_id': worker_id,
                    'client_id': client_id, 'workload_id': WORKLOAD, 'source_revision': source_revision,
                    'inventory_evidence': 'NOT_OBSERVED', 'state': STATE})
        return self.status(worker_id)

    def _expire(self, db, worker_id, now):
        rows = db.execute('''SELECT a.*,j.status AS job_status FROM compute_worker_attempts a
            LEFT JOIN compute_jobs j ON j.id=a.job_id
            WHERE a.worker_id=? AND a.state IN ('leased','uncertain','cancel_requested')''',
            (worker_id,)).fetchall()
        for row in rows:
            cancelled = row['job_status'] in ('cancelled', 'external_cancel_requested')
            state = 'cancel_requested' if cancelled else 'uncertain' if row['expires_at'] <= now else row['state']
            if state != row['state']:
                db.execute('UPDATE compute_worker_attempts SET state=? WHERE attempt_id=?',
                    (state, row['attempt_id']))
                self.queue._event(db, row['job_id'], 'worker_attempt_uncertainty',
                    {'worker_id': worker_id, 'attempt_id': row['attempt_id'], 'state': state,
                     'automatic_replay': False})
            if state in ('uncertain', 'cancel_requested'):
                db.execute("UPDATE compute_jobs SET status=?,error=?,updated_at=? WHERE id=?",
                    ('external_cancel_requested' if cancelled else 'external_uncertain',
                     'WORKER_COMPLETION_UNVERIFIED', _stamp(now), row['job_id']))

    def heartbeat(self, worker_id, client_id, inventory):
        inventory = _decode(inventory)
        require(set(inventory) <= {'hostname', 'platform', 'node_version',
            'logical_processors', 'total_memory_mib'} and
            {'hostname', 'platform', 'node_version'} <= set(inventory) and
            inventory['hostname'] == HOSTNAME and inventory['platform'] == 'win32' and
            type(inventory['node_version']) is str and
            re.fullmatch(r'v?(?:2[0-9]|[3-9][0-9]|100)\.[0-9]{1,4}\.[0-9]{1,4}', inventory['node_version']) is not None,
            'INVALID_WORKER_INVENTORY')
        for key, maximum in (('logical_processors', 1024), ('total_memory_mib', 1048576)):
            if key in inventory:
                require(type(inventory[key]) is int and 1 <= inventory[key] <= maximum,
                    'INVALID_WORKER_INVENTORY')
        now = self._now()
        with self.queue.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._worker(db, worker_id, client_id)
            self._expire(db, worker_id, now)
            db.execute('UPDATE compute_worker_registry SET heartbeat_at=?,inventory_json=? WHERE worker_id=?',
                (now, canonical_bytes(inventory).decode(), worker_id))
        return self.status(worker_id)

    @staticmethod
    def _payload(worker):
        return {'schema': 'prime.compute-worker-payload.v1', 'worker_id': worker['worker_id'],
            'workload_id': WORKLOAD, 'source_revision': worker['source_revision'],
            'file_sha256': _manifest(_decode(worker['files_json']))}

    def submit(self, worker_id, *, agent='a18', priority='normal', source_revision, file_sha256):
        require(type(agent) is str and type(priority) in (str, int) and
            (priority in PRIORITIES if type(priority) is str else 0 <= priority <= 100),
            'INVALID_WORKER_JOB')
        try:
            actor = canonical_agent_id(agent)
        except (ValueError, TypeError, AttributeError):
            raise ComputeWorkerError('INVALID_WORKER_AGENT') from None
        require(actor in registered_agent_ids(include_orchestrator=False), 'INVALID_WORKER_AGENT')
        files = _manifest(file_sha256)
        now, job_id = self._now(), str(uuid.uuid4())
        level = PRIORITIES[priority] if type(priority) is str else priority
        with self.queue.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            worker = self._worker(db, worker_id)
            self._expire(db, worker_id, now)
            require(source_revision == worker['source_revision'] and
                canonical_bytes(files).decode() == worker['files_json'], 'WORKER_SOURCE_MISMATCH')
            held = db.execute('''SELECT COUNT(*) FROM compute_jobs j
                WHERE j.external_execution=1 AND j.preferred_provider=?
                AND (j.status NOT IN ('completed','failed','cancelled','budget_blocked')
                  OR EXISTS(SELECT 1 FROM compute_worker_attempts a WHERE a.job_id=j.id
                    AND a.state IN ('leased','uncertain','cancel_requested')))''',
                ('worker:' + worker_id,)).fetchone()[0]
            require(held < MAX_PENDING, 'WORKER_PENDING_FULL')
            self.queue._require_pending_capacity(db, level)
            payload = canonical_bytes(self._payload(worker)).decode()
            require(len(payload.encode()) <= MAX_SOURCE_BYTES, 'WORKER_PAYLOAD_TOO_LARGE')
            stamp = _stamp(now)
            db.execute('''INSERT INTO compute_jobs
                (id,agent,prompt,priority,model_role,model,ram_mb,vram_mb,timeout_seconds,max_retries,
                 max_cost_usd,allow_cloud,external_execution,status,approval_status,created_at,updated_at,
                 classification,preferred_provider,data_classification,task_class)
                VALUES(?,?,?,?,'auto',?,0,0,?,0,0,0,1,'external_queued','not_required',?,?,'R0',?,'LOCAL_ONLY','worker_tests')''',
                (job_id, actor, payload, level, WORKLOAD, MAX_DURATION_SECONDS, stamp, stamp, 'worker:' + worker_id))
            self.queue._event(db, job_id, 'external_submitted', {'worker_id': worker_id,
                'workload_id': WORKLOAD, 'payload_sha256': hashlib.sha256(payload.encode()).hexdigest(),
                'source_revision': source_revision, 'automatic_replay': False})
            job = dict(db.execute('SELECT * FROM compute_jobs WHERE id=?', (job_id,)).fetchone())
        return job

    def _check_job(self, job, worker):
        require(job is not None and type(job['external_execution']) is int and job['external_execution'] == 1 and
            job['allow_cloud'] == 0 and job['max_retries'] == 0 and job['model'] == WORKLOAD and
            job['preferred_provider'] == 'worker:' + worker['worker_id'], 'WORKER_JOB_BINDING_FAILED')
        payload = _decode(job['prompt'])
        require(canonical_bytes(payload).decode() == job['prompt'] and
            canonical_bytes(payload) == canonical_bytes(self._payload(worker)), 'WORKER_PAYLOAD_CHANGED')
        return payload, digest(payload)

    def claim(self, worker_id, client_id):
        now = self._now()
        with self.queue.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            worker = self._worker(db, worker_id, client_id)
            self._expire(db, worker_id, now)
            if db.execute("SELECT 1 FROM compute_worker_attempts WHERE worker_id=? AND state IN ('leased','uncertain','cancel_requested')",
                    (worker_id,)).fetchone():
                return None
            if worker['heartbeat_at'] is None or not 0 <= now - worker['heartbeat_at'] < self.heartbeat_ttl:
                return None
            db.create_function('worker_priority', 2, lambda level, created: self.queue._effective_priority(
                {'priority': level, 'created_at': created}, now))
            job = db.execute('''SELECT * FROM compute_jobs WHERE status='external_queued'
                AND external_execution=1 AND preferred_provider=?
                AND NOT EXISTS(SELECT 1 FROM compute_worker_attempts a WHERE a.job_id=compute_jobs.id)
                ORDER BY worker_priority(priority,created_at) DESC,priority DESC,created_at,id LIMIT 1''',
                ('worker:' + worker_id,)).fetchone()
            if job is None:
                return None
            payload, payload_sha = self._check_job(job, worker)
            attempt_id, lease = str(uuid.uuid4()), secrets.token_urlsafe(32)
            expires = now + self.lease_seconds
            db.execute("INSERT INTO compute_worker_attempts VALUES(?,?,?,?,?,?,?,?,?,'leased',NULL,NULL)",
                (attempt_id, job['id'], worker_id, client_id, hashlib.sha256(lease.encode()).hexdigest(),
                 payload_sha, now, expires))
            db.execute("UPDATE compute_jobs SET status='external_running',provider=?,lease_until=?,attempts=1,started_at=?,updated_at=? WHERE id=?",
                ('worker:' + worker_id, expires, _stamp(now), _stamp(now), job['id']))
            self.queue._event(db, job['id'], 'external_claimed', {'worker_id': worker_id,
                'attempt_id': attempt_id, 'payload_sha256': payload_sha, 'lease_expires_at': expires,
                'automatic_replay': False})
            return {'job': {'id': job['id'], 'agent': job['agent'], 'priority': job['priority'],
                'payload': payload, 'payload_sha256': payload_sha}, 'attempt_id': attempt_id,
                'lease_token': lease, 'lease_expires_at': expires,
                'constraints': {'max_duration_seconds': MAX_DURATION_SECONDS,
                    'max_source_bytes': MAX_SOURCE_BYTES, 'expected_test_count': EXPECTED_TESTS}}

    @staticmethod
    def _validate_result(result, worker, job_id, attempt_id, payload_sha, now, leased_at):
        require(set(result) == RESULT_FIELDS, 'INVALID_WORKER_RESULT_SCHEMA')
        require(result['schema'] == 'prime.compute-worker-result.v1' and
            result['worker_id'] == worker['worker_id'] and result['client_id'] == worker['client_id'] and
            result['job_id'] == job_id and result['attempt_id'] == attempt_id and
            result['workload_id'] == WORKLOAD and result['source_revision'] == worker['source_revision'] and
            result['payload_sha256'] == payload_sha, 'WORKER_RESULT_BINDING_FAILED')
        files = _manifest(_decode(worker['files_json']))
        require(result['manifest_sha256'] == digest(files) and
            canonical_bytes(result['testfile_sha256']) == canonical_bytes({key: files[key] for key in TEST_FILES}),
            'WORKER_RESULT_SOURCE_FAILED')
        require(result['terminal'] is True and result['execution_stopped'] is True and
            all(type(result[key]) is bool for key in ('cancelled', 'timed_out', 'execution_started')) and
            type(result['error_code']) is str and result['error_code'] in ERROR_CODES,
            'WORKER_COMPLETION_UNPROVEN')
        counts = [result[key] for key in ('tests_total', 'tests_passed', 'tests_failed', 'tests_skipped')]
        require(all(type(value) is int and 0 <= value <= EXPECTED_TESTS for value in counts) and
            counts[0] == sum(counts[1:]), 'INVALID_WORKER_TEST_COUNTS')
        require(type(result['duration_ms']) is int and 0 <= result['duration_ms'] <= MAX_DURATION_SECONDS * 1000 and
            type(result['source_bytes']) is int and 0 <= result['source_bytes'] <= MAX_SOURCE_BYTES,
            'INVALID_WORKER_RESULT_BOUNDS')
        code = result['exit_code']
        require((type(code) is int and code in (0, 1)) or
            (code is None and (result['cancelled'] or result['timed_out'])), 'INVALID_WORKER_EXIT')
        start, end = _timestamp(result['started_at']), _timestamp(result['ended_at'])
        require(leased_at - 30 <= start <= end <= now + 30 and
            abs((end - start) * 1000 - result['duration_ms']) <= 1000,
            'INVALID_WORKER_RESULT_TIME')
        success = (code == 0 and counts == [EXPECTED_TESTS, EXPECTED_TESTS, 0, 0] and
            result['execution_started'] is True and result['cancelled'] is False and
            result['timed_out'] is False and result['error_code'] == 'NONE' and result['source_bytes'] > 0)
        require(success or result['error_code'] != 'NONE', 'WORKER_FAILURE_REASON_REQUIRED')
        require(result['execution_started'] or (counts == [0, 0, 0, 0] and code == 1 and
            not result['cancelled'] and not result['timed_out']), 'WORKER_EXECUTION_CLAIM_INVALID')
        return success

    def complete(self, worker_id, client_id, job_id, attempt_id, lease_token, result, result_sha256):
        require(_sha(result_sha256) and type(lease_token) is str and
            re.fullmatch('[A-Za-z0-9_-]{43}', lease_token) is not None,
            'INVALID_WORKER_COMPLETION_BINDING')
        result = _decode(result)
        require(digest(result) == result_sha256, 'WORKER_RESULT_DIGEST_MISMATCH')
        now = self._now()
        with self.queue.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            worker = self._worker(db, worker_id, client_id)
            attempt = db.execute('SELECT * FROM compute_worker_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            require(attempt is not None and attempt['worker_id'] == worker_id and attempt['client_id'] == client_id and
                attempt['job_id'] == job_id and attempt['state'] in ACTIVE and
                hmac.compare_digest(attempt['lease_sha256'], hashlib.sha256(lease_token.encode()).hexdigest()),
                'WORKER_LEASE_MISMATCH_OR_REPLAY')
            job = db.execute('SELECT * FROM compute_jobs WHERE id=?', (job_id,)).fetchone()
            _, payload_sha = self._check_job(job, worker)
            require(payload_sha == attempt['payload_sha256'], 'WORKER_PAYLOAD_CHANGED')
            success = self._validate_result(result, worker, job_id, attempt_id, payload_sha, now, attempt['leased_at'])
            cancellation_requested = job['status'] in ('cancelled', 'external_cancel_requested')
            status = 'cancelled' if cancellation_requested or result['cancelled'] else 'completed' if success else 'failed'
            db.execute("UPDATE compute_worker_attempts SET state='resolved',result_sha256=?,completed_at=? WHERE attempt_id=?",
                (result_sha256, now, attempt_id))
            db.execute('''UPDATE compute_jobs SET status=?,result=?,error=?,lease_until=NULL,
                actual_cost_usd=0,input_tokens=0,output_tokens=0,completed_at=?,updated_at=? WHERE id=?''',
                (status, canonical_bytes(result).decode(), None if success and not cancellation_requested else
                 'WORKER_CANCELLED' if status == 'cancelled' else result['error_code'], _stamp(now), _stamp(now), job_id))
            self.queue._event(db, job_id, 'external_completed', {'worker_id': worker_id,
                'attempt_id': attempt_id, 'result_sha256': result_sha256, 'status': status,
                'execution_evidence': 'AUTHENTICATED_WORKER_REPORT_NOT_INDEPENDENT_ATTESTATION',
                'automatic_replay': False})
            return {'job_id': job_id, 'attempt_id': attempt_id, 'worker_id': worker_id,
                'status': status, 'result_sha256': result_sha256, 'state': STATE,
                'independent_attestation': False, 'l7_awarded': False}

    def status(self, worker_id=None):
        now = self._now()
        with self.queue.connect() as db:
            workers = [self._worker(db, worker_id)] if worker_id is not None else db.execute(
                'SELECT * FROM compute_worker_registry ORDER BY worker_id').fetchall()
            result = []
            for worker in workers:
                attempt = db.execute("SELECT job_id,attempt_id,state,expires_at FROM compute_worker_attempts WHERE worker_id=? AND state IN ('leased','uncertain','cancel_requested')",
                    (worker['worker_id'],)).fetchone()
                fresh = worker['heartbeat_at'] is not None and 0 <= now - worker['heartbeat_at'] < self.heartbeat_ttl
                availability = ('UNCERTAIN' if attempt and (attempt['state'] != 'leased' or attempt['expires_at'] <= now) else
                    'BUSY' if attempt else 'SELF_REPORTED_AVAILABLE' if fresh else
                    'STALE' if worker['heartbeat_at'] is not None else 'UNOBSERVED')
                result.append({'worker_id': worker['worker_id'], 'client_id': worker['client_id'],
                    'hostname': worker['hostname'], 'workload_id': WORKLOAD,
                    'source_revision': worker['source_revision'], 'manifest_sha256': digest(_decode(worker['files_json'])),
                    'availability': availability, 'heartbeat_fresh': fresh,
                    'inventory_evidence': 'SELF_REPORTED_NOT_HARDWARE_ATTESTATION' if worker['heartbeat_at'] is not None else 'NOT_OBSERVED',
                    'active_attempt': dict(attempt) if attempt else None, 'state': STATE})
        return {'state': STATE, 'workers': result, 'remote_execution_verified': False}
