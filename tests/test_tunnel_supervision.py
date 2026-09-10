import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import subprocess
import hashlib
import os
import sys
from types import SimpleNamespace

import pytest

from scripts import supervise_tunnel as tunnel
from app.operator_health import tunnel_status, interpret


def test_process_death_backs_off_and_exhausts_without_resetting_on_launch():
    recovery = tunnel.Recovery()
    now = 0
    for attempt in range(5):
        assert recovery.tick(now, False, False) == "START"
        assert recovery.tick(now + 1, False, False) == "PROCESS_EXITED"
        assert recovery.failures == attempt + 1
        if attempt < 4:
            assert recovery.tick(now + 1, False, False) == "WAIT"
        now = recovery.next_start
    assert recovery.tick(now, False, False) == "EXHAUSTED"
    assert tunnel.Recovery(recovery.failures).tick(now, False, False) == "EXHAUSTED"


def test_network_loss_has_grace_and_recovery_requires_sustained_health():
    recovery = tunnel.Recovery(2)
    assert recovery.tick(0, False, False) == "START"
    assert recovery.tick(10, True, False) == "STARTING"
    assert recovery.tick(30, True, False) == "DEGRADED"
    assert recovery.tick(40, True, False) == "DEGRADED"
    assert recovery.tick(50, True, False) == "RESTART"
    assert recovery.failures == 3
    assert recovery.tick(60, False, False) == "START"
    assert recovery.tick(70, True, True) == "HEALTHY"
    assert recovery.failures == 3
    assert recovery.tick(370, True, True) == "HEALTHY"
    assert recovery.failures == 0


def test_persisted_exhaustion_and_failure_history_survive_restart(tmp_path):
    evidence = tunnel.Evidence(tmp_path)
    evidence.record("PROCESS_EXITED", 1, False)
    evidence.record("HEALTHY", 1, True)
    assert evidence.state["reconnect_count"] == 1
    evidence.record("EXHAUSTED", 5, False)
    restored = tunnel.Evidence(tmp_path)
    assert restored.state["last_failure"]
    assert tunnel.Recovery(restored.state["consecutive_failures"]).tick(0, False, False) == "EXHAUSTED"
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 3
    assert restored.state["authority_changed"] is False


def test_health_probe_is_bounded_read_only_and_discards_raw_output(monkeypatch, tmp_path):
    run = Mock(side_effect=subprocess.TimeoutExpired("health", 8, output="secret-fixture"))
    monkeypatch.setattr(tunnel.subprocess, "run", run)
    monkeypatch.setattr(tunnel.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    assert tunnel.ready("tunnel-client.exe", tmp_path / "health.url", 123) is False
    args, kwargs = run.call_args
    assert args[0][1] == "health" and "--require-control-plane-poll" in args[0]
    assert "--pid" in args[0] and "123" in args[0]
    assert kwargs["timeout"] == 8
    assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize("age,expected", [(0, "HEALTHY"), (60, "STALE"), (-60, "STALE")])
def test_operator_never_reports_stale_tunnel_evidence_healthy(tmp_path, age, expected):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"state":"HEALTHY", "observed_at":(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat(),
                             "process_running":True, "secret":"must-not-project"}))
    result = tunnel_status(p)
    assert result["state"] == expected
    assert "must-not-project" not in str(result)
    if age == 0:
        stopped = json.loads(p.read_text())
        stopped["process_running"] = False
        p.write_text(json.dumps(stopped))
        assert tunnel_status(p)["state"] == "DEGRADED"


def test_tunnel_outage_does_not_block_independent_local_work_or_grant_authority():
    evidence = {"authority":{"configured":True,"pilot_enabled":True},
                "worker":{"configured_ceiling":1,"running_workers":1},
                "stores":{k:{"ok":True} for k in ("spine","harness","queue","compute")},
                "local_ready":True,"tunnel":{"state":"EXHAUSTED"}}
    result = interpret(evidence)
    assert result["state"] == "DEGRADED" and result["ready_for_local_work"] is True
    assert result["authority_granted"] is False and result["production_ready"] is False
    evidence["authority"]["configured"] = False
    result = interpret(evidence)
    assert result["state"] == "SAFE_STOP" and result["ready_for_local_work"] is False


@pytest.mark.parametrize("dependency_ready", [True, False])
def test_supervisor_driver_bounds_restarts_and_retains_real_evidence(monkeypatch, tmp_path, dependency_ready):
    binary, profile = tmp_path / "tunnel-client.exe", tmp_path / "approved.yaml"
    binary.write_bytes(b"fixture")
    profile.write_bytes(b"fixture existing profile, never a real credential")
    monkeypatch.setattr(tunnel, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA":str(tmp_path)}, fsync=os.fsync))
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(locking=Mock(), LK_NBLCK=1))
    monkeypatch.setattr(tunnel.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(tunnel.subprocess, "run", Mock(return_value=SimpleNamespace(stdout="")))
    children = []
    class Child:
        pid = 123
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, timeout): return 0
    def start(*args):
        child = Child()
        children.append(child)
        return child
    monkeypatch.setattr(tunnel, "launch", start)
    monkeypatch.setattr(tunnel, "ready", lambda *args: False)
    monkeypatch.setattr(tunnel, "prime_ready", lambda: dependency_ready)
    clock = iter(range(0, 10000, 10))
    monkeypatch.setattr(tunnel.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(tunnel.time, "sleep", lambda seconds: None)
    fingerprint = hashlib.sha256(profile.read_bytes()).hexdigest()
    evidence = tmp_path / "evidence"
    assert tunnel.supervise(binary, profile, evidence, fingerprint) == 1
    expected_children = 5 if dependency_ready else 0
    assert len(children) == expected_children and all(child.stopped for child in children)
    assert json.loads((evidence / "status.json").read_text())["state"] == "EXHAUSTED"
    # A supervisor restart does not reset the persisted retry limit.
    assert tunnel.supervise(binary, profile, evidence, fingerprint) == 1
    assert len(children) == expected_children
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == fingerprint
    profile.write_bytes(b"modified profile")
    with pytest.raises(ValueError, match="approved profile changed"):
        tunnel.supervise(binary, profile, evidence, fingerprint)
    assert len(children) == expected_children
