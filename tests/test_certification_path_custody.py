"""Real redirected ancestry cannot lend custody to a valid evidence digest."""

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from app.agent_certification import _artifact_digest_ok


def test_contained_evidence_under_redirected_ancestry_is_denied(tmp_path):
    real = tmp_path / "real"
    agent = real / "agent"
    agent.mkdir(parents=True)
    body = b"original synthetic evidence"
    (agent / "record.json").write_bytes(body)
    expected = hashlib.sha256(body).hexdigest()
    assert _artifact_digest_ok(agent, "record.json", expected)
    link = tmp_path / "redirect"
    if os.name == "nt":
        environment = {**os.environ, "ABEX_TEST_LINK_PATH": str(link), "ABEX_TEST_REAL_PATH": str(real)}
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:ABEX_TEST_LINK_PATH -Target $env:ABEX_TEST_REAL_PATH | Out-Null",
            ],
            env=environment,
            capture_output=True,
            timeout=20,
        )
        if result.returncode:
            pytest.skip("Host does not permit a test-directory junction")
    else:
        link.symlink_to(real, target_is_directory=True)
    assert (link / "agent" / "record.json").read_bytes() == body
    assert not _artifact_digest_ok(link / "agent", "record.json", expected)


def test_contained_ntfs_reparse_evidence_is_denied_even_without_symlink_flag(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    nested = agent / "redirect"
    nested.mkdir(parents=True)
    body = b"contained synthetic redirected evidence"
    (nested / "record.json").write_bytes(body)
    assert not nested.is_symlink()
    original = getattr(Path, "is_junction", lambda self: False)
    monkeypatch.setattr(Path, "is_junction", lambda self: self == nested or original(self), raising=False)
    assert not _artifact_digest_ok(agent, "redirect/record.json", hashlib.sha256(body).hexdigest())
