"""Routing fixtures exercise capability ownership, not organizational status."""

import json

import pytest

from app import capability_selection as selection
from app.agent_registry import RegistryError, responsibility_owner


@pytest.mark.parametrize(
    "objective, expected",
    [
        ("Investigate dataset anomalies", "responsibility.a12"),
        ("Analyze ORQEVIA runtime authority architecture", "responsibility.a16"),
        ("Estimate budget exposure", "responsibility.a21"),
        ("Compare competing approaches", "responsibility.a08"),
        ("Implement a parser", "responsibility.a17"),
        ("Prepare rollback instructions", "responsibility.a29"),
        ("Identify provenance gaps", "responsibility.a14"),
        ("Choose a trade-off", "responsibility.a04"),
        ("Explain planetary motion", "responsibility.a02"),
        ("Discuss the hardware shipment", "responsibility.a02"),
    ],
)
def test_selects_one_explicit_owned_capability(objective, expected):
    result = selection.select_capability(objective)
    assert result == expected
    assert responsibility_owner(result)


def configure(tmp_path, monkeypatch, routes):
    path = tmp_path / "routes.json"
    path.write_text(json.dumps(routes), encoding="utf-8")
    monkeypatch.setattr(selection, "ROUTES_PATH", path)


def test_new_inventory_capability_needs_no_reporting_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        selection,
        "load_agent_registry",
        lambda: {
            "agents": [
                {"lifecycle_status": "active", "capability_requirements": ["reasoning.general", "reasoning.geometry"]}
            ]
        },
    )
    configure(
        tmp_path,
        monkeypatch,
        {
            "schema": "orqevia.task-capability-routes.v1",
            "default": "reasoning.general",
            "routes": [{"capability": "reasoning.geometry", "terms": ["geometry"]}],
        },
    )
    assert selection.select_capability("Solve a geometry exercise") == "reasoning.geometry"
    assert selection.select_capability("An unrelated request") == "reasoning.general"


def test_retired_capability_is_not_selected(tmp_path, monkeypatch):
    configure(
        tmp_path,
        monkeypatch,
        {
            "schema": "orqevia.task-capability-routes.v1",
            "default": "responsibility.a02",
            "routes": [{"capability": "retired.capability", "terms": ["test"]}],
        },
    )
    assert selection.select_capability("test") == "responsibility.a02"


def test_missing_default_fails_without_inventing_identity(tmp_path, monkeypatch):
    configure(
        tmp_path,
        monkeypatch,
        {"schema": "orqevia.task-capability-routes.v1", "default": "invented", "routes": []},
    )
    with pytest.raises(RegistryError, match="unavailable"):
        selection.select_capability("test")
