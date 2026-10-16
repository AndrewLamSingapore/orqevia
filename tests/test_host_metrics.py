import json
import time

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
    monkeypatch.delenv('PRIME_HOST_METRICS_RECEIPT', raising=False)
    result = host_metrics()
    assert result['configured'] is False
    assert all(value is None for value in result['values'].values())


def test_valid_receipt_is_observed(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_HOST_METRICS_RECEIPT', str(receipt(tmp_path)))
    result = host_metrics()
    assert result['configured'] is True
    assert result['values'] == {
        'cpu_percent': 12.5, 'memory_percent': 42.0,
        'disk_percent': 33.0, 'network_latency_ms': 1.5,
    }


def test_stale_receipt_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_HOST_METRICS_RECEIPT',
                       str(receipt(tmp_path, captured_at=time.time() - MAX_AGE_SECONDS - 1)))
    result = host_metrics()
    assert result['configured'] is True
    assert all(value is None for value in result['values'].values())


def test_out_of_range_receipt_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_HOST_METRICS_RECEIPT',
                       str(receipt(tmp_path, cpu_percent=150.0, memory_percent=-1.0)))
    result = host_metrics()
    assert result['configured'] is True
    assert result['values']['cpu_percent'] is None
    assert result['values']['memory_percent'] is None
    assert result['values']['disk_percent'] == 33.0
    assert result['values']['network_latency_ms'] == 1.5
