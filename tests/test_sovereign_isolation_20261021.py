"""Real ASGI/task-storage isolation and process reopen; never points at live data.

CLI: python -B tests/test_sovereign_isolation_20261021.py --root <new-scratch-path>
The receipt excludes credential/cookie contents. Real HTTP transports are blocked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.request


REPOSITORY = Path(__file__).resolve().parents[1]
OWNER_ORIGIN = "http://127.0.0.1:18080"
PWA_ORIGIN = "https://127.0.0.1:19443"
FIXTURE_TEXT = b"ORQEVIA standalone recovery fixture 2026-10-21"
MARKER = "ORQEVIA_SOVEREIGN_ISOLATION_FIXTURE_20261021"


def child_environment(root: Path) -> dict[str, str]:
    essential = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in essential}
    data = root / "data"
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "ORQEVIA_DATA_DIR": str(data), "ORQEVIA_COMPUTE_QUEUE_DB": str(data / "compute-queue.db"),
        "ORQEVIA_MEMORY_DB": str(data / "orqevia-memory.db"), "ORQEVIA_SPINE_DB": str(data / "orqevia-spine.db"),
        "ORQEVIA_PROJECT_WORKFLOW_DB": str(data / "project-workflows.db"),
        "ORQEVIA_PROJECT_WORKFLOW_DIR": str(data / "project-workflows"),
        "ORQEVIA_SPINE_TOKEN": "task-local-sovereignty-fixture-not-production",
        "ORQEVIA_REGISTRY_V1_ENABLED": "1", "OLLAMA_BASE_URL": "http://127.0.0.1:1",
        "ORQEVIA_PROVIDER_CATALOG": str(root / "empty-provider-catalog.json"),
        "ORQEVIA_PUBLIC_AGENT_TRACE": "0", "ORQEVIA_OTEL_ENABLED": "0", "ORQEVIA_HIGGSFIELD_ENABLED": "0",
        "ORQEVIA_PWA_ORIGIN": PWA_ORIGIN, "ORQEVIA_PWA_ACCESS_MODE": "pairing",
        "ORQEVIA_PWA_STATIC_DIR": str(REPOSITORY / "clients" / "pwa"),
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": "sovereignty-fixture-owner",
        "PORTAL_RESULT_URL": "", "PORTAL_RESULT_TOKEN": "", "PORTFOLIO_RELAY_URL": "", "PORTFOLIO_RELAY_TOKEN": "",
    })
    return env


def prohibit_real_http() -> list[str]:
    import httpx

    attempts: list[str] = []

    def reject_sync(*_args, **_kwargs):
        attempts.append("real-http-sync")
        raise httpx.ConnectError("HTTP disabled in task-only isolation fixture")

    async def reject_async(*_args, **_kwargs):
        attempts.append("real-http-async")
        raise httpx.ConnectError("HTTP disabled in task-only isolation fixture")

    httpx.HTTPTransport.handle_request = reject_sync
    httpx.AsyncHTTPTransport.handle_async_request = reject_async
    urllib.request.urlopen = reject_sync
    return attempts


def check_pwa() -> dict:
    from fastapi.testclient import TestClient
    from app import interface_server, pwa_sessions as pwa

    headers = {"Origin": PWA_ORIGIN, "X-ORQEVIA-PWA": "1"}
    with TestClient(interface_server.app, base_url=PWA_ORIGIN) as owner, TestClient(interface_server.app, base_url=PWA_ORIGIN) as member, TestClient(interface_server.app, base_url=PWA_ORIGIN) as anonymous:
        assert owner.get("/pwa/").status_code == 200
        assert anonymous.get("/pwa/api/session").json()["authenticated"] is False
        for client, role, account in ((owner, "OWNER", "sovereignty-fixture-owner"), (member, "MEMBER", "sovereignty-fixture-member")):
            code = secrets.token_urlsafe(16)
            with pwa.database() as db:
                db.execute("INSERT INTO pairing(code_hash,expires,used,owner_account_id,role) VALUES(?,?,0,?,?)", (pwa.digest(code), time.time() + 300, account, role))
            response = client.post("/pwa/api/enroll", headers=headers, json={"code": code})
            assert response.status_code == 200
            assert response.json()["role"] == role
            cookie = response.headers["set-cookie"]
            assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
            assert client.post("/pwa/api/enroll", headers=headers, json={"code": code}).status_code == 401
        assert owner.post("/pwa/api/owner-authority-check", headers=headers).status_code == 200
        assert member.post("/pwa/api/owner-authority-check", headers=headers).status_code == 403
        assert anonymous.post("/pwa/api/owner-authority-check", headers=headers).status_code == 401
        uploaded = owner.post("/pwa/api/uploads", headers={**headers, "X-Filename": "isolation.txt"}, content=FIXTURE_TEXT)
        assert uploaded.status_code == 200
        artifact = uploaded.json()["artifactId"]
        path = "/interface/v1/artifacts/" + artifact
        assert owner.get(path).content == FIXTURE_TEXT
        assert member.get(path).status_code == 404
        assert anonymous.get(path).status_code == 401
        assert owner.post("/pwa/api/uploads", headers={**headers, "X-Filename": "../escape.txt"}, content=b"fixture").status_code == 422
        assert owner.post("/pwa/api/logout", headers={**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
        client_id = owner.get("/pwa/api/session").json()["clientId"]
        with pwa.database() as db:
            db.execute("UPDATE sessions SET expires=? WHERE client_id=?", (time.time() - 1, client_id))
        restored = owner.get("/pwa/api/session").json()
        assert restored["authenticated"] and restored["clientId"] == client_id
        with pwa.database() as db:
            hashes = db.execute("SELECT session_hash FROM sessions").fetchall()
            assert len(hashes) == 2 and all(len(row[0]) == 64 for row in hashes)
        return {"pairing": "PASS", "role_denial": "PASS", "owned_upload_isolation": "PASS", "trusted_device_expiry_restore": "PASS", "server_stored_sessions": len(hashes)}


def phase(root: Path, name: str) -> dict:
    assert (root / "fixture-marker.txt").read_text() == MARKER
    sys.path.insert(0, str(REPOSITORY))
    blocked = prohibit_real_http()
    from fastapi.testclient import TestClient
    from app import production_entry, production_survival

    headers = {"Origin": OWNER_ORIGIN}
    receipt_path = root / "fixture-record.json"
    checks: dict = {}
    with TestClient(production_entry.app, base_url=OWNER_ORIGIN, client=("127.0.0.1", 43001)) as client:
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/control").status_code == 200
        assert client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 403
        assert client.get("/api/compute-queue/jobs").status_code == 401
        checks["real_asgi_lifespan_and_health"] = "PASS"
        checks["host_and_protected_api_denial"] = "PASS"
        if name == "seed":
            body = {"objective": "Hash supplied text", "context": FIXTURE_TEXT.decode(), "capability": "responsibility.a02", "deterministic_operation": "sha256"}
            assert client.post("/control/api/objectives", json=body).status_code == 403
            assert client.post("/control/api/objectives", json=body, headers={"Origin": "https://untrusted.invalid"}).status_code == 403
            response = client.post("/control/api/objectives", json=body, headers=headers)
            assert response.status_code == 202
            task_id = response.json()["id"]
            task = client.get("/control/api/objectives/" + task_id).json()
            assert task["state"] == "COMPLETED"
            artifact = task["steps"][0]["dispatch"]["artifact"]["artifact_id"]
            content = client.get("/control/api/artifacts/" + artifact)
            assert content.status_code == 200 and hashlib.sha256(FIXTURE_TEXT).hexdigest() in content.text
            assert client.get("/control/api/jobs").json() == {"jobs": []}
            production_survival.runtime().observe(network=False, provider=False)
            queued = client.post("/control/api/survival/queue", headers=headers, json={"objective_id": "task-fixture", "operation_type": "github.push", "payload_ref": "fixture://never-executed", "idempotency_key": "sovereign-fixture-offline-20261021", "authorization_ref": "fixture:owner", "payload": {"fixture": True}})
            assert queued.status_code == 202 and queued.json()["state"] == "DEFERRED_OFFLINE"
            saved = client.post("/control/api/survival/memory", headers=headers, json={"memory_class": "semantic", "key": "standalone", "value": {"test": "isolated"}})
            assert saved.status_code == 201
            receipt_path.write_text(json.dumps({"task_id": task_id, "artifact_id": artifact, "artifact_sha256": hashlib.sha256(content.content).hexdigest(), "deferred_id": queued.json()["id"]}), encoding="utf-8")
            checks.update({"deterministic_objective_to_real_artifact": "PASS", "same_origin_mutation_denial": "PASS", "offline_deferred_queue": "PASS", "local_memory_write": "PASS", "pwa": check_pwa()})
        else:
            saved = json.loads(receipt_path.read_text(encoding="utf-8"))
            task = client.get("/control/api/objectives/" + saved["task_id"])
            assert task.status_code == 200 and task.json()["state"] == "COMPLETED"
            content = client.get("/control/api/artifacts/" + saved["artifact_id"])
            assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == saved["artifact_sha256"]
            queued = client.get("/control/api/survival/queue").json()["operations"]
            assert len(queued) == 1 and queued[0]["id"] == saved["deferred_id"] and queued[0]["state"] == "DEFERRED_OFFLINE"
            assert client.get("/control/api/survival/memory/semantic/standalone").status_code == 200
            with sqlite3.connect(root / "data" / "pwa-sessions.db") as db:
                assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
            checks["new_process_task_artifact_memory_queue_session_persistence"] = "PASS"
    assert not blocked, "Unexpected outbound HTTP attempt in the task fixture"
    return {"phase": name, "checks": checks, "outbound_http_attempts": len(blocked), "production_data_touched": False}


def run(root: Path) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)  # Never reuse or erase an existing data directory.
    (root / "fixture-marker.txt").write_text(MARKER)
    (root / "empty-provider-catalog.json").write_text('{"models":[]}', encoding="utf-8")
    phases = []
    for name in ("seed", "reopen"):
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--root", str(root), "--phase", name], cwd=REPOSITORY, env=child_environment(root), text=True, encoding="utf-8", capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f"Isolated {name} phase failed:\n{result.stderr}")
        phases.append(json.loads(result.stdout))
    sys.path.insert(0, str(REPOSITORY))
    from scripts.sqlite_backup import integrity_report, restore_test, run_backup

    backups = run_backup(root / "data", root / "backups")
    restores = []
    for item in backups["databases"]:
        original = integrity_report(item["source"])
        restored = restore_test(item["backup"], original["row_counts"])
        assert restored["status"] == "PASS" and restored["row_counts_match"]
        assert original["foreign_key_violations"] == restored["foreign_key_violations"] == 0
        restores.append({"database": Path(item["source"]).name, "sha256": item["sha256"], "integrity": "ok", "row_counts_match": True})
    assert restores
    report = {"result": "PASS", "fixture_root": str(root), "phases": phases, "sqlite_backup_restore": restores, "limitations": ["In-process ASGI transport, not real TLS or physical phone acceptance", "No generative inference, 21-role qualification or production deployment", "Local SQLite scratch restore, not encrypted off-device recovery", "Real HTTP transports blocked; host networking unchanged"], "production_data_touched": False}
    (root / "isolation-receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def test_fresh_process_standalone_and_recovery(tmp_path):
    report = run(tmp_path / "sovereign-data")
    assert report["result"] == "PASS"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase", choices=("seed", "reopen"))
    args = parser.parse_args()
    result = phase(args.root, args.phase) if args.phase else run(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
