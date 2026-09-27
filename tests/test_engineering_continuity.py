"""Real process-loss tests of LAB helper continuity, not production autonomy."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from app.engineering_continuity import ContinuityError, Journal, digest, encode
from app.engineering_loop import build_verify, resume_build_verify


FINGERPRINT = hashlib.sha256(b'trusted-fixture-callbacks-v1').hexdigest()
ROOT = Path(__file__).resolve().parents[1]


def accept(path):
    return {'passed': True, 'verdict': 'ACCEPT', 'verifier': 'a18', 'independent': True,
            'candidate_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'checks': [{'name': 'fixture', 'status': 'PASS', 'evidence_ref': 'fixture:executed'}]}


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path / 'ledger'))
    yield
    from app.action_records import close_ledgers
    close_ledgers()


def create(tmp_path, **kwargs):
    return build_verify(root=tmp_path / 'runs', objective='bounded fixture',
                        builder=lambda *_: '(module)', verifier=accept,
                        execution_fingerprint=FINGERPRINT, **kwargs)


def resume(tmp_path, task_id, **kwargs):
    return resume_build_verify(root=tmp_path / 'runs', task_id=task_id,
                               execution_fingerprint=FINGERPRINT,
                               builder=kwargs.get('builder', lambda *_: pytest.fail('builder replayed')),
                               verifier=kwargs.get('verifier', lambda *_: pytest.fail('verifier replayed')))


def test_terminal_resume_reuses_exact_result_without_callback(tmp_path):
    result = create(tmp_path)
    directory = tmp_path / 'runs' / result['task_id']
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert resume(tmp_path, result['task_id']) == result
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == original
    assert result['production_acceptance'] is False
    assert result['verification_scope'] == 'CALLABLE_RECEIPT_VALIDATION_ONLY'
    assert result['independent_verification'] is False


@pytest.mark.parametrize('phase', ['builder', 'verifier'])
def test_real_process_interruption_never_replays_unknown_effect(tmp_path, phase):
    code = '''
import os,sys
from pathlib import Path
from app.engineering_loop import build_verify
root=Path(sys.argv[1]); phase=sys.argv[2]
def builder(*args):
    if phase=='builder':
        (root.parent/'effect-marker').write_bytes(b'one build effect')
        os._exit(47)
    return '(module)'
def verifier(path):
    (root.parent/'effect-marker').write_bytes(b'one verify effect')
    os._exit(48)
build_verify(root=root,objective='bounded',builder=builder,verifier=verifier,execution_fingerprint=sys.argv[3])
'''
    completed = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path / 'runs'), phase, FINGERPRINT],
                               cwd=ROOT, env=os.environ.copy(), timeout=15, capture_output=True)
    assert completed.returncode == (47 if phase == 'builder' else 48), completed.stderr
    directory = next((tmp_path / 'runs').iterdir())
    raw_before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ContinuityError, match='RUN_LOCKED_RECONCILIATION_REQUIRED'):
        resume(tmp_path, directory.name)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == raw_before
    checkpoint = json.loads(sorted(directory.glob('checkpoint-*'))[-1].read_bytes())
    assert checkpoint['payload']['phase'] == ('BUILD_STARTED' if phase == 'builder' else 'VERIFY_STARTED')
    assert (tmp_path / 'effect-marker').read_bytes() == b'one ' + (b'build' if phase == 'builder' else b'verify') + b' effect'
    assert not (directory / 'result.json').exists()


@pytest.mark.parametrize('phase', ['BUILD_STARTED', 'VERIFY_STARTED'])
def test_exception_without_process_lock_still_requires_reconciliation(tmp_path, phase):
    def fail(*_):
        raise RuntimeError('callback may already have performed an effect')
    with pytest.raises(RuntimeError):
        build_verify(root=tmp_path / 'runs', objective='bounded',
                     builder=fail if phase == 'BUILD_STARTED' else lambda *_: '(module)',
                     verifier=fail, execution_fingerprint=FINGERPRINT)
    directory = next((tmp_path / 'runs').iterdir())
    assert not (directory / '.lock').exists()
    with pytest.raises(ContinuityError, match='INTERRUPTED_CALLBACK_RECONCILIATION_REQUIRED:' + phase):
        resume(tmp_path, directory.name)


def test_safe_preserved_candidate_resumes_verifier_only(tmp_path, monkeypatch):
    append = Journal.append
    def stop_at_boundary(self, payload):
        append(self, payload)
        if payload['phase'] == 'CANDIDATE_PRESERVED':
            raise RuntimeError('bounded pause after durable boundary')
    monkeypatch.setattr(Journal, 'append', stop_at_boundary)
    with pytest.raises(RuntimeError):
        create(tmp_path)
    monkeypatch.setattr(Journal, 'append', append)
    directory = next((tmp_path / 'runs').iterdir())
    result = resume(tmp_path, directory.name, verifier=accept)
    assert result['state'] == 'RECEIPT_STRUCTURALLY_VALID'
    assert len(result['attempts']) == 1


def test_rejected_attempt_resume_preserves_budget_and_feedback(tmp_path, monkeypatch):
    append = Journal.append
    def pause(self, payload):
        append(self, payload)
        if payload['phase'] == 'ATTEMPT_RECORDED':
            raise RuntimeError('pause between attempts')
    monkeypatch.setattr(Journal, 'append', pause)
    with pytest.raises(RuntimeError):
        build_verify(root=tmp_path / 'runs', objective='bounded', builder=lambda *_: 'first',
                     verifier=lambda _: {'passed': False}, max_attempts=2,
                     execution_fingerprint=FINGERPRINT)
    monkeypatch.setattr(Journal, 'append', append)
    directory = next((tmp_path / 'runs').iterdir())
    observed = []
    def builder(objective, feedback):
        observed.append((objective, feedback))
        return 'second'
    result = resume(tmp_path, directory.name, builder=builder, verifier=lambda _: {'passed': False})
    assert result['state'] == 'VALIDATION_FAILED'
    assert [x['attempt'] for x in result['attempts']] == [1, 2]
    assert observed == [('bounded', result['attempts'][0]['verification'])]
    assert resume(tmp_path, directory.name) == result


@pytest.mark.parametrize('name', ['candidate-1.wat', 'verification-1.json', 'result.json', 'checkpoint-0002.json', 'checkpoint-0006.json'])
def test_tampered_or_missing_artifact_fails_closed(tmp_path, name):
    result = create(tmp_path)
    path = tmp_path / 'runs' / result['task_id'] / name
    original = path.read_bytes()
    path.write_bytes(original + b' ')
    with pytest.raises(ContinuityError):
        resume(tmp_path, result['task_id'])
    path.unlink()
    with pytest.raises(ContinuityError):
        resume(tmp_path, result['task_id'])


@pytest.mark.parametrize('task_id', ['../outside', '/absolute', r'C:\Windows', '..', 'a' * 31, 'A' * 32])
def test_task_path_is_never_caller_selected(tmp_path, task_id):
    with pytest.raises(ContinuityError, match='INVALID_TASK_ID'):
        resume(tmp_path, task_id)
    assert not (tmp_path / 'runs').exists()


def test_missing_or_changed_configuration_fingerprint_refuses_resume(tmp_path):
    result = create(tmp_path)
    for supplied in [None, '', 'b' * 64]:
        with pytest.raises(ContinuityError, match='FINGERPRINT'):
            resume_build_verify(root=tmp_path / 'runs', task_id=result['task_id'],
                                execution_fingerprint=supplied, builder=None, verifier=None)


@pytest.mark.parametrize('arguments', [{'max_attempts': 1.5}, {'max_attempts': True},
                                     {'max_attempts': '2'}, {'model': 2}, {'backend': []}])
def test_invalid_initial_configuration_cannot_create_unresumable_effects(tmp_path, arguments):
    with pytest.raises(ValueError):
        build_verify(root=tmp_path / 'runs', objective='bounded',
                     builder=lambda *_: pytest.fail('invalid configuration invoked builder'),
                     verifier=lambda *_: pytest.fail('invalid configuration invoked verifier'),
                     execution_fingerprint=FINGERPRINT, **arguments)
    assert not (tmp_path / 'runs').exists()


def test_partial_unreferenced_file_is_preserved_not_overwritten(tmp_path):
    result = create(tmp_path)
    partial = tmp_path / 'runs' / result['task_id'] / '.pending-fixture'
    partial.write_bytes(b'preserve interruption evidence')
    with pytest.raises(ContinuityError, match='UNREFERENCED_EVIDENCE'):
        resume(tmp_path, result['task_id'])
    assert partial.read_bytes() == b'preserve interruption evidence'


def test_malformed_journal_is_an_explicit_recovery_error(tmp_path):
    result = create(tmp_path)
    path = tmp_path / 'runs' / result['task_id'] / 'checkpoint-0001.json'
    path.write_bytes(b'{partial')
    with pytest.raises(ContinuityError, match='ARTIFACT_MALFORMED'):
        resume(tmp_path, result['task_id'])


def test_active_runner_excludes_concurrent_resumption(tmp_path):
    entered, release = threading.Event(), threading.Event()
    results = []
    def builder(*_):
        entered.set()
        assert release.wait(5)
        return '(module)'
    worker = threading.Thread(target=lambda: results.append(build_verify(
        root=tmp_path / 'runs', objective='bounded', builder=builder, verifier=accept,
        execution_fingerprint=FINGERPRINT)))
    worker.start()
    try:
        assert entered.wait(5)
        directory = next((tmp_path / 'runs').iterdir())
        with pytest.raises(ContinuityError, match='RUN_LOCKED_RECONCILIATION_REQUIRED'):
            resume(tmp_path, directory.name)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results[0]['state'] == 'RECEIPT_STRUCTURALLY_VALID'


def test_legacy_verified_terminal_requires_reconciliation_without_rewriting(tmp_path):
    result = create(tmp_path)
    directory = tmp_path / 'runs' / result['task_id']
    # Represent the prior writer's well-formed, internally consistent terminal
    # bytes. This is a fixture, never a migration or rewrite of real evidence.
    result['state'] = 'VERIFIED_CANDIDATE'
    result.pop('independent_verification')
    raw = encode(result)
    (directory / 'result.json').write_bytes(raw)
    terminal = directory / 'checkpoint-0006.json'
    event = json.loads(terminal.read_bytes())
    event['payload']['sha256'] = digest(raw)
    terminal.write_bytes(encode(event))
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ContinuityError, match='LEGACY_VERIFIED_STATE_RECONCILIATION_REQUIRED'):
        resume(tmp_path, result['task_id'])
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def test_reparse_component_rejected_without_following(tmp_path, monkeypatch):
    result = create(tmp_path)
    path = tmp_path / 'runs' / result['task_id'] / 'candidate-1.wat'
    original = Path.lstat
    class Reparse:
        st_mode = 0o100644
        st_file_attributes = 0x400
    monkeypatch.setattr(Path, 'lstat', lambda self: Reparse() if self == path else original(self))
    with pytest.raises(ContinuityError, match='PATH_LINK_OR_REPARSE_POINT'):
        resume(tmp_path, result['task_id'])


def test_real_link_root_rejected_where_supported(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'runs'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            raise
        # Windows junction creation does not require developer-mode symlink rights.
        completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                   capture_output=True, timeout=10)
        assert completed.returncode == 0, completed.stderr
    with pytest.raises(ContinuityError, match='PATH_LINK_OR_REPARSE_POINT'):
        build_verify(root=link, objective='bounded', builder=None, verifier=None)
    assert not list(outside.iterdir())
