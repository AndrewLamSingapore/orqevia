"""Controlled internet research gateway - advisory only, fail closed.

Never fetches without an explicit domain allowlist. HTTPS only, bounded bytes,
bounded redirects, no credentials, no automatic execution. Results are
caller-visible evidence, never authority.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


SCHEMA = "orqevia.internet-gateway.v1"
MAX_BYTES = 65536
MAX_REDIRECTS = 3
_ALLOWLIST_ENV = "ORQEVIA_RESEARCH_ALLOWLIST"


def _allowlist() -> frozenset[str]:
    raw = os.getenv(_ALLOWLIST_ENV, "").strip()
    return frozenset(
        part.strip().lower()
        for part in raw.split(",")
        if part.strip() and re.fullmatch(r"[a-z0-9.-]{1,253}", part.strip().lower())
    )


def _allowed(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.hostname.lower() in _allowlist()
    )


def fetch_text(url: str, *, max_bytes: int = MAX_BYTES, timeout: int = 10) -> dict:
    """One bounded advisory fetch. Errors are classified, never leaked as text."""
    if not isinstance(url, str) or not url or not _allowed(url):
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "ALLOWLIST_DENIED",
            "authoritative": False,
            "execution": "ADVISORY_ONLY",
        }
    if not 1 <= max_bytes <= MAX_BYTES or not 1 <= timeout <= 30:
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "INVALID_BOUNDS",
            "authoritative": False,
            "execution": "ADVISORY_ONLY",
        }
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            request = urllib.request.Request(current, headers={"User-Agent": "orqevia-research-gateway/1"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                final = response.geturl()
                if not _allowed(final):
                    return {
                        "schema_version": SCHEMA,
                        "ok": False,
                        "reason": "REDIRECT_ALLOWLIST_DENIED",
                        "authoritative": False,
                        "execution": "ADVISORY_ONLY",
                    }
                if response.status != 200:
                    return {
                        "schema_version": SCHEMA,
                        "ok": False,
                        "reason": "HTTP_" + str(response.status),
                        "authoritative": False,
                        "execution": "ADVISORY_ONLY",
                    }
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    return {
                        "schema_version": SCHEMA,
                        "ok": False,
                        "reason": "SIZE_LIMIT_EXCEEDED",
                        "authoritative": False,
                        "execution": "ADVISORY_ONLY",
                    }
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    return {
                        "schema_version": SCHEMA,
                        "ok": False,
                        "reason": "NON_UTF8_CONTENT",
                        "authoritative": False,
                        "execution": "ADVISORY_ONLY",
                    }
                return {
                    "schema_version": SCHEMA,
                    "ok": True,
                    "url": final,
                    "status": response.status,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "text": text,
                    "provenance": "CONTROLLED_INTERNET_GATEWAY",
                    "authoritative": False,
                    "execution": "ADVISORY_ONLY",
                }
    except urllib.error.HTTPError as exc:
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "HTTP_" + str(exc.code),
            "authoritative": False,
            "execution": "ADVISORY_ONLY",
        }
    except (urllib.error.URLError, OSError, ValueError):
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "FETCH_UNAVAILABLE",
            "authoritative": False,
            "execution": "ADVISORY_ONLY",
        }


def capability_summary() -> dict:
    return {
        "schema_version": SCHEMA,
        "status": "QUALIFIED",
        "authority": "ADVISORY_ONLY",
        "allowlist_configured": bool(_allowlist()),
        "max_bytes": MAX_BYTES,
        "max_redirects": MAX_REDIRECTS,
        "credentials_accepted": False,
    }
