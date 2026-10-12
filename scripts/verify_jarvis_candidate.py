"""Independent verifier for JARVIS candidate contracts and portable PWA tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.jarvis_response_contract import validate_user_facing_answer


def canonical_pwa_branding(pwa: Path) -> bool:
    """Verify the preserved private PWA identity and exact install asset family."""
    try:
        manifest = json.loads((pwa / 'manifest.webmanifest').read_text(encoding='utf-8'))
        icons = manifest['icons']
        expected = {'/pwa/icons/orqevia-v1-192.png': '192x192',
                    '/pwa/icons/orqevia-v1-512.png': '512x512'}
        return (manifest['name'] == 'ORQEVIA · 奥启维亚'
                and manifest['short_name'] == 'ORQEVIA'
                and manifest['id'] == manifest['scope'] == manifest['start_url'] == '/pwa/'
                and type(icons) is list and len(icons) == len(expected)
                and {icon['src']: icon['sizes'] for icon in icons} == expected
                and all(icon['type'] == 'image/png' and icon['purpose'] == 'any'
                        and (pwa / icon['src'].removeprefix('/pwa/')).is_file()
                        for icon in icons))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verify() -> dict[str, object]:
    node = subprocess.run(["node", "--test", "clients/pwa/tests.mjs", "clients/pwa/followup-tests.mjs", "clients/pwa/revision-tests.mjs", "clients/pwa/candidate-tests.mjs"], cwd=ROOT, text=True, capture_output=True, check=False)
    pwa = ROOT / "clients" / "pwa"
    checks = {
        "portable_pwa_suite": node.returncode == 0 and "fail 0" in node.stdout,
        "jarvis_chinese_valid": validate_user_facing_answer("你叫什么名字？", "我是 JARVIS，很高兴为你服务。") == [],
        "model_identity_rejected": "product_identity_overridden" in validate_user_facing_answer("你叫什么名字？", "I am a large language model."),
        "read_aloud_uses_governed_result": "voice.speak(spokenText(currentTask))" in (pwa / "app.mjs").read_text(encoding="utf-8"),
        "authoritative_session_refresh": "setInterval(" in (pwa / "app.mjs").read_text(encoding="utf-8") and "verifiedAt" in (pwa / "core.mjs").read_text(encoding="utf-8"),
        "deterministic_startup_recovery": (pwa / "recovery.js").is_file() and "startup-recovery" in (pwa / "index.html").read_text(encoding="utf-8"),
        "canonical_branding": canonical_pwa_branding(pwa),
    }
    return {"verifier": "jarvis-candidate-v1", "checks": checks, "passed": sum(checks.values()), "total": len(checks), "production_touched": False, "physical_phone_tested": False, "node_output_tail": node.stdout.splitlines()[-6:]}


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
