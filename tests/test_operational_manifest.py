import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.verify_operational_manifest import assess_static


ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    manifest = json.loads((ROOT / "governance" / "operational-manifest.json").read_text())
    inventory = json.loads((ROOT / "governance" / "branch-inventory.json").read_text())
    return manifest, inventory


def test_current_requires_fresh_post_update_dell_acceptance():
    manifest, inventory = fixtures()
    now = datetime.fromisoformat(manifest["verification"]["verified_at_utc"].replace("Z", "+00:00"))
    manifest = copy.deepcopy(manifest)
    manifest["dell_runtime"]["accepted"] = True
    manifest["dell_runtime"]["post_update_status"] = True
    manifest["status"] = "CURRENT"
    manifest["verification"]["stale_reasons"] = []
    result = assess_static(manifest, inventory, now=now)
    assert result.errors == []
    assert result.stale_reasons == []


def test_verification_expires_after_24_hours():
    manifest, inventory = fixtures()
    manifest = copy.deepcopy(manifest)
    manifest["dell_runtime"]["accepted"] = True
    manifest["dell_runtime"]["post_update_status"] = True
    manifest["status"] = "STALE"
    baseline = datetime.fromisoformat(manifest["verification"]["verified_at_utc"].replace("Z", "+00:00"))
    result = assess_static(manifest, inventory, now=baseline + timedelta(hours=25))
    assert any(reason.startswith("verification_expired:") for reason in result.stale_reasons)


def test_invalid_contract_commit_is_rejected():
    manifest, inventory = fixtures()
    manifest = copy.deepcopy(manifest)
    manifest["shared_contract"]["source_sha"] = "a05fa2e41221d0000110fb24e4641985633c14fb"
    now = datetime.now(timezone.utc)
    result = assess_static(manifest, inventory, now=now)
    assert "shared contract source_sha is not the canonical publication commit" in result.errors
