"""Dated real role/review evidence integrity, not signing or full L7 proof.

No provider or signing calls. Evaluate historical evidence at its pinned review
record time; the actual protected signer separately enforces current expiry.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest

from app.agent_cert_transport import bind_cloud_case, canonical_cert_case
from app.agent_registry import agent_record
from scripts.agent_cert_reviewed_signing import CertificationReviewError, _review, sign_reviewed_case
from scripts.sign_admitted_agent_cases import parse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '5b3dd3aa09a9f91fa52c71560498b1401443562c'
IMAGE = 'sha256:4bf082c30689a6ea96178b1f39ea77cf7a1569ae92440fc9e0ebcfbb41247004'
EXECUTION_SHA = '7724fcb99725f0266cff89ee6332ddca7e366e3f559f2a19ba287f52b8bcd88c'
REVIEW_SHA = 'd02c66770a17757f18a2dad4499875650d9afe89b762571f328fb5f27e4d4b23'


def case():
    entries = parse((ROOT / 'governance/agent-cert-historical-admissions/a19-role-normal-20261007.json').read_bytes())
    matches = [entry for entry in entries if entry['record']['agent_id'] == 'a19'
               and entry['record']['dimension'] == 'role'
               and entry['record']['test_case'] == 'normal']
    assert len(matches) == 1
    entry = matches[0]
    directory = ROOT / entry['evidence_directory'] / 'a19'
    return entry, (directory / 'execution.json').read_bytes(), (directory / 'review.json').read_bytes()


def check(entry, primary, review, *, now=None):
    policy = entry['cloud_policy']
    spec = canonical_cert_case('a19', 'responsibility.a19', 'role:normal')
    binding = bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                              expected_policy_sha256=entry['owner_policy_sha256'])
    return _review(entry['record'], primary, review, source_revision=SOURCE,
                   runtime_image_id=IMAGE, reviewer_code_revision=SOURCE,
                   cloud_binding=binding, cloud_policy=policy,
                   expected_owner_policy_sha256=entry['owner_policy_sha256'],
                   now=now or datetime.fromisoformat(entry['record']['last_revalidated']))


def test_original_execution_and_review_bytes_and_independent_identity():
    entry, primary, review = case()
    assert len(primary) == 4569 and hashlib.sha256(primary).hexdigest() == EXECUTION_SHA
    assert len(review) == 6040 and hashlib.sha256(review).hexdigest() == REVIEW_SHA
    assert entry['execution_sha256'] == entry['record']['evidence_sha256'] == EXECUTION_SHA
    assert entry['review_sha256'] == entry['record']['review_evidence_sha256'] == REVIEW_SHA
    assert entry['execution_source_revision'] == entry['reviewer_code_revision'] == SOURCE
    assert entry['runtime_image_id'] == IMAGE
    assert entry['record']['verifier'] == 'a26' != entry['record']['executor_identity']
    assert agent_record('a26')['agent_id'] == 'a26'
    assert check(entry, primary, review) is True


def test_completed_case_is_preserved_exactly_not_resubmitted_after_reviewer_code_changes():
    archive = ROOT / 'governance/agent-cert-historical-admissions'
    original = (archive / 'a19-role-normal-20261007.json').read_bytes()
    signed = (archive / 'a19-role-normal-signed-37613202210.json').read_bytes()
    assert len(original) == 2413
    assert hashlib.sha256(original).hexdigest() == '0046f5f3a8926e58b30b9a9c79366405c82b9c4ae4d1d67c6d6d4dc75bc01fd2'
    assert len(signed) == 1804
    assert hashlib.sha256(signed).hexdigest() == '726f997f7bbe8a50ec42fefeb0720aea92b765ffcadae35b20b781e7a286cfca'
    output = json.loads(signed)
    assert output['signed_case_count'] == 1 and output['l7_awarded'] is False
    active = parse((ROOT / 'governance/agent-cert-reviewed-cases.json').read_bytes())
    # A distinct new case may be admitted; this retired role-normal case must
    # remain historical, preserving its original signed and unsigned bytes.
    assert not any(entry['execution_source_revision'] == SOURCE
        and entry['record'].get('agent_id') == 'a19'
        and entry['record'].get('capability_id') == 'responsibility.a19'
        and entry['record'].get('dimension') == 'role'
        and entry['record'].get('test_case') == 'normal' for entry in active)
    assert all(entry['execution_sha256'] != EXECUTION_SHA
        and entry['review_sha256'] != REVIEW_SHA for entry in active)


def test_exact_case_bytes_remain_non_text_git_inputs():
    entry, _, _ = case()
    attributes = (ROOT / '.gitattributes').read_text()
    assert 'governance/agent-cert-reviewed-cases.json -text' in attributes
    assert entry['evidence_directory'] + '/** -text' in attributes


def test_unsigned_admission_does_not_contain_attestation_or_l7_award():
    entry, _, review = case()
    assert 'attestation' not in entry['record']
    assert 'L7' not in entry['record'].values()
    assert entry['record']['dimension'] == 'role'
    assert entry['record']['test_version'] == 'a19-role-normal-operation-id.v2'
    proof = json.loads(review)['observations']['reviewer_execution']
    assert len(proof['action_records']) == 2


@pytest.mark.parametrize('field,value', [
    ('verifier', 'a19'), ('executor_identity', 'a26'),
    ('source_revision', 'eee2247bb1bb09e6b17952b3f7d01a0e590a2c73'),
    ('test_result', 'FAIL'),
])
def test_forged_case_identity_result_or_digest_denied(field, value):
    entry, primary, review = case()
    altered = deepcopy(entry)
    altered['record'][field] = value
    with pytest.raises(CertificationReviewError, match='RECORD_BINDING_INVALID'):
        check(altered, primary, review)


def test_public_signer_rejects_record_digest_mismatch_before_any_signing():
    entry, _, _ = case()
    altered = deepcopy(entry['record'])
    altered['evidence_sha256'] = '0' * 64
    calls = []
    pin = json.loads((ROOT / 'governance/agent-cert-verifier-azure-pins.json').read_bytes())
    with pytest.raises(CertificationReviewError, match='APPROVED_ARTIFACT_MISMATCH'):
        sign_reviewed_case(altered, evidence_root=ROOT / entry['evidence_directory'],
                           execution_sha256=EXECUTION_SHA, review_sha256=REVIEW_SHA,
                           execution_source_revision=SOURCE, runtime_image_id=IMAGE,
                           reviewer_code_revision=SOURCE, public_pin=pin,
                           sign_digest=lambda digest: calls.append(digest),
                           now=datetime.fromisoformat(entry['record']['last_revalidated']))
    assert calls == []


def test_current_signer_time_must_reject_expired_record():
    entry, primary, review = case()
    with pytest.raises(CertificationReviewError, match='EXECUTION_TIME_INVALID'):
        check(entry, primary, review,
              now=datetime.fromisoformat(entry['record']['expires_at']))


def test_altered_original_bytes_are_not_accepted_as_a_review():
    entry, primary, review = case()
    altered = primary.replace(b'0cabb134', b'1cabb134', 1)
    assert altered != primary
    with pytest.raises(CertificationReviewError, match='COMPLETED_EXECUTION_INVALID'):
        check(entry, altered, review)
