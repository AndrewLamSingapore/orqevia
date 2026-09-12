#!/usr/bin/env python3
"""Validate PRIME's operational SSOT and, optionally, its live boundaries."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "governance" / "operational-manifest.json"
DEFAULT_BRANCH_INVENTORY = ROOT / "governance" / "branch-inventory.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID = re.compile(r"^dpl_[A-Za-z0-9]+$")
EXPECTED_SCHEMA_VERSION = "4.2.0"
EXPECTED_ACTIVE = {"control", "authority", "game", "portal", "prime", "sky", "velyqua"}
EXPECTED_CONTRACT_SHA = "a05fa2e3df80733af9ed87068b3526768d4a8394"
EXPECTED_PROJECTS = {
    "velyqua": "prj_SixsxN06HC8wtBVwGpF4eukIXfY2",
    "authority": "prj_bpSxvAZetd54FAZlL9N7VkKttdJk",
    "game": "prj_qChRa1e7NSvFYbaovNgHk8NxxKpn",
    "portal": "prj_ygtCDVg4RyuHE4caN9t6nhFC8Xui",
}
EXPECTED_STATIC_PROJECTS = {
    "sky": "prj_MniyVhjPHLiwQufvuqIjeYErQmEP",
}


@dataclass
class Assessment:
    errors: list[str] = field(default_factory=list)
    stale_reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def stale(self, message: str) -> None:
        if message not in self.stale_reasons:
            self.stale_reasons.append(message)


def parse_utc(value: Any, label: str, assessment: Assessment) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        assessment.error(f"{label} must be an RFC3339 UTC timestamp ending in Z")
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        assessment.error(f"{label} is not a valid timestamp")
        return None
    return parsed.astimezone(timezone.utc)


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def assess_branch_inventory(value: dict[str, Any], assessment: Assessment) -> None:
    if value.get("schema_version") != "1.0.0":
        assessment.error("branch inventory schema_version must be 1.0.0")
    branches = value.get("branches")
    if not isinstance(branches, list):
        assessment.error("branch inventory branches must be a list")
        return
    if len(branches) != 112 or value.get("total_non_main_branches") != 112:
        assessment.error("branch inventory must classify the 112-branch baseline exactly")
    allowed = {"active", "merged", "rollback", "checkpoint"}
    identities: set[tuple[str, str]] = set()
    counts = {name: 0 for name in sorted(allowed)}
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            assessment.error(f"branch inventory entry {index} must be an object")
            continue
        identity = (str(branch.get("repository", "")), str(branch.get("branch", "")))
        if not all(identity) or identity[1] == "main" or identity in identities:
            assessment.error(f"branch inventory entry {index} has an invalid or duplicate identity")
        identities.add(identity)
        classification = branch.get("classification")
        if classification not in allowed:
            assessment.error(f"branch inventory entry {index} has invalid classification")
        else:
            counts[classification] += 1
    if value.get("classification_counts") != counts:
        assessment.error("branch inventory classification_counts do not match its entries")


def assess_static(
    value: dict[str, Any],
    inventory: dict[str, Any],
    *,
    now: datetime,
) -> Assessment:
    result = Assessment()
    if value.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        result.error(f"schema_version must be {EXPECTED_SCHEMA_VERSION}")
    if value.get("status") not in {"CURRENT", "STALE"}:
        result.error("status must be CURRENT or STALE")
    canonical = value.get("canonical_machine_source")
    if canonical != {
        "repository": "AndrewLamSingapore/prime",
        "branch": "main",
        "path": "governance/operational-manifest.json",
    }:
        result.error("canonical_machine_source is not the PRIME main manifest")

    scope = value.get("scope", {})
    active = scope.get("active_systems", [])
    if not isinstance(active, list) or set(active) != EXPECTED_ACTIVE or len(active) != len(set(active)):
        result.error("active system scope must contain the seven unique software systems")
    if scope.get("excluded_systems") != []:
        result.error("resumed software scope must not retain parked exclusions")

    shared = value.get("shared_contract", {})
    if shared.get("version") != "2.0.0":
        result.error("shared contract version must be 2.0.0")
    if shared.get("source_sha") != EXPECTED_CONTRACT_SHA:
        result.error("shared contract source_sha is not the canonical publication commit")
    if shared.get("repository") != "AndrewLamSingapore/AndrewLamSingapore":
        result.error("shared contract repository is invalid")
    if shared.get("path") != "portfolio-contracts/manifest.json":
        result.error("shared contract path is invalid")

    verification = value.get("verification", {})
    stale_after = verification.get("stale_after_hours")
    if stale_after != 24:
        result.error("verification.stale_after_hours must be 24")
        stale_after = 24

    systems = value.get("systems", {})
    if not isinstance(systems, dict) or set(systems) != EXPECTED_ACTIVE:
        result.error("systems must contain exactly the seven active systems")
        systems = systems if isinstance(systems, dict) else {}

    for system_id in sorted(EXPECTED_ACTIVE):
        system = systems.get(system_id, {})
        for fact in ("source_head_sha", "release_sha", "runtime_sha", "verified_at_utc"):
            if fact not in system:
                result.error(f"systems.{system_id}.{fact} is required")
        source_head = system.get("source_head_sha")
        if system_id == "prime":
            if source_head is not None or system.get("source_head_resolution") != "live":
                result.error("PRIME source_head_sha must be live-resolved to avoid self-reference")
        elif not valid_sha(source_head):
            result.error(f"systems.{system_id}.source_head_sha must be a full SHA")
        release_sha = system.get("release_sha")
        runtime_sha = system.get("runtime_sha")
        if not valid_sha(release_sha):
            result.error(f"systems.{system_id}.release_sha must be a full SHA")
        if system_id == "control":
            if runtime_sha is not None:
                result.error("control runtime_sha must be null because no runtime revision endpoint exists")
        elif not valid_sha(runtime_sha):
            result.error(f"systems.{system_id}.runtime_sha must be a full SHA")
        verified = parse_utc(system.get("verified_at_utc"), f"systems.{system_id}.verified_at_utc", result)
        if verified:
            age = now - verified
            if age > timedelta(hours=stale_after):
                result.stale(f"verification_expired:{system_id}")
            if age < timedelta(minutes=-5):
                result.error(f"systems.{system_id}.verified_at_utc is in the future")

    for system_id, project_id in EXPECTED_PROJECTS.items():
        system = systems.get(system_id, {})
        if system.get("vercel_project_id") != project_id:
            result.error(f"systems.{system_id}.vercel_project_id is invalid")
        if not DEPLOYMENT_ID.fullmatch(str(system.get("production_deployment_id", ""))):
            result.error(f"systems.{system_id}.production_deployment_id is invalid")
        if system.get("production_state") != "READY":
            result.stale(f"production_not_ready:{system_id}")
        if not str(system.get("health_url", "")).startswith("https://"):
            result.error(f"systems.{system_id}.health_url is invalid")
        if system.get("release_sha") != system.get("runtime_sha"):
            result.stale(f"release_runtime_drift:{system_id}")
        if system.get("source_head_sha") != system.get("release_sha"):
            result.stale(f"source_release_drift:{system_id}")

    for system_id, project_id in EXPECTED_STATIC_PROJECTS.items():
        system = systems.get(system_id, {})
        if system.get("vercel_project_id") != project_id:
            result.error(f"systems.{system_id}.vercel_project_id is invalid")
        if not DEPLOYMENT_ID.fullmatch(str(system.get("production_deployment_id", ""))):
            result.error(f"systems.{system_id}.production_deployment_id is invalid")
        if system.get("production_state") != "READY":
            result.stale(f"production_not_ready:{system_id}")
        if not str(system.get("runtime_probe_url", "")).startswith("https://"):
            result.error(f"systems.{system_id}.runtime_probe_url is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(system.get("runtime_content_sha256", ""))):
            result.error(f"systems.{system_id}.runtime_content_sha256 is invalid")
        if system.get("source_path") != "index.html":
            result.error(f"systems.{system_id}.source_path is invalid")
        if system.get("release_sha") != system.get("runtime_sha"):
            result.stale(f"release_runtime_drift:{system_id}")
        if system.get("source_head_sha") != system.get("release_sha"):
            result.stale(f"source_release_drift:{system_id}")

    prime = systems.get("prime", {})
    if prime.get("release_sha") != prime.get("runtime_sha"):
        result.stale("release_runtime_drift:prime")
    image = str(prime.get("published_image", ""))
    release_sha = str(prime.get("release_sha", ""))
    if valid_sha(release_sha) and not image.endswith(f":sha-{release_sha[:7]}"):
        result.error("PRIME published image tag does not match release_sha")

    dell = value.get("dell_runtime", {})
    if dell.get("command") != "JARVIS.cmd status":
        result.error("Dell acceptance command must be JARVIS.cmd status")
    if dell.get("runtime_sha") != prime.get("runtime_sha"):
        result.error("Dell runtime_sha must match systems.prime.runtime_sha")
    if dell.get("accepted") is not True:
        result.stale("dell_status_post_update_required")
    if dell.get("post_update_status") is not True:
        result.stale("dell_status_predates_latest_update")
    dell_verified = parse_utc(dell.get("verified_at_utc"), "dell_runtime.verified_at_utc", result)
    if dell_verified and now - dell_verified > timedelta(hours=stale_after):
        result.stale("verification_expired:dell_runtime")

    assess_branch_inventory(inventory, result)
    inventory_ref = value.get("github_hygiene", {}).get("branch_inventory", {})
    if inventory_ref.get("path") != "governance/branch-inventory.json":
        result.error("github_hygiene branch inventory path is invalid")
    if inventory_ref.get("total_non_main_branches") != 112:
        result.error("github_hygiene branch inventory total must be 112")
    if inventory_ref.get("classification_counts") != inventory.get("classification_counts"):
        result.error("manifest branch classification counts differ from the inventory")

    # A saved snapshot cannot pre-list tomorrow's TTL failures. Carry forward
    # live findings and derive effective freshness without classifying age as
    # a schema defect. --allow-stale never permits malformed data.
    recorded = verification.get("stale_reasons", [])
    if not isinstance(recorded, list) or any(not isinstance(x, str) or not x for x in recorded):
        result.error("stale_reasons must be a list of nonempty strings")
    else:
        if value.get("status") == "CURRENT" and recorded:
            result.error("CURRENT snapshot cannot contain recorded stale reasons")
        for reason in recorded:
            result.stale(reason)
    for label, timestamp in [("manifest", verification.get("verified_at_utc")),
                              ("shared_contract", shared.get("verified_at_utc"))]:
        checked = parse_utc(timestamp, label + ".verified_at_utc", result)
        if checked:
            if now - checked > timedelta(hours=24): result.stale("verification_expired:" + label)
            if checked - now > timedelta(minutes=5): result.error(label + " verification is in the future")
    if value.get("status") == "STALE" and not result.stale_reasons:
        result.error("STALE snapshot requires a recorded or computed reason")
    return result


def http_json(url: str, *, token: str | None = None, timeout: int = 15) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "prime-operational-ssot/4.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("response is not a JSON object")
    return value


def http_bytes(url: str, *, token: str | None = None, timeout: int = 15) -> bytes:
    headers = {"Accept": "*/*", "User-Agent": "prime-operational-ssot/4.2"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read()


def assess_live(value: dict[str, Any], result: Assessment) -> None:
    github_token = os.getenv("GITHUB_TOKEN")
    systems = value["systems"]
    github_evidence: dict[str, Any] = {}
    for system_id in sorted(EXPECTED_ACTIVE):
        system = systems[system_id]
        repository = system["repository"]
        try:
            head = http_json(f"https://api.github.com/repos/{repository}/commits/main", token=github_token)
            observed = head.get("sha")
            github_evidence[system_id] = {"source_head_sha": observed}
            if system_id != "prime" and observed != system.get("source_head_sha"):
                result.stale(f"github_head_drift:{system_id}")
            release = http_json(
                f"https://api.github.com/repos/{repository}/commits/{system['release_sha']}",
                token=github_token,
            )
            if release.get("sha") != system["release_sha"]:
                result.stale(f"github_release_missing:{system_id}")
        except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
            result.stale(f"github_live_check_failed:{system_id}:{type(exc).__name__}")

    shared = value["shared_contract"]
    try:
        contract = http_json(
            "https://api.github.com/repos/"
            f"{shared['repository']}/contents/{shared['path']}?ref={shared['source_sha']}",
            token=github_token,
        )
        payload = json.loads(base64.b64decode(contract["content"]).decode("utf-8"))
        if payload.get("contract_version") != shared["version"]:
            result.stale("shared_contract_live_version_mismatch")
    except (KeyError, OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
        result.stale(f"shared_contract_live_check_failed:{type(exc).__name__}")
    result.evidence["github"] = github_evidence

    vercel_evidence: dict[str, Any] = {}
    for system_id in sorted(EXPECTED_PROJECTS):
        system = systems[system_id]
        try:
            health = http_json(system["health_url"])
            observed = health.get("revision")
            vercel_evidence[system_id] = {
                "health_ok": health.get("ok") is True,
                "runtime_sha": observed,
                "deployment_id": system["production_deployment_id"],
            }
            if health.get("ok") is not True:
                result.stale(f"vercel_health_not_ready:{system_id}")
            if observed != system.get("runtime_sha"):
                result.stale(f"vercel_runtime_drift:{system_id}")
        except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
            result.stale(f"vercel_health_check_failed:{system_id}:{type(exc).__name__}")

    for system_id in sorted(EXPECTED_STATIC_PROJECTS):
        system = systems[system_id]
        try:
            source = http_json(
                "https://api.github.com/repos/"
                f"{system['repository']}/contents/{system['source_path']}?ref={system['release_sha']}",
                token=github_token,
            )
            source_bytes = base64.b64decode(source["content"])
            observed_head = github_evidence.get(system_id, {}).get("source_head_sha")
            current_source_hash = None
            if valid_sha(observed_head):
                current_source = http_json(
                    "https://api.github.com/repos/"
                    f"{system['repository']}/contents/{system['source_path']}?ref={observed_head}",
                    token=github_token,
                )
                current_source_hash = hashlib.sha256(
                    base64.b64decode(current_source["content"])
                ).hexdigest()
            runtime_bytes = http_bytes(system["runtime_probe_url"])
            source_hash = hashlib.sha256(source_bytes).hexdigest()
            runtime_hash = hashlib.sha256(runtime_bytes).hexdigest()
            expected_hash = system["runtime_content_sha256"]
            vercel_evidence[system_id] = {
                "source_content_sha256": source_hash,
                "current_source_content_sha256": current_source_hash,
                "runtime_content_sha256": runtime_hash,
                "deployment_id": system["production_deployment_id"],
            }
            if source_hash != expected_hash:
                result.stale(f"github_release_content_drift:{system_id}")
            if runtime_hash != expected_hash:
                result.stale(f"vercel_runtime_content_drift:{system_id}")
        except (KeyError, OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
            result.stale(f"vercel_static_check_failed:{system_id}:{type(exc).__name__}")

    vercel_token = os.getenv("VERCEL_TOKEN")
    if vercel_token:
        team_id = value.get("verification", {}).get("vercel_team_id")
        for system_id in sorted(EXPECTED_PROJECTS | EXPECTED_STATIC_PROJECTS):
            system = systems[system_id]
            try:
                deployment = http_json(
                    "https://api.vercel.com/v13/deployments/"
                    f"{urlsplit(system['health_url']).hostname}?teamId={team_id}",
                    token=vercel_token,
                )
                if deployment.get("id") != system.get("production_deployment_id"):
                    result.stale(f"vercel_production_alias_drift:{system_id}")
                meta = deployment.get("meta", {})
                if deployment.get("readyState", deployment.get("state")) != "READY":
                    result.stale(f"vercel_deployment_not_ready:{system_id}")
                if deployment.get("target") != "production":
                    result.stale(f"vercel_deployment_not_production:{system_id}")
                if system_id in EXPECTED_PROJECTS and meta.get("githubCommitSha") != system.get("release_sha"):
                    result.stale(f"vercel_deployment_release_drift:{system_id}")
                vercel_evidence.setdefault(system_id, {})["api_verified"] = True
            except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
                result.stale(f"vercel_api_check_failed:{system_id}:{type(exc).__name__}")
    else:
        for system_id in EXPECTED_PROJECTS | EXPECTED_STATIC_PROJECTS:
            result.stale(f"vercel_api_not_verified:{system_id}")
            vercel_evidence.setdefault(system_id, {})["api_verified"] = False
            vercel_evidence[system_id]["api_note"] = "VERCEL_TOKEN absent; exact deployment ID retained from last authenticated refresh"
    result.evidence["vercel"] = vercel_evidence


def refresh_from_live(value: dict[str, Any], evidence: dict[str, Any], *, now: datetime) -> bool:
    """Apply only live facts that are independently corroborated.

    Deployment identifiers, PRIME runtime facts, and Dell acceptance are never
    inferred from GitHub heads or public health endpoints.
    """
    changed = False
    observed_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    github = evidence.get("github", {})
    vercel = evidence.get("vercel", {})
    systems = value["systems"]

    def refreshed_timestamp(system: dict[str, Any], facts_changed: bool) -> str:
        current = system.get("verified_at_utc")
        parsed = None
        if isinstance(current, str) and current.endswith("Z"):
            try:
                parsed = datetime.fromisoformat(current[:-1] + "+00:00")
            except ValueError:
                pass
        if facts_changed or parsed is None or now - parsed >= timedelta(hours=20):
            return observed_at
        return current

    control_head = github.get("control", {}).get("source_head_sha")
    if valid_sha(control_head):
        control = systems["control"]
        facts_changed = any([
            control.get("source_head_sha") != control_head,
            control.get("release_sha") != control_head,
            control.get("state") != "SOURCE_RELEASE_VERIFIED",
        ])
        updates = {
            "source_head_sha": control_head,
            "release_sha": control_head,
            "verified_at_utc": refreshed_timestamp(control, facts_changed),
            "state": "SOURCE_RELEASE_VERIFIED",
        }
        for key, updated in updates.items():
            if control.get(key) != updated:
                control[key] = updated
                changed = True

    for system_id in sorted(EXPECTED_PROJECTS):
        head = github.get(system_id, {}).get("source_head_sha")
        runtime = vercel.get(system_id, {})
        runtime_sha = runtime.get("runtime_sha")
        if not (valid_sha(head) and runtime.get("health_ok") is True and runtime_sha == head):
            continue
        system = systems[system_id]
        state = (
            "ALIGNED_VERIFIED" if runtime.get("api_verified") is True
            else "SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED"
        )
        facts_changed = any([
            system.get("source_head_sha") != head,
            system.get("release_sha") != head,
            system.get("runtime_sha") != head,
            system.get("state") != state,
        ])
        updates = {
            "source_head_sha": head,
            "release_sha": head,
            "runtime_sha": head,
            "verified_at_utc": refreshed_timestamp(system, facts_changed),
            "state": state,
        }
        for key, updated in updates.items():
            if system.get(key) != updated:
                system[key] = updated
                changed = True
    for system_id in sorted(EXPECTED_STATIC_PROJECTS):
        head = github.get(system_id, {}).get("source_head_sha")
        runtime = vercel.get(system_id, {})
        if not valid_sha(head):
            continue
        system = systems[system_id]
        if system.get("source_head_sha") != head:
            system["source_head_sha"] = head
            changed = True
        current_hash = runtime.get("current_source_content_sha256")
        runtime_hash = runtime.get("runtime_content_sha256")
        aligned = (
            isinstance(current_hash, str)
            and current_hash == runtime_hash
            and re.fullmatch(r"[0-9a-f]{64}", current_hash)
        )
        state = "SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED" if aligned \
            else "SOURCE_HEAD_OBSERVED_RUNTIME_CONTENT_DRIFT"
        facts_changed = any([
            system.get("source_head_sha") != head,
            system.get("state") != state,
            aligned and system.get("release_sha") != head,
            aligned and system.get("runtime_sha") != head,
            aligned and system.get("runtime_content_sha256") != runtime_hash,
        ])
        updates = {
            "verified_at_utc": refreshed_timestamp(system, facts_changed),
            "state": state,
        }
        if aligned:
            updates.update({
                "release_sha": head,
                "runtime_sha": head,
                "runtime_content_sha256": runtime_hash,
            })
        for key, updated in updates.items():
            if system.get(key) != updated:
                system[key] = updated
                changed = True
        implementation = value.get("implementation_frontier", {})
        if "sky_tablet" in implementation:
            sky_note = (
                "current source and production artifact content are hash-aligned; "
                "exact Vercel deployment identity remains unverified"
                if aligned else
                "current source is observed, but the production artifact content hash differs; "
                "release reconciliation remains blocked"
            )
            if implementation["sky_tablet"] != sky_note:
                implementation["sky_tablet"] = sky_note
                changed = True

    if changed and value.get("as_of_utc") != observed_at:
        value["as_of_utc"] = observed_at
    return changed


def write_stale(path: Path, value: dict[str, Any], reasons: list[str]) -> bool:
    changed = False
    if value.get("status") != "STALE":
        value["status"] = "STALE"
        changed = True
    verification = value.setdefault("verification", {})
    normalized = sorted(reasons)
    if verification.get("stale_reasons") != normalized:
        verification["stale_reasons"] = normalized
        changed = True
    if changed:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--branch-inventory", type=Path, default=DEFAULT_BRANCH_INVENTORY)
    parser.add_argument("--live", action="store_true", help="resolve live GitHub and Vercel boundaries")
    parser.add_argument("--allow-stale", action="store_true", help="accept truthful STALE state, never schema errors")
    parser.add_argument("--mark-stale", action="store_true", help="persist STALE when live or TTL checks fail")
    parser.add_argument(
        "--refresh-live",
        action="store_true",
        help="persist only corroborated live facts, then recompute effective status",
    )
    parser.add_argument("--now", help="override current UTC time for deterministic tests")
    parser.add_argument("--report", type=Path, help="write machine-readable verification evidence")
    args = parser.parse_args(argv)

    if args.refresh_live and not args.live:
        parser.error("--refresh-live requires --live")

    try:
        value = load_json(args.manifest)
        inventory = load_json(args.branch_inventory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Operational manifest: INVALID ({exc})", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc) if not args.now else datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    result = assess_static(value, inventory, now=now)
    if args.live and not result.errors:
        assess_live(value, result)
    if args.refresh_live and not result.errors:
        refresh_from_live(value, result.evidence, now=now)
        value.setdefault("verification", {})["stale_reasons"] = []
        value["status"] = "STALE"
        result = assess_static(value, inventory, now=now)
        if not result.errors:
            assess_live(value, result)
        write_stale(args.manifest, value, result.stale_reasons)
    elif args.mark_stale and result.stale_reasons:
        write_stale(args.manifest, value, result.stale_reasons)
    if args.report:
        args.report.write_text(json.dumps({
            "checked_at_utc": now.isoformat().replace("+00:00", "Z"),
            "effective_status": "STALE" if result.stale_reasons else "CURRENT",
            "errors": sorted(result.errors),
            "stale_reasons": sorted(result.stale_reasons),
            "evidence": result.evidence,
        }, indent=2) + "\n", encoding="utf-8")
    if result.errors:
        print("Operational manifest: INVALID", file=sys.stderr)
        for error in sorted(result.errors):
            print(f"- {error}", file=sys.stderr)
        return 2
    if result.stale_reasons:
        print("Operational manifest: STALE")
        for reason in sorted(result.stale_reasons):
            print(f"- {reason}")
        return 0 if args.allow_stale else 1
    print("Operational manifest: CURRENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
