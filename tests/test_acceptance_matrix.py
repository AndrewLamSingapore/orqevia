import copy
import json
from pathlib import Path

import pytest
from scripts.build_acceptance_matrix import build, ROOT


def fixture(tmp_path, extra="", count=1):
    path = tmp_path / "results.xml"
    path.write_text(f'<testsuites><testsuite tests="{count}"><testcase classname="tests.test_operator_health" name="observed">{extra}</testcase></testsuite></testsuites>')
    return path


def inventory():
    return {"items": [{"item": "Health model", "phase": 4, "tests": ["tests.test_operator_health"],
                      "status": "BLOCKED", "remaining_limitation": "Hardware unavailable", "lam_action_required": False}]}


def test_fixture_success_cannot_promote_production_or_phase(tmp_path):
    report = build(inventory(), fixture(tmp_path))
    assert report["items"][0]["development_checks"] == "PASS"
    assert report["overall_status"] == "BLOCKED"
    assert not report["production_verified"] and not report["full_mandate_complete"]
    assert all(p["status"] == "BLOCKED" for p in report["phases"])


@pytest.mark.parametrize("tag", ["failure", "error", "skipped"])
def test_nonpassing_fixture_cannot_be_hidden(tmp_path, tag):
    report = build(inventory(), fixture(tmp_path, f"<{tag}/>"))
    assert report["items"][0]["development_checks"] == "BLOCKED"
    assert report["nonpassing_cases"]


@pytest.mark.parametrize("status", ["PASS", "PASS_WITH_NON_BLOCKING_LIMITATION", "DEVELOPMENT_CHECKS_PASS"])
def test_unresolved_inventory_cannot_relabel_itself_pass(tmp_path, status):
    data = inventory()
    data["items"][0]["status"] = status
    with pytest.raises(ValueError):
        build(data, fixture(tmp_path))


def test_truncated_evidence_rejects(tmp_path):
    with pytest.raises(ValueError):
        build(inventory(), fixture(tmp_path, count=2))


def test_missing_required_fixture_is_blocked(tmp_path):
    data = inventory()
    data["items"][0]["tests"] = ["tests.test_stable_spine"]
    report = build(data, fixture(tmp_path))
    assert report["items"][0]["development_checks"] == "BLOCKED"
    assert report["items"][0]["missing_test_modules"] == ["tests.test_stable_spine"]


def test_inventory_covers_all_required_items_and_phase_range():
    data = json.loads((ROOT / "governance/acceptance_inventory.v1.json").read_text())
    names = [i["item"] for i in data["items"]]
    assert len(names) == len(set(names)) == 31
    assert {"Offline Companion", "Reconciliation", "ABEX real deployment", "Executor isolation", "Documentation"} <= set(names)
    assert all(0 <= i["phase"] <= 12 for i in data["items"])
    assert all(i["remaining_limitation"] and isinstance(i["lam_action_required"], bool) for i in data["items"])

