import os
import tempfile
from unittest.mock import patch

from app.compute_ledger import ComputeLedger
from app.model_gateway import ModelGateway
from app.settings import PrimeSettings


def settings(**overrides):
    values = dict(
        ollama_base_url="http://ollama.test", fast_model="fast:1", deep_model="deep:1",
        evaluator_model="evaluator:1", embedding_model="embed:1", compute_profile="balanced",
        multi_specialist_workers=3, context_tokens=16384, max_output_tokens=4096, keep_alive="10m",
    )
    values.update(overrides)
    return PrimeSettings(**values)


def test_evaluator_role_and_throughput_are_recorded():
    with tempfile.TemporaryDirectory() as directory:
        ledger = ComputeLedger(os.path.join(directory, "compute.db"))
        gateway = ModelGateway(ledger=ledger, settings=settings())
        captured = {}
        def post(url, payload, headers, timeout):
            captured.update(payload)
            return {
                "response": "bounded answer", "prompt_eval_count": 20, "eval_count": 10,
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


def test_max_profile_defaults_are_bounded():
    with patch.dict(os.environ, {"PRIME_COMPUTE_PROFILE": "max"}, clear=True):
        value = PrimeSettings.from_env()
    assert value.compute_profile == "max"
    assert value.multi_specialist_workers == 4
    assert value.context_tokens == 32768
    assert value.max_output_tokens == 8192
