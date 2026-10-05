"""Optional, fail-closed thermal envelope for heavy local inference.

This is a consumer contract, not a claim that Windows exposes a privileged
sensor to PRIME. An operator-owned collector must publish an atomic receipt
through a read-only path inaccessible for writing by PRIME. The policy is
hash-pinned so an optional compute profile cannot relax the limit.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path


POLICY_SCHEMA = 'prime.ssd-thermal-policy.v1'
RECEIPT_SCHEMA = 'prime.ssd-temperature.v1'
SENSOR = 'MSFT_StorageReliabilityCounter.Temperature'
MAX_AGE_SECONDS = 30
HEADROOM_C = 5
# Fixed conservative exemption for explicitly bounded light local work. A
# missing optional policy cannot raise this threshold.
LIGHT_DEMAND_MIB = 1024


def _unique_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


def _absolute_path(name: str) -> Path:
    value = os.getenv(name, '')
    if not value or not Path(value).is_absolute():
        raise PermissionError(f'{name} unavailable')
    return Path(value)


def policy() -> dict:
    """Return a pinned disk/limit contract; no unverified default of 70 C."""
    path = _absolute_path('PRIME_SSD_THERMAL_POLICY')
    expected = os.getenv('PRIME_SSD_THERMAL_POLICY_SHA256', '').lower()
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise PermissionError('SSD thermal policy hash unavailable')
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('policy hash mismatch')
        value = _unique_json(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PermissionError('SSD thermal policy unavailable or invalid') from exc
    identity = ('host', 'device_id', 'serial_number', 'friendly_name', 'limit_source')
    if (value.get('schema') != POLICY_SCHEMA or
            any(not isinstance(value.get(key), str) or not value[key] for key in identity) or
            value.get('sensor') != SENSOR or
            type(value.get('heavy_demand_mib')) is not int or value['heavy_demand_mib'] < LIGHT_DEMAND_MIB or
            type(value.get('max_operating_c')) not in (int, float) or
            not math.isfinite(value['max_operating_c']) or
            not 0 < value['max_operating_c'] <= 150):
        raise PermissionError('SSD thermal policy incomplete')
    return value


def observation(thermal_policy: dict, *, now: float | None = None) -> dict:
    path = _absolute_path('PRIME_SSD_THERMAL_RECEIPT')
    try:
        sample = _unique_json(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise PermissionError('SSD temperature receipt unavailable') from exc
    now = time.time() if now is None else now
    identity = ('host', 'device_id', 'serial_number', 'friendly_name', 'sensor')
    if (sample.get('schema') != RECEIPT_SCHEMA or
            any(sample.get(key) != thermal_policy.get(key) for key in identity) or
            sample.get('unit') != 'C' or sample.get('source') != 'Windows.StorageReliabilityCounter' or
            not isinstance(sample.get('collector_id'), str) or not sample['collector_id'] or
            not isinstance(sample.get('boot_id'), str) or not sample['boot_id'] or
            sample.get('read_ok') is not True):
        raise PermissionError('SSD temperature receipt scope or sensor mismatch')
    captured = sample.get('captured_at')
    temperature = sample.get('temperature_c')
    if (type(now) not in (int, float) or not math.isfinite(now) or
            type(captured) not in (int, float) or not math.isfinite(captured) or
            not 0 <= now - captured <= MAX_AGE_SECONDS or
            type(temperature) not in (int, float) or not math.isfinite(temperature) or
            not 0 < temperature <= 150):
        raise PermissionError('SSD temperature receipt stale or unsupported')
    return sample


def require_for_demand(demand_mib: int) -> None:
    """When enabled, missing telemetry holds heavy work without blocking light work.

    The feature remains opt-in on isolated source until an independently
    reviewed collector, ACL and manufacturer limit are provisioned. Once
    enabled, a missing policy is never treated as permission to run heavy work.
    """
    enforce = os.getenv('PRIME_SSD_THERMAL_ENFORCE', '')
    if not enforce:
        return
    if enforce != '1':
        raise PermissionError('invalid SSD thermal enforcement setting')
    if type(demand_mib) is not int or demand_mib <= 0:
        raise PermissionError('valid local inference memory demand required')
    if demand_mib <= LIGHT_DEMAND_MIB:
        return
    thermal_policy = policy()
    if demand_mib <= thermal_policy['heavy_demand_mib']:
        return
    sample = observation(thermal_policy)
    if sample['temperature_c'] >= thermal_policy['max_operating_c'] - HEADROOM_C:
        raise PermissionError('SSD thermal headroom insufficient for heavy local inference')
