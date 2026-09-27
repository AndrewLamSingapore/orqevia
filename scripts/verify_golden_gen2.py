#!/usr/bin/env python3
from __future__ import annotations

import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance/golden-gen2-manifest.json"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    value = json.loads((root / "governance/golden-gen2-manifest.json").read_text(encoding="utf-8"))
    def require(condition: bool, label: str) -> None:
        if not condition: errors.append(label)
    require(value.get("generation") == 2, "generation")
    require(value.get("source", {}).get("accepted_commit") == "b171253566e7c879283d2aacf699ae6c1ec8988e", "source")
    require(value.get("build", {}).get("image_id") == "sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5", "image")
    receipt = root / value["runtime_receipt"]["path"]
    require(receipt.is_file() and sha(receipt) == value["runtime_receipt"]["sha256"], "receipt_digest")
    audio = value.get("audio", {})
    issue = root / audio.get("known_issue_path", "missing")
    require(issue.is_file() and sha(issue) == audio.get("known_issue_sha256"), "audio_issue_digest")
    require(audio.get("read_aloud") == "PARKED_PHYSICAL_FAIL_NOT_ACCEPTED", "audio_not_parked")
    require(audio.get("production_critical") is False and audio.get("owner_waiver") is True, "audio_scope")
    require(value.get("acceptance", {}).get("state") == "VERIFIED_WITH_EXPLICIT_AUDIO_EXCLUSION", "acceptance")
    require(value.get("acceptance", {}).get("dell_post_promotion") == "PENDING", "dell_truth")
    require(value.get("rollback", {}).get("ready") is True and value.get("historical_preservation", {}).get("golden_gen1_preserved") is True, "rollback")
    q = value.get("qualification", {})
    require((q.get("unresolved_p0"), q.get("unresolved_p1"), q.get("unresolved_p2_accepted_scope")) == (0, 0, 0), "defects")
    return errors

if __name__ == "__main__":
    failures = validate()
    print(json.dumps({"golden_baseline_id": "jarvis-prime-golden-gen2-20260927", "verdict": "PASS" if not failures else "FAIL", "violations": failures}, sort_keys=True))
    raise SystemExit(bool(failures))
