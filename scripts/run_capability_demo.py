"""Exercise the live model registry, debate judge and shared notebook APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8000"
TOKEN = os.environ["ORQEVIA_SPINE_TOKEN"].strip()
ADMIN = hmac.new(
    TOKEN.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256
).hexdigest()
OUTPUT = Path("/data/capability-demo-20261020.json")


def request(method: str, path: str, body: dict | None = None, *, role: str = "OWNER", actor: str = "owner"):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
        "Origin": BASE,
    }
    if role == "OWNER":
        headers.update(
            {
                "X-ORQEVIA-Actor": actor,
                "X-ORQEVIA-Role": "OWNER",
                "X-ORQEVIA-Notebook-Admin": ADMIN,
            }
        )
    else:
        headers.update({"X-ORQEVIA-Actor": actor, "X-ORQEVIA-Role": "AGENT"})
    data = None if body is None else json.dumps(body).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        return response.status, json.loads(raw)


def main() -> int:
    artifact = hashlib.sha256(b"capability-demo-model").hexdigest()
    results = {}
    _, registered = request(
        "POST",
        "/api/model-registry/models",
        {
            "model_id": "pilot.deep",
            "version": "1.0.0",
            "provider": "ollama",
            "model_name": "qwen2.5:14b-instruct-q4_K_M",
            "location": "local",
            "context_tokens": 8192,
            "output_tokens": 2048,
            "capabilities": ["text_generation"],
            "artifact_sha256": artifact,
            "source_url": "https://example.invalid/pilot.deep",
            "metadata": {"purpose": "capability demo"},
        },
    )
    results["registered"] = registered
    _, evaluated = request(
        "POST",
        "/api/model-registry/models/pilot.deep/1.0.0/evaluate",
        {
            "status": "PASS",
            "evidence_ref": "demo://model-evaluation",
            "checks": [{"name": "contract", "status": "PASS"}],
        },
    )
    results["evaluated"] = evaluated
    _, approved = request(
        "POST",
        "/api/model-registry/models/pilot.deep/1.0.0/approve",
        {
            "reason": "demo review complete",
            "compatibility": {
                "compatible": True,
                "evidence_ref": "demo://compatibility",
                "context_tokens": 8192,
                "output_tokens": 2048,
            },
        },
    )
    results["approved"] = approved
    _, activated = request(
        "POST",
        "/api/model-registry/models/pilot.deep/1.0.0/activate",
        {"reason": "demo activation"},
    )
    results["activated"] = activated
    _, assigned = request(
        "POST",
        "/api/model-registry/assignments/a02",
        {"model_id": "pilot.deep", "version": "1.0.0"},
    )
    results["assigned"] = assigned

    _, resolved = request(
        "POST",
        "/api/debates",
        {
            "question": "Which option should the project choose?",
            "judge_agent": "a26",
            "positions": [
                {
                    "agent_id": "a01",
                    "proposition": "Choose option A",
                    "evidence_refs": ["demo://evidence-a"],
                    "confidence": 0.8,
                },
                {
                    "agent_id": "a02",
                    "proposition": "Choose option A",
                    "evidence_refs": ["demo://evidence-b"],
                    "confidence": 0.7,
                },
                {
                    "agent_id": "a04",
                    "proposition": "Choose option B",
                    "evidence_refs": ["demo://evidence-c"],
                    "confidence": 0.6,
                },
            ],
        },
    )
    results["debate_resolved"] = resolved
    _, escalated = request(
        "POST",
        "/api/debates",
        {
            "question": "Is the disputed release safe?",
            "judge_agent": "a26",
            "positions": [
                {
                    "agent_id": "a01",
                    "proposition": "Yes",
                    "evidence_refs": ["demo://yes"],
                },
                {
                    "agent_id": "a02",
                    "proposition": "No",
                    "evidence_refs": ["demo://no"],
                },
            ],
        },
    )
    results["debate_escalated"] = escalated

    project_id = "CAPABILITY-PROJECT-20261020"
    _, project = request(
        "POST",
        "/api/agent-notebooks/projects",
        {"project_id": project_id, "name": "Capability demonstration project"},
    )
    results["project"] = project
    for agent, permission in (("a02", "write"), ("a04", "read")):
        _, member = request(
            "POST",
            f"/api/agent-notebooks/projects/{project_id}/members",
            {"agent_id": agent, "permission": permission},
        )
        results[f"member_{agent}"] = member
    _, project_record = request(
        "POST",
        "/api/agent-notebooks/a02/records",
        {
            "section": "lessons_learned",
            "content": {"lesson": "Project membership grants bounded shared evidence access."},
            "source": "capability-demo",
            "scope": "project",
            "project_id": project_id,
            "verification_status": "verified_execution",
        },
    )
    results["project_record"] = project_record
    _, agent_read = request(
        "GET",
        f"/api/agent-notebooks/a02/records/{project_record['memory_id']}",
        role="AGENT",
        actor="a04",
    )
    results["agent_read"] = agent_read
    _, organization_record = request(
        "POST",
        "/api/agent-notebooks/a02/records",
        {
            "section": "lessons_learned",
            "content": {"lesson": "Approved organization knowledge is visible to eligible agents."},
            "source": "capability-demo-owner",
            "scope": "organization",
            "verification_status": "verified_execution",
        },
    )
    results["organization_record"] = organization_record
    OUTPUT.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "model": results["activated"].get("state"),
                "debate": results["debate_resolved"].get("decision"),
                "escalation": results["debate_escalated"].get("decision"),
                "project_record": results["project_record"].get("scope"),
                "organization_record": results["organization_record"].get("scope"),
                "output": str(OUTPUT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
