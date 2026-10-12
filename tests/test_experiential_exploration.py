"""Local symbolic fixtures; no live inference, grants or certification evidence."""
import json
import sqlite3

import pytest

from app.agent_registry import agent_record, registered_agent_ids
from app.experiential_exploration import ExplorationSandbox, HELD_OUT, TRAIN, simulate


def reviewer(agent):
    record = agent_record(agent)
    if not record['can_delegate']:
        return record['reports_to']
    return next(a for a in sorted(registered_agent_ids(include_orchestrator=False))
                if a != agent and agent_record(a)['can_delegate'])


def verifier(receipt, binding):
    # Explicit test trust fixture. Production verifier deliberately absent.
    return receipt.get('fixture_authorization') == binding


def receipt(candidate, sandbox):
    return {'fixture_authorization': sandbox.admission_binding(candidate['candidate_id'])}


@pytest.mark.parametrize('agent', sorted(registered_agent_ids(include_orchestrator=False)))
def test_every_actual_agent_explores_restarts_and_transfers_without_claiming_inference(tmp_path, agent):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    run = sandbox.start(agent)
    candidate = sandbox.explore(run)
    assert candidate['strategy'] == 'ascending'
    assert candidate['failed_strategies'] == ['preserve', 'reverse']
    assert candidate['model_weight_training'] is False and not candidate['grants_authority']
    assert sandbox.challenge(candidate['candidate_id'], reviewer(agent))['disposition'] == 'STORE'
    assert sandbox.admit(candidate['candidate_id'], authorization=receipt(candidate, sandbox)) == 1
    restarted = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    assert len(restarted.history(agent)) == 9
    assert restarted.transfer(agent, reviewer(agent), (8, -12, 8, 0))['output'] == [-12, 0, 8, 8]
    with restarted.memory.connect() as db:
        assert db.execute('select count(*) from durable_memory where memory_kind="procedural"').fetchone()[0] == 0
    assert set(TRAIN).isdisjoint(set(HELD_OUT))


def test_default_promotion_denial_and_unverified_transfer(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox')
    candidate = sandbox.explore(sandbox.start('a17'))
    with pytest.raises(PermissionError):
        sandbox.admit(candidate['candidate_id'], authorization={'owner': True})
    sandbox.challenge(candidate['candidate_id'], reviewer('a17'))
    with pytest.raises(PermissionError):
        sandbox.admit(candidate['candidate_id'], authorization={'owner': True})
    with pytest.raises(PermissionError):
        sandbox.transfer('a17', 'a18', (2, 1))


def test_version_rollback_and_replay_denial(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    candidates = []
    for _ in range(2):
        candidate = sandbox.explore(sandbox.start('a17')); candidates.append(candidate)
        sandbox.challenge(candidate['candidate_id'], reviewer('a17'))
        sandbox.admit(candidate['candidate_id'], authorization=receipt(candidate, sandbox))
    with pytest.raises(PermissionError):
        sandbox.admit(candidates[0]['candidate_id'], authorization={'fixture_authorization': sandbox._admission_binding(candidates[0]['candidate_id'], 'a17', 1)})
    authorization = {'fixture_authorization': {'operation': 'sandbox-skill-rollback',
        'agent_id': 'a17', 'version': 1, 'scope': 'simulation_fixture'}}
    sandbox.rollback('a17', 1, authorization=authorization)
    assert sandbox.transfer('a17', 'a18', (-1, 0))['skill_version'] == 1
    with pytest.raises(sqlite3.IntegrityError):
        sandbox.rollback('a17', 1, authorization=authorization)


def test_restart_does_not_reset_budget_and_failed_persistence_consumes_trial(tmp_path, monkeypatch):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', max_trials=9)
    run = sandbox.start('a17')
    def fail(**kwargs):
        raise OSError('injected disk write failure')
    monkeypatch.setattr(sandbox.memory, 'record_episode', fail)
    with pytest.raises(OSError):
        sandbox.observe(run, 'ascending', (2, 1))
    restarted = ExplorationSandbox(tmp_path/'sandbox', max_trials=100)
    for _ in range(8):
        restarted.observe(run, 'ascending', (2, 1))
    with pytest.raises(ValueError, match='budget exhausted'):
        restarted.observe(run, 'ascending', (2, 1))


def test_unsupported_code_injection_unknown_agents_and_self_review_fail_closed(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox')
    with pytest.raises(ValueError): sandbox.start('invented-agent')
    with pytest.raises(ValueError): sandbox.start('prime')
    with pytest.raises(ValueError): simulate('__import__("os").system("bad")', (1,))
    for values in [(True, 2), ('1',), (100001,), (), tuple(range(33))]:
        with pytest.raises(ValueError): simulate('ascending', values)
    candidate = sandbox.explore(sandbox.start('a17'))
    with pytest.raises(PermissionError): sandbox.challenge(candidate['candidate_id'], 'a17')
    with pytest.raises(Exception): sandbox.challenge(candidate['candidate_id'], 'a18')


def test_contaminated_episode_cannot_be_admitted_or_shared(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    candidate = sandbox.explore(sandbox.start('a17'))
    sandbox.challenge(candidate['candidate_id'], reviewer('a17'))
    with sandbox.memory.connect() as db:
        db.execute('update episodic_memory set content_json=? where episode_id=?',
                   (json.dumps({'forged': True}), candidate['episodes'][0]))
    with pytest.raises(ValueError, match='provenance changed'):
        sandbox.admit(candidate['candidate_id'], authorization=receipt(candidate, sandbox))


def test_preexisting_unmarked_storage_is_not_reused(tmp_path):
    (tmp_path/'production.txt').write_text('preserve')
    with pytest.raises(ValueError, match='unmarked'):
        ExplorationSandbox(tmp_path)
    assert (tmp_path/'production.txt').read_text() == 'preserve'


def test_partial_run_resumes_after_restart_and_completed_run_is_idempotent(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', max_trials=9)
    run = sandbox.start('a17')
    sandbox.observe(run, 'preserve', TRAIN[0])
    resumed = ExplorationSandbox(tmp_path/'sandbox')
    candidate = resumed.explore(run)
    assert len(resumed.history('a17')) == 9
    assert len(resumed.history('a17', query='ascending')) == 3
    assert resumed.explore(run) == candidate
    assert len(resumed.history('a17')) == 9


def test_tampered_review_cannot_propagate(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    candidate = sandbox.explore(sandbox.start('a17'))
    sandbox.challenge(candidate['candidate_id'], reviewer('a17'))
    sandbox.admit(candidate['candidate_id'], authorization=receipt(candidate, sandbox))
    with sandbox.memory.connect() as db:
        db.execute('update exploration_reviews set body=?', (json.dumps({'disposition': 'STORE'}),))
    with pytest.raises(PermissionError):
        sandbox.transfer('a17', 'a18', (3, 2))


def test_durable_agent_ceiling_survives_restart_and_concurrent_new_runs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    sandbox = ExplorationSandbox(tmp_path/'sandbox', max_agent_runs=2)
    def start(_):
        try: return sandbox.start('a17')
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(start, range(10)))
    assert sum(value is not None for value in outcomes) == 2
    restarted = ExplorationSandbox(tmp_path/'sandbox', max_agent_runs=100)
    with pytest.raises(ValueError, match='agent runs ceiling'):
        restarted.start('a17')


def test_sandbox_and_agent_trial_ceilings_cannot_reset_in_new_run(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', max_agent_trials=9, max_sandbox_trials=10,
                                 max_sandbox_runs=3)
    run = sandbox.start('a17')
    for _ in range(9): sandbox.observe(run, 'ascending', (2, 1))
    new_run = sandbox.start('a17')
    with pytest.raises(ValueError, match='agent trials ceiling'):
        sandbox.observe(new_run, 'ascending', (2, 1))
    other = sandbox.start('a18')
    sandbox.observe(other, 'ascending', (2, 1))
    with pytest.raises(ValueError, match='sandbox trials ceiling'):
        sandbox.observe(other, 'ascending', (2, 1))
    with pytest.raises(ValueError, match='sandbox runs ceiling'):
        sandbox.start('a01')


def test_reviewed_but_unadmitted_version_insertion_cannot_transfer_or_rollback(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox', promotion_verifier=verifier)
    first = sandbox.explore(sandbox.start('a17'))
    sandbox.challenge(first['candidate_id'], reviewer('a17'))
    sandbox.admit(first['candidate_id'], authorization=receipt(first, sandbox))
    second = sandbox.explore(sandbox.start('a17'))
    sandbox.challenge(second['candidate_id'], reviewer('a17'))
    with sandbox.memory.connect() as db:
        witness = db.execute('select authorization_hash from exploration_versions').fetchone()[0]
        db.execute('update exploration_versions set active=0')
        db.execute('insert into exploration_versions values(?,?,?,?,1)',
                   ('a17', 2, second['candidate_id'], witness))
    with pytest.raises(PermissionError, match='admission witness'):
        sandbox.transfer('a17', 'a18', (3, 1))
    authorization = {'fixture_authorization': {'operation': 'sandbox-skill-rollback',
        'agent_id': 'a17', 'version': 2, 'scope': 'simulation_fixture'}}
    with pytest.raises(PermissionError, match='admission witness'):
        sandbox.rollback('a17', 2, authorization=authorization)


def test_history_sql_limit_and_agent_filter(tmp_path):
    sandbox = ExplorationSandbox(tmp_path/'sandbox')
    sandbox.explore(sandbox.start('a17'))
    sandbox.explore(sandbox.start('a18'))
    rows = sandbox.history('a17', limit=2)
    assert len(rows) == 2 and all(row['agent_id'] == 'a17' for row in rows)
    assert len(sandbox.history('a17', query='ascending', limit=2)) == 2
