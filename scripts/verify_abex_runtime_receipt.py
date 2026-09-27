#!/usr/bin/env python3
"""Fail-closed verifier for an ABEX-observed, pre-independent runtime receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PWA_ASSETS = ("index.html", "app.mjs", "sw.js", "release.mjs", "recovery.js")


def git_bytes(root: Path, revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=root, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def digest_matches(raw: bytes, expected: Any) -> bool:
    """Accept checkout EOL policy without accepting any semantic byte drift."""
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return isinstance(expected, str) and any(
        hashlib.sha256(value).hexdigest() == expected for value in (raw, lf, crlf)
    )


def validate(receipt: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(receipt.get("schema_version") == "abex.runtime-observation.v1", "schema_invalid")
    require(receipt.get("receipt_state") == "ABEX_OBSERVED_PENDING_INDEPENDENT_DELL_VERIFICATION", "state_invalid")
    require(receipt.get("independent_verification") is False, "abex_receipt_cannot_self_verify")
    runtime = receipt.get("runtime", {})
    source = runtime.get("source_sha", "")
    require(bool(SHA40.fullmatch(source)), "source_sha_invalid")
    require(runtime.get("remote_sha") == source, "remote_source_mismatch")
    require(runtime.get("host_id") == "ABEX", "runtime_host_invalid")
    require(runtime.get("image_tag") == f"prime:sha-{source[:7]}", "image_tag_source_mismatch")
    require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", str(runtime.get("image_id", "")))), "image_id_invalid")
    for service in ("prime", "interface", "ollama"):
        value = runtime.get(service, {})
        require(value.get("health") == "healthy", f"{service}_not_healthy")
        require(value.get("restart_count") == 0, f"{service}_restart_nonzero")
        require(value.get("oom_killed") is False, f"{service}_oom_state_invalid")

    components = receipt.get("canonical_components", {})
    require(components.get("registry_schema") == "2.0", "registry_schema_invalid")
    require(components.get("logical_agent_count") == 21, "agent_count_invalid")
    require(bool(SHA256.fullmatch(str(components.get("registry_sha256", "")))), "registry_digest_invalid")
    require(bool(SHA256.fullmatch(str(components.get("product_manifest_sha256", "")))), "product_digest_invalid")
    if SHA40.fullmatch(source):
        try:
            registry = git_bytes(root, source, "config/agent_registry.json")
            product = git_bytes(root, source, "system.manifest.json")
            registry_value = json.loads(registry)
            require(digest_matches(registry, components.get("registry_sha256")), "registry_source_digest_mismatch")
            require(digest_matches(product, components.get("product_manifest_sha256")), "product_source_digest_mismatch")
            require(registry_value.get("schema_version") == "2.0" and len(registry_value.get("agents", [])) == 21, "registry_source_identity_mismatch")
            for name in PWA_ASSETS:
                expected = receipt.get("pwa", {}).get("assets", {}).get(name)
                require(digest_matches(git_bytes(root, source, f"clients/pwa/{name}"), expected), f"pwa_source_digest_mismatch:{name}")
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            errors.append("source_evidence_unavailable")

    task = receipt.get("task_evidence", {})
    require(task.get("task_id") == receipt.get("physical_owner_acceptance", {}).get("task_id"), "physical_task_binding_mismatch")
    require(task.get("state") == "COMPLETED", "task_state_invalid")
    require(task.get("model_content_authoritative") is False, "model_content_authority_invalid")
    require(task.get("model_system_contradictions") == [], "model_system_contradiction_present")
    require(bool(SHA256.fullmatch(str(task.get("artifact_sha256", "")))), "artifact_digest_invalid")
    try:
        times = [datetime.fromisoformat(str(task[name]).replace("Z", "+00:00")) for name in ("created_at", "started_at", "completed_at", "updated_at")]
        require(times == sorted(times) and times[2] == times[3], "task_lifecycle_order_invalid")
    except (TypeError, ValueError):
        errors.append("task_lifecycle_timestamp_invalid")

    physical = receipt.get("physical_owner_acceptance", {})
    require(physical.get("evidence_authority") == "OWNER_PHYSICAL_ATTESTATION", "physical_authority_invalid")
    require(physical.get("task_open_from_recent_work") == "PASS", "physical_task_open_not_passed")
    require(physical.get("authoritative_metadata_separate_from_model_content") is True, "physical_metadata_separation_unverified")
    require(physical.get("chinese_result_visible") is True, "physical_result_unverified")
    require(physical.get("application_warning_or_error_banner") is False, "physical_application_warning_present")

    iphone = receipt.get("physical_owner_iphone_acceptance", {})
    require(iphone.get("evidence_authority") == "OWNER_PHYSICAL_ATTESTATION_PLUS_SERVER_CORRELATION", "iphone_evidence_authority_invalid")
    require(iphone.get("owner_account_id") == "owner:lam:prime-epoch-20260919", "iphone_owner_identity_invalid")
    require(iphone.get("role") == "OWNER", "iphone_role_invalid")
    require(iphone.get("session_persisted_after_reopen") is True, "iphone_session_persistence_unverified")
    require(iphone.get("owner_authority_endpoint") == "HTTP_200", "iphone_owner_authority_unverified")
    require(iphone.get("state") == "COMPLETED", "iphone_task_not_completed")
    require(iphone.get("result_language") == "zh-CN", "iphone_result_language_invalid")
    require(iphone.get("jarvis_identity_visible") is True, "iphone_jarvis_identity_unverified")
    require(iphone.get("duplicate_owner_identity_created") is False, "iphone_duplicate_owner_identity")

    acceptance = receipt.get("acceptance", {})
    require(acceptance.get("dell_independent_runtime_verification") == "PENDING", "independent_state_invalid")
    require(acceptance.get("prime_state_transition_authorized") is False, "prime_state_transition_must_be_denied")
    require(acceptance.get("prime_runtime_acceptance") == "UNVERIFIED", "runtime_acceptance_must_remain_unverified")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    raw = args.receipt.read_bytes()
    receipt = json.loads(raw)
    errors = validate(receipt)
    print(json.dumps({
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "verdict": "ABEX_OBSERVATION_VALID_PENDING_INDEPENDENT_VERIFICATION" if not errors else "REJECT",
        "violations": errors,
    }, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
