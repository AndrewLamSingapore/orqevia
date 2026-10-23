"""Optional real-service adapters for the scoped collective operations board.

No agent assertion selects a principal, target URL, tool, credential or role.
Existing queue execution remains independent if this optional registry fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .agent_registry import REGISTRY_PATH, load_agent_registry
from .collective_intelligence import (
    CollectiveConflict,
    CollectiveDenied,
    CollectiveError,
    CollectiveNotFound,
    CollectivePrincipal,
    CollectiveStore,
    canonical_json,
    digest,
)

_STORES: dict[str, CollectiveStore] = {}
_LOCK = threading.RLock()
_RECONCILE_LOCK = threading.Lock()
_LAST_AUTO_REPAIR = 0.0
_LAST_STATE = {"state": "NOT_OBSERVED", "published": 0, "failures": 0}
ROOT = Path(__file__).resolve().parents[1]


def _configured_principal(role: str = "SYSTEM", actor: str = "collective-runtime") -> CollectivePrincipal:
    account = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    if os.getenv("ORQEVIA_COLLECTIVE_ENABLED") != "1" or not account:
        raise CollectiveDenied("collective service is not activated with a bound owner")
    owner = hashlib.sha256(account.encode()).hexdigest()
    return CollectivePrincipal(os.getenv("ORQEVIA_TENANT_ID", "personal"), owner, actor, roles=frozenset({role}))


def _bound(p: CollectivePrincipal | None) -> CollectivePrincipal:
    configured = _configured_principal()
    if p is not None and (p.tenant_id, p.owner_id) != (configured.tenant_id, configured.owner_id):
        raise CollectiveDenied("principal is outside the configured service scope")
    return p or configured


def get_store() -> CollectiveStore:
    p = _configured_principal()
    path = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "collective-intelligence.db"
    key = str(path.resolve())
    with _LOCK:
        if key not in _STORES:
            store = CollectiveStore(path)
            store.provision(p)
            _STORES[key] = store
        return _STORES[key]


def _command(store: CollectiveStore, p: CollectivePrincipal, operation: str, data: dict, key: str) -> dict:
    return store.command(p, operation, data, key)["record"]


def _revision() -> str:
    candidate = os.getenv("ORQEVIA_RUNTIME_REVISION", os.getenv("ORQEVIA_SOURCE_REVISION", "")).strip()
    return candidate[:120] or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _execution(
    store: CollectiveStore,
    *,
    adapter: str,
    scope: dict,
    execution_id: str,
    source: str,
    content: dict | None = None,
    subject_id: str | None = None,
) -> dict:
    p = _configured_principal(actor="runtime-observer")
    key = "runtime-evidence:" + execution_id
    with store.connect() as db:
        prior = db.execute(
            "SELECT response_json FROM command_receipts WHERE tenant_id=? AND owner_id=? AND actor_id=? AND key=?",
            (p.tenant_id, p.owner_id, p.actor_id, key),
        ).fetchone()
    if prior:
        record = json.loads(prior[0])["record"]
        previous = record["data"]["content"]
        if (
            previous.get("adapter") != adapter
            or previous.get("scope") != scope
            or any(previous.get(key) != value for key, value in (content or {}).items())
        ):
            raise CollectiveConflict("authoritative execution receipt changed after publication")
        return record
    body = {
        "adapter": adapter,
        "scope": scope,
        "plan_id": f"observation:{execution_id}",
        "execution_id": execution_id,
        "candidate_revision": _revision(),
        "outcome": "SUCCEEDED",
        **(content or {}),
    }
    payload = {
        "content": body,
        "source": source,
        "kind": "EXECUTION",
        "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
    }
    if subject_id:
        payload["subject_id"] = subject_id
    return _command(store, p, "evidence.record", payload, key)


def publish_job(job_id: str, principal: CollectivePrincipal | None = None) -> dict:
    """Re-read actual committed queue output; a POST body never supplies results."""
    _bound(principal)
    from .compute_queue_api import queue

    job = queue.get(job_id)
    known = {item["agent_id"] for item in load_agent_registry()["agents"]}
    if job.get("status") != "completed" or job.get("agent") not in known:
        raise CollectiveConflict("only completed canonical agent executions can contribute")
    result = job.get("result")
    if not isinstance(result, str) or not result.strip():
        raise CollectiveConflict("completed execution has no inspectable output")
    if result.strip().upper() in {"READY", "OK", "PASS", "ALIVE"}:
        return {"state": "SKIPPED_LIVENESS_ONLY", "job_id": job_id}
    store = get_store()
    p = _configured_principal()
    result_sha = hashlib.sha256(result.encode()).hexdigest()
    prompt_sha = hashlib.sha256(job["prompt"].encode()).hexdigest()
    try:
        request_receipt = json.loads(job.get("inference_receipt") or "{}")
    except (ValueError, TypeError):
        request_receipt = {}
    ev = _execution(
        store,
        adapter="queue_inference",
        scope={"job_id": job_id},
        execution_id=job_id,
        source="authoritative-compute-queue",
        content={
            "agent_id": job["agent"],
            "result_sha256": result_sha,
            "prompt_sha256": prompt_sha,
            "provider": job.get("provider"),
            "model": request_receipt.get("model") or job.get("model") or "NOT_RECORDED",
            "actual_cost_usd": job.get("actual_cost_usd"),
            "input_tokens": job.get("input_tokens"),
            "output_tokens": job.get("output_tokens"),
            "completed_at": job.get("completed_at"),
        },
    )
    agent = CollectivePrincipal(
        p.tenant_id, p.owner_id, "ignored", agent_id=job["agent"], execution_id=job_id, roles=frozenset({"AGENT"})
    )
    claim = _command(
        store,
        agent,
        "claim.contribute",
        {
            "title": f"Agent {job['agent']} execution finding",
            "statement": result[:6000],
            "classification": "HYPOTHESIS",
            "evidence_ids": [ev["id"]],
        },
        "job-contribution:" + job_id,
    )
    notebook = {"state": "UNAVAILABLE"}
    try:
        from .agent_notebooks import NotebookPrincipal
        from .agent_notebook_api import _store

        record = _store().add_record(
            NotebookPrincipal(job["agent"], "AGENT", job["agent"]),
            agent_id=job["agent"],
            section="project_knowledge",
            content={"finding": result[:6000], "collective_claim_id": claim["id"], "result_sha256": result_sha},
            source="collective-queue-adapter",
            scope="private",
            source_ref="queue-job:" + job_id,
            evidence_refs=[ev["id"]],
            verification_status="agent_reported",
            task_id=job_id,
            idempotency_key="collective:" + job_id,
            logical_key="collective:" + job_id,
            embed=False,
        )
        notebook = {"state": "RECORDED", "memory_id": record.get("memory_id")}
    except (RuntimeError, ValueError, OSError):
        pass
    investigation = _publish_investigation(store, agent, job, result)
    return {
        "state": "PUBLISHED",
        "job_id": job_id,
        "agent_id": job["agent"],
        "claim_id": claim["id"],
        "evidence_id": ev["id"],
        "result_sha256": result_sha,
        "notebook": notebook,
        "investigation": investigation,
        "classification": "HYPOTHESIS",
        "qualification": "NOT_ESTABLISHED_BY_CONTRIBUTION",
    }


QUESTION_FIELDS = {
    "canonical_id": "Does the mirrored canonical identifier match the current canonical source?",
    "source_sha256": "Does the mirrored source digest match the current canonical source bytes?",
    "capability_requirements": "Does the mirrored capability list match the current canonical source?",
    "runtime_health": "Is the agent runtime health established by a fresh independent runtime observation?",
}
QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "field": {"type": "string"},
        "reason": {"type": "string"},
        "gap_detected": {"type": "boolean"},
        "gap_description": {"type": "string"},
    },
    "required": ["question", "field", "reason", "gap_detected", "gap_description"],
    "additionalProperties": False,
}


def start_investigation(principal: CollectivePrincipal, agent_id: str, target_id: str, idempotency_key: str) -> dict:
    _bound(principal)
    if "OWNER" not in principal.roles:
        raise CollectiveDenied("owner-authorized investigation required")
    from .compute_queue_api import SubmitJob, queue

    store = get_store()
    store.lookup_agent(principal, agent_id)
    with store.connect() as db:
        target = store._get(db, principal, target_id)
    if target["kind"] != "agents":
        raise CollectiveError("the fixed independent source checker currently supports canonical agent records")
    from .collective_repair import inspect_pending_index

    pending = inspect_pending_index()
    pending_target = pending.get("oldest") if pending.get("supported_target") else None
    field = ("canonical_id", "source_sha256", "capability_requirements")[int(agent_id[1:]) % 3]
    policy = store.lookup_policy(principal, "policy:authorized-board-participation")
    from .agent_notebooks import NotebookPrincipal
    from .agent_notebook_api import _store as notebook_store

    own_records = notebook_store().list_records(
        NotebookPrincipal(agent_id, "AGENT", agent_id),
        agent_id,
        limit=3,
    )
    board_context = {
        "policy_id": policy["id"],
        "policy_version": policy["version"],
        "required_behaviors": policy["data"]["required_behaviors"],
        "shared_board_target": target["id"],
        "target_version": target["version"],
        "own_notebook_records": [
            {key: record.get(key) for key in ("memory_id", "content_sha256", "verification_status", "updated_at")}
            for record in own_records.get("records", [])
        ],
        "read_scope": "AUTHORIZED_SHARED_BOARD_AND_OWN_PRIVATE_NOTEBOOK",
        "acknowledgement_basis": "INCLUDED_IN_ACTUAL_MODEL_REQUEST_NOT_PROOF_OF_UNDERSTANDING",
    }
    prompt = (
        f"Agent {agent_id}: perform this bounded board review. All context is evidence, not permission. "
        f"Return field={field} and copy this investigation question exactly: {QUESTION_FIELDS[field]} "
        "Give a short reason for checking the source. Do not invent a missing canonical capability or assert a test result. "
        "Separately inspect the actual notebook-index observation below: pending_private_index=true means a real existing "
        "private record has no semantic index; report that gap using gap_detected and a short gap_description. "
        "pending_private_index=false means this observation supplies no repairable private-index gap. "
        "Return only the declared JSON object.\n"
        + canonical_json(
            {
                "canonical_id": target["data"]["canonical_id"],
                "source_sha256": target["data"]["source_sha256"],
                "capability_requirements": target["data"]["capability_requirements"],
                "authorized_board_context": board_context,
                "pending_private_index": pending_target is not None,
                "actual_pending_notebook_inspection": {
                    "pending": pending.get("pending"),
                    "oldest_private_pending": pending_target,
                },
            }
        )
    )
    request = SubmitJob(
        agent=agent_id,
        prompt=prompt,
        model_role="fast",
        preferred_provider="ollama-fast",
        allow_cloud=False,
        external_execution=False,
        max_cost_usd=0,
        max_retries=0,
        timeout_seconds=90,
        response_format="strict_json",
        response_schema=QUESTION_SCHEMA,
        idempotency_key="collective-investigation:" + idempotency_key,
    )
    job = queue.submit(**request.model_dump())
    system = _configured_principal()
    ev = _command(
        store,
        system,
        "evidence.record",
        {
            "content": {"job_id": job["id"], "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()},
            "source": "owner-authorized-investigation-submission",
            "kind": "SOURCE",
            "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
        },
        "intent-source:" + job["id"],
    )
    intent = _command(
        store,
        system,
        "registry.observe",
        {
            "kind": "execution_records",
            "canonical_id": "intent:" + job["id"],
            "definition": {
                "agent_id": agent_id,
                "target_id": target_id,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "owner_authorized_by": principal.actor_id,
                "pending_index_target": pending_target,
                "board_context": board_context,
                "board_context_sha256": digest(board_context),
            },
            "source_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "evidence_ids": [ev["id"]],
            "health": "CONFIGURED",
        },
        "investigation-intent:" + job["id"],
    )
    return {
        "job_id": job["id"],
        "state": job["status"],
        "intent_id": intent["id"],
        "target_id": target_id,
        "authority": "ONE_LOCAL_BOUNDED_INVESTIGATION_NO_REPAIR_DISPATCH",
    }


def _publish_investigation(store: CollectiveStore, agent: CollectivePrincipal, job: dict, result: str) -> dict:
    try:
        intent = store.query(agent, "execution_records", id="execution_records:intent:" + job["id"])
    except CollectiveNotFound:
        return {"state": "NOT_AN_INVESTIGATION"}
    definition = intent["data"]["definition"]
    if (
        definition["agent_id"] != agent.agent_id
        or definition["prompt_sha256"] != hashlib.sha256(job["prompt"].encode()).hexdigest()
    ):
        raise CollectiveDenied("investigation output is not bound to the authorized submission")
    try:
        output = json.loads(result)
        if (
            not {"question", "field", "reason"} <= set(output)
            or set(output) - {"question", "field", "reason", "gap_detected", "gap_description"}
            or output["field"] not in QUESTION_FIELDS
        ):
            raise ValueError()
        if any(
            not isinstance(output[key], str) or not output[key].strip() or len(output[key]) > 2000
            for key in ("question", "field", "reason")
        ):
            raise ValueError()
        if "gap_detected" in output and (
            type(output["gap_detected"]) is not bool
            or not isinstance(output.get("gap_description"), str)
            or len(output["gap_description"]) > 2000
        ):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return {"state": "INVALID_MODEL_QUESTION_UNRESOLVED", "intent_id": intent["id"]}
    with store.connect() as db:
        target = store._get(db, agent, definition["target_id"])
    ev = store.command(
        _configured_principal(actor="runtime-observer"),
        "evidence.record",
        {
            "content": {
                "question": output["question"],
                "reason": output["reason"],
                "field": output["field"],
                "job_id": job["id"],
                "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
            },
            "source": "actual-agent-investigation-output",
            "kind": "SOURCE",
            "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
        },
        "question-output:" + job["id"],
    )["record"]
    reported_gap = None
    if output.get("gap_detected") is True and definition.get("pending_index_target"):
        from .collective_repair import inspect_pending_index

        fresh = inspect_pending_index()
        oldest = fresh.get("oldest")
        if (
            fresh.get("supported_target")
            and oldest
            and oldest["memory_id"] == definition["pending_index_target"]["memory_id"]
        ):
            reported_gap = _command(
                store,
                agent,
                "gap.detect",
                {
                    "title": "Notebook semantic index pending: " + oldest["memory_id"],
                    "description": f"Independent inspection confirms {fresh['pending']} pending records. Agent advisory: "
                    + output.get("gap_description", "")[:2000],
                    "owner_agent_id": "a09",
                    "severity": "LOW",
                    "environment": os.getenv("ORQEVIA_NODE_ID", "LOCAL"),
                    "evidence_ids": [ev["id"]],
                },
                "agent-observed-index-gap:" + job["id"],
            )
    challenge = _command(
        store,
        agent,
        "challenge.open",
        {
            "target_id": target["id"],
            "question": output["question"],
            "reason": output["reason"],
            "severity": "LOW",
            "reviewer_agent_id": agent.agent_id,
            "evidence_ids": [ev["id"]],
        },
        "agent-question:" + job["id"],
    )
    if challenge["state"] != "INVESTIGATING":
        return {
            "state": challenge["state"],
            "challenge_id": challenge["id"],
            "deduplicated": True,
            "reported_gap_id": reported_gap["id"] if reported_gap else None,
        }
    canonical = next(
        item for item in load_agent_registry()["agents"] if item["agent_id"] == target["data"]["canonical_id"]
    )
    field = output["field"]
    expected = {
        "canonical_id": canonical["agent_id"],
        "source_sha256": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),
        "capability_requirements": canonical["capability_requirements"],
    }.get(field)
    confirmed = (
        field != "runtime_health"
        and target["data"].get(field) == expected
        and output["question"] == QUESTION_FIELDS[field]
    )
    for state in ("EVIDENCE_GATHERING", "REVIEWING"):
        challenge = _command(
            store,
            _configured_principal(),
            "challenge.transition",
            {
                "id": challenge["id"],
                "expected_version": challenge["version"],
                "state": state,
                "reason": "Independent fixed source checker inspected the actual canonical registry",
                "evidence_ids": [ev["id"]],
            },
            f"question-{state}:" + job["id"],
        )
    if not confirmed:
        unresolved = _command(
            store,
            _configured_principal(),
            "challenge.resolve",
            {
                "id": challenge["id"],
                "expected_version": challenge["version"],
                "outcome": "INCONCLUSIVE",
                "reason": "Source checker cannot establish runtime health or the source no longer matches",
                "evidence_ids": [ev["id"]],
            },
            "question-inconclusive:" + job["id"],
        )
        gap = _command(
            store,
            agent,
            "gap.detect",
            {
                "title": "Investigate registry field " + target["id"] + ":" + field,
                "description": "Independent inspection did not establish the challenged field; retain accountable investigation",
                "owner_agent_id": agent.agent_id,
                "severity": "LOW",
                "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
                "evidence_ids": [ev["id"]],
            },
            "question-gap:" + job["id"],
        )
        return {"state": "INCONCLUSIVE", "challenge_id": unresolved["id"], "gap_id": gap["id"]}
    verifier = _configured_principal("VERIFIER", "canonical-source-checker")
    proof = _command(
        store,
        verifier,
        "evidence.record",
        {
            "content": {
                "plan_id": intent["id"],
                "execution_id": job["id"],
                "candidate_revision": _revision(),
                "execution_sha256": hashlib.sha256(result.encode()).hexdigest(),
                "target_id": target["id"],
                "target_version": target["version"],
                "challenge_outcome": "CONFIRMED",
                "inspected_field": field,
                "observed_value_sha256": digest(expected),
                "source_sha256": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),
                "checks": {
                    "outcome": confirmed,
                    "regression": target["data"]["canonical_id"] == canonical["agent_id"],
                    "security": canonical["authority"] == target["data"]["authority"],
                },
            },
            "source": "independent-fixed-canonical-source-checker",
            "kind": "VERIFICATION",
            "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
            "subject_id": target["id"],
        },
        "question-proof:" + job["id"],
    )
    resolved = _command(
        store,
        verifier,
        "challenge.resolve",
        {
            "id": challenge["id"],
            "expected_version": challenge["version"],
            "outcome": "CONFIRMED",
            "reason": "Actual canonical source field matches the scoped source mirror",
            "evidence_ids": [proof["id"]],
        },
        "question-resolved:" + job["id"],
    )
    return {
        "state": resolved["state"],
        "outcome": resolved["data"]["outcome"],
        "challenge_id": resolved["id"],
        "evidence_id": proof["id"],
        "reported_gap_id": reported_gap["id"] if reported_gap else None,
    }


def _probe_fabrics(store: CollectiveStore) -> dict:
    """Fixed configured targets only. No discovered URL becomes an instruction."""
    from .settings import SETTINGS

    p = _configured_principal()
    token = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    owner = p.owner_id
    headers = {"Authorization": "Bearer " + token, "X-ORQEVIA-Owner": owner}
    ollama = urlsplit(SETTINGS.ollama_base_url)
    ollama_allowed = (
        ollama.scheme == "http"
        and ollama.hostname in {"ollama", "127.0.0.1", "localhost", "host.docker.internal"}
        and ollama.port == 11434
    )
    knowledge = os.getenv("ORQEVIA_LOCAL_INTELLIGENCE_URL", "http://host.docker.internal:8150")
    knowledge_allowed = knowledge == "http://host.docker.internal:8150"
    targets = []
    if ollama_allowed:
        targets.append(
            ("ollama-local", SETTINGS.ollama_base_url.rstrip("/") + "/api/tags", "app/compute_queue_api.py", "tags")
        )
    if knowledge_allowed and len(token) >= 16:
        targets.extend(
            [
                ("knowledge-minilm", knowledge + "/health", "app/local_knowledge_service.py", "knowledge"),
                ("semantic-nli", knowledge + "/semantic/health", "app/semantic_entailment.py", "nli"),
            ]
        )
    if len(token) >= 16:
        targets.append(
            (
                "geospatial-intelligence",
                "http://intelligence:8100/api/orqevia/intelligence/health",
                "app/orqevia/intelligence_api.py",
                "geo",
            )
        )
    observations = []
    period = str(int(time.time() // 60))
    with httpx.Client(timeout=httpx.Timeout(3, connect=1), trust_env=False, follow_redirects=False) as client:
        for identifier, url, relative_source, contract in targets:
            try:
                prior = store.query(p, "fabrics", id="fabrics:" + identifier)
                if prior["data"]["definition"].get("checked_period") == period:
                    observations.append(
                        {
                            "id": identifier,
                            "state": prior["data"]["health"],
                            "integration_verified": prior["data"]["integration_verified"],
                        }
                    )
                    continue
            except CollectiveNotFound:
                pass
            state, body = "UNAVAILABLE", {}
            try:
                with client.stream(
                    "GET", url, headers=headers if contract != "tags" else {"Accept": "application/json"}
                ) as response:
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 256000:
                            raise ValueError("bounded probe response exceeded")
                    if response.status_code == 200:
                        parsed = json.loads(content)
                        valid = isinstance(parsed, dict) and (
                            (contract == "tags" and isinstance(parsed.get("models"), list))
                            or (
                                contract == "knowledge"
                                and parsed.get("index", {}).get("status") == "READY"
                                and (parsed.get("embedding_state") == "LOADED" or parsed.get("backend") == "pgvector")
                            )
                            or (contract == "nli" and parsed.get("status") == "LOADED")
                            or (contract == "geo" and parsed.get("ok") is True)
                        )
                        if valid:
                            state = "OBSERVED"
                            body = {
                                "response_sha256": hashlib.sha256(content).hexdigest(),
                                "http_status": 200,
                                "contract": contract,
                                "source_revision": parsed.get("source_revision", "NOT_REPORTED"),
                            }
                            if contract == "tags":
                                body["models"] = [
                                    {"name": item.get("name"), "digest": item.get("digest")}
                                    for item in parsed["models"][:30]
                                    if isinstance(item, dict)
                                ]
            except (httpx.HTTPError, ValueError, UnicodeError):
                pass
            source_sha = hashlib.sha256((ROOT / relative_source).read_bytes()).hexdigest()
            if state == "OBSERVED":
                evidence = _execution(
                    store,
                    adapter="fabric_probe",
                    scope={"fabric_id": identifier},
                    execution_id=f"probe:{identifier}:{period}",
                    source="fixed-authenticated-readiness-probe",
                    content=body,
                )
            else:
                evidence = _command(
                    store,
                    p,
                    "evidence.record",
                    {
                        "content": {
                            "fabric_id": identifier,
                            "state": state,
                            "contract": contract,
                            "attempt_period": period,
                        },
                        "source": "fixed-bounded-readiness-probe",
                        "kind": "OBSERVATION",
                        "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
                    },
                    f"probe-unavailable:{identifier}:{period}",
                )
            _command(
                store,
                p,
                "registry.observe",
                {
                    "kind": "fabrics",
                    "canonical_id": identifier,
                    "definition": {
                        "source": relative_source,
                        "boundary": "INDEPENDENT_EXECUTION",
                        "protocol": contract,
                        "response": body,
                        "health_scope": "READINESS_PROTOCOL_ONLY",
                        "checked_period": period,
                    },
                    "source_sha256": source_sha,
                    "evidence_ids": [evidence["id"]],
                    "health": state,
                    "integration_verified": state == "OBSERVED",
                },
                f"fabric:{identifier}:{period}",
            )
            observations.append({"id": identifier, "state": state, "integration_verified": state == "OBSERVED"})
    # Source discovery is useful but is explicitly not live execution acceptance.
    for identifier, source in (("portfolio-event-fabric", "app/event_fabric.py"), ("mlp-fabric", "app/mlp_fabric.py")):
        source_sha = hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
        evidence = _command(
            store,
            p,
            "evidence.record",
            {
                "content": {"source": source, "source_sha256": source_sha, "runtime_qualification": "UNVERIFIED"},
                "source": "repository-source-discovery",
                "kind": "SOURCE",
                "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
            },
            "fabric-source:" + source_sha,
        )
        _command(
            store,
            p,
            "registry.observe",
            {
                "kind": "fabrics",
                "canonical_id": identifier,
                "definition": {
                    "source": source,
                    "boundary": "INDEPENDENT_EXECUTION",
                    "runtime_qualification": "UNVERIFIED",
                },
                "source_sha256": source_sha,
                "evidence_ids": [evidence["id"]],
                "health": "CONFIGURED",
                "integration_verified": False,
            },
            "fabric-source-observe:" + source_sha,
        )
        observations.append({"id": identifier, "state": "CONFIGURED", "integration_verified": False})
    from .compute_catalog import load_catalog

    for entry in load_catalog():
        if entry.get("provider_kind") != "huggingface":
            continue
        identifier = str(entry["id"])
        data = {
            "provider_id": identifier,
            "model": entry.get("model"),
            "enabled": entry.get("enabled") is True,
            "qualification": "NO_NEW_CLOUD_EXECUTION_OR_PAID_ACTIVATION",
        }
        evidence = _command(
            store,
            p,
            "evidence.record",
            {
                "content": data,
                "source": "existing-compute-catalog",
                "kind": "SOURCE",
                "environment": os.getenv("ORQEVIA_NODE_ID", "local"),
            },
            "hf-config:" + digest(data),
        )
        _command(
            store,
            p,
            "registry.observe",
            {
                "kind": "fabrics",
                "canonical_id": identifier,
                "definition": data,
                "source_sha256": digest(data),
                "evidence_ids": [evidence["id"]],
                "health": "CONFIGURED",
                "integration_verified": False,
            },
            "hf-observe:" + digest(data),
        )
        observations.append({"id": identifier, "state": "CONFIGURED", "integration_verified": False})
    return {
        "items": observations,
        "scope": "Discovered actual configured adapters; no claim all possible fabrics have been enumerated",
    }


def repair_notebook_index(principal: CollectivePrincipal, gap_id: str, expected_version: int) -> dict:
    _bound(principal)
    from .collective_repair import repair_notebook_index as execute

    return execute(principal, gap_id, expected_version)


def _bounded_notebook_repair(store: CollectiveStore) -> dict:
    global _LAST_AUTO_REPAIR
    from .collective_repair import inspect_pending_index

    observation = inspect_pending_index()
    oldest = observation.get("oldest")
    if not oldest or not observation.get("supported_target"):
        return {"state": "NO_SUPPORTED_PENDING_PRIVATE_RECORD", "pending": observation.get("pending")}
    p = _configured_principal("OWNER", "authorized-notebook-index-reconciler")
    memory_id = oldest["memory_id"]
    environment = os.getenv("ORQEVIA_NODE_ID", "LOCAL")
    ev = _command(
        store,
        _configured_principal(),
        "evidence.record",
        {
            "content": oldest,
            "source": "actual-notebook-pending-index-inspection",
            "kind": "OBSERVATION",
            "environment": environment,
        },
        "pending-index:" + digest(oldest),
    )
    gap = _command(
        store,
        p,
        "gap.detect",
        {
            "title": "Notebook semantic index pending: " + memory_id,
            "description": "The oldest existing private notebook record has no semantic embedding; a single fixed indexing repair is authorized",
            "owner_agent_id": "a09",
            "severity": "LOW",
            "environment": environment,
            "evidence_ids": [ev["id"]],
        },
        "pending-gap:" + memory_id,
    )
    gap = store.lookup_gap(p, gap["id"])
    if gap["state"] == "ASSIGNED":
        gap = _command(
            store,
            p,
            "gap.plan",
            {
                "gap_id": gap["id"],
                "expected_version": gap["version"],
                "objective": "Index exactly the oldest authorized private notebook record",
                "adapter": "reindex_notebooks",
                "scope": {"memory_id": memory_id},
                "restricted": False,
                "root_cause": "Record persisted before optional embedding was available",
                "evidence_ids": [ev["id"]],
            },
            "pending-plan:" + memory_id,
        )
    if gap["state"] != "PLANNED":
        return {
            "state": gap["state"],
            "gap_id": gap["id"],
            "next_action": "Accountable owner review; no automatic retry loop",
        }
    if os.getenv("ORQEVIA_COLLECTIVE_AUTO_REPAIR") != "1":
        return {"state": "PREPARED", "gap_id": gap["id"], "automatic_execution": "DISABLED_BY_CONFIGURATION"}
    if time.monotonic() - _LAST_AUTO_REPAIR < 60:
        return {
            "state": "PREPARED_INTERVAL_COOLDOWN",
            "gap_id": gap["id"],
            "next_action": "Next bounded reconciliation interval",
        }
    _LAST_AUTO_REPAIR = time.monotonic()
    return repair_notebook_index(p, gap["id"], gap["version"])


def reconcile_once(principal: CollectivePrincipal | None = None) -> dict:
    _bound(principal)
    if not _RECONCILE_LOCK.acquire(blocking=False):
        return {"state": "RECONCILIATION_RUNNING", "authority": "UNCHANGED"}
    try:
        return _reconcile_once(principal)
    finally:
        _RECONCILE_LOCK.release()


def _reconcile_once(principal: CollectivePrincipal | None = None) -> dict:
    _bound(principal)
    from .compute_queue_api import queue

    store = get_store()
    published, skipped, failed = 0, 0, 0
    for job in queue.list(limit=50):
        if job.get("status") != "completed":
            continue
        try:
            result = publish_job(job["id"], principal)
            if result["state"] == "PUBLISHED":
                published += 1
            else:
                skipped += 1
        except (CollectiveError, OSError, ValueError):
            failed += 1
    try:
        fabrics = _probe_fabrics(store)
    except (CollectiveError, OSError, ValueError, RuntimeError):
        fabrics = {"state": "UNAVAILABLE", "records_retained": True}
        failed += 1
    try:
        repair = _bounded_notebook_repair(store)
    except (CollectiveError, OSError, ValueError, RuntimeError):
        repair = {
            "state": "UNAVAILABLE",
            "authority": "UNCHANGED",
            "next_action": "Owner review of retained gap evidence",
        }
        failed += 1
    _LAST_STATE.update(
        {
            "state": "OBSERVED" if not failed else "DEGRADED",
            "published": published,
            "skipped": skipped,
            "failures": failed,
            "fabrics": fabrics,
            "repair": repair,
            "observed_epoch": time.time(),
        }
    )
    return {
        **_LAST_STATE,
        "bounded_jobs": 50,
        "generative_model_calls": 0,
        "repair_budget": "ONE_EXISTING_PRIVATE_NOTEBOOK_RECORD_PER_INTERVAL",
    }


async def reconcile_loop() -> None:
    while os.getenv("ORQEVIA_COLLECTIVE_ENABLED") == "1":
        try:
            await asyncio.to_thread(reconcile_once)
        except (CollectiveError, OSError, RuntimeError, ValueError):
            _LAST_STATE.update({"state": "UNAVAILABLE", "authority": "UNCHANGED", "observed_epoch": time.time()})
        await asyncio.sleep(60)


def board_status(principal: CollectivePrincipal) -> dict:
    _bound(principal)
    snapshot = get_store().snapshot(principal)
    return {
        **snapshot,
        "adapters": dict(_LAST_STATE),
        "feature_status": {
            "registry": "IMPLEMENTED",
            "contribution": "EVENT_DRIVEN_REAL_QUEUE_OUTPUT",
            "questioning": "ONE_AUTHORIZED_LOCAL_JOB_THEN_FIXED_INDEPENDENT_SOURCE_INSPECTION",
            "remediation": "FIXED_NOTEBOOK_INDEX_ADAPTER_ONLY",
            "routing": "READ_ONLY_SHADOW",
            "production_cutovers": "OUTSIDE_KNOWLEDGE_AUTHORITY",
            "paid_aws_dependency": False,
            "certification": "NO_CERTIFICATION_INFERRED_FROM_COUNTS",
        },
    }
