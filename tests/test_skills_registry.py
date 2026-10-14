from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "skills" / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_schema_and_status():
    manifest = _manifest()
    assert manifest["schema_version"] == "1.0"
    assert manifest["status"] == "DRAFT_CANDIDATE"
    assert manifest["activation"] == "advisory_only"


def test_every_skill_is_unqualified_and_versioned():
    manifest = _manifest()
    assert len(manifest["skills"]) == 12
    for skill in manifest["skills"]:
        assert skill["status"] == "DRAFT_CANDIDATE"
        assert skill["qualified"] is False
        assert re.fullmatch(r"\d+\.\d+\.\d+", skill["version"])
        assert skill["owner_agents"]


def test_every_skill_has_a_skill_package():
    manifest = _manifest()
    for skill in manifest["skills"]:
        package = REPO_ROOT / "skills" / skill["id"] / "SKILL.md"
        assert package.is_file(), skill["id"]
        text = package.read_text(encoding="utf-8")
        assert f"id: {skill['id']}" in text
        assert f"version: {skill['version']}" in text


def test_dependencies_resolve_without_cycles_or_self_reference():
    manifest = _manifest()
    ids = {skill["id"] for skill in manifest["skills"]}
    for skill in manifest["skills"]:
        assert skill["id"] not in skill["dependencies"]
        assert set(skill["dependencies"]) <= ids
