"""Certify the live notebook API for every registered agent."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from app.agent_registry import load_agent_registry

BASE = os.getenv("ORQEVIA_LOCAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = (os.getenv("ORQEVIA_SPINE_TOKEN") or os.getenv("PRIME_SPINE_TOKEN") or "").strip()


def hashlib_hmac() -> str:
    import hmac

    return hmac.new(TOKEN.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256).hexdigest()


ADMIN = os.getenv("ORQEVIA_NOTEBOOK_ADMIN_TOKEN", "").strip() or hashlib_hmac()
OUT = Path(os.getenv("ORQEVIA_NOTEBOOK_CERT_OUT", "/data/notebook-certification"))


def request(path: str, *, method: str = "GET", body: dict | None = None, actor: str = "owner", role: str = "OWNER"):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
        "X-ORQEVIA-Actor": actor,
        "X-ORQEVIA-Role": role,
    }
    if role == "OWNER":
        headers["X-ORQEVIA-Notebook-Admin"] = ADMIN
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = BASE
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = load_agent_registry()
    agents = [item["agent_id"] for item in registry["agents"]]
    results = []
    for agent_id in agents:
        marker = f"ORQNBTEST-{agent_id}-{uuid.uuid4().hex}"
        content = {
            "text": f"{marker}: supplier account reconciliation evidence is verified for {agent_id}.",
            "marker": marker,
            "agent_id": agent_id,
        }
        status, created = request(
            f"/api/agent-notebooks/{agent_id}/records",
            method="POST",
            actor=agent_id,
            role="AGENT",
            body={
                "section": "lessons_learned",
                "record_type": "reflection",
                "content": content,
                "source": "live-notebook-certification",
                "evidence_refs": ["ORQ-002 notebook certification"],
                "confidence": 0.95,
                "verification_status": "verified_execution",
                "idempotency_key": f"cert-{agent_id}-{uuid.uuid4().hex}",
            },
        )
        checks = {"create": status == 201}
        if status == 201:
            memory_id = created["memory_id"]
            status_read, read = request(
                f"/api/agent-notebooks/{agent_id}/records/{memory_id}",
                actor=agent_id,
                role="AGENT",
            )
            checks["read"] = status_read == 200 and read.get("memory_id") == memory_id
            other = next(item for item in agents if item != agent_id)
            status_denied, _ = request(
                f"/api/agent-notebooks/{agent_id}/records/{memory_id}",
                actor=other,
                role="AGENT",
            )
            checks["isolation"] = status_denied == 403
            status_keyword, keyword = request(
                "/api/agent-notebooks/search",
                method="POST",
                actor=agent_id,
                role="AGENT",
                body={"query": marker, "agent_id": agent_id, "limit": 5},
            )
            checks["keyword_search"] = status_keyword == 200 and any(
                item["memory_id"] == memory_id for item in keyword.get("results", [])
            )
            status_semantic, semantic = request(
                "/api/agent-notebooks/search",
                method="POST",
                actor=agent_id,
                role="AGENT",
                body={"query": "vendor account reconciliation evidence", "agent_id": agent_id, "limit": 5},
            )
            checks["semantic_search"] = (
                status_semantic == 200
                and semantic.get("retrieval", {}).get("mode") == "hybrid"
                and any(
                    item["memory_id"] == memory_id and item.get("semantic_score", 0) > 0
                    for item in semantic.get("results", [])
                )
            )
            status_update, updated = request(
                f"/api/agent-notebooks/{agent_id}/records/{memory_id}",
                method="PATCH",
                actor=agent_id,
                role="AGENT",
                body={
                    "content": {**content, "corrected": True},
                    "source": "live-notebook-certification",
                    "expected_version": created["version"],
                    "change_reason": "certification version check",
                    "confidence": 0.96,
                    "verification_status": "verified_execution",
                },
            )
            checks["update"] = status_update == 200 and updated.get("version") == created["version"] + 1
            status_history, history = request(
                f"/api/agent-notebooks/{agent_id}/records/{memory_id}/history",
                actor=agent_id,
                role="AGENT",
            )
            checks["version_history"] = status_history == 200 and len(history.get("versions", [])) >= 2
            record = {
                "agent_id": agent_id,
                "marker": marker,
                "memory_id": memory_id,
                "version": updated.get("version") if checks["update"] else created["version"],
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL",
            }
        else:
            record = {
                "agent_id": agent_id,
                "marker": marker,
                "memory_id": None,
                "version": None,
                "checks": checks,
                "status": "FAIL",
                "create_response": created,
            }
        results.append(record)
        print(json.dumps({"agent_id": agent_id, "status": record["status"]}, sort_keys=True), flush=True)

    status_health, health = request("/api/agent-notebooks/health")
    report = {
        "schema_version": "orqevia.agent-notebook-live-certification.v1",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "agents_discovered": len(agents),
        "agents_passed": sum(1 for item in results if item["status"] == "PASS"),
        "checks": ["create", "read", "isolation", "keyword_search", "semantic_search", "update", "version_history"],
        "results": results,
        "health_http_status": status_health,
        "health": health,
    }
    path = OUT / "notebook-certification.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "agents_passed": report["agents_passed"]}, sort_keys=True))
    if report["agents_passed"] != 21:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
