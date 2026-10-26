"""Real HTTPS -> tools -> workflow -> Academy -> Library -> recovery acceptance.

Qualification records are explicitly synthetic domain-evidence fixtures. All
other boundaries use actual components, SQLite, TLS and registered handlers.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time

from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import pytest

from app import pwa_sessions
from app.academy import AcademyError, PersistentAcademy
from app.action_records import ActionLedger
from app.agent_certification import AgentCertificationRegistry, REQUIRED_CASES
from app.agent_registry import agent_record
from app.activity_pockets.api import create_app
from app.activity_pockets.contracts import PocketManifest, ExtractionConfig, CoachingProposal, Provenance
from app.activity_pockets.factory import Factory, Principal
from app.activity_pockets.migration import adapt_agent
from app.activity_pockets.store import Store, canonical, digest
from app.activity_pockets.web import HTTPSFetcher, Source, QualityError, RetrievalError, extract
from app.activity_pockets.worker import Worker
from tests.test_lan_tls_repair import old_certificates


REVISION = "20bdad87a97e649eb751dd6c7add53d3fb9d65fe"
FIXTURES = Path(__file__).resolve().parents[1] / "app" / "activity_pockets" / "fixtures"
OWNER = Principal("lam", "owner:lam", "OWNER")
OTHER = Principal("other", "owner:other", "OWNER")


def qualification_fixture(root, *, revision=REVISION, now=None, expiry_hours=2):
    now = now or datetime.now(timezone.utc)
    for agent in ("a07", "a14"):
        directory = root / agent
        directory.mkdir(parents=True, exist_ok=True)
        rows = []
        for dimension in ("baseline", "role"):
            for case in REQUIRED_CASES[dimension]:
                name = dimension + "-" + case + ".json"
                raw = canonical({"fixture": True, "agent": agent, "dimension": dimension, "case": case}).encode()
                (directory / name).write_bytes(raw)
                rows.append({"agent_id": agent, "capability_id": "responsibility." + agent,
                    "dimension": dimension, "test_case": case, "certification_test": "controlled-fixture." + case,
                    "test_version": "1.0", "test_result": "PASS", "verifier": "a18",
                    "evidence": name, "evidence_sha256": hashlib.sha256(raw).hexdigest(),
                    "certified_at": (now - timedelta(minutes=1)).isoformat(), "last_revalidated": now.isoformat(),
                    "expires_at": (now + timedelta(hours=expiry_hours)).isoformat(), "source_revision": revision,
                    "authority_scope": agent_record(agent)["authority"], "fixture": True})
        (directory / "certification.json").write_text(json.dumps({"schema_version": "1.0", "records": rows}), encoding="utf-8")
    return AgentCertificationRegistry(root, source_revision=revision,
        verify_record=lambda row: row.get("fixture") is True and row.get("verifier") == "a18")


@pytest.fixture
def https_source(tmp_path):
    ca, _, leaf, key = old_certificates()
    (tmp_path / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "server.crt").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "server.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pages = {"/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\n"),
             "/catalog": (200, "text/html", (FIXTURES / "catalog.html").read_text()),
             "/changed": (200, "text/html", (FIXTURES / "layout-change.html").read_text())}
    requests = []
    gate, entered = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests.append((self.path, time.monotonic()))
            if self.path == "/blocked":
                entered.set()
                gate.wait(3)
            status, media, body = pages.get(self.path, (404, "text/plain", "not found"))
            raw = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(tmp_path / "server.crt", tmp_path / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"origin": f"https://127.0.0.1:{server.server_port}", "pages": pages, "requests": requests,
           "fetcher": HTTPSFetcher(ca_file=str(tmp_path / "ca.crt")), "gate": gate, "entered": entered}
    gate.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


@pytest.fixture
def environment(tmp_path, monkeypatch, https_source):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PRIME_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    ledger = ActionLedger(tmp_path / "actions.jsonl")
    import app.action_records as records
    monkeypatch.setattr(records, "action_ledger", lambda: ledger)
    store = Store(tmp_path / "pockets.db", REVISION, origin="controlled-fixture")
    cert = qualification_fixture(tmp_path / "qualifications")

    def make(paths=("/catalog", "/changed"), *, source_id="controlled", owners=("lam", "other"), store_override=None, **kwargs):
        source = Source(source_id, tuple(https_source["origin"] + path for path in paths), owners,
                        "Controlled fixture source: test owner permits catalogue extraction.", True, 0)
        return Factory(store_override or store, cert, (source,), fetcher=https_source["fetcher"], **kwargs)

    yield {"make": make, "store": store, "cert": cert, "ledger": ledger, "https": https_source, "root": tmp_path}
    assert ledger.close()


def manifest(*, owner="lam", component="factory", **updates):
    return PocketManifest(owner=owner, objective="Extract the authorized catalogue and preserve provenance.",
        source_ids=("controlled",), permissions=("provided_context.read",),
        success_criteria="All catalogue records have valid IDs, titles, prices and source evidence.",
        provenance=Provenance(component=component, source_revision=REVISION, origin="controlled-fixture", reference="pytest"),
        **updates)


def session_client(factory, *, start_worker=False, orqevia=False):
    # Genuine existing session store and cookie validation, no authentication mock.
    raw = "s" * 43
    with pwa_sessions.database() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?,0,?,?)", (pwa_sessions.digest(raw), "pwa:" + "1" * 32,
                   time.time() + 600, "lam", "OWNER"))
    app = create_app(factory, start_worker=start_worker)
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(pwa_sessions.ORQEVIA_COOKIE, raw)
    client.headers["origin"] = "https://testserver"
    return client


def test_complete_twenty_step_reference_workflow(environment):
    factory = environment["make"]()
    body = manifest(component="orqevia")
    with session_client(factory, start_worker=True, orqevia=True) as client:
        response = client.post("/api/agents/objectives/activity-pocket", json=body.model_dump(mode="json"),
                               headers={"idempotency-key": "objective-one"})
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 15
        observed = None
        while time.monotonic() < deadline:
            observed = factory.get(body.id, OWNER)
            if observed["evaluations"]:
                break
            time.sleep(.02)
        assert observed["state"] == "PAUSED" and observed["reason"] == "QUALITY_FAILURE"
        assert observed["outputs"][0]["details"]["records"] == [
            {"product_id": "book-1", "title": "Field Notes", "price": "12.50", "currency": "SGD"},
            {"product_id": "book-2", "title": "Atlas", "price": "20.00", "currency": "SGD"}]
        proposal, evaluation = observed["coaching_proposals"][0], observed["evaluations"][0]
        assert evaluation["passed"] and all(row["passed"] for row in evaluation["regression_results"])
        assert len(evaluation["regression_results"]) == 7
        assert observed["version"] == "1.0.0"  # Evaluation alone never promotes.
        approval = client.post(f"/api/activity-pockets/{body.id}/promote", json={"proposal_id": proposal["id"],
            "evaluation_id": evaluation["id"], "reason": "Controlled owner acceptance of exact held-out results."})
        assert approval.status_code == 200, approval.text
        while time.monotonic() < deadline:
            observed = factory.get(body.id, OWNER)
            if observed["state"] == "COMPLETED":
                break
            time.sleep(.02)
        assert observed["state"] == "COMPLETED" and observed["version"] == "1.0.1"
        assert len(observed["outputs"]) == 2
        assert observed["outputs"][1]["details"]["skill_version"] == "1.0.1"
        assert observed["qualification_evidence"]
        events = client.get(f"/api/activity-pockets/{body.id}/events").json()
        types = {row["event"]["event_type"] for row in events}
        assert {"orqevia.objective.submitted", "execution.failed", "coaching.proposed", "evaluation.completed",
                "promotion.approved", "execution.finished"} <= types
        assert client.get("/api/activity-pockets/status").json()["audit_chain_valid"]
    assert environment["ledger"].flush()
    records = [json.loads(line) for line in environment["ledger"].path.read_text().splitlines()]
    reads = [row for row in records if row.get("tool") == "pocket-source"]
    assert reads and all(row["agent_id"] == "a07" for row in reads)
    assert all(row["task_id"] in {event["event"]["details"].get("run_id") for event in events} for row in reads)


def test_standalone_worker_and_restart_persistence(environment):
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "one")
    assert Worker(factory).once()["status"] == "COMPLETED"
    reopened = environment["make"](("/catalog",), store_override=Store(environment["store"].path, REVISION, origin="controlled-fixture"))
    assert reopened.get(body.id, OWNER)["state"] == "COMPLETED"
    assert len(reopened.get(body.id, OWNER)["outputs"]) == 1
    script = """import json,sys
from app.activity_pockets.store import Store
from app.activity_pockets.factory import Factory,Principal
from app.agent_certification import AgentCertificationRegistry
factory=Factory(Store(sys.argv[1],sys.argv[2],origin='controlled-fixture'),
    AgentCertificationRegistry(sys.argv[3],source_revision=sys.argv[2]))
print(json.dumps(factory.get(sys.argv[4],Principal('lam','owner:lam','OWNER'))['state']))
"""
    result = subprocess.run([sys.executable, "-c", script, str(factory.store.path), REVISION,
                             str(environment["root"] / "qualifications"), body.id], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == "COMPLETED"


def test_duplicate_creation_and_execution_are_idempotent(environment):
    factory = environment["make"](("/catalog",))
    body = manifest()
    assert factory.create(body, OWNER, "same")["id"] == factory.create(body, OWNER, "same")["id"]
    first = factory.run_one(body.id, OWNER, "same-run")
    assert first == factory.run_one(body.id, OWNER, "same-run")
    assert len(factory.get(body.id, OWNER)["outputs"]) == 1
    with pytest.raises(ValueError):
        factory.create(body.model_copy(update={"objective": "A different authorized objective entirely."}), OWNER, "same")


def test_http_replay_with_server_generated_fields(environment):
    factory = environment["make"](("/catalog",))
    data = manifest().model_dump(mode="json")
    for key in ("id", "created_at", "not_before"):
        data.pop(key)
    with session_client(factory) as client:
        first = client.post("/api/activity-pockets", json=data, headers={"idempotency-key": "replay"})
        second = client.post("/api/activity-pockets", json=data, headers={"idempotency-key": "replay"})
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]


@pytest.mark.parametrize("open_access", ["0", "1"])
def test_ownership_and_authentication_survive_estate_open_access(environment, monkeypatch, open_access):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", open_access)
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "owner")
    with pytest.raises(KeyError):
        factory.get(body.id, OTHER)
    with pytest.raises(PermissionError):
        factory.create(manifest(owner="other"), OWNER, "wrong-owner")
    with TestClient(create_app(factory, start_worker=False), base_url="https://testserver") as client:
        assert client.get("/api/activity-pockets/status").status_code == 401
    with session_client(factory) as client:
        assert client.post(f"/api/activity-pockets/{body.id}/pause", headers={"origin": "https://attacker.invalid"}).status_code == 403
        client.base_url = "http://testserver"
        assert client.get("/api/activity-pockets/status").status_code == 426


def test_stale_qualification_prevents_create_and_runtime(environment):
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "fresh")
    factory.clock = lambda: time.time() + 3 * 3600
    assert factory.run_one(body.id, OWNER, "stale")["status"] == "PAUSED"
    with pytest.raises(PermissionError):
        factory.create(manifest(), OWNER, "stale-create")


@pytest.mark.parametrize("defect", ["unknown_source", "unknown_agent", "tool_expansion", "invalid_budget", "no_stop", "extra_policy"])
def test_malformed_and_unauthorized_manifests(environment, defect):
    factory = environment["make"](("/catalog",))
    body = manifest().model_dump(mode="json")
    if defect == "unknown_source": body["source_ids"] = ["unauthorized"]
    if defect == "unknown_agent": body["agent_ids"] = ["unregistered"]
    if defect == "tool_expansion": body["permitted_operations"] = ["shell.execute"]
    if defect == "invalid_budget": body["budget"]["max_attempts"] = 0
    if defect == "no_stop": body["stop_conditions"] = []
    if defect == "extra_policy": body["governance_override"] = True
    with pytest.raises((ValueError, PermissionError, RuntimeError)):
        factory.create(body, OWNER, defect)


def test_budget_exhaustion_stops_execution(environment):
    factory = environment["make"]()
    body = manifest(budget={"max_attempts": 1})
    factory.create(body, OWNER, "budget")
    assert factory.run_one(body.id, OWNER, "first")["status"] == "READY"
    assert factory.run_one(body.id, OWNER, "second")["status"] == "BUDGET_EXHAUSTED"
    assert len(environment["https"]["requests"]) == 2


def test_tool_failure_retry_and_robots_denial(environment):
    source = environment["https"]
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "retry")
    source["pages"]["/catalog"] = (503, "text/plain", "unavailable")
    assert factory.run_one(body.id, OWNER, "failed")["status"] == "READY"
    source["pages"]["/catalog"] = (200, "text/html", (FIXTURES / "catalog.html").read_text())
    factory.clock = lambda: time.time() + 2
    assert factory.run_one(body.id, OWNER, "recovered")["status"] == "COMPLETED"
    second = manifest()
    factory.create(second, OWNER, "robots")
    source["pages"]["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /catalog\n")
    assert factory.run_one(second.id, OWNER, "denied")["status"] == "FAILED"
    assert factory.get(second.id, OWNER)["reason"] == "ROBOTS_DENIED"


def test_https_verification_redirect_and_private_address_boundaries(environment):
    source = environment["https"]
    policy = Source("test", (source["origin"] + "/catalog",), ("lam",), "fixture", True, 0)
    with pytest.raises(RetrievalError):
        HTTPSFetcher().fetch(policy, policy.urls[0], max_bytes=10000, wall_seconds=2)
    public_only = Source("public", policy.urls, ("lam",), "fixture", False, 0)
    with pytest.raises(RetrievalError, match="SOURCE_ADDRESS_DENIED"):
        source["fetcher"].fetch(public_only, policy.urls[0], max_bytes=10000, wall_seconds=2)
    source["pages"]["/catalog"] = (302, "text/html", "redirect denied")
    with pytest.raises(RetrievalError, match="SOURCE_HTTP_302"):
        source["fetcher"].fetch(policy, policy.urls[0], max_bytes=10000, wall_seconds=2)
    with pytest.raises(ValueError):
        Source("bad", ("http://example.invalid/catalog",), ("lam",), "terms")
    with pytest.raises(ValueError):
        Source("bad", policy.urls, ("lam",), "terms", "false")


def test_candidate_rejection_and_no_self_promotion(environment):
    factory = environment["make"](("/changed",))
    body = manifest()
    factory.create(body, OWNER, "candidate")
    assert factory.run_one(body.id, OWNER, "failure")["status"] == "PAUSED"
    state = factory.get(body.id, OWNER)
    original = CoachingProposal.model_validate(state["coaching_proposals"][0])
    overfit = original.model_copy(update={"id": "overfit", "proposed_change": ExtractionConfig(title_fields=("name",), price_fields=("amount",))})
    with factory.store.transaction() as db:
        factory.store.put(db, "coaching_proposal", overfit, body.id)
        rejected = factory.academy.evaluate_candidate(db, overfit)
    assert not rejected.passed
    with pytest.raises(PermissionError):
        factory.promote(body.id, OWNER, overfit.id, rejected.id, "Must reject original-layout regression.")
    accepted = factory.evaluate_pending()
    assert accepted["passed"]
    with pytest.raises(PermissionError):
        factory.promote(body.id, Principal("lam", "a07", "WORKER"), original.id, accepted["id"], "Self promotion denied.")
    with pytest.raises(ValueError):
        ExtractionConfig.model_validate({"title_fields": ["name"], "price_fields": ["amount"], "grant_tools": ["shell"]})
    assert sum(row["event"]["event_type"] == "promotion.denied" for row in factory.events(body.id, OWNER)) == 2


def test_actual_pause_cancel_multi_pocket_and_emergency_isolation(environment):
    factory = environment["make"](("/catalog",))
    one, two = manifest(), manifest(owner="other")
    factory.create(one, OWNER, "one")
    factory.create(two, OTHER, "two")
    factory.emergency_stop(OWNER)
    assert factory.run_one(one.id, OWNER, "stop")["status"] == "EMERGENCY_STOPPED"
    assert factory.run_one(two.id, OTHER, "other")["status"] == "COMPLETED"
    factory.emergency_stop(OWNER, False)
    assert factory.transition(one.id, OWNER, "pause")["state"] == "PAUSED"
    assert factory.transition(one.id, OWNER, "resume")["state"] == "READY"
    assert factory.transition(one.id, OWNER, "cancel")["state"] == "CANCELLED"
    assert factory.transition(one.id, OWNER, "retire")["state"] == "RETIRED"


def test_interrupted_execution_recovers_with_fencing_and_reserved_accounting(environment):
    https = environment["https"]
    https["pages"]["/blocked"] = (200, "text/html", (FIXTURES / "catalog.html").read_text())
    factory = environment["make"](("/blocked",))
    qualification_fixture(environment["root"] / "qualifications", expiry_hours=24)
    body = manifest(budget={"max_bytes": 3_000_000, "max_wall_seconds": 120})
    factory.create(body, OWNER, "interrupted")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(factory.run_one, body.id, OWNER, "before-crash")
        assert https["entered"].wait(2)
        # A fresh process sees only durable state. Advance to its expired lease.
        restarted = environment["make"](("/blocked",), store_override=Store(factory.store.path, REVISION, origin="controlled-fixture"),
                                         clock=lambda: time.time() + 8 * 3600)
        assert restarted.recover() == [body.id]
        recovered = restarted.get(body.id, OWNER)
        assert recovered["state"] == "READY" and recovered["bytes"] == 1_000_000
        assert recovered["seconds"] == 20  # Eight powered-off hours consume only the attempt reservation.
        https["gate"].set()
        assert running.result(timeout=3)["status"] == "STALE_RESULT_DISCARDED"
    assert restarted.run_one(body.id, OWNER, "after-restart")["status"] == "COMPLETED"
    assert len(restarted.get(body.id, OWNER)["outputs"]) == 1


def test_concurrent_duplicate_execution_and_owner_cancellation(environment):
    https = environment["https"]
    https["pages"]["/blocked"] = (200, "text/html", (FIXTURES / "catalog.html").read_text())
    factory = environment["make"](("/blocked",))
    body = manifest()
    factory.create(body, OWNER, "concurrent")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(factory.run_one, body.id, OWNER, "run")
        assert https["entered"].wait(2)
        assert factory.run_one(body.id, OWNER, "run")["status"] == "RUNNING"
        factory.transition(body.id, OWNER, "cancel")
        https["gate"].set()
        assert running.result(timeout=3)["status"] == "RESULT_DISCARDED"
    assert factory.get(body.id, OWNER)["outputs"] == []


def test_persistent_academy_room_interfaces_and_budgets(environment):
    academy = PersistentAcademy(environment["store"], "lam")
    first = academy.submit_training_attempt("a07", "research", "s-research-01", tokens=1, wall_seconds=.01)
    feedback = academy.record_feedback(first["attempt_id"], "Preserve the source reference.")
    assert feedback["status"] == "feedback_recorded"
    reopened = PersistentAcademy(environment["store"], "lam")
    second = reopened.submit_training_attempt("a07", "research", "s-research-01", tokens=1, wall_seconds=.01)
    assert second["attempt_id"] != first["attempt_id"]
    assessment = reopened.submit_assessment("a07", "autonomy-safety", "s-autonomy-02", outcome={"pass": True})
    assert assessment["status"] == "assessed_not_certified"
    with pytest.raises(AcademyError):
        reopened.submit_training_attempt("a07", "research", "s-research-01", tokens=20001, wall_seconds=1)


def test_artifact_tampering_and_full_fleet_coverage_are_explicit(environment):
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "tampering")
    coverage = factory.coverage(OWNER)
    assert coverage["registered_count"] == 21 and not coverage["all_agents_coached"]
    assert coverage["coaching_snapshot"]["status"] == "UNAVAILABLE"
    with factory.store.transaction() as db:
        row = db.execute("SELECT id,body FROM pocket_records WHERE kind='library_skill'").fetchone()
        skill = json.loads(row["body"])
        skill["artifact"]["title_fields"] = ["name"]
        db.execute("UPDATE pocket_records SET body=? WHERE kind='library_skill' AND id=?", (canonical(skill), row["id"]))
    with pytest.raises((ValueError, PermissionError)):
        factory.run_one(body.id, OWNER, "tampered")
    assert factory.get(body.id, OWNER)["outputs"] == []


def test_legacy_adapter_and_prompt_injection_do_not_grant_tools():
    adapted = adapt_agent(agent_record("a07"), owner="lam", source_revision=REVISION)
    assert adapted.agent_id == "a07" and adapted.provenance.origin == "legacy-adapter"
    with pytest.raises(ValueError):
        adapt_agent({"agent_id": "prime", "immutable_id": "prime", "status": "registered"}, owner="lam", source_revision=REVISION)
    records = extract((FIXTURES / "heldout" / "injection.html").read_text(), ExtractionConfig(title_fields=("title",), price_fields=("price",)))
    assert records[0]["price"] == "2.00"
    with pytest.raises(QualityError):
        extract((FIXTURES / "heldout" / "personal.html").read_text(), ExtractionConfig(title_fields=("title",), price_fields=("price",)))


def test_source_request_spacing_and_origin_aliases(environment):
    https = environment["https"]
    source = Source("paced", (https["origin"] + "/catalog",), ("lam",), "fixture", True, .05)
    https["fetcher"].fetch(source, source.urls[0], max_bytes=10000, wall_seconds=2)
    assert https["requests"][-1][1] - https["requests"][-2][1] >= .045
    one = Source("one", source.urls, ("lam",), "fixture", True, .2)
    two = Source("two", source.urls, ("lam",), "fixture", True, .2)
    factory = Factory(environment["store"], environment["cert"], (one, two), fetcher=https["fetcher"])
    first = manifest().model_copy(update={"source_ids": ("one",)})
    second = manifest().model_copy(update={"source_ids": ("two",)})
    factory.create(first, OWNER, "one")
    factory.create(second, OWNER, "two")
    assert factory.run_one(first.id, OWNER, "first")["status"] == "COMPLETED"
    assert factory.run_one(second.id, OWNER, "second")["status"] == "SOURCE_NOT_DUE"


@pytest.mark.parametrize("resource", ["max_bytes", "max_records"])
def test_transfer_and_output_budgets(environment, resource):
    factory = environment["make"](("/catalog",))
    body = manifest(budget={resource: 1})
    factory.create(body, OWNER, "small")
    assert factory.run_one(body.id, OWNER, "one")["status"] == "BUDGET_EXHAUSTED"
    state = factory.get(body.id, OWNER)
    assert state["outputs"] == [] and state["records"] == 0
    assert state["bytes"] <= state["manifest"]["budget"]["max_bytes"]


def test_rollback_and_retention_preserve_audit(environment):
    factory = environment["make"](("/changed",))
    body = manifest(retention_days=1)
    factory.create(body, OWNER, "rollback")
    factory.run_one(body.id, OWNER, "failure")
    evaluation = factory.evaluate_pending()
    proposal = factory.get(body.id, OWNER)["coaching_proposals"][0]
    promoted = factory.promote(body.id, OWNER, proposal["id"], evaluation["id"], "Owner accepts measured fixture change.")
    assert promoted["version"] == "1.0.1"
    assert factory.run_one(body.id, OWNER, "good")["status"] == "COMPLETED"
    rolled = factory.rollback(body.id, OWNER, promoted["decisions"][0]["id"], "Demonstrate a reversible pinned-version rollback.")
    assert rolled["state"] == "PAUSED" and rolled["version"] == "1.0.0"
    factory.transition(body.id, OWNER, "cancel")
    factory.transition(body.id, OWNER, "retire")
    factory.clock = lambda: time.time() + 86401
    assert factory.purge_expired_outputs() == [body.id]
    state = factory.get(body.id, OWNER)
    assert state["outputs"] == [] and state["reason"] == "RETENTION_PURGED"
    assert state["recovery"][-1]["operation"] == "retention-purge"
    assert factory.health(OWNER)["audit_chain_valid"]


def test_recovery_preserves_cancelled_owner_intent(environment):
    https = environment["https"]
    https["pages"]["/blocked"] = (200, "text/html", (FIXTURES / "catalog.html").read_text())
    factory = environment["make"](("/blocked",))
    body = manifest(budget={"max_attempts": 1})
    factory.create(body, OWNER, "cancel-recovery")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(factory.run_one, body.id, OWNER, "run")
        assert https["entered"].wait(2)
        factory.transition(body.id, OWNER, "cancel")
        factory.clock = lambda: time.time() + 30
        assert factory.recover() == [body.id]
        state = factory.get(body.id, OWNER)
        assert state["state"] == "CANCELLED" and state["reason"] == "OWNER_CANCEL"
        https["gate"].set()
        assert running.result(timeout=3)["status"] == "STALE_RESULT_DISCARDED"


def test_tampered_evaluation_and_stale_source_cannot_promote(environment):
    factory = environment["make"](("/changed",))
    body = manifest()
    factory.create(body, OWNER, "eval")
    factory.run_one(body.id, OWNER, "failure")
    evaluation = factory.evaluate_pending()
    proposal = factory.get(body.id, OWNER)["coaching_proposals"][0]
    assert evaluation["candidate_sha256"] == digest(proposal["proposed_change"])
    with factory.store.transaction() as db:
        db.execute("UPDATE pocket_records SET body=json_set(body,'$.provenance.source_revision',?) "
                   "WHERE kind='evaluation' AND id=?", ("b" * 40, evaluation["id"]))
    with pytest.raises((PermissionError, ValueError)):
        factory.promote(body.id, OWNER, proposal["id"], evaluation["id"], "Tampered evaluation must never approve.")
    assert not factory.health(OWNER)["audit_chain_valid"]
    with factory.store.connect() as db:
        assert db.execute("SELECT version FROM pockets WHERE id=?", (body.id,)).fetchone()[0] == "1.0.0"


def test_full_api_and_console_are_mounted_in_existing_product(environment, monkeypatch):
    import app.activity_pockets.api as api
    from app import interface_server, production_entry
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", REVISION)
    api.default_factory.cache_clear()
    try:
        setup = session_client(environment["make"](("/catalog",)))
        for application in (interface_server.app, production_entry.app):
            client = TestClient(application, base_url="https://testserver")
            client.cookies.update(setup.cookies)
            client.headers["origin"] = "https://testserver"
            response = client.get("/api/activity-pockets/status")
            assert response.status_code == 200, response.text
            assert response.json()["configuration"] == "NO_AUTHORIZED_SOURCES"
            assert response.headers["cache-control"] == "no-store"
            assert client.get("/activity-pockets").status_code == 200
            assert client.get("/activity-pockets/app.js").status_code == 200
            client.close()
        setup.close()
    finally:
        api.default_factory.cache_clear()


def test_actual_actor_coaching_and_advisory_skill_migration(environment):
    from app.activity_pockets.migration import adapt_skill
    factory = environment["make"](("/changed",))
    body = manifest(agent_ids=("a14",))
    factory.create(body, OWNER, "a14")
    factory.run_one(body.id, OWNER, "failed")
    state = factory.get(body.id, OWNER)
    assert state["coaching_proposals"][0]["proposer"] == "a14"
    registry = json.loads((Path(__file__).parents[1] / "config" / "prime_skill_registry.json").read_text())
    migrated = adapt_skill(registry["skills"][0], owner="lam", source_revision=REVISION, agent_ids=("a07",))
    assert migrated.tool_ids == () and migrated.artifact.authority == "advisory_only"


def test_source_upgrade_revalidates_builtin_without_erasing_history(environment):
    factory = environment["make"](("/catalog",))
    original = manifest()
    factory.create(original, OWNER, "old-source")
    updated_revision = "b" * 40
    qualifications = qualification_fixture(environment["root"] / "qualifications", revision=updated_revision)
    upgraded = Factory(Store(factory.store.path, updated_revision, origin="controlled-fixture"), qualifications,
                       tuple(factory.sources.values()), fetcher=environment["https"]["fetcher"])
    second = manifest()
    upgraded.create(second, OWNER, "new-source")
    assert upgraded.run_one(original.id, OWNER, "recovered-upgrade")["status"] == "COMPLETED"
    with upgraded.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pocket_records WHERE kind='skill_validation'").fetchone()[0] == 2


def test_retired_training_feedback_is_purged_without_breaking_academy(environment):
    factory = environment["make"](("/changed",))
    body = manifest(retention_days=1)
    factory.create(body, OWNER, "retention-feedback")
    factory.run_one(body.id, OWNER, "fail")
    with factory.store.connect() as db:
        record = factory.store.records(db, "academy_training", "lam", body.id)[0]
    academy = PersistentAcademy(factory.store, "lam")
    academy.record_feedback(record["details"]["attempt_id"], "Original failure retained for diagnosis.")
    factory.transition(body.id, OWNER, "cancel")
    factory.transition(body.id, OWNER, "retire")
    factory.clock = lambda: time.time() + 86401
    assert factory.purge_expired_outputs() == [body.id]
    new = PersistentAcademy(factory.store, "lam").submit_training_attempt("a07", "research", "s-research-01", tokens=0, wall_seconds=0)
    assert new["attempt_id"] != record["details"]["attempt_id"]
    assert factory.health(OWNER)["audit_chain_valid"]


def test_long_robots_interval_progresses_after_restart(environment):
    https = environment["https"]
    https["pages"]["/robots.txt"] = (200, "text/plain", "User-agent: *\nAllow: /\nCrawl-delay: 30\n")
    factory = environment["make"](("/catalog",))
    body = manifest()
    factory.create(body, OWNER, "slow-source")
    first = factory.run_one(body.id, OWNER, "robots-only")
    assert first["status"] == "READY" and first["reason"] == "SOURCE_RATE_RETRY"
    assert [path for path, _ in https["requests"]] == ["/robots.txt"]
    restarted = environment["make"](("/catalog",), store_override=Store(factory.store.path, REVISION, origin="controlled-fixture"),
                                     clock=lambda: time.time() + 31)
    assert restarted.run_one(body.id, OWNER, "page-due")["status"] == "COMPLETED"
    assert [path for path, _ in https["requests"]] == ["/robots.txt", "/catalog"]


def test_interface_creation_and_separate_backend_worker_share_configuration(environment, monkeypatch):
    import app.activity_pockets.api as api
    import app.agent_cert_azure_es256 as azure
    from app import interface_server
    root = Path(pwa_sessions.os.environ["ORQEVIA_DATA_DIR"])
    qualification_fixture(root / "agent-certification")
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("ORQEVIA_AGENT_CERT_AZURE_ES256_ENABLED", "1")
    monkeypatch.setattr(azure, "verifier_from_azure_es256_pin_file", lambda *args, **kwargs: lambda row: row.get("fixture") is True)
    configuration = environment["root"] / "sources.json"
    configuration.write_text(json.dumps({"schema_version": "1.0", "sources": [{"id": "controlled",
        "urls": [environment["https"]["origin"] + "/catalog"], "owners": ["lam"], "terms_reference": "controlled fixture",
        "allow_private": True, "min_interval_seconds": 0}]}))
    monkeypatch.setenv("ORQEVIA_POCKET_SOURCES_FILE", str(configuration))
    api.default_factory.cache_clear()
    setup = session_client(environment["make"](("/catalog",)))
    try:
        client = TestClient(interface_server.app, base_url="https://testserver")
        client.cookies.update(setup.cookies)
        client.headers["origin"] = "https://testserver"
        body = manifest(component="orqevia")
        created = client.post("/api/agents/objectives/activity-pocket", json=body.model_dump(mode="json"), headers={"idempotency-key": "shared-product"})
        assert created.status_code == 202, created.text
        api.default_factory.cache_clear()  # Construct the independent backend's view of shared storage.
        backend = api.default_factory()
        backend.fetcher = environment["https"]["fetcher"]
        assert Worker(backend).once()["status"] == "COMPLETED"
        assert client.get("/api/activity-pockets/" + body.id).json()["state"] == "COMPLETED"
        client.close()
    finally:
        setup.close()
        api.default_factory.cache_clear()


def test_completed_rollback_resume_does_not_execute_consumed_sources(environment):
    factory = environment["make"](("/changed",))
    body = manifest()
    factory.create(body, OWNER, "done-rollback")
    factory.run_one(body.id, OWNER, "failure")
    evaluation = factory.evaluate_pending()
    proposal = factory.get(body.id, OWNER)["coaching_proposals"][0]
    promoted = factory.promote(body.id, OWNER, proposal["id"], evaluation["id"], "Owner accepts controlled candidate.")
    factory.run_one(body.id, OWNER, "complete")
    count = len(environment["https"]["requests"])
    factory.rollback(body.id, OWNER, promoted["decisions"][0]["id"], "Restore original pin after completion.")
    factory.transition(body.id, OWNER, "resume")
    assert Worker(factory).once()["status"] == "COMPLETED"
    assert len(environment["https"]["requests"]) == count


def test_published_artifact_can_be_revalidated_after_source_upgrade(environment):
    factory = environment["make"](("/changed",))
    body = manifest()
    factory.create(body, OWNER, "upgrade-candidate")
    factory.run_one(body.id, OWNER, "failure")
    evaluation = factory.evaluate_pending()
    proposal = factory.get(body.id, OWNER)["coaching_proposals"][0]
    factory.promote(body.id, OWNER, proposal["id"], evaluation["id"], "Owner approves the immutable artifact.")
    updated_revision = "c" * 40
    qualifications = qualification_fixture(environment["root"] / "qualifications", revision=updated_revision)
    upgraded = Factory(Store(factory.store.path, updated_revision, origin="controlled-fixture"), qualifications,
                       tuple(factory.sources.values()), fetcher=environment["https"]["fetcher"])
    assert upgraded.run_one(body.id, OWNER, "needs-review")["reason"] == "SKILL_REVALIDATION_REQUIRED"
    assert upgraded.revalidate(body.id, OWNER)["state"] == "READY"
    assert upgraded.run_one(body.id, OWNER, "revalidated")["status"] == "COMPLETED"


def test_dns_timeout_does_not_keep_interpreter_alive():
    script = """import socket,time
from app.activity_pockets.web import HTTPSFetcher,RetrievalError
socket.getaddrinfo=lambda *args,**kwargs:time.sleep(60)
try: HTTPSFetcher().addresses('fixture.invalid',443,.02)
except RetrievalError: print('DNS_TIMEOUT')
"""
    started = time.monotonic()
    process = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=5)
    assert process.returncode == 0 and "DNS_TIMEOUT" in process.stdout
    assert time.monotonic() - started < 5


def test_unknown_agent_is_a_scoped_api_denial(environment):
    factory = environment["make"](("/catalog",))
    with session_client(factory) as client:
        data = manifest().model_dump(mode="json")
        data["agent_ids"] = ["unregistered"]
        response = client.post("/api/activity-pockets", json=data, headers={"idempotency-key": "unknown"})
        assert response.status_code == 403


def test_non_layout_failure_is_not_promoted_as_an_alias_improvement(environment):
    factory = environment["make"](("/catalog",))
    environment["https"]["pages"]["/catalog"] = (200, "text/html", (FIXTURES / "heldout" / "invalid-price.html").read_text())
    body = manifest()
    factory.create(body, OWNER, "invalid-price")
    factory.run_one(body.id, OWNER, "fail")
    # This page first fails the baseline field layout; its unsafe amount must
    # still fail runtime validation after any approved alias improvement.
    proposal = CoachingProposal.model_validate(factory.get(body.id, OWNER)["coaching_proposals"][0])
    no_change = proposal.model_copy(update={"id": "no-change", "proposed_change": ExtractionConfig(title_fields=("title",), price_fields=("price",))})
    with factory.store.transaction() as db:
        rejected = factory.academy.evaluate_candidate(db, no_change)
    assert not rejected.passed
    environment["https"]["pages"]["/catalog"] = (200, "text/html", '<article data-id="bad"><span data-field="title">Bad</span><span data-field="price">NaN</span></article>')
    second = manifest()
    factory.create(second, OWNER, "numeric-failure")
    factory.run_one(second.id, OWNER, "fail")
    assert factory.get(second.id, OWNER)["coaching_proposals"] == []


def test_untrusted_document_structure_is_bounded():
    config = ExtractionConfig(title_fields=("title",), price_fields=("price",))
    with pytest.raises(QualityError):
        extract('<div>' * 129, config)
    with pytest.raises(QualityError):
        extract('<article data-id="x"><span data-field="title">' + 'x' * 513 + '</span></article>', config)
