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
    for system in manifest["systems"].values():
        system["verified_at_utc"] = manifest["verification"]["verified_at_utc"]
        if system["source_head_sha"] is not None: system["source_head_sha"] = system["release_sha"]
    manifest["dell_runtime"]["verified_at_utc"] = manifest["verification"]["verified_at_utc"]
    manifest["systems"]["prime"]["runtime_sha"] = manifest["systems"]["prime"]["release_sha"]
    manifest["dell_runtime"]["runtime_sha"] = manifest["systems"]["prime"]["release_sha"]
    manifest["status"] = "CURRENT"
    manifest["verification"]["stale_reasons"] = []
    result = assess_static(manifest, inventory, now=now)
    assert result.errors == []
    assert result.stale_reasons == []


def test_published_image_can_be_ahead_of_unverified_host():
    manifest, inventory = fixtures()
    manifest["systems"]["prime"]["release_sha"] = "f" * 40
    manifest["systems"]["prime"]["published_image"] = "ghcr.io/andrewlamsingapore/prime:sha-fffffff"
    now = datetime.fromisoformat(manifest["verification"]["verified_at_utc"].replace("Z", "+00:00"))
    result = assess_static(manifest, inventory, now=now)
    assert result.errors == []
    assert "release_runtime_drift:prime" in result.stale_reasons


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


def test_age_does_not_turn_truthful_stale_snapshot_into_schema_error():
    manifest, inventory = fixtures()
    baseline = datetime.fromisoformat(manifest["verification"]["verified_at_utc"].replace("Z", "+00:00"))
    result = assess_static(manifest, inventory, now=baseline + timedelta(days=3))
    assert result.errors == []
    assert "verification_expired:manifest" in result.stale_reasons


def test_missing_deployment_authentication_cannot_prove_current(monkeypatch):
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    def fake(url, **kwargs):
        if '/contents/' in url:
            import base64
            return {"content": base64.b64encode(b'{"contract_version":"2.0.0"}').decode()}
        for system in manifest['systems'].values():
            if url == system.get('health_url'): return {'ok': True, 'revision': system['runtime_sha']}
            if '/repos/' + system['repository'] + '/commits/' in url:
                return {'sha': system['source_head_sha'] if url.endswith('/main') else system['release_sha']}
        raise AssertionError(url)
    monkeypatch.setattr(verifier, 'http_json', fake)
    monkeypatch.delenv('VERCEL_TOKEN', raising=False)
    result = verifier.Assessment()
    verifier.assess_live(manifest, result)
    assert {f'vercel_api_not_verified:{x}' for x in verifier.EXPECTED_PROJECTS}.issubset(result.stale_reasons)
