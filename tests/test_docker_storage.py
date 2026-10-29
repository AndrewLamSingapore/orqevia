"""Metadata privacy, incomplete evidence, offline refusal and copy integrity."""

import io
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import docker_cold_backup as backup
import docker_storage_monitor as monitor


def test_projection_omits_credentials_commands_and_health_output():
    item = {
        "Id": "a" * 64,
        "Name": "/fixture",
        "Image": "sha256:fixture",
        "Config": {"Env": ["SECRET=never-export"], "Cmd": ["private command"], "Labels": {}},
        "HostConfig": {},
        "State": {"Health": {"Status": "healthy", "Log": ["secret health text"]}},
    }
    projected = monitor.container_projection(item)
    text = json.dumps(projected)
    assert "never-export" not in text and "private command" not in text and "secret health text" not in text
    assert projected["health"] == "healthy"
    assert len(projected["configuration_sha256"]) == 64


def test_growth_requires_history_and_reasonable_interval():
    now = {"schema": "v1", "observed_epoch": 100, "virtual_disks": []}
    assert monitor.growth(now, None)["status"] == "INSUFFICIENT_HISTORY"
    assert monitor.growth(now, {**now, "observed_epoch": 99})["status"] == "INTERVAL_TOO_SHORT"


def test_growth_keeps_negative_deltas_without_claiming_reclamation():
    before = {"schema": "v1", "observed_epoch": 0, "virtual_disks": [{"path": "disk", "allocated_bytes": 200}]}
    after = {"schema": "v1", "observed_epoch": 86400, "virtual_disks": [{"path": "disk", "allocated_bytes": 150}]}
    result = monitor.growth(after, before)
    assert result["rates_bytes_per_day"]["disk"] == -50
    assert "NOT_RECLAIMABILITY" in result["status"]


def test_atomic_output_and_missing_vhdx(tmp_path):
    target = tmp_path / "report.json"
    monitor.atomic_json(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert list(tmp_path.iterdir()) == [target]
    assert monitor.vhdx_metadata(tmp_path / "absent")["allocated_bytes"] is None


def test_logging_plan_binds_current_identity_and_never_applies():
    item = {
        "name": "orqevia-intelligence-1",
        "id": "a",
        "image_id": "b",
        "configuration_sha256": "c",
        "logging": {"Type": "json-file", "Config": {}},
        "compose_project": None,
    }
    result = monitor.logging_plan({"containers": [item]})
    assert "NOT_APPLIED" in result["status"]
    assert result["proposed_log_config"]["Config"] == {"max-size": "10m", "max-file": "3"}


def test_cold_copy_refuses_without_maintenance_authorization(tmp_path):
    with pytest.raises(ValueError, match="explicitly authorize"):
        backup.copy_offline(tmp_path / "must-not-exist", False)
    assert not (tmp_path / "must-not-exist").exists()


def test_cold_copy_refuses_active_docker_before_output(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "plan", lambda destination: {"all_sources_exist": True, "capacity_sufficient": True})

    def active():
        raise RuntimeError("Docker active")

    monkeypatch.setattr(backup, "require_offline", active)
    with pytest.raises(RuntimeError, match="Docker active"):
        backup.copy_offline(tmp_path / "must-not-exist", True)
    assert not (tmp_path / "must-not-exist").exists()


def test_verified_copy_readback_and_never_overwrite(tmp_path):
    target = tmp_path / "fixture.vhdx"
    data = b"deterministic fixture" * 100
    record = backup.copy_stream_verified(io.BytesIO(data), target)
    assert target.read_bytes() == data and record["bytes"] == len(data)
    with pytest.raises(FileExistsError):
        backup.copy_stream_verified(io.BytesIO(b"replace"), target)
    assert target.read_bytes() == data


def test_manifest_verification_detects_corruption_and_incomplete_backup(tmp_path):
    entries = {
        name: backup.copy_stream_verified(io.BytesIO(name.encode()), tmp_path / filename)
        for name, filename in [("data", "docker_data.vhdx"), ("boot", "ext4.vhdx")]
    }
    manifest = {"copy_status": "IN_PROGRESS", "disks": entries}
    monitor.atomic_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Incomplete"):
        backup.verify(tmp_path)
    manifest["copy_status"] = "HASH_VERIFIED_BOTH_DISKS_NOT_RESTORE_QUALIFIED"
    monitor.atomic_json(tmp_path / "manifest.json", manifest)
    assert backup.verify(tmp_path)["restore_qualification"] == "NOT_TESTED"
    (tmp_path / "ext4.vhdx").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        backup.verify(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows exclusive handle contract")
def test_windows_share_none_handle_prevents_live_reopen_and_copies_fixture(tmp_path):
    source = tmp_path / "fixture-source.vhdx"
    source.write_bytes(b"offline fixture" * 100)
    target = tmp_path / "fixture-copy.vhdx"
    with backup.exclusive_read(source) as stream:
        with pytest.raises(OSError):
            source.open("rb")
        record = backup.copy_stream_verified(stream, target)
    assert source.read_bytes() == target.read_bytes()
    assert record["sha256"] == backup.digest_file(source)


def test_backup_plan_measures_both_fixture_disks_without_creating_destination(tmp_path, monkeypatch):
    paths = {name: tmp_path / filename for name, filename in [("data", "d.vhdx"), ("boot", "b.vhdx")]}
    for value in paths.values():
        value.write_bytes(b"fixture")
    monkeypatch.setattr(backup, "sources", lambda: paths)
    target = tmp_path / "new-backup"
    result = backup.plan(target)
    assert result["required_copy_bytes"] == 14
    assert result["all_sources_exist"] and result["capacity_sufficient"]
    assert not target.exists()


def test_unavailable_docker_emits_fresh_unknown_receipt_without_raw_diagnostics(tmp_path, monkeypatch):
    def fail(previous):
        raise RuntimeError("private diagnostic must never be exported")

    monkeypatch.setattr(monitor, "collect", fail)
    output = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", ["monitor", "--output", str(output)])
    assert monitor.main() == 1
    report = json.loads(output.read_text())
    assert report["status"] == "UNAVAILABLE" and report["running_count"] is None
    assert "private diagnostic" not in output.read_text()
