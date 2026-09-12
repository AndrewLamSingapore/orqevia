import pytest

from app.failsafe import Failsafe, FailsafeError


def test_freeze_blocks_consequential_execution(tmp_path):
    fs = Failsafe(tmp_path / "fs.db")
    fs.assert_consequential_execution_allowed()
    fs.freeze(reason="authority unavailable")
    with pytest.raises(PermissionError):
        fs.assert_consequential_execution_allowed()


def test_freeze_survives_restart(tmp_path):
    path = tmp_path / "fs.db"
    Failsafe(path).freeze(reason="control plane unknown")
    restored = Failsafe(path)
    assert restored.snapshot().state == "EXECUTION_FREEZE"
    with pytest.raises(PermissionError):
        restored.assert_consequential_execution_allowed()


def test_recovery_cannot_skip_validation(tmp_path):
    fs = Failsafe(tmp_path / "fs.db")
    fs.freeze(reason="test")
    with pytest.raises(FailsafeError):
        fs.validate_recovery(checks_passed=True, reason="bad shortcut", changed_by="operator", owner_approval_id="x")


def test_failed_validation_returns_to_containment(tmp_path):
    fs = Failsafe(tmp_path / "fs.db")
    fs.freeze(reason="test")
    fs.request_recovery(reason="fault cleared", changed_by="operator")
    fs.begin_validation(reason="run acceptance", changed_by="operator")
    result = fs.validate_recovery(checks_passed=False, reason="acceptance failed", changed_by="operator")
    assert result.state == "CONTAINED"


def test_successful_recovery_requires_owner_approval(tmp_path):
    fs = Failsafe(tmp_path / "fs.db")
    fs.freeze(reason="test")
    fs.request_recovery(reason="fault cleared", changed_by="operator")
    fs.begin_validation(reason="run acceptance", changed_by="operator")
    with pytest.raises(FailsafeError):
        fs.validate_recovery(checks_passed=True, reason="checks green", changed_by="operator")
    result = fs.validate_recovery(checks_passed=True, reason="checks green", changed_by="operator", owner_approval_id="owner-acceptance-001")
    assert result.state == "NOMINAL"


def test_hard_lock_is_not_downgraded_by_watchdog(tmp_path):
    fs = Failsafe(tmp_path / "fs.db")
    fs.freeze(reason="invariant violation", hard=True)
    assert fs.degrade(reason="later minor fault").state == "HARD_LOCK"
    assert fs.contain(reason="later containment").state == "HARD_LOCK"
