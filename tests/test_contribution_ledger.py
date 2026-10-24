import pytest

from app.contribution_ledger import ContributionLedger


def test_record_totals_and_recent(tmp_path):
    ledger = ContributionLedger(tmp_path / "ledger.db")
    ledger.record("a01", "sweep_round", 1, {"round": 1}, source_revision="b3ae4211")
    ledger.record("a01", "finding_reported", 3)
    totals = {row["contributor"]: row["units"] for row in ledger.totals()}
    assert totals["a01"] == 4
    assert len(ledger.recent(10)) == 2


def test_validation(tmp_path):
    ledger = ContributionLedger(tmp_path / "ledger.db")
    with pytest.raises(ValueError):
        ledger.record("", "sweep_round")
    with pytest.raises(ValueError):
        ledger.record("a01", "bad kind!")
    with pytest.raises(ValueError):
        ledger.record("a01", "sweep_round", 0)
