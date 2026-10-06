"""Synthetic only: these tests never reference the ABEX runtime volume."""

import hashlib
import sqlite3
import struct

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

from scripts.offhost_backup import BackupError, _validate_manifest, encrypt_tree, restore_tree


def _keys(root):
    private = x25519.X25519PrivateKey.generate()
    public_path, private_path = root / "recipient.pub", root / "offline.key"
    public_path.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    private_path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return public_path, private_path


def _fixture(root):
    (root / "artifacts").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "artifacts" / "proof.json").write_bytes(b'{"owner_write":true}')
    (root / "action-records.jsonl").write_bytes(b'{"event":"created"}\n')
    with sqlite3.connect(root / "pwa-sessions.db") as db:
        db.execute("CREATE TABLE devices(role TEXT)")
        db.executemany("INSERT INTO devices VALUES (?)", [("OWNER",), ("MEMBER",)])


def test_encrypted_round_trip_keeps_owner_member_and_artifact(tmp_path):
    public, private = _keys(tmp_path)
    source, cipher, restored = (tmp_path / name for name in ("fenced", "backup.bin", "restored"))
    source.mkdir()
    _fixture(source)
    pinned = encrypt_tree(source, public, cipher)
    assert pinned == hashlib.sha256(cipher.read_bytes()).hexdigest()
    assert b"owner_write" not in cipher.read_bytes()
    assert restore_tree(cipher, private, restored, pinned) == 3
    assert (restored / "empty").is_dir()
    assert (restored / "artifacts" / "proof.json").read_bytes() == b'{"owner_write":true}'
    assert (restored / "action-records.jsonl").read_bytes() == b'{"event":"created"}\n'
    with sqlite3.connect(restored / "pwa-sessions.db") as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT role FROM devices ORDER BY role").fetchall() == [("MEMBER",), ("OWNER",)]


def test_tamper_and_truncation_rejected_without_published_restore(tmp_path):
    public, private = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"sensitive synthetic state")
    cipher = tmp_path / "backup.bin"
    encrypt_tree(source, public, cipher)
    original = cipher.read_bytes()
    data_offset = 13 + struct.unpack(">I", original[9:13])[0] + 5
    changed = bytearray(original)
    changed[data_offset] ^= 1  # authenticated data, not just the magic header
    for altered in (bytes(changed), original[:-20]):
        tampered = tmp_path / "tampered.bin"
        tampered.write_bytes(altered)
        destination = tmp_path / "restored"
        with pytest.raises(Exception):
            restore_tree(tampered, private, destination, hashlib.sha256(altered).hexdigest())
        assert not destination.exists()


def test_wrong_key_or_digest_rejected(tmp_path):
    public, _ = _keys(tmp_path)
    wrong_dir = tmp_path / "other"
    wrong_dir.mkdir()
    _, wrong_private = _keys(wrong_dir)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"state")
    cipher, restored = tmp_path / "backup.bin", tmp_path / "restored"
    pinned = encrypt_tree(source, public, cipher)
    with pytest.raises(BackupError, match="pinned"):
        restore_tree(cipher, wrong_private, restored, "0" * 64)
    with pytest.raises(Exception):
        restore_tree(cipher, wrong_private, restored, pinned)
    assert not restored.exists()


def test_more_than_one_authenticated_chunk(tmp_path):
    public, private = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    original = b"A" * (1024 * 1024 + 73)
    (source / "large.synthetic").write_bytes(original)
    cipher, restored = tmp_path / "backup.bin", tmp_path / "restored"
    pinned = encrypt_tree(source, public, cipher)
    assert restore_tree(cipher, private, restored, pinned) == 1
    assert (restored / "large.synthetic").read_bytes() == original


def test_unsafe_manifest_paths_and_source_escape_rejected(tmp_path):
    for name in ("../outside", "/absolute", "nested\\escape", "CON", "case/../bad"):
        with pytest.raises(BackupError):
            _validate_manifest({"version": 1, "directories": [],
                                "files": {name: {"size": 0, "sha256": "0" * 64}}})
    with pytest.raises(BackupError, match="undeclared parent"):
        _validate_manifest({"version": 1, "directories": [],
                            "files": {"nested/file": {"size": 0, "sha256": "0" * 64}}})
    public, _ = _keys(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "state").write_bytes(b"state")
    with pytest.raises(BackupError, match="outside source"):
        encrypt_tree(source, public, source / "cipher.bin")
