"""Authorized HTTPS catalogue retrieval and declarative, non-executable extraction."""

from dataclasses import dataclass
from concurrent.futures import Future, TimeoutError as FutureTimeout
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import math
import re
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .contracts import ExtractionConfig


class QualityError(ValueError):
    def __init__(self, reason, *, observed_fields=()):
        super().__init__(reason)
        self.observed_fields = sorted(set(observed_fields))[:32]


class RetrievalError(RuntimeError):
    def __init__(self, code, *, retryable=False, bytes_read=0, retry_after=0):
        super().__init__(code)
        self.retryable, self.bytes_read, self.retry_after = retryable, bytes_read, retry_after


@dataclass(frozen=True)
class Source:
    id: str
    urls: tuple[str, ...]
    owners: tuple[str, ...]
    terms_reference: str
    allow_private: bool = False
    min_interval_seconds: float = 1

    def __post_init__(self):
        if type(self.allow_private) is not bool or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.id):
            raise ValueError("valid source identity and boolean private-network permission required")
        if not self.urls or len(self.urls) > 100 or not self.owners or not self.terms_reference:
            raise ValueError("source URLs, authorized owners and terms permission required")
        origins = set()
        for url in self.urls:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or "\\" in url
                or parsed.path.startswith("//")
            ):
                raise ValueError("explicit HTTPS catalogue URLs without credentials or queries required")
            origins.add((parsed.hostname, parsed.port or 443))
        if len(origins) != 1 or not 0 <= self.min_interval_seconds <= 86400:
            raise ValueError("one source origin and finite source interval required")

    @property
    def origin(self):
        parsed = urlsplit(self.urls[0])
        return f"https://{parsed.hostname.lower()}:{parsed.port or 443}"

    def public(self):
        return {
            "id": self.id,
            "urls": self.urls,
            "terms_reference": self.terms_reference,
            "controlled_private_source": self.allow_private,
            "min_interval_seconds": self.min_interval_seconds,
        }


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address, context, timeout):
        super().__init__(host, port, context=context, timeout=timeout)
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class HTTPSFetcher:
    """Pinned DNS address, verified hostname, no proxies, redirects or plaintext fallback."""

    def __init__(self, *, ca_file=None):
        self.context = ssl.create_default_context(cafile=ca_file)
        self.resolving, self.resolver_lock = None, threading.Lock()

    def addresses(self, host, port, timeout):
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            pass
        with self.resolver_lock:
            if self.resolving is not None and not self.resolving.done():
                raise RetrievalError("DNS_BUSY", retryable=True, retry_after=1)
            future = Future()
            self.resolving = future

            def resolve():
                try:
                    future.set_result(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM))
                except Exception as exc:
                    future.set_exception(exc)

            threading.Thread(target=resolve, name="pocket-dns", daemon=True).start()
        try:
            return sorted({row[4][0] for row in future.result(timeout=max(0.001, timeout))})
        except FutureTimeout:
            raise RetrievalError("DNS_TIMEOUT", retryable=True) from None

    def _get(self, source, url, *, limit, deadline):
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port or 443
        try:
            addresses = self.addresses(host, port, min(5, max(0.001, deadline - time.monotonic())))
            if not addresses or (
                not source.allow_private and any(not ipaddress.ip_address(address).is_global for address in addresses)
            ):
                raise RetrievalError("SOURCE_ADDRESS_DENIED")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RetrievalError("TIME_BUDGET_EXHAUSTED")
            connection = _PinnedHTTPS(host, port, addresses[0], self.context, min(15, remaining))

            def abort():
                if connection.sock:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                connection.close()

            timer = threading.Timer(remaining, abort)
            timer.daemon = True
            timer.start()
            body = bytearray()
            try:
                connection.request(
                    "GET",
                    parsed.path or "/",
                    headers={
                        "User-Agent": "ORQEVIA-ActivityPocket/1.0",
                        "Accept": "text/html,text/plain",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                if response.status in (429, 503) or response.status >= 500:
                    retry = response.getheader("Retry-After", "1")
                    retry = min(86400, int(retry)) if retry.isdigit() else 60
                    raise RetrievalError("SOURCE_TEMPORARILY_UNAVAILABLE", retryable=True, retry_after=retry)
                if response.status != 200:
                    raise RetrievalError("SOURCE_HTTP_" + str(response.status))
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise RetrievalError("UNSUPPORTED_CONTENT_ENCODING")
                media = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                if media not in {"text/html", "text/plain"}:
                    raise RetrievalError("UNSUPPORTED_CONTENT_TYPE")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RetrievalError("TIME_BUDGET_EXHAUSTED", bytes_read=len(body))
                    if connection.sock:
                        connection.sock.settimeout(min(15, remaining))
                    chunk = response.read1(min(16384, max(1, limit + 1 - len(body))))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > limit:
                        raise RetrievalError("BYTE_BUDGET_EXHAUSTED", bytes_read=limit)
                try:
                    return bytes(body).decode("utf-8"), len(body)
                except UnicodeDecodeError:
                    raise RetrievalError("UNSUPPORTED_TEXT_ENCODING", bytes_read=len(body)) from None
            except (OSError, http.client.HTTPException) as exc:
                raise RetrievalError(type(exc).__name__, retryable=True, bytes_read=len(body)) from None
            finally:
                timer.cancel()
                connection.close()
        except (OSError, ssl.SSLError) as exc:
            raise RetrievalError(type(exc).__name__, retryable=True) from None

    def fetch(self, source, url, *, max_bytes, wall_seconds, robots_cache=None, save_robots=None, clock=time.time):
        if url not in source.urls:
            raise PermissionError("URL outside trusted source allowlist")
        parsed = urlsplit(url)
        deadline = time.monotonic() + wall_seconds
        robots_url = f"https://{parsed.netloc}/robots.txt"
        cached = (
            robots_cache is not None
            and robots_cache.get("origin") == source.origin
            and robots_cache.get("expires_at", 0) > clock()
        )
        robots_bytes = 0
        if cached:
            robots = robots_cache["body"]
        else:
            try:
                robots, robots_bytes = self._get(source, robots_url, limit=min(65536, max_bytes), deadline=deadline)
            except RetrievalError as exc:
                if str(exc) == "SOURCE_HTTP_404":
                    robots, robots_bytes = "", 0
                else:
                    raise
        rules = RobotFileParser()
        rules.parse(robots.splitlines())
        if not rules.can_fetch("ORQEVIA-ActivityPocket", url):
            raise RetrievalError("ROBOTS_DENIED", bytes_read=robots_bytes)
        delay = rules.crawl_delay("ORQEVIA-ActivityPocket") or 0
        request_rate = rules.request_rate("ORQEVIA-ActivityPocket")
        if request_rate:
            delay = max(delay, request_rate.seconds / request_rate.requests)
        delay = max(delay, source.min_interval_seconds)
        if not cached:
            robots_cache = {
                "origin": source.origin,
                "body": robots,
                "next_at": clock() + delay,
                "expires_at": clock() + max(300, delay + 60),
            }
            if save_robots:
                save_robots(robots_cache)
        wait = max(0, robots_cache["next_at"] - clock())
        if wait:
            if deadline - time.monotonic() <= wait:
                raise RetrievalError(
                    "SOURCE_RATE_RETRY", retryable=True, bytes_read=robots_bytes, retry_after=math.ceil(wait)
                )
            time.sleep(wait)  # Source permission, not a deployment guard or inference queue delay.
        if robots_bytes >= max_bytes:
            raise RetrievalError("BYTE_BUDGET_EXHAUSTED", bytes_read=robots_bytes)
        try:
            body, size = self._get(source, url, limit=max_bytes - robots_bytes, deadline=deadline)
        except RetrievalError as exc:
            exc.bytes_read += robots_bytes
            raise
        if save_robots:
            save_robots(None)  # One page per permission snapshot; next page refreshes directives.
        return {
            "body": body,
            "bytes": size + robots_bytes,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "source_url": url,
            "source_id": source.id,
            "next_interval_seconds": max(source.min_interval_seconds, delay),
        }


class _CatalogueParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.stack, self.current = [], [], None
        self.fields, self.blocked = set(), 0

    def handle_starttag(self, tag, attrs):
        if len(self.stack) >= 128 or len(self.items) >= 10000:
            raise QualityError("DOCUMENT_STRUCTURE_BUDGET_EXHAUSTED")
        attrs = dict(attrs)
        if tag in {"script", "style", "template"}:
            self.blocked += 1
        field = attrs.get("data-field")
        if field and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", field) and not self.blocked:
            self.fields.add(field)
        if tag == "article" and not self.blocked:
            if self.current is not None:
                raise QualityError("NESTED_RECORD")
            self.current = {"id": attrs.get("data-id", ""), "fields": {}, "currency": attrs.get("data-currency", "USD")}
        if tag not in {
            "br",
            "hr",
            "img",
            "meta",
            "link",
            "input",
            "wbr",
            "source",
            "area",
            "embed",
            "param",
            "col",
            "base",
        }:
            self.stack.append((tag, field if not self.blocked else None))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"}:
            self.blocked = max(0, self.blocked - 1)
        if tag == "article" and self.current is not None and not self.blocked:
            self.items.append(self.current)
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        if self.current is not None and not self.blocked:
            field = next((value for _, value in reversed(self.stack) if value), None)
            if field:
                previous = self.current["fields"].get(field, "")
                if len(previous) + len(text) > 512:
                    raise QualityError("FIELD_CONTRACT_TOO_LARGE", observed_fields=self.fields)
                self.current["fields"][field] = previous + text


def extract(body, config: ExtractionConfig):
    parser = _CatalogueParser()
    parser.feed(body)
    parser.close()
    records, identifiers = [], set()
    if not parser.items or parser.current is not None:
        raise QualityError("NO_COMPLETE_RECORDS", observed_fields=parser.fields)
    for item in parser.items:
        fields = item["fields"]
        title = next((fields[key].strip() for key in config.title_fields if fields.get(key, "").strip()), "")
        price = next((fields[key].strip() for key in config.price_fields if fields.get(key, "").strip()), "")
        if not title or not price:
            raise QualityError("LAYOUT_FIELDS_MISSING", observed_fields=parser.fields)
        # Reference scope is non-personal public catalogue records only.
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item["id"])
            or item["id"] in identifiers
            or len(title) > 200
            or "@" in title
            or re.search(r"\b\d[\d ()+-]{7,}\d\b", title)
            or item["currency"] not in {"USD", "SGD", "EUR"}
        ):
            raise QualityError("RECORD_CONTRACT_FAILED", observed_fields=parser.fields)
        try:
            amount = Decimal(price)
            if not amount.is_finite() or not 0 <= amount <= 1_000_000 or amount != amount.quantize(Decimal(".01")):
                raise InvalidOperation()
        except InvalidOperation:
            raise QualityError("PRICE_CONTRACT_FAILED", observed_fields=parser.fields) from None
        identifiers.add(item["id"])
        records.append(
            {"product_id": item["id"], "title": title, "price": format(amount, ".2f"), "currency": item["currency"]}
        )
    return records
