"""Read the host-owned Windows receipt without inventing live measurements.

The existing sampler runs about every 60 seconds. A 150-second receipt window
allows scheduling and collection jitter; original field timestamps and ages are
retained. File readability and a matching host ID do not attest writer ACLs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time


RECEIPT_SCHEMA = 'orqevia.host-metrics.v1'
COLLECTOR_ID = 'abex-host-metrics-v1'
MAX_AGE_SECONDS = 150
MAX_RECEIPT_BYTES = 131072
FIELDS = ('cpu_percent', 'memory_percent', 'disk_percent', 'network_latency_ms')
SOURCES = {
    'cpu': 'Win32_Processor.LoadPercentage',
    'memory': 'Win32_OperatingSystem.TotalVisibleMemorySize/FreePhysicalMemory',
    'disk': 'Win32_LogicalDisk.Size/FreeSpace',
    'network': 'Get-NetAdapter/Get-NetAdapterStatistics',
    'network_latency': 'Test-Connection/default IPv4 gateway',
}
COUNTERS = ('received_bytes', 'sent_bytes', 'received_packet_errors',
            'outbound_packet_errors', 'received_discarded_packets',
            'outbound_discarded_packets')
RATES = ('received_bytes_per_second', 'sent_bytes_per_second')
DETAIL_FIELDS = {
    'cpu': ('percent', 'logical_processors'),
    'memory': ('percent', 'total_bytes', 'used_bytes', 'available_bytes'),
    'disk': ('percent', 'total_bytes', 'used_bytes', 'available_bytes'),
}


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


def _number(value, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
            return None
        return float(value)
    except (OverflowError, ValueError):
        return None


def _integer(value):
    return value if type(value) is int and value >= 0 else None


def _text(value):
    return value if isinstance(value, str) and value.strip() and len(value) <= 512 else None


def _reason(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', value) else fallback


def _utc(stamp):
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else None
    except (OverflowError, OSError, ValueError):
        return None


def _meta(status, reason, source, stamp):
    return {'collection_status': status, 'reason': reason,
            'source': source, 'captured_at': stamp}


def _summarize(fields):
    statuses = [field['collection_status'] for field in fields]
    if statuses and all(status == 'OBSERVED' for status in statuses):
        return 'OBSERVED', None
    if any(status in ('OBSERVED', 'PARTIAL') for status in statuses):
        return 'PARTIAL', next(field['reason'] for field in fields if field['collection_status'] != 'OBSERVED')
    if 'STALE' in statuses:
        return 'STALE', 'FIELD_STALE'
    return 'UNAVAILABLE', next((field['reason'] for field in fields if field['reason']), 'METRIC_MISSING')


def _measurement(value, *, raw, source, stamp, receipt_stamp, now, integer=False,
                 maximum=None, missing_reason='METRIC_MISSING'):
    """Validate a value and its own timestamp, never the API response time."""
    parsed = _integer(value) if integer else _number(value, maximum)
    reason = None
    status = 'UNAVAILABLE'
    if raw.get('collection_status') not in (None, 'OBSERVED', 'PARTIAL'):
        reason = _reason(raw.get('reason'), 'COLLECTION_FAILED')
    elif stamp is None or stamp > receipt_stamp + 5:
        reason = 'FIELD_TIMESTAMP_INVALID'
    elif stamp > now + 5:
        reason = 'FIELD_FROM_FUTURE'
    elif now - stamp > MAX_AGE_SECONDS:
        status, reason = 'STALE', 'FIELD_STALE'
    elif parsed is None:
        reason = _reason(raw.get('reason'), missing_reason if value is None else 'METRIC_INVALID')
    else:
        return parsed, _meta('OBSERVED', None, source, stamp)
    return None, _meta(status, reason, source, stamp)


def _empty(configured, reason, now, *, sample=None, status='UNAVAILABLE'):
    sample = sample if isinstance(sample, dict) else {}
    stamp = _number(sample.get('captured_at'))
    source = {'system': 'Windows',
              'host_id': _text(sample.get('host_id')),
              'boot_id': _text(sample.get('boot_id')),
              'collector_id': _text(sample.get('collector_id')),
              'identity_check': 'NOT_CONFIGURED', 'writer_trust': 'NOT_ATTESTED'}
    result = {'configured': configured, 'collection_status': status, 'reason': reason,
              'schema': _text(sample.get('schema')), 'source': source,
              'captured_at': stamp, 'captured_at_utc': _utc(stamp),
              'age_seconds': round(now - stamp, 3) if stamp is not None else None,
              'read_at': _utc(now), 'max_age_seconds': MAX_AGE_SECONDS,
              'cadence_seconds': 60, 'values': {field: None for field in FIELDS},
              'field_status': {}}
    raw_fields = sample.get('field_status')
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    for field in FIELDS:
        raw = raw_fields.get(field)
        raw = raw if isinstance(raw, dict) else {}
        group = 'network_latency' if field == 'network_latency_ms' else field.removesuffix('_percent')
        field_stamp = _number(raw.get('captured_at', stamp))
        result['field_status'][field] = _meta(status, reason, _text(raw.get('source')) or SOURCES[group], field_stamp)
    for name, fields in DETAIL_FIELDS.items():
        raw = sample.get(name)
        raw = raw if isinstance(raw, dict) else {}
        group_stamp = _number(raw.get('captured_at', stamp))
        group_source = _text(raw.get('source')) or SOURCES[name]
        group = {field: None for field in fields}
        group.update(_meta(status, reason, group_source, group_stamp))
        group['field_status'] = {field: _meta(status, reason, group_source, group_stamp) for field in fields}
        if name == 'disk':
            group['device'] = _text(raw.get('device'))
        result[name] = group
    raw_network = sample.get('network')
    raw_network = raw_network if isinstance(raw_network, dict) else {}
    network_stamp = _number(raw_network.get('captured_at', stamp))
    result['network'] = {
        **_meta(status, reason, SOURCES['network'], network_stamp), 'interfaces': [],
        'interfaces_status': status, 'interfaces_reason': reason,
        'latency_ms': None, 'latency_status': status, 'latency_reason': reason,
        'latency_source': SOURCES['network_latency'], 'latency_captured_at': stamp,
        'field_status': {'latency_ms': result['field_status']['network_latency_ms']},
    }
    return result


def _detail_group(sample, name, legacy, legacy_meta, now):
    raw = sample.get(name)
    raw = raw if isinstance(raw, dict) else {}
    source = _text(raw.get('source')) or SOURCES[name]
    stamp = _number(raw.get('captured_at', sample['captured_at']))
    fields = {}
    result = {**_meta('UNAVAILABLE', None, source, stamp)}
    for field in DETAIL_FIELDS[name]:
        if field == 'percent' and not raw:
            value, meta = legacy, dict(legacy_meta)
        else:
            value, meta = _measurement(
                raw.get(field), raw=raw, source=source, stamp=stamp,
                receipt_stamp=sample['captured_at'], now=now,
                integer=field != 'percent', maximum=100 if field == 'percent' else None,
                missing_reason='DETAIL_NOT_COLLECTED' if not raw else 'METRIC_MISSING')
        if field == 'logical_processors' and value == 0:
            value, meta = None, _meta('UNAVAILABLE', 'METRIC_INVALID', source, stamp)
        result[field], fields[field] = value, meta
    if name in ('memory', 'disk'):
        byte_fields = ('total_bytes', 'used_bytes', 'available_bytes')
        values = [result[field] for field in byte_fields]
        if all(value is not None for value in values) and (values[0] == 0 or values[0] != values[1] + values[2]):
            for field in byte_fields:
                result[field] = None
                fields[field] = _meta('UNAVAILABLE', 'INCONSISTENT_BYTE_TOTALS', source, stamp)
    if name == 'disk':
        result['device'] = _text(raw.get('device'))
    result['field_status'] = fields
    result['collection_status'], result['reason'] = _summarize(list(fields.values()))
    return result


def _network(sample, legacy, legacy_meta, now):
    raw = sample.get('network')
    raw = raw if isinstance(raw, dict) else {}
    source = _text(raw.get('source')) or SOURCES['network']
    stamp = _number(raw.get('captured_at', sample['captured_at']))
    result = {**_meta('UNAVAILABLE', None, source, stamp),
              'latency_ms': legacy, 'latency_status': legacy_meta['collection_status'],
              'latency_reason': legacy_meta['reason'], 'latency_source': legacy_meta['source'],
              'latency_captured_at': legacy_meta['captured_at'],
              'field_status': {'latency_ms': dict(legacy_meta)}, 'interfaces': []}
    rows = raw.get('interfaces')
    interface_reason = _reason(raw.get('reason'), 'DETAIL_NOT_COLLECTED' if not raw else 'NO_NETWORK_INTERFACES')
    if rows is not None and not isinstance(rows, list):
        interface_reason = 'NETWORK_INTERFACES_INVALID'
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            interface_reason = 'INTERFACE_IDENTITY_INVALID'
            continue
        index, name = _integer(row.get('interface_index')), _text(row.get('name'))
        if index is None or name is None or index in seen:
            interface_reason = 'INTERFACE_IDENTITY_INVALID'
            continue
        seen.add(index)
        row_stamp = _number(row.get('captured_at', stamp))
        row_source = _text(row.get('source')) or source
        item = {key: _text(row.get(key)) for key in ('description', 'status', 'link_speed')}
        item.update({'name': name, 'interface_index': index,
                     'hardware_interface': row.get('hardware_interface') if type(row.get('hardware_interface')) is bool else None,
                     'source': row_source, 'captured_at': row_stamp, 'field_status': {}})
        for field in COUNTERS:
            value, meta = _measurement(row.get(field), raw=row, source=row_source, stamp=row_stamp,
                                       receipt_stamp=sample['captured_at'], now=now, integer=True,
                                       missing_reason='INTERFACE_COUNTER_MISSING')
            item[field], item['field_status'][field] = value, meta
        interval = _number(row.get('rate_interval_seconds'))
        rate_raw = {'collection_status': row.get('rate_status', 'UNAVAILABLE'),
                    'reason': _reason(row.get('rate_reason'), 'RATE_BASELINE_UNAVAILABLE')}
        if interval is None or not 0 < interval <= MAX_AGE_SECONDS:
            if rate_raw['collection_status'] == 'OBSERVED':
                rate_raw = {'collection_status': 'UNAVAILABLE', 'reason': 'RATE_INTERVAL_INVALID'}
            interval = None
        for field in RATES:
            value, meta = _measurement(row.get(field), raw=rate_raw, source=row_source + '/counter delta',
                                       stamp=row_stamp, receipt_stamp=sample['captured_at'], now=now)
            item[field], item['field_status'][field] = value, meta
        item['rate_status'], item['rate_reason'] = _summarize([item['field_status'][field] for field in RATES])
        item['rate_interval_seconds'] = interval if item['rate_status'] == 'OBSERVED' else None
        item['rate_started_at'] = row_stamp - interval if item['rate_status'] == 'OBSERVED' else None
        item['collection_status'], item['reason'] = _summarize(list(item['field_status'].values()))
        result['interfaces'].append(item)
    interface_fields = [meta for row in result['interfaces'] for meta in row['field_status'].values()]
    if interface_fields:
        result['interfaces_status'], result['interfaces_reason'] = _summarize(interface_fields)
        if interface_reason == 'INTERFACE_IDENTITY_INVALID':
            result['interfaces_status'], result['interfaces_reason'] = 'PARTIAL', interface_reason
    else:
        result['interfaces_status'], result['interfaces_reason'] = 'UNAVAILABLE', interface_reason
    summary = [legacy_meta, _meta(result['interfaces_status'], result['interfaces_reason'], source, stamp)]
    result['collection_status'], result['reason'] = _summarize(summary)
    return result


def host_metrics(*, now: float | None = None) -> dict:
    """Return validated v1 scalars plus Windows details and original provenance."""
    now = time.time() if now is None else now
    path = os.getenv('ORQEVIA_HOST_METRICS_RECEIPT', '')
    if not path:
        return _empty(False, 'HOST_COLLECTOR_NOT_CONFIGURED', now)
    if not Path(path).is_absolute():
        return _empty(False, 'RECEIPT_PATH_NOT_ABSOLUTE', now)
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            return _empty(True, 'RECEIPT_TOO_LARGE', now)
        sample = _unique_json(raw)
    except FileNotFoundError:
        return _empty(True, 'RECEIPT_MISSING', now)
    except PermissionError:
        return _empty(True, 'RECEIPT_PERMISSION_DENIED', now)
    except IsADirectoryError:
        return _empty(True, 'RECEIPT_NOT_A_FILE', now)
    except OSError:
        return _empty(True, 'RECEIPT_READ_FAILED', now)
    except (UnicodeError, ValueError, RecursionError):
        return _empty(True, 'RECEIPT_MALFORMED', now)

    result = _empty(True, None, now, sample=sample)
    captured = result['captured_at']
    expected_host = os.getenv('ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID', '').strip()
    reason = None
    if sample.get('schema') != RECEIPT_SCHEMA:
        reason = 'RECEIPT_SCHEMA_MISMATCH'
    elif result['source']['host_id'] is None:
        reason = 'HOST_ID_MISSING'
    elif expected_host and result['source']['host_id'].casefold() != expected_host.casefold():
        reason = 'HOST_ID_MISMATCH'
    elif result['source']['boot_id'] is None:
        reason = 'BOOT_ID_MISSING'
    elif result['source']['collector_id'] != COLLECTOR_ID:
        reason = 'COLLECTOR_ID_MISMATCH'
    elif captured is None or _utc(captured) is None:
        reason = 'RECEIPT_TIMESTAMP_INVALID'
    elif captured > now + 5:
        reason = 'RECEIPT_FROM_FUTURE'
    elif now - captured > MAX_AGE_SECONDS:
        reason = 'RECEIPT_STALE'
    identity_check = 'MISMATCH' if reason == 'HOST_ID_MISMATCH' else 'MATCHED' if expected_host and result['source']['host_id'] else 'NOT_CONFIGURED'
    if reason:
        result = _empty(True, reason, now, sample=sample,
                        status='STALE' if reason == 'RECEIPT_STALE' else 'UNAVAILABLE')
        result['source']['identity_check'] = identity_check
        return result
    result['source']['identity_check'] = identity_check
    raw_fields = sample.get('field_status')
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    for field in FIELDS:
        raw_meta = raw_fields.get(field)
        raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
        name = 'network_latency' if field == 'network_latency_ms' else field.removesuffix('_percent')
        source = _text(raw_meta.get('source')) or SOURCES[name]
        stamp = _number(raw_meta.get('captured_at', captured))
        value, meta = _measurement(sample.get(field), raw=raw_meta, source=source,
                                   stamp=stamp, receipt_stamp=captured, now=now,
                                   maximum=None if field == 'network_latency_ms' else 100)
        result['values'][field], result['field_status'][field] = value, meta
    for name in DETAIL_FIELDS:
        field = name + '_percent'
        result[name] = _detail_group(sample, name, result['values'][field], result['field_status'][field], now)
    result['network'] = _network(sample, result['values']['network_latency_ms'],
                                 result['field_status']['network_latency_ms'], now)
    summaries = list(result['field_status'].values()) + [result[name] for name in (*DETAIL_FIELDS, 'network')]
    result['collection_status'], result['reason'] = _summarize(summaries)
    if result['collection_status'] == 'PARTIAL':
        result['reason'] = 'PARTIAL_COLLECTION'
    return result
