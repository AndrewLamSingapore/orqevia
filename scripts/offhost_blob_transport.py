"""Bounded Azure Blob transport for synthetic canaries and PRIME ciphertext.

The SAS arrives on stdin (for example, a local clipboard pipeline), never in an
argument, URL, log, or returned record. This does not create a backup or prove a
production fence/restore. Runtime requires the official azure-storage-blob SDK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl


ACCOUNT = "abexrecovery20261006"
CONTAINER = "abex-recovery"
ACCOUNT_URL = f"https://{ACCOUNT}.blob.core.windows.net"
MAGIC = b"PRIMEBKP1"
CANARY_BYTES = 64 * 1024
MAX_SAS_CHARS = 4096
MIN_REMAINING = timedelta(minutes=5)
MAX_REMAINING = timedelta(hours=1)
MAX_DOWNLOAD_CHUNK = 4 * 1024 * 1024
MAX_CIPHERTEXT_BYTES = 16 * 1024 * 1024 * 1024


class TransportError(ValueError):
    """A non-secret, operator-safe transport failure."""


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise TransportError("SAS has an invalid UTC timestamp") from None


def validate_sas(raw: str, *, now: datetime | None = None) -> str:
    """Validate a narrowly scoped SAS query without ever returning decoded fields."""
    token = raw.strip().removeprefix("?")
    if (not token or len(token) > MAX_SAS_CHARS or "://" in token or "#" in token
            or any(ord(char) < 32 or ord(char) == 127 for char in token)):
        raise TransportError("SAS must be a short query string, not a URL")
    try:
        pairs = parse_qsl(
            token, keep_blank_values=True, strict_parsing=True,
            max_num_fields=32, encoding="utf-8", errors="strict",
        )
    except ValueError:
        raise TransportError("SAS query is malformed") from None
    fields = dict(pairs)
    if (len(fields) != len(pairs) or "ss" in fields or "srt" in fields or "si" in fields
            or any(any(ord(char) < 32 or ord(char) == 127 for char in value)
                   for value in fields.values())):
        raise TransportError("SAS scope is ambiguous or too broad")
    if fields.get("sr") != "c" or fields.get("sp") != "rcw":
        raise TransportError("SAS must be container-scoped with only read/create/write")
    if fields.get("spr") != "https" or not fields.get("sv") or not fields.get("sig"):
        raise TransportError("SAS requires HTTPS, version, and signature")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = _utc(fields.get("se", ""))
    if not MIN_REMAINING <= expires - current <= MAX_REMAINING:
        raise TransportError("SAS expiry must be 5 to 60 minutes from now")
    if "st" in fields and _utc(fields["st"]) > current:
        raise TransportError("SAS is not yet valid")
    return token


def _blob_client(token: str, name: str):
    from azure.storage.blob import BlobClient  # type: ignore[import-not-found]

    return BlobClient(
        account_url=ACCOUNT_URL, container_name=CONTAINER,
        blob_name=name, credential=token,
        max_single_get_size=MAX_DOWNLOAD_CHUNK,
        max_chunk_get_size=MAX_DOWNLOAD_CHUNK,
    )


def _client(factory, token: str, name: str):
    try:
        return factory(validate_sas(token), name)
    except TransportError:
        raise
    except Exception:
        # SDK constructor errors may contain its credential-bearing URL.
        raise TransportError("Azure client unavailable") from None


def _transfer(client, source, size: int, expected_sha256: str, name: str) -> dict:
    try:
        client.upload_blob(source, blob_type="BlockBlob", length=size, overwrite=False)
        actual = hashlib.sha256()
        count = 0
        for chunk in client.download_blob().chunks():
            if not isinstance(chunk, (bytes, bytearray, memoryview)) or not 0 < len(chunk) <= MAX_DOWNLOAD_CHUNK:
                raise TransportError("Azure returned an invalid readback chunk")
            if count + len(chunk) > size:
                raise TransportError("Azure readback exceeded uploaded ciphertext size")
            actual.update(chunk)
            count += len(chunk)
    except Exception:
        # SDK exceptions can include a SAS-bearing request URL. Never relay them.
        raise TransportError("Azure upload or readback failed") from None
    if count != size or actual.hexdigest() != expected_sha256:
        raise TransportError("Independent Azure readback hash mismatch")
    return {
        "account": ACCOUNT, "container": CONTAINER, "blob": name,
        "bytes": size, "sha256": expected_sha256,
        "verification": "DOWNLOAD_SHA256_MATCH",
    }


def canary(token: str, *, client_factory=_blob_client, payload: bytes | None = None) -> dict:
    data = secrets.token_bytes(CANARY_BYTES) if payload is None else payload
    name = f"canary/{uuid.uuid4().hex}.bin"
    return _transfer(_client(client_factory, token, name), data, len(data), hashlib.sha256(data).hexdigest(), name)


def _file_identity(info) -> tuple[int, int, int, int, int]:
    # Reading may update atime; it is not a change to ciphertext identity.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)


def _same_open_file(path: Path, stream, expected: tuple[int, int, int, int, int]) -> bool:
    return (not path.is_symlink() and _file_identity(os.fstat(stream.fileno())) == expected
            and _file_identity(path.stat()) == expected)


def encrypted_file(token: str, path: Path, expected_sha256: str, *, client_factory=_blob_client) -> dict:
    """Upload only an already encrypted PRIME bundle, then read it back."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise TransportError("Expected ciphertext SHA-256 is required")
    if path.is_symlink():
        raise TransportError("Ciphertext path must not be a link")
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            identity = _file_identity(before)
            if (not stat.S_ISREG(before.st_mode) or not len(MAGIC) < before.st_size <= MAX_CIPHERTEXT_BYTES):
                raise TransportError("Ciphertext must be a bounded nonempty regular file")
            if os.name == "nt" and before.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise TransportError("Ciphertext path must not be a reparse point")
            if not _same_open_file(path, stream, identity):
                raise TransportError("Ciphertext path changed before preflight")
            digest = hashlib.sha256()
            if stream.read(len(MAGIC)) != MAGIC:
                raise TransportError("Input is not a PRIME encrypted bundle")
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise TransportError("Ciphertext does not match the pinned SHA-256")
            if not _same_open_file(path, stream, identity):
                raise TransportError("Ciphertext changed during preflight")
            stream.seek(0)
            name = f"encrypted/{expected_sha256}.primebkp"
            result = _transfer(_client(client_factory, token, name), stream, before.st_size, expected_sha256, name)
            if not _same_open_file(path, stream, identity):
                raise TransportError("Ciphertext changed during transfer")
            return result
    except OSError:
        raise TransportError("Ciphertext file could not be read") from None


def _check_real_directory_chain(directory: Path) -> None:
    if not directory.is_absolute() or ".." in directory.parts:
        raise TransportError("Isolated directory must be an absolute, direct path")
    try:
        for part in (directory, *directory.parents):
            info = part.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or (os.name == "nt" and info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)):
                raise TransportError("Isolated directory chain contains a link or reparse point")
    except OSError:
        raise TransportError("Isolated directory chain is unavailable") from None


def _same_isolated_directory(directory: Path, created) -> bool:
    if created is None:
        return False
    try:
        _check_real_directory_chain(directory)
        current = directory.lstat()
        return (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)
    except (OSError, TransportError):
        return False


def download_ciphertext(token: str, blob_name: str, expected_sha256: str, new_directory: Path,
                        *, client_factory=_blob_client) -> dict:
    """Download pinned ciphertext into a new directory, publishing only after hash verification."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise TransportError("Expected ciphertext SHA-256 is required")
    if blob_name != f"encrypted/{expected_sha256}.primebkp":
        raise TransportError("Blob name must match the pinned ciphertext SHA-256")
    new_directory = Path(new_directory)
    _check_real_directory_chain(new_directory.parent)
    client = _client(client_factory, token, blob_name)
    staged = None
    staged_identity = None
    created_directory = False
    created = None
    published = False
    try:
        os.mkdir(new_directory, 0o700)  # exclusive: this run owns the isolated directory
        created_directory = True
        created = new_directory.lstat()
        _check_real_directory_chain(new_directory)
        final = new_directory / f"{expected_sha256}.primebkp"
        digest = hashlib.sha256()
        prefix = bytearray()
        count = 0
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".prime-ciphertext-", dir=new_directory,
                                         delete=False) as output:
            staged = Path(output.name)
            for chunk in client.download_blob(max_concurrency=1).chunks():
                if not isinstance(chunk, (bytes, bytearray, memoryview)) or not 0 < len(chunk) <= MAX_DOWNLOAD_CHUNK:
                    raise TransportError("Azure returned an invalid ciphertext chunk")
                count += len(chunk)
                if count > MAX_CIPHERTEXT_BYTES:
                    raise TransportError("Ciphertext exceeds the bounded download limit")
                if len(prefix) < len(MAGIC):
                    prefix.extend(chunk[:len(MAGIC) - len(prefix)])
                digest.update(chunk)
                if output.write(chunk) != len(chunk):
                    raise TransportError("Ciphertext staging write was incomplete")
            output.flush()
            os.fsync(output.fileno())
            stage_stat = os.fstat(output.fileno())
            staged_identity = (stage_stat.st_dev, stage_stat.st_ino)
            if stage_stat.st_size != count:
                raise TransportError("Staged ciphertext size does not match download")
        if count <= len(MAGIC) or bytes(prefix) != MAGIC or digest.hexdigest() != expected_sha256:
            raise TransportError("Downloaded ciphertext failed format or SHA-256 verification")
        if not _same_isolated_directory(new_directory, created):
            raise TransportError("Isolated directory changed during download")
        staged_info = staged.lstat()
        if ((staged_info.st_dev, staged_info.st_ino) != staged_identity
                or staged_info.st_size != count
                or not stat.S_ISREG(staged_info.st_mode)
                or (os.name == "nt" and staged_info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            raise TransportError("Temporary ciphertext path changed before publication")
        os.link(staged, final)  # atomic no-clobber; rename could replace on POSIX
        published = True
        staged.unlink()
        staged = None
        return {
            "account": ACCOUNT, "container": CONTAINER, "blob": blob_name,
            "bytes": count, "sha256": expected_sha256, "path": str(final),
            "verification": "CIPHERTEXT_DOWNLOAD_SHA256_MATCH",
        }
    except TransportError:
        raise
    except Exception:
        # Never forward SDK exceptions: a request URL may include the SAS.
        raise TransportError("Azure ciphertext download or publication failed") from None
    finally:
        same_directory = created_directory and _same_isolated_directory(new_directory, created)
        if same_directory and staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass  # only an unverified ciphertext stage may remain
        if same_directory and not published:
            try:
                new_directory.rmdir()  # remove only this run's empty directory
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Transport a synthetic canary or pinned PRIME ciphertext")
    parser.add_argument("mode", choices=("canary", "encrypted-file", "download-ciphertext"))
    parser.add_argument("path", nargs="?", type=Path, help="ciphertext file or NEW isolated download directory")
    parser.add_argument("--expected-sha256", help="Previously pinned ciphertext digest")
    parser.add_argument("--blob-name", help="Known encrypted/<sha256>.primebkp name for download")
    args = parser.parse_args()
    if args.mode == "canary" and (args.path is not None or args.expected_sha256 is not None or args.blob_name is not None):
        parser.error("canary takes no file, blob name, or digest")
    if args.mode == "encrypted-file" and (args.path is None or args.expected_sha256 is None or args.blob_name is not None):
        parser.error("encrypted-file requires a path and previously pinned SHA-256")
    if args.mode == "download-ciphertext" and (args.path is None or args.expected_sha256 is None or args.blob_name is None):
        parser.error("download-ciphertext requires a NEW directory, blob name, and pinned SHA-256")
    if sys.stdin.isatty():
        raise SystemExit("SAS must arrive on stdin from a local clipboard pipeline")
    try:
        token = sys.stdin.read(MAX_SAS_CHARS + 2)
        if len(token) > MAX_SAS_CHARS + 1:
            raise TransportError("SAS input is too long")
        if args.mode == "canary":
            result = canary(token)
        elif args.mode == "encrypted-file":
            result = encrypted_file(token, args.path, args.expected_sha256)
        else:
            result = download_ciphertext(token, args.blob_name, args.expected_sha256, args.path)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Include neither SDK exception messages nor SAS input in terminal output.
        print("Blob transport failed; no success receipt was issued", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
