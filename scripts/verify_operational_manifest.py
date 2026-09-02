#!/usr/bin/env python3
"""Fail closed when PRIME's operational single source of truth is ambiguous."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "governance" / "operational-manifest.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID = re.compile(r"^dpl_[A-Za-z0-9]+$")
EXPECTED_SCHEMA_VERSION = "3.2.0"
EXPECTED_ACTIVE = {"control", "authority", "game", "portal", "prime"}
EXPECTED_PROJECTS = {
    "authority": "prj_bpSxvAZetd54FAZlL9N7VkKttdJk",
    "game": "prj_qChRa1e7NSvFYbaovNgHk8NxxKpn",
    "portal": "prj_ygtCDVg4RyuHE4caN9t6nhFC8Xui",
}


def verify(value: dict) -> None:
    assert value["schema_version"] == EXPECTED_SCHEMA_VERSION
    assert value["status"] == "CURRENT"
    canonical = value["canonical_machine_source"]
    assert canonical == {
        "repository": "AndrewLamSingapore/PRIME", "branch": "main",
        "path": "governance/operational-manifest.json",
    }
    active = value["scope"]["active_systems"]
    assert len(active) == len(set(active)) and set(active) == EXPECTED_ACTIVE
    excluded = value["scope"]["excluded_systems"]
    assert len(excluded) == 1
    assert excluded[0]["id"] == "velyqua" and excluded[0]["state"] == "PARKED"
    assert excluded[0]["resume_phrase"] == "resume VELYQUA"
    alignment = value["alignment_state"]
    assert alignment["source_and_deployments"] == "ALIGNED"
    assert alignment["portfolio_relay"] in {"ALIGNED", "CONFIGURATION_REQUIRED"}
    assert alignment["authority_evidence_review"] in {"ALIGNED", "CONFIGURATION_REQUIRED"}
    assert alignment["dell_runtime"] in {"ALIGNED", "OPERATOR_UPDATE_REQUIRED", "VERIFICATION_REQUIRED"}
    assert value["shared_contract"]["version"] == "2.0.0"
    assert SHA.fullmatch(value["shared_contract"]["source_sha"])
    systems = value["systems"]
    assert set(systems) == EXPECTED_ACTIVE
    for system_id in ("control", "authority", "game", "portal"):
        assert SHA.fullmatch(systems[system_id]["source_sha"])
    project_ids = []
    for system_id, project_id in EXPECTED_PROJECTS.items():
        assert systems[system_id]["vercel_project_id"] == project_id
        assert DEPLOYMENT_ID.fullmatch(systems[system_id]["production_deployment_id"])
        assert systems[system_id]["production_state"] == "READY"
        assert systems[system_id]["health_url"].startswith("https://")
        assert systems[system_id]["health_url"].endswith("/api/health")
        assert systems[system_id]["health_revision_verified"] == systems[system_id]["source_sha"]
        project_ids.append(project_id)
    assert len(project_ids) == len(set(project_ids))
    assert systems["prime"]["repository"] == "AndrewLamSingapore/PRIME"
    assert systems["prime"]["source_ref"] == "main"
    assert SHA.fullmatch(systems["prime"]["last_green_source_sha"])
    assert systems["prime"]["published_image"].endswith(
        f":sha-{systems['prime']['last_green_source_sha'][:7]}"
    )
    assert value["human_resume_mirror"]["library_file_id"] == "libfile_79bbf3a6138c8191a69bce305ea6094b"
    assert value["event_alignment"]["inbound_dell_exposure_required"] is False
    assert value["event_alignment"]["contract"] == "portfolio-event-v1"
    configuration = value["configuration_required"]
    relay = configuration["portfolio_relay"]
    assert relay["status"] in {"ALIGNED", "CONFIGURATION_REQUIRED"}
    assert relay["shared_secret_stored"] is False or relay["status"] == "ALIGNED"
    review = configuration["authority_evidence_review"]
    assert review["publication_mode"] == "explicit_draft_only"
    dell = value["dell_runtime"]
    assert SHA.fullmatch(dell["last_verified_source_sha"])
    assert dell["status"] in {"aligned", "operator_update_required", "verification_required"}
    assert dell["target_image"] == systems["prime"]["published_image"]
    hygiene = value["github_hygiene"]
    assert hygiene["last_branch_audit_utc"].endswith("Z")
    audit = hygiene["last_branch_audit"]
    assert audit["content_redundant_branch_candidates"] >= 0
    assert audit["unique_non_main_branches"] >= 0
    assert hygiene["redundant_branch_state"] == "retained_pending_confirmed_deletion"
    assert value["release_gate"]["secret_values_allowed"] is False
    assert value["supersession"]["duplicate_current_checkpoints_allowed"] is False


if __name__ == "__main__":
    verify(json.loads(PATH.read_text(encoding="utf-8")))
    print("Operational manifest: PASS")
