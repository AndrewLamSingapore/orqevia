import copy
import json
import shutil
from pathlib import Path

from scripts.verify_golden_gen4 import validate


ROOT = Path(__file__).resolve().parents[1]


def test_golden_gen4_binds_epoch_runtime_and_preserves_audio_failure():
    assert validate() == []


def test_golden_gen4_rejects_source_drift_and_wrong_interface_binding(tmp_path):
    (tmp_path / "governance").mkdir()
    (tmp_path / "docs/evidence").mkdir(parents=True)
    shutil.copy2(ROOT / "governance/golden-gen4-manifest.json", tmp_path / "governance/golden-gen4-manifest.json")
    shutil.copy2(
        ROOT / "docs/evidence/ORQEVIA_RUNTIME_RECEIPT_48648EDD_20261016.json",
        tmp_path / "docs/evidence/ORQEVIA_RUNTIME_RECEIPT_48648EDD_20261016.json",
    )
    manifest_path = tmp_path / "governance/golden-gen4-manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = copy.deepcopy(value)
    changed["source"]["accepted_commit"] = "0" * 40
    changed["interface_build"]["source_revision"] = "1" * 40
    manifest_path.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")
    errors = validate(tmp_path)
    assert "source" in errors
    assert "interface_source" in errors
