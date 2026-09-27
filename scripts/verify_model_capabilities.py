"""Independently derive model capabilities from sanitized benchmark receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "model_capabilities.v1.json"
DEFAULT_EVIDENCE = (
    ROOT / "docs" / "evidence" / "supreme-intelligence-gemma3-1b-20260925.json",
    ROOT / "docs" / "evidence" / "supreme-intelligence-gemma3-4b-20260925.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(profile_path: Path, evidence_paths: tuple[Path, ...]) -> dict:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    evidence_by_model = {}
    evidence_hashes = {}
    for path in evidence_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        model = raw.get("model")
        if not model or model in evidence_by_model:
            raise ValueError("benchmark evidence requires unique model identities")
        if raw.get("classification") != "LAB_EXECUTED" or raw.get("privacy") != "docker-internal-only":
            raise ValueError(f"untrusted benchmark classification for {model}")
        if raw.get("measurement_scope", {}).get("response_content_persisted") is not False:
            raise ValueError(f"benchmark response-content boundary missing for {model}")
        results = raw.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError(f"benchmark results missing for {model}")
        categories = [str(item.get("category", "")) for item in results]
        if len(categories) != len(set(categories)) or any(not item for item in categories):
            raise ValueError(f"benchmark categories invalid for {model}")
        evidence_by_model[model] = raw
        evidence_hashes[path.name] = sha256(path)

    verified_profiles = []
    for item in profile.get("profiles", []):
        model = item.get("model")
        evidence = evidence_by_model.get(model)
        if evidence is None:
            raise ValueError(f"profile has no benchmark evidence: {model}")
        passed = {result["category"] for result in evidence["results"] if result.get("passed") is True}
        failed = {result["category"] for result in evidence["results"] if result.get("passed") is not True}
        claimed = set(item.get("verified_capabilities", []))
        declared_failed = set(item.get("failed_capabilities", []))
        if claimed != passed:
            raise ValueError(f"verified capability overclaim or omission for {model}")
        if declared_failed != failed:
            raise ValueError(f"failed capability mismatch for {model}")
        measured_latency = float(evidence.get("overall", {}).get("median_latency_seconds", 0))
        if float(item.get("median_latency_seconds", 0)) != measured_latency:
            raise ValueError(f"latency evidence mismatch for {model}")
        verified_profiles.append(model)
    if set(verified_profiles) != set(evidence_by_model):
        raise ValueError("benchmark evidence and profiles are not one-to-one")
    return {
        "status": "PASS",
        "profile_sha256": sha256(profile_path),
        "evidence_sha256": evidence_hashes,
        "verified_models": sorted(verified_profiles),
        "authority_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--evidence", type=Path, nargs="+", default=list(DEFAULT_EVIDENCE))
    args = parser.parse_args()
    print(json.dumps(verify(args.profile, tuple(args.evidence)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
