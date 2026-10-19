"""Provider-independent media generation contracts and durable job state.

This module is deliberately separate from the reasoning/model gateway. Media
generation is an optional external capability and never inherits ORQEVIA agent
tool authority. External submission requires explicit cloud data permission,
charge acknowledgement and a bounded cost estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping, Protocol
from .observability import traced


MEDIA_OPERATIONS = frozenset({"image", "video", "audio", "workflow", "3d"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "nsfw", "canceled"})
ACTIVE_STATUSES = frozenset({"submitting", "queued", "in_progress"})
VALID_STATUSES = TERMINAL_STATUSES | ACTIVE_STATUSES
_MODEL_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z")
_SECRET_KEY = re.compile(r"secret|password|token|credential|api.?key|authorization", re.I)


class MediaProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        correlation_id: str | None = None,
        pre_execution: bool = False,
    ):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
        self.correlation_id = correlation_id
        self.pre_execution = pre_execution


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal_value(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MediaProviderError(f"INVALID_{field.upper()}", pre_execution=True) from None
    if not parsed.is_finite() or parsed < 0:
        raise MediaProviderError(f"INVALID_{field.upper()}", pre_execution=True)
    return parsed


def payload_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_json(value: Any, depth: int = 0) -> None:
    if depth > 20:
        raise MediaProviderError("MEDIA_PAYLOAD_TOO_DEEP", pre_execution=True)
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MediaProviderError("MEDIA_PAYLOAD_INVALID_NUMBER", pre_execution=True)
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise MediaProviderError("MEDIA_PAYLOAD_TOO_LARGE", pre_execution=True)
        for item in value:
            _validate_json(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 200:
            raise MediaProviderError("MEDIA_PAYLOAD_TOO_LARGE", pre_execution=True)
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 120:
                raise MediaProviderError("MEDIA_PAYLOAD_INVALID_KEY", pre_execution=True)
            if _SECRET_KEY.search(key):
                raise MediaProviderError("MEDIA_PAYLOAD_CONTAINS_SECRET_FIELD", pre_execution=True)
            _validate_json(item, depth + 1)
        return
    raise MediaProviderError("MEDIA_PAYLOAD_NOT_JSON", pre_execution=True)


@dataclass(frozen=True)
class MediaEstimate:
    usd: Decimal
    credits: Decimal | None = None
    currency: str = "USD"

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "usd": str(self.usd),
            "credits": str(self.credits) if self.credits is not None else None,
            "currency": self.currency,
            "basis": "PROVIDER_ESTIMATE_NOT_INVOICE",
        }


@dataclass(frozen=True)
class MediaJob:
    request_id: str
    status: str
    provider: str
    operation: str
    model_path: str
    task_id: str
    outputs: tuple[dict[str, str], ...] = ()
    error_code: str | None = None
    correlation_id: str | None = None
    estimated_usd: Decimal | None = None
    updated_at: str = ""
    status_url: str | None = None
    cancel_url: str | None = None

    def __post_init__(self):
        if not _UUID.fullmatch(self.request_id):
            raise MediaProviderError("INVALID_REQUEST_ID", pre_execution=True)
        if self.status not in VALID_STATUSES:
            raise MediaProviderError("INVALID_JOB_STATUS", pre_execution=True)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "terminal": self.terminal,
            "provider": self.provider,
            "operation": self.operation,
            "model_path": self.model_path,
            "task_id": self.task_id,
            "outputs": list(self.outputs),
            "error_code": self.error_code,
            "correlation_id": self.correlation_id,
            "estimated_usd": str(self.estimated_usd) if self.estimated_usd is not None else None,
            "cost_basis": "PROVIDER_ESTIMATE_NOT_INVOICE",
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MediaJobRequest:
    task_id: str
    operation: str
    model_path: str
    payload: Mapping[str, Any]
    data_classification: str
    max_cost_usd: Decimal
    charge_authorized: bool
    idempotency_key: str
    timeout_seconds: int = 900

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id.strip() or len(self.task_id) > 256:
            raise MediaProviderError("INVALID_TASK_ID", pre_execution=True)
        if self.operation not in MEDIA_OPERATIONS:
            raise MediaProviderError("UNSUPPORTED_MEDIA_OPERATION", pre_execution=True)
        if (
            not isinstance(self.model_path, str)
            or not _MODEL_PATH.fullmatch(self.model_path)
            or ".." in self.model_path
            or "//" in self.model_path
        ):
            raise MediaProviderError("INVALID_MODEL_PATH", pre_execution=True)
        if not isinstance(self.payload, Mapping):
            raise MediaProviderError("INVALID_MEDIA_PAYLOAD", pre_execution=True)
        clean_payload = dict(self.payload)
        _validate_json(clean_payload)
        if len(json.dumps(clean_payload, separators=(",", ":")).encode("utf-8")) > 64_000:
            raise MediaProviderError("MEDIA_PAYLOAD_TOO_LARGE", pre_execution=True)
        object.__setattr__(self, "payload", clean_payload)
        if self.data_classification not in {"LOCAL_ONLY", "CLOUD_PERMITTED", "SENSITIVE", "RESTRICTED"}:
            raise MediaProviderError("INVALID_DATA_CLASSIFICATION", pre_execution=True)
        if not isinstance(self.max_cost_usd, Decimal):
            object.__setattr__(self, "max_cost_usd", decimal_value(self.max_cost_usd, "max_cost_usd"))
        if self.max_cost_usd <= 0:
            raise MediaProviderError("INVALID_MAX_COST_USD", pre_execution=True)
        if type(self.charge_authorized) is not bool:
            raise MediaProviderError("INVALID_CHARGE_AUTHORIZATION", pre_execution=True)
        if not isinstance(self.idempotency_key, str) or not re.fullmatch(r"[\x21-\x7e]{1,255}", self.idempotency_key):
            raise MediaProviderError("INVALID_IDEMPOTENCY_KEY", pre_execution=True)
        if type(self.timeout_seconds) is not int or not 30 <= self.timeout_seconds <= 3600:
            raise MediaProviderError("INVALID_MEDIA_TIMEOUT", pre_execution=True)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        operation: str,
        model_path: str,
        payload: Mapping[str, Any],
        data_classification: str,
        max_cost_usd: Any,
        charge_authorized: bool,
        idempotency_key: str | None = None,
        timeout_seconds: int = 900,
    ) -> "MediaJobRequest":
        return cls(
            task_id=task_id,
            operation=operation,
            model_path=model_path,
            payload=payload,
            data_classification=data_classification,
            max_cost_usd=decimal_value(max_cost_usd, "max_cost_usd"),
            charge_authorized=charge_authorized,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            timeout_seconds=timeout_seconds,
        )


class MediaProvider(Protocol):
    provider_id: str

    def health(self) -> dict[str, Any]: ...

    async def estimate(self, request: MediaJobRequest) -> MediaEstimate: ...

    async def submit(self, request: MediaJobRequest, estimate: MediaEstimate) -> MediaJob: ...

    async def status(self, request_id: str) -> MediaJob: ...

    async def cancel(self, request_id: str) -> MediaJob: ...


class MediaJobStore:
    """Minimal durable lifecycle store; payloads and credentials are never stored."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS media_jobs (
                idempotency_key TEXT PRIMARY KEY,
                request_sha256 TEXT NOT NULL,
                request_id TEXT UNIQUE,
                task_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                model_path TEXT NOT NULL,
                status TEXT NOT NULL,
                estimated_usd TEXT,
                correlation_id TEXT,
                error_code TEXT,
                outputs_json TEXT NOT NULL DEFAULT '[]',
                status_url TEXT,
                cancel_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS media_jobs_owner_status ON media_jobs(owner_id, provider_id, status)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS media_jobs_created ON media_jobs(created_at)")
        return connection

    @traced("media.db.begin", {"component": "media", "operation": "db_begin"})
    def begin(self, request: MediaJobRequest, *, owner_id: str, provider_id: str) -> dict[str, Any]:
        digest = payload_digest(request.payload)
        now = utcnow()
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT * FROM media_jobs WHERE idempotency_key=?", (request.idempotency_key,)
            ).fetchone()
            if existing:
                if (
                    existing["request_sha256"] != digest
                    or existing["model_path"] != request.model_path
                    or existing["operation"] != request.operation
                    or existing["task_id"] != request.task_id
                ):
                    raise MediaProviderError("IDEMPOTENCY_CONFLICT", pre_execution=True)
                return dict(existing)
            connection.execute(
                """
                INSERT INTO media_jobs(
                    idempotency_key,request_sha256,task_id,owner_id,provider_id,
                    operation,model_path,status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    request.idempotency_key,
                    digest,
                    request.task_id,
                    owner_id,
                    provider_id,
                    request.operation,
                    request.model_path,
                    "submitting",
                    now,
                    now,
                ),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM media_jobs WHERE idempotency_key=?", (request.idempotency_key,)
                ).fetchone()
            )

    def active_count(self, *, owner_id: str, provider_id: str) -> int:
        active = frozenset({"queued", "in_progress"})
        with closing(self._connect()) as connection, connection:
            placeholders = ",".join("?" for _ in active)
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM media_jobs WHERE owner_id=? AND provider_id=? AND status IN ({placeholders})",
                (owner_id, provider_id, *sorted(active)),
            ).fetchone()
            return int(row["count"])

    def count_since(self, *, owner_id: str, provider_id: str, since: str) -> int:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM media_jobs WHERE owner_id=? AND provider_id=? AND created_at>=?",
                (owner_id, provider_id, since),
            ).fetchone()
            return int(row["count"])

    @traced("media.db.update", {"component": "media", "operation": "db_update"})
    def update(self, request_id: str, job: MediaJob) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE media_jobs SET status=?,estimated_usd=?,correlation_id=?,error_code=?,
                    outputs_json=?,status_url=?,cancel_url=?,updated_at=? WHERE request_id=?
                """,
                (
                    job.status,
                    str(job.estimated_usd) if job.estimated_usd is not None else None,
                    job.correlation_id,
                    job.error_code,
                    json.dumps(job.outputs, separators=(",", ":")),
                    job.status_url,
                    job.cancel_url,
                    job.updated_at or utcnow(),
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                raise MediaProviderError("JOB_NOT_FOUND", pre_execution=True)

    @traced("media.db.submitted", {"component": "media", "operation": "db_submitted"})
    def set_submitted(self, idempotency_key: str, job: MediaJob) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE media_jobs SET request_id=?,status=?,estimated_usd=?,correlation_id=?,
                    error_code=?,outputs_json=?,status_url=?,cancel_url=?,updated_at=?
                WHERE idempotency_key=?
                """,
                (
                    job.request_id,
                    job.status,
                    str(job.estimated_usd) if job.estimated_usd is not None else None,
                    job.correlation_id,
                    job.error_code,
                    json.dumps(job.outputs, separators=(",", ":")),
                    job.status_url,
                    job.cancel_url,
                    job.updated_at or utcnow(),
                    idempotency_key,
                ),
            )
            if cursor.rowcount != 1:
                raise MediaProviderError("JOB_NOT_FOUND", pre_execution=True)

    def get_by_idempotency(self, idempotency_key: str, *, owner_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM media_jobs WHERE idempotency_key=? AND owner_id=?",
                (idempotency_key, owner_id),
            ).fetchone()
            return dict(row) if row else None

    def get(self, request_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM media_jobs WHERE request_id=? AND owner_id=?",
                (request_id, owner_id),
            ).fetchone()
            return dict(row) if row else None
