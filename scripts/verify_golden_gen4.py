#!/usr/bin/env python3
"""Verify the current ORQEVIA golden baseline (gen4: epoch runtime, per role)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    value = json.loads((root / "governance/golden-gen4-manifest.json").read_text(encoding="utf-8"))

    def require(condition: bool, label: str) -> None:
        if not condition:
            errors.append(label)

    require(value.get("generation") == 4, "generation")
    require(value.get("golden_baseline_id") == "orqevia-golden-gen4-20261016", "baseline_id")
    require(value.get("source", {}).get("accepted_commit") == "48648edd8d2640f12f8086b9910deec865519326", "source")
    require(value.get("build", {}).get("image_id") == "sha256:aca892c4f19a4426e960d273ee0e9524f7bfe7f08bb80b902e7cbc73b82d36f3", "image")
    require(value.get("interface_build", {}).get("image_id") == "sha256:4e78da5c05254beef17bebd50be4300986fac9a5f28ca27905f4846530f4a388", "interface_image")
    require(value.get("interface_build", {}).get("source_revision") == "891e3adfdd6defac00d7faef34bec06a10de4a4e", "interface_source")
    require(value.get("supersedes", {}).get("golden_baseline_id") == "orqevia-golden-gen3-20261016", "supersedes")
    receipt = root / value["runtime_receipt"]["path"]
    require(receipt.is_file() and sha256(receipt) == value["runtime_receipt"]["sha256"], "receipt_digest")
    audio = value.get("audio", {})
    require(audio.get("read_aloud") == "PARKED_PHYSICAL_FAIL_NOT_ACCEPTED", "audio_not_parked")
    require(audio.get("production_critical") is False and audio.get("owner_waiver") is True, "audio_scope")
    require(value.get("acceptance", {}).get("state") == "VERIFIED_WITH_EXPLICIT_AUDIO_EXCLUSION", "acceptance")
    require(value.get("authority", {}).get("production_authority") == "ABEX", "authority")
    return errors


if __name__ == "__main__":
    failures = validate()
    print(json.dumps({
        "golden_baseline_id": "orqevia-golden-gen4-20261016",
        "verdict": "PASS" if not failures else "FAIL",
        "violations": failures,
    }, sort_keys=True))
    raise SystemExit(1 if failures else 0)
