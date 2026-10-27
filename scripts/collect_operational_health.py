"""Bounded, content-free producer for the existing Windows host sampler hook.

Run only through the fixed sibling PowerShell wrapper. No daemon, admission
guard, model generation, private HTTP probe, application import, or runtime
mutation is performed. Docker commands observe existing metadata and stores.
"""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("C:/ProgramData/ABEX/PrimeHostMetrics")
CANARY_ROOT = Path("C:/Users/Admin/Documents/ABEX/operations/permanent-readiness-20261017")
DOCKER = "C:/Program Files/Docker/Docker/resources/bin/docker.exe"
ORIGIN = "https://localhost:8443"
SERVICES = {
    "backend": (
        "orqevia-epoch-20261016-backend-1",
        {"backend-health": "DOCKER_HEALTHCHECK", "backend-readiness": "DEPENDENCY"},
    ),
    "interface": ("orqevia-epoch-20261016-interface-1", {"interface-https": "HTTPS_READINESS"}),
    "ollama": ("orqevia-epoch-20261016-ollama-1", {"model-inventory": "DEPENDENCY"}),
    "intelligence": ("orqevia-intelligence-1", {"intelligence-https": "HTTPS_READINESS"}),
    "coaching": ("orqevia-coaching-coaching-1", {"controller-heartbeat": "DEPENDENCY"}),
    "otel-collector": ("orqevia-epoch-20261016-otel-collector-1", {"otel-export": "TELEMETRY"}),
    "integration-gateway": ("orqevia-epoch-20261016-integration-gateway-1", {"gateway-https": "HTTPS_READINESS"}),
    "cloudflared": (
        "orqevia-epoch-20261016-cloudflared-1",
        {"tunnel-connection": "DEPENDENCY", "tunnel-https": "HTTPS_READINESS"},
    ),
    "cloudflared-dual": (
        "orqevia-epoch-20261016-cloudflared-dual-1",
        {"tunnel-connection": "DEPENDENCY", "tunnel-https": "HTTPS_READINESS"},
    ),
}
INSPECT_FORMAT = (
    '{"container_id":{{json .Id}},"name":{{json .Name}},"process_state":{{json .State.Status}},'
    '"started_at":{{json .State.StartedAt}},"network_mode":{{json .HostConfig.NetworkMode}},'
    '"source_revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
    '"docker_health":{{with (index .State "Health")}}{{json .Status}}{{else}}null{{end}},'
    '"health_observations":[{{with (index .State "Health")}}{{range $i,$r:=.Log}}{{if $i}},{{end}}'
    '{"observed_at":{{json $r.End}},"exit_code":{{$r.ExitCode}}}{{end}}{{end}}]}'
)
BACKEND_READ = """
import datetime,json,os,pathlib,sqlite3
def read(path,sql):
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
    try:
        c.execute('PRAGMA query_only=ON'); return c.execute(sql).fetchone()
    finally: c.close()
try:
    root=pathlib.Path(os.getenv('ORQEVIA_DATA_DIR','/data'))
    queue=pathlib.Path(os.getenv('ORQEVIA_COMPUTE_QUEUE_DB',str(root/'compute-queue.db')))
    queue_count=read(queue,'SELECT COUNT(*) FROM compute_jobs')[0]
    objective_path=pathlib.Path(os.getenv('PRIME_DATA_DIR','/data'))/'objectives.db'
    objective_count=read(objective_path,'SELECT COUNT(*) FROM objectives')[0]
    execution=read(queue,'SELECT MAX(started_at),MAX(completed_at) FROM compute_jobs')
    model_keys=('ORQEVIA_FAST_MODEL','ORQEVIA_DEEP_MODEL','ORQEVIA_EVALUATOR_MODEL','ORQEVIA_EMBED_MODEL')
    result={'database_read':True,'queue_record_count':queue_count,'objective_record_count':objective_count,
        'worker_started_at':execution[0], 'worker_completed_at':execution[1],
        'required_models':list(dict.fromkeys(os.getenv(k,'') for k in model_keys if os.getenv(k,'')))}
except (OSError,sqlite3.Error,ValueError): result={'database_read':False}
result['observed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
print(json.dumps(result))
"""
COACHING_READ = """
import json,pathlib,sqlite3
c=sqlite3.connect(pathlib.Path('/data/agent-coaching.db').as_uri()+'?mode=ro',uri=True,timeout=1)
try:
    c.execute('PRAGMA query_only=ON')
    row=c.execute('SELECT source_revision,last_tick_epoch FROM coaching_controller WHERE id=1').fetchone()
    print(json.dumps({'source_revision':row[0],'tick_epoch':row[1]} if row else {}))
finally: c.close()
"""


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def epoch(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.timestamp() if stamp.tzinfo else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def load_json(path, maximum=2_000_000):
    if path.stat().st_size > maximum or path.is_symlink():
        raise ValueError("Invalid observation file")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Observation object required")
    return value


def check(name, kind, status, observed_at, reason, source, scope, **extra):
    return {
        "check_id": name,
        "kind": kind,
        "status": status,
        "observed_at": observed_at,
        "last_success_at": observed_at if status == "PASS" else None,
        "reason": reason,
        "source": source,
        "scope": scope,
        **extra,
    }


class Budget:
    def __init__(self, seconds=22):
        self.deadline = time.monotonic() + seconds

    def remaining(self, maximum):
        remaining = min(maximum, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Collection budget exhausted")
        return remaining


class Runner:
    def __init__(self, budget):
        self.budget = budget

    def run(self, args, *, script=None, timeout=3):
        result = subprocess.run(
            args,
            input=script,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.budget.remaining(timeout),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Log exporter output uses stderr; never emit either raw stream.
        output = result.stdout + (result.stderr if "logs" in args else "")
        if len(output.encode("utf-8")) > 131072:
            raise ValueError("Observation output too large")
        return result.returncode, output


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Functional checks must observe the fixed requested endpoint.


def https_read(path, context, timeout, *, read_body=True):
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Fixed HTTPS path required")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context)
    )
    with opener.open(ORIGIN + path, timeout=timeout) as response:
        if not read_body:
            return response.status, b""
        body = response.read(131073)
        if len(body) > 131072:
            raise ValueError("Observation response too large")
        return response.status, body


def tls_check(name, path, context, budget, *, intelligence=False, reader=https_read):
    try:
        status, raw = reader(path, context, budget.remaining(3))
        if intelligence:
            body = json.loads(raw)
            passed = (
                status == 200
                and body.get("ok") is True
                and type(body.get("observation_count")) is int
                and body["observation_count"] >= 0
            )
        else:
            passed = status == 200 and b"ORQEVIA" in raw
        return check(
            name,
            "HTTPS_READINESS",
            "PASS" if passed else "FAIL",
            iso(time.time()),
            "HTTPS_READINESS_PASSED" if passed else "HTTPS_RESPONSE_INVALID",
            ORIGIN + path,
            "INTELLIGENCE_DATABASE_READ" if intelligence else "HTTPS_STATIC_ENTRYPOINT",
            certificate_verified=True,
        )
    except TimeoutError:
        status, reason = "UNKNOWN", "COLLECTION_BUDGET_OR_TIMEOUT"
    except urllib.error.HTTPError:
        status, reason = "FAIL", "HTTPS_HTTP_ERROR"
    except (urllib.error.URLError, ssl.SSLError, OSError):
        status, reason = "FAIL", "HTTPS_VERIFIED_CONNECTION_FAILED"
    except (ValueError, TypeError):
        status, reason = "FAIL", "HTTPS_RESPONSE_INVALID"
    return check(
        name,
        "HTTPS_READINESS",
        status,
        iso(time.time()),
        reason,
        ORIGIN + path,
        "HTTPS_FUNCTIONAL_ENDPOINT",
        certificate_verified=False,
    )


def otel_check(metadata, text, now):
    backend = metadata.get(SERVICES["backend"][0], {})
    collector = metadata.get(SERVICES["otel-collector"][0], {})
    namespace_matches = (
        bool(backend.get("container_id")) and collector.get("network_mode") == "container:" + backend["container_id"]
    )
    stamps = []
    for line in text.splitlines():
        stamp = epoch(line.split(" ", 1)[0])
        if (
            stamp is not None
            and '"otelcol.signal": "metrics"' in line
            and re.search(r'"data points":\s*[1-9][0-9]*', line)
        ):
            stamps.append(stamp)
    stamp = max(stamps) if stamps else None
    if not backend.get("container_id") or not collector.get("network_mode"):
        status, reason = "UNKNOWN", "OTEL_NAMESPACE_OBSERVATION_UNAVAILABLE"
    elif not namespace_matches:
        status, reason = "FAIL", "OTEL_BACKEND_NAMESPACE_MISMATCH"
    elif stamp is None:
        status, reason = "UNKNOWN", "OTEL_EXPORT_OBSERVATION_UNAVAILABLE"
    elif not -5 <= now - stamp <= 120:
        status, reason = "UNKNOWN", "OTEL_EXPORT_OBSERVATION_STALE"
    else:
        status, reason = "PASS", "RECENT_METRIC_EXPORT_CURRENT_NAMESPACE"
    return check(
        "otel-export",
        "TELEMETRY",
        status,
        iso(stamp) if stamp is not None else iso(now),
        reason,
        "docker-logs:otel-collector",
        "METRIC_EXPORT_CURRENT_BACKEND_NAMESPACE",
    )


def inspect_metadata(raw):
    """Retain valid whitelisted observations when another record is malformed."""
    expected = {spec[0] for spec in SERVICES.values()}
    result = {}
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            name = row.get("name", "").lstrip("/")
            if name in expected:
                result[name] = row
        except (ValueError, AttributeError, TypeError):
            continue
    return result


def history_for(canary, previous, archive_root):
    """Preserve original failure/success dates from at most 48 bounded archives."""
    histories = previous.get("canary_check_history", {})
    histories = (
        {key: dict(value) for key, value in histories.items() if isinstance(value, dict)}
        if isinstance(histories, dict)
        else {}
    )
    records = []
    total = 0
    try:
        paths = sorted(archive_root.glob("FULL-STACK-CANARY-*.json"))[-48:]
        for path in paths:
            size = path.stat().st_size
            if size > 131072 or total + size > 2_000_000:
                continue
            total += size
            records.append(load_json(path, 131072))
    except (OSError, ValueError):
        pass
    records.append(canary)
    for record in records:
        if record.get("schema_version") != "orqevia.full-stack-canary.v1":
            continue
        for row in record.get("checks", []):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                continue
            stamp = epoch(row.get("observed_at"))
            if stamp is None:
                continue
            item = histories.setdefault(row["name"], {})
            last = epoch(item.get("last_success_at"))
            first = epoch(item.get("first_failure_at"))
            if row.get("status") == "PASS" and (last is None or stamp > last):
                item["last_success_at"] = row["observed_at"]
                if first is not None and stamp >= first:
                    item.pop("first_failure_at", None)
            elif row.get("status") == "FAIL" and (last is None or stamp > last) and (first is None or stamp < first):
                item["first_failure_at"] = row["observed_at"]
    return histories


def merge_check_history(result, previous):
    prior = {row.get("service_id"): row for row in previous.get("services", []) if isinstance(row, dict)}
    for service in result["services"]:
        old = {
            row.get("check_id"): row
            for row in prior.get(service["service_id"], {}).get("checks", [])
            if isinstance(row, dict)
        }
        for row in service["checks"]:
            previous_row = old.get(row["check_id"], {})
            if row["status"] != "PASS":
                row["last_success_at"] = previous_row.get("last_success_at")
                if previous_row.get("first_failure_at"):
                    row["first_failure_at"] = previous_row["first_failure_at"]
                elif row["status"] == "FAIL":
                    row["first_failure_at"] = row["observed_at"]


def collect(
    context,
    *,
    runner,
    budget,
    now=None,
    previous=None,
    canary=None,
    archive_root=CANARY_ROOT / "full-stack-canary-history",
    reader=https_read,
    tls_context=None,
):
    now = time.time() if now is None else now
    previous = previous or {}
    native = context.get("native_identity", {})
    host = context.get("host_receipt", {})
    identity = host.get("host_id") == native.get("host_id") and bool(native.get("host_id"))
    boot = epoch(host.get("boot_id")) == epoch(native.get("boot_id")) and epoch(native.get("boot_id")) is not None
    host_stamp = host.get("captured_at")
    host_stamp = host_stamp if type(host_stamp) in (int, float) and math.isfinite(host_stamp) else None
    host_fresh = (
        host_stamp is not None
        and -5 <= now - host_stamp <= 120
        and host.get("schema") == "orqevia.host-metrics.v1"
        and host.get("collector_id") == "abex-host-metrics-v1"
        and host.get("cadence_seconds") == 60
    )
    source = context.get("integrity", {})
    collector_checks = [
        check(
            "collector-source",
            "CONFIGURATION",
            "PASS" if source.get("status") == "PASS" else "FAIL",
            source.get("observed_at", iso(now)),
            source.get("reason", "SOURCE_INTEGRITY_UNAVAILABLE"),
            "installed-file-sha256-and-dacl",
            "FIXED_HOST_COLLECTOR_SOURCE",
        ),
        check(
            "host-identity",
            "CONFIGURATION",
            "PASS" if identity and host_fresh else "UNKNOWN",
            iso(host_stamp) if host_stamp is not None else iso(now),
            "HOST_IDENTITY_MATCHED" if identity and host_fresh else "HOST_RECEIPT_IDENTITY_OR_FRESHNESS_UNAVAILABLE",
            "native-host-and-host-receipt",
            "NATIVE_SAME_HOST",
        ),
        check(
            "boot-identity",
            "CONFIGURATION",
            "PASS" if boot and host_fresh else "UNKNOWN",
            iso(host_stamp) if host_stamp is not None else iso(now),
            "BOOT_IDENTITY_MATCHED" if boot and host_fresh else "HOST_RECEIPT_SAME_BOOT_UNAVAILABLE",
            "native-boot-and-host-receipt",
            "NATIVE_SAME_BOOT",
        ),
    ]
    metadata = {}
    try:
        _, raw = runner.run(
            [DOCKER, "inspect", "--format", INSPECT_FORMAT, *(spec[0] for spec in SERVICES.values())], timeout=4
        )
        metadata = inspect_metadata(raw)
    except (OSError, ValueError, KeyError, TimeoutError, subprocess.TimeoutExpired):
        pass
    services = []
    for service_id, (name, required) in SERVICES.items():
        item = metadata.get(name, {})
        observations = item.get("health_observations", [])
        successes = [row.get("observed_at") for row in observations if row.get("exit_code") == 0]
        services.append(
            {
                "service_id": service_id,
                "container_name": name,
                "observed_at": iso(time.time()),
                "process_state": item.get("process_state", "UNKNOWN"),
                "docker_health": item.get("docker_health"),
                "health_observed_at": observations[-1].get("observed_at") if observations else None,
                "health_last_success_at": successes[-1] if successes else None,
                "checks": [
                    check(
                        key,
                        kind,
                        "NOT_CONFIGURED",
                        None,
                        "VERIFIED_FUNCTIONAL_PROBE_NOT_CONFIGURED",
                        "host-operational-collector",
                        "DECLARED_SERVICE_CHECK",
                    )
                    for key, kind in required.items()
                ],
            }
        )
    by_id = {row["service_id"]: row for row in services}

    def set_check(service_id, item):
        rows = by_id[service_id]["checks"]
        rows[next(index for index, row in enumerate(rows) if row["check_id"] == item["check_id"])] = item

    backend = by_id["backend"]
    set_check(
        "backend",
        check(
            "backend-health",
            "DOCKER_HEALTHCHECK",
            "PASS"
            if backend["docker_health"] == "healthy"
            else "FAIL"
            if backend["docker_health"] == "unhealthy"
            else "UNKNOWN",
            backend["health_observed_at"],
            "CONFIGURATION_LIVENESS_ONLY",
            "docker-healthcheck:backend",
            "CONFIGURATION_LIVENESS",
        ),
    )
    backend_data = {}
    try:
        code, raw = runner.run([DOCKER, "exec", "-i", SERVICES["backend"][0], "python", "-B", "-"], script=BACKEND_READ)
        backend_data = json.loads(raw) if code == 0 else {}
        executions = [
            (epoch(value), value)
            for value in (backend_data.get("worker_started_at"), backend_data.get("worker_completed_at"))
            if epoch(value) is not None
        ]
        worker, worker_observed_at = max(executions, default=(None, None))
        started = epoch(metadata.get(SERVICES["backend"][0], {}).get("started_at"))
        if backend_data.get("database_read") is False:
            status, reason = "FAIL", "BACKEND_PERSISTENCE_READ_FAILED"
        elif worker is not None and started is not None and worker >= started and -5 <= time.time() - worker <= 120:
            status, reason = "PASS", "PERSISTENCE_AND_RECENT_EXECUTION_OBSERVED"
        else:
            status, reason = "UNKNOWN", "WORKER_HEARTBEAT_NOT_EXPOSED"
        set_check(
            "backend",
            check(
                "backend-readiness",
                "DEPENDENCY",
                status,
                worker_observed_at if status == "PASS" else backend_data.get("observed_at", iso(time.time())),
                reason,
                "sqlite-select-only:backend",
                "PERSISTENCE_AND_RECENT_WORKER_EXECUTION",
                database_read_observed_at=backend_data.get("observed_at"),
                worker_started_at=backend_data.get("worker_started_at"),
                worker_completed_at=backend_data.get("worker_completed_at"),
            ),
        )
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        set_check(
            "backend",
            check(
                "backend-readiness",
                "DEPENDENCY",
                "UNKNOWN",
                iso(time.time()),
                "BACKEND_OBSERVATION_UNAVAILABLE",
                "sqlite-select-only:backend",
                "PERSISTENCE_AND_RECENT_WORKER_EXECUTION",
            ),
        )
    try:
        code, raw = runner.run([DOCKER, "exec", SERVICES["ollama"][0], "ollama", "list"])
        required = backend_data.get("required_models", [])
        installed = {line.split()[0] for line in raw.splitlines()[1:] if line.split()}
        status = (
            "PASS"
            if code == 0 and required and set(required) <= installed
            else "FAIL"
            if code == 0 and required
            else "UNKNOWN"
        )
        set_check(
            "ollama",
            check(
                "model-inventory",
                "DEPENDENCY",
                status,
                iso(time.time()),
                "REQUIRED_MODEL_INVENTORY_PRESENT"
                if status == "PASS"
                else "REQUIRED_MODEL_INVENTORY_UNAVAILABLE_OR_MISSING",
                "ollama-list:existing-runtime",
                "INSTALLED_MODELS_ONLY_NO_INFERENCE",
            ),
        )
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        set_check(
            "ollama",
            check(
                "model-inventory",
                "DEPENDENCY",
                "UNKNOWN",
                iso(time.time()),
                "MODEL_INVENTORY_UNAVAILABLE",
                "ollama-list:existing-runtime",
                "INSTALLED_MODELS_ONLY_NO_INFERENCE",
            ),
        )
    try:
        code, raw = runner.run(
            [DOCKER, "exec", "-i", SERVICES["coaching"][0], "python", "-B", "-"], script=COACHING_READ
        )
        row = json.loads(raw) if code == 0 else {}
        tick = row.get("tick_epoch")
        revision = metadata.get(SERVICES["coaching"][0], {}).get("source_revision")
        passed = (
            type(tick) in (int, float)
            and -5 <= time.time() - tick <= 60
            and bool(revision)
            and row.get("source_revision") == revision
        )
        set_check(
            "coaching",
            check(
                "controller-heartbeat",
                "DEPENDENCY",
                "PASS" if passed else "UNKNOWN",
                iso(tick) if type(tick) in (int, float) else iso(time.time()),
                "CURRENT_CONTROLLER_TICK" if passed else "CONTROLLER_TICK_OR_SOURCE_UNAVAILABLE",
                "sqlite-select-only:coaching-controller",
                "CONTROLLER_HEARTBEAT_ONLY",
            ),
        )
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        set_check(
            "coaching",
            check(
                "controller-heartbeat",
                "DEPENDENCY",
                "UNKNOWN",
                iso(time.time()),
                "CONTROLLER_OBSERVATION_UNAVAILABLE",
                "sqlite-select-only:coaching-controller",
                "CONTROLLER_HEARTBEAT_ONLY",
            ),
        )
    try:
        _, raw = runner.run([DOCKER, "logs", "--timestamps", "--tail", "24", SERVICES["otel-collector"][0]], timeout=2)
        set_check("otel-collector", otel_check(metadata, raw, time.time()))
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        set_check("otel-collector", otel_check(metadata, "", time.time()))
    for service_id, name, path, intelligence in (
        ("interface", "interface-https", "/pwa/", False),
        ("intelligence", "intelligence-https", "/api/orqevia/intelligence/health", True),
    ):
        set_check(service_id, tls_check(name, path, tls_context, budget, intelligence=intelligence, reader=reader))
    for service_id in ("cloudflared", "cloudflared-dual"):
        set_check(
            service_id,
            check(
                "tunnel-connection",
                "DEPENDENCY",
                "UNKNOWN",
                iso(time.time()),
                "CURRENT_CONNECTION_OBSERVATION_NOT_EXPOSED_OVER_HTTPS",
                "existing-tunnel-observation",
                "CURRENT_CONNECTIONS_NOT_PROCESS_OR_OLD_REGISTRATION",
            ),
        )
    result = {
        "schema_version": "orqevia.operational-observation.v1",
        "host_id": native.get("host_id"),
        "boot_id": native.get("boot_id"),
        "observed_at": iso(time.time()),
        "cadence_seconds": 60,
        "services": services,
        "collector_checks": collector_checks,
        "canary": canary or {},
        "canary_check_history": history_for(canary or {}, previous, archive_root),
        "limits": [
            "NO_GENERATION_CALLS",
            "NO_NEW_PRIVATE_HTTP_PROBES",
            "UNCONFIGURED_GATEWAY_AND_TUNNEL_HTTPS_PATHS",
            "RECENT_WORKER_EXECUTION_IS_NOT_CONTINUOUS_WORKER_HEARTBEAT",
        ],
    }
    merge_check_history(result, previous)
    return result


def atomic_write(path, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > 2_000_000:
        raise ValueError("Receipt too large")
    descriptor, temporary = tempfile.mkstemp(prefix=".operational-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if len(sys.argv) != 1 or Path(__file__).resolve().parent != ROOT.resolve():
        raise SystemExit("Fixed installed collector required")
    context = json.loads(sys.stdin.read(131073))
    output = ROOT / "receipt" / "operational-health.json"
    previous, canary = {}, {}
    for path, target in ((output, "previous"), (CANARY_ROOT / "LATEST-FULL-STACK-CANARY.json", "canary")):
        try:
            value = load_json(path)
            if target == "previous":
                previous = value
            else:
                canary = value
        except (OSError, ValueError):
            pass
    ca = ROOT / "orqevia-ca.crt"
    tls_context = ssl.create_default_context(cafile=str(ca) if context.get("ca_verified") is True else None)
    budget = Budget()
    result = collect(
        context, runner=Runner(budget), budget=budget, previous=previous, canary=canary, tls_context=tls_context
    )
    atomic_write(output, result)
    refreshed = False
    try:
        status, _ = https_read("/interface/v1/telemetry", tls_context, 3, read_body=False)
        refreshed = status == 200
    except (OSError, ValueError, urllib.error.URLError):
        pass
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "observed_at": result["observed_at"],
                "service_count": len(result["services"]),
                "https_refresh_succeeded": refreshed,
            }
        )
    )


if __name__ == "__main__":
    main()
