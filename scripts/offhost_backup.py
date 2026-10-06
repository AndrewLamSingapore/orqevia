"""Encrypt a *fenced copy* for off-host storage; restore only to a new tree.

The recipient's X25519 private key belongs on an offline recovery device, never
on ABEX. A pinned ciphertext SHA-256 is required for restore because anyone with
the public key can create a different encrypted bundle. This tool cannot create
or prove a production write fence, private destination ACL, or Azure upload.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


MAGIC = b"PRIMEBKP1"
CHUNK = 1024 * 1024
MAX_MANIFEST = 8 * 1024 * 1024
REPARSE = 0x400
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class BackupError(ValueError):
    pass


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError("duplicate manifest field")
        result[key] = value
    return result


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise BackupError("unsafe archive path")
    parts = name.split("/")
    if any(not part or part in (".", "..") or part[-1] in ". " or
           re.search(r'[<>"|?*\x00-\x1f]', part) or
           part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), *(f"COM{i}" for i in "¹²³"), *(f"LPT{i}" for i in "¹²³")}
           for part in parts):
        raise BackupError("unsafe archive path")
    return name


def _real_dir(path: Path) -> Path:
    if not path.is_dir():
        raise BackupError("expected a real directory")
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink() or part.is_junction() or getattr(part.lstat(), "st_file_attributes", 0) & REPARSE:
            raise BackupError("directory or ancestor is a link")
    return path.resolve()


def _private_dir(path: Path) -> None:
    resolved = _real_dir(path)
    if os.name == "nt":
        # Use .NET's security descriptor API, never localized icacls text.
        script = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:PRIME_RESTORE_PRIVATE_DIR
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed = @($me, 'S-1-5-18', 'S-1-5-32-544')
if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed) { exit 2 }
$allowed += 'S-1-3-4' # OWNER RIGHTS is restricted to the validated owner.
$allowCount = 0
foreach ($rule in $acl.Access) {
    if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { continue }
    $allowCount++
    $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($sid -notin $allowed) { exit 2 }
}
if ($allowCount -eq 0) { exit 2 } # Also reject a null/unrestricted DACL.
"""
        environment = os.environ.copy()
        environment["PRIME_RESTORE_PRIVATE_DIR"] = str(resolved)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        environment["PSModulePath"] = str(powershell.parent / "Modules")
        try:
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                    env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    check=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackupError("private restore ACL could not be verified") from exc
        if result.returncode:
            raise BackupError("private restore ACL could not be verified")
    else:
        info = resolved.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise BackupError("private restore permissions required")


def _recipient(public_key: Path) -> tuple[x25519.X25519PublicKey, str]:
    key = serialization.load_pem_public_key(Path(public_key).read_bytes())
    if not isinstance(key, x25519.X25519PublicKey):
        raise BackupError("recipient must be an X25519 public key")
    canonical = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, hashlib.sha256(canonical).hexdigest()


def _publish_new(staged: Path, output: Path, directory: bool) -> None:
    if not directory:
        os.link(staged, output)  # Fails atomically if the destination appeared.
    elif os.name == "nt":
        os.rename(staged, output)  # Windows rename never replaces an existing destination.
    else:
        # Linux renameat2(RENAME_NOREPLACE); unsupported platforms fail closed.
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise BackupError("no atomic no-replace directory publication")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(staged), -100, os.fsencode(output), 1):
            raise OSError(ctypes.get_errno(), "atomic restore publication failed")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    # Windows fstat() reports mtime as ctime, unlike lstat(); exclude ctime there.
    return (info.st_dev, info.st_ino, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns if os.name != "nt" else 0)


def _inventory(root: Path) -> tuple[list[str], dict[str, dict], dict[str, tuple]]:
    _real_dir(root)
    dirs: list[str] = []
    files: dict[str, dict] = {}
    identities: dict[str, tuple] = {}
    folded: set[str] = set()

    def visit(folder: Path, prefix: str = "") -> None:
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            name = _safe_name(f"{prefix}/{entry.name}" if prefix else entry.name)
            if name.casefold() in folded:
                raise BackupError("case-colliding archive path")
            folded.add(name.casefold())
            info = Path(entry.path).lstat()  # DirEntry.stat omits file IDs/link counts on Windows.
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE:
                raise BackupError("links and reparse points are forbidden")
            if stat.S_ISDIR(info.st_mode):
                dirs.append(name)
                visit(Path(entry.path), name)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise BackupError("hardlinked source file")
                digest = hashlib.sha256()
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                with os.fdopen(os.open(entry.path, flags), "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if _identity(opened) != _identity(info):
                        raise BackupError("source changed during inventory")
                    for block in iter(lambda: stream.read(CHUNK), b""):
                        digest.update(block)
                    if _identity(os.fstat(stream.fileno())) != _identity(info):
                        raise BackupError("source changed during inventory")
                if _identity(Path(entry.path).lstat()) != _identity(info):
                    raise BackupError("source changed during inventory")
                files[name] = {"size": info.st_size, "sha256": digest.hexdigest()}
                identities[name] = _identity(info)
            else:
                raise BackupError("unsupported archive entry")

    visit(root)
    return sorted(dirs), dict(sorted(files.items())), dict(sorted(identities.items()))


class _VerifiedFile:
    def __init__(self, path: Path, expected: dict, identity: tuple):
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & REPARSE or _identity(before) != identity:
            raise BackupError("source changed before archive")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        self.stream = os.fdopen(os.open(path, flags), "rb")
        self.expected = expected
        self.identity = identity
        self.digest = hashlib.sha256()
        self.count = 0
        if _identity(os.fstat(self.stream.fileno())) != identity or _identity(path.lstat()) != identity:
            self.stream.close()
            raise BackupError("source changed before archive")

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        self.digest.update(block)
        self.count += len(block)
        return block

    def finish(self) -> None:
        extra = self.stream.read(1)
        unchanged = _identity(os.fstat(self.stream.fileno())) == self.identity
        self.stream.close()
        if (extra or self.count != self.expected["size"] or self.digest.hexdigest() != self.expected["sha256"]
                or not unchanged):
            raise BackupError("source changed during archive")


class _CipherWriter:
    def __init__(self, stream, recipient: x25519.X25519PublicKey):
        ephemeral = x25519.X25519PrivateKey.generate()
        salt, prefix = os.urandom(16), os.urandom(4)
        header = _json({"version": 1, "chunk": CHUNK, "ephemeral": base64.b64encode(ephemeral.public_key().public_bytes_raw()).decode(),
                        "salt": base64.b64encode(salt).decode(), "nonce_prefix": base64.b64encode(prefix).decode()})
        self.key = AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=MAGIC).derive(ephemeral.exchange(recipient)))
        self.header_hash = hashlib.sha256(header).digest()
        self.prefix = prefix
        self.stream = stream
        self.cipher_hash = hashlib.sha256()
        self.plain_hash = hashlib.sha256()
        self.plain_size = 0
        self.buffer = bytearray()
        self.index = 0
        self._raw(MAGIC + struct.pack(">I", len(header)) + header)

    def _raw(self, block: bytes) -> None:
        self.stream.write(block)
        self.cipher_hash.update(block)

    def _frame(self, kind: bytes, plain: bytes) -> None:
        if self.index >= 2**64:
            raise BackupError("too many chunks")
        frame = kind + struct.pack(">I", len(plain) + 16)
        nonce = self.prefix + self.index.to_bytes(8, "big")
        self._raw(frame + self.key.encrypt(nonce, plain, self.header_hash + frame + self.index.to_bytes(8, "big")))
        self.index += 1

    def write(self, value: bytes) -> int:
        self.plain_hash.update(value)
        self.plain_size += len(value)
        self.buffer.extend(value)
        while len(self.buffer) >= CHUNK:
            self._frame(b"D", bytes(self.buffer[:CHUNK]))
            del self.buffer[:CHUNK]
        return len(value)

    def finish(self) -> str:
        if self.buffer:
            self._frame(b"D", bytes(self.buffer))
            self.buffer.clear()
        summary = _json({"chunks": self.index, "bytes": self.plain_size, "sha256": self.plain_hash.hexdigest()})
        self._frame(b"F", summary)
        return self.cipher_hash.hexdigest()


class _CipherReader:
    def __init__(self, stream, private: x25519.X25519PrivateKey):
        self.stream = stream
        self.cipher_hash = hashlib.sha256()
        if self._exact(len(MAGIC)) != MAGIC:
            raise BackupError("invalid backup header")
        length = struct.unpack(">I", self._exact(4))[0]
        if not 0 < length <= 4096:
            raise BackupError("invalid backup header")
        header = self._exact(length)
        value = json.loads(header, object_pairs_hook=_unique_pairs)
        if set(value) != {"version", "chunk", "ephemeral", "salt", "nonce_prefix"} or value["version"] != 1 or value["chunk"] != CHUNK:
            raise BackupError("unsupported backup header")
        ephemeral = base64.b64decode(value["ephemeral"], validate=True)
        salt = base64.b64decode(value["salt"], validate=True)
        self.prefix = base64.b64decode(value["nonce_prefix"], validate=True)
        if len(ephemeral) != 32 or len(salt) != 16 or len(self.prefix) != 4:
            raise BackupError("invalid backup header")
        shared = private.exchange(x25519.X25519PublicKey.from_public_bytes(ephemeral))
        self.key = AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=MAGIC).derive(shared))
        self.header_hash = hashlib.sha256(header).digest()
        self.index = 0
        self.buffer = bytearray()
        self.plain_hash = hashlib.sha256()
        self.plain_size = 0
        self.done = False

    def _exact(self, count: int) -> bytes:
        block = self.stream.read(count)
        if len(block) != count:
            raise BackupError("truncated backup")
        self.cipher_hash.update(block)
        return block

    def _next(self) -> None:
        kind = self._exact(1)
        length_bytes = self._exact(4)
        length = struct.unpack(">I", length_bytes)[0]
        if (kind == b"D" and not 16 <= length <= CHUNK + 16) or (kind == b"F" and not 16 <= length <= 512):
            raise BackupError("invalid backup frame")
        frame = kind + length_bytes
        nonce = self.prefix + self.index.to_bytes(8, "big")
        plain = self.key.decrypt(nonce, self._exact(length), self.header_hash + frame + self.index.to_bytes(8, "big"))
        if kind == b"F":
            summary = json.loads(plain, object_pairs_hook=_unique_pairs)
            if summary != {"chunks": self.index, "bytes": self.plain_size, "sha256": self.plain_hash.hexdigest()} or self.stream.read(1):
                raise BackupError("incomplete backup")
            self.done = True
        else:
            self.index += 1
            self.plain_hash.update(plain)
            self.plain_size += len(plain)
            self.buffer.extend(plain)

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = CHUNK
        while len(self.buffer) < size and not self.done:
            self._next()
        block = bytes(self.buffer[:size])
        del self.buffer[:size]
        return block


def encrypt_tree(source: Path, public_key: Path, output: Path, expected_recipient_sha256: str) -> str:
    source, output = Path(source), Path(output)
    _real_dir(source)
    _real_dir(output.parent)
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise BackupError("output must be new and outside source")
    key, fingerprint = _recipient(public_key)
    if not HEX_SHA256.fullmatch(expected_recipient_sha256) or fingerprint != expected_recipient_sha256:
        raise BackupError("recipient key differs from pinned fingerprint")
    dirs, files, identities = _inventory(source)
    manifest = _json({"version": 1, "directories": dirs, "files": files})
    if len(manifest) > MAX_MANIFEST:
        raise BackupError("manifest too large")
    with tempfile.TemporaryDirectory(prefix=".prime-backup-", dir=output.parent) as temporary:
        staged = Path(temporary) / "ciphertext"
        with staged.open("xb") as stream:
            writer = _CipherWriter(stream, key)
            with tarfile.open(fileobj=writer, mode="w|") as archive:
                meta = tarfile.TarInfo("backup-manifest.json")
                meta.size = len(manifest)
                archive.addfile(meta, io.BytesIO(manifest))
                for name in dirs:
                    info = tarfile.TarInfo("payload/" + name + "/")
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                for name, expected in files.items():
                    info = tarfile.TarInfo("payload/" + name)
                    info.size = expected["size"]
                    reader = _VerifiedFile(source / Path(name), expected, identities[name])
                    try:
                        archive.addfile(info, reader)
                        reader.finish()
                    finally:
                        reader.stream.close()
            digest = writer.finish()
        if _inventory(source) != (dirs, files, identities):
            raise BackupError("source tree changed during archive")
        _publish_new(staged, output, directory=False)
    return digest


def _validate_manifest(value: object) -> tuple[set[str], dict[str, dict]]:
    if not isinstance(value, dict) or set(value) != {"version", "directories", "files"} or value["version"] != 1:
        raise BackupError("invalid manifest")
    dirs, files = value["directories"], value["files"]
    if (not isinstance(dirs, list) or not all(isinstance(name, str) for name in dirs)
            or dirs != sorted(set(dirs)) or not isinstance(files, dict)):
        raise BackupError("invalid manifest")
    names = set()
    for name in [*dirs, *files]:
        _safe_name(name)
        if name.casefold() in names:
            raise BackupError("case-colliding manifest path")
        names.add(name.casefold())
    for name, entry in files.items():
        if not isinstance(entry, dict) or set(entry) != {"size", "sha256"} or type(entry["size"]) is not int or entry["size"] < 0 or not isinstance(entry["sha256"], str) or not HEX_SHA256.fullmatch(entry["sha256"]):
            raise BackupError("invalid manifest file")
    for name in [*dirs, *files]:
        parts = name.split("/")
        if any("/".join(parts[:i]) in files for i in range(1, len(parts))):
            raise BackupError("file used as directory")
        if any("/".join(parts[:i]) not in dirs for i in range(1, len(parts))):
            raise BackupError("undeclared parent directory")
    return set(dirs), files


def restore_tree(ciphertext: Path, private_key: Path, output: Path, expected_sha256: str, password: bytes) -> int:
    ciphertext, output = Path(ciphertext), Path(output)
    if not HEX_SHA256.fullmatch(expected_sha256) or output.exists():
        raise BackupError("expected digest or new output required")
    _private_dir(output.parent)
    if not password:
        raise BackupError("encrypted private key passphrase required")
    digest = hashlib.sha256()
    with ciphertext.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    if digest.hexdigest() != expected_sha256:
        raise BackupError("ciphertext digest differs from pinned value")
    key = serialization.load_pem_private_key(Path(private_key).read_bytes(), password=password)
    if not isinstance(key, x25519.X25519PrivateKey):
        raise BackupError("recovery key must be X25519")
    with tempfile.TemporaryDirectory(prefix=".prime-restore-", dir=output.parent) as temporary:
        _private_dir(Path(temporary))
        staged = Path(temporary) / "data"
        staged.mkdir(mode=0o700)
        _private_dir(staged)
        seen_dirs, seen_files = set(), set()
        with ciphertext.open("rb") as stream:
            reader = _CipherReader(stream, key)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                first = archive.next()
                if first is None or first.name != "backup-manifest.json" or not first.isfile() or first.size > MAX_MANIFEST:
                    raise BackupError("missing manifest")
                manifest = json.loads(archive.extractfile(first).read(), object_pairs_hook=_unique_pairs)
                dirs, files = _validate_manifest(manifest)
                while (member := archive.next()) is not None:
                    if not member.name.startswith("payload/"):
                        raise BackupError("unexpected archive entry")
                    name = _safe_name(member.name.removeprefix("payload/").removesuffix("/"))
                    target = staged / Path(name)
                    if member.isdir() and name in dirs and name not in seen_dirs:
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                        seen_dirs.add(name)
                    elif member.isfile() and name in files and name not in seen_files and member.size == files[name]["size"]:
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        digest = hashlib.sha256()
                        size = 0
                        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                               getattr(os, "O_BINARY", 0), 0o600), "wb") as destination:
                            member_stream = archive.extractfile(member)
                            while block := member_stream.read(CHUNK):
                                size += len(block)
                                digest.update(block)
                                destination.write(block)
                        if size != member.size or digest.hexdigest() != files[name]["sha256"]:
                            raise BackupError("restored file differs from manifest")
                        seen_files.add(name)
                    else:
                        raise BackupError("invalid or duplicate archive entry")
            while reader.read(CHUNK):
                pass
        if (reader.cipher_hash.hexdigest() != expected_sha256 or seen_dirs != dirs
                or seen_files != set(files)):
            raise BackupError("incomplete restore")
        _private_dir(staged)
        _publish_new(staged, output, directory=True)
    return len(seen_files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted fenced-snapshot transport; never read live /data")
    sub = parser.add_subparsers(dest="command", required=True)
    encrypt = sub.add_parser("encrypt")
    encrypt.add_argument("source", type=Path)
    encrypt.add_argument("recipient_public_key", type=Path)
    encrypt.add_argument("ciphertext", type=Path)
    encrypt.add_argument("expected_recipient_sha256")
    fingerprint = sub.add_parser("fingerprint", help="Run on offline device; pin the canonical public-key digest")
    fingerprint.add_argument("recipient_public_key", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("ciphertext", type=Path)
    restore.add_argument("offline_private_key", type=Path)
    restore.add_argument("destination", type=Path)
    restore.add_argument("expected_sha256")
    args = parser.parse_args(argv)
    try:
        if args.command == "fingerprint":
            print("recipient_sha256=" + _recipient(args.recipient_public_key)[1])
        elif args.command == "encrypt":
            print("ciphertext_sha256=" + encrypt_tree(args.source, args.recipient_public_key, args.ciphertext,
                                                      args.expected_recipient_sha256))
        else:
            password = getpass.getpass("Offline key passphrase: ").encode()
            print("restored_files=" + str(restore_tree(args.ciphertext, args.offline_private_key, args.destination, args.expected_sha256, password)))
        return 0
    except Exception:
        print("backup operation failed; no destination published", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
