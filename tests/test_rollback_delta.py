import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from scripts.rollback_delta import DeltaError, _inventory, capture_delta, manifest_digest, replay_delta


def _db(path: Path, member: bool) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE identities (role TEXT NOT NULL)")
        db.execute("INSERT INTO identities VALUES ('OWNER')")
        if member:
            db.execute("INSERT INTO identities VALUES ('MEMBER')")


def test_post_snapshot_owner_member_and_artifact_bytes_replay(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    for root in (base, final):
        (root / "artifacts").mkdir(parents=True)
    _db(base / "pwa-sessions.db", False)
    _db(final / "pwa-sessions.db", True)
    (base / "artifacts" / "old.json").write_text('{"version":1}')
    (final / "artifacts" / "old.json").write_text('{"version":2}')
    (final / "artifacts" / "new.json").write_text('{"owner_write":true}')
    (base / "deleted.jsonl").write_text("old\n")
    manifest = capture_delta(base, final, package)
    assert "pwa-sessions.db" in manifest["changed"]
    assert manifest["deleted"] == ["deleted.jsonl"]
    replay_delta(base, package, restored, manifest_digest(package))
    assert _inventory(restored) == _inventory(final)
    with sqlite3.connect(restored / "pwa-sessions.db") as db:
        assert db.execute("SELECT role FROM identities ORDER BY role").fetchall() == [("MEMBER",), ("OWNER",)]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert not (restored / "deleted.jsonl").exists()


def test_tampered_payload_fails_without_creating_restore(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    base.mkdir(); final.mkdir()
    (base / "state").write_bytes(b"before")
    (final / "state").write_bytes(b"after")
    capture_delta(base, final, package)
    (package / "payload" / "state").write_bytes(b"evil")
    with pytest.raises(DeltaError, match="payload"):
        replay_delta(base, package, restored, manifest_digest(package))
    assert not restored.exists()


def test_changed_snapshot_and_existing_destination_fail_closed(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    base.mkdir(); final.mkdir()
    (base / "state").write_bytes(b"before")
    (final / "state").write_bytes(b"after")
    capture_delta(base, final, package)
    (base / "state").write_bytes(b"mutated")
    with pytest.raises(DeltaError, match="snapshot"):
        replay_delta(base, package, restored, manifest_digest(package))
    assert not restored.exists()
    restored.mkdir()
    with pytest.raises(DeltaError, match="already exists"):
        replay_delta(base, package, restored, manifest_digest(package))


def test_path_traversal_manifest_rejected(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    base.mkdir(); final.mkdir()
    (final / "state").write_bytes(b"after")
    capture_delta(base, final, package)
    pinned = manifest_digest(package)
    path = package / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["deleted"] = ["../outside"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(DeltaError, match="invalid delta path"):
        replay_delta(base, package, restored, manifest_digest(package))
    with pytest.raises(DeltaError, match="independent pinned digest"):
        replay_delta(base, package, restored, pinned)
    assert not restored.exists()


def test_file_directory_shape_change_replays(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    (base / "parent").mkdir(parents=True)
    (base / "parent" / "child").write_text("before")
    final.mkdir(); (final / "parent").write_text("after")
    capture_delta(base, final, package)
    replay_delta(base, package, restored, manifest_digest(package))
    assert _inventory(restored) == _inventory(final)


def test_file_replaced_by_directory_replays(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    base.mkdir(); (base / "parent").write_text("before")
    (final / "parent").mkdir(parents=True)
    (final / "parent" / "child").write_text("after")
    capture_delta(base, final, package)
    replay_delta(base, package, restored, manifest_digest(package))
    assert _inventory(restored) == _inventory(final)
    assert (restored / "parent").is_dir()


def test_file_replaced_by_empty_directory_replays(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    base.mkdir(); (base / "parent").write_text("before")
    (final / "parent").mkdir(parents=True)
    capture_delta(base, final, package)
    replay_delta(base, package, restored, manifest_digest(package))
    assert (restored / "parent").is_dir()
    assert list((restored / "parent").iterdir()) == []


def test_empty_directory_shape_change_rejects_changed_snapshot(tmp_path):
    base, final, package, restored = (tmp_path / name for name in ("base", "final", "delta", "restored"))
    (base / "empty").mkdir(parents=True)
    final.mkdir()
    capture_delta(base, final, package)
    (base / "empty").rmdir()
    with pytest.raises(DeltaError, match="snapshot differs"):
        replay_delta(base, package, restored, manifest_digest(package))
    assert not restored.exists()


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction regression requires Windows")
def test_windows_junction_outside_fenced_tree_is_rejected(tmp_path):
    base, final, outside, package = (tmp_path / name for name in ("base", "final", "outside", "delta"))
    base.mkdir(); final.mkdir(); outside.mkdir()
    (outside / "private.txt").write_text("outside the fenced snapshot")
    junction = final / "escaped"
    created = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J",
                              str(junction), str(outside)],
                             capture_output=True, text=True)
    assert created.returncode == 0, (created.stdout + created.stderr).strip()
    assert junction.is_junction() and not junction.is_symlink()
    with pytest.raises(DeltaError, match="reparse"):
        capture_delta(base, final, package)
    assert not package.exists()
