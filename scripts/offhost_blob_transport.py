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


def encrypted_file(token: str, path: Path, expected_sha256: str, *, client_factory=_blob_client) -> dict:
    """Upload only an already encrypted PRIME bundle, then read it back."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise TransportError("Expected ciphertext SHA-256 is required")
    if path.is_symlink():
        raise TransportError("Ciphertext path must not be a link")
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size <= len(MAGIC):
            raise TransportError("Ciphertext must be a nonempty regular file")
        if os.name == "nt" and before.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise TransportError("Ciphertext path must not be a reparse point")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            if stream.read(len(MAGIC)) != MAGIC:
                raise TransportError("Input is not a PRIME encrypted bundle")
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise TransportError("Ciphertext does not match the pinned SHA-256")
        if path.stat() != before:
            raise TransportError("Ciphertext changed during preflight")
        name = f"encrypted/{expected_sha256}.primebkp"
        with path.open("rb") as stream:
            result = _transfer(_client(client_factory, token, name), stream, before.st_size, expected_sha256, name)
        if path.stat() != before:
            raise TransportError("Ciphertext changed during transfer")
        return result
    except OSError:
        raise TransportError("Ciphertext file could not be read") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload and independently read back a synthetic canary or PRIME ciphertext")
    parser.add_argument("mode", choices=("canary", "encrypted-file"))
    parser.add_argument("path", nargs="?", type=Path, help="PRIMEBKP1 ciphertext path (encrypted-file only)")
    parser.add_argument("--expected-sha256", help="Previously pinned ciphertext digest (encrypted-file only)")
    args = parser.parse_args()
    if args.mode == "canary" and (args.path is not None or args.expected_sha256 is not None):
        parser.error("canary takes no file or digest")
    if args.mode == "encrypted-file" and (args.path is None or args.expected_sha256 is None):
        parser.error("encrypted-file requires a path and previously pinned SHA-256")
    if sys.stdin.isatty():
        raise SystemExit("SAS must arrive on stdin from a local clipboard pipeline")
    try:
        token = sys.stdin.read(MAX_SAS_CHARS + 2)
        if len(token) > MAX_SAS_CHARS + 1:
            raise TransportError("SAS input is too long")
        result = canary(token) if args.mode == "canary" else encrypted_file(token, args.path, args.expected_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Include neither SDK exception messages nor SAS input in terminal output.
        print("Blob transport failed; no success receipt was issued", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
