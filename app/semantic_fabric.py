"""Rebuildable, bounded read-only semantics over explicit domain projections.

Requires the optional real RDFLib/pySHACL/OWL-RL engines lazily. No imports of
runtime singletons, stores, models, secret mechanisms, or external RDF. The graph
does not grant authority, certify an agent, or verify a factual capability.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import importlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import threading
import time
from uuid import UUID

from .agent_registry import load_agent_registry

ONTOLOGY_VERSION = "0.1.0"
SCHEMA = "prime.semantic.fabric.v1"
NS = "urn:prime:semantic:"
MAX_INPUT_BYTES = 196_608
MAX_RESULTS = 48
MAX_METRICS = 48
MAX_TRIPLES = 4096
MAX_DERIVED_TRIPLES = 8192
MAX_QUERY_ROWS = 50
MAX_OPERATION_SECONDS = 3.0
_RESOURCES = Path(__file__).with_name("semantic")
_GATE = threading.BoundedSemaphore(1)
_CACHE: OrderedDict[str, "_Bundle"] = OrderedDict()
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ENVIRONMENTS = frozenset({"ISOLATED", "CI", "RELEASE", "GOLDEN", "PRODUCTION"})
_RESULT_FIELDS = frozenset({"id", "task_id", "agent_id", "source_revision", "environment",
    "integrity", "currentness", "verification", "evidence_ref", "result_sha256"})
_METRIC_FIELDS = frozenset({"metric_id", "agent_id", "result_ids", "name", "value", "unit"})
_METRIC_NAMES = frozenset({"observed_task_count", "verified_output_count", "failed_output_count",
    "latency_ms", "poll_elapsed_seconds", "catalog_estimated_cost_usd", "input_tokens",
    "output_tokens", "success_rate", "failure_rate", "timeout_rate", "recovery_rate"})
_UNITS = frozenset({"count", "ms", "seconds", "USD", "tokens", "ratio"})
QUERY_IDS = frozenset({"overview", "why", "prove_it", "depends_on", "capability_agents"})
_ENGINE_VERSIONS = {"rdflib": "7.6.0", "pyshacl": "0.40.1", "owlrl": "7.6.2"}
# Fixed SELECT templates only; callers never supply query text or an RDF parser input.
_QUERIES = {
    "agents": "SELECT ?id ?name ?role WHERE { ?a a p:PermanentPrimeAgent; p:id ?id; p:name ?name; p:role ?role } ORDER BY ?id LIMIT 22",
    "capabilities": "SELECT ?id WHERE { ?focus p:declaredCapability ?c . ?c p:id ?id } ORDER BY ?id LIMIT 30",
    "results": "SELECT ?id ?task_id ?evidence_ref ?environment ?verification ?digest WHERE { ?r a p:Result; p:producer ?focus; p:id ?id; p:task ?t; p:evidenceRef ?evidence_ref; p:environment ?environment; p:verification ?verification; p:resultDigest ?digest . ?t p:id ?task_id } ORDER BY ?id LIMIT 50",
    "proof": "SELECT ?id ?agent_id ?task_id ?evidence_ref ?environment ?verification ?digest WHERE { ?focus a p:Result; p:id ?id; p:producer ?a; p:task ?t; p:evidenceRef ?evidence_ref; p:environment ?environment; p:verification ?verification; p:resultDigest ?digest . ?a p:id ?agent_id . ?t p:id ?task_id } LIMIT 1",
    "dependencies": "SELECT ?metric_id ?agent_id WHERE { ?m a p:Metric; p:id ?metric_id; p:metricAgent ?a; p:derivedFrom ?focus . ?a p:id ?agent_id } ORDER BY ?metric_id LIMIT 50",
    "capability_agents": "SELECT ?id ?name ?role WHERE { ?a a p:PermanentPrimeAgent; p:declaredCapability ?focus; p:id ?id; p:name ?name; p:role ?role } ORDER BY ?id LIMIT 22",
}


class SemanticError(ValueError):
    """Only fixed public codes, never an input payload or engine traceback."""


def _require(value: bool, code: str) -> None:
    if value is not True:
        raise SemanticError(code)


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise SemanticError("SEMANTIC_INPUT_NOT_CANONICAL") from None
    _require(len(raw) <= MAX_INPUT_BYTES, "SEMANTIC_INPUT_BUDGET_EXCEEDED")
    return raw


def _engines():
    try:
        rdf = importlib.import_module("rdflib")
        shacl = importlib.import_module("pyshacl")
        owl = importlib.import_module("owlrl")
        sparql = importlib.import_module("rdflib.plugins.sparql")
        versions = {name: version(name) for name in ("rdflib", "pyshacl", "owlrl")}
    except ImportError:
        raise SemanticError("SEMANTIC_ENGINES_UNAVAILABLE") from None
    _require(versions == _ENGINE_VERSIONS, "SEMANTIC_ENGINE_VERSION_UNQUALIFIED")
    return rdf, shacl, owl, sparql, versions


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _task_id(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _owned_registry(snapshot: dict) -> dict:
    try:
        registry = load_agent_registry()
        owned = {a["id"]: {field: a[field] for field in
            ("id", "name", "role", "version", "capability_requirements")}
            for a in registry["agents"]}
        owned = json.loads(_canonical(owned))
    except (KeyError, TypeError, ValueError, RuntimeError, OSError):
        raise SemanticError("SEMANTIC_REGISTRY_UNAVAILABLE") from None
    agents = snapshot.get("agents")
    _require(type(agents) is list and len(agents) == 21, "SEMANTIC_EXACT_REGISTRY_POPULATION_REQUIRED")
    seen = set()
    for row in agents:
        _require(type(row) is dict and set(row) <= {"id", "name", "role", "version", "capabilities"},
            "SEMANTIC_AGENT_PROJECTION_FIELDS_INVALID")
        identity = row.get("id")
        _require(type(identity) is str and identity in owned and identity not in seen,
            "SEMANTIC_AGENT_NOT_PERMANENT")
        expected = owned[identity]
        _require(row.get("name") == expected["name"] and row.get("role") == expected["role"],
            "SEMANTIC_AGENT_OWNER_BINDING_MISMATCH")
        if "version" in row:
            _require(row["version"] == expected["version"], "SEMANTIC_AGENT_VERSION_MISMATCH")
        if "capabilities" in row:
            caps = row["capabilities"]
            _require(type(caps) is list and all(type(c) is str for c in caps) and
                len(caps) == len(set(caps)) and set(caps) == set(expected["capability_requirements"]),
                "SEMANTIC_DECLARED_CAPABILITY_OWNER_MISMATCH")
        seen.add(identity)
    _require(seen == set(owned), "SEMANTIC_EXACT_REGISTRY_POPULATION_REQUIRED")
    return owned


@dataclass
class _Bundle:
    graph: object
    summary: dict
    engines: tuple
    results: dict
    metrics: dict
    agents: dict


def _resource_bytes(name: str) -> bytes:
    path = _RESOURCES / name
    try:
        _require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 32768,
            "SEMANTIC_GOVERNED_RESOURCE_INVALID")
        return path.read_bytes()
    except OSError:
        raise SemanticError("SEMANTIC_GOVERNED_RESOURCE_INVALID") from None


def _uri(rdf, kind: str, identity: str):
    # All identities are prevalidated; no external scheme, parser or lookup.
    return rdf.URIRef("urn:prime:" + kind + ":" + identity)


def _shape_failures(graph, shapes, engine) -> set:
    _, shacl, _, _, _ = engine
    try:
        conforms, report, _ = shacl.validate(graph, shacl_graph=shapes, inference="none",
            advanced=False, js=False, inplace=False, do_owl_imports=False,
            allow_infos=False, allow_warnings=False, max_validation_depth=8)
    except Exception:
        raise SemanticError("SEMANTIC_SHACL_ENGINE_FAILED") from None
    if conforms is True:
        return set()
    rdf = engine[0]
    return set(report.objects(None, rdf.URIRef("http://www.w3.org/ns/shacl#focusNode")))


def _bind_shapes(shapes, rdf, owned, revision):
    """Closed-world membership/version constraints from the actual owning domain.

    Ontology classes alone are not identity admission: an arbitrary IRI labelled
    PermanentPrimeAgent must not pass. Lists are local RDF collections, not URLs.
    """
    from rdflib.collection import Collection
    p, sh = rdf.Namespace(NS), rdf.Namespace("http://www.w3.org/ns/shacl#")

    def property_shape(target, path):
        node = rdf.BNode()
        shapes.add((target, sh.property, node)); shapes.add((node, sh.path, path))
        return node

    identities = rdf.BNode()
    Collection(shapes, identities, [rdf.Literal(identity) for identity in sorted(owned)])
    shapes.add((property_shape(p.PermanentAgentShape, p.id), sh["in"], identities))
    members = rdf.BNode()
    Collection(shapes, members, [_uri(rdf, "agent", identity) for identity in sorted(owned)])
    for target, predicate in ((p.ResultShape, p.producer), (p.MetricShape, p.metricAgent)):
        shapes.add((property_shape(target, predicate), sh["in"], members))
    shapes.add((property_shape(p.ResultShape, p.sourceRevision), sh.hasValue, rdf.Literal(revision)))


def _new_bundle(snapshot: dict, owned: dict, ontology: bytes, shape_bytes: bytes, key: str) -> _Bundle:
    engine = _engines()
    rdf, _, owl, _, versions = engine
    p = rdf.Namespace(NS)
    graph, shapes = rdf.Graph(), rdf.Graph()
    # Governed checked-in Turtle bytes only. Never parse caller URLs/data/formats.
    try:
        graph.parse(data=ontology.decode("utf-8"), format="turtle")
        shapes.parse(data=shape_bytes.decode("utf-8"), format="turtle")
    except Exception:
        raise SemanticError("SEMANTIC_GOVERNED_TURTLE_INVALID") from None
    _bind_shapes(shapes, rdf, owned, snapshot["source_revision"])
    graph.add((_uri(rdf, "system", "prime"), rdf.RDF.type, p.PrimeOrchestrator))
    for identity, row in owned.items():
        node = _uri(rdf, "agent", identity)
        for predicate, value in ((rdf.RDF.type, p.PermanentPrimeAgent),
            (p.id, rdf.Literal(identity)), (p.name, rdf.Literal(row["name"])),
            (p.role, rdf.Literal(row["role"])), (p.version, rdf.Literal(row["version"])),
            (p.origin, rdf.Literal("DOMAIN_ASSERTED"))):
            graph.add((node, predicate, value))
        for capability in row["capability_requirements"]:
            cap = _uri(rdf, "capability", capability)
            graph.add((node, p.declaredCapability, cap))
            graph.add((cap, rdf.RDF.type, p.DeclaredCapability))
            graph.add((cap, p.id, rdf.Literal(capability)))
    quarantined, results, metrics = [], {}, {}
    seen_result_ids, seen_metric_ids = set(), set()

    def quarantine(kind, identity, code):
        # Do not return malformed identities, input literals or engine messages.
        quarantined.append({"kind": kind, "id": identity if _identifier(identity) else "UNKNOWN",
            "reason": code})

    for row in snapshot["results"]:
        identity = row.get("id") if type(row) is dict else None
        if type(row) is not dict or not set(row) <= _RESULT_FIELDS or not _identifier(identity):
            quarantine("result", identity, "UNSUPPORTED_RESULT_PROJECTION"); continue
        if identity in seen_result_ids:
            # Contradictory duplicate identities invalidate the snapshot, not last-writer-wins.
            raise SemanticError("SEMANTIC_DUPLICATE_RESULT_ID")
        seen_result_ids.add(identity)
        if row.get("agent_id") is not None and (type(row["agent_id"]) is not str or row["agent_id"] not in owned):
            quarantine("result", identity, "WRONG_OR_NONPERMANENT_AGENT"); continue
        if row.get("source_revision") is not None and row["source_revision"] != snapshot["source_revision"]:
            quarantine("result", identity, "VERSION_HISTORICAL_OR_INCOMPATIBLE"); continue
        if row.get("task_id") is not None and not _task_id(row["task_id"]):
            quarantine("result", identity, "TASK_IDENTITY_INVALID"); continue
        ref = row.get("evidence_ref")
        if ref is not None and (type(ref) is not str or not _task_id(row.get("task_id")) or
            re.fullmatch("objective:" + re.escape(row["task_id"]) + r":r[0-9]{1,6}", ref) is None):
            quarantine("result", identity, "BROKEN_EVIDENCE_REFERENCE"); continue
        if row.get("result_sha256") is not None and (type(row["result_sha256"]) is not str or
            _DIGEST.fullmatch(row["result_sha256"]) is None):
            quarantine("result", identity, "RESULT_DIGEST_INVALID"); continue
        enums = {"environment": _ENVIRONMENTS, "integrity": {"VALID", "INVALID", "UNKNOWN"},
            "currentness": {"CURRENT", "STALE", "HISTORICAL", "UNKNOWN", "CONTESTED"},
            "verification": {"UNVERIFIED", "PARTIAL", "VERIFIED", "UNKNOWN", "FAILED", "CONTRADICTED"}}
        if any(field in row and (type(row[field]) is not str or row[field] not in values)
               for field, values in enums.items()):
            quarantine("result", identity, "RESULT_STATE_INVALID"); continue
        node = _uri(rdf, "result", identity)
        graph.add((node, rdf.RDF.type, p.Result)); graph.add((node, p.id, rdf.Literal(identity)))
        graph.add((node, p.origin, rdf.Literal("DOMAIN_ASSERTED")))
        if row.get("agent_id") is not None:
            graph.add((node, p.producer, _uri(rdf, "agent", row["agent_id"])))
        if row.get("task_id") is not None:
            task = _uri(rdf, "task", row["task_id"])
            graph.add((node, p.task, task)); graph.add((task, rdf.RDF.type, p.Task))
            graph.add((task, p.id, rdf.Literal(row["task_id"])))
        for field, predicate in (("source_revision", p.sourceRevision), ("environment", p.environment),
            ("integrity", p.integrity), ("currentness", p.currentness), ("verification", p.verification),
            ("evidence_ref", p.evidenceRef), ("result_sha256", p.resultDigest)):
            if row.get(field) is not None:
                graph.add((node, predicate, rdf.Literal(row[field])))
        results[identity] = dict(row)
    for row in snapshot["metrics"]:
        identity = row.get("metric_id") if type(row) is dict else None
        if type(row) is not dict or not set(row) <= _METRIC_FIELDS or not _identifier(identity):
            quarantine("metric", identity, "UNSUPPORTED_METRIC_PROJECTION"); continue
        if identity in seen_metric_ids:
            raise SemanticError("SEMANTIC_DUPLICATE_METRIC_ID")
        seen_metric_ids.add(identity)
        refs = row.get("result_ids")
        if (type(row.get("agent_id")) is not str or row["agent_id"] not in owned or
            type(refs) is not list or not 1 <= len(refs) <= MAX_RESULTS
            or any(type(ref) is not str for ref in refs) or len(refs) != len(set(refs))
            or any(ref not in results or results[ref].get("agent_id") != row["agent_id"] for ref in refs)):
            quarantine("metric", identity, "METRIC_RESULT_PROVENANCE_INVALID"); continue
        if (("name" in row and (type(row["name"]) is not str or row["name"] not in _METRIC_NAMES)) or
            ("unit" in row and (type(row["unit"]) is not str or row["unit"] not in _UNITS)) or
            ("value" in row and (type(row["value"]) not in (int, float) or not math.isfinite(row["value"])))):
            quarantine("metric", identity, "METRIC_MEASUREMENT_INVALID"); continue
        node = _uri(rdf, "metric", identity)
        graph.add((node, rdf.RDF.type, p.Metric)); graph.add((node, p.id, rdf.Literal(identity)))
        graph.add((node, p.metricAgent, _uri(rdf, "agent", row["agent_id"])))
        graph.add((node, p.origin, rdf.Literal("DOMAIN_ASSERTED")))
        for ref in refs:
            graph.add((node, p.derivedFrom, _uri(rdf, "result", ref)))
        metrics[identity] = dict(row)
    _require(len(graph) <= MAX_TRIPLES, "SEMANTIC_GRAPH_BUDGET_EXCEEDED")
    invalid = _shape_failures(graph, shapes, engine)
    for identity in list(results):
        node = _uri(rdf, "result", identity)
        if node in invalid:
            del results[identity]; quarantine("result", identity, "SHACL_OR_CURRENT_EVIDENCE_CONSTRAINT_FAILED")
            graph.remove((node, None, None)); graph.remove((None, None, node))
    for identity in list(metrics):
        node = _uri(rdf, "metric", identity)
        if node in invalid or any(ref not in results for ref in metrics[identity]["result_ids"]):
            del metrics[identity]; quarantine("metric", identity, "SHACL_OR_RESULT_DEPENDENCY_FAILED")
            graph.remove((node, None, None)); graph.remove((None, None, node))
    _require(not _shape_failures(graph, shapes, engine), "SEMANTIC_REGISTRY_OR_GOVERNED_SHAPE_FAILED")
    asserted = set(graph)
    try:
        owl.DeductiveClosure(owl.OWLRL_Semantics, axiomatic_triples=False,
            datatype_axioms=False).expand(graph)
    except Exception:
        raise SemanticError("SEMANTIC_BOUNDED_REASONING_FAILED") from None
    _require(len(graph) <= MAX_DERIVED_TRIPLES, "SEMANTIC_DERIVED_GRAPH_BUDGET_EXCEEDED")
    _require(not _shape_failures(graph, shapes, engine), "SEMANTIC_INFERRED_SHAPE_FAILED")
    # No rule is permitted to manufacture certification or verified capability.
    _require(not list(graph.triples((None, p.hasVerifiedCapability, None))) and
        not list(graph.triples((None, p.hasL7Certification, None))), "SEMANTIC_AUTHORITY_UPLIFT_FORBIDDEN")
    summary = {"schema_version": SCHEMA, "status": "DEGRADED" if quarantined else "READY",
        "ontology_version": ONTOLOGY_VERSION, "shacl_version": "0.1.0", "query_contract_version": "0.1.0",
        "source_revision": snapshot["source_revision"], "snapshot_sha256": key,
        "permanent_agent_count": len(owned), "rdf": "PASS", "shacl": "PASS_ACCEPTED_PROJECTION",
        "reasoning": "PASS_FIXED_OWL2_RL_SUBSET", "engines": versions,
        "asserted_triples": len(asserted), "inferred_triples": len(set(graph) - asserted),
        "accepted_results": len(results), "accepted_metrics": len(metrics), "quarantined": quarantined,
        "semantic_compatibility_is_verified_capability": False, "l7_awarded": False,
        "authority": "READ_ONLY_REBUILDABLE_DOMAIN_PROJECTION", "no_universal_authority": True,
        "production_acceptance": "UNVERIFIED", "routing_promoted": False,
        "time_freshness": "NOT_INDEPENDENTLY_ESTABLISHED", "raw_payloads_stored": False,
        "metric_acceptance": "REGISTRY_AND_RESULT_REFERENCE_COMPATIBILITY_ONLY",
        "metric_accuracy_and_freshness": "CONSULT_OBSERVATORY_DOMAIN_NOT_VERIFIED_BY_SEMANTICS",
        "owl_profile": "Fixed class/subproperty subset; no caller axioms, imports, equivalence or transitivity",
        "resource_contract": {"max_input_bytes": MAX_INPUT_BYTES, "max_results": MAX_RESULTS,
            "max_metrics": MAX_METRICS, "max_triples": MAX_DERIVED_TRIPLES, "max_query_rows": MAX_QUERY_ROWS,
            "parallel_operations": 1, "cache_entries": 2,
            "time_policy": "Elapsed rejection plus fixed bounded graph/templates; no unsafe thread cancellation"}}
    return _Bundle(graph, summary, engine, results, metrics, owned)


def _bundle(snapshot: object) -> _Bundle:
    _require(type(snapshot) is dict and set(snapshot) == {"source_revision", "agents", "results", "metrics"},
        "SEMANTIC_SNAPSHOT_FIELDS_INVALID")
    _require(type(snapshot["source_revision"]) is str and _REVISION.fullmatch(snapshot["source_revision"]) is not None,
        "SEMANTIC_SOURCE_REVISION_REQUIRED")
    _require(type(snapshot["results"]) is list and len(snapshot["results"]) <= MAX_RESULTS and
        type(snapshot["metrics"]) is list and len(snapshot["metrics"]) <= MAX_METRICS,
        "SEMANTIC_ENTITY_BUDGET_EXCEEDED")
    raw = _canonical(snapshot)
    # Do not retain or reason over mutable caller objects after hashing them.
    snapshot = json.loads(raw)
    owned = _owned_registry(snapshot)
    ontology, shapes = _resource_bytes("ontology.ttl"), _resource_bytes("shapes.ttl")
    key = hashlib.sha256(raw + ontology + shapes + _canonical(owned)).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    result = _new_bundle(snapshot, owned, ontology, shapes, key)
    _CACHE[key] = result
    while len(_CACHE) > 2:
        _CACHE.popitem(last=False)
    return result


def _perform(snapshot, operation):
    _require(_GATE.acquire(blocking=False), "SEMANTIC_RESOURCE_BUSY")
    started = time.monotonic()
    try:
        result = operation(_bundle(snapshot))
        _require(time.monotonic() - started <= MAX_OPERATION_SECONDS, "SEMANTIC_ELAPSED_BUDGET_EXCEEDED")
        # Return detached public JSON, never a mutable graph or internal cache.
        return json.loads(_canonical(result))
    finally:
        _GATE.release()


def build_semantics(snapshot: dict) -> dict:
    """Build/reuse the small formal projection and return truthful public status."""
    return _perform(snapshot, lambda bundle: bundle.summary)


def _select(bundle: _Bundle, query: str, focus=None) -> list[dict]:
    rdf, _, _, sparql, _ = bundle.engines
    try:
        prepared = sparql.prepareQuery(_QUERIES[query], initNs={"p": rdf.Namespace(NS)})
        rows = bundle.graph.query(prepared, initBindings={} if focus is None else {"focus": focus})
        answer = [{str(k): str(v) for k, v in row.asdict().items()} for row in rows]
    except Exception:
        raise SemanticError("SEMANTIC_FIXED_QUERY_FAILED") from None
    _require(len(answer) <= MAX_QUERY_ROWS, "SEMANTIC_QUERY_RESULT_BUDGET_EXCEEDED")
    return answer


def query_semantics(snapshot: dict, query_id: str, subject: str | None = None) -> dict:
    """Execute one typed catalogue query; never accepts arbitrary SPARQL text."""
    _require(type(query_id) is str and query_id in QUERY_IDS, "SEMANTIC_QUERY_NOT_ALLOWED")
    _require(subject is None if query_id == "overview" else _identifier(subject), "SEMANTIC_QUERY_SUBJECT_INVALID")

    def query(bundle):
        rdf = bundle.engines[0]
        base = {"schema_version": "prime.semantic.query.v1", "query_id": query_id,
            "source_revision": bundle.summary["source_revision"], "ontology_version": ONTOLOGY_VERSION,
            "snapshot_sha256": bundle.summary["snapshot_sha256"], "status": "READY",
            "authority": "READ_ONLY_PROJECTION", "l7_awarded": False, "routing_promoted": False}
        if query_id == "overview":
            return {**base, "summary": bundle.summary, "agents": _select(bundle, "agents")}
        if query_id == "why":
            _require(subject in bundle.agents, "SEMANTIC_AGENT_NOT_PERMANENT")
            focus = _uri(rdf, "agent", subject)
            return {**base, "agent_id": subject, "declared_capabilities": _select(bundle, "capabilities", focus),
                "result_evidence": _select(bundle, "results", focus),
                "verified_capabilities": [], "verified_capability_state": "NOT_ESTABLISHED_BY_SEMANTICS",
                "certification": "CONSULT_CERTIFICATION_DOMAIN", "performance": "CONSULT_OBSERVATORY_DOMAIN"}
        if query_id in {"prove_it", "depends_on"}:
            if subject not in bundle.results:
                return {**base, "status": "UNKNOWN", "result_id": subject, "rows": [],
                    "reason": "NO_ACCEPTED_CURRENT_RESULT"}
            focus = _uri(rdf, "result", subject)
            return {**base, "result_id": subject, "rows": _select(bundle,
                "proof" if query_id == "prove_it" else "dependencies", focus),
                "proof_basis": "REFERENCES_DOMAIN_EVIDENCE_NOT_INDEPENDENT_FACT_VERIFICATION"}
        capabilities = {c for row in bundle.agents.values() for c in row["capability_requirements"]}
        _require(subject in capabilities, "SEMANTIC_CAPABILITY_NOT_REGISTERED")
        return {**base, "capability_id": subject,
            "routing_candidates": _select(bundle, "capability_agents", _uri(rdf, "capability", subject)),
            "verified_routing_decision": False}

    return _perform(snapshot, query)
