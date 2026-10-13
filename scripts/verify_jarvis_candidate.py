"""Independent ORQEVIA display verifier; legacy filename/report ID stay compatible."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.jarvis_response_contract import validate_user_facing_answer
from app.product_identity import PRODUCT_NAME


def approved_manifest_icons(manifest: dict, pwa: Path) -> bool:
    """Require the approved full-image derivatives, not a branding filename."""
    expected = {
        "/pwa/icons/orqevia-official-v1-192.png": ("192x192", "d7cc5c2c6c63bf87a4afdad5b3cf0fa058444bb16d498ecaaa81e789d0fdeea2"),
        "/pwa/icons/orqevia-official-v1-512.png": ("512x512", "c018857c354a1cede7c514ff67904dd5057e9b3e8b7eef56a63fe46f094dce39"),
    }
    icons = manifest.get("icons", [])
    if len(icons) != len(expected) or {icon.get("src") for icon in icons} != set(expected):
        return False
    for icon in icons:
        size, digest = expected[icon["src"]]
        if (icon.get("sizes"), icon.get("type"), icon.get("purpose")) != (size, "image/png", "any"):
            return False
        path = pwa / icon["src"].removeprefix("/pwa/")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


def verify() -> dict[str, object]:
    node = subprocess.run(["node", "--test", "clients/pwa/tests.mjs", "clients/pwa/followup-tests.mjs", "clients/pwa/revision-tests.mjs", "clients/pwa/candidate-tests.mjs"], cwd=ROOT, text=True, capture_output=True, check=False)
    pwa = ROOT / "clients" / "pwa"
    manifest = json.loads((pwa / "manifest.webmanifest").read_text(encoding="utf-8"))
    checks = {
        "portable_pwa_suite": node.returncode == 0 and "fail 0" in node.stdout,
        "jarvis_chinese_valid": validate_user_facing_answer("你叫什么名字？", f"我是 {PRODUCT_NAME}，很高兴为你服务。") == [],
        "model_identity_rejected": all("product_identity_overridden" in validate_user_facing_answer("你叫什么名字？", answer) for answer in ("I am a large language model.", "我是 JARVIS，很高兴为你服务。")),
        "read_aloud_uses_governed_result": "voice.speak(spokenText(currentTask))" in (pwa / "app.mjs").read_text(encoding="utf-8"),
        "authoritative_session_refresh": "setInterval(" in (pwa / "app.mjs").read_text(encoding="utf-8") and "verifiedAt" in (pwa / "core.mjs").read_text(encoding="utf-8"),
        "deterministic_startup_recovery": (pwa / "recovery.js").is_file() and "startup-recovery" in (pwa / "index.html").read_text(encoding="utf-8"),
        "canonical_branding": manifest["name"] == manifest["short_name"] == "ORQEVIA" and manifest["id"] == manifest["scope"] == manifest["start_url"] == "/pwa/" and approved_manifest_icons(manifest, pwa),
    }
    return {"verifier": "jarvis-candidate-v1", "product_name": PRODUCT_NAME, "checks": checks, "passed": sum(checks.values()), "total": len(checks), "production_touched": False, "physical_phone_tested": False, "node_output_tail": node.stdout.splitlines()[-6:]}


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
