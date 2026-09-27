import importlib.util
from pathlib import Path


def test_independent_jarvis_candidate_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_jarvis_candidate.py"
    spec = importlib.util.spec_from_file_location("verify_jarvis_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["passed"] == result["total"] == 7
    assert result["production_touched"] is False
    assert result["physical_phone_tested"] is False
