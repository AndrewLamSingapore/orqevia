"""Optional Higgsfield media provider.

Production generation uses the documented asynchronous REST API. The installed
Higgsfield CLI is treated as a bounded, read-only discovery surface and is never
used as a general command runner. This module is not registered as an agent tool
and no caller can fall through from this provider to an unrelated model.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from .action_records import ActionRecord, action_ledger
from .media_generation import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    MediaEstimate,
    MediaJob,
    MediaJobRequest,
    MediaJobStore,
    MediaProviderError,
    decimal_value,
    utcnow,
)
from .secret_refs import SecretUnavailable, resolve_secret


API_BASE_URL = "https://api.higgsfield.ai"
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
        return headers

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
        try:
            async with self._client() as client:
                response = await client.post(f"/estimate/{request.model_path}", headers=headers, json=request.payload)
                body = await self._json_response(response)
        except httpx.TimeoutException:
            raise MediaProviderError("PROVIDER_TIMEOUT") from None
        except httpx.TransportError:
            raise MediaProviderError("PROVIDER_TRANSPORT_FAILURE", retryable=True) from None
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
            await self.sleep(1.5 ** attempt)
        raise last or MediaProviderError("PROVIDER_FAILURE")

    async def status(self, request_id: str, *, status_url: str | None = None) -> MediaJob:
        if not _UUID.fullmatch(request_id):
            raise MediaProviderError("INVALID_REQUEST_ID", pre_execution=True)
        url = _https_url(status_url or f"{self.settings.api_base_url}/requests/{request_id}/status", host="api.higgsfield.ai")
        last: MediaProviderError | None = None
        for attempt in range(3):
            try:
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
                    error_code="PROVIDER_GENERATION_FAILED" if status == "failed" else "PROVIDER_CONTENT_REJECTED" if status == "nsfw" else None,
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
            await self.sleep(2 ** attempt)
        raise last or MediaProviderError("PROVIDER_FAILURE")

    async def cancel(self, request_id: str, *, cancel_url: str | None = None) -> MediaJob:
        if not _UUID.fullmatch(request_id):
            raise MediaProviderError("INVALID_REQUEST_ID", pre_execution=True)
        current = await self.status(request_id)
        if current.status != "queued":
            raise MediaProviderError("JOB_NOT_CANCELABLE", pre_execution=True)
        url = _https_url(cancel_url or f"{self.settings.api_base_url}/requests/{request_id}/cancel", host="api.higgsfield.ai")
        try:
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
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
            "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "HOME",
            "USERNAME", "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE", "SYSTEMDRIVE",
            "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
            "COMSPEC", "ALLUSERSPROFILE", "PUBLIC", "HOMEDRIVE", "HOMEPATH",
            "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
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
            {"display_name": str(item.get("display_name", ""))[:200], "job_type": str(item.get("job_type", ""))[:100], "type": str(item.get("type", ""))[:20]}
            for item in models
            if isinstance(item, dict) and _CLI_NAME.fullmatch(str(item.get("job_type", "")))
        ]
        workflow_rows = [
            {"display_name": str(item.get("display_name", ""))[:200], "job_type": str(item.get("job_type", ""))[:100], "type": str(item.get("type", ""))[:20]}
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


class HiggsfieldMediaService:
    def __init__(
        self,
        settings: HiggsfieldMediaSettings,
        *,
        provider: HiggsfieldApiProvider | None = None,
        discovery: HiggsfieldCliDiscovery | None = None,
        store: MediaJobStore | None = None,
    ):
        self.settings = settings
        self.provider = provider or HiggsfieldApiProvider(settings)
        self.discovery = discovery
        self.store = store or MediaJobStore(settings.database_path)

    def _audit(self, action: str, request_id: str | None, task_id: str, *, phase: str, owner_id: str, model_path: str, **details: Any) -> None:
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
        return {
            "provider": self.provider_id(),
            "enabled": self.settings.enabled,
            "api": self.provider.health(),
            "cli_discovery_configured": self.discovery is not None,
            "execution_authority": "NONE_MEDIA_PROVIDER_ONLY",
        }

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
            self._audit("media.estimate", None, request.task_id, phase="completed", owner_id=owner_id, model_path=request.model_path, estimated_usd=str(estimate.usd))
            return estimate
        except MediaProviderError as error:
            self._audit("media.estimate", None, request.task_id, phase="failed", owner_id=owner_id, model_path=request.model_path, error=error.code)
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
        if self.store.active_count(owner_id=owner_id, provider_id=self.provider_id()) >= self.settings.max_concurrent_jobs:
            raise MediaProviderError("MAX_CONCURRENT_JOBS", pre_execution=True)
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        if self.store.count_since(owner_id=owner_id, provider_id=self.provider_id(), since=since) >= self.settings.max_jobs_per_day:
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
            self._audit("media.submit", job.request_id, request.task_id, phase="completed", owner_id=owner_id, model_path=request.model_path, estimated_usd=str(estimate.usd))
            self.store.update(job.request_id, job)
            return {
                **job.as_public_dict(),
                "idempotency_key": request.idempotency_key,
            }
        except MediaProviderError as error:
            self._audit("media.submit", None, request.task_id, phase="failed", owner_id=owner_id, model_path=request.model_path, error=error.code)
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
        self._audit("media.cancel", request_id, row["task_id"], phase="completed", owner_id=owner_id, model_path=row["model_path"])
        return job.as_public_dict()
