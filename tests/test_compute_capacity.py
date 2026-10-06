import os
import tempfile
import hashlib
import json
from unittest.mock import patch
import pytest

from app.compute_ledger import ComputeLedger
from app.model_gateway import ModelGateway
from app import compute_profile
from app.settings import PrimeSettings
from tests.backend_receipt_fixture import install as install_backend_receipt


def settings(**overrides):
    values = dict(
        ollama_base_url="http://ollama.test", fast_model="fast:1", deep_model="deep:1",
        evaluator_model="evaluator:1", embedding_model="embed:1", compute_profile="balanced",
        multi_specialist_workers=3, context_tokens=16384, max_output_tokens=4096, keep_alive="10m",
    )
    values.update(overrides)
    return PrimeSettings(**values)


def test_evaluator_role_and_throughput_are_recorded(monkeypatch,tmp_path):
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'measured')
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', os.path.join(directory, 'queue.db'))
        install_backend_receipt(monkeypatch,tmp_path,'http://ollama.test')
        # The gateway requires an independently measured peak, even when the
        # operator memory receipt itself is valid.
        raw = json.dumps({'schema':'abex.measured-compute.v1',
                          'normal_concurrency':1,'minimum_available_mib':1,
                          'context_tokens':16384,'output_limit':4096,
                          'runtime_version':'fixture-ollama',
                          'models':{'evaluator:1':{'peak_mib':1024,'digest':'a'*64}}}).encode()
        profile = tmp_path / 'measured-profile.json'
        profile.write_bytes(raw)
        monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE', str(profile))
        monkeypatch.setenv('PRIME_MEASURED_COMPUTE_PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
        compute_profile.load_compute_profile.cache_clear()
        compute_profile.runtime_compute_profile.cache_clear()
        monkeypatch.setattr(compute_profile, 'verify_runtime_identity', lambda *_: None)
        ledger = ComputeLedger(os.path.join(directory, "compute.db"))
        gateway = ModelGateway(ledger=ledger, settings=settings())
        captured = {}
        def post(url, payload, headers, timeout):
            captured.update(payload)
            return {
                "response": "bounded answer", "done": True, "prompt_eval_count": 20, "eval_count": 10,
                "prompt_eval_duration": 2_000_000_000, "eval_duration": 1_000_000_000,
                "total_duration": 3_000_000_000, "load_duration": 0,
            }
        gateway._post = post
        result = gateway.local(prompt="evaluate", role="evaluator")
        assert result.model == "evaluator:1"
        assert result.usage["output_tokens_per_second"] == 10.0
        assert captured["options"] == {"num_ctx": 16384, "num_predict": 4096}
        summary = ledger.summary()
        assert summary["groups"][0]["success_rate"] == 1.0
        assert summary["groups"][0]["average_output_tokens_per_second"] == 10.0
        compute_profile.load_compute_profile.cache_clear()
        compute_profile.runtime_compute_profile.cache_clear()


def test_golden_gateway_local_inference_needs_no_measured_telemetry(monkeypatch,tmp_path):
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE', 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    gateway = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'ledger.db')),
                           settings=settings(fast_model='gemma3:1b'))
    gateway._post = lambda *_args: {'response': 'baseline answer', 'done': True}
    assert gateway.local(prompt='fixture').text == 'baseline answer'


def test_golden_gateway_keeps_one_shared_local_slot(monkeypatch,tmp_path):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    golden_settings = settings(fast_model='gemma3:1b')
    first = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'first-ledger.db')),
                         settings=golden_settings)
    second = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'second-ledger.db')),
                          settings=golden_settings)
    second._post = lambda *_args: {'response': 'second answer', 'done': True}

    def first_post(*_args):
        with pytest.raises(PermissionError, match='occupied'):
            second.local(prompt='overlapping')
        return {'response': 'first answer', 'done': True}

    first._post = first_post
    assert first.local(prompt='first').text == 'first answer'
    assert second.local(prompt='after completion').text == 'second answer'


def test_golden_gateway_rejects_unobserved_deep_model(monkeypatch,tmp_path):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    gateway = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'ledger.db')),
                           settings=settings(fast_model='gemma3:1b', deep_model='qwen3:14b'))
    gateway._post = lambda *_args: (_ for _ in ()).throw(AssertionError('backend contacted'))
    with pytest.raises(PermissionError, match='requires measured'):
        gateway.local(prompt='fixture', deep=True)


def test_max_profile_defaults_are_bounded():
    with patch.dict(os.environ, {"PRIME_COMPUTE_PROFILE": "max"}, clear=True):
        value = PrimeSettings.from_env()
    assert value.compute_profile == "max"
    assert value.multi_specialist_workers == 4
    assert value.context_tokens == 32768
    assert value.max_output_tokens == 8192
