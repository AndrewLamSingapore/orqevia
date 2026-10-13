import importlib.util
import copy
import json
import shutil
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


def test_manifest_verifier_rejects_legacy_or_modified_logo_assets(tmp_path):
    from scripts.verify_jarvis_candidate import ROOT, approved_manifest_icons

    pwa = ROOT / "clients/pwa"
    manifest = json.loads((pwa / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert approved_manifest_icons(manifest, pwa)
    legacy = copy.deepcopy(manifest)
    legacy["icons"][0]["src"] = "/pwa/icons/orqevia-v1-192.png"
    assert not approved_manifest_icons(legacy, pwa)
    masking = copy.deepcopy(manifest)
    masking["icons"][0]["purpose"] = "any maskable"
    assert not approved_manifest_icons(masking, pwa)

    shutil.copytree(pwa / "icons", tmp_path / "icons")
    asset = tmp_path / "icons/orqevia-official-v1-192.png"
    asset.write_bytes(asset.read_bytes() + b"unapproved-change")
    assert not approved_manifest_icons(manifest, tmp_path)
