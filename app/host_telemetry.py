"""Read a bounded Windows receipt; never substitute container/estimated metrics."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import stat

SCHEMA = 'orqevia.host-telemetry.v1'
MAX_BYTES = 32768
MAX_AGE_SECONDS = 90
FUTURE_TOLERANCE_SECONDS = 5
SPECS = {
    'cpu': ('percent', 100, 'WINDOWS_CIM_CPU', 'HOST_CPU_LOAD'),
    'memory': ('percent', 100, 'WINDOWS_CIM_MEMORY', 'HOST_PHYSICAL_MEMORY_USED'),
    'disk': ('percent', 100, 'WINDOWS_CIM_C_VOLUME', 'C_VOLUME_CAPACITY_USED'),
    'network_latency': ('ms', 5000, 'WINDOWS_HTTP_STOPWATCH', 'LOCAL_LOOPBACK_HTTP_HEALTH'),
}
FAILURES = {'COLLECTION_FAILED', 'DEPENDENCY_UNAVAILABLE', 'HTTP_UNHEALTHY', 'INVALID_SAMPLE'}


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp timezone')
    return result.timestamp()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def host_metrics(instance, observed_at):
    """Environment selects an operator-managed read-only receipt, never a URL."""
    now = _timestamp(observed_at)

    def metric(name, code, *, value=None, timestamp=None):
        unit, _, producer, scope = SPECS[name]
        observed = code is None
        return {'metric_id': name, 'value': value if observed else None, 'unit': unit,
                'collection_status': 'OBSERVED' if observed else 'UNAVAILABLE',
                'source_system': 'WINDOWS_HOST', 'source_instance': instance,
                'producer': producer if observed else code, 'scope': 'WORKSPACE_AGGREGATE',
                'measurement_scope': scope,
                'event_timestamp': timestamp, 'observed_at': observed_at,
                'provenance': 'WINDOWS_READ_ONLY_HOST_RECEIPT' if observed else 'NO_MEASUREMENT'}

    def unavailable(code):
        return [metric(name, code) for name in SPECS]

    configured = os.getenv('PRIME_INTERFACE_HOST_TELEMETRY_RECEIPT', '').strip()
    if not configured:
        return unavailable('HOST_COLLECTOR_NOT_CONFIGURED')
    try:
        path = Path(configured)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            return unavailable('HOST_RECEIPT_INVALID')
        with path.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return unavailable('HOST_RECEIPT_INVALID')
        receipt = json.loads(raw, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return unavailable('HOST_RECEIPT_MISSING')
    except OSError:
        return unavailable('HOST_RECEIPT_UNREADABLE')
    except (ValueError, UnicodeError, RecursionError):
        return unavailable('HOST_RECEIPT_INVALID')
    if not isinstance(receipt, dict) or receipt.get('schema_version') != SCHEMA:
        return unavailable('HOST_RECEIPT_SCHEMA_MISMATCH')
    source = receipt.get('source')
    if (not isinstance(source, dict) or instance == 'UNKNOWN'
            or source.get('instance') != instance or source.get('system') != 'WINDOWS_HOST'
            or source.get('collector') != 'windows-cim-http-v1'):
        return unavailable('HOST_RECEIPT_IDENTITY_MISMATCH')
    try:
        collected = _timestamp(receipt.get('collected_at_utc'))
    except (ValueError, OverflowError):
        return unavailable('HOST_RECEIPT_INVALID')
    if collected - now > FUTURE_TOLERANCE_SECONDS:
        return unavailable('HOST_RECEIPT_FUTURE')
    if now - collected > MAX_AGE_SECONDS:
        return unavailable('HOST_RECEIPT_STALE')
    rows = receipt.get('metrics')
    if not isinstance(rows, list) or len(rows) > 4:
        return unavailable('HOST_RECEIPT_INVALID')
    by_name = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('metric_id'), str)
                or row['metric_id'] not in SPECS or row['metric_id'] in by_name):
            return unavailable('HOST_RECEIPT_INVALID')
        by_name[row['metric_id']] = row
    result = []
    for name, (unit, maximum, producer, scope) in SPECS.items():
        row = by_name.get(name)
        code = 'HOST_METRIC_MISSING'
        if row:
            code = 'HOST_METRIC_INVALID'
            try:
                timestamp = _timestamp(row.get('event_timestamp'))
                valid = (row.get('unit') == unit and row.get('producer') == producer
                         and row.get('scope') == scope and -FUTURE_TOLERANCE_SECONDS <= now - timestamp <= MAX_AGE_SECONDS
                         and abs(collected - timestamp) <= 30)
                value = row.get('value')
                if valid and row.get('collection_status') == 'OBSERVED':
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= maximum:
                        result.append(metric(name, None, value=value, timestamp=row['event_timestamp']))
                        continue
                elif (valid and row.get('collection_status') == 'UNAVAILABLE' and value is None
                      and isinstance(row.get('failure_code'), str) and row['failure_code'] in FAILURES):
                    code = 'HOST_' + row['failure_code']
            except (ValueError, OverflowError):
                pass
        result.append(metric(name, code))
    return result
