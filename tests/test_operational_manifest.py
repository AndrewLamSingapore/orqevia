import json
from pathlib import Path

from scripts.verify_operational_manifest import verify


def test_operational_manifest_is_unambiguous():
    root = Path(__file__).resolve().parents[1]
    verify(json.loads((root / "governance" / "operational-manifest.json").read_text(encoding="utf-8")))
