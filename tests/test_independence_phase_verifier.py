import importlib.util
from pathlib import Path


def test_independent_independence_phase_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_independence_phase.py"
    spec = importlib.util.spec_from_file_location("verify_independence_phase", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["passed"] == result["total"] == 7
    assert result["production_touched"] is False
    assert result["physical_black_start_executed"] is False
