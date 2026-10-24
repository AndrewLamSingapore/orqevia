"""Credential-free, bounded retrieval from an exact primary-source allowlist.

Retrieved content is source data, never instructions or verified factual truth.
The HTTP payload cannot select a client, transport, header, proxy or executable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

APPROVED_HOSTS = frozenset(
    {
        "docs.docker.com",
        "docs.ollama.com",
        "cdli.earth",
        "www.britishmuseum.org",
        "britishmuseum.org",
        "oracc.museum.upenn.edu",
    }
)
MAX_URL = 2048
MAX_BODY = 256 * 1024
MAX_REDIRECTS = 2
TOTAL_SECONDS = 20
MAX_EXCERPT_WORDS = 150
MAX_EXCERPT_CHARACTERS = 2400
MIMES = frozenset({"text/html", "application/xhtml+xml", "text/plain", "text/markdown", "application/json"})
HEADERS = {
    "Accept": "text/html, application/xhtml+xml, text/plain, text/markdown, application/json",
    "Accept-Encoding": "identity",
    "User-Agent": "ORQEVIA-Research/1.0 (bounded primary-source retrieval)",
}
_TEXT = {"type": "string"}
_URL = {"type": "string", "minLength": 1, "maxLength": MAX_URL, "format": "uri"}
_SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}

CONTRACTS = {
    "f19": {
        "version": "1.1.0",
        "operations": [
            {
                "operation": "fetch_primary_source",
                "input_schema": {
                    "type": "object",
                    "required": ["url"],
                    "additionalProperties": False,
                    "properties": {
                        "url": {
                            **_URL,
                            "pattern": "^[Hh][Tt][Tt][Pp][Ss]://.*$",
                            "description": "HTTPS only, exact approved host, no userinfo, only default/443 port. Redirects undergo the same checks.",
                        }
                    },
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "requested_url",
                        "source_url",
                        "http_status",
                        "retrieved_at",
                        "content_sha256",
                        "body_bytes",
                        "mime_type",
                        "title",
                        "excerpt",
                        "excerpt_words",
                        "excerpt_truncated",
                        "redirects",
                        "classification",
                        "factual_claims_verified",
                        "instructions_may_execute",
                        "paid_provider_called",
                    ],
                    "properties": {
                        "requested_url": _URL,
                        "source_url": _URL,
                        "http_status": {"const": 200},
                        "retrieved_at": {"type": "string", "format": "date-time"},
                        "content_sha256": _SHA,
                        "body_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_BODY},
                        "mime_type": {"enum": sorted(MIMES)},
                        "title": {"type": "string", "maxLength": 256},
                        "excerpt": {"type": "string", "maxLength": MAX_EXCERPT_CHARACTERS},
                        "excerpt_words": {"type": "integer", "minimum": 0, "maximum": MAX_EXCERPT_WORDS},
                        "excerpt_truncated": {"type": "boolean"},
                        "redirects": {
                            "type": "array",
                            "maxItems": MAX_REDIRECTS,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["source_url", "status", "target_url"],
                                "properties": {
                                    "source_url": _URL,
                                    "status": {"enum": [301, 302, 303, 307, 308]},
                                    "target_url": _URL,
                                },
                            },
                        },
                        "classification": {"const": "FETCHED_SOURCE_NOT_FACT_VERIFICATION"},
                        "factual_claims_verified": {"const": False},
                        "instructions_may_execute": {"const": False},
                        "paid_provider_called": {"const": False},
                    },
                },
                "scope": "ACTUAL_BOUNDED_GET_FROM_EXACT_APPROVED_PRIMARY_HTTPS_HOSTS_WITH_SOURCE_DIGEST_AND_EXCERPT",
            }
        ],
        "limitations": [
            "Approved hosts: " + ", ".join(sorted(APPROVED_HOSTS)) + ". No arbitrary hosts or HTTP fallback.",
            "At most two validated redirects, 2048-character URL and 262144 response bytes; identity content encoding only.",
            "Network I/O bounds: connect 3s, read 10s, total operation deadline 20s; no automatic retries.",
            "HTML/plain text/Markdown/JSON only; Markdown is inert text. No PDF, external XML resolution, browser execution or model invocation.",
            "Excerpt is at most 150 whitespace-delimited words and 2400 characters; title is at most 256 characters.",
            "Primary-domain retrieval establishes provenance, not source authenticity beyond normal HTTPS, factual accuracy or cross-source confirmation.",
        ],
    },
}


class ResearchUnavailable(RuntimeError):
    """Sanitized upstream, size, encoding or deadline failure."""


def _url_text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_URL:
        raise ValueError("PRIMARY_SOURCE_URL_INVALID")
    if any(ord(char) < 33 or ord(char) == 127 or char == "\\" for char in value):
        raise ValueError("PRIMARY_SOURCE_URL_INVALID")
    return value


def _approved_url(value):
    """Validate before HTTPX normalization; never let URL cleanup hide authority."""
    value = _url_text(value)
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (
            parsed.scheme != "https"
            or host not in APPROVED_HOSTS
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.netloc.lower() not in {host, host + ":443"}
        ):
            raise ValueError
        # Fragments identify document positions, not a distinct HTTP resource.
        result = str(httpx.URL(urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))))
        if len(result) > MAX_URL:
            raise ValueError
    except (ValueError, TypeError, httpx.InvalidURL):
        raise ValueError("PRIMARY_SOURCE_URL_NOT_APPROVED") from None
    return result


def _plain(value):
    value = "".join(char for char in value if ord(char) >= 32 or char in "\t\r\n")
    return " ".join(value.split())


class _HTMLText(HTMLParser):
    BLOCKED = frozenset({"script", "style", "noscript", "template"})
    BLOCKS = frozenset({"p", "div", "br", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "section", "article"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked, self.parts, self.title = [], [], []
        self.in_head = False
        self.in_title = False
        self.title_seen = False

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKED:
            self.blocked.append(tag)
        if self.blocked:
            return
        if tag == "head":
            self.in_head = True
        elif tag == "title" and not self.title_seen:
            self.in_title = True
        elif tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        if tag == "head":
            self.in_head = False
        elif tag == "title":
            self.in_title = False
            self.title_seen = True
        elif tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.blocked:
            return
        if self.in_title:
            self.title.append(data)
        elif not self.in_head:
            self.parts.append(data)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _json_text(text):
    def constant(_):
        raise ValueError("Non-finite JSON value")

    try:
        value = json.loads(text, object_pairs_hook=_json_pairs, parse_constant=constant)
        stack, nodes = [(value, 0)], 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > 12 or nodes > 10000 or (isinstance(item, float) and not math.isfinite(item)):
                raise ValueError
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        title = value.get("title", "") if isinstance(value, dict) else ""
        rendered = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        rendered.encode("utf-8")
        return rendered, title if isinstance(title, str) else ""
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise ResearchUnavailable("PRIMARY_SOURCE_JSON_INVALID") from None


def _extract(raw, content_type):
    mime = content_type.split(";", 1)[0].strip().lower()
    charset = re.search(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.I)
    charset = charset.group(1).lower() if charset else "utf-8"
    encodings = {
        "utf-8": "utf-8-sig",
        "utf8": "utf-8-sig",
        "us-ascii": "ascii",
        "ascii": "ascii",
        "iso-8859-1": "latin-1",
        "latin-1": "latin-1",
        "windows-1252": "cp1252",
        "cp1252": "cp1252",
    }
    if charset not in encodings or (
        mime == "application/json" and charset not in {"utf-8", "utf8", "us-ascii", "ascii"}
    ):
        raise ResearchUnavailable("PRIMARY_SOURCE_CHARSET_UNSUPPORTED")
    try:
        text = raw.decode(encodings[charset], errors="strict")
    except UnicodeError:
        raise ResearchUnavailable("PRIMARY_SOURCE_TEXT_ENCODING_INVALID") from None
    title = ""
    if mime in {"text/html", "application/xhtml+xml"}:
        parser = _HTMLText()
        try:
            parser.feed(text)
            parser.close()
        except (ValueError, AssertionError):
            raise ResearchUnavailable("PRIMARY_SOURCE_HTML_INVALID") from None
        text, title = "".join(parser.parts), "".join(parser.title)
    elif mime == "application/json":
        text, title = _json_text(text)
    elif mime == "text/markdown":
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
    normalized = _plain(text)
    excerpt = " ".join(normalized.split()[:MAX_EXCERPT_WORDS])
    if len(excerpt) > MAX_EXCERPT_CHARACTERS:
        prefix = excerpt[:MAX_EXCERPT_CHARACTERS]
        excerpt = prefix.rsplit(" ", 1)[0] if " " in prefix else prefix
    return _plain(title)[:256], excerpt, len(excerpt.split()), len(excerpt) < len(normalized)


async def _retrieve(url, transport, seconds):
    deadline = time.monotonic() + seconds
    async with asyncio.timeout(seconds):
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(connect=3, read=10, write=3, pool=3),
            headers=HEADERS,
            auth=None,
            event_hooks={},
            verify=True,
        ) as client:
            original, current, redirects = url, url, []
            for hop in range(MAX_REDIRECTS + 1):
                # Discard even upstream-issued cookies before every request.
                client.cookies.clear()
                async with client.stream("GET", current) as response:
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        if hop == MAX_REDIRECTS:
                            raise ResearchUnavailable("PRIMARY_SOURCE_REDIRECT_LIMIT")
                        location = _url_text(response.headers.get("location", ""))
                        following = _approved_url(urljoin(current, location))
                        redirects.append({"source_url": current, "status": status, "target_url": following})
                        current = following
                        continue
                    if status != 200:
                        raise ResearchUnavailable("PRIMARY_SOURCE_HTTP_STATUS_" + str(status))
                    content_type = response.headers.get("content-type", "")
                    mime = content_type.split(";", 1)[0].strip().lower()
                    if mime not in MIMES:
                        raise ResearchUnavailable("PRIMARY_SOURCE_MIME_UNSUPPORTED")
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise ResearchUnavailable("PRIMARY_SOURCE_ENCODING_UNSUPPORTED")
                    length = response.headers.get("content-length")
                    if length is not None:
                        try:
                            if not 0 <= int(length) <= MAX_BODY:
                                raise ValueError
                        except ValueError:
                            raise ResearchUnavailable("PRIMARY_SOURCE_SIZE_LIMIT") from None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BODY:
                            raise ResearchUnavailable("PRIMARY_SOURCE_SIZE_LIMIT")
                        body.extend(chunk)
                    if not body:
                        raise ResearchUnavailable("PRIMARY_SOURCE_EMPTY_BODY")
                    title, excerpt, words, truncated = _extract(bytes(body), content_type)
                    if time.monotonic() > deadline:
                        raise ResearchUnavailable("PRIMARY_SOURCE_TOTAL_TIMEOUT")
                    return {
                        "requested_url": original,
                        "source_url": str(response.url),
                        "http_status": status,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "content_sha256": hashlib.sha256(body).hexdigest(),
                        "body_bytes": len(body),
                        "mime_type": mime,
                        "title": title,
                        "excerpt": excerpt,
                        "excerpt_words": words,
                        "excerpt_truncated": truncated,
                        "redirects": redirects,
                        "classification": "FETCHED_SOURCE_NOT_FACT_VERIFICATION",
                        "factual_claims_verified": False,
                        "instructions_may_execute": False,
                        "paid_provider_called": False,
                    }


def _fetch_primary_source(url, *, _transport=None, _total_seconds=TOTAL_SECONDS):
    """Private transport/deadline injection is for tests, never an HTTP option."""
    url = _approved_url(url)
    if (
        isinstance(_total_seconds, bool)
        or not isinstance(_total_seconds, (int, float))
        or not 0 < _total_seconds <= TOTAL_SECONDS
    ):
        raise ValueError("PRIMARY_SOURCE_DEADLINE_INVALID")
    try:
        return asyncio.run(_retrieve(url, _transport, _total_seconds))
    except TimeoutError:
        raise ResearchUnavailable("PRIMARY_SOURCE_TOTAL_TIMEOUT") from None
    except httpx.TimeoutException:
        raise ResearchUnavailable("PRIMARY_SOURCE_NETWORK_TIMEOUT") from None
    except httpx.HTTPError:
        raise ResearchUnavailable("PRIMARY_SOURCE_NETWORK_UNAVAILABLE") from None


def execute(fabric_id, operation, payload):
    if fabric_id != "f19" or operation != "fetch_primary_source":
        raise ValueError("PRIMARY_SOURCE_OPERATION_UNSUPPORTED")
    if not isinstance(payload, dict) or set(payload) != {"url"}:
        raise ValueError("PRIMARY_SOURCE_FIELDS_INVALID")
    return _fetch_primary_source(payload["url"])
