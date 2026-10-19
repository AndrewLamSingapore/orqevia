"""Optional, fail-closed host metrics receipt for the telemetry surface.

An operator-owned collector on the host publishes an atomic JSON receipt
through a read-only bind mount. ORQEVIA never writes this path; a missing,
stale or malformed receipt is reported as unavailable, never invented.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path


RECEIPT_SCHEMA = 'orqevia.host-metrics.v1'
MAX_AGE_SECONDS = 60
FIELDS = ('cpu_percent', 'memory_percent', 'disk_percent', 'network_latency_ms')


def _unique_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def host_metrics(*, now: float | None = None) -> dict:
    """Return {'configured': bool, 'values': {field: float|None}}.

    'configured' is True when ORQEVIA_HOST_METRICS_RECEIPT points at an absolute
    path. 'values' then reflects a valid fresh receipt; each metric is a
    number or None. Missing optional metrics stay None and render UNAVAILABLE.
    """
    path = os.getenv('ORQEVIA_HOST_METRICS_RECEIPT', '')
    values = {field: None for field in FIELDS}
    if not path or not Path(path).is_absolute():
        return {'configured': False, 'values': values}
    now = time.time() if now is None else now
    try:
        sample = _unique_json(Path(path).read_bytes())
    except (OSError, UnicodeError, ValueError):
        return {'configured': True, 'values': values}
    captured = sample.get('captured_at')
    valid = (
        sample.get('schema') == RECEIPT_SCHEMA
        and isinstance(sample.get('host_id'), str) and bool(sample['host_id'])
        and isinstance(sample.get('boot_id'), str) and bool(sample['boot_id'])
        and isinstance(sample.get('collector_id'), str) and bool(sample['collector_id'])
        and isinstance(captured, (int, float)) and math.isfinite(captured)
        and 0 <= now - captured <= MAX_AGE_SECONDS
    )
    if not valid:
        return {'configured': True, 'values': values}
    for field in FIELDS:
        value = sample.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        upper = None if field == 'network_latency_ms' else 100.0
        if value < 0 or (upper is not None and value > upper):
            continue
        values[field] = float(value)
    return {'configured': True, 'values': values}
