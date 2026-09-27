#!/usr/bin/env python3
"""Fail-closed structural verifier for the isolated Phase 2 candidate."""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance/phase2-candidate-manifest.json"


def validate(value: dict) -> list[str]:
    errors: list[str] = []
    require = lambda condition, message: None if condition else errors.append(message)
    require(value.get("schema_version") == "jarvis.phase2-candidate.v1", "schema")
    require(value.get("state") == "CANDIDATE_NOT_DEPLOYED", "candidate_state")
    require(value.get("parent_golden", {}).get("tag") == "jarvis-prime-golden-gen1-20260926", "golden_parent")
    require(value.get("parent_golden", {}).get("commit") == "26f7d49cfe7134f8665dda5886111e91b574554d", "golden_commit")
    for key in ("implementation", "architecture", "gap_analysis"):
        require((ROOT / value.get("source", {}).get(key, "missing")).is_file(), "missing:" + key)
    for path in ("app/evidence_product.py", "app/prime_evidence_adapter.py", "app/phase2_evidence_adapter.py",
                 "governance/action-envelope-v0.1.schema.json", "governance/evidence-product-v0.1-manifest.json",
                 "docs/ACTION-ENVELOPE-STANDARD-v0.1.md", "examples/evidence-lens/index.html"):
        require((ROOT / path).is_file(), "missing_product:" + path)
    authority = value.get("authority", {})
    for key in ("creates_authority", "model_content_authoritative", "member_inherits_owner",
                "predictions_trigger_actions", "lessons_trigger_actions"):
        require(authority.get(key) is False, "authority:" + key)
    require(value.get("feature_flags", {}).get("production_enabled") is False, "production_flag")
    require(value.get("production", {}).get("modified") is False, "production_modified")
    require(value.get("production", {}).get("runtime_receipt") == "NOT_APPLICABLE_NOT_DEPLOYED", "runtime_receipt_boundary")
    require(value.get("promotion", {}).get("authorized_by_this_manifest") is False, "promotion_boundary")
    require(value.get("external_boundaries", {}).get("wuhan_mainland_china") == "PHYSICAL_VERIFICATION_PENDING", "wuhan_boundary")
    require(value.get("external_boundaries", {}).get("velyqua_physical") == "PARKED", "velyqua_boundary")
    try:
        tree = ast.parse((ROOT / value["source"]["implementation"]).read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        require({"Phase2Kernel", "AuthorityEnvelope", "CompiledContext"}.issubset(names), "implementation_contract")
    except Exception:
        errors.append("implementation_parse")
    try:
        ancestor = subprocess.run(["git", "merge-base", "HEAD", value["parent_golden"]["tag"]], cwd=ROOT,
                                  check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        require(ancestor == value["parent_golden"]["commit"], "lineage")
    except Exception:
        errors.append("lineage_probe")
    return sorted(set(errors))


def main() -> int:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = validate(value)
    print(json.dumps({"candidate_id": value.get("candidate_id"), "verdict": "PASS" if not errors else "FAIL",
                      "violations": errors}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
