"""Local probe preparation preserves the original prompt and never enables cloud."""
import pytest

from scripts.identity_probe_21_runtime import build_requests
from scripts.identity_a21_local_runtime import local_request, run


def test_independent_local_request_keeps_the_exact_installed_identity_prompt():
    original = next(item for item in build_requests() if item['agent'] == 'a21')
    request, prompt = local_request(original)
    assert prompt == original['prompt']
    assert request.data_classification == 'LOCAL_ONLY'
    assert request.max_cost_usd == 0 and request.preferred_provider == 'ollama-fast'
    assert request.objective == original['request']['objective']


def test_changed_identity_prompt_is_rejected():
    original = next(item for item in build_requests() if item['agent'] == 'a21')
    with pytest.raises(ValueError, match='original installed identity prompt changed'):
        local_request({**original, 'prompt': 'tampered'})


def test_revision_mismatch_cannot_submit_local_or_cloud_probe(monkeypatch):
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'b'*40)
    with pytest.raises(ValueError, match='exact installed runtime revision'):
        run('tick', 'a'*40)
