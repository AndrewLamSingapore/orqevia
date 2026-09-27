import importlib.util
from pathlib import Path


def test_independent_static_vision_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_vision_candidate.py"
    spec = importlib.util.spec_from_file_location("verify_vision_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["passed"] == result["total"] == 5
    assert result["production_touched"] is False and result["camera_used"] is False
