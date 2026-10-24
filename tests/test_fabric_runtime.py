"""Actual operation, journal and scope tests; not live production evidence."""

import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import fabric_runtime as runtime
from app.collective_api import router
from app.collective_intelligence import CollectivePrincipal

OWNER = "runtime-test-owner"
TOKEN = "runtime-test-authority-token-20261024"


def principal(tenant="test", owner="owner-a"):
    return CollectivePrincipal(tenant, owner, "test-actor", roles=frozenset({"OWNER"}))


def run(tmp_path, fabric="f04", operation="distance_km", parameters=None, *, identity=None, execution_id=None):
    return runtime.execute_fabric(
        fabric,
        operation,
        parameters if parameters is not None else {"a": [0, 0], "b": [0, 1]},
        principal=identity or principal(),
        data_root=tmp_path,
        execution_id=execution_id or str(uuid.uuid4()),
    )


def test_real_distance_and_hash_readback(tmp_path):
    receipt = run(tmp_path)
    assert receipt["status"] == "COMPLETED"
    assert receipt["result"]["distance_km"] == pytest.approx(111.195, abs=0.001)
    assert runtime.read_execution(tmp_path, receipt["execution_id"], principal()) == receipt
    assert (
        receipt["result_sha256"]
        == hashlib.sha256(json.dumps(receipt["result"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    checked = run(tmp_path, "f12", "verify_execution_integrity", {"execution_id": receipt["execution_id"]})["result"]
    assert checked["integrity_verified"] is True and checked["correctness_verified"] is False


@pytest.mark.parametrize(
    "parameters",
    [
        {"a": [0, 0], "b": [91, 0]},
        {"a": [0, 0], "b": [0, 1], "role": "SYSTEM"},
        {"a": [0, True], "b": [0, 1]},
        {"a": [0, float("nan")], "b": [0, 1]},
    ],
)
def test_invalid_inputs_cannot_pass(tmp_path, parameters):
    with pytest.raises(ValueError):
        run(tmp_path, parameters=parameters)


def test_unknown_operation_and_fabric_do_not_execute(tmp_path):
    with pytest.raises(ValueError):
        run(tmp_path, operation="shell")
    with pytest.raises(runtime.FabricUnavailable):
        run(tmp_path, fabric="f37")


def test_extremely_large_integer_is_validation_error_not_overflow():
    with pytest.raises(ValueError):
        runtime._validate(10**1000, {"type": "number", "minimum": -1e12, "maximum": 1e12})


def test_replay_is_once_and_cannot_rebind(tmp_path):
    identifier = str(uuid.uuid4())
    first = run(tmp_path, execution_id=identifier)
    assert run(tmp_path, execution_id=identifier) == first
    with pytest.raises(runtime.FabricConflict):
        run(tmp_path, execution_id=identifier, parameters={"a": [1, 0], "b": [1, 1]})
    with pytest.raises(runtime.FabricConflict):
        run(tmp_path, execution_id=identifier, identity=principal(owner="other"))
    with pytest.raises(KeyError):
        runtime.read_execution(tmp_path, identifier, principal(tenant="other"))


def test_concurrent_replay_never_duplicates_work(tmp_path):
    identifier = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: run(tmp_path, execution_id=identifier), range(8)))
    assert all(record["execution_id"] == identifier for record in records)
    with sqlite3.connect(tmp_path / "fabric-runtime/executions.db") as db:
        assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 1


def test_integrity_tamper_is_rejected(tmp_path):
    record = run(tmp_path)
    with sqlite3.connect(tmp_path / "fabric-runtime/executions.db") as db:
        db.execute("UPDATE executions SET result_json='{}' WHERE execution_id=?", (record["execution_id"],))
    with pytest.raises(runtime.FabricUnavailable, match="integrity"):
        runtime.read_execution(tmp_path, record["execution_id"], principal())


def test_owner_and_tenant_memory_namespaces(tmp_path):
    run(
        tmp_path,
        "f14",
        "store_context",
        {"key": "canary", "value": {"note": "cobaltcanary"}, "source": "test document"},
    )
    same = run(tmp_path, "f14", "search_context", {"query": "cobaltcanary"})["result"]["records"]
    assert len(same) == 1 and same[0]["source_authority"] == "MODEL"
    for identity in (principal(owner="other"), principal(tenant="other")):
        assert (
            run(tmp_path, "f14", "search_context", {"query": "cobaltcanary"}, identity=identity)["result"]["records"]
            == []
        )


def test_interruption_and_restart_never_mark_completion(tmp_path):
    class Interrupted(BaseException):
        pass

    identifier = str(uuid.uuid4())
    with patch.object(runtime, "_builtin", side_effect=Interrupted):
        with pytest.raises(Interrupted):
            run(tmp_path, execution_id=identifier)
    assert runtime.read_execution(tmp_path, identifier, principal())["status"] == "FAILED"
    with sqlite3.connect(tmp_path / "fabric-runtime/executions.db") as db:
        db.execute("UPDATE executions SET status='RUNNING' WHERE execution_id=?", (identifier,))
    assert runtime.recover_interrupted(tmp_path) == 1
    assert runtime.read_execution(tmp_path, identifier, principal())["status"] == "INTERRUPTED"


def test_tool_allowlist_arguments_and_governance(tmp_path):
    result = run(tmp_path, "f09", "invoke_tool", {"tool": "geo.distance", "arguments": {"a": [0, 0], "b": [0, 1]}})[
        "result"
    ]
    assert result["result"]["distance_km"] > 111 and result["credential_disclosed"] is False
    for tool in ("shell", "../secret", "mcp.unapproved"):
        with pytest.raises(ValueError):
            run(tmp_path, "f09", "invoke_tool", {"tool": tool, "arguments": {}})
    denied = run(tmp_path, "f24", "evaluate_tool_permission", {"tool": "geo.distance", "consequential": True})["result"]
    assert denied["allowed"] is False


def test_actual_deployed_code_and_node_measurements(tmp_path):
    code = run(tmp_path, "f10", "inspect_deployed_module", {"module": "fabric_runtime"})["result"]
    assert "execute_fabric" in code["functions"] and code["bytes"] > 100
    node = run(tmp_path, "f33", "edge_telemetry", {})["result"]
    assert node["resident_bytes"] > 0 and node["physical_actions_enabled"] is False
    with pytest.raises(ValueError):
        run(tmp_path, "f10", "inspect_deployed_module", {"module": "../../secrets"})


def test_all_thirty_six_have_executable_scoped_contracts():
    contracts = runtime.executable_contracts()
    assert set(contracts) == {f"f{number:02d}" for number in range(1, 37)}
    assert all(contract["operations"] and contract["limitations"] for contract in contracts.values())


@pytest.fixture
def api(tmp_path, monkeypatch):
    for name, value in {
        "ORQEVIA_SPINE_TOKEN": TOKEN,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": OWNER,
        "ORQEVIA_COLLECTIVE_ENABLED": "1",
        "ORQEVIA_OPEN_ACCESS": "1",
        "ORQEVIA_DATA_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_http_owner_auth_and_real_execution(api):
    url = "/api/collective/v1/fabrics/f04/execute"
    body = {"operation": "distance_km", "parameters": {"a": [0, 0], "b": [0, 1]}}
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "runtime-test",
    }
    assert api.post(url, json=body).status_code == 401
    assert api.post(url, headers={**headers, "X-ORQEVIA-Owner": "other"}, json=body).status_code == 403
    response = api.post(url, headers=headers, json=body)
    assert response.status_code == 200
    receipt = response.json()["data"]
    assert receipt["status"] == "COMPLETED" and receipt["result"]["distance_km"] > 111
    assert (
        api.get("/api/collective/v1/fabrics/executions/" + receipt["execution_id"], headers=headers).json()["data"]
        == receipt
    )
    assert api.post(url, headers=headers, json={**body, "role": "OWNER"}).status_code == 422
    assert api.post(url, headers=headers, json={**body, "operation": "shell"}).status_code == 422
    assert (
        api.post(
            url, headers=headers, json={"operation": "distance_km", "parameters": {"a": [10**1000, 0], "b": [0, 1]}}
        ).status_code
        == 422
    )
    assert (
        api.get("/api/collective/v1/fabrics/registry", headers=headers).json()["data"]["summary"]["state_counts"][
            "VERIFIED"
        ]
        == 0
    )


def test_compact_discovery_preserves_real_scopes_without_full_schemas(api):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "discovery-test",
    }
    full = api.get("/api/collective/v1/fabrics/registry", headers=headers)
    compact = api.get("/api/collective/v1/fabrics/registry?summary=1", headers=headers)
    assert full.status_code == compact.status_code == 200
    data = compact.json()["data"]
    assert data["fabric_count"] == len(data["fabrics"]) == 36
    assert data["discovery_mode"] == "COMPACT_SUPPORTED_OPERATIONS"
    assert len(compact.content) < len(full.content) / 3
    assert all(
        item["operations"] and item["limitations"] and item["verification"]["status"] == "UNVERIFIED"
        for item in data["fabrics"]
    )
    assert "input_schema" not in json.dumps(data) and "output_schema" not in json.dumps(data)
    selected = api.get(data["fabrics"][3]["contract_url"], headers=headers).json()["data"]
    assert selected["fabric_count"] == 36 and selected["selected_fabric_count"] == 1
    assert selected["fabrics"][0]["id"] == "f04" and selected["fabrics"][0]["input_schema"]
    assert api.get("/api/collective/v1/fabrics/registry?summary=1").status_code == 401


@pytest.mark.parametrize(
    "query,status",
    [("summary=all", 422), ("summary=1&summary=0", 422), ("fabric_id=f37", 404), ("fabric_id=f04&role=OWNER", 422)],
)
def test_discovery_query_is_bounded(api, query, status):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "discovery-test",
    }
    assert api.get("/api/collective/v1/fabrics/registry?" + query, headers=headers).status_code == status


def test_research_extension_preserves_observations_and_rejects_http_before_network(api):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "research-test",
    }
    registry = api.get("/api/collective/v1/fabrics/registry?fabric_id=f19", headers=headers).json()["data"]
    fabric = registry["fabrics"][0]
    assert fabric["version"] == "1.1.0"
    assert {op["operation"] for op in fabric["runtime_contract"]["operations"]} == {
        "retrieve_observations",
        "fetch_primary_source",
    }
    operation = next(op for op in fabric["runtime_contract"]["operations"] if op["operation"] == "fetch_primary_source")
    # The in-repo validator uses fullmatch, so the declared HTTPS pattern must
    # accept the complete URL, including supported uppercase schemes.
    for url in ("https://docs.docker.com/reference/compose-file/merge.md", "HTTPS://DOCS.DOCKER.COM/"):
        runtime._validate({"url": url}, operation["input_schema"])
    with patch("app.fabric_research.httpx.AsyncClient") as client:
        response = api.post(
            "/api/collective/v1/fabrics/f19/execute",
            headers=headers,
            json={"operation": "fetch_primary_source", "parameters": {"url": "http://docs.docker.com/"}},
        )
        assert response.status_code == 422
    client.assert_not_called()


@pytest.mark.parametrize("candidate", ["-" * 36, "a" * 36, "not-a-uuid"])
def test_trace_metadata_is_a_canonical_uuid(api, candidate):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "trace-test",
        "X-Request-ID": candidate,
    }
    response = api.get("/api/collective/v1/fabrics/registry?summary=1", headers=headers)
    identifier = response.json()["correlation_id"]
    assert str(uuid.UUID(identifier)) == identifier and identifier != candidate
    assert response.headers["X-Request-ID"] == identifier


def test_cross_contract_version_post_conflicts_without_changing_history(tmp_path):
    first = run(tmp_path)
    with sqlite3.connect(tmp_path / "fabric-runtime/executions.db") as db:
        db.execute("UPDATE executions SET version='0.9.0' WHERE execution_id=?", (first["execution_id"],))
    historical = runtime.read_execution(tmp_path, first["execution_id"], principal())
    with patch.object(runtime, "_builtin", side_effect=AssertionError("old execution must never run again")):
        with pytest.raises(runtime.FabricConflict):
            run(tmp_path, execution_id=first["execution_id"])
    assert runtime.read_execution(tmp_path, first["execution_id"], principal()) == historical
    assert historical["version"] == "0.9.0" and historical["result_sha256"] == first["result_sha256"]
    assert historical["result"] == first["result"]


def test_cross_version_post_is_http409_while_historical_get_stays_available(api):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "version-test",
    }
    body = {"operation": "distance_km", "parameters": {"a": [0, 0], "b": [0, 1]}, "execution_id": str(uuid.uuid4())}
    first = api.post("/api/collective/v1/fabrics/f04/execute", headers=headers, json=body)
    assert first.status_code == 200
    from pathlib import Path
    import os

    with sqlite3.connect(Path(os.environ["ORQEVIA_DATA_DIR"]) / "fabric-runtime/executions.db") as db:
        db.execute("UPDATE executions SET version='0.9.0' WHERE execution_id=?", (body["execution_id"],))
    before = api.get("/api/collective/v1/fabrics/executions/" + body["execution_id"], headers=headers)
    assert before.status_code == 200 and before.json()["data"]["version"] == "0.9.0"
    with patch.object(runtime, "_builtin", side_effect=AssertionError("historical record must not rerun")):
        assert api.post("/api/collective/v1/fabrics/f04/execute", headers=headers, json=body).status_code == 409
    after = api.get("/api/collective/v1/fabrics/executions/" + body["execution_id"], headers=headers)
    assert after.json()["data"] == before.json()["data"]


def test_malformed_upstream_is_failed_and_never_persisted_and_slot_is_released(tmp_path, monkeypatch):
    import threading

    marker = "synthetic-private-upstream-diagnostic"
    execution_id = str(uuid.uuid4())
    monkeypatch.setattr(runtime, "SLOTS", threading.BoundedSemaphore(1))
    with patch.object(runtime, "_service", return_value={"unexpected": marker}):
        with pytest.raises(runtime.OutputContractViolation) as error:
            run(tmp_path, "f02", "retrieve", {"question": "synthetic fixture"}, execution_id=execution_id)
    assert marker not in str(error.value)
    stored = runtime.read_execution(tmp_path, execution_id, principal())
    assert stored["status"] == "FAILED" and stored["result"] is None and stored["result_sha256"] is None
    assert stored["error_code"] == "OutputContractViolation"
    assert marker not in json.dumps(stored)
    assert run(tmp_path)["status"] == "COMPLETED"


def test_output_contract_failure_http_error_does_not_echo_upstream_payload(api):
    marker = "synthetic-private-provider-error-body"
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "output-test",
    }
    body = {"operation": "retrieve", "parameters": {"question": "synthetic fixture"}, "execution_id": str(uuid.uuid4())}
    with patch.object(runtime, "_service", return_value={"error": marker}):
        response = api.post("/api/collective/v1/fabrics/f02/execute", headers=headers, json=body)
    assert response.status_code == 503 and marker not in response.text
    record = api.get("/api/collective/v1/fabrics/executions/" + body["execution_id"], headers=headers).json()["data"]
    assert record["status"] == "FAILED" and record["result"] is None and marker not in json.dumps(record)


@pytest.mark.parametrize(
    "value,schema",
    [
        (
            {"flag": True},
            {
                "type": "object",
                "required": ["flag"],
                "properties": {"flag": {"const": False}},
                "additionalProperties": False,
            },
        ),
        (
            {"flag": 0},
            {
                "type": "object",
                "required": ["flag"],
                "properties": {"flag": {"const": False}},
                "additionalProperties": False,
            },
        ),
        ({"value": True}, {"type": "object", "properties": {"value": {"type": "integer"}}}),
        ({"extra": 1}, {"type": "object", "additionalProperties": False}),
        ({}, {"type": "object", "required": ["value"]}),
        (1, {"oneOf": [{"type": "number"}, {"type": "integer"}]}),
        ("none", {"anyOf": [{"type": "null"}, {"type": "integer"}]}),
        (0, {"type": "number", "exclusiveMinimum": 0}),
        (3, {"type": "number", "maximum": 2}),
        ("a", {"type": "string", "minLength": 2}),
        ("abc", {"type": "string", "pattern": "^[0-9]+$"}),
        ("not-a-uuid", {"type": "string", "format": "uuid"}),
        ("2026-10-24", {"type": "string", "format": "date-time"}),
        ("https://[broken", {"type": "string", "format": "uri"}),
        ("https://example.org/%ZZ", {"type": "string", "format": "uri"}),
        ("https://example.org/<bad>", {"type": "string", "format": "uri"}),
        ("not base64!", {"type": "string", "contentEncoding": "base64"}),
        ([1, 2], {"type": "array", "maxItems": 1}),
        ({"x": "bad"}, {"type": "object", "additionalProperties": {"type": "integer"}}),
        ({"abc": 1}, {"type": "object", "propertyNames": {"pattern": "^[0-9]+$"}}),
        (
            {"count": "bad"},
            {"type": "object", "patternProperties": {"^count$": {"type": "integer"}}, "additionalProperties": False},
        ),
    ],
)
def test_output_guard_rejects_declared_constraint_mismatches(value, schema):
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output(value, schema)


@pytest.mark.parametrize(
    "value,schema",
    [
        (None, {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]}),
        (1, {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]}),
        (1.0, {"type": "integer"}),
        (False, {"const": False}),
        ({"x": 1}, {"type": "object", "additionalProperties": {"type": "integer"}}),
        ("2026-10-24T03:00:00+00:00", {"type": "string", "format": "date-time"}),
        ("https://docs.docker.com/reference/", {"type": "string", "format": "uri"}),
        ("YWJj", {"type": "string", "contentEncoding": "base64"}),
    ],
)
def test_output_guard_accepts_supported_assertion_variants(value, schema):
    runtime._validate_output(value, schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "unrecognizedAssertion": True},
        {"format": "unrecognized-format"},
        {"anyOf": [{"type": "object"}, {"unknownAssertion": True}]},
        {"pattern": "[broken"},
    ],
)
def test_output_guard_never_silently_skips_unsupported_schema_assertions(schema):
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output({}, schema)


def test_output_json_finiteness_size_and_unicode_precede_recursive_guard(monkeypatch):
    monkeypatch.setattr(runtime, "MAX_RESULT", 40)
    with patch.object(runtime, "_output_value", side_effect=AssertionError("invalid JSON reached recursive guard")):
        for invalid in ({"value": float("nan")}, {"value": float("inf")}, {"value": "x" * 100}, {"value": "\ud800"}):
            with pytest.raises(runtime.OutputContractViolation):
                runtime._validate_output(invalid, {"type": "object"})


def test_output_guard_data_budget_and_schema_depth_are_bounded(monkeypatch):
    monkeypatch.setattr(runtime, "OUTPUT_MAX_VISITS", 3)
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output([1, 2, 3, 4], {"type": "array", "items": {"type": "integer"}})
    deep = {"type": "integer"}
    for _ in range(66):
        deep = {"type": "array", "items": deep}
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output([], deep)


@pytest.mark.parametrize("value", [{"unconstrained": (1, 2)}, {"unconstrained": {1: "converted key"}}])
def test_schema_free_output_fields_still_require_json_types(value):
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output(value, {"type": "object"})


def test_schema_free_output_fields_still_have_a_depth_bound():
    value = {}
    for _ in range(runtime.OUTPUT_MAX_DEPTH + 1):
        value = {"unconstrained": value}
    with pytest.raises(runtime.OutputContractViolation):
        runtime._validate_output(value, {"type": "object"})


@pytest.mark.parametrize("page", [None, 1])
def test_retrieval_nullable_page_survives_the_runtime_output_guard(tmp_path, page):
    passage = "synthetic unpaginated fixture"
    result = {
        "status": "RETRIEVED",
        "results": [
            {
                "citation": "[1]",
                "document_id": hashlib.sha256(b"fixture.md").hexdigest(),
                "source": "fixture.md",
                "page": page,
                "document_version": 1,
                "passage": passage,
                "sha256": hashlib.sha256(passage.encode()).hexdigest(),
                "similarity": 0.9,
                "content_is_authority": False,
                "instructions_may_execute": False,
            }
        ],
        "embedding_model": "synthetic-MiniLM-fixture",
        "diagnostics": {"index_chunks": 1, "eligible_chunks": 1, "metric": "normalized inner product"},
    }
    with patch.object(runtime, "_service", return_value=result):
        record = run(tmp_path, "f02", "retrieve", {"question": "synthetic fixture"})
    assert record["status"] == "COMPLETED" and record["result"]["results"][0]["page"] == page


@pytest.mark.parametrize("result", [["malformed upstream"], {"flag": float("nan")}])
def test_invalid_upstream_types_are_failed_without_result_data(tmp_path, result):
    execution_id = str(uuid.uuid4())
    with patch.object(runtime, "_service", return_value=result):
        with pytest.raises(runtime.OutputContractViolation):
            run(tmp_path, "f02", "retrieve", {"question": "synthetic fixture"}, execution_id=execution_id)
    stored = runtime.read_execution(tmp_path, execution_id, principal())
    assert stored["status"] == "FAILED" and stored["result"] is None and stored["result_sha256"] is None


def test_output_guard_supports_the_entire_current_operation_vocabulary():
    seen = set()

    def inventory(schema):
        if type(schema) is bool:
            return
        seen.update(schema)
        for keyword in ("properties", "patternProperties"):
            for child in schema.get(keyword, {}).values():
                inventory(child)
        for keyword in ("items", "additionalProperties", "propertyNames"):
            if keyword in schema:
                inventory(schema[keyword])
        for keyword in ("oneOf", "anyOf"):
            for child in schema.get(keyword, []):
                inventory(child)

    for contract in runtime.executable_contracts().values():
        for operation in contract["operations"]:
            inventory(operation["output_schema"])
            runtime._output_schema_supported(operation["output_schema"], [10000])
    assert seen <= runtime.OUTPUT_SCHEMA_KEYWORDS
    assert {"oneOf", "anyOf", "const", "patternProperties", "contentEncoding", "propertyNames"} <= seen
