"""Absent-Spine HTTP regressions in disposable fixtures; no live certification."""
import pytest

from tests.test_agent_cert_authority_chain import configured, runtime, collect


@pytest.mark.parametrize('prior_authority', [False, True])
def test_authorized_assessment_does_not_create_or_require_spine(runtime, prior_authority):
    spine = runtime.root / 'prime-spine.db'
    assert not spine.exists()
    if prior_authority:
        prior = collect(runtime, 'authority:complete')
        assert prior.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', prior.summary
        assert not spine.exists()
    result = collect(runtime, 'unauthorized_rejection:authorized')
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert result.summary['model_calls'] == 0
    assert result.summary['signature'] == 'NOT_PERFORMED'
    assert result.summary['certification'] == 'UNVERIFIED'
    assert not spine.exists()
