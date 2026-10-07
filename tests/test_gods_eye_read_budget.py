"""Tiny disposable DB fixtures; no lifespan, workers, network or provider calls."""
from contextlib import closing
import copy
import json
import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

AUTH = 'Bearer observation-budget-synthetic-owner'


@pytest.fixture
def stores(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_SPINE_TOKEN', AUTH.split(' ', 1)[1])
    from app import objective_api as objective, evidence_lens_api as lens
    queue_path = tmp_path / 'queue.db'
    with sqlite3.connect(queue_path) as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT,agent TEXT,model TEXT,provider TEXT,status TEXT,'
                   'result TEXT,error TEXT,created_at TEXT,started_at TEXT,completed_at TEXT)')
    def forbidden_get(_):
        raise AssertionError('Normal unbounded queue getter must not be called')
    monkeypatch.setattr(objective.compute_queue_api, 'queue', SimpleNamespace(db_path=str(queue_path), get=forbidden_get))
    identity = str(uuid4())
    steps = [{'capability': 'system.registry', 'dispatch': {'state': 'COMPLETED',
              'model_backend': 'none', 'result': 'public fixture result'}}]
    with closing(objective.connect()) as db:
        with db:
            db.execute('INSERT INTO objectives VALUES(?,?,?,?)', (identity, 'public-hash', 'submitted', json.dumps(steps)))
            db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)', (identity, 0, '2026-10-07T04:00:00Z', '2026-10-07T04:00:01Z'))
    return objective, lens, tmp_path, identity


def budget():
    return time.monotonic() + .5


def test_bounded_objective_preserves_existing_result_contract(stores):
    objective, _, _, identity = stores
    ordinary = objective.get_read_only(identity, AUTH)
    assert objective.get_read_only(identity, AUTH, observation_deadline=budget()) == ordinary


@pytest.mark.parametrize('deadline', [True, float('nan'), float('inf'), -1.0])
def test_invalid_deadline_fails_closed_without_creating_store(stores, deadline):
    from app.evidence_product import ObservationBudgetExceeded
    objective, _, _, identity = stores
    with pytest.raises(ObservationBudgetExceeded):
        objective.get_read_only(identity, AUTH, observation_deadline=deadline)


def test_whole_deadline_is_not_reset_for_next_domain(stores):
    from app.evidence_product import ObservationBudgetExceeded
    objective, lens, _, identity = stores
    deadline = time.monotonic() - .001
    with pytest.raises(ObservationBudgetExceeded):
        objective.get_read_only(identity, AUTH, observation_deadline=deadline)
    with pytest.raises(ObservationBudgetExceeded):
        lens.read(identity, AUTH, observation_deadline=deadline)


def test_history_25_turns_is_not_truncated_into_current(stores):
    from app.evidence_product import ObservationBudgetExceeded
    objective, _, _, identity = stores
    with closing(objective.connect()) as db:
        with db:
            for revision in range(1, 26):
                db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
                           (identity, revision, 'fixture-' + str(revision), 'hash', 'submitted', '[]'))
    with pytest.raises(ObservationBudgetExceeded, match='HISTORY'):
        objective.get_read_only(identity, AUTH, observation_deadline=budget())
    # Default existing reader is unchanged, not globally constrained.
    assert objective.get_read_only(identity, AUTH)['revision'] == 25


def test_oversized_objective_bytes_not_returned_or_silently_truncated(stores):
    from app.evidence_product import OBSERVATION_PAYLOAD_BYTES, ObservationBudgetExceeded
    objective, _, _, identity = stores
    with closing(objective.connect()) as db:
        with db:
            db.execute('UPDATE objectives SET steps_json=? WHERE id=?',
                       (json.dumps([{'private': 'x' * OBSERVATION_PAYLOAD_BYTES}]), identity))
    with pytest.raises(ObservationBudgetExceeded, match='HISTORY'):
        objective.get_read_only(identity, AUTH, observation_deadline=budget())


def test_queue_job_read_uses_bounded_owned_sql_not_normal_getter(stores):
    objective, _, root, identity = stores
    jid = str(uuid4())
    with sqlite3.connect(root / 'queue.db') as db:
        db.execute('INSERT INTO compute_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (jid, 'a20', 'fixture-model', 'fixture-provider', 'completed', 'public model output', None,
                    '2026-10-07T04:00:00Z', '2026-10-07T04:00:00Z', '2026-10-07T04:00:01Z'))
    with closing(objective.connect()) as db:
        with db:
            db.execute('UPDATE objectives SET steps_json=? WHERE id=?',
                       (json.dumps([{'capability': 'responsibility.a20', 'dispatch': {'job': {'id': jid}}}]), identity))
    task = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    assert task['state'] == 'COMPLETED'
    assert task['result']['text'] == 'public model output'
    assert task['execution_metadata']['jobs'][0]['job_id'] == jid
    assert task['result']['verification_status'] == 'VERIFY_REQUIRED'


def test_locked_objective_returns_in_short_sqlite_budget(stores):
    objective, _, root, identity = stores
    lock = sqlite3.connect(root / 'objectives.db')
    try:
        lock.execute('BEGIN EXCLUSIVE')
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            objective.get_read_only(identity, AUTH, observation_deadline=started + .3)
        # Scheduling/filesystem overhead is not the SQLite wait setting. Keep
        # a short real lock discriminator without asserting a 50ms benchmark.
        assert time.monotonic() - started < .5
    finally:
        lock.rollback()
        lock.close()


def test_lens_reuses_only_exact_bound_already_read_task(stores, monkeypatch):
    from app.evidence_product import ObservationBudgetExceeded
    objective, lens, _, identity = stores
    captured = lens.materialize(identity, AUTH)
    owned = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    monkeypatch.setattr(objective, 'get_read_only', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No repeated task read')))
    result = lens.read(identity, AUTH, observation_deadline=budget(), task=owned)
    assert result == captured and result['verification'] == 'UNVERIFIED'
    bad = copy.deepcopy(owned)
    bad['execution_metadata']['task_id'] = str(uuid4())
    with pytest.raises(ObservationBudgetExceeded, match='BINDING'):
        lens.read(identity, AUTH, observation_deadline=budget(), task=bad)


def test_bounded_lens_stale_and_tampered_are_never_current(stores):
    from app.evidence_product import content_digest, canonical_bytes
    objective, lens, root, identity = stores
    lens.materialize(identity, AUTH)
    owned = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    stale = copy.deepcopy(owned)
    stale['result']['text'] = 'different public content'
    assert lens.read(identity, AUTH, observation_deadline=budget(), task=stale)['currentness'] == 'STALE'
    with sqlite3.connect(root / 'evidence-lens.db') as db:
        raw = db.execute('SELECT envelope_json FROM evidence_actions').fetchone()[0]
        value = json.loads(raw)
        value['objective'] = 'tampered public fixture'
        db.execute('UPDATE evidence_actions SET envelope_json=?', (json.dumps(value),))
    invalid = lens.read(identity, AUTH, observation_deadline=budget(), task=owned)
    assert invalid['integrity'] == 'INVALID' and invalid['currentness'] == 'UNKNOWN'


def test_lens_more_than_64_events_denied_not_partial_valid(stores):
    from app.evidence_product import ObservationBudgetExceeded
    objective, lens, root, identity = stores
    lens.materialize(identity, AUTH)
    owned = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    with sqlite3.connect(root / 'evidence-lens.db') as db:
        for index in range(65):
            db.execute('INSERT INTO evidence_events(event_id,idempotency_key,action_id,event_type,payload_json,'
                'previous_digest,event_digest,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (str(uuid4()), 'extra-' + str(index), 'objective:' + identity + ':r0', 'fixture', '{}', None, 'a' * 64, '2026-10-07T04:00:01Z'))
    with pytest.raises(ObservationBudgetExceeded, match='CHAIN'):
        lens.read(identity, AUTH, observation_deadline=budget(), task=owned)


def test_missing_bounded_lens_does_not_create_store(stores):
    from fastapi import HTTPException
    objective, lens, root, identity = stores
    owned = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    with pytest.raises(HTTPException) as failure:
        lens.read(identity, AUTH, observation_deadline=budget(), task=owned)
    assert failure.value.status_code == 404
    assert not (root / 'evidence-lens.db').exists()


def test_observation_connection_is_readonly_short_wait_and_not_immutable(stores):
    from app.evidence_product import observation_connection
    _, _, root, _ = stores
    with closing(observation_connection(root / 'queue.db', budget())) as db:
        assert 0 <= db.execute('PRAGMA busy_timeout').fetchone()[0] <= 50
        assert db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute('DELETE FROM compute_jobs')


def test_oversized_ledger_envelope_is_unavailable_not_partial_valid(stores):
    from app.evidence_product import OBSERVATION_PAYLOAD_BYTES, ObservationBudgetExceeded
    objective, lens, root, identity = stores
    lens.materialize(identity, AUTH)
    owned = objective.get_read_only(identity, AUTH, observation_deadline=budget())
    with sqlite3.connect(root / 'evidence-lens.db') as db:
        db.execute('UPDATE evidence_actions SET envelope_json=?', ('x' * (OBSERVATION_PAYLOAD_BYTES + 1),))
    with pytest.raises(ObservationBudgetExceeded, match='PAYLOAD'):
        lens.read(identity, AUTH, observation_deadline=budget(), task=owned)
