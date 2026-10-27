"""Service observations and operational incidents from an existing host collector.

No network, Docker, startup, credential, or model APIs are used here. The host
publishes an atomic, aggregate-only receipt through a read-only mount. Reading
the receipt may reconcile its original observations into a small local journal;
replaying it does not create another incident or refresh an observation date.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

RECEIPT_SCHEMA = "orqevia.operational-observation.v1"
CANARY_SCHEMA = "orqevia.full-stack-canary.v1"
CANARY_MAX_AGE_SECONDS = 1200  # Two periods of the observed ten-minute task.
RESOLVED_RETENTION_SECONDS = 30 * 86400
RESOLVED_RETENTION_COUNT = 500
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_STATES = {"PASS", "FAIL", "UNKNOWN", "NOT_CONFIGURED"}

# A process observation is separate from each declared functional observation.
# Model inventory and controller heartbeat scopes do not certify inference or
# coaching quality. A tunnel needs current connections AND its HTTPS journey.
SERVICE_SPECS = {
    "backend": (
        "orqevia-epoch-20261016-backend-1",
        True,
        {"backend-health": "DOCKER_HEALTHCHECK", "backend-readiness": "DEPENDENCY"},
    ),
    "interface": ("orqevia-epoch-20261016-interface-1", True, {"interface-https": "HTTPS_READINESS"}),
    "ollama": ("orqevia-epoch-20261016-ollama-1", True, {"model-inventory": "DEPENDENCY"}),
    "intelligence": ("orqevia-intelligence-1", True, {"intelligence-https": "HTTPS_READINESS"}),
    "coaching": ("orqevia-coaching-coaching-1", True, {"controller-heartbeat": "DEPENDENCY"}),
    "otel-collector": ("orqevia-epoch-20261016-otel-collector-1", False, {"otel-export": "TELEMETRY"}),
    "integration-gateway": (
        "orqevia-epoch-20261016-integration-gateway-1",
        False,
        {"gateway-https": "HTTPS_READINESS"},
    ),
    "cloudflared": (
        "orqevia-epoch-20261016-cloudflared-1",
        False,
        {"tunnel-connection": "DEPENDENCY", "tunnel-https": "HTTPS_READINESS"},
    ),
    "cloudflared-dual": (
        "orqevia-epoch-20261016-cloudflared-dual-1",
        False,
        {"tunnel-connection": "DEPENDENCY", "tunnel-https": "HTTPS_READINESS"},
    ),
}
COLLECTOR_CHECKS = ("collector-source", "host-identity", "boot-identity")
CANARY_CHECKS = {
    "docker-engine": "CRITICAL",
    "persistent-containers": "CRITICAL",
    "backend-health": "CRITICAL",
    "cloud-inference-configuration": "DEGRADED",
    "interface-local": "CRITICAL",
    "cloudflare-tunnel": "DEGRADED",
    "auth-boundary": "DEGRADED",
    "host-telemetry-freshness": "DEGRADED",
    "model-runtime": "CRITICAL",
    "fabrics-and-ai-scaffold-imports": "DEGRADED",
    "agent-liveness-receipt": "DEGRADED",
    "deployment-identity": "DEGRADED",
    "queue-runtime-and-cost": "DEGRADED",
    "workflow-and-notebook-persistence": "DEGRADED",
    "rollback-readiness": "DEGRADED",
    "permanent-supervision-tasks": "DEGRADED",
}


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


def _epoch(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        result = parsed.timestamp() if parsed.tzinfo is not None else None
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, OverflowError, OSError):
        return None


def _code(value, fallback):
    return value if isinstance(value, str) and _CODE.fullmatch(value) else fallback


def _source(value):
    if not isinstance(value, str) or len(value) > 240 or any(ord(c) < 32 for c in value):
        return None
    if "://" in value:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
        return value
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}", value) else None


def _unique_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("Object required")
    return value


def _rows(value, key):
    if not isinstance(value, list) or len(value) > 100:
        return {}, False
    result = {}
    valid = True
    for row in value:
        name = row.get(key) if isinstance(row, dict) else None
        if not isinstance(name, str) or name in result:
            valid = False
        else:
            result[name] = row
    return result, valid


def _check(row, *, key, check_id, service_id, kind, now, ttl, severity="CRITICAL"):
    value = {
        "check_key": key,
        "check_id": check_id,
        "service_id": service_id,
        "kind": kind,
        "status": "NOT_CONFIGURED",
        "state": "NOT_CONFIGURED",
        "reason": "CHECK_NOT_CONFIGURED",
        "observed_at": None,
        "last_success_at": None,
        "first_failure_at": None,
        "source": None,
        "scope": "UNSPECIFIED",
        "severity": severity,
        "fresh": False,
    }
    if not isinstance(row, dict):
        return value
    status = row.get("status")
    value.update(source=_source(row.get("source")), scope=_code(row.get("scope"), "UNSPECIFIED"))
    if status not in _STATES or row.get("kind", kind) != kind:
        return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "INVALID_CHECK"}
    value.update(status=status, reason=_code(row.get("reason"), "CHECK_" + status))
    stamp = _epoch(row.get("observed_at"))
    if stamp is not None:
        value["observed_at"] = row["observed_at"]
    last_success = _epoch(row.get("last_success_at"))
    if last_success is not None and stamp is not None and last_success <= stamp:
        value["last_success_at"] = row["last_success_at"]
    first_failure = _epoch(row.get("first_failure_at"))
    if first_failure is not None and stamp is not None and first_failure <= stamp:
        value["first_failure_at"] = row["first_failure_at"]
    if status == "NOT_CONFIGURED":
        return value
    if stamp is None or stamp > now + 5:
        return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "INVALID_OBSERVATION_TIME"}
    if now - stamp > ttl:
        return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "STALE_OBSERVATION"}
    if status == "UNKNOWN":
        return {**value, "state": "UNKNOWN"}
    if value["source"] is None or value["scope"] == "UNSPECIFIED":
        return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "CHECK_PROVENANCE_UNAVAILABLE"}
    if kind == "HTTPS_READINESS":
        value["certificate_verified"] = row.get("certificate_verified") is True
        if not value["source"].startswith("https://") or (status == "PASS" and not value["certificate_verified"]):
            return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "HTTPS_CERTIFICATE_NOT_VERIFIED"}
    # The existing /interface/v1/health's constant READY is configuration
    # information. It cannot by itself establish backend worker readiness.
    if (
        service_id == "backend"
        and check_id == "backend-readiness"
        and value["scope"] in {"CONFIGURATION_LIVENESS", "INTERFACE_READY", "INTERFACE_HEALTH", "PROCESS_RUNNING"}
    ):
        return {**value, "status": "UNKNOWN", "state": "UNKNOWN", "reason": "BACKEND_READINESS_NOT_MEASURED"}
    value.update(fresh=True, state="HEALTHY" if status == "PASS" else severity)
    if status == "PASS":
        value["last_success_at"] = value["observed_at"]
    elif value["first_failure_at"] is None:
        value["first_failure_at"] = value["observed_at"]
    return value


def _aggregate(checks):
    states = {row["state"] for row in checks}
    for state in ("CRITICAL", "DEGRADED", "UNKNOWN", "NOT_CONFIGURED"):
        if state in states:
            return state
    return "HEALTHY" if checks else "NOT_CONFIGURED"


def _service(service_id, row, now, ttl, unavailable_reason=None):
    container, docker_required, required = SERVICE_SPECS[service_id]
    row = row if isinstance(row, dict) else {}
    process = row.get("process_state", "UNKNOWN")
    process = process.lower() if isinstance(process, str) else "unknown"
    if process not in {"running", "exited", "dead", "paused", "restarting", "created", "missing", "unknown"}:
        process = "unknown"
    process_row = {
        "status": "PASS" if process == "running" else "UNKNOWN" if process == "unknown" else "FAIL",
        "observed_at": row.get("observed_at"),
        "source": "docker-inspect:" + container,
        "scope": "PROCESS_ONLY",
        "reason": "PROCESS_RUNNING"
        if process == "running"
        else "PROCESS_STATE_UNAVAILABLE"
        if process == "unknown"
        else "PROCESS_NOT_RUNNING",
    }
    checks = [
        _check(
            process_row,
            key=f"service:{service_id}:process",
            check_id="process",
            service_id=service_id,
            kind="PROCESS",
            now=now,
            ttl=ttl,
        )
    ]
    docker = row.get("docker_health")
    docker_check = _check(
        {
            "status": "PASS"
            if docker == "healthy"
            else "FAIL"
            if docker == "unhealthy"
            else "NOT_CONFIGURED"
            if docker in (None, "none", "NO_HEALTHCHECK")
            else "UNKNOWN",
            "observed_at": row.get("health_observed_at"),
            "last_success_at": row.get("health_last_success_at"),
            "source": "docker-healthcheck:" + container,
            "scope": "DECLARED_HEALTHCHECK_ONLY",
        },
        key=f"service:{service_id}:docker-health",
        check_id="docker-health",
        service_id=service_id,
        kind="DOCKER_HEALTHCHECK",
        now=now,
        ttl=ttl,
    )
    if docker_required:
        checks.append(docker_check)
    supplied, rows_valid = _rows(row.get("checks", []), "check_id")
    for check_id, kind in required.items():
        checks.append(
            _check(
                supplied.get(check_id),
                key=f"service:{service_id}:{check_id}",
                check_id=check_id,
                service_id=service_id,
                kind=kind,
                now=now,
                ttl=ttl,
            )
        )
    reason = unavailable_reason
    if row.get("container_name") != container:
        reason = reason or ("SERVICE_OBSERVATION_MISSING" if not row else "CONTAINER_IDENTITY_MISMATCH")
    if not rows_valid or set(supplied) - set(required):
        reason = reason or "INVALID_SERVICE_CHECK_INVENTORY"
    if reason:
        for check in checks:
            check.update(status="UNKNOWN", state="UNKNOWN", fresh=False, reason=reason)
    state = _aggregate(checks)
    observed = [_epoch(check["observed_at"]) for check in checks if _epoch(check["observed_at"]) is not None]
    successful = [_epoch(check["last_success_at"]) for check in checks]
    complete = all(check["fresh"] for check in checks)
    return {
        "service_id": service_id,
        "container_name": container,
        "status": state,
        "reason": next((check["reason"] for check in checks if check["state"] == state), "CHECKS_PASSED"),
        "observed_at": _iso(min(observed)) if observed else None,
        "last_success_at": _iso(min(successful)) if all(v is not None for v in successful) else None,
        "process_state": process.upper(),
        "docker_health": docker_check,
        "coverage_complete": complete,
        "checks": checks,
        "scope": "DECLARED_SERVICE_CHECKS_ONLY",
    }


def _journal(path, checks, now, boot_id):
    """Reconcile only fresh, monotonic PASS/FAIL observations in one transaction."""
    observations = [c for c in checks if c["fresh"] and c["status"] in {"PASS", "FAIL"}]
    if not observations and not path.is_file():
        return {
            "status": "NOT_CONFIGURED",
            "incidents": [],
            "transitions": [],
            "known_critical_count": 0,
            "known_open_count": 0,
            "last_success": {},
            "conflicts": False,
        }
    db = None
    try:
        if observations:
            path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(path, timeout=1)
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operational_checks(
                    check_key TEXT PRIMARY KEY, status TEXT NOT NULL, observed_at REAL NOT NULL,
                    last_success_at REAL, boot_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operational_incidents(
                    id INTEGER PRIMARY KEY, incident_key TEXT NOT NULL, service_id TEXT NOT NULL,
                    check_id TEXT NOT NULL, severity TEXT NOT NULL, state TEXT NOT NULL,
                    reason TEXT NOT NULL, source TEXT, opened_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL, last_success_at REAL, recovered_at REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_operational_incident
                    ON operational_incidents(incident_key) WHERE state='OPEN';
                CREATE TABLE IF NOT EXISTS operational_incident_transitions(
                    id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES operational_incidents(id) ON DELETE CASCADE,
                    transition TEXT NOT NULL, observed_at REAL NOT NULL,
                    UNIQUE(incident_id,transition));
            """)
            db.execute("BEGIN IMMEDIATE")
        else:
            db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
            db.execute("PRAGMA query_only=ON")
        db.row_factory = sqlite3.Row
        conflicts = False
        for check in observations:
            stamp = _epoch(check["observed_at"])
            previous = db.execute(
                "SELECT * FROM operational_checks WHERE check_key=?", (check["check_key"],)
            ).fetchone()
            if previous and stamp <= previous["observed_at"]:
                if stamp < previous["observed_at"] or previous["status"] != check["status"]:
                    conflicts = True
                continue
            success = _epoch(check["last_success_at"])
            if previous and previous["last_success_at"] is not None:
                success = max(
                    success if success is not None else previous["last_success_at"], previous["last_success_at"]
                )
            db.execute(
                "INSERT INTO operational_checks VALUES(?,?,?,?,?) ON CONFLICT(check_key) DO UPDATE SET "
                "status=excluded.status,observed_at=excluded.observed_at,last_success_at=excluded.last_success_at,boot_id=excluded.boot_id",
                (check["check_key"], check["status"], stamp, success, boot_id),
            )
            incident = db.execute(
                "SELECT * FROM operational_incidents WHERE incident_key=? AND state='OPEN'", (check["check_key"],)
            ).fetchone()
            if check["status"] == "FAIL":
                first = _epoch(check["first_failure_at"])
                first = first if first is not None and (success is None or first > success) else stamp
                if incident:
                    db.execute(
                        "UPDATE operational_incidents SET last_observed_at=?,reason=?,source=?,last_success_at=?,opened_at=MIN(opened_at,?) WHERE id=?",
                        (stamp, check["reason"], check["source"], success, first, incident["id"]),
                    )
                    db.execute(
                        "UPDATE operational_incident_transitions SET observed_at=MIN(observed_at,?) WHERE incident_id=? AND transition='OPENED'",
                        (first, incident["id"]),
                    )
                else:
                    cursor = db.execute(
                        "INSERT INTO operational_incidents(incident_key,service_id,check_id,severity,state,reason,source,opened_at,last_observed_at,last_success_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            check["check_key"],
                            check["service_id"],
                            check["check_id"],
                            check["severity"],
                            "OPEN",
                            check["reason"],
                            check["source"],
                            first,
                            stamp,
                            success,
                        ),
                    )
                    db.execute(
                        "INSERT INTO operational_incident_transitions(incident_id,transition,observed_at) VALUES(?,?,?)",
                        (cursor.lastrowid, "OPENED", first),
                    )
            elif incident:
                db.execute(
                    "UPDATE operational_incidents SET state='RECOVERED',recovered_at=?,last_observed_at=?,last_success_at=? WHERE id=?",
                    (stamp, stamp, stamp, incident["id"]),
                )
                db.execute(
                    "INSERT INTO operational_incident_transitions(incident_id,transition,observed_at) VALUES(?,?,?)",
                    (incident["id"], "RECOVERED", stamp),
                )
        if observations:
            db.execute(
                "DELETE FROM operational_incidents WHERE state='RECOVERED' AND (recovered_at<? OR id NOT IN "
                "(SELECT id FROM operational_incidents WHERE state='RECOVERED' ORDER BY recovered_at DESC,id DESC LIMIT ?))",
                (now - RESOLVED_RETENTION_SECONDS, RESOLVED_RETENTION_COUNT),
            )
            db.commit()
        incidents = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM operational_incidents WHERE state='OPEN' ORDER BY severity,opened_at,id"
            )
        ]
        critical = sum(row["severity"] == "CRITICAL" for row in incidents)
        transitions = [
            dict(row)
            for row in db.execute(
                "SELECT t.incident_id,t.transition,t.observed_at,i.incident_key FROM operational_incident_transitions t JOIN operational_incidents i ON i.id=t.incident_id ORDER BY t.id DESC LIMIT 100"
            )
        ]
        success = {
            row["check_key"]: row["last_success_at"]
            for row in db.execute("SELECT check_key,last_success_at FROM operational_checks")
        }
        for incident in incidents:
            for field in ("opened_at", "last_observed_at", "last_success_at", "recovered_at"):
                incident[field] = _iso(incident[field])
        for transition in transitions:
            transition["observed_at"] = _iso(transition["observed_at"])
        return {
            "status": "OBSERVED",
            "incidents": incidents,
            "transitions": transitions,
            "known_critical_count": critical,
            "known_open_count": len(incidents),
            "last_success": success,
            "conflicts": conflicts,
        }
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        return {
            "status": "UNAVAILABLE",
            "incidents": [],
            "transitions": [],
            "known_critical_count": None,
            "known_open_count": None,
            "last_success": {},
            "conflicts": False,
        }
    finally:
        if db is not None:
            db.close()


def operational_health_snapshot(*, receipt_path=None, data_dir=None, now=None):
    """Return ``service_health`` and ``critical_issues`` for workspace telemetry.

    Missing or unmeasured sources never become a healthy empty result. Critical
    count is authoritative only after every declared check and journal query
    succeeds; the known open count is explicitly separate during missing coverage.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("Finite observation time required")
    raw_path = os.getenv("ORQEVIA_OPERATIONAL_HEALTH_RECEIPT", "") if receipt_path is None else str(receipt_path)
    configured = bool(raw_path)
    receipt = {}
    reason = "COLLECTOR_NOT_CONFIGURED" if not configured else None
    ttl = CANARY_MAX_AGE_SECONDS
    if configured:
        try:
            path = Path(raw_path)
            if not path.is_absolute() or path.stat().st_size > 2_000_000:
                raise ValueError("Invalid receipt path/size")
            receipt = _unique_json(path.read_bytes())
            if receipt.get("schema_version") != RECEIPT_SCHEMA:
                raise ValueError("Invalid receipt schema")
            cadence = receipt.get("cadence_seconds")
            if type(cadence) is not int or not 1 <= cadence <= 600:
                raise ValueError("Invalid collector cadence")
            ttl = cadence * 2
            stamp = _epoch(receipt.get("observed_at"))
            if stamp is None or stamp > now + 5:
                reason = "INVALID_RECEIPT_TIME"
            elif now - stamp > ttl:
                reason = "COLLECTOR_RECEIPT_STALE"
            for field in ("host_id", "boot_id"):
                if not isinstance(receipt.get(field), str) or not receipt[field] or len(receipt[field]) > 128:
                    reason = reason or "HOST_BOOT_IDENTITY_UNAVAILABLE"
            expected_host = os.getenv("ORQEVIA_INTERFACE_HOST_ID", "")
            expected_boot = os.getenv("ORQEVIA_HOST_BOOT_ID", "")
            if expected_host and expected_host != "UNKNOWN" and receipt.get("host_id") != expected_host:
                reason = "HOST_IDENTITY_MISMATCH"
            if expected_boot and receipt.get("boot_id") != expected_boot:
                reason = "BOOT_IDENTITY_MISMATCH"
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            reason = "COLLECTOR_RECEIPT_UNAVAILABLE_OR_INVALID"
    service_rows, inventory_valid = _rows(receipt.get("services", []), "service_id")
    inventory_valid = inventory_valid and set(service_rows) == set(SERVICE_SPECS)
    services = [_service(name, service_rows.get(name), now, ttl, reason) for name in SERVICE_SPECS]
    collector_rows, collector_valid = _rows(receipt.get("collector_checks", []), "check_id")
    collectors = [
        _check(
            collector_rows.get(name),
            key="collector:" + name,
            check_id=name,
            service_id="collector",
            kind="CONFIGURATION",
            now=now,
            ttl=ttl,
            severity="DEGRADED",
        )
        for name in COLLECTOR_CHECKS
    ]
    collector_valid = collector_valid and set(collector_rows) == set(COLLECTOR_CHECKS)
    canary = receipt.get("canary")
    canary = canary if isinstance(canary, dict) else {}
    canary_rows, canary_valid = _rows(canary.get("checks", []), "name")
    canary_stamp = _epoch(canary.get("observed_at_utc"))
    canary_valid = (
        canary_valid
        and canary.get("schema_version") == CANARY_SCHEMA
        and set(canary_rows) == set(CANARY_CHECKS)
        and canary.get("check_count") == len(CANARY_CHECKS)
        and canary_stamp is not None
        and -5 <= now - canary_stamp <= CANARY_MAX_AGE_SECONDS
    )
    failures = sum(row.get("status") == "FAIL" for row in canary_rows.values())
    canary_valid = (
        canary_valid
        and type(canary.get("failed_count")) is int
        and canary["failed_count"] == failures
        and canary.get("overall") == ("FAIL" if failures else "PASS")
    )
    histories = receipt.get("canary_check_history", {})
    histories = histories if isinstance(histories, dict) else {}
    canary_checks = []
    for name, severity in CANARY_CHECKS.items():
        row = canary_rows.get(name)
        if isinstance(row, dict):
            history = histories.get(name, {})
            history = history if isinstance(history, dict) else {}
            row = {
                **history,
                **row,
                "kind": "CANARY",
                "source": "full-stack-canary:" + name,
                "scope": "EXISTING_CANARY_CHECK_ONLY",
            }
        canary_checks.append(
            _check(
                row,
                key="canary:" + name,
                check_id=name,
                service_id="canary",
                kind="CANARY",
                now=now,
                ttl=CANARY_MAX_AGE_SECONDS,
                severity=severity,
            )
        )
    if not canary_valid:
        for check in canary_checks:
            check.update(fresh=False, state="UNKNOWN", status="UNKNOWN", reason="CANARY_RECEIPT_UNAVAILABLE_OR_INVALID")
    source_verified = collector_valid and all(row["fresh"] and row["status"] == "PASS" for row in collectors)
    if not source_verified and not reason:
        for service in services:
            service.update(status="UNKNOWN", reason="COLLECTOR_PROVENANCE_UNAVAILABLE", coverage_complete=False)
            for check in service["checks"]:
                check.update(fresh=False, state="UNKNOWN", status="UNKNOWN", reason="COLLECTOR_PROVENANCE_UNAVAILABLE")
        for check in canary_checks:
            check.update(fresh=False, state="UNKNOWN", status="UNKNOWN", reason="COLLECTOR_PROVENANCE_UNAVAILABLE")
    all_checks = [check for service in services for check in service["checks"]] + collectors + canary_checks
    if reason:
        for check in all_checks:
            check.update(
                fresh=False, state="NOT_CONFIGURED" if not configured else "UNKNOWN", status="UNKNOWN", reason=reason
            )
        for service in services:
            service.update(
                status="NOT_CONFIGURED" if not configured else "UNKNOWN", reason=reason, coverage_complete=False
            )
    root = Path(data_dir if data_dir is not None else os.getenv("ORQEVIA_DATA_DIR", "/data"))
    journal = _journal(root / "operational-health.db", all_checks, now, receipt.get("boot_id", "UNKNOWN"))
    for check in all_checks:
        prior = journal["last_success"].get(check["check_key"])
        if prior is not None:
            check["last_success_at"] = _iso(prior)
    for service in services:
        successes = [_epoch(check["last_success_at"]) for check in service["checks"]]
        service["last_success_at"] = _iso(min(successes)) if all(value is not None for value in successes) else None
    service_complete = inventory_valid and all(row["coverage_complete"] for row in services)
    collector_complete = collector_valid and all(row["fresh"] for row in collectors)
    canary_complete = canary_valid and all(row["fresh"] for row in canary_checks)
    complete = (
        not reason
        and service_complete
        and collector_complete
        and canary_complete
        and journal["status"] == "OBSERVED"
        and not journal["conflicts"]
    )
    status = _aggregate(all_checks)
    if reason:
        status = "NOT_CONFIGURED" if not configured else "UNKNOWN"
    elif status == "HEALTHY" and not complete:
        status = "UNKNOWN"
    count = journal["known_critical_count"] if complete else None
    count_reason = (
        "MONITORING_COMPLETE"
        if complete
        else "INCIDENT_STORE_UNAVAILABLE"
        if journal["status"] == "UNAVAILABLE"
        else "OBSERVATION_REGRESSION_OR_CONFLICT"
        if journal["conflicts"]
        else reason or "MONITORING_COVERAGE_INCOMPLETE"
    )
    latest_success = [_epoch(row["last_success_at"]) for row in all_checks]
    last_success_at = (
        _iso(min(latest_success)) if latest_success and all(value is not None for value in latest_success) else None
    )
    return {
        "service_health": {
            "schema_version": "orqevia.service-health.v1",
            "status": status,
            "reason": reason or count_reason,
            "observed_at": receipt.get("observed_at") if _epoch(receipt.get("observed_at")) is not None else None,
            "evaluated_at": _iso(now),
            "last_success_at": last_success_at,
            "host_id": receipt.get("host_id"),
            "boot_id": receipt.get("boot_id"),
            "cadence_seconds": receipt.get("cadence_seconds"),
            "freshness_seconds": ttl,
            "services": services,
            "collector_checks": collectors,
            "canary_checks": canary_checks,
            "coverage": {
                "complete": complete,
                "expected_service_count": len(SERVICE_SPECS),
                "observed_service_count": sum(row["coverage_complete"] for row in services),
                "healthy_service_count": sum(row["status"] == "HEALTHY" for row in services),
                "inventory_complete": inventory_valid,
                "service_checks_complete": service_complete,
                "collector_checks_complete": collector_complete,
                "canary_checks_complete": canary_complete,
                "canary_observed_at": canary.get("observed_at_utc"),
                "canary_freshness_seconds": CANARY_MAX_AGE_SECONDS,
                "unmeasured_service_ids": [row["service_id"] for row in services if not row["coverage_complete"]],
            },
            "limits": [
                "DECLARED_CHECKS_ONLY",
                "PROCESS_RUNNING_IS_NOT_READINESS",
                "MODEL_INVENTORY_IS_NOT_INFERENCE_ACCEPTANCE",
                "CANARY_INTERFACE_READY_IS_NOT_BACKEND_READINESS",
                "NO_NEW_NETWORK_OR_MODEL_CALLS",
            ],
        },
        "critical_issues": {
            "schema_version": "orqevia.operational-incidents.v1",
            "status": status,
            "reason": count_reason,
            "critical_count": count,
            "known_critical_count": journal["known_critical_count"],
            "known_open_count": journal["known_open_count"],
            "coverage_complete": complete,
            "store_status": journal["status"],
            "observed_at": receipt.get("observed_at") if _epoch(receipt.get("observed_at")) is not None else None,
            "evaluated_at": _iso(now),
            "last_success_at": last_success_at,
            "incidents": journal["incidents"],
            "transitions": journal["transitions"],
            "retention": {
                "resolved_days": RESOLVED_RETENTION_SECONDS // 86400,
                "resolved_incidents": RESOLVED_RETENTION_COUNT,
                "open_incidents_preserved": True,
            },
            "limits": [
                "KNOWN_COUNT_IS_NOT_AUTHORITATIVE_CURRENT_COUNT",
                "STALE_OR_UNKNOWN_NEVER_RECOVERS_AN_INCIDENT",
                "GEOSPATIAL_ALERTS_ARE_SEPARATE",
                "CHECK_SCOPED_INCIDENTS_MAY_SHARE_A_CAUSE",
                "CONTINUOUS_REFRESH_REQUIRES_EXISTING_COLLECTOR_HTTPS_HOOK",
            ],
        },
    }
