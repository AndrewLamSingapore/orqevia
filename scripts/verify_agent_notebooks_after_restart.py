"""Verify live notebook records and backup integrity after a process restart."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from app.agent_notebooks import AgentNotebookStore

BASE = os.getenv("ORQEVIA_LOCAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = (os.getenv("ORQEVIA_SPINE_TOKEN") or os.getenv("PRIME_SPINE_TOKEN") or "").strip()
ADMIN = os.getenv("ORQEVIA_NOTEBOOK_ADMIN_TOKEN", "").strip() or hmac.new(
    TOKEN.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256
).hexdigest()
OUT = Path(os.getenv("ORQEVIA_NOTEBOOK_CERT_OUT", "/data/notebook-certification"))


def request(path: str):
    req = urllib.request.Request(
        BASE + path,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "X-ORQEVIA-Actor": "owner",
            "X-ORQEVIA-Role": "OWNER",
            "X-ORQEVIA-Notebook-Admin": ADMIN,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    path = OUT / "notebook-certification.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    passed = 0
    for item in report["results"]:
        try:
            record = request(
                f"/api/agent-notebooks/{item['agent_id']}/records/{item['memory_id']}"
            )
            ok = item["marker"] in json.dumps(record.get("content", {}), sort_keys=True)
        except Exception:
            ok = False
        item["restart_read"] = ok
        if ok:
            passed += 1

    backup_dir = OUT / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "orqevia-memory-restart-check.db"
    if backup.exists():
        backup.unlink()
    store = AgentNotebookStore(os.getenv("ORQEVIA_MEMORY_DB", "/data/orqevia-memory.db"))
    manifest = store.backup(backup)
    restored = sqlite3.connect(backup)
    try:
        integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
        notebooks = restored.execute("SELECT COUNT(*) FROM agent_notebooks").fetchone()[0]
        records = restored.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0]
    finally:
        restored.close()
    report["restart"] = {
        "x_agents_retrieved": f"{passed}/{report['agents_discovered']}",
        "backup_manifest": manifest,
        "restored_integrity": integrity,
        "restored_notebooks": notebooks,
        "restored_records": records,
        "status": "PASS" if passed == 21 and integrity == "ok" and notebooks == 21 else "FAIL",
    }
    report["status"] = (
        "PASS"
        if report["agents_passed"] == 21 and report["restart"]["status"] == "PASS"
        else "FAIL"
    )
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "restart": report["restart"]}, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
