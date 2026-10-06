"""Encrypt a *fenced copy* for off-host storage; restore only to a new tree.

The recipient's X25519 private key belongs on an offline recovery device, never
on ABEX. A pinned ciphertext SHA-256 is required for restore because anyone with
the public key can create a different encrypted bundle. This tool cannot create
or prove a production write fence, private destination ACL, or Azure upload.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import io
import json
import os
import re
import stat
import struct
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
           part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
           for part in parts):
        raise BackupError("unsafe archive path")
    return name


def _real_dir(path: Path) -> Path:
    if not path.is_dir() or path.is_symlink() or path.is_junction() or (path.lstat().st_file_attributes if os.name == "nt" else 0) & REPARSE:
        raise BackupError("expected a real directory")
    return path.resolve()


def _inventory(root: Path) -> tuple[list[str], dict[str, dict]]:
    _real_dir(root)
    dirs: list[str] = []
    files: dict[str, dict] = {}
    folded: set[str] = set()

    def visit(folder: Path, prefix: str = "") -> None:
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            name = _safe_name(f"{prefix}/{entry.name}" if prefix else entry.name)
            if name.casefold() in folded:
                raise BackupError("case-colliding archive path")
            folded.add(name.casefold())
            info = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE:
                raise BackupError("links and reparse points are forbidden")
            if stat.S_ISDIR(info.st_mode):
                dirs.append(name)
                visit(Path(entry.path), name)
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(entry.path, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if opened.st_size != info.st_size or (info.st_ino and opened.st_ino != info.st_ino):
                        raise BackupError("source changed during inventory")
                    for block in iter(lambda: stream.read(CHUNK), b""):
                        digest.update(block)
                files[name] = {"size": info.st_size, "sha256": digest.hexdigest()}
            else:
                raise BackupError("unsupported archive entry")

    visit(root)
    return sorted(dirs), dict(sorted(files.items()))


class _VerifiedFile:
    def __init__(self, path: Path, expected: dict):
        self.stream = path.open("rb")
        self.expected = expected
        self.digest = hashlib.sha256()
        self.count = 0
        if os.fstat(self.stream.fileno()).st_size != expected["size"]:
            self.stream.close()
            raise BackupError("source changed before archive")

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        self.digest.update(block)
        self.count += len(block)
        return block

    def finish(self) -> None:
        extra = self.stream.read(1)
        self.stream.close()
        if extra or self.count != self.expected["size"] or self.digest.hexdigest() != self.expected["sha256"]:
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


def encrypt_tree(source: Path, public_key: Path, output: Path) -> str:
    source, output = Path(source), Path(output)
    _real_dir(source)
    _real_dir(output.parent)
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise BackupError("output must be new and outside source")
    key = serialization.load_pem_public_key(Path(public_key).read_bytes())
    if not isinstance(key, x25519.X25519PublicKey):
        raise BackupError("recipient must be an X25519 public key")
    dirs, files = _inventory(source)
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
                    reader = _VerifiedFile(source / Path(name), expected)
                    try:
                        archive.addfile(info, reader)
                        reader.finish()
                    finally:
                        reader.stream.close()
            digest = writer.finish()
        if _inventory(source) != (dirs, files):
            raise BackupError("source tree changed during archive")
        if output.exists():
            raise BackupError("output appeared during encryption")
        staged.rename(output)
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


def restore_tree(ciphertext: Path, private_key: Path, output: Path, expected_sha256: str, password: bytes | None = None) -> int:
    ciphertext, output = Path(ciphertext), Path(output)
    if not HEX_SHA256.fullmatch(expected_sha256) or output.exists():
        raise BackupError("expected digest or new output required")
    _real_dir(output.parent)
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
        staged = Path(temporary) / "data"
        staged.mkdir()
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
                        target.mkdir(parents=True, exist_ok=True)
                        seen_dirs.add(name)
                    elif member.isfile() and name in files and name not in seen_files and member.size == files[name]["size"]:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        digest = hashlib.sha256()
                        size = 0
                        with target.open("xb") as destination:
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
                or seen_files != set(files) or output.exists()):
            raise BackupError("incomplete restore")
        staged.rename(output)
    return len(seen_files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted fenced-snapshot transport; never read live /data")
    sub = parser.add_subparsers(dest="command", required=True)
    encrypt = sub.add_parser("encrypt")
    encrypt.add_argument("source", type=Path)
    encrypt.add_argument("recipient_public_key", type=Path)
    encrypt.add_argument("ciphertext", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("ciphertext", type=Path)
    restore.add_argument("offline_private_key", type=Path)
    restore.add_argument("destination", type=Path)
    restore.add_argument("expected_sha256")
    restore.add_argument("--ask-passphrase", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "encrypt":
            print("ciphertext_sha256=" + encrypt_tree(args.source, args.recipient_public_key, args.ciphertext))
        else:
            password = getpass.getpass("Offline key passphrase: ").encode() if args.ask_passphrase else None
            print("restored_files=" + str(restore_tree(args.ciphertext, args.offline_private_key, args.destination, args.expected_sha256, password)))
        return 0
    except Exception:
        print("backup operation failed; no destination published", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
