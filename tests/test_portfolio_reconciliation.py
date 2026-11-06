"""Historical portfolio checks are preserved without gating current status notes."""

import hashlib
import json
from pathlib import Path


def test_historical_portfolio_reconciliation_originals_are_preserved():
    archive = Path(__file__).resolve().parents[1] / "docs/history/portfolio-reconciliation-20261106"
    manifest = json.loads((archive / "ARCHIVE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["scope"] == "DATED_PORTFOLIO_RECONCILIATION_NOT_PRODUCT_RUNTIME_AUTHORITY"
    assert {item["source"] for item in manifest["files"]} == {"tests/test_portfolio_reconciliation.py", "STATUS.md"}
    for item in manifest["files"]:
        path = (archive / item["archive"]).resolve()
        assert path.is_relative_to(archive.resolve())
        raw = path.read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
