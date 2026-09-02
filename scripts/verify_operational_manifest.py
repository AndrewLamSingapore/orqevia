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
    assert value["canonical_machine_source"] == {
        "repository": "AndrewLamSingapore/PRIME",
        "branch": "main",
        "path": "governance/operational-manifest.json",
    }

    active = value["scope"]["active_systems"]
    assert len(active) == len(set(active)) and set(active) == EXPECTED_ACTIVE
    excluded = value["scope"]["excluded_systems"]
    assert len(excluded) == 1
    assert excluded[0]["id"] == "velyqua" and excluded[0]["state"] == "PARKED"
    assert excluded[0]["resume_phrase"] == "resume VELYQUA"

    alignment = value["alignment_state"]
    required_alignment = {
        "source_and_deployments",
        "portfolio_relay",
        "dell_runtime",
        "compute_hardening",
        "queue_hardening",
        "sanitized_observability",
    }
    assert all(alignment[key] == "ALIGNED_VERIFIED" for key in required_alignment)
    assert alignment["authority_evidence_review"] == "READY_DRAFT_ONLY"

    shared = value["shared_contract"]
    assert shared["version"] == "2.0.0"
    assert SHA.fullmatch(shared["source_sha"])

    systems = value["systems"]
    assert set(systems) == EXPECTED_ACTIVE
    for system_id in ("control", "authority", "game", "portal"):
        assert SHA.fullmatch(systems[system_id]["source_sha"])
    project_ids = []
    for system_id, project_id in EXPECTED_PROJECTS.items():
        system = systems[system_id]
        assert system["vercel_project_id"] == project_id
        assert DEPLOYMENT_ID.fullmatch(system["production_deployment_id"])
        assert system["production_state"] == "READY"
        assert system["health_url"].startswith("https://")
        assert system["health_url"].endswith("/api/health")
        assert system["health_revision_verified"] == system["source_sha"]
        project_ids.append(project_id)
    assert len(project_ids) == len(set(project_ids))

    prime = systems["prime"]
    assert prime["repository"] == "AndrewLamSingapore/PRIME"
    assert prime["source_ref"] == "main"
    assert SHA.fullmatch(prime["last_green_source_sha"])
    assert prime["published_image"].endswith(f":sha-{prime['last_green_source_sha'][:7]}")
    assert prime["runtime_promotion"] == "complete_verified"

    assert value["human_resume_mirror"]["library_file_id"] == "libfile_79bbf3a6138c8191a69bce305ea6094b"
    assert value["event_alignment"]["inbound_dell_exposure_required"] is False
    assert value["event_alignment"]["contract"] == "portfolio-event-v1"

    configuration = value["configuration_required"]
    relay = configuration["portfolio_relay"]
    assert relay["status"] == "ALIGNED_VERIFIED"
    assert relay["shared_secret_stored"] is True
    review = configuration["authority_evidence_review"]
    assert review["status"] == "READY_DRAFT_ONLY"
    assert review["publication_mode"] == "explicit_draft_only"

    dell = value["dell_runtime"]
    assert SHA.fullmatch(dell["source_sha"])
    assert dell["source_sha"] == prime["last_green_source_sha"]
    assert dell["status"] == "healthy_aligned"
    assert dell["verified_image"] == prime["published_image"]
    acceptance = dell["runtime_acceptance"]
    assert acceptance["container_healthy"] is True
    assert acceptance["health_http_status"] == 200
    assert acceptance["integrity"] == "ok"
    assert acceptance["models_ready"] is True
    assert acceptance["gpu_processor_observed"] == "100% GPU"

    hygiene = value["github_hygiene"]
    assert hygiene["last_branch_audit_utc"].endswith("Z")
    assert hygiene["redundant_branches_deleted"] >= 0
    assert hygiene["unique_non_main_branches_preserved"] >= 0
    assert hygiene["redundant_branch_state"] == "deleted_verified"
    assert value["release_gate"]["secret_values_allowed"] is False
    assert value["supersession"]["duplicate_current_checkpoints_allowed"] is False


if __name__ == "__main__":
    verify(json.loads(PATH.read_text(encoding="utf-8")))
    print("Operational manifest: PASS")
