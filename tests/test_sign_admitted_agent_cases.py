"""Loader fixtures only; no actual Azure operation or agent certification."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from scripts import sign_admitted_agent_cases as loader
from app.agent_registry import load_agent_registry

OWNED_IDENTITY_PAIRS = [(a['id'],c) for a in load_agent_registry()['agents']
    for c in a['capability_requirements'] if (a['id'],c) != ('a19','responsibility.a19')]


SOURCE = 'd' * 40
REVIEW = 'c' * 40
INVOKE = 'b' * 40
IMAGE = 'sha256:' + 'e' * 64


def manifest(cases=()):
    return json.dumps({'schema_version': 'prime.protected-reviewed-cases.v1', 'cases': list(cases)}).encode()


def entry():
    return dict(record={'agent_id': 'a19', 'capability_id': 'responsibility.a19',
                       'dimension': 'role', 'test_case': 'normal'},
        evidence_directory=loader.EVIDENCE_PREFIX + '/fixture-a19',
        execution_sha256='a' * 64, review_sha256='f' * 64, execution_source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=REVIEW, cloud_policy=None,
        owner_policy_sha256=None)


def test_empty_admission_is_pending_without_signing_or_code_proof(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('No signing or code proof should be needed for zero cases')
    result = loader.run(manifest(), root=tmp_path, protected_source_revision=INVOKE,
        public_pin={}, sign_digest=forbidden, check_code=forbidden, now=datetime.now(timezone.utc))
    assert result['state'] == 'PENDING_NO_ADMITTED_CASES'
    assert result['signed_cases'] == [] and result['signed_case_count'] == 0
    assert result['l7_awarded'] is False


def test_fixed_trusted_manifest_passes_exact_pins_to_existing_signer(tmp_path, monkeypatch):
    calls = []
    code = []
    pin = {'key_id': 'fixture-public-key-id', 'jwk': {}}
    signer = lambda digest: (_ for _ in ()).throw(AssertionError('Mock bridge must not call Azure'))
    def bridge(row, **kwargs):
        calls.append((row, kwargs))
        return {'agent_id': row['agent_id'], 'attestation': 'SYNTHETIC_STUB_NOT_A_SIGNATURE'}
    monkeypatch.setattr(loader, 'sign_reviewed_case', bridge)
    now = datetime.now(timezone.utc)
    result = loader.run(manifest([entry()]), root=tmp_path, protected_source_revision=INVOKE,
        public_pin=pin, sign_digest=signer, check_code=lambda *args: code.append(args), now=now)
    assert code == [(tmp_path, REVIEW)]
    row, kwargs = calls[0]
    assert row == entry()['record']
    assert kwargs == dict(evidence_root=tmp_path / entry()['evidence_directory'],
        execution_sha256='a' * 64, review_sha256='f' * 64, execution_source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=REVIEW, public_pin=pin,
        sign_digest=signer, now=now)
    assert result['protected_invocation_source_revision'] == INVOKE
    assert result['signed_case_count'] == 1 and result['l7_awarded'] is False


@pytest.mark.parametrize('field,value', [('evidence_directory', '../outside'),
    ('evidence_directory', 'C:/outside'), ('evidence_directory', loader.EVIDENCE_PREFIX + '/../../escape'),
    ('evidence_directory', loader.EVIDENCE_PREFIX + '/fixture/child'), ('evidence_directory', True),
    ('execution_sha256', 'bad'), ('review_sha256', False), ('execution_source_revision', 'UNKNOWN'),
    ('reviewer_code_revision', 'main'), ('runtime_image_id', 'UNKNOWN'), ('record', []),
    ('verifier_code_revision', 'main'), ('verifier_code_revision', True),
    ('owner_policy_sha256', 'f' * 64), ('cloud_policy', {}), ('unused_approval', True)])
def test_invalid_manifest_cannot_reach_signer(tmp_path, monkeypatch, field, value):
    calls = []
    monkeypatch.setattr(loader, 'sign_reviewed_case', lambda *args, **kwargs: calls.append(kwargs))
    changed = entry()
    changed[field] = value
    with pytest.raises(ValueError, match='Protected reviewed-case admission rejected'):
        loader.run(manifest([changed]), root=tmp_path, protected_source_revision=INVOKE,
            public_pin={}, sign_digest=lambda _: None, check_code=lambda *args: None,
            now=datetime.now(timezone.utc))
    assert calls == []


@pytest.mark.parametrize('raw', [b'[]', b'{}', b'{"schema_version":"x","cases":[]}',
    b'{"schema_version":"prime.protected-reviewed-cases.v1","cases":[],"cases":[]}',
    b'{"schema_version":"prime.protected-reviewed-cases.v1","cases":NaN}', b'not-json'])
def test_outer_shape_duplicate_and_nonfinite_fail_closed(raw):
    with pytest.raises(ValueError):
        loader.parse(raw)


def test_duplicate_agents_and_unbounded_batch_are_not_admitted():
    for entries in ([entry(), entry()], [entry()] * 22):
        with pytest.raises(ValueError):
            loader.parse(manifest(entries))


def test_manifest_without_agent_does_not_admit_unknown_identity():
    changed = entry()
    changed['record'] = {}
    with pytest.raises(ValueError):
        loader.parse(manifest([changed]))


def test_identity_admission_is_exact_event_scope_not_a_model_answer_or_duplicate_role():
    identity = entry()
    identity['record'] = dict(agent_id='a19', capability_id='responsibility.a19',
                              dimension='baseline', test_case='identity')
    assert loader.parse(manifest([identity])) == [identity]
    assert loader.parse(manifest([entry(), identity])) == [entry(), identity]
    wrong_agent = copy.deepcopy(identity)
    wrong_agent['record'].update(agent_id='a20', capability_id='responsibility.a19')
    with pytest.raises(ValueError):
        loader.parse(manifest([wrong_agent]))


@pytest.mark.parametrize('agent,capability',OWNED_IDENTITY_PAIRS)
def test_owned_identity_manifest_accepts_only_exact_registered_pair_and_no_duplicates(agent,capability):
    value = entry()
    value['record'].update(agent_id=agent,capability_id=capability,dimension='baseline',test_case='identity')
    assert loader.parse(manifest([value])) == [value]
    with pytest.raises(ValueError): loader.parse(manifest([value,value]))
    value['record']['capability_id'] = 'responsibility.a19'
    with pytest.raises(ValueError): loader.parse(manifest([value]))


@pytest.mark.parametrize('cloud,policy', [(None, 'f' * 64), ({}, None), ({}, 'f' * 64)])
def test_identity_admission_never_accepts_cloud_transport(cloud, policy):
    identity = entry()
    identity['record'].update(dimension='baseline', test_case='identity')
    identity.update(cloud_policy=cloud, owner_policy_sha256=policy)
    with pytest.raises(ValueError):
        loader.parse(manifest([identity]))


@pytest.mark.parametrize('dependency', ['app/agent_cert_identity_review.py',
    'app/action_records.py', 'app/artifact_factory.py', 'app/objective_api.py',
    'app/agent_cert_initialization.py', 'app/agent_cert_initialization_review.py',
    'app/agent_cert_secondary_roles.py', 'app/agent_cert_a19_general.py',
    'app/agent_cert_event_api.py', 'app/agent_cert_a19_baseline.py', 'app/agent_cert_authority_events.py',
    'app/context_pack.py', 'app/agent_cert_owned_identity.py', 'app/agent_cert_owned_contract.py',
    'app/agent_cert_owned_contract_review.py', 'app/agent_cert_clean_room.py', 'app/agent_cert_fresh_input.py', 'app/spine.py', 'app/generated/portfolio_contracts.py',
    'app/model_selection.py','app/agent_cert_model_selection.py','app/compute_queue_api.py','app/settings.py','app/job_queue.py'])
def test_original_identity_domain_dependencies_are_all_protected_code_inputs(tmp_path, dependency):
    assert len(loader.CODE_FILES) == len(set(loader.CODE_FILES)) == 81
    revisions = {}
    for name in loader.CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'SYNTHETIC_CODE_FIXTURE')
        revisions[name] = path.read_bytes()
    loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=lambda name: revisions[name])
    revisions[dependency] = b'SYNTHETIC_CHANGED_DOMAIN'
    with pytest.raises(ValueError):
        loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=lambda name: revisions[name])


def test_reviewer_code_reuse_requires_all_fixed_inputs_byte_identical(tmp_path):
    revisions = {}
    for name in loader.CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'SYNTHETIC_CODE_FIXTURE')
        revisions[name] = path.read_bytes()
    loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=lambda name: revisions[name])
    name = 'app/agent_registry.py'
    revisions[name] = b'SYNTHETIC_CHANGED_AUTHORITY'
    with pytest.raises(ValueError):
        loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=lambda name: revisions[name])


def separated_code(tmp_path):
    current = {}
    for name in loader.CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'SYNTHETIC_CURRENT_PROTECTED_CODE')
        current[name] = path.read_bytes()
    original = dict(current)
    original['scripts/agent_cert_reviewed_signing.py'] = b'SYNTHETIC_ORIGINAL_VERIFIER_BRIDGE'
    return current, original


def test_new_verifier_bridge_preserves_original_runtime_review_provenance(tmp_path, monkeypatch):
    current, original = separated_code(tmp_path)
    assert 'app/agent_cert_clean_room.py' in loader.CODE_FILES and 'app/agent_cert_clean_room.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert len(loader.CODE_FILES) == 81 and len(loader.RUNTIME_REVIEW_CODE_FILES) == 80
    assert {'app/agent_cert_owned_contract.py','app/agent_cert_owned_contract_review.py'} <= set(loader.RUNTIME_REVIEW_CODE_FILES)
    assert 'app/agent_cert_fresh_input.py' in loader.CODE_FILES and 'app/agent_cert_fresh_input.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert set(loader.CODE_FILES) - set(loader.RUNTIME_REVIEW_CODE_FILES) == {'scripts/agent_cert_reviewed_signing.py'}
    value = entry()
    value['record']['reviewer_code_revision'] = REVIEW
    value['verifier_code_revision'] = INVOKE
    revisions = {REVIEW: original, INVOKE: current}
    calls = []
    monkeypatch.setattr(loader, 'sign_reviewed_case', lambda row, **kwargs: calls.append((row, kwargs)) or row)
    result = loader.run(manifest([value]), root=tmp_path, protected_source_revision=INVOKE,
        public_pin={}, sign_digest=lambda _: None, now=datetime.now(timezone.utc),
        check_code=lambda root, revision: loader.unchanged_reviewer_code(root, revision,
            read_revision=revisions[revision].__getitem__),
        check_runtime_code=lambda root, revision: loader.unchanged_runtime_reviewer_code(root, revision,
            read_revision=revisions[revision].__getitem__))
    assert result['signed_case_count'] == 1
    assert calls[0][0] == value['record']
    assert calls[0][1]['reviewer_code_revision'] == REVIEW
    assert calls[0][1]['verifier_code_revision'] == INVOKE


@pytest.mark.parametrize('dependency', loader.RUNTIME_REVIEW_CODE_FILES)
def test_separate_verifier_version_cannot_allow_changed_original_runtime_oracle_or_trust_input(tmp_path, dependency):
    _, original = separated_code(tmp_path)
    original[dependency] = b'SYNTHETIC_CHANGED_ORIGINAL_RUNTIME_INPUT'
    with pytest.raises(ValueError, match='Protected reviewed-case admission rejected'):
        loader.unchanged_runtime_reviewer_code(tmp_path, REVIEW, read_revision=original.__getitem__)


def test_complete_current_verifier_closure_still_pins_the_changed_bridge(tmp_path):
    current, _ = separated_code(tmp_path)
    current['scripts/agent_cert_reviewed_signing.py'] = b'SYNTHETIC_UNREVIEWED_CURRENT_BRIDGE'
    with pytest.raises(ValueError, match='Protected reviewed-case admission rejected'):
        loader.unchanged_reviewer_code(tmp_path, INVOKE, read_revision=current.__getitem__)


def test_missing_or_private_upstream_code_error_is_sanitized(tmp_path):
    path = tmp_path / loader.CODE_FILES[0]
    path.parent.mkdir(parents=True)
    path.write_bytes(b'SYNTHETIC_CODE_FIXTURE')
    def reject(name):
        raise RuntimeError('PRIVATE_SYNTHETIC_DEPENDENCY_ERROR')
    with pytest.raises(ValueError) as error:
        loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=reject)
    assert 'PRIVATE' not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_workflow_remains_fixed_protected_main_without_signing_inputs():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/prime-verifier-signer.yml').read_text()
    assert 'workflow_call:' in workflow and '\n  inputs:' not in workflow
    assert 'REF_PROTECTED' in workflow and 'refs/heads/main' in workflow
    assert 'EVENT_NAME' in workflow and 'workflow_dispatch' in workflow
    assert 'python -m scripts.sign_admitted_agent_cases' in workflow
    assert 'persist-credentials: false' in workflow and 'fetch-depth: 0' in workflow
    assert 'verifier-output/signed-cases.json' in workflow
    assert 'secrets: inherit' not in workflow
