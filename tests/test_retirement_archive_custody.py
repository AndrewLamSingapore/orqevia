"""Retired source evidence must survive Linux and Windows checkout byte-exactly."""

import hashlib
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "folder",
    [
        "registry-retirement-20261106",
        "entrypoint-retirement-20261106",
        "architecture-baseline-retirement-20261106",
        "pocket-console-retirement-20261106",
        "desktop-retirement-20261106",
    ],
)
def test_retired_source_matches_its_custody_manifest(folder):
    root = Path(__file__).resolve().parents[1] / "docs/history" / folder
    manifest = json.loads((root / "ARCHIVE-MANIFEST.json").read_text(encoding="utf8"))
    assert manifest["scope"] == "HISTORICAL_NONEXECUTABLE_BYTES_NOT_CURRENT_AUTHORITY"
    for item in manifest["files"]:
        path = (root / item["path"]).resolve()
        assert path.is_relative_to(root.resolve()) and path.is_file()
        raw = path.read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
