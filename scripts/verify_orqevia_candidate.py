"""Independent verifier for ORQEVIA candidate contracts and portable PWA tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orqevia_response_contract import validate_user_facing_answer


def canonical_branding(pwa: Path) -> bool:
    """Require the current install identity and real linked mark, not a prefix."""
    expected = {
        "/pwa/icons/orqevia-command-v2-192.png": ("192x192", "any"),
        "/pwa/icons/orqevia-command-v2-512.png": ("512x512", "any"),
        "/pwa/icons/orqevia-command-v2-maskable-512.png": ("512x512", "maskable"),
    }
    try:
        manifest = json.loads((pwa / "manifest.webmanifest").read_text(encoding="utf-8"))
        icons = manifest["icons"]
        identity = {icon["src"]: (icon["sizes"], icon["purpose"]) for icon in icons}
        html = (pwa / "index.html").read_text(encoding="utf-8")
        return (
            manifest["name"] == manifest["short_name"] == "ORQEVIA"
            and len(icons) == len(expected)
            and identity == expected
            and all((pwa / name.removeprefix("/pwa/")).is_file() for name in expected)
            and (pwa / "icons" / "orqevia-mark.svg").is_file()
            and 'src="/pwa/icons/orqevia-mark.svg"' in html
            and 'href="/pwa/icons/orqevia-command-v2-apple-touch.png"' in html
            and "orqevia-command-v1-" not in html
            and "orqevia-official-v1-" not in html
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verify() -> dict[str, object]:
    node = subprocess.run(
        [
            "node",
            "--test",
            "clients/pwa/tests.mjs",
            "clients/pwa/followup-tests.mjs",
            "clients/pwa/revision-tests.mjs",
            "clients/pwa/candidate-tests.mjs",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    pwa = ROOT / "clients" / "pwa"
    checks = {
        "portable_pwa_suite": node.returncode == 0 and "fail 0" in node.stdout,
        "orqevia_chinese_valid": validate_user_facing_answer("你叫什么名字？", "我是 ORQEVIA，很高兴为你服务。") == [],
        "model_identity_rejected": "product_identity_overridden"
        in validate_user_facing_answer("你叫什么名字？", "I am a large language model."),
        "read_aloud_uses_governed_result": "voice.speak(spokenText(currentTask))"
        in (pwa / "app.mjs").read_text(encoding="utf-8"),
        "authoritative_session_refresh": "setInterval(" in (pwa / "app.mjs").read_text(encoding="utf-8")
        and "verifiedAt" in (pwa / "core.mjs").read_text(encoding="utf-8"),
        "deterministic_startup_recovery": (pwa / "recovery.js").is_file()
        and "startup-recovery" in (pwa / "index.html").read_text(encoding="utf-8"),
        "canonical_branding": canonical_branding(pwa),
    }
    return {
        "verifier": "orqevia-candidate-v1",
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "production_touched": False,
        "physical_phone_tested": False,
        "node_output_tail": node.stdout.splitlines()[-6:],
    }


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
