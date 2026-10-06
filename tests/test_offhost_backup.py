"""Synthetic only: these tests never reference the ABEX runtime volume."""

import hashlib
import os
import sqlite3
import struct
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

from scripts import offhost_backup
from scripts.offhost_backup import BackupError, _validate_manifest, encrypt_tree, restore_tree


PASSPHRASE = b"synthetic offline passphrase"


def _keys(root):
    private = x25519.X25519PrivateKey.generate()
    public_path, private_path = root / "recipient.pub", root / "offline.key"
    public_path.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    private_path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(PASSPHRASE)))
    fingerprint = hashlib.sha256(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    return public_path, private_path, fingerprint


def _private_parent(root):
    parent = root / "private-restore"
    parent.mkdir()
    if os.name == "nt":
        script = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:PRIME_TEST_PRIVATE_DIR
$acl.SetAccessRuleProtection($true, $false)
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
foreach ($sid in @($me, [System.Security.Principal.SecurityIdentifier]'S-1-5-18', [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544')) {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $env:PRIME_TEST_PRIVATE_DIR -AclObject $acl
"""
        environment = os.environ.copy()
        environment["PRIME_TEST_PRIVATE_DIR"] = str(parent)
        environment["PSModulePath"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/Modules")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       env=environment, check=True, capture_output=True)
    else:
        parent.chmod(0o700)
    return parent


def _fixture(root):
    (root / "artifacts").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "artifacts" / "proof.json").write_bytes(b'{"owner_write":true}')
    (root / "action-records.jsonl").write_bytes(b'{"event":"created"}\n')
    with sqlite3.connect(root / "pwa-sessions.db") as db:
        db.execute("CREATE TABLE devices(role TEXT)")
        db.executemany("INSERT INTO devices VALUES (?)", [("OWNER",), ("MEMBER",)])


def test_encrypted_round_trip_keeps_owner_member_and_artifact(tmp_path):
    public, private, fingerprint = _keys(tmp_path)
    source, cipher = tmp_path / "fenced", tmp_path / "backup.bin"
    restored = _private_parent(tmp_path) / "restored"
    source.mkdir()
    _fixture(source)
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    assert pinned == hashlib.sha256(cipher.read_bytes()).hexdigest()
    assert b"owner_write" not in cipher.read_bytes()
    assert restore_tree(cipher, private, restored, pinned, PASSPHRASE) == 3
    assert (restored / "empty").is_dir()
    assert (restored / "artifacts" / "proof.json").read_bytes() == b'{"owner_write":true}'
    assert (restored / "action-records.jsonl").read_bytes() == b'{"event":"created"}\n'
    with sqlite3.connect(restored / "pwa-sessions.db") as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT role FROM devices ORDER BY role").fetchall() == [("MEMBER",), ("OWNER",)]


def test_tamper_and_truncation_rejected_without_published_restore(tmp_path):
    public, private, fingerprint = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"sensitive synthetic state")
    cipher = tmp_path / "backup.bin"
    encrypt_tree(source, public, cipher, fingerprint)
    original = cipher.read_bytes()
    data_offset = 13 + struct.unpack(">I", original[9:13])[0] + 5
    changed = bytearray(original)
    changed[data_offset] ^= 1  # authenticated data, not just the magic header
    destination = _private_parent(tmp_path) / "restored"
    for altered in (bytes(changed), original[:-20]):
        tampered = tmp_path / "tampered.bin"
        tampered.write_bytes(altered)
        with pytest.raises(Exception):
            restore_tree(tampered, private, destination, hashlib.sha256(altered).hexdigest(), PASSPHRASE)
        assert not destination.exists()


def test_wrong_key_or_digest_rejected(tmp_path):
    public, _, fingerprint = _keys(tmp_path)
    wrong_dir = tmp_path / "other"
    wrong_dir.mkdir()
    _, wrong_private, _ = _keys(wrong_dir)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"state")
    cipher, restored = tmp_path / "backup.bin", _private_parent(tmp_path) / "restored"
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    with pytest.raises(BackupError, match="pinned"):
        restore_tree(cipher, wrong_private, restored, "0" * 64, PASSPHRASE)
    with pytest.raises(Exception):
        restore_tree(cipher, wrong_private, restored, pinned, PASSPHRASE)
    assert not restored.exists()


def test_more_than_one_authenticated_chunk(tmp_path):
    public, private, fingerprint = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    original = b"A" * (1024 * 1024 + 73)
    (source / "large.synthetic").write_bytes(original)
    cipher, restored = tmp_path / "backup.bin", _private_parent(tmp_path) / "restored"
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    assert restore_tree(cipher, private, restored, pinned, PASSPHRASE) == 1
    assert (restored / "large.synthetic").read_bytes() == original


def test_unsafe_manifest_paths_and_source_escape_rejected(tmp_path):
    for name in ("../outside", "/absolute", "nested\\escape", "CON", "COM¹", "LPT³.txt", "case/../bad"):
        with pytest.raises(BackupError):
            _validate_manifest({"version": 1, "directories": [],
                                "files": {name: {"size": 0, "sha256": "0" * 64}}})
    with pytest.raises(BackupError, match="undeclared parent"):
        _validate_manifest({"version": 1, "directories": [],
                            "files": {"nested/file": {"size": 0, "sha256": "0" * 64}}})
    public, _, fingerprint = _keys(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "state").write_bytes(b"state")
    with pytest.raises(BackupError, match="outside source"):
        encrypt_tree(source, public, source / "cipher.bin", fingerprint)


def test_substituted_recipient_and_unencrypted_private_key_rejected(tmp_path):
    public, private, fingerprint = _keys(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    substitute, _, _ = _keys(other)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"synthetic")
    cipher = tmp_path / "backup.bin"
    with pytest.raises(BackupError, match="recipient key"):
        encrypt_tree(source, substitute, cipher, fingerprint)
    assert not cipher.exists()
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    unencrypted = tmp_path / "unencrypted.key"
    unencrypted.write_bytes(serialization.load_pem_private_key(private.read_bytes(), password=PASSPHRASE).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    restored = _private_parent(tmp_path) / "restored"
    with pytest.raises(Exception):
        restore_tree(cipher, unencrypted, restored, pinned, PASSPHRASE)
    with pytest.raises(BackupError, match="passphrase"):
        restore_tree(cipher, private, restored, pinned, b"")
    assert not restored.exists()


def test_offline_fingerprint_command(tmp_path, capsys):
    public, _, fingerprint = _keys(tmp_path)
    assert offhost_backup.main(["fingerprint", str(public)]) == 0
    assert capsys.readouterr().out.strip() == "recipient_sha256=" + fingerprint


def test_hardlinks_source_change_and_destination_race_rejected(tmp_path, monkeypatch):
    public, _, fingerprint = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    state = source / "state"
    state.write_bytes(b"synthetic")
    linked = tmp_path / "hardlink"
    os.link(state, linked)
    with pytest.raises(BackupError, match="hardlinked"):
        encrypt_tree(source, public, tmp_path / "backup.bin", fingerprint)
    linked.unlink()

    original = offhost_backup._VerifiedFile

    def change_source(path, expected, identity):
        os.utime(path, ns=(identity[4] + 10_000_000, identity[4] + 10_000_000))
        return original(path, expected, identity)

    monkeypatch.setattr(offhost_backup, "_VerifiedFile", change_source)
    with pytest.raises(BackupError, match="source changed"):
        encrypt_tree(source, public, tmp_path / "backup.bin", fingerprint)
    monkeypatch.setattr(offhost_backup, "_VerifiedFile", original)

    original_publish = offhost_backup._publish_new

    def race(staged, output, directory):
        output.write_bytes(b"existing")
        return original_publish(staged, output, directory)

    monkeypatch.setattr(offhost_backup, "_publish_new", race)
    with pytest.raises(FileExistsError):
        encrypt_tree(source, public, tmp_path / "backup.bin", fingerprint)
    assert (tmp_path / "backup.bin").read_bytes() == b"existing"


def test_broad_restore_parent_refused_before_plaintext(tmp_path):
    public, private, fingerprint = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"synthetic")
    cipher = tmp_path / "backup.bin"
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    broad = tmp_path / "broad"
    broad.mkdir()
    if os.name == "nt":
        script = r"""
$acl = Get-Acl -LiteralPath $env:PRIME_TEST_BROAD_DIR
$sid = [System.Security.Principal.SecurityIdentifier]'S-1-1-0'
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'ReadAndExecute', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $env:PRIME_TEST_BROAD_DIR -AclObject $acl
"""
        environment = os.environ.copy()
        environment["PRIME_TEST_BROAD_DIR"] = str(broad)
        environment["PSModulePath"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/Modules")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       env=environment, check=True, capture_output=True)
    else:
        broad.chmod(0o755)
    with pytest.raises(BackupError, match="private restore"):
        restore_tree(cipher, private, broad / "restored", pinned, PASSPHRASE)
    assert list(broad.iterdir()) == []


def test_restore_publication_does_not_replace_racing_directory(tmp_path, monkeypatch):
    public, private, fingerprint = _keys(tmp_path)
    source = tmp_path / "fenced"
    source.mkdir()
    (source / "state").write_bytes(b"synthetic")
    cipher = tmp_path / "backup.bin"
    pinned = encrypt_tree(source, public, cipher, fingerprint)
    destination = _private_parent(tmp_path) / "restored"
    original_publish = offhost_backup._publish_new

    def race(staged, output, directory):
        output.mkdir()
        (output / "racer").write_bytes(b"existing")
        return original_publish(staged, output, directory)

    monkeypatch.setattr(offhost_backup, "_publish_new", race)
    with pytest.raises(FileExistsError):
        restore_tree(cipher, private, destination, pinned, PASSPHRASE)
    assert (destination / "racer").read_bytes() == b"existing"
    assert not (destination / "state").exists()
