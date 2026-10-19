"""Receipt-contract tests only; no actual sensor, stress or inference workload."""
import hashlib
import json
import sqlite3
import time

import pytest

from app import ssd_thermal


def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('ORQEVIA_LOCAL_ADMISSION_MODE', 'measured')
    policy = {
        'schema': ssd_thermal.POLICY_SCHEMA,
        'host': 'DESKTOP-27LKJ2V', 'device_id': '0',
        'serial_number': 'exact-drive-serial', 'friendly_name': 'Lexar SSD NM610 PRO 1TB',
        'sensor': ssd_thermal.SENSOR, 'max_operating_c': 80,
        'limit_source': 'synthetic-test-fixture:not-a-manufacturer-claim',
        'reader_sha256': 'a' * 64, 'required_sensor_numbers': [1, 2],
    }
    policy_path = tmp_path / 'policy.json'
    raw = json.dumps(policy).encode()
    policy_path.write_bytes(raw)
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_ENFORCE', '1')
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_POLICY', str(policy_path))
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_POLICY_SHA256', hashlib.sha256(raw).hexdigest())
    receipt_path = tmp_path / 'reading.json'
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_RECEIPT', str(receipt_path))
    return policy, receipt_path


def reading(policy, *, temperature=52, captured=None):
    return {**{key: policy[key] for key in ('host', 'device_id', 'serial_number', 'friendly_name', 'sensor', 'reader_sha256')},
            'schema': ssd_thermal.RECEIPT_SCHEMA,
            'source': ssd_thermal.SOURCE, 'unit': 'C',
            'composite_temperature_c': temperature,
            'temperature_sensors': [{'number': 1, 'celsius': temperature},
                                    {'number': 2, 'celsius': temperature + 7}],
            'critical_warning_bits': 0,
            'media_data_integrity_errors': '0', 'error_log_entries': '0',
            'captured_at': time.time() if captured is None else captured,
            'collector_id': 'independent-test-collector', 'boot_id': 'boot-1', 'read_ok': True}


def test_heavy_requires_fresh_exact_sensor_and_scope(tmp_path, monkeypatch):
    policy, receipt_path = configured(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(6000)
    receipt = reading(policy)
    receipt_path.write_text(json.dumps(receipt))
    ssd_thermal.require_for_demand(6000)
    for mutation in (
        {'serial_number': 'other-drive'}, {'device_id': '1'},
        {'sensor': 'unverified-hotspot'}, {'unit': 'F'}, {'read_ok': 'true'},
        {'reader_sha256': 'b' * 64}, {'critical_warning_bits': 1},
        {'media_data_integrity_errors': '1'}, {'error_log_entries': '2'},
        {'media_data_integrity_errors': 0}, {'error_log_entries': '00'},
        {'composite_temperature_c': 0}, {'captured_at': time.time() - 31},
        {'captured_at': time.time() + 1}, {'composite_temperature_c': 75},
        {'temperature_sensors': [{'number': 1, 'celsius': 52}]},
        {'temperature_sensors': [{'number': 2, 'celsius': 52}, {'number': 1, 'celsius': 59}]},
    ):
        receipt_path.write_text(json.dumps({**receipt, **mutation}))
        try:
            ssd_thermal.require_for_demand(6000)
        except PermissionError:
            pass
        else:
            raise AssertionError(f'mutation admitted: {mutation}')


def test_light_bound_survives_missing_policy_but_heavy_fails_closed(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    monkeypatch.delenv('ORQEVIA_SSD_THERMAL_POLICY')
    ssd_thermal.require_for_demand(1024)
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(1025)
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_ENFORCE', 'yes')
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(1024)


def test_hottest_smart_sensor_controls_admission(tmp_path, monkeypatch):
    policy, receipt_path = configured(tmp_path, monkeypatch)
    sample = reading(policy, temperature=52)
    sample['temperature_sensors'][1]['celsius'] = 75
    receipt_path.write_text(json.dumps(sample))
    with pytest.raises(PermissionError, match='thermal headroom'):
        ssd_thermal.require_for_demand(6000)


def test_optional_profile_field_cannot_exempt_heavy_work(tmp_path, monkeypatch):
    policy, _ = configured(tmp_path, monkeypatch)
    policy['heavy_demand_mib'] = 1000000
    raw = json.dumps(policy).encode()
    (tmp_path / 'policy.json').write_bytes(raw)
    monkeypatch.setenv('ORQEVIA_SSD_THERMAL_POLICY_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(1025)


def test_privileged_wrapper_has_no_caller_supplied_paths_or_commands():
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'collect-ssd-temperature.ps1'
    source = script.read_text(encoding='utf-8')
    assert 'param(' not in source.lower()
    assert "$args.Count -ne 0" in source
    assert "$Root = 'C:\\ProgramData\\ABEX\\PrimeThermal'" in source
    assert '$ReaderScript = Join-Path $Root' in source
    assert '$RawEvidencePath = Join-Path $RawDirectory' in source
    assert '$OutputPath = Join-Path $OutputDirectory' in source
    assert '[IO.FileAttributes]::ReparsePoint' in source


def test_tampered_policy_and_duplicate_receipt_rejected(tmp_path, monkeypatch):
    policy, receipt_path = configured(tmp_path, monkeypatch)
    (tmp_path / 'policy.json').write_text(json.dumps({**policy, 'max_operating_c': 150}))
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(6000)
    raw = json.dumps(policy).encode()
    (tmp_path / 'policy.json').write_bytes(raw)
    receipt_path.write_text(json.dumps(reading(policy))[:-1] + ',"composite_temperature_c":20}')
    with pytest.raises(PermissionError):
        ssd_thermal.require_for_demand(6000)


