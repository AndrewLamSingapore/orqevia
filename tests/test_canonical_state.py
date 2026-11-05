"""Current release checks use source integrity instead of historical organizational authority."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.check_canonical_state import component_hash_matches, validate_source, validate_state

ROOT = Path(__file__).resolve().parents[1]


def records():
    return tuple(
        json.loads((ROOT / path).read_text(encoding="utf-8"))
        for path in ("system.manifest.json", "config/agent_registry.json")
    )


def test_source_check_does_not_require_historical_portfolio_or_checkpoint(tmp_path):
    product, _ = records()
    for name in ("system.manifest.json", *(item["path"] for item in product["components"].values())):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    result = validate_source(tmp_path)
    assert result["status"] == "PASS" and result["registry_agents"] == 21
    assert result["scope"] == "SOURCE_INTEGRITY_NOT_DEPLOYMENT"
    assert not (tmp_path / "governance").exists()
    assert not (tmp_path / "STATUS.md").exists()


@pytest.mark.parametrize("mutation", ["duplicate_identity", "duplicate_capability", "empty_inventory", "runtime_claim"])
def test_ambiguous_capabilities_or_runtime_claims_cannot_pass(mutation):
    product, registry = records()
    if mutation == "duplicate_identity":
        registry["agents"][1]["agent_id"] = registry["agents"][0]["agent_id"]
    elif mutation == "duplicate_capability":
        registry["agents"][1]["capability_requirements"] = registry["agents"][0]["capability_requirements"]
    elif mutation == "empty_inventory":
        registry["agents"] = []
    elif mutation == "runtime_claim":
        product["verification_scope"] = "PRODUCTION_VERIFIED"
    with pytest.raises(AssertionError):
        validate_state(product, registry)


def test_current_product_has_no_subordinate_portfolio_authority():
    product, registry = records()
    for name in ("authority_scope", "canonical_operational_source", "ecosystem_release_id", "governance"):
        assert name not in product
    assert validate_state(product, registry)


def test_manifest_path_cannot_escape_source_tree(tmp_path):
    product, registry = records()
    product["components"]["task"]["path"] = "../outside.json"
    for name, value in (("system.manifest.json", product), ("config/agent_registry.json", registry)):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
    shutil.copy2(ROOT / "config/agent_registry.json", tmp_path / "config/agent_registry.json")
    shutil.copy2(ROOT / "docs/interface-contract.v1.json", tmp_path / "interface.json")
    product["components"]["interface"]["path"] = "interface.json"
    (tmp_path / "system.manifest.json").write_text(json.dumps(product))
    with pytest.raises(AssertionError, match="within this source tree"):
        validate_source(tmp_path)


def test_component_hash_accepts_checkout_eol_conversion(tmp_path):
    component = tmp_path / "component.json"
    component.write_bytes(b'{\r\n  "ok": true\r\n}\r\n')
    canonical = b'{\n  "ok": true\n}\n'
    assert component_hash_matches(component, hashlib.sha256(canonical).hexdigest())


def test_component_hash_rejects_content_change(tmp_path):
    component = tmp_path / "component.json"
    component.write_bytes(b'{\r\n  "ok": false\r\n}\r\n')
    canonical = b'{\n  "ok": true\n}\n'
    assert not component_hash_matches(component, hashlib.sha256(canonical).hexdigest())
