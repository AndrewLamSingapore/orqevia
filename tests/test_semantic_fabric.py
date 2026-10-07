"""Actual formal-engine tests; no model, runtime/store, network or production calls.

An off-host semantic acceptance job must install requirements-semantic.txt and
execute this complete file with zero dependency skips. A host without the optional
engines can run the small fail-closed tests but has not passed formal acceptance.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app import semantic_fabric as sf
from app.agent_registry import load_agent_registry

REVISION = "b" * 40
TASK = "01234567-89ab-4cde-8f01-23456789abcd"
RESULT = "objective:" + TASK + ":r0"
DIGEST = hashlib.sha256(b"public synthetic result").hexdigest()
PERMANENT_IDS = {"a01", "a02", "a04", "a05", "a06", "a07", "a09", "a10", "a12", "a13",
    "a14", "a15", "a16", "a17", "a18", "a19", "a20", "a21", "a26", "a28", "a29"}


def snapshot():
    agents = [{"id": a["id"], "name": a["name"], "role": a["role"], "version": a["version"],
        "capabilities": list(a["capability_requirements"])} for a in load_agent_registry()["agents"]]
    return {"source_revision": REVISION, "agents": agents, "results": [{"id": RESULT,
        "task_id": TASK, "agent_id": "a20", "source_revision": REVISION, "environment": "ISOLATED",
        "integrity": "VALID", "currentness": "CURRENT", "verification": "UNVERIFIED",
        "evidence_ref": RESULT, "result_sha256": DIGEST}],
        "metrics": [{"metric_id": "public-poll", "agent_id": "a20", "result_ids": [RESULT],
            "name": "poll_elapsed_seconds", "value": 1.5, "unit": "seconds"}]}


@pytest.fixture(autouse=True)
def isolated_cache():
    sf._CACHE.clear()
    yield
    sf._CACHE.clear()


@pytest.fixture
def formal():
    try:
        return sf._engines()
    except sf.SemanticError as error:
        if str(error) == "SEMANTIC_ENGINES_UNAVAILABLE":
            pytest.skip("OPTIONAL_FORMAL_ENGINES_ABSENT: not formal acceptance")
        raise


def graph_bundle(data):
    owned = sf._owned_registry(data)
    return sf._new_bundle(data, owned, sf._resource_bytes("ontology.ttl"),
        sf._resource_bytes("shapes.ttl"), "f" * 64)


def shapes_for(formal, data):
    rdf = formal[0]
    shapes = rdf.Graph().parse(data=sf._resource_bytes("shapes.ttl").decode(), format="turtle")
    sf._bind_shapes(shapes, rdf, sf._owned_registry(data), data["source_revision"])
    return shapes


def test_optional_engines_fail_closed_without_runtime_or_secret_import(monkeypatch):
    actual = sf.importlib.import_module

    def missing(name):
        if name in {"rdflib", "pyshacl", "owlrl"}:
            raise ModuleNotFoundError("not installed")
        return actual(name)

    monkeypatch.setattr(sf.importlib, "import_module", missing)
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_ENGINES_UNAVAILABLE$"):
        sf.build_semantics(snapshot())
    assert not sf._CACHE


@pytest.mark.parametrize("query", ["SELECT * WHERE {?s ?p ?o}", "SERVICE", "INSERT DATA", "DESCRIBE", "DELETE", ""])
def test_arbitrary_sparql_rejected_before_engine(query):
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_QUERY_NOT_ALLOWED$"):
        sf.query_semantics(snapshot(), query, "a20")


@pytest.mark.parametrize("subject", ["https://attacker.invalid/x", "a20 } SERVICE", "<urn:a20>", {"id": "a20"}, ""])
def test_remote_or_injected_subject_rejected_before_engine(subject):
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_QUERY_SUBJECT_INVALID$"):
        sf.query_semantics(snapshot(), "why", subject)


@pytest.mark.parametrize("field", ["rdf", "sparql", "owl_imports", "secret", "raw_prompt", "hidden_master_database"])
def test_untrusted_graph_and_payload_fields_rejected_before_engine(field):
    data = snapshot(); data[field] = "not parsed or returned"
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_SNAPSHOT_FIELDS_INVALID$"):
        sf.build_semantics(data)


@pytest.mark.parametrize("value", [None, True, 42, "short", "C" * 40])
def test_source_revision_is_mandatory_and_canonical(value):
    data = snapshot(); data["source_revision"] = value
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_SOURCE_REVISION_REQUIRED$"):
        sf.build_semantics(data)


@pytest.mark.parametrize("change", ["missing", "duplicate", "phantom", "prime", "alias", "role", "version", "capability", "l7"])
def test_exact_domain_registry_and_boundaries_are_not_manufactured(change):
    data = snapshot(); first = data["agents"][0]
    if change == "missing": data["agents"].pop()
    elif change == "duplicate": data["agents"][-1] = deepcopy(first)
    elif change == "phantom": first["id"] = "a22"
    elif change == "prime": first["id"] = "prime"
    elif change == "alias": first["id"] = "A01"
    elif change == "role": first["role"] = "different role"
    elif change == "version": first["version"] = "fake-version"
    elif change == "capability": first["capabilities"] = ["responsibility.a22"]
    elif change == "l7": first["l7_status"] = "L7"
    with pytest.raises(sf.SemanticError):
        sf.build_semantics(data)


def test_resource_gate_and_input_size_fail_closed():
    assert sf._GATE.acquire(blocking=False)
    try:
        with pytest.raises(sf.SemanticError, match="^SEMANTIC_RESOURCE_BUSY$"):
            sf.build_semantics(snapshot())
    finally:
        sf._GATE.release()
    data = snapshot(); data["results"] *= sf.MAX_RESULTS + 1
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_ENTITY_BUDGET_EXCEEDED$"):
        sf.build_semantics(data)
    data = snapshot(); data["results"][0]["evidence_ref"] = "x" * sf.MAX_INPUT_BYTES
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_INPUT_BUDGET_EXCEEDED$"):
        sf.build_semantics(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_data_is_not_a_valid_measurement(value):
    data = snapshot(); data["metrics"][0]["value"] = value
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_INPUT_NOT_CANONICAL$"):
        sf.build_semantics(data)


def test_actual_rdf_shacl_owl_and_read_only_template_queries(formal):
    data = snapshot()
    result = sf.build_semantics(data)
    assert result["status"] == "READY" and result["permanent_agent_count"] == 21
    assert result["engines"] == {"rdflib": "7.6.0", "pyshacl": "0.40.1", "owlrl": "7.6.2"}
    assert result["rdf"] == "PASS" and result["shacl"] == "PASS_ACCEPTED_PROJECTION"
    assert result["reasoning"] == "PASS_FIXED_OWL2_RL_SUBSET" and result["inferred_triples"] > 0
    overview = sf.query_semantics(data, "overview")
    assert {row["id"] for row in overview["agents"]} == PERMANENT_IDS
    assert len(overview["agents"]) == 21 and "prime" not in {row["id"] for row in overview["agents"]}
    why = sf.query_semantics(data, "why", "a20")
    assert why["result_evidence"][0]["evidence_ref"] == RESULT
    proof = sf.query_semantics(data, "prove_it", RESULT)
    assert proof["rows"][0]["digest"] == DIGEST and proof["rows"][0]["agent_id"] == "a20"
    assert sf.query_semantics(data, "depends_on", RESULT)["rows"] == [{"metric_id": "public-poll", "agent_id": "a20"}]
    assert sf.query_semantics(data, "capability_agents", "responsibility.a20")["routing_candidates"][0]["id"] == "a20"
    assert not proof["l7_awarded"] and not why["verified_capabilities"] and not why["routing_promoted"]


def test_owl_does_not_infer_metrics_as_results_or_prime_as_permanent(formal):
    bundle = graph_bundle(snapshot()); rdf = formal[0]; p = rdf.Namespace(sf.NS)
    assert (sf._uri(rdf, "agent", "a20"), rdf.RDF.type, p.Agent) in bundle.graph
    assert (sf._uri(rdf, "metric", "public-poll"), rdf.RDF.type, p.Result) not in bundle.graph
    assert (sf._uri(rdf, "system", "prime"), rdf.RDF.type, p.PermanentPrimeAgent) not in bundle.graph
    assert not list(bundle.graph.triples((None, p.hasVerifiedCapability, None)))
    assert not list(bundle.graph.triples((None, p.hasL7Certification, None)))


@pytest.mark.parametrize("field", ["agent_id", "task_id", "source_revision", "environment", "integrity", "currentness", "verification", "evidence_ref", "result_sha256"])
def test_missing_shape_contract_is_quarantined_and_dependencies_removed(formal, field):
    data = snapshot(); del data["results"][0][field]
    result = sf.build_semantics(data)
    assert result["status"] == "DEGRADED" and result["accepted_results"] == 0
    assert result["accepted_metrics"] == 0
    assert any(q["kind"] == "result" for q in result["quarantined"])
    assert sf.query_semantics(data, "prove_it", RESULT)["status"] == "UNKNOWN"


@pytest.mark.parametrize("field,value", [("agent_id", "a22"), ("agent_id", "prime"), ("agent_id", {"bad": 1}),
    ("source_revision", "c" * 40), ("environment", "UNKNOWN"), ("environment", False),
    ("integrity", "INVALID"), ("currentness", "STALE"), ("currentness", "HISTORICAL"),
    ("verification", "FAILED"), ("verification", "CONTRADICTED"), ("evidence_ref", "objective:bad:r0"),
    ("result_sha256", "not-a-digest"), ("task_id", "wrong-task"), ("raw_prompt", "do not publish")])
def test_wrong_version_environment_integrity_agent_or_payload_cannot_be_current_evidence(formal, field, value):
    data = snapshot(); data["results"][0][field] = value
    result = sf.build_semantics(data)
    assert result["status"] == "DEGRADED" and result["accepted_results"] == 0
    assert result["accepted_metrics"] == 0 and "do not publish" not in json.dumps(result)


@pytest.mark.parametrize("environment", ["ISOLATED", "CI", "RELEASE", "GOLDEN", "PRODUCTION"])
def test_environment_and_domain_verification_never_upgrade_production_or_l7(formal, environment):
    data = snapshot(); data["results"][0].update(environment=environment, verification="VERIFIED")
    result = sf.build_semantics(data)
    proof = sf.query_semantics(data, "prove_it", RESULT)
    assert proof["rows"][0]["environment"] == environment
    assert proof["rows"][0]["verification"] == "VERIFIED"
    assert result["production_acceptance"] == "UNVERIFIED" and result["l7_awarded"] is False
    assert sf.query_semantics(data, "why", "a20")["verified_capabilities"] == []


@pytest.mark.parametrize("field,value", [("agent_id", "a19"), ("agent_id", {}), ("result_ids", ["unknown"]),
    ("result_ids", [RESULT, RESULT]), ("result_ids", []), ("name", {}), ("unit", []), ("value", True),
    ("value", "1.5"), ("scope", "invented-scope"), ("l7_status", "L7")])
def test_metrics_require_bound_provenance_and_typed_measurement(formal, field, value):
    data = snapshot(); data["metrics"][0][field] = value
    result = sf.build_semantics(data)
    assert result["accepted_results"] == 1 and result["accepted_metrics"] == 0 and result["status"] == "DEGRADED"
    assert sf.query_semantics(data, "depends_on", RESULT)["rows"] == []


@pytest.mark.parametrize("kind", ["results", "metrics"])
def test_contradictory_duplicate_identity_is_not_last_writer_wins(formal, kind):
    data = snapshot(); data[kind].append(deepcopy(data[kind][0]))
    data[kind][-1]["agent_id"] = "a19"
    with pytest.raises(sf.SemanticError, match="SEMANTIC_DUPLICATE_"):
        sf.build_semantics(data)


def test_dynamic_shacl_identity_and_revision_constraints_are_actual_engine_checks(formal):
    data = snapshot(); bundle = graph_bundle(data); rdf = formal[0]; p = rdf.Namespace(sf.NS)
    shapes = shapes_for(formal, data); graph = bundle.graph
    result = sf._uri(rdf, "result", RESULT)
    graph.set((result, p.sourceRevision, rdf.Literal("c" * 40)))
    assert result in sf._shape_failures(graph, shapes, formal)
    graph.set((result, p.sourceRevision, rdf.Literal(REVISION)))
    phantom = sf._uri(rdf, "agent", "a22")
    for predicate, value in ((rdf.RDF.type, p.PermanentPrimeAgent), (p.id, rdf.Literal("a22")),
        (p.name, rdf.Literal("phantom")), (p.role, rdf.Literal("fiction")), (p.version, rdf.Literal("1"))):
        graph.add((phantom, predicate, value))
    graph.set((result, p.producer, phantom))
    failures = sf._shape_failures(graph, shapes, formal)
    assert phantom in failures and result in failures


def test_actual_shacl_rejects_false_l7_and_verified_capability(formal):
    data = snapshot(); bundle = graph_bundle(data); rdf = formal[0]; p = rdf.Namespace(sf.NS)
    agent = sf._uri(rdf, "agent", "a20")
    for predicate in (p.hasL7Certification, p.hasVerifiedCapability):
        graph = rdf.Graph()
        for triple in bundle.graph: graph.add(triple)
        graph.add((agent, predicate, sf._uri(rdf, "capability", "responsibility.a20")))
        assert agent in sf._shape_failures(graph, shapes_for(formal, data), formal)


def test_cache_is_bounded_detached_and_invalidated_by_provenance(formal):
    data = snapshot(); first = sf.build_semantics(data)
    first["engines"]["rdflib"] = "tampered"
    assert sf.build_semantics(data)["engines"]["rdflib"] == "7.6.0"
    before = sf.build_semantics(data)["snapshot_sha256"]
    data["results"][0]["result_sha256"] = "e" * 64
    assert sf.build_semantics(data)["snapshot_sha256"] != before
    data["results"][0]["currentness"] = "STALE"
    assert sf.build_semantics(data)["accepted_results"] == 0
    assert len(sf._CACHE) == 2
    sf._CACHE.clear()
    rebuilt = sf.build_semantics(snapshot())
    assert rebuilt["accepted_results"] == 1 and rebuilt["snapshot_sha256"] == before


def test_engine_error_and_elapsed_rejection_are_sanitized_without_unsafe_cancellation(formal, monkeypatch):
    def engine_error(*args, **kwargs):
        raise ValueError("secret-like fixture text must not escape")

    monkeypatch.setattr(formal[1], "validate", engine_error)
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_SHACL_ENGINE_FAILED$"):
        sf.build_semantics(snapshot())
    monkeypatch.undo()
    data = snapshot(); sf.build_semantics(data)
    ticks = iter([0.0, sf.MAX_OPERATION_SECONDS + 1])
    monkeypatch.setattr(sf.time, "monotonic", lambda: next(ticks))
    with pytest.raises(sf.SemanticError, match="^SEMANTIC_ELAPSED_BUDGET_EXCEEDED$"):
        sf.build_semantics(data)


def test_resources_and_module_have_no_external_loader_or_hidden_universal_store():
    source = Path(sf.__file__).read_text(encoding="utf-8")
    assert "from .runtime" not in source and "MemoryStore(" not in source and "sqlite3" not in source
    assert "import requests" not in source and "httpx" not in source
    assert all("SERVICE" not in query and "UPDATE" not in query and "DESCRIBE" not in query for query in sf._QUERIES.values())
    ontology = sf._resource_bytes("ontology.ttl").decode()
    assert "owl:imports" not in ontology and "owl:equivalentClass" not in ontology and "owl:TransitiveProperty" not in ontology
    pins = Path(sf.__file__).resolve().parents[1].joinpath("requirements-semantic.txt").read_text()
    assert all(pin in pins for pin in ("rdflib==7.6.0", "pyshacl==0.40.1", "owlrl==7.6.2"))
