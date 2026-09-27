"""Guard immutable failure evidence; these are not production acceptance tests."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence'
CAPTURES = EVIDENCE / 'evidence-lens-e2e-20260927'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_original_failure_captures_are_byte_identical():
    index = load(CAPTURES / 'SHA256SUMS.json')
    for entry in index['files']:
        raw = (CAPTURES / entry['path']).read_bytes()
        assert len(raw) == entry['bytes']
        assert hashlib.sha256(raw).hexdigest() == entry['sha256']


def test_executed_tasks_and_artifacts_cannot_be_promoted_into_evidence_pass():
    receipt = load(EVIDENCE / 'EVIDENCE_LENS_PRODUCTION_QUALIFICATION_20260927.json')
    assert receipt['verdict'] == 'ABEX_EVIDENCE_LENS_E2E_FAIL'
    assert receipt['lens_status'] == 'NOT_COMPLETE'
    assert {case['case'] for case in receipt['cases']} == set('ABCDEF')
    assert len({case['task_id'] for case in receipt['cases']}) == 6
    for case in receipt['cases']:
        assert case['result'] == 'FAIL'
        assert case['actual_classification']['task_lifecycle'] == 'COMPLETED'
        assert case['persistence_retrieval']['task'] == 'PASS'
        assert case['persistence_retrieval']['artifact'] == 'PASS'
        assert case['persistence_retrieval']['lens_record'] == 'FAIL_NOT_CREATED'
        assert case['ssot_update']['result'] == 'FAIL'
        assert case['model_memory_used_as_authoritative_evidence'] == 'NO'
        raw = (CAPTURES / (case['case'] + '-artifact.bin')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case['evidence_digest']['artifact']


def test_expected_qualifier_evidence_is_not_attributed_to_jarvis_retrieval():
    receipt = load(EVIDENCE / 'EVIDENCE_LENS_PRODUCTION_QUALIFICATION_20260927.json')
    for source in receipt['expected_evidence_sources']:
        assert source['retrieved_by'] == 'ABEX_QUALIFIER_NOT_JARVIS'
    for case in receipt['cases']:
        assert case['commit_version']['evidence_source_commit_returned_by_runtime'] is None
        assert case['evidence_digest']['claim_source_digest_returned_by_runtime'] is None
        if case['case'] != 'A':
            assert case['authoritative_source_retrieved_by_runtime'] is None


def test_model_fabrications_remain_untrusted_but_are_not_hidden():
    receipt = load(EVIDENCE / 'EVIDENCE_LENS_PRODUCTION_QUALIFICATION_20260927.json')
    for case in receipt['cases']:
        if case['case'] not in 'CEF':
            continue
        assert case['model_prose_presented_unsupported_sources_as_evidence'] is True
        path = CAPTURES / case['persistence_retrieval']['reads'][-1]
        result = load(path)['response']['body']['result']
        assert result['type'] == 'MODEL_CONTENT'
        assert result['authoritative'] is False
        assert result['verification_status'] == 'VERIFY_REQUIRED'
        assert result['may_update_truth_plane'] is False
