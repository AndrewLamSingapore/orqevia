import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_ID = "sha256:67af1345345ab8b89b2195507c3ed8343ac1998de79ec81f8494dcaf49346f37"
SOURCE = "767f9451d42c65eb905f2c3e5f816536c4e17982"
MANIFEST_SHA256 = "8024013629f992fd65a6895a0fd56eb20bf60b166b04c8c9f8bea734ae698056"


def test_gen7_runtime_receipt_matches_manifest_and_signed_closure():
    manifest_raw = (ROOT / "governance/runtime-baselines/golden-gen7-manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == MANIFEST_SHA256
    manifest = json.loads(manifest_raw)
    receipt_path = ROOT / "governance/runtime-baselines" / Path(manifest["runtime_receipt"]["path"]).name
    receipt = json.loads(receipt_path.read_bytes())
    signed = json.loads((ROOT / "governance/fresh29-20261019-signed-cases-39237401371.json").read_bytes())

    assert manifest["golden_baseline_id"] == "orqevia-golden-gen7-20261019"
    assert manifest["source"]["accepted_commit"] == SOURCE
    assert manifest["build"]["image_id"] == IMAGE_ID
    assert manifest["interface_build"]["image_id"] == IMAGE_ID
    assert manifest["acceptance"]["overall_provider_status"] == "READY"
    assert manifest["acceptance"]["queue_liveness"] == {"passed": 21, "failed": 0}
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == manifest["runtime_receipt"]["sha256"]
    assert receipt["source"]["commit"] == SOURCE
    assert receipt["backend"]["image_id"] == IMAGE_ID
    assert receipt["interface"]["image_id"] == IMAGE_ID
    assert receipt["signed_closure"]["artifact_sha256"] == (
        "192ced6249dd32218a0f89b1f70b3db22e4f32c776a9fab77265a51b968bfb50"
    )
    assert signed["state"] == "SIGNED_CASE_EVIDENCE"
    assert signed["signed_case_count"] == 29
    assert signed["l7_awarded"] is False


def test_attestation_verifier_defaults_bind_the_deployed_candidate():
    script = (ROOT / "scripts/verify_live_runtime_attestation.ps1").read_text(encoding="utf-8")
    assert f"ExpectedSource = '{SOURCE}'" in script
    assert f"ExpectedImageDigest = '{IMAGE_ID}'" in script
    assert "ExpectedGeneration = 'orqevia-golden-gen7-20261019'" in script
    assert "ExpectedReceiptDigest = 'sha256:74064717221f5948d04ef62e5b0e1f0dee3d17580e3621b4dc7a86bd9bf1955b'" in script


def test_status_records_post_deploy_evidence_without_new_verified_claim():
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    start = status.index("## ORQEVIA signed naming candidate deployment - 19 October 2026")
    end = status.index("\n## ", start + 1) + 1
    section = status[start:end]
    assert IMAGE_ID in section
    assert "21/21, 0 failed" in section
    assert "orqevia-golden-gen7-20261019" in section
    assert "### Claimed, not independently checked" in section
    assert "### Verified" not in section
