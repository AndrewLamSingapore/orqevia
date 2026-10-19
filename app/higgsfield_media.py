"""Optional Higgsfield media provider.

Production generation uses the documented asynchronous REST API. The installed
Higgsfield CLI is treated as a bounded, read-only discovery surface and is never
used as a general command runner. This module is not registered as an agent tool
and no caller can fall through from this provider to an unrelated model.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from . import media_generation as media_generation_contract
from . import secret_refs as secret_refs_contract
from .action_records import ActionRecord, action_ledger
from .media_generation import (
    TERMINAL_STATUSES,
    MediaEstimate,
    MediaJob,
    MediaJobRequest,
    MediaJobStore,
    MediaProviderError,
    decimal_value,
    utcnow,
)
from .observability import record_counter, span, trace_headers
from .secret_refs import SecretUnavailable, resolve_secret


API_BASE_URL = "https://api.higgsfield.ai"
VALIDATION_FINGERPRINT_CONTEXT = b"orqevia.higgsfield-provider-validation.v1\0"
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z")
_CORRELATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_CONTENT_TYPE = re.compile(r"(?:image/(?:jpeg|jpg|png|webp|gif)|audio/(?:wav|x-wav)|video/mp4)\Z")
_CLI_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def _bounded_correlation(value: str | None) -> str | None:
    return value if isinstance(value, str) and _CORRELATION.fullmatch(value) else None


def _https_url(value: Any, *, host: str | None = None) -> str:
    if not isinstance(value, str):
        raise MediaProviderError("INVALID_PROVIDER_URL", pre_execution=True)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (host is not None and parsed.hostname.lower() != host)
    ):
        raise MediaProviderError("INVALID_PROVIDER_URL", pre_execution=True)
    return value


def _error_for_status(status: int, body: Any) -> MediaProviderError:
    message = ""
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        message = body["detail"][:500].lower()
    if status == 400 and "concurrent" in message:
        return MediaProviderError("PROVIDER_CONCURRENCY", retryable=True, http_status=status, pre_execution=True)
    if status == 400:
        return MediaProviderError("PROVIDER_VALIDATION", http_status=status, pre_execution=True)
    if status == 401:
        return MediaProviderError("PROVIDER_AUTHENTICATION", http_status=status, pre_execution=True)
    if status == 403:
        return MediaProviderError("PROVIDER_INSUFFICIENT_CREDITS", http_status=status, pre_execution=True)
    if status == 404:
        return MediaProviderError("PROVIDER_NOT_FOUND", http_status=status, pre_execution=True)
    if status == 422:
        return MediaProviderError("PROVIDER_REQUEST_REJECTED", http_status=status, pre_execution=True)
    if status == 423:
        return MediaProviderError("PROVIDER_MODEL_BLOCKED", retryable=True, http_status=status, pre_execution=True)
    if status == 429:
        return MediaProviderError("PROVIDER_RATE_LIMIT", retryable=True, http_status=status, pre_execution=True)
    if status == 503:
        return MediaProviderError("PROVIDER_MODEL_UNAVAILABLE", retryable=True, http_status=status)
    if 500 <= status < 600:
        return MediaProviderError("PROVIDER_FAILURE", retryable=True, http_status=status)
    return MediaProviderError("PROVIDER_HTTP_FAILURE", http_status=status)


def _media_outputs(payload: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    outputs: list[dict[str, str]] = []

    def add(value: Any, kind: str) -> None:
        if not isinstance(value, dict):
            return
        url = value.get("url")
        if isinstance(url, str):
            outputs.append({"type": kind, "url": _https_url(url), "retention": "PROVIDER_MANAGED_AT_LEAST_7_DAYS"})

    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            add(item, "image")
    add(payload.get("video"), "video")
    add(payload.get("audio"), "audio")
    audios = payload.get("audios")
    if isinstance(audios, list):
        for item in audios:
            add(item, "audio")
    return tuple(outputs)


@dataclass(frozen=True)
class HiggsfieldMediaSettings:
    enabled: bool = False
    api_base_url: str = API_BASE_URL
    api_key_ref: str = "env:ORQEVIA_HIGGSFIELD_API_KEY"
    api_key_id_ref: str = ""
    api_key_secret_ref: str = ""
    cli_executable: str = ""
    catalog_file: str = ""
    catalog_sha256_file: str = ""
    catalog_max_age_seconds: int = 86400
    validation_file: str = ""
    validation_sha256_file: str = ""
    validation_max_age_seconds: int = 86400
    generation_file: str = ""
    generation_sha256_file: str = ""
    generation_max_age_seconds: int = 31536000
    database_path: str = "/data/media-jobs.db"
    max_cost_usd: Decimal = Decimal("0.25")
    max_jobs_per_day: int = 3
    max_concurrent_jobs: int = 1
    request_timeout_seconds: int = 30
    poll_timeout_seconds: int = 900
    poll_initial_seconds: float = 2.0
    poll_max_seconds: float = 10.0
    max_upload_bytes: int = 100 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "HiggsfieldMediaSettings":
        def flag(name: str, default: bool = False) -> bool:
            return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes"}

        def integer(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError:
                value = default
            return max(low, min(high, value))

        def number(name: str, default: float, low: float, high: float) -> float:
            try:
                value = float(os.getenv(name, str(default)))
            except ValueError:
                value = default
            return max(low, min(high, value))

        base = os.getenv("ORQEVIA_HIGGSFIELD_API_BASE_URL", API_BASE_URL).strip().rstrip("/")
        if base != API_BASE_URL:
            raise ValueError("ORQEVIA_HIGGSFIELD_API_BASE_URL must remain the documented production origin")
        return cls(
            enabled=flag("ORQEVIA_HIGGSFIELD_ENABLED"),
            api_base_url=base,
            api_key_ref=os.getenv("ORQEVIA_HIGGSFIELD_API_KEY_REF", "env:ORQEVIA_HIGGSFIELD_API_KEY").strip(),
            api_key_id_ref=os.getenv("ORQEVIA_HIGGSFIELD_API_KEY_ID_REF", "").strip(),
            api_key_secret_ref=os.getenv("ORQEVIA_HIGGSFIELD_API_KEY_SECRET_REF", "").strip(),
            cli_executable=os.getenv("ORQEVIA_HIGGSFIELD_CLI", "").strip(),
            catalog_file=os.getenv("ORQEVIA_HIGGSFIELD_CATALOG_FILE", "").strip(),
            catalog_sha256_file=os.getenv("ORQEVIA_HIGGSFIELD_CATALOG_SHA256_FILE", "").strip(),
            catalog_max_age_seconds=integer("ORQEVIA_HIGGSFIELD_CATALOG_MAX_AGE_SECONDS", 86400, 300, 604800),
            validation_file=os.getenv("ORQEVIA_HIGGSFIELD_VALIDATION_FILE", "").strip(),
            validation_sha256_file=os.getenv("ORQEVIA_HIGGSFIELD_VALIDATION_SHA256_FILE", "").strip(),
            validation_max_age_seconds=integer("ORQEVIA_HIGGSFIELD_VALIDATION_MAX_AGE_SECONDS", 86400, 300, 604800),
            generation_file=os.getenv("ORQEVIA_HIGGSFIELD_GENERATION_FILE", "").strip(),
            generation_sha256_file=os.getenv("ORQEVIA_HIGGSFIELD_GENERATION_SHA256_FILE", "").strip(),
            generation_max_age_seconds=integer(
                "ORQEVIA_HIGGSFIELD_GENERATION_MAX_AGE_SECONDS", 31536000, 300, 31536000
            ),
            database_path=os.getenv("ORQEVIA_MEDIA_DB", "/data/media-jobs.db").strip(),
            max_cost_usd=decimal_value(os.getenv("ORQEVIA_MEDIA_MAX_COST_USD", "0.25"), "max_cost_usd"),
            max_jobs_per_day=integer("ORQEVIA_MEDIA_MAX_JOBS_PER_DAY", 3, 1, 100),
            max_concurrent_jobs=integer("ORQEVIA_MEDIA_MAX_CONCURRENT_JOBS", 1, 1, 10),
            request_timeout_seconds=integer("ORQEVIA_MEDIA_HTTP_TIMEOUT_SECONDS", 30, 5, 120),
            poll_timeout_seconds=integer("ORQEVIA_MEDIA_POLL_TIMEOUT_SECONDS", 900, 30, 3600),
            poll_initial_seconds=number("ORQEVIA_MEDIA_POLL_INITIAL_SECONDS", 2.0, 0.1, 10.0),
            poll_max_seconds=number("ORQEVIA_MEDIA_POLL_MAX_SECONDS", 10.0, 0.1, 30.0),
            max_upload_bytes=integer("ORQEVIA_MEDIA_MAX_UPLOAD_BYTES", 100 * 1024 * 1024, 1024, 1024 * 1024 * 1024),
        )


class HiggsfieldApiProvider:
    provider_id = "higgsfield"

    def __init__(
        self,
        settings: HiggsfieldMediaSettings,
        *,
        secret_resolver: Callable[[str], str] = resolve_secret,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.settings = settings
        self.resolve_secret = secret_resolver
        self.transport = transport
        self.sleep = sleeper

    def _credential(self) -> str:
        try:
            complete = self.resolve_secret(self.settings.api_key_ref)
        except (SecretUnavailable, KeyError, OSError):
            complete = ""
        if not complete and self.settings.api_key_id_ref and self.settings.api_key_secret_ref:
            try:
                key_id = self.resolve_secret(self.settings.api_key_id_ref)
                key_secret = self.resolve_secret(self.settings.api_key_secret_ref)
                complete = f"{key_id}:{key_secret}"
            except (SecretUnavailable, KeyError, OSError):
                complete = ""
        if (
            not isinstance(complete, str)
            or not complete
            or "\r" in complete
            or "\n" in complete
            or any(char.isspace() for char in complete)
            or complete.count(":") != 1
        ):
            raise MediaProviderError("CREDENTIAL_UNAVAILABLE", pre_execution=True)
        return complete

    def health(self) -> dict[str, Any]:
        try:
            self._credential()
            readiness = "READY"
        except MediaProviderError:
            readiness = "CREDENTIAL_UNAVAILABLE"
        return {
            "provider": self.provider_id,
            "enabled": self.settings.enabled,
            "readiness": readiness,
            "provider_health": "UNMEASURED",
            "network_probe_performed": False,
        }

    def credential_fingerprint(self) -> str | None:
        try:
            credential = self._credential()
        except MediaProviderError:
            return None
        return hashlib.sha256(
            VALIDATION_FINGERPRINT_CONTEXT + credential.encode("ascii")
        ).hexdigest()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.api_base_url,
            transport=self.transport,
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=False,
        )

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": "Key " + self._credential(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ORQEVIA-media-provider/1",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return trace_headers(headers)

    async def _json_response(self, response: httpx.Response) -> dict[str, Any]:
        correlation = _bounded_correlation(response.headers.get("x-correlation-id"))
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = None
        if response.status_code < 200 or response.status_code >= 300:
            error = _error_for_status(response.status_code, body)
            error.correlation_id = correlation
            raise error
        if not isinstance(body, dict):
            raise MediaProviderError("MALFORMED_PROVIDER_RESPONSE", correlation_id=correlation)
        return body

    async def estimate(self, request: MediaJobRequest) -> MediaEstimate:
        if request.data_classification != "CLOUD_PERMITTED":
            raise MediaProviderError("DATA_LOCALITY", pre_execution=True)
        headers = self._headers()
        last: MediaProviderError | None = None
        body = None
        for attempt in range(2):
            try:
                with span(
                    "media.provider",
                    {"component": "media", "provider": self.provider_id, "operation": "estimate"},
                ):
                    async with self._client() as client:
                        response = await client.post(
                            f"/estimate/{request.model_path}", headers=headers, json=request.payload
                        )
                        body = await self._json_response(response)
                break
            except MediaProviderError as error:
                last = error
                if not error.retryable or attempt == 1:
                    raise
            except httpx.TimeoutException:
                last = MediaProviderError("PROVIDER_TIMEOUT", retryable=True)
            except httpx.TransportError:
                last = MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True)
            await self.sleep(1.5**attempt)
        if body is None:
            raise last or MediaProviderError("PROVIDER_FAILURE")
        credits = decimal_value(body.get("credits"), "credits") if body.get("credits") is not None else None
        if body.get("usd") is None:
            raise MediaProviderError("COST_ESTIMATE_UNAVAILABLE")
        usd = decimal_value(body.get("usd"), "estimate_usd")
        estimate = MediaEstimate(usd=usd, credits=credits)
        return estimate

    async def submit(self, request: MediaJobRequest, estimate: MediaEstimate) -> MediaJob:
        if request.data_classification != "CLOUD_PERMITTED":
            raise MediaProviderError("DATA_LOCALITY", pre_execution=True)
        if request.charge_authorized is not True:
            raise MediaProviderError("CHARGE_NOT_AUTHORIZED", pre_execution=True)
        if estimate.usd > request.max_cost_usd:
            raise MediaProviderError("COST_LIMIT_EXCEEDED", pre_execution=True)
        headers = self._headers(idempotency_key=request.idempotency_key)
        last: MediaProviderError | None = None
        for attempt in range(2):
            try:
                with span(
                    "media.provider",
                    {"component": "media", "provider": self.provider_id, "operation": "submit"},
                ):
                    async with self._client() as client:
                        response = await client.post(f"/{request.model_path}", headers=headers, json=request.payload)
                        body = await self._json_response(response)
                request_id = str(body.get("request_id") or "")
                if not _UUID.fullmatch(request_id):
                    raise MediaProviderError(
                        "MALFORMED_PROVIDER_RESPONSE",
                        correlation_id=_bounded_correlation(response.headers.get("x-correlation-id")),
                    )
                status = body.get("status", "queued")
                if status not in {"queued", "in_progress"}:
                    raise MediaProviderError("MALFORMED_PROVIDER_RESPONSE")
                status_url = _https_url(body.get("status_url"), host="api.higgsfield.ai")
                cancel_url = _https_url(body.get("cancel_url"), host="api.higgsfield.ai")
                return MediaJob(
                    request_id=request_id,
                    status=status,
                    provider=self.provider_id,
                    operation=request.operation,
                    model_path=request.model_path,
                    task_id=request.task_id,
                    correlation_id=_bounded_correlation(response.headers.get("x-correlation-id")),
                    estimated_usd=estimate.usd,
                    updated_at=utcnow(),
                    status_url=status_url,
                    cancel_url=cancel_url,
                )
            except MediaProviderError as error:
                last = error
                if not error.retryable or attempt == 1:
                    raise
            except httpx.TimeoutException:
                last = MediaProviderError("PROVIDER_TIMEOUT", retryable=True)
            except httpx.TransportError:
                last = MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True)
            await self.sleep(1.5**attempt)
        raise last or MediaProviderError("PROVIDER_FAILURE")

    async def status(self, request_id: str, *, status_url: str | None = None) -> MediaJob:
        if not _UUID.fullmatch(request_id):
            raise MediaProviderError("INVALID_REQUEST_ID", pre_execution=True)
        url = _https_url(
            status_url or f"{self.settings.api_base_url}/requests/{request_id}/status", host="api.higgsfield.ai"
        )
        last: MediaProviderError | None = None
        for attempt in range(3):
            try:
                with span(
                    "media.provider",
                    {"component": "media", "provider": self.provider_id, "operation": "status"},
                ):
                    async with self._client() as client:
                        response = await client.get(url, headers=self._headers())
                        body = await self._json_response(response)
                if str(body.get("request_id")) != request_id:
                    raise MediaProviderError("PROVIDER_REQUEST_ID_MISMATCH")
                status = body.get("status")
                if status not in TERMINAL_STATUSES | {"queued", "in_progress"}:
                    raise MediaProviderError("MALFORMED_PROVIDER_RESPONSE")
                return MediaJob(
                    request_id=request_id,
                    status=status,
                    provider=self.provider_id,
                    operation="workflow",
                    model_path="",
                    task_id="",
                    outputs=_media_outputs(body),
                    error_code="PROVIDER_GENERATION_FAILED"
                    if status == "failed"
                    else "PROVIDER_CONTENT_REJECTED"
                    if status == "nsfw"
                    else None,
                    correlation_id=_bounded_correlation(response.headers.get("x-correlation-id")),
                    updated_at=utcnow(),
                    status_url=url,
                )
            except MediaProviderError as error:
                last = error
                if not error.retryable or attempt == 2:
                    raise
            except httpx.TimeoutException:
                last = MediaProviderError("PROVIDER_TIMEOUT", retryable=True)
            except httpx.TransportError:
                last = MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True)
            await self.sleep(2**attempt)
        raise last or MediaProviderError("PROVIDER_FAILURE")

    async def cancel(self, request_id: str, *, cancel_url: str | None = None) -> MediaJob:
        if not _UUID.fullmatch(request_id):
            raise MediaProviderError("INVALID_REQUEST_ID", pre_execution=True)
        current = await self.status(request_id)
        if current.status != "queued":
            raise MediaProviderError("JOB_NOT_CANCELABLE", pre_execution=True)
        url = _https_url(
            cancel_url or f"{self.settings.api_base_url}/requests/{request_id}/cancel", host="api.higgsfield.ai"
        )
        try:
            with span(
                "media.provider",
                {"component": "media", "provider": self.provider_id, "operation": "cancel"},
            ):
                async with self._client() as client:
                    response = await client.post(url, headers=self._headers())
            if response.status_code != 202:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                error = _error_for_status(response.status_code, body)
                error.correlation_id = _bounded_correlation(response.headers.get("x-correlation-id"))
                raise error
        except httpx.TimeoutException:
            raise MediaProviderError("PROVIDER_TIMEOUT") from None
        except httpx.TransportError:
            raise MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True) from None
        return MediaJob(
            request_id=request_id,
            status="canceled",
            provider=self.provider_id,
            operation=current.operation,
            model_path=current.model_path,
            task_id=current.task_id,
            correlation_id=current.correlation_id,
            updated_at=utcnow(),
            status_url=current.status_url,
            cancel_url=url,
        )

    async def upload_file(self, path: str | Path, content_type: str) -> str:
        source = Path(path)
        if not source.is_file():
            raise MediaProviderError("UPLOAD_FILE_NOT_FOUND", pre_execution=True)
        if not _CONTENT_TYPE.fullmatch(content_type):
            raise MediaProviderError("UPLOAD_CONTENT_TYPE_DENIED", pre_execution=True)
        if source.stat().st_size < 1 or source.stat().st_size > self.settings.max_upload_bytes:
            raise MediaProviderError("UPLOAD_SIZE_DENIED", pre_execution=True)
        try:
            async with self._client() as client:
                response = await client.post(
                    "/files/generate-upload-url",
                    headers=self._headers(),
                    json={"content_type": content_type},
                )
                body = await self._json_response(response)
                upload_url = _https_url(body.get("upload_url"))
                public_url = _https_url(body.get("public_url"))
                upload_headers = body.get("upload_headers")
                if not isinstance(upload_headers, dict):
                    raise MediaProviderError("MALFORMED_PROVIDER_RESPONSE")
                headers: dict[str, str] = {}
                for key, value in upload_headers.items():
                    if (
                        not isinstance(key, str)
                        or not isinstance(value, str)
                        or key.lower() in {"authorization", "cookie", "host"}
                        or "\r" in value
                        or "\n" in value
                    ):
                        raise MediaProviderError("MALFORMED_PROVIDER_RESPONSE")
                    headers[key] = value
                upload = await client.put(upload_url, headers=headers, content=source.read_bytes())
                if not 200 <= upload.status_code < 300:
                    raise MediaProviderError("UPLOAD_FAILED", http_status=upload.status_code)
                return public_url
        except httpx.TimeoutException:
            raise MediaProviderError("PROVIDER_TIMEOUT") from None
        except httpx.TransportError:
            raise MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True) from None


class HiggsfieldCliDiscovery:
    """Allowlisted, read-only CLI discovery with no arbitrary command support."""

    def __init__(
        self,
        executable: str,
        *,
        runner: Callable[[list[str], int], subprocess.CompletedProcess] | None = None,
    ):
        self.executable = self._resolve(executable)
        self.runner = runner or self._run

    @staticmethod
    def _resolve(executable: str) -> str:
        candidate = executable.strip() if isinstance(executable, str) else ""
        if candidate and Path(candidate).is_file():
            resolved = str(Path(candidate).resolve())
        else:
            resolved = shutil.which(candidate) if candidate else None
        if not resolved or Path(resolved).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise MediaProviderError("CLI_UNAVAILABLE", pre_execution=True)
        return resolved

    @staticmethod
    def _safe_env() -> dict[str, str]:
        allowed = {
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "HOME",
            "USERNAME",
            "USERDOMAIN",
            "USERDOMAIN_ROAMINGPROFILE",
            "SYSTEMDRIVE",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "COMMONPROGRAMFILES",
            "COMMONPROGRAMFILES(X86)",
            "COMSPEC",
            "ALLUSERSPROFILE",
            "PUBLIC",
            "HOMEDRIVE",
            "HOMEPATH",
            "PROCESSOR_ARCHITECTURE",
            "NUMBER_OF_PROCESSORS",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "NODE_EXTRA_CA_CERTS",
        }
        return {key: value for key, value in os.environ.items() if key in allowed}

    def _run(self, arguments: list[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.executable, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            env=self._safe_env(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _json(self, arguments: list[str], timeout: int = 20) -> Any:
        try:
            result = self.runner(arguments, timeout)
        except (OSError, subprocess.SubprocessError):
            raise MediaProviderError("CLI_EXECUTION_FAILED") from None
        if result.returncode != 0:
            raise MediaProviderError("CLI_COMMAND_FAILED")
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError):
            raise MediaProviderError("CLI_RESPONSE_INVALID") from None

    def version(self) -> str:
        try:
            result = self.runner(["--version"], 10)
        except (OSError, subprocess.SubprocessError):
            raise MediaProviderError("CLI_EXECUTION_FAILED") from None
        if result.returncode != 0:
            raise MediaProviderError("CLI_COMMAND_FAILED")
        value = (result.stdout or "").strip().splitlines()
        if not value:
            raise MediaProviderError("CLI_RESPONSE_INVALID")
        return value[0][:200]

    def snapshot(self) -> dict[str, Any]:
        workspace = self._json(["workspace", "status", "--json"])
        account = self._json(["account", "status", "--json"])
        models = self._json(["model", "list", "--json"], timeout=30)
        workflows = self._json(["workflow", "list", "--json"], timeout=30)
        if not isinstance(workspace, dict) or not isinstance(account, dict):
            raise MediaProviderError("CLI_RESPONSE_INVALID")
        if not isinstance(models, list) or not isinstance(workflows, list):
            raise MediaProviderError("CLI_RESPONSE_INVALID")
        model_rows = [
            {
                "display_name": str(item.get("display_name", ""))[:200],
                "job_type": str(item.get("job_type", ""))[:100],
                "type": str(item.get("type", ""))[:20],
            }
            for item in models
            if isinstance(item, dict) and _CLI_NAME.fullmatch(str(item.get("job_type", "")))
        ]
        workflow_rows = [
            {
                "display_name": str(item.get("display_name", ""))[:200],
                "job_type": str(item.get("job_type", ""))[:100],
                "type": str(item.get("type", ""))[:20],
            }
            for item in workflows
            if isinstance(item, dict) and _CLI_NAME.fullmatch(str(item.get("job_type", "")))
        ]
        workspace_id = str(workspace.get("id", ""))
        if not _UUID.fullmatch(workspace_id):
            raise MediaProviderError("CLI_WORKSPACE_INVALID")
        return {
            "status": "AUTHENTICATED",
            "workspace": {
                "id": workspace_id,
                "name": workspace.get("name"),
                "plan": workspace.get("plan_type"),
                "credits": workspace.get("credits"),
                "role": workspace.get("user_role"),
                "selected": workspace.get("is_selected") is True,
            },
            "account": {
                "plan": account.get("subscription_plan_type"),
                "credits": account.get("credits"),
            },
            "models": model_rows,
            "model_count": len(model_rows),
            "model_types": sorted({row["type"] for row in model_rows}),
            "workflows": workflow_rows,
            "workflow_count": len(workflow_rows),
            "workflow_types": sorted({row["type"] for row in workflow_rows}),
            "execution_authority": "NONE_DISCOVERY_ONLY",
        }

    def model(self, job_type: str) -> dict[str, Any]:
        if not isinstance(job_type, str) or not _CLI_NAME.fullmatch(job_type):
            raise MediaProviderError("INVALID_MODEL_ID", pre_execution=True)
        value = self._json(["model", "get", job_type, "--json"])
        if not isinstance(value, dict):
            raise MediaProviderError("CLI_RESPONSE_INVALID")
        return value

    def workflow(self, workflow_id: str) -> dict[str, Any]:
        if not isinstance(workflow_id, str) or not _CLI_NAME.fullmatch(workflow_id):
            raise MediaProviderError("INVALID_WORKFLOW_ID", pre_execution=True)
        value = self._json(["workflow", "get", workflow_id, "--json"])
        if not isinstance(value, dict):
            raise MediaProviderError("CLI_RESPONSE_INVALID")
        return value


class HiggsfieldCatalogSnapshot:
    """Read a sanitized catalog produced by the authenticated Windows CLI."""

    schema_version = "orqevia.higgsfield-catalog.v1"

    def __init__(self, path: str, sha256_file: str, *, max_age_seconds: int = 86400):
        self.path = Path(path)
        self.sha256_file = Path(sha256_file)
        self.max_age_seconds = max_age_seconds
        if not self.path.is_absolute() or not self.sha256_file.is_absolute():
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)

    def _load(self) -> tuple[dict[str, Any], str]:
        try:
            raw = self.path.read_bytes()
            digest_raw = self.sha256_file.read_bytes()
        except OSError:
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True) from None
        if not 1 <= len(raw) <= 1024 * 1024:
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        try:
            expected = digest_raw.decode("ascii").strip().lower()
        except UnicodeError:
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True) from None
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True) from None
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != self.schema_version
            or not isinstance(value.get("generated_at_utc"), str)
            or not isinstance(value.get("cli_version"), str)
            or not isinstance(value.get("catalog"), dict)
        ):
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        return value, actual

    def health(self) -> dict[str, Any]:
        if not self.path.is_file() or not self.sha256_file.is_file():
            return {
                "mode": "READ_ONLY_SNAPSHOT",
                "status": "MISSING",
                "configured": True,
            }
        try:
            value, digest = self._load()
            generated = datetime.fromisoformat(value["generated_at_utc"].replace("Z", "+00:00"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - generated).total_seconds()))
        except (MediaProviderError, ValueError):
            return {
                "mode": "READ_ONLY_SNAPSHOT",
                "status": "INVALID",
                "configured": True,
            }
        return {
            "mode": "READ_ONLY_SNAPSHOT",
            "status": "STALE" if age > self.max_age_seconds else "VALID_FRESH",
            "configured": True,
            "generated_at_utc": value["generated_at_utc"],
            "age_seconds": age,
            "max_age_seconds": self.max_age_seconds,
            "sha256": digest,
            "cli_version": value["cli_version"],
        }

    @staticmethod
    def _rows(items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list) or len(items) > 5000:
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        rows = []
        for item in items:
            if not isinstance(item, dict):
                raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
            job_type = str(item.get("job_type", ""))
            if not _CLI_NAME.fullmatch(job_type):
                raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
            rows.append({
                "display_name": str(item.get("display_name", ""))[:200],
                "job_type": job_type[:100],
                "type": str(item.get("type", ""))[:20],
            })
        return rows

    def snapshot(self) -> dict[str, Any]:
        value, digest = self._load()
        generated = datetime.fromisoformat(value["generated_at_utc"].replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - generated).total_seconds()))
        if age > self.max_age_seconds:
            raise MediaProviderError("CATALOG_STALE", pre_execution=True)
        catalog = value["catalog"]
        workspace = catalog.get("workspace")
        account = catalog.get("account")
        if (
            catalog.get("status") != "AUTHENTICATED"
            or not isinstance(workspace, dict)
            or not isinstance(account, dict)
            or not _UUID.fullmatch(str(workspace.get("id", "")))
        ):
            raise MediaProviderError("CATALOG_UNAVAILABLE", pre_execution=True)
        models = self._rows(catalog.get("models"))
        workflows = self._rows(catalog.get("workflows"))
        return {
            "status": "AUTHENTICATED",
            "source": "WINDOWS_CLI_SNAPSHOT",
            "generated_at_utc": value["generated_at_utc"],
            "cli_version": value["cli_version"],
            "snapshot_sha256": digest,
            "workspace": {
                "id": str(workspace["id"]),
                "name": str(workspace.get("name", ""))[:200],
                "plan": str(workspace.get("plan", ""))[:80],
                "credits": workspace.get("credits"),
                "role": str(workspace.get("role", ""))[:80],
                "selected": workspace.get("selected") is True,
            },
            "account": {
                "plan": str(account.get("plan", ""))[:80],
                "credits": account.get("credits"),
            },
            "models": models,
            "model_count": len(models),
            "model_types": sorted({row["type"] for row in models}),
            "workflows": workflows,
            "workflow_count": len(workflows),
            "workflow_types": sorted({row["type"] for row in workflows}),
            "execution_authority": "NONE_DISCOVERY_ONLY",
        }

    def model(self, job_type: str) -> dict[str, Any]:
        if not isinstance(job_type, str) or not _CLI_NAME.fullmatch(job_type):
            raise MediaProviderError("INVALID_MODEL_ID", pre_execution=True)
        match = next((row for row in self.snapshot()["models"] if row["job_type"] == job_type), None)
        if match is None:
            raise MediaProviderError("PROVIDER_MODEL_UNAVAILABLE", pre_execution=True)
        return match

    def workflow(self, workflow_id: str) -> dict[str, Any]:
        if not isinstance(workflow_id, str) or not _CLI_NAME.fullmatch(workflow_id):
            raise MediaProviderError("INVALID_WORKFLOW_ID", pre_execution=True)
        match = next((row for row in self.snapshot()["workflows"] if row["job_type"] == workflow_id), None)
        if match is None:
            raise MediaProviderError("PROVIDER_MODEL_UNAVAILABLE", pre_execution=True)
        return match


class HiggsfieldValidationReceipt:
    """A non-billable provider validation receipt produced outside the backend."""

    schema_version = "orqevia.higgsfield-provider-validation.v1"

    def __init__(self, path: str, sha256_file: str, *, max_age_seconds: int = 86400):
        self.path = Path(path)
        self.sha256_file = Path(sha256_file)
        self.max_age_seconds = max_age_seconds
        if not self.path.is_absolute() or not self.sha256_file.is_absolute():
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True)

    def _load(self) -> tuple[dict[str, Any], str]:
        try:
            raw = self.path.read_bytes()
            digest_raw = self.sha256_file.read_bytes()
        except OSError:
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True) from None
        if not 1 <= len(raw) <= 64 * 1024:
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True)
        try:
            expected = digest_raw.decode("ascii").strip().lower()
            value = json.loads(raw)
        except (UnicodeError, ValueError):
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True) from None
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True)
        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != self.schema_version
            or value.get("result") not in {"PASSED", "FAILED"}
            or not isinstance(value.get("validated_at_utc"), str)
            or not isinstance(value.get("provider_authentication_verified"), bool)
            or not isinstance(value.get("estimate_verified"), bool)
            or value.get("billable_generation_submitted") is not False
            or (
                value.get("credential_fingerprint_sha256") is not None
                and (
                    not isinstance(value.get("credential_fingerprint_sha256"), str)
                    or re.fullmatch(r"[a-f0-9]{64}", value["credential_fingerprint_sha256"]) is None
                )
            )
        ):
            raise MediaProviderError("VALIDATION_UNAVAILABLE", pre_execution=True)
        return value, actual

    def health(self) -> dict[str, Any]:
        if not self.path.is_file() or not self.sha256_file.is_file():
            return {
                "mode": "NON_BILLABLE_ESTIMATE",
                "status": "MISSING",
                "configured": True,
            }
        try:
            value, digest = self._load()
            validated = datetime.fromisoformat(value["validated_at_utc"].replace("Z", "+00:00"))
            if validated.tzinfo is None:
                validated = validated.replace(tzinfo=timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - validated).total_seconds()))
        except (MediaProviderError, ValueError):
            return {
                "mode": "NON_BILLABLE_ESTIMATE",
                "status": "INVALID",
                "configured": True,
            }
        status = (
            "STALE"
            if age > self.max_age_seconds
            else "VALID"
            if value["result"] == "PASSED"
            else "FAILED"
        )
        return {
            "mode": "NON_BILLABLE_ESTIMATE",
            "status": status,
            "configured": True,
            "validated_at_utc": value["validated_at_utc"],
            "age_seconds": age,
            "max_age_seconds": self.max_age_seconds,
            "sha256": digest,
            "result": value["result"],
            "provider_authentication_verified": value["provider_authentication_verified"],
            "estimate_verified": value["estimate_verified"],
            "credential_fingerprint_sha256": value["credential_fingerprint_sha256"],
            "billable_generation_submitted": False,
        }


class HiggsfieldGenerationReceipt:
    """A digest-verified acceptance receipt for one completed live generation."""

    schema_version = "orqevia.higgsfield-generation-acceptance.v1"

    def __init__(self, path: str, sha256_file: str, *, max_age_seconds: int = 31536000):
        self.path = Path(path)
        self.sha256_file = Path(sha256_file)
        self.max_age_seconds = max_age_seconds
        if not self.path.is_absolute() or not self.sha256_file.is_absolute():
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)

    def _load(self) -> tuple[dict[str, Any], str]:
        try:
            raw = self.path.read_bytes()
            digest_raw = self.sha256_file.read_bytes()
        except OSError:
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True) from None
        if not 1 <= len(raw) <= 128 * 1024:
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
        try:
            expected = digest_raw.decode("ascii").strip().lower()
            value = json.loads(raw)
        except (UnicodeError, ValueError):
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True) from None
        if re.fullmatch(r"[a-f0-9]{64}", expected) is None:
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
        outputs = value.get("outputs") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != self.schema_version
            or value.get("provider") != "higgsfield"
            or not isinstance(value.get("observed_at_utc"), str)
            or not isinstance(value.get("request_id"), str)
            or _UUID.fullmatch(value["request_id"]) is None
            or not isinstance(value.get("task_id"), str)
            or not value["task_id"]
            or len(value["task_id"]) > 256
            or not isinstance(value.get("model"), str)
            or not value["model"]
            or len(value["model"]) > 200
            or not isinstance(value.get("idempotency_key"), str)
            or re.fullmatch(r"[\x21-\x7e]{1,255}", value["idempotency_key"]) is None
            or value.get("terminal_status") not in TERMINAL_STATUSES
            or type(value.get("polls")) is not int
            or value["polls"] < 0
            or not isinstance(value.get("estimated_usd"), str)
            or not isinstance(value.get("maximum_cost_usd"), str)
            or re.fullmatch(r"[a-f0-9]{64}", str(value.get("credential_fingerprint_sha256", ""))) is None
            or re.fullmatch(r"[a-f0-9]{64}", str(value.get("provider_contract_sha256", ""))) is None
            or value.get("result_urls_exported") is not False
            or not isinstance(outputs, list)
            or not 1 <= len(outputs) <= 100
        ):
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
        estimated = decimal_value(value["estimated_usd"], "estimated_usd")
        maximum = decimal_value(value["maximum_cost_usd"], "maximum_cost_usd")
        if maximum <= 0 or maximum > Decimal("0.25") or estimated > maximum:
            raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
        cleaned_outputs = []
        for output in outputs:
            if (
                not isinstance(output, dict)
                or type(output.get("bytes")) is not int
                or not 1 <= output["bytes"] <= 100 * 1024 * 1024
                or re.fullmatch(r"[a-f0-9]{64}", str(output.get("sha256", ""))) is None
                or not isinstance(output.get("host"), str)
                or not output["host"]
                or len(output["host"]) > 255
            ):
                raise MediaProviderError("GENERATION_EVIDENCE_UNAVAILABLE", pre_execution=True)
            cleaned_outputs.append({
                "bytes": output["bytes"],
                "sha256": output["sha256"],
                "host": output["host"],
            })
        value["outputs"] = cleaned_outputs
        return value, actual

    def health(self) -> dict[str, Any]:
        if not self.path.is_file() or not self.sha256_file.is_file():
            return {
                "mode": "LIVE_GENERATION_ACCEPTANCE",
                "status": "MISSING",
                "configured": True,
            }
        try:
            value, digest = self._load()
            observed = datetime.fromisoformat(value["observed_at_utc"].replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))
        except (MediaProviderError, ValueError):
            return {
                "mode": "LIVE_GENERATION_ACCEPTANCE",
                "status": "INVALID",
                "configured": True,
            }
        completed = value["terminal_status"] == "completed" and value.get("error_code") is None
        status = "STALE" if age > self.max_age_seconds else "VALID" if completed else "FAILED"
        return {
            "mode": "LIVE_GENERATION_ACCEPTANCE",
            "status": status,
            "configured": True,
            "observed_at_utc": value["observed_at_utc"],
            "age_seconds": age,
            "max_age_seconds": self.max_age_seconds,
            "sha256": digest,
            "request_id": value["request_id"],
            "task_id": value["task_id"],
            "model": value["model"],
            "idempotency_key": value["idempotency_key"],
            "terminal_status": value["terminal_status"],
            "polls": value["polls"],
            "estimated_usd": value["estimated_usd"],
            "maximum_cost_usd": value["maximum_cost_usd"],
            "output_count": len(value["outputs"]),
            "outputs": value["outputs"],
            "credential_fingerprint_sha256": value["credential_fingerprint_sha256"],
            "provider_contract_sha256": value["provider_contract_sha256"],
            "entitlement_scope": value.get("entitlement_scope"),
        }


class HiggsfieldMediaService:
    def __init__(
        self,
        settings: HiggsfieldMediaSettings,
        *,
        provider: HiggsfieldApiProvider | None = None,
        discovery: HiggsfieldCliDiscovery | HiggsfieldCatalogSnapshot | None = None,
        validation: HiggsfieldValidationReceipt | None = None,
        generation: HiggsfieldGenerationReceipt | None = None,
        store: MediaJobStore | None = None,
    ):
        self.settings = settings
        self.provider = provider or HiggsfieldApiProvider(settings)
        self.discovery = discovery
        self.validation = validation
        self.generation = generation
        self.store = store or MediaJobStore(settings.database_path)

    def _audit(
        self,
        action: str,
        request_id: str | None,
        task_id: str,
        *,
        phase: str,
        owner_id: str,
        model_path: str,
        **details: Any,
    ) -> None:
        record = ActionRecord(
            task_id=task_id or (request_id or "media"),
            agent_id=owner_id,
            action_type=action,
            tool="higgsfield-media",
            target=model_path,
            classification="consequential",
            model_backend="higgsfield",
            execution_location="cloud",
        )
        action_ledger().emit(record, phase, request_id=request_id, **details)

    def health(self) -> dict[str, Any]:
        api_health = self.provider.health()
        if isinstance(self.discovery, HiggsfieldCatalogSnapshot):
            catalog_health = self.discovery.health()
        elif isinstance(self.discovery, HiggsfieldCliDiscovery):
            catalog_health = {
                "mode": "WINDOWS_CLI",
                "status": "CONFIGURED_UNVERIFIED",
                "configured": True,
            }
        else:
            catalog_health = {
                "mode": "NONE",
                "status": "NOT_CONFIGURED",
                "configured": False,
            }
        validation_health = (
            self.validation.health()
            if isinstance(self.validation, HiggsfieldValidationReceipt)
            else {
                "mode": "NON_BILLABLE_ESTIMATE",
                "status": "NOT_CONFIGURED",
                "configured": False,
            }
        )
        current_fingerprint = (
            self.provider.credential_fingerprint()
            if hasattr(self.provider, "credential_fingerprint")
            else None
        )
        receipt_fingerprint = validation_health.get("credential_fingerprint_sha256")
        credential_matches = bool(
            current_fingerprint
            and receipt_fingerprint
            and hmac.compare_digest(current_fingerprint, receipt_fingerprint)
        )
        validation_public = dict(validation_health)
        validation_public.pop("credential_fingerprint_sha256", None)
        rest_valid = (
            validation_health.get("status") == "VALID"
            and validation_health.get("provider_authentication_verified") is True
            and validation_health.get("estimate_verified") is True
            and credential_matches
        )
        generation_health = (
            self.generation.health()
            if isinstance(self.generation, HiggsfieldGenerationReceipt)
            else {
                "mode": "LIVE_GENERATION_ACCEPTANCE",
                "status": "NOT_CONFIGURED",
                "configured": False,
            }
        )
        generation_valid = self._generation_evidence_valid(
            generation_health,
            validation_health,
            current_fingerprint,
        )
        if not self.settings.enabled:
            overall = "DISABLED"
        elif api_health.get("readiness") != "READY":
            overall = "AUTH_REQUIRED"
        elif not rest_valid:
            overall = "AUTH_REQUIRED"
        elif catalog_health.get("status") != "VALID_FRESH":
            overall = "DEGRADED"
        elif generation_valid:
            overall = "READY"
        else:
            overall = "DEGRADED"
        generation_public = dict(generation_health)
        generation_public.pop("credential_fingerprint_sha256", None)
        return {
            "provider": self.provider_id(),
            "enabled": self.settings.enabled,
            "status": overall,
            "provider_configured": api_health.get("readiness") == "READY",
            "rest_credentials": "VALID"
            if rest_valid
            else "LOADED_NOT_SERVER_VERIFIED"
            if api_health.get("readiness") == "READY"
            else "AUTH_REQUIRED",
            "rest_credentials_valid": rest_valid,
            "credential_matches_validation": credential_matches,
            "rest_execution_ready": rest_valid and generation_valid,
            "cli_discovery_available": isinstance(self.discovery, HiggsfieldCliDiscovery),
            "catalog_snapshot_valid": catalog_health.get("status") in {"VALID_FRESH", "STALE"},
            "catalog_snapshot_fresh": catalog_health.get("status") == "VALID_FRESH",
            "quota_entitlement_verified": generation_valid
            and generation_health.get("entitlement_scope") == "SELECTED_MODEL_EXECUTION",
            "quota_entitlement_scope": "SELECTED_MODEL_EXECUTION"
            if generation_valid
            and generation_health.get("entitlement_scope") == "SELECTED_MODEL_EXECUTION"
            else "NOT_VERIFIED",
            "api": api_health,
            "catalog": catalog_health,
            "validation": validation_public,
            "generation": generation_public,
            "generation_execution_verified": generation_valid,
            "cli_discovery_configured": isinstance(self.discovery, HiggsfieldCliDiscovery),
            "catalog_discovery_configured": isinstance(self.discovery, HiggsfieldCatalogSnapshot),
            "execution_authority": "NONE_MEDIA_PROVIDER_ONLY",
        }

    def _generation_evidence_valid(
        self,
        evidence: Mapping[str, Any],
        validation_health: Mapping[str, Any],
        current_fingerprint: str | None,
    ) -> bool:
        if not isinstance(self.generation, HiggsfieldGenerationReceipt):
            return False
        if evidence.get("status") != "VALID":
            return False
        if not current_fingerprint or not hmac.compare_digest(
            current_fingerprint, validation_health.get("credential_fingerprint_sha256", "")
        ):
            return False
        if not hmac.compare_digest(
            current_fingerprint, evidence.get("credential_fingerprint_sha256", "")
        ):
            return False
        if not hmac.compare_digest(
            higgsfield_generation_contract_sha256(),
            evidence.get("provider_contract_sha256", ""),
        ):
            return False
        try:
            row = self.store.get_by_idempotency(evidence["idempotency_key"], owner_id="owner")
            if not row:
                return False
            outputs = json.loads(row.get("outputs_json") or "[]")
            return (
                row.get("provider_id") == "higgsfield"
                and row.get("request_id") == evidence["request_id"]
                and row.get("task_id") == evidence["task_id"]
                and row.get("model_path") == evidence["model"]
                and row.get("status") == "completed"
                and str(row.get("estimated_usd")) == evidence["estimated_usd"]
                and isinstance(outputs, list)
                and len(outputs) == evidence["output_count"]
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return False

    def provider_id(self) -> str:
        return "higgsfield"

    def discover(self) -> dict[str, Any]:
        if self.discovery is None:
            raise MediaProviderError("CLI_UNAVAILABLE", pre_execution=True)
        return self.discovery.snapshot()

    async def estimate(self, request: MediaJobRequest, *, owner_id: str) -> MediaEstimate:
        if not self.settings.enabled:
            raise MediaProviderError("PROVIDER_DISABLED", pre_execution=True)
        if request.data_classification != "CLOUD_PERMITTED":
            raise MediaProviderError("DATA_LOCALITY", pre_execution=True)
        try:
            estimate = await self.provider.estimate(request)
            if estimate.usd > self.settings.max_cost_usd or estimate.usd > request.max_cost_usd:
                raise MediaProviderError("COST_LIMIT_EXCEEDED", pre_execution=True)
            self._audit(
                "media.estimate",
                None,
                request.task_id,
                phase="completed",
                owner_id=owner_id,
                model_path=request.model_path,
                estimated_usd=str(estimate.usd),
            )
            return estimate
        except MediaProviderError as error:
            self._audit(
                "media.estimate",
                None,
                request.task_id,
                phase="failed",
                owner_id=owner_id,
                model_path=request.model_path,
                error=error.code,
            )
            raise

    def _public_or_existing(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "idempotency_key": row["idempotency_key"],
            "request_id": row["request_id"],
            "status": row["status"],
            "provider": row["provider_id"],
            "operation": row["operation"],
            "model_path": row["model_path"],
            "task_id": row["task_id"],
            "estimated_usd": row["estimated_usd"],
            "cost_basis": "PROVIDER_ESTIMATE_NOT_INVOICE",
            "error_code": row["error_code"],
            "correlation_id": row["correlation_id"],
            "terminal": row["status"] in TERMINAL_STATUSES,
            "updated_at": row["updated_at"],
        }

    async def submit(self, request: MediaJobRequest, *, owner_id: str) -> dict[str, Any]:
        if not self.settings.enabled:
            raise MediaProviderError("PROVIDER_DISABLED", pre_execution=True)
        if request.data_classification != "CLOUD_PERMITTED":
            raise MediaProviderError("DATA_LOCALITY", pre_execution=True)
        if request.charge_authorized is not True:
            raise MediaProviderError("CHARGE_NOT_AUTHORIZED", pre_execution=True)
        existing = self.store.get_by_idempotency(request.idempotency_key, owner_id=owner_id)
        if existing and existing["request_id"]:
            return self._public_or_existing(existing)
        if (
            self.store.active_count(owner_id=owner_id, provider_id=self.provider_id())
            >= self.settings.max_concurrent_jobs
        ):
            raise MediaProviderError("MAX_CONCURRENT_JOBS", pre_execution=True)
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        if (
            self.store.count_since(owner_id=owner_id, provider_id=self.provider_id(), since=since)
            >= self.settings.max_jobs_per_day
        ):
            raise MediaProviderError("DAILY_JOB_LIMIT", pre_execution=True)
        estimate = await self.provider.estimate(request)
        if estimate.usd > self.settings.max_cost_usd or estimate.usd > request.max_cost_usd:
            raise MediaProviderError("COST_LIMIT_EXCEEDED", pre_execution=True)
        row = self.store.begin(request, owner_id=owner_id, provider_id=self.provider_id())
        if row.get("request_id"):
            return self._public_or_existing(row)
        try:
            job = await self.provider.submit(request, estimate)
            self.store.set_submitted(request.idempotency_key, job)
            self._audit(
                "media.submit",
                job.request_id,
                request.task_id,
                phase="completed",
                owner_id=owner_id,
                model_path=request.model_path,
                estimated_usd=str(estimate.usd),
            )
            self.store.update(job.request_id, job)
            record_counter(
                "orqevia.media.jobs",
                1,
                {"provider": self.provider_id(), "operation": request.operation, "status": job.status},
            )
            return {
                **job.as_public_dict(),
                "idempotency_key": request.idempotency_key,
            }
        except MediaProviderError as error:
            record_counter(
                "orqevia.media.jobs",
                1,
                {
                    "provider": self.provider_id(),
                    "operation": request.operation,
                    "status": "ERROR",
                    "error_code": error.code,
                },
            )
            self._audit(
                "media.submit",
                None,
                request.task_id,
                phase="failed",
                owner_id=owner_id,
                model_path=request.model_path,
                error=error.code,
            )
            raise

    async def status(self, request_id: str, *, owner_id: str) -> dict[str, Any]:
        if not self.settings.enabled:
            raise MediaProviderError("PROVIDER_DISABLED", pre_execution=True)
        row = self.store.get(request_id, owner_id=owner_id)
        if not row:
            raise MediaProviderError("JOB_NOT_FOUND", pre_execution=True)
        job = await self.provider.status(request_id, status_url=row.get("status_url"))
        job = MediaJob(
            request_id=job.request_id,
            status=job.status,
            provider=job.provider,
            operation=row["operation"],
            model_path=row["model_path"],
            task_id=row["task_id"],
            outputs=job.outputs,
            error_code=job.error_code,
            correlation_id=job.correlation_id or row.get("correlation_id"),
            estimated_usd=decimal_value(row["estimated_usd"], "estimated_usd") if row.get("estimated_usd") else None,
            updated_at=job.updated_at,
            status_url=job.status_url or row.get("status_url"),
            cancel_url=row.get("cancel_url"),
        )
        self.store.update(request_id, job)
        return job.as_public_dict()

    async def cancel(self, request_id: str, *, owner_id: str) -> dict[str, Any]:
        if not self.settings.enabled:
            raise MediaProviderError("PROVIDER_DISABLED", pre_execution=True)
        row = self.store.get(request_id, owner_id=owner_id)
        if not row:
            raise MediaProviderError("JOB_NOT_FOUND", pre_execution=True)
        job = await self.provider.cancel(request_id, cancel_url=row.get("cancel_url"))
        job = MediaJob(
            request_id=job.request_id,
            status="canceled",
            provider=job.provider,
            operation=row["operation"],
            model_path=row["model_path"],
            task_id=row["task_id"],
            correlation_id=job.correlation_id or row.get("correlation_id"),
            estimated_usd=decimal_value(row["estimated_usd"], "estimated_usd") if row.get("estimated_usd") else None,
            updated_at=job.updated_at,
            status_url=job.status_url or row.get("status_url"),
            cancel_url=row.get("cancel_url"),
        )
        self.store.update(request_id, job)
        self._audit(
            "media.cancel",
            request_id,
            row["task_id"],
            phase="completed",
            owner_id=owner_id,
            model_path=row["model_path"],
        )
        return job.as_public_dict()


def higgsfield_generation_contract_sha256() -> str:
    """Hash the source that governs credential use and paid job execution."""

    digest = hashlib.sha256(b"orqevia.higgsfield-generation-contract.v1\0")
    file_parts = (
        ("media_generation", Path(media_generation_contract.__file__).read_bytes()),
        ("secret_refs", Path(secret_refs_contract.__file__).read_bytes()),
    )
    method_parts = (
        ("provider.credential", inspect.getsource(HiggsfieldApiProvider._credential)),
        ("provider.client", inspect.getsource(HiggsfieldApiProvider._client)),
        ("provider.headers", inspect.getsource(HiggsfieldApiProvider._headers)),
        ("provider.response", inspect.getsource(HiggsfieldApiProvider._json_response)),
        ("provider.estimate", inspect.getsource(HiggsfieldApiProvider.estimate)),
        ("provider.submit", inspect.getsource(HiggsfieldApiProvider.submit)),
        ("provider.status", inspect.getsource(HiggsfieldApiProvider.status)),
        ("provider.cancel", inspect.getsource(HiggsfieldApiProvider.cancel)),
        ("service.submit", inspect.getsource(HiggsfieldMediaService.submit)),
        ("service.status", inspect.getsource(HiggsfieldMediaService.status)),
        ("service.cancel", inspect.getsource(HiggsfieldMediaService.cancel)),
    )
    for name, value in (*file_parts, *method_parts):
        raw = value if isinstance(value, bytes) else value.encode("utf-8")
        raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()
