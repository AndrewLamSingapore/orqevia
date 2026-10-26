"""Contract tests for the versioned 36-fabric registry."""

from copy import deepcopy
import hashlib
import json
import re
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import fabric_runtime
from app.collective_api import router

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


def test_schema_objects_are_independent_between_fabrics_and_directions():
    registry = load_fabric_registry()
    registry["fabrics"][0]["input_schema"]["injected"] = True
    assert "injected" not in registry["fabrics"][0]["output_schema"]
    assert "injected" not in registry["fabrics"][1]["input_schema"]


def test_validator_rejects_replacement_id_and_duplicate_runtime_identifier():
    import pytest

    registry = load_fabric_registry()
    registry["fabrics"][-1]["id"] = "f37"
    with pytest.raises(ValueError, match="f01-f36"):
        validate_registry(registry["fabrics"])
    registry = load_fabric_registry()
    registry["fabrics"][1]["identifier"] = registry["fabrics"][0]["identifier"]
    with pytest.raises(ValueError, match="unique"):
        validate_registry(registry["fabrics"])


def test_supported_http_operations_have_defined_top_level_schemas():
    registry = load_fabric_registry()
    assert all(item["contract_status"] == "DEFINED_FOR_LISTED_OPERATIONS" for item in registry["fabrics"])
    assert all(item["state"] == "IMPLEMENTED" for item in registry["fabrics"])
    assert registry_report(registry)["state_counts"]["VERIFIED"] == 0


def test_existing_forecast_and_financial_implementations_are_not_duplicated():
    by_id = {x["id"]: x for x in load_fabric_registry()["fabrics"]}
    assert by_id["f26"]["state"] == by_id["f34"]["state"] == "IMPLEMENTED"
    assert "not validated coverage guarantees" in " ".join(by_id["f26"]["limitations"]).lower()
    assert any("project_workflows.py" in dependency for dependency in by_id["f34"]["dependencies"])


def _assert_declared_shape(value, schema):
    """Test the vocabulary declared here; this is not a general JSON Schema engine.

    Primitive constraints reuse the existing operation validator. These tests
    also inspect declared branch/field relationships. Separate operator evidence
    uses the already installed jsonschema package for full standards validation.
    """
    for keyword in ("oneOf", "anyOf"):
        if keyword in schema:
            matches = 0
            for branch in schema[keyword]:
                try:
                    _assert_declared_shape(value, branch)
                    matches += 1
                except (AssertionError, ValueError, TypeError):
                    pass
            assert matches == 1 if keyword == "oneOf" else matches >= 1
    if "const" in schema:
        assert value == schema["const"] and isinstance(value, bool) == isinstance(schema["const"], bool)
    if "enum" in schema:
        assert value in schema["enum"]
    kind = schema.get("type")
    if isinstance(kind, list):
        choices = [{**schema, "type": item} for item in kind]
        _assert_declared_shape(value, {"anyOf": choices})
        return
    if kind == "null":
        assert value is None
        return
    primitive = {
        key: item
        for key, item in schema.items()
        if key not in {"properties", "items", "additionalProperties", "required"}
    }
    if kind == "array":
        primitive["items"] = {}
    fabric_runtime._validate(value, primitive)
    if kind == "object":
        assert set(schema.get("required", [])) <= value.keys()
        assert schema.get("minProperties", 0) <= len(value) <= schema.get("maxProperties", 50000)
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, item in value.items():
            if key in properties:
                _assert_declared_shape(item, properties[key])
                continue
            matching = [subschema for pattern, subschema in patterns.items() if re.search(pattern, key)]
            if matching:
                for subschema in matching:
                    _assert_declared_shape(item, subschema)
            elif schema.get("additionalProperties") is False:
                raise AssertionError("Undeclared field: " + key)
            elif isinstance(schema.get("additionalProperties"), dict):
                _assert_declared_shape(item, schema["additionalProperties"])
    elif kind == "array":
        prefix = schema.get("prefixItems", [])
        for index, item in enumerate(value):
            _assert_declared_shape(item, prefix[index] if index < len(prefix) else schema.get("items", {}))


def _request_branch(item, operation):
    branches = item["input_schema"]["oneOf"]
    matches = [branch for branch in branches if branch["properties"]["operation"]["const"] == operation]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("identifier", ["f%02d" % number for number in range(1, 37)])
def test_every_http_contract_binds_real_operations_and_full_envelope(identifier):
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == identifier)
    runtime = item["runtime_contract"]
    assert item["operations"] == [operation["operation"] for operation in runtime["operations"]]
    assert item["input_schema"] == runtime["request_schema"]
    assert item["output_schema"] == runtime["response_schema"]
    assert item["output_schema"]["properties"]["data"] == runtime["execution_receipt_schema"]
    assert item["input_schema"]["$schema"].endswith("/2020-12/schema")
    assert set(item["output_schema"]["required"]) == {
        "protocol",
        "observed_at",
        "correlation_id",
        "data",
        "grants_execution_authority",
    }
    for operation in runtime["operations"]:
        branch = _request_branch(item, operation["operation"])
        assert set(branch["properties"]) == {"operation", "parameters", "execution_id"}
        assert "execution_id" not in branch["required"]
        assert branch["properties"]["parameters"]["type"] == "object"
        assert operation["output_schema"] != {"type": "object"}
        assert operation["scope"]


def test_local_repository_contracts_remain_separate_and_intact():
    by_id = {item["id"]: item for item in load_fabric_registry()["fabrics"]}
    local_analysis = by_id["f10"]["local_entrypoint_contract"]
    assert local_analysis["input_schema"]["required"] == ["repository", "profile", "evidence_root"]
    assert "directory" in local_analysis["output_schema"]["properties"]
    assert local_analysis["entrypoint"] == "scripts/evaluate_repository.py"
    local_verification = by_id["f12"]["local_entrypoint_contract"]
    assert local_verification["input_schema"]["required"] == ["receipt_directory"]
    assert local_verification["output_schema"]["properties"]["publication_authorized"] == {"const": False}
    assert local_verification["entrypoint"] == "app.repository_evaluation:verify_receipt"
    assert by_id["f10"]["operations"] == ["inspect_deployed_module"]
    assert by_id["f12"]["operations"] == ["verify_execution_integrity"]


def test_wrappers_reject_unknown_operation_extra_fields_and_invalid_parameters():
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f04")
    good = {"operation": "distance_km", "parameters": {"a": [0, 0], "b": [0, 1]}}
    _assert_declared_shape(good, item["input_schema"])
    for wrong in (
        {**good, "operation": "execute_arbitrary_command"},
        {**good, "role": "SYSTEM"},
        {"operation": "distance_km"},
        {**good, "execution_id": "not-a-uuid"},
        {**good, "parameters": {"a": [91, 0], "b": [0, 1]}},
    ):
        with pytest.raises((AssertionError, ValueError)):
            _assert_declared_shape(wrong, item["input_schema"])


def test_retrieval_bounds_match_both_existing_local_backends():
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f02")
    accepted = {"operation": "retrieve", "parameters": {"question": "x" * 4096, "top_k": 5}}
    _assert_declared_shape(accepted, item["input_schema"])
    for parameters in ({"question": "x" * 4097}, {"question": "evidence", "top_k": 6}):
        with pytest.raises((AssertionError, ValueError)):
            _assert_declared_shape({"operation": "retrieve", "parameters": parameters}, item["input_schema"])


def test_tool_argument_contract_is_discriminated_by_the_allowlisted_tool():
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f09")
    good = {"operation": "invoke_tool", "parameters": {"tool": "geo.distance", "arguments": {"a": [0, 0], "b": [0, 1]}}}
    _assert_declared_shape(good, item["input_schema"])
    good["parameters"]["tool"] = "mlp.reference"
    with pytest.raises(AssertionError):
        _assert_declared_shape(good, item["input_schema"])


@pytest.fixture
def contract_client(tmp_path, monkeypatch):
    import hashlib

    owner, token = "contract-fixture-owner", "contract-fixture-local-authority"
    for key, value in {
        "ORQEVIA_SPINE_TOKEN": token,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": owner,
        "ORQEVIA_COLLECTIVE_ENABLED": "1",
        "ORQEVIA_DATA_DIR": str(tmp_path),
        "ORQEVIA_RUNTIME_REVISION": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.headers.update(
        {
            "Authorization": "Bearer " + token,
            "X-ORQEVIA-Owner": hashlib.sha256(owner.encode()).hexdigest(),
            "X-ORQEVIA-Actor": "contract-test",
        }
    )
    yield client
    client.close()


@pytest.mark.parametrize(
    "identifier,operation,parameters",
    [
        ("f04", "distance_km", {"a": [0, 0], "b": [0, 1]}),
        ("f06", "reference_infer", {"rows": [{"x": 0.5}]}),
        ("f09", "invoke_tool", {"tool": "geo.distance", "arguments": {"a": [0, 0], "b": [0, 1]}}),
        ("f09", "invoke_tool", {"tool": "mlp.reference", "arguments": {"rows": [{"x": 0.5}]}}),
        ("f10", "inspect_deployed_module", {"module": "fabric_registry"}),
        (
            "f14",
            "store_context",
            {"key": "fixture", "value": {"note": "contract canary"}, "source": "synthetic unit test"},
        ),
        ("f14", "search_context", {"query": "contract canary"}),
        ("f15", "execution_metrics", {}),
        ("f16", "release_identity", {}),
        (
            "f18",
            "prepare_storyboard",
            {
                "brief": "fixture",
                "scenes": [{"description": "product capture", "seconds": 5, "source_kind": "product_capture"}],
            },
        ),
        ("f24", "evaluate_tool_permission", {"tool": "geo.distance", "consequential": False}),
        ("f29", "bound_identity", {}),
        ("f33", "edge_telemetry", {}),
    ],
)
def test_actual_deterministic_http_results_conform_and_missing_fields_do_not(
    contract_client, identifier, operation, parameters
):
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == identifier)
    body = {"operation": operation, "parameters": parameters, "execution_id": str(uuid.uuid4())}
    _assert_declared_shape(body, item["input_schema"])
    response = contract_client.post(f"/api/collective/v1/fabrics/{identifier}/execute", json=body)
    assert response.status_code == 200, response.json()
    actual = response.json()
    assert actual["data"]["status"] == "COMPLETED"
    _assert_declared_shape(actual, item["output_schema"])
    broken = deepcopy(actual)
    broken["data"]["result"].pop(next(iter(broken["data"]["result"])))
    with pytest.raises(AssertionError):
        _assert_declared_shape(broken, item["output_schema"])


def test_actual_memory_search_and_integrity_results_keep_result_contracts(contract_client):
    first = contract_client.post(
        "/api/collective/v1/fabrics/f14/execute",
        json={
            "operation": "store_context",
            "parameters": {
                "key": "memory-canary",
                "value": {"text": "cobaltcontractcanary"},
                "source": "synthetic unit test",
            },
        },
    )
    first.raise_for_status()
    contracts = {item["id"]: item for item in load_fabric_registry()["fabrics"]}
    search = contract_client.post(
        "/api/collective/v1/fabrics/f14/execute",
        json={"operation": "search_context", "parameters": {"query": "cobaltcontractcanary"}},
    ).json()
    assert len(search["data"]["result"]["records"]) == 1
    _assert_declared_shape(search, contracts["f14"]["output_schema"])
    check = contract_client.post(
        "/api/collective/v1/fabrics/f12/execute",
        json={
            "operation": "verify_execution_integrity",
            "parameters": {"execution_id": first.json()["data"]["execution_id"]},
        },
    ).json()
    assert check["data"]["result"]["integrity_verified"] is True
    _assert_declared_shape(check, contracts["f12"]["output_schema"])


def test_empty_parameter_and_execution_id_defaults_match_the_real_http_wrapper(contract_client):
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f16")
    body = {"operation": "release_identity"}
    _assert_declared_shape(body, item["input_schema"])
    response = contract_client.post("/api/collective/v1/fabrics/f16/execute", json=body)
    assert response.status_code == 200
    value = response.json()
    assert str(uuid.UUID(value["data"]["execution_id"])) == value["data"]["execution_id"]
    _assert_declared_shape(value, item["output_schema"])


def test_replayed_failed_receipt_is_typed_without_being_relabelled_completed(contract_client):
    identifier = str(uuid.uuid4())
    body = {
        "operation": "inspect_deployed_module",
        "parameters": {"module": "missing_schema_fixture_module"},
        "execution_id": identifier,
    }
    assert contract_client.post("/api/collective/v1/fabrics/f10/execute", json=body).status_code == 422
    replay = contract_client.post("/api/collective/v1/fabrics/f10/execute", json=body)
    assert replay.status_code == 200 and replay.json()["data"]["status"] == "FAILED"
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f10")
    _assert_declared_shape(replay.json(), item["output_schema"])
    assert replay.json()["data"]["result"] is None
    assert replay.json()["data"]["result_json"] is None


def test_validator_rejects_catalog_operation_drift():
    registry = load_fabric_registry()
    registry["fabrics"][0]["operations"] = ["infer_without_queue"]
    with pytest.raises(ValueError, match="match the executable"):
        validate_registry(registry["fabrics"])


def test_scope_limits_remain_explicit_in_current_contracts():
    entries = {item["id"]: item for item in load_fabric_registry()["fabrics"]}
    assert "speech recognition" in entries["f31"]["notes"].lower()
    assert "No attached robot" in entries["f33"]["notes"]
    assert "new MCP" in entries["f09"]["notes"]
    assert "confidential-computing" in entries["f28"]["notes"]
    assert "valid until replaced" in entries["f07"]["notes"].lower()
    assert all(item["verification"]["status"] == "UNVERIFIED" for item in entries.values())


def test_retrieval_preserves_unknown_page_provenance_for_unpaginated_sources(tmp_path):
    from app.local_knowledge import extract_document

    document = tmp_path / "unpaginated.md"
    document.write_text("A synthetic unpaginated document.", encoding="utf-8")
    pages = extract_document(document)
    assert pages == [("A synthetic unpaginated document.", None)]
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f02")
    schema = item["runtime_contract"]["operations"][0]["output_schema"]
    passage, page = pages[0]
    hit = {
        "citation": "[1]",
        "document_id": hashlib.sha256(document.name.encode()).hexdigest(),
        "source": document.name,
        "page": page,
        "document_version": 1,
        "passage": passage,
        "sha256": hashlib.sha256(passage.encode()).hexdigest(),
        "similarity": 0.9,
        "content_is_authority": False,
        "instructions_may_execute": False,
    }
    result = {
        "status": "RETRIEVED",
        "results": [hit],
        "embedding_model": "synthetic-MiniLM-fixture",
        "diagnostics": {"index_chunks": 1, "eligible_chunks": 1, "metric": "normalized inner product"},
    }
    _assert_declared_shape(result, schema)
    for invalid_page in ("unknown", False, 0):
        broken = deepcopy(result)
        broken["results"][0]["page"] = invalid_page
        with pytest.raises(AssertionError):
            _assert_declared_shape(broken, schema)
    missing = deepcopy(result)
    missing["results"][0].pop("page")
    with pytest.raises(AssertionError):
        _assert_declared_shape(missing, schema)


def test_direct_backend_and_collective_gateway_errors_use_explicit_closed_shapes(contract_client):
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f04")
    schema = item["runtime_contract"]["error_response_schema"]
    backend = contract_client.post(
        "/api/collective/v1/fabrics/f04/execute",
        json={"operation": "distance_km", "parameters": {"a": [91, 0], "b": [0, 1]}},
    )
    assert backend.status_code == 422
    _assert_declared_shape(backend.json(), schema)
    # Observed stage gateway shape; message text is a fixture, not source content.
    gateway = {
        "protocol": "orqevia.collective.v1",
        "error": {"code": "COLLECTIVE_REQUEST_FAILED", "message": "Controlled upstream failure.", "retryable": False},
        "correlation_id": str(uuid.uuid4()),
    }
    _assert_declared_shape(gateway, schema)
    for field in gateway:
        incomplete = deepcopy(gateway)
        incomplete.pop(field)
        with pytest.raises(AssertionError):
            _assert_declared_shape(incomplete, schema)
    for field in gateway["error"]:
        incomplete = deepcopy(gateway)
        incomplete["error"].pop(field)
        with pytest.raises(AssertionError):
            _assert_declared_shape(incomplete, schema)
    for changed in (
        {**gateway, "token": "fixture-never-a-real-credential"},
        {**gateway, "correlation_id": "not-a-uuid"},
        {**gateway, "error": {**gateway["error"], "retryable": True}},
        {**gateway, "error": {**gateway["error"], "message": 1}},
    ):
        with pytest.raises(AssertionError):
            _assert_declared_shape(changed, schema)


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 422, 426, 429, 500, 503])
def test_actual_early_interface_error_shapes_are_declared(status):
    from app.interface_server import error_response

    actual = json.loads(error_response(status).body)
    item = next(item for item in load_fabric_registry()["fabrics"] if item["id"] == "f04")
    schema = item["runtime_contract"]["error_response_schema"]
    _assert_declared_shape(actual, schema)
    incomplete = deepcopy(actual)
    incomplete["error"].pop("retryable")
    with pytest.raises(AssertionError):
        _assert_declared_shape(incomplete, schema)
