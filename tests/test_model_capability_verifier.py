import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_model_capabilities", ROOT / "scripts" / "verify_model_capabilities.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_current_profile_is_derived_exactly_from_receipts():
    result = MODULE.verify(MODULE.DEFAULT_PROFILE, MODULE.DEFAULT_EVIDENCE)
    assert result["status"] == "PASS"
    assert result["verified_models"] == ["gemma3:1b", "gemma3:4b"]
    assert result["authority_granted"] is False
    assert len(result["profile_sha256"]) == 64


def test_verifier_rejects_capability_overclaim(tmp_path):
    profile = json.loads(MODULE.DEFAULT_PROFILE.read_text(encoding="utf-8"))
    profile["profiles"][0]["verified_capabilities"].append("structured_output")
    path = tmp_path / "overclaim.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="overclaim"):
        MODULE.verify(path, MODULE.DEFAULT_EVIDENCE)


def test_verifier_rejects_tampered_privacy_boundary(tmp_path):
    evidence = json.loads(MODULE.DEFAULT_EVIDENCE[0].read_text(encoding="utf-8"))
    evidence["measurement_scope"]["response_content_persisted"] = True
    path = tmp_path / "unsafe-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="response-content"):
        MODULE.verify(MODULE.DEFAULT_PROFILE, (path, MODULE.DEFAULT_EVIDENCE[1]))
