"""Driver bounds and hold behavior only; no inference or public HTTP call."""
import argparse
import json
import pytest
from scripts import agent_tool_bridge_specimen as specimen


def args(tmp_path, stage='prepare', **changes):
    return argparse.Namespace(stage=stage, output_dir=tmp_path,
        deployment_confirmed=False, expected_source=None, expected_image=None, **changes)


def test_preparation_and_packet_do_not_submit_or_supply_task_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(specimen, 'rpc', lambda *a, **k: pytest.fail('Preparation must not call runtime'))
    prepared = specimen.run(args(tmp_path))
    assert prepared['maximum_initial_model_jobs'] == 1 and prepared['maximum_feedback_model_jobs'] == 1
    scenario = json.loads((tmp_path / 'scenario.json').read_text())
    assert scenario['answers_supplied'] is False and scenario['source_contents_supplied_before_retrieval'] is False
    from app.response_schema import canonicalize_schema
    assert canonicalize_schema(scenario['response_schema'])
    packet = specimen.run(args(tmp_path, stage='packet'))
    assert 'generation-job.json' in packet['missing_evidence']
    assert 'deployment-identity-before.json' in packet['missing_evidence']
    assert 'runtime-source-custody.json' in packet['missing_evidence']
    result = json.loads((tmp_path / 'azure-assessment-packet.json').read_text())
    assert result['signed_cases'] == [] and result['full_role_accepted_count'] == 0
    assert result['azure_signing_or_credentials_used'] is False
    assert result['existing_owner_credentials_used_for_loopback_auth'] is False
    assert len(list(tmp_path.glob('azure-assessment-packet-*.json'))) == 1


@pytest.mark.parametrize('stage', ['submit', 'collect', 'feedback', 'finish'])
def test_mutating_stages_hold_before_deployment_confirmation(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(specimen, 'rpc', lambda *a, **k: pytest.fail('No submission before deployment'))
    with pytest.raises(PermissionError):
        specimen.run(args(tmp_path, stage=stage))


@pytest.mark.parametrize('change', [{'actor': 'a19'}, {'parameters': {'url': 'https://other.example/'}},
    {'service': 'secrets.request'}, {'kind': 'workspace'}])
def test_actual_model_request_rejected_instead_of_fixed(change):
    step = {'id': 'source', 'kind': 'service', 'service': 'internet.public.read',
            'parameters': {'url': specimen.SOURCE_URL}, **change}
    raw = json.dumps({'schema': specimen.SCHEMA, 'requests': [step]})
    with pytest.raises((ValueError, PermissionError)):
        specimen.check_model_request(raw)


def test_confirmed_runtime_source_mismatch_still_stops(tmp_path, monkeypatch):
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'a' * 40)
    value = args(tmp_path)
    value.deployment_confirmed = True
    value.expected_source = 'b' * 40
    value.expected_image = 'sha256:' + 'c' * 64
    with pytest.raises(PermissionError):
        specimen.guard(value)


def test_local_payload_receipt_mismatch_is_detected_without_inference():
    from app.direct_stream import inference_request
    from app.settings import SETTINGS
    from app.compute_profile import generation_options
    from app.job_queue import Provider
    from app.response_schema import canonicalize_schema
    job = {'model': SETTINGS.fast_model, 'provider': 'ollama-fast',
        'prompt': specimen.prompt(), 'response_format': 'strict_json',
        'response_schema': json.dumps(canonicalize_schema(specimen.response_schema()))}
    _, _, receipt = inference_request(job, Provider('ollama-fast', 'local', SETTINGS.fast_model, 1024, 0, 1),
                                    settings=SETTINGS, options=generation_options)
    job['inference_receipt'] = json.dumps(receipt)
    assert specimen.inference_receipt_bound(job)
    receipt['prompt_sha256'] = 'f' * 64
    job['inference_receipt'] = json.dumps(receipt)
    assert not specimen.inference_receipt_bound(job)


def test_diagnosed_second_prompt_only_clarifies_identifier_grammar():
    assert specimen.prompt(2).startswith(specimen.prompt(1))
    assert specimen.OBJECTIVE in specimen.prompt(2)
    assert specimen.SOURCE_URL in specimen.prompt(2)
    assert 'start with a lowercase ASCII letter' in specimen.prompt(2)
