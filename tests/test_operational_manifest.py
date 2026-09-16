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


def test_fresh_dell_acceptance_still_requires_abex_receipt():
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
    manifest["alignment_state"]["overall"] = "CURRENT"
    manifest["verification"]["stale_reasons"] = []
    result = assess_static(manifest, inventory, now=now)
    assert result.errors == []
    assert result.stale_reasons == ["abex_runtime_receipt_missing"]


def test_published_image_can_be_ahead_of_unverified_host():
    manifest, inventory = fixtures()
    manifest["systems"]["prime"]["release_sha"] = "f" * 40
    manifest["systems"]["prime"]["published_image"] = "ghcr.io/andrewlamsingapore/prime:sha-fffffff"
    now = datetime.fromisoformat(manifest["as_of_utc"].replace("Z", "+00:00"))
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
    baseline = datetime.fromisoformat(manifest["as_of_utc"].replace("Z", "+00:00"))
    result = assess_static(manifest, inventory, now=baseline + timedelta(days=3))
    assert result.errors == []
    assert "verification_expired:manifest" in result.stale_reasons


def test_missing_deployment_authentication_cannot_prove_current(monkeypatch):
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    def fake(url, **kwargs):
        if '/contents/' in url:
            import base64
            if '/sky-tablet/' in url:
                return {"content": base64.b64encode(b'sky artifact').decode()}
            return {"content": base64.b64encode(b'{"contract_version":"2.0.0"}').decode()}
        for system in manifest['systems'].values():
            if url == system.get('health_url'): return {'ok': True, 'revision': system['runtime_sha']}
            if '/repos/' + system['repository'] + '/commits/' in url:
                return {'sha': system['source_head_sha'] if url.endswith('/main') else system['release_sha']}
        raise AssertionError(url)
    monkeypatch.setattr(verifier, 'http_json', fake)
    monkeypatch.setattr(verifier, 'http_bytes', lambda *args, **kwargs: b'sky artifact')
    monkeypatch.delenv('VERCEL_TOKEN', raising=False)
    result = verifier.Assessment()
    verifier.assess_live(manifest, result)
    expected = verifier.EXPECTED_PROJECTS | verifier.EXPECTED_STATIC_PROJECTS
    assert {f'vercel_api_not_verified:{x}' for x in expected}.issubset(result.stale_reasons)


def test_sky_static_runtime_is_part_of_the_active_ssot():
    from scripts import verify_operational_manifest as verifier
    manifest, inventory = fixtures()
    now = datetime.fromisoformat(manifest["as_of_utc"].replace("Z", "+00:00"))
    result = assess_static(manifest, inventory, now=now)
    assert "sky" in verifier.EXPECTED_ACTIVE
    assert manifest["systems"]["sky"]["production_state"] == "READY"
    assert result.errors == []


def test_refresh_advances_only_corroborated_public_runtime_facts():
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    manifest = copy.deepcopy(manifest)
    now = datetime(2026, 9, 12, 7, 0, tzinfo=timezone.utc)
    head = "1" * 40
    evidence = {
        "github": {"authority": {"source_head_sha": head}},
        "vercel": {"authority": {
            "health_ok": True,
            "runtime_sha": head,
            "api_verified": False,
        }},
    }

    old_deployment = manifest["systems"]["authority"]["production_deployment_id"]
    assert verifier.refresh_from_live(manifest, evidence, now=now) is True
    authority = manifest["systems"]["authority"]
    assert authority["source_head_sha"] == head
    assert authority["release_sha"] == head
    assert authority["runtime_sha"] == head
    assert authority["production_deployment_id"] == old_deployment
    assert authority["state"] == "SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED"


def test_refresh_does_not_promote_uncorroborated_runtime():
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    manifest = copy.deepcopy(manifest)
    before = copy.deepcopy(manifest["systems"]["game"])
    evidence = {
        "github": {"game": {"source_head_sha": "2" * 40}},
        "vercel": {"game": {
            "health_ok": True,
            "runtime_sha": "3" * 40,
            "api_verified": False,
        }},
    }
    verifier.refresh_from_live(manifest, evidence, now=datetime.now(timezone.utc))
    assert manifest["systems"]["game"] == before


def test_refresh_records_sky_drift_without_relabeling_release():
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    manifest = copy.deepcopy(manifest)
    sky = manifest["systems"]["sky"]
    previous_release = sky["release_sha"]
    head = "4" * 40
    evidence = {
        "github": {"sky": {"source_head_sha": head}},
        "vercel": {"sky": {
            "current_source_content_sha256": "5" * 64,
            "runtime_content_sha256": "6" * 64,
            "api_verified": False,
        }},
    }
    verifier.refresh_from_live(manifest, evidence, now=datetime.now(timezone.utc))
    assert sky["source_head_sha"] == head
    assert sky["release_sha"] == previous_release
    assert sky["state"] == "SOURCE_HEAD_OBSERVED_RUNTIME_CONTENT_DRIFT"
    assert "production artifact content hash differs" in manifest["implementation_frontier"]["sky_tablet"]


def test_refresh_does_not_churn_fresh_unchanged_observations():
    from scripts import verify_operational_manifest as verifier
    manifest, _ = fixtures()
    manifest = copy.deepcopy(manifest)
    authority = manifest["systems"]["authority"]
    authority["state"] = "SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED"
    checked = datetime.fromisoformat(authority["verified_at_utc"].replace("Z", "+00:00"))
    head = authority["source_head_sha"]
    evidence = {
        "github": {"authority": {"source_head_sha": head}},
        "vercel": {"authority": {
            "health_ok": True,
            "runtime_sha": head,
            "api_verified": False,
        }},
    }
    assert verifier.refresh_from_live(
        manifest, evidence, now=checked + timedelta(hours=1)
    ) is False


def test_current_prime_identity_cannot_reuse_historical_dell_receipt():
    manifest, inventory = fixtures()
    manifest['systems']['prime']['runtime_sha'] = manifest['dell_runtime']['runtime_sha']
    result = assess_static(manifest, inventory, now=datetime.now(timezone.utc))
    assert 'unverified current PRIME runtime_sha must be null; retain historical identity separately' in result.errors


def test_unknown_current_prime_identity_is_valid_but_not_accepted():
    manifest, inventory = fixtures()
    result = assess_static(manifest, inventory, now=datetime.now(timezone.utc))
    assert result.errors == []
    assert manifest['systems']['prime']['runtime_sha'] is None
    assert 'abex_runtime_receipt_missing' in result.stale_reasons
