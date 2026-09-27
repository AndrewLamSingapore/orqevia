import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_independent_receipt_verifier_preserves_raw_and_governed_truth():
    path = ROOT / "scripts" / "verify_structured_output.py"
    spec = importlib.util.spec_from_file_location("verify_structured_output", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["status"] == "PASS"
    assert result["checks_passed"] == 3
    assert result["authority_granted"] is False
    assert result["production_touched"] is False
    assert len(result["evidence_sha256"]) == 64
