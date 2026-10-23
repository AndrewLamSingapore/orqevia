"""One fixed notebook-index repair with observed, independently checked receipts.

Only a server-authenticated bound Owner can invoke this adapter. It indexes at
most the existing oldest pending private record, preserves source and access
fields, and cannot execute commands, change permissions or choose file paths.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterator
import uuid

from .agent_notebooks import NotebookPermissionDenied, NotebookPrincipal, get_notebook_store
from .agent_registry import registered_agent_ids
from .collective_intelligence import CollectiveConflict, CollectiveDenied, CollectivePrincipal, canonical_json

ADAPTER = "reindex_notebooks"
MAX_OBSERVED_RECORDS = 10_000
_REPAIR_LOCK = threading.Lock()
_DERIVED_FIELDS = frozenset({"embedding_json", "embedding_model", "embedding_status", "updated_at"})


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=8)
    connection.row_factory = sqlite3.Row
    return connection


def _pending(connection: sqlite3.Connection) -> tuple[int, dict | None]:
    count = connection.execute(
        "SELECT count(*) FROM agent_memory_records WHERE embedding_json IS NULL AND deleted_at IS NULL"
    ).fetchone()[0]
    # Keep the selection identical to the existing index_pending(limit=1).
    row = connection.execute(
        "SELECT * FROM agent_memory_records WHERE embedding_json IS NULL AND deleted_at IS NULL ORDER BY updated_at LIMIT 1"
    ).fetchone()
    return count, dict(row) if row is not None else None


def _protected_digest(row: dict) -> str:
    return _sha({key: value for key, value in row.items() if key not in _DERIVED_FIELDS})


def _metadata(row: dict) -> dict:
    return {
        "memory_id": row["memory_id"],
        "agent_id": row["agent_id"],
        "scope": row["scope"],
        "version": row["version"],
        "content_sha256": row["content_hash"],
        "source_sha256": _sha({key: row[key] for key in ("source", "source_ref", "evidence_refs_json")}),
        "protected_fields_sha256": _protected_digest(row),
    }


def inspect_pending_index() -> dict:
    """Inspect the existing store without disclosing text, paths or credentials."""
    notebooks = get_notebook_store()
    with closing(_connection(notebooks.path)) as connection:
        count, row = _pending(connection)
    return {
        "adapter": ADAPTER,
        "pending": count,
        "oldest": _metadata(row) if row else None,
        "supported_target": row is not None and row["scope"] == "private",
        "scope": "OLDEST_EXISTING_PRIVATE_RECORD_ONLY",
    }


def _snapshot(path: Path, target_id: str) -> dict:
    with closing(_connection(path)) as connection:
        connection.execute("BEGIN")
        total = connection.execute("SELECT count(*) FROM agent_memory_records").fetchone()[0]
        if total > MAX_OBSERVED_RECORDS:
            raise CollectiveConflict("notebook observation exceeds this bounded adapter's record budget")
        signatures = {}
        target = None
        for record in connection.execute("SELECT * FROM agent_memory_records"):
            row = dict(record)
            signatures[row["memory_id"]] = _sha(row)
            if row["memory_id"] == target_id:
                target = row
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    if target is None:
        raise CollectiveConflict("planned notebook record is unavailable")
    return {"row": target, "signatures": signatures, "sqlite_quick_check": quick_check}


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    if not _REPAIR_LOCK.acquire(blocking=False):
        raise CollectiveConflict("a bounded notebook-index repair is already active")
    descriptor = None
    locked = False
    try:
        lock_path = path.with_name(path.name + ".collective-index.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    except BlockingIOError:
        raise CollectiveConflict("a bounded notebook-index repair is already active") from None
    finally:
        if descriptor is not None:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        _REPAIR_LOCK.release()


def _owner(principal: CollectivePrincipal) -> None:
    if not isinstance(principal, CollectivePrincipal) or principal.roles != frozenset({"OWNER"}):
        raise CollectiveDenied("bound Owner authority required for the fixed index repair")
    account = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    expected_owner = hashlib.sha256(account.encode()).hexdigest()
    if (
        not account
        or principal.tenant_id != os.getenv("ORQEVIA_TENANT_ID", "personal")
        or not hmac.compare_digest(principal.owner_id, expected_owner)
    ):
        raise CollectiveDenied("repair is unavailable outside the configured owner scope")


def _vector_valid(row: dict, notebooks) -> bool:
    try:
        values = json.loads(row.get("embedding_json") or "null")
    except (TypeError, ValueError):
        return False
    return (
        isinstance(values, list)
        and 0 < len(values) <= 8192
        and all(type(value) in {int, float} and math.isfinite(value) for value in values)
        and row["embedding_status"] == "indexed"
        and row["embedding_model"] == notebooks._embedding_identity()
    )


def _verify(notebooks, before: dict, target_id: str) -> tuple[dict[str, bool], dict]:
    after = _snapshot(notebooks.path, target_id)
    row = after["row"]
    protected_unchanged = _protected_digest(row) == _protected_digest(before["row"])
    changed = sorted(
        key
        for key in before["signatures"].keys() | after["signatures"].keys()
        if before["signatures"].get(key) != after["signatures"].get(key)
    )
    owner_agent = row["agent_id"]
    own_read = False
    denied = False
    try:
        observed = notebooks.get_record(NotebookPrincipal(owner_agent, "AGENT", owner_agent), target_id)
        own_read = observed["memory_id"] == target_id and observed["content_hash"] == before["row"]["content_hash"]
        other_agent = next(
            agent for agent in sorted(registered_agent_ids(include_orchestrator=False)) if agent != owner_agent
        )
        try:
            notebooks.get_record(NotebookPrincipal(other_agent, "AGENT", other_agent), target_id)
        except NotebookPermissionDenied:
            denied = True
    except (KeyError, ValueError, RuntimeError, sqlite3.Error):
        pass
    content_intact = hashlib.sha256(row["content_json"].encode("utf-8")).hexdigest() == row["content_hash"]
    details = {
        "target": _metadata(row),
        "changed_record_ids": changed,
        "finite_configured_model_vector": bool(_vector_valid(row, notebooks)),
        "protected_fields_unchanged": protected_unchanged,
        "own_agent_read": own_read,
        "other_agent_read_denied": denied,
        "sqlite_quick_check": after["sqlite_quick_check"],
        "content_hash_matches_stored_content": content_intact,
        "new_permissions": False,
    }
    return {
        "outcome": bool(details["finite_configured_model_vector"]),
        "regression": protected_unchanged and changed == [target_id],
        "security": bool(
            own_read and denied and content_intact and after["sqlite_quick_check"] and protected_unchanged
        ),
    }, details


def repair_notebook_index(principal: CollectivePrincipal, gap_id: str, expected_version: int) -> dict:
    """Execute one prepared index repair and retain every failed check visibly."""
    _owner(principal)
    if type(expected_version) is not int or expected_version < 1:
        raise CollectiveConflict("an exact current gap version is required")
    revision = os.getenv("ORQEVIA_RUNTIME_REVISION", "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise CollectiveDenied("a source-bound runtime revision is required")
    environment = os.getenv("ORQEVIA_NODE_ID", "LOCAL").strip() or "LOCAL"
    # Import only at dispatch to avoid a composition cycle with the runtime.
    from .collective_runtime import get_store

    board = get_store()
    notebooks = get_notebook_store()
    with _exclusive(notebooks.path), notebooks._lock:
        gap = board.query(principal, "gaps", gap_id)
        if gap["state"] != "PLANNED" or gap["version"] != expected_version:
            raise CollectiveConflict("repair requires the exact currently planned gap")
        plan_id = gap["data"].get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            raise CollectiveConflict("a prepared remediation plan is required")
        plan = board.query(principal, "remediation_plans", plan_id)
        scope = plan["data"].get("scope")
        if (
            plan["data"].get("gap_id") != gap_id
            or plan["data"].get("adapter") != ADAPTER
            or plan["data"].get("restricted") is not False
            or plan["state"] != "PREPARED"
            or plan["data"].get("environment") != environment
            or gap["data"].get("environment") != environment
            or not isinstance(scope, dict)
            or set(scope) != {"memory_id"}
            or not isinstance(scope["memory_id"], str)
        ):
            raise CollectiveDenied("the prepared plan is outside the fixed index adapter scope")
        with closing(_connection(notebooks.path)) as connection:
            _, oldest = _pending(connection)
        if oldest is None or oldest["memory_id"] != scope["memory_id"]:
            raise CollectiveConflict("planned record is no longer the oldest pending index target")
        if oldest["scope"] != "private":
            raise CollectiveDenied("this bounded repair supports existing private notebook records only")
        before = _snapshot(notebooks.path, oldest["memory_id"])
        if not before["sqlite_quick_check"]:
            raise CollectiveConflict("notebook integrity must pass before repair")
        execution_id = str(uuid.uuid4())
        executor = CollectivePrincipal(
            principal.tenant_id, principal.owner_id, "notebook-index-executor", roles=frozenset({"SYSTEM"})
        )
        verifier = CollectivePrincipal(
            principal.tenant_id, principal.owner_id, "notebook-index-verifier", roles=frozenset({"VERIFIER"})
        )

        def command(actor, operation, data, phase):
            return board.command(actor, operation, data, "notebook-index:" + execution_id + ":" + phase)["record"]

        failure_class = None
        try:
            result = notebooks.index_pending(limit=1)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            failure_class = type(error).__name__
            result = {"indexed": 0, "failed": 1, "examined": 1, "pending": None}
        succeeded = (
            isinstance(result, dict)
            and type(result.get("indexed")) is int
            and result["indexed"] == 1
            and type(result.get("failed")) is int
            and result["failed"] == 0
            and type(result.get("examined")) is int
            and result["examined"] == 1
        )
        execution = command(
            executor,
            "evidence.record",
            {
                "kind": "EXECUTION",
                "source": "fixed-adapter:notebook-index-executor",
                "environment": environment,
                "subject_id": gap_id,
                "content": {
                    "plan_id": plan["id"],
                    "execution_id": execution_id,
                    "candidate_revision": revision,
                    "adapter": ADAPTER,
                    "scope": scope,
                    "outcome": "SUCCEEDED" if succeeded else "FAILED",
                    "result": {key: result.get(key) for key in ("indexed", "failed", "examined", "pending")}
                    if isinstance(result, dict)
                    else {"invalid_adapter_result": True},
                    "failure_class": failure_class,
                    "target_before": _metadata(before["row"]),
                    "generative_model_calls": 0,
                    "embedding_calls_limit": 1,
                },
            },
            "execution",
        )
        gap = command(
            executor,
            "gap.execute",
            {
                "gap_id": gap_id,
                "expected_version": gap["version"],
                "plan_id": plan["id"],
                "evidence_id": execution["id"],
            },
            "attach-execution",
        )
        try:
            checks, observations = _verify(notebooks, before, oldest["memory_id"])
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            checks = {"outcome": False, "regression": False, "security": False}
            observations = {"failure_class": type(error).__name__, "new_permissions": False}
        checks["outcome"] = bool(checks["outcome"] and succeeded)
        verification = command(
            verifier,
            "evidence.record",
            {
                "kind": "VERIFICATION",
                "source": "fixed-checker:notebook-index-verifier",
                "environment": environment,
                "subject_id": gap_id,
                "content": {
                    "plan_id": plan["id"],
                    "execution_id": execution_id,
                    "candidate_revision": revision,
                    "execution_sha256": execution["data"]["sha256"],
                    "checks": checks,
                    "observations": observations,
                    "verification_method": "SEPARATE_SQLITE_CONNECTION_AND_ACTUAL_AGENT_ACCESS_POLICY",
                },
            },
            "verification",
        )
        if succeeded and all(checks.values()):
            gap = command(
                verifier,
                "gap.verify",
                {"gap_id": gap_id, "expected_version": gap["version"], "evidence_id": verification["id"]},
                "verified-close",
            )
        return {
            "adapter": ADAPTER,
            "execution_id": execution_id,
            "environment": environment,
            "gap": {key: gap[key] for key in ("id", "state", "version")},
            "execution_evidence_id": execution["id"],
            "verification_evidence_id": verification["id"],
            "checks": checks,
            "status": "VERIFIED_REPAIRED" if gap["state"] == "CLOSED" else "NOT_VERIFIED_REPAIRED",
            "authority": "NO_NEW_EXECUTION_PERMISSION",
            "generative_model_calls": 0,
        }
