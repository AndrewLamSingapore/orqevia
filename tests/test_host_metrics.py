import json
import time
from pathlib import Path

import pytest

from app.host_metrics import MAX_AGE_SECONDS, RECEIPT_SCHEMA, host_metrics


def receipt(tmp_path, **overrides):
    value = {
        'schema': RECEIPT_SCHEMA,
        'host_id': 'DESKTOP-ABEX',
        'boot_id': 'boot-1',
        'collector_id': 'abex-host-metrics-v1',
        'captured_at': time.time(),
        'cpu_percent': 12.5,
        'memory_percent': 42.0,
        'disk_percent': 33.0,
        'network_latency_ms': 1.5,
    }
    value.update(overrides)
    path = tmp_path / 'host-metrics.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_unconfigured_is_not_configured(monkeypatch):
    monkeypatch.delenv('ORQEVIA_HOST_METRICS_RECEIPT', raising=False)
    result = host_metrics()
    assert result['configured'] is False
    assert all(value is None for value in result['values'].values())


def test_valid_receipt_is_observed(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_RECEIPT', str(receipt(tmp_path)))
    result = host_metrics()
    assert result['configured'] is True
    assert result['values'] == {
        'cpu_percent': 12.5, 'memory_percent': 42.0,
        'disk_percent': 33.0, 'network_latency_ms': 1.5,
    }


def test_stale_receipt_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_RECEIPT',
                       str(receipt(tmp_path, captured_at=time.time() - MAX_AGE_SECONDS - 1)))
    result = host_metrics()
    assert result['configured'] is True
    assert all(value is None for value in result['values'].values())


def test_out_of_range_receipt_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_RECEIPT',
                       str(receipt(tmp_path, cpu_percent=150.0, memory_percent=-1.0)))
    result = host_metrics()
    assert result['configured'] is True
    assert result['values']['cpu_percent'] is None
    assert result['values']['memory_percent'] is None
    assert result['values']['disk_percent'] == 33.0
    assert result['values']['network_latency_ms'] == 1.5


def configured(monkeypatch, path, **kwargs):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_RECEIPT', str(path))
    return host_metrics(**kwargs)


def extended_receipt(tmp_path, **overrides):
    stamp = 1000.0
    meta = {'source': 'Windows native observation', 'captured_at': stamp,
            'collection_status': 'OBSERVED', 'reason': None}
    interface = {
        **meta, 'name': 'Wi-Fi', 'description': 'Windows adapter',
        'interface_index': 3, 'status': 'Up', 'received_bytes': 12000,
        'sent_bytes': 6000, 'received_bytes_per_second': 100.0,
        'sent_bytes_per_second': 50.0, 'rate_interval_seconds': 60.0,
        'rate_status': 'OBSERVED', 'rate_reason': None,
        'received_packet_errors': 0, 'outbound_packet_errors': 0,
        'received_discarded_packets': 0, 'outbound_discarded_packets': 0,
    }
    return receipt(tmp_path, captured_at=stamp,
                   cpu={**meta, 'percent': 12.5, 'logical_processors': 16},
                   memory={**meta, 'percent': 42.0, 'total_bytes': 1000,
                           'used_bytes': 420, 'available_bytes': 580},
                   disk={**meta, 'device': 'C:', 'percent': 33.0,
                         'total_bytes': 1000, 'used_bytes': 330, 'available_bytes': 670},
                   network={**meta, 'interfaces': [interface]}, **overrides)


def test_native_detail_keeps_sample_identity_times_and_zero_errors(monkeypatch, tmp_path):
    result = configured(monkeypatch, extended_receipt(tmp_path), now=1065)
    assert result['collection_status'] == 'OBSERVED'
    assert result['captured_at'] == 1000
    assert result['captured_at_utc'] == '1970-01-01T00:16:40+00:00'
    assert result['age_seconds'] == 65
    assert result['max_age_seconds'] == 150
    assert result['source']['host_id'] == 'DESKTOP-ABEX'
    assert result['source']['writer_trust'] == 'NOT_ATTESTED'
    assert result['memory']['used_bytes'] == 420
    assert result['disk']['available_bytes'] == 670
    row = result['network']['interfaces'][0]
    assert row['received_bytes'] == 12000
    assert row['received_bytes_per_second'] == 100.0
    assert row['rate_started_at'] == 940
    assert row['received_packet_errors'] == 0
    assert row['field_status']['received_packet_errors']['collection_status'] == 'OBSERVED'
    assert result['field_status']['cpu_percent']['captured_at'] == 1000


def test_minute_cadence_jitter_is_fresh_without_redating(monkeypatch, tmp_path):
    path = receipt(tmp_path, captured_at=1000)
    result = configured(monkeypatch, path, now=1120)
    assert result['values']['cpu_percent'] == 12.5
    assert result['captured_at'] == 1000
    assert result['age_seconds'] == 120
    stale = configured(monkeypatch, path, now=1151)
    assert stale['collection_status'] == 'STALE'
    assert stale['reason'] == 'RECEIPT_STALE'
    assert stale['captured_at'] == 1000
    assert all(value is None for value in stale['values'].values())


@pytest.mark.parametrize(('content', 'reason'), [
    ('{', 'RECEIPT_MALFORMED'),
    ('{"schema":1,"schema":2}', 'RECEIPT_MALFORMED'),
    ('[]', 'RECEIPT_MALFORMED'),
    (' ' * 131073, 'RECEIPT_TOO_LARGE'),
], ids=['malformed', 'duplicate', 'non_object', 'oversized'])
def test_receipt_parse_failures_are_explicit(monkeypatch, tmp_path, content, reason):
    path = tmp_path / 'host-metrics.json'
    path.write_text(content, encoding='utf-8')
    result = configured(monkeypatch, path)
    assert result['configured'] is True
    assert result['reason'] == reason
    assert all(value is None for value in result['values'].values())


def test_missing_receipt_and_permission_denial_are_distinct(monkeypatch, tmp_path):
    path = tmp_path / 'missing.json'
    assert configured(monkeypatch, path)['reason'] == 'RECEIPT_MISSING'
    path = receipt(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError('fixture permission denial')

    monkeypatch.setattr(Path, 'open', denied)
    result = configured(monkeypatch, path)
    assert result['reason'] == 'RECEIPT_PERMISSION_DENIED'
    assert result['field_status']['cpu_percent']['reason'] == 'RECEIPT_PERMISSION_DENIED'


def test_host_identity_mismatch_is_unavailable_not_an_abex_measurement(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID', 'OTHER-HOST')
    result = configured(monkeypatch, receipt(tmp_path, captured_at=1000), now=1001)
    assert result['reason'] == 'HOST_ID_MISMATCH'
    assert result['source']['identity_check'] == 'MISMATCH'
    assert result['source']['host_id'] == 'DESKTOP-ABEX'
    assert result['captured_at'] == 1000
    assert result['values']['cpu_percent'] is None


def test_host_identity_comparison_is_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID', 'desktop-abex')
    result = configured(monkeypatch, receipt(tmp_path))
    assert result['source']['identity_check'] == 'MATCHED'
    assert result['values']['cpu_percent'] == 12.5


@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), -1, 101])
def test_non_measurements_are_not_numeric_cpu_values(monkeypatch, tmp_path, value):
    result = configured(monkeypatch, receipt(tmp_path, cpu_percent=value))
    assert result['values']['cpu_percent'] is None
    assert result['field_status']['cpu_percent']['reason'] == 'METRIC_INVALID'


def test_field_timestamp_and_collection_failure_survive_fresh_envelope(monkeypatch, tmp_path):
    path = receipt(tmp_path, captured_at=1000, field_status={
        'cpu_percent': {'captured_at': 800, 'collection_status': 'OBSERVED'},
        'memory_percent': {'captured_at': 990, 'collection_status': 'UNAVAILABLE',
                           'reason': 'PERMISSION_DENIED'},
    })
    result = configured(monkeypatch, path, now=1001)
    assert result['values']['cpu_percent'] is None
    assert result['field_status']['cpu_percent']['collection_status'] == 'STALE'
    assert result['field_status']['cpu_percent']['captured_at'] == 800
    assert result['field_status']['memory_percent']['reason'] == 'PERMISSION_DENIED'
    assert result['field_status']['memory_percent']['captured_at'] == 990
    assert result['values']['disk_percent'] == 33


def test_legacy_receipt_is_honest_about_missing_detail(monkeypatch, tmp_path):
    result = configured(monkeypatch, receipt(tmp_path))
    assert result['values']['memory_percent'] == 42
    assert result['memory']['total_bytes'] is None
    assert result['memory']['field_status']['total_bytes']['reason'] == 'DETAIL_NOT_COLLECTED'
    assert result['network']['interfaces_reason'] == 'DETAIL_NOT_COLLECTED'
    assert result['collection_status'] == 'PARTIAL'


def test_inconsistent_byte_totals_are_rejected_independently(monkeypatch, tmp_path):
    path = extended_receipt(tmp_path)
    sample = json.loads(path.read_text())
    sample['memory']['available_bytes'] = 999
    path.write_text(json.dumps(sample))
    result = configured(monkeypatch, path, now=1001)
    assert result['memory']['total_bytes'] is None
    assert result['memory']['field_status']['used_bytes']['reason'] == 'INCONSISTENT_BYTE_TOTALS'
    assert result['values']['cpu_percent'] == 12.5


def test_first_counter_sample_does_not_invent_zero_throughput(monkeypatch, tmp_path):
    path = extended_receipt(tmp_path)
    sample = json.loads(path.read_text())
    row = sample['network']['interfaces'][0]
    row.update(rate_status='UNAVAILABLE', rate_reason='RATE_BASELINE_UNAVAILABLE',
               rate_interval_seconds=None, received_bytes_per_second=None,
               sent_bytes_per_second=None, collection_status='PARTIAL')
    path.write_text(json.dumps(sample))
    result = configured(monkeypatch, path, now=1001)
    row = result['network']['interfaces'][0]
    assert row['received_bytes'] == 12000
    assert row['received_bytes_per_second'] is None
    assert row['rate_reason'] == 'RATE_BASELINE_UNAVAILABLE'
    assert row['collection_status'] == 'PARTIAL'


def test_future_receipt_and_boolean_timestamp_are_rejected(monkeypatch, tmp_path):
    assert configured(monkeypatch, receipt(tmp_path, captured_at=2000), now=1000)['reason'] == 'RECEIPT_FROM_FUTURE'
    assert configured(monkeypatch, receipt(tmp_path, captured_at=True), now=1000)['reason'] == 'RECEIPT_TIMESTAMP_INVALID'
