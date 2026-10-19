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


def settings(**overrides):
    values = dict(
        ollama_base_url="http://ollama.test", fast_model="fast:1", deep_model="deep:1",
        evaluator_model="evaluator:1", embedding_model="embed:1", compute_profile="balanced",
        multi_specialist_workers=3, context_tokens=16384, max_output_tokens=4096, keep_alive="10m",
    )
    values.update(overrides)
    return PrimeSettings(**values)


def test_evaluator_role_and_throughput_are_recorded(monkeypatch,tmp_path):
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', os.path.join(directory, 'queue.db'))
        # The gateway requires an independently measured peak, even when the
        # operator memory receipt itself is valid.
        raw = json.dumps({'schema':'abex.measured-compute.v1',
                          'normal_concurrency':1,'minimum_available_mib':1,
                          'context_tokens':16384,'output_limit':4096,
                          'runtime_version':'fixture-ollama',
                          'models':{'evaluator:1':{'peak_mib':1024,'digest':'a'*64}}}).encode()
        profile = tmp_path / 'measured-profile.json'
        profile.write_bytes(raw)
        monkeypatch.setenv('ORQEVIA_MEASURED_COMPUTE_PROFILE', str(profile))
        monkeypatch.setenv('ORQEVIA_MEASURED_COMPUTE_PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
        compute_profile.load_compute_profile.cache_clear()
        compute_profile.runtime_compute_profile.cache_clear()
        monkeypatch.setattr(compute_profile, 'verify_runtime_identity', lambda *_, **__: None)
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
    for name in ('ORQEVIA_LOCAL_ADMISSION_MODE', 'ORQEVIA_BACKEND_MEMORY_RECEIPT',
                 'ORQEVIA_MEASURED_COMPUTE_PROFILE', 'ORQEVIA_MEASURED_COMPUTE_PROFILE_SHA256',
                 'ORQEVIA_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    gateway = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'ledger.db')),
                           settings=settings(fast_model='gemma3:1b'))
    gateway._post = lambda *_args: {'response': 'baseline answer', 'done': True}
    assert gateway.local(prompt='fixture').text == 'baseline answer'


def test_gateway_allows_deep_model_without_a_measured_profile(monkeypatch,tmp_path):
    for name in ('ORQEVIA_BACKEND_MEMORY_RECEIPT', 'ORQEVIA_MEASURED_COMPUTE_PROFILE',
                 'ORQEVIA_MEASURED_COMPUTE_PROFILE_SHA256', 'ORQEVIA_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('ORQEVIA_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    gateway = ModelGateway(ledger=ComputeLedger(str(tmp_path / 'ledger.db')),
                           settings=settings(fast_model='gemma3:1b', deep_model='qwen3:14b'))
    gateway._post = lambda *_args: {'response': 'deep answer', 'done': True}
    assert gateway.local(prompt='fixture', deep=True).text == 'deep answer'


def test_max_profile_defaults_are_bounded():
    with patch.dict(os.environ, {"ORQEVIA_COMPUTE_PROFILE": "max"}, clear=True):
        value = PrimeSettings.from_env()
    assert value.compute_profile == "max"
    assert value.multi_specialist_workers == 4
    assert value.context_tokens == 32768
    assert value.max_output_tokens == 8192
