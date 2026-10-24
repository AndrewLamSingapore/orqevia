"""Contract tests for the versioned 36-fabric registry."""

from app.fabric_registry import (
    CONTRACT_FIELDS,
    FABRIC_COUNT,
    REGISTRY_VERSION,
    STATES,
    load_fabric_registry,
    registry_report,
    validate_registry,
)


def test_registry_has_exactly_thirty_six_fabrics():
    registry = load_fabric_registry()
    assert registry["fabric_count"] == FABRIC_COUNT == 36
    assert len(registry["fabrics"]) == 36


def test_every_fabric_has_full_contract():
    registry = load_fabric_registry()
    for item in registry["fabrics"]:
        for field in CONTRACT_FIELDS:
            assert field in item, (item["id"], field)
        assert item["purpose"].strip(), item["id"]
        assert item["timeout_policy"].strip(), item["id"]
        assert item["retry_policy"].strip(), item["id"]
        assert item["lifecycle_owner"].strip(), item["id"]


def test_ids_unique_and_sequential():
    ids = [item["id"] for item in load_fabric_registry()["fabrics"]]
    assert ids == ["f%02d" % n for n in range(1, 37)]


def test_states_valid_and_honest():
    registry = load_fabric_registry()
    for item in registry["fabrics"]:
        assert item["state"] in STATES, item["id"]
        if item["state"] == "VERIFIED":
            assert item["evidence"], "VERIFIED without evidence: " + item["id"]


def test_baseline_fabric_identifiers_match_live_runtime():
    registry = load_fabric_registry()
    by_id = {item["id"]: item for item in registry["fabrics"]}
    assert by_id["f01"]["identifier"] == "ollama-local"
    assert by_id["f02"]["identifier"] == "knowledge-minilm"
    assert by_id["f03"]["identifier"] == "semantic-nli"
    assert by_id["f04"]["identifier"] == "geospatial-intelligence"
    assert by_id["f05"]["identifier"] == "portfolio-event-fabric"
    assert by_id["f06"]["identifier"] == "mlp-fabric"
    assert by_id["f07"]["identifier"] == "hf-gemma-nano"


def test_mlp_never_grants_agent_authority():
    mlp = next(x for x in load_fabric_registry()["fabrics"] if x["id"] == "f06")
    assert "grants_agent_authority=false" in mlp["notes"]
    assert "automatic_training=false" in mlp["notes"]


def test_no_fabric_beyond_seven_claims_verified_without_evidence():
    registry = load_fabric_registry()
    for item in registry["fabrics"]:
        if item["id"] not in ("f05", "f06", "f07"):
            assert item["state"] != "VERIFIED" or item["evidence"], item["id"]


def test_report_counts_are_consistent():
    report = registry_report()
    assert sum(report["state_counts"].values()) == 36
    assert report["registry_version"] == REGISTRY_VERSION
    assert len(report["fabrics"]) == 36
    states = {item["state"] for item in report["fabrics"]}
    assert states <= set(STATES)


def test_validator_rejects_bad_state():
    registry = load_fabric_registry()
    broken = dict(registry["fabrics"][0])
    broken["state"] = "MAGIC"
    try:
        validate_registry([broken] + registry["fabrics"][1:])
    except ValueError as exc:
        assert "invalid state" in str(exc)
    else:
        raise AssertionError("validator accepted an invalid state")


def test_validator_rejects_verified_without_evidence():
    registry = load_fabric_registry()
    broken = dict(registry["fabrics"][0])
    broken["state"] = "VERIFIED"
    broken["evidence"] = []
    try:
        validate_registry([broken] + registry["fabrics"][1:])
    except ValueError as exc:
        assert "no recorded evidence" in str(exc)
    else:
        raise AssertionError("validator accepted VERIFIED without evidence")
