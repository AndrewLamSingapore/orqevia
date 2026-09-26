#!/usr/bin/env python3
"""Fail-closed, one-generation PRIME.RUNTIME acceptance transition."""
from __future__ import annotations

import argparse, hashlib, json, ssl, subprocess, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.verify_abex_runtime_receipt import validate as validate_receipt
except ModuleNotFoundError:
    from verify_abex_runtime_receipt import validate as validate_receipt

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_SHA = "dc80ee30a8e13c541b677a97df283fc02d75ec81599a6d57e2bb9570f44c014d"
RECEIPT_SHA = "49c6668f38b9654cc1b20e46af7b70664b79b787b45befac8bc42b1d1ce488b0"
VERIFICATION_ID = "f5a6f344-faf9-4eec-b4f9-f73bd20bc5ff"
SOURCE_SHA = "17fad78d410dca5d9101483cb777a2b9b619bac3"
IMAGE_TAG = "prime:sha-17fad78"
IMAGE_ID = "sha256:745244a3a8fb6d2708e96b63504e55c10aead7538fc4ed9c0621328cd7ef3681"
EXPECTED_CHECKS = {"DELL_CLIENT_PATH", "OWNER_AUTHORITY", "PRIME_END_TO_END_EXECUTION", "TASK_UUID_PROVENANCE", "TIMESTAMP_PROVENANCE", "RUNTIME_IDENTITY", "ARTIFACT_BINDING", "AGENT_ROLE_AUTHORITY_ENFORCEMENT", "HALLUCINATION_CONTAINMENT", "SECURITY_BOUNDARY", "RUNTIME_RECEIPT", "ABEX_PRODUCTION_MODIFIED_BY_DELL"}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_documents(artifact_path: Path, receipt_path: Path) -> tuple[dict, dict]:
    assert artifact_path.stat().st_size == 7804 and digest(artifact_path) == ARTIFACT_SHA, "independent artifact bytes mismatch"
    assert digest(receipt_path) == RECEIPT_SHA, "ABEX receipt bytes mismatch"
    artifact, receipt = json.loads(artifact_path.read_bytes()), json.loads(receipt_path.read_bytes())
    assert validate_receipt(receipt, ROOT) == [], "ABEX receipt rejected"
    assert artifact["verification_id"] == artifact["reconciliation_id"] == VERIFICATION_ID
    assert artifact["receipt_hash_digest"] == RECEIPT_SHA
    assert artifact["final_verification"] == "PASS" and artifact["overall_health"] == "GREEN"
    assert artifact["prime_runtime_acceptance"] == "UNVERIFIED" and artifact["abex_modified_by_dell"] is False
    assert artifact["unresolved_findings"] == []
    checks = {row["id"]: row["verdict"] for row in artifact["checks"]}
    assert set(checks) == EXPECTED_CHECKS and checks["ABEX_PRODUCTION_MODIFIED_BY_DELL"] == "NO"
    assert all(value == "PASS" for key, value in checks.items() if key != "ABEX_PRODUCTION_MODIFIED_BY_DELL")
    runtime = artifact["production_runtime_identity"]
    assert runtime["source_sha"] == receipt["runtime"]["source_sha"] == SOURCE_SHA
    assert runtime["image_tag"] == receipt["runtime"]["image_tag"] == IMAGE_TAG
    assert runtime["image_id"] == receipt["runtime"]["image_id"] == IMAGE_ID
    assert runtime["registry_schema"] == "2.0" and runtime["logical_agent_count"] == 21
    assert artifact["post_repair_owner_task_id"] == receipt["physical_owner_iphone_acceptance"]["task_id"]
    return artifact, receipt

def live_snapshot(ca_file: Path) -> dict:
    containers = json.loads(subprocess.run(["docker", "inspect", "prime-epoch-20260919-prime-1", "prime-epoch-20260919-interface-1", "prime-epoch-20260919-ollama-1"], check=True, capture_output=True, text=True).stdout)
    by_name = {row["Name"].lstrip("/"): row for row in containers}
    for name in ("prime-epoch-20260919-prime-1", "prime-epoch-20260919-interface-1"):
        row = by_name[name]
        assert row["Config"]["Image"] == IMAGE_TAG and row["Image"] == IMAGE_ID
        assert row["Config"]["Labels"]["org.opencontainers.image.revision"] == SOURCE_SHA
        assert row["State"]["Health"]["Status"] == "healthy" and row["RestartCount"] == 0 and row["State"]["OOMKilled"] is False
    ollama = by_name["prime-epoch-20260919-ollama-1"]
    assert ollama["State"]["Health"]["Status"] == "healthy" and ollama["RestartCount"] == 0 and ollama["State"]["OOMKilled"] is False
    context = ssl.create_default_context(cafile=str(ca_file))
    def get(path: str) -> bytes:
        with urllib.request.urlopen("https://192.168.1.23:8443" + path, context=context, timeout=10) as response:
            assert response.status == 200 and response.headers["x-prime-protocol"] == "jarvis.interface.v1"
            return response.read()
    index, release = get("/pwa/"), get("/pwa/release.mjs")
    assert hashlib.sha256(index).hexdigest() == "69d5915533dc878a686264f04eb8eca913c1acd1ae8ddd73ac98084b794a18f0"
    assert b"jarvis-shell-v11" in release
    job = json.loads(subprocess.run(["docker", "exec", "prime-epoch-20260919-prime-1", "python", "-c", "import sqlite3,json;c=sqlite3.connect('file:/data/compute-queue.db?mode=ro',uri=True);print(json.dumps(c.execute(\"select status,provider,result,error from compute_jobs where id='4dedf6e0-c899-4926-a3bf-6a684d4f7413'\").fetchone(),ensure_ascii=False))"], check=True, capture_output=True, text=True, encoding="utf-8").stdout)
    assert job[0] == "completed" and job[1] == "ollama-deep" and "JARVIS" in job[2] and not job[3]
    return {"source_sha": SOURCE_SHA, "image_tag": IMAGE_TAG, "image_id": IMAGE_ID, "pwa_index_sha256": hashlib.sha256(index).hexdigest(), "pwa_release": "jarvis-shell-v11", "owner_task": "3c235145-0fbd-4fcb-9983-1074dd3c87f7"}

def transition(manifest: dict, artifact: dict, snapshot: dict, now: str) -> dict:
    assert manifest["abex_runtime"]["state"] == "UNVERIFIED", "transition is not exactly-once"
    receipt_ref = {"path": "docs/evidence/ABEX_RUNTIME_RECEIPT_17FAD78_20260926.json", "sha256": RECEIPT_SHA, "independent_verification": True, "independent_artifact": "docs/evidence/DELL-ABEX-CORRECTED-INDEPENDENT-VERIFICATION-20260926.json", "independent_artifact_sha256": ARTIFACT_SHA, "verification_id": VERIFICATION_ID, "source_sha": SOURCE_SHA}
    manifest["as_of_utc"] = now
    manifest["canonical_release"].update({"runtime_state": "VERIFIED", "scope": "Local ABEX PRIME generation independently verified; broader ecosystem freshness remains separate."})
    manifest["abex_runtime"].update({"state": "VERIFIED", "receipt": receipt_ref, "source_sha": SOURCE_SHA, "observed_image": IMAGE_TAG, "observed_image_id": IMAGE_ID, "verified_at_utc": now, "independent_disagreement": "Historical FAIL preserved and superseded by the corrected independent artifact.", "rule": "Transition produced only by scripts/accept_abex_runtime.py after exact artifact, receipt, live image, TLS/PWA and task validation."})
    manifest["systems"]["prime"].update({"state": "ALIGNED_VERIFIED", "note": "Current ABEX generation independently accepted; Wuhan/Mainland-China remains physical verification pending.", "release_sha": SOURCE_SHA, "runtime_sha": SOURCE_SHA, "published_image": IMAGE_TAG, "verified_at_utc": now})
    dell_verified_at = datetime.fromisoformat(artifact["timestamp"]).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest["dell_runtime"].update({"runtime_sha": SOURCE_SHA, "observed_image": IMAGE_TAG, "verified_at_utc": dell_verified_at, "accepted": True, "post_update_status": True, "result": "Corrected independent verification PASS for current ABEX generation; historical FAIL preserved as superseded.", "observation_scope": "INDEPENDENT_CURRENT_ABEX_RUNTIME_VERIFICATION", "corrected_verification": {"path": receipt_ref["independent_artifact"], "sha256": ARTIFACT_SHA, "verification_id": VERIFICATION_ID}})
    manifest["alignment_state"]["source_and_deployments"] = "LOCAL_PRIME_ACCEPTED_GLOBAL_EVIDENCE_STALE"
    manifest["release_gate"]["current_result"] = "PASSED_LOCAL_PRIME_GLOBAL_EVIDENCE_STALE"
    manifest["verification"]["stale_reasons"] = ["sky_webgl_device_acceptance_unverified", "global_public_system_evidence_expired"]
    manifest["next_actions"] = ["Keep qualified local PRIME production in quiet observation.", "Perform read-only High-Context Engineering gap analysis outside production.", "Complete Wuhan/Mainland-China physical verification when geographically available.", "Refresh unrelated public-system evidence before claiming global CURRENT status."]
    manifest["qualified_local_prime_baseline"] = {"state": "FROZEN", "accepted_at_utc": now, **snapshot, "receipt_sha256": RECEIPT_SHA, "independent_artifact_sha256": ARTIFACT_SHA, "rollback_image": "prime:sha-2ca9b4a", "rollback_checkpoint": "/data/recovery/pwa-mobile-control-predeploy-20260926"}
    manifest["local_prime_commissioning"] = {"state": "CLOSED", "closed_at_utc": now, "basis": ["governed runtime receipt", "corrected independent Dell verification", "live immutable runtime readback", "physical Owner and Dell acceptance"], "wuhan_mainland_china": "PHYSICAL_VERIFICATION_PENDING", "unresolved_p0": 0, "unresolved_p1": 0, "unresolved_p2": 0}
    return manifest

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=ROOT / "docs/evidence/ABEX_RUNTIME_RECEIPT_17FAD78_20260926.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "governance/operational-manifest.json")
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    artifact, _ = validate_documents(args.artifact, args.receipt)
    snapshot = live_snapshot(args.ca_file)
    result = {"verdict": "PRIME.RUNTIME_ACCEPTANCE_PREREQUISITES_VALID", "verification_id": VERIFICATION_ID, "artifact_sha256": ARTIFACT_SHA, "receipt_sha256": RECEIPT_SHA, "runtime": snapshot}
    if args.apply:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        args.manifest.write_text(json.dumps(transition(manifest, artifact, snapshot, now), indent=2) + "\n", encoding="utf-8")
        result["transition"] = "APPLIED"
        result["accepted_at_utc"] = now
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
