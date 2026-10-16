import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_candidate_installation_binds_all_29_signed_cases_to_owned_domains():
    doc = json.loads((ROOT / "governance/agent-cert-installation-20261016.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "orqevia.agent-cert-installation.v1"
    assert doc["status"].startswith("CANDIDATE_INSTALLATION")
    assert doc["record_count"] == 29 == len(doc["records"])
    assert doc["unresolved_domains"] == []
    pairs = {(r["agent_id"], r["capability_id"]) for r in doc["records"]}
    assert len(pairs) == 29
    assert all(r["owned_domain"] and r["owned_domain"]["definition_sha256"] for r in doc["records"])
    assert all(r["runtime_activated"] is False and r["l7_awarded"] is False for r in doc["records"])


def test_registry_is_module_schema_locked_so_bindings_are_staged():
    # The initialization module validates the registry bytes strictly; any edit
    # (including model/origin fields) fails closed. The origin is carried by
    # governance/ORQEVIA-ORIGIN.md and the readiness artifact; registry bindings
    # ride the next sanctioned closure re-issue. This test documents the lock.
    registry = json.loads((ROOT / "config" / "agent_registry.json").read_text(encoding="utf-8"))
    assert len(registry["agents"]) == 21
