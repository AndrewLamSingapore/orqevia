import time

import pytest

from app.agent_dispatch_api import user_facing_contract
from app.agent_registry import load_agent_registry
from app.capability_router import CapabilityBackend, select_capability_route
from app.governed_knowledge import AccessContext, GovernedKnowledgeStore, MemoryClass, Scope
from app.independence_matrix import COMPONENTS, dependency_loss_matrix
from app.offline_survival import CapabilityState, OfflineSurvival, QueueState
from app.supreme_integration import IntegrationEnvelope, authorize_tool


OWNER = AccessContext("OWNER", "lam", "household-1")


def test_every_dependency_loss_has_separate_complete_truthful_classification():
    matrix = dependency_loss_matrix()
    assert [item.name for item in matrix] == [
        "cloud_ai_unavailable", "github_unavailable", "preferred_local_model_unavailable",
        "rag_unavailable", "optional_tool_unavailable", "internet_unavailable",
    ]
    for item in matrix:
        item.validate()
        assert set(item.results) == set(COMPONENTS)
        assert "FAILED" not in item.results.values()
        assert item.physical_black_start is False


def test_identity_authority_registry_memory_and_lan_survive_external_loss(tmp_path):
    assert len(load_agent_registry()["agents"]) == 21
    memory = GovernedKnowledgeStore(tmp_path / "memory.db")
    row = memory.write(context=OWNER, memory_key="jarvis.identity", memory_class=MemoryClass.FACT, scope=Scope.OWNER_PRIVATE, scope_id="lam", value={"identity": "JARVIS"}, source="local-policy", source_version="1", source_authority="OWNER", verification_ref="local:identity", write_request_id="identity:1")
    assert GovernedKnowledgeStore(tmp_path / "memory.db").get(row["record_id"], context=OWNER)["value"]["identity"] == "JARVIS"
    assert "JARVIS" in user_facing_contract("你叫什么名字？")
    now = time.time()
    member = IntegrationEnvelope("t", "r", "wife", "MEMBER", "household-1", "1.0", now, now + 60, "i", frozenset({"task.submit"}))
    assert not authorize_tool(member, permission="owner.admin", model_claimed_role="OWNER")


def test_cloud_loss_never_enables_private_cloud_fallback():
    backends = (
        CapabilityBackend("local-1b", "gemma3:1b", "local", 1.885, frozenset({"reasoning"}), available=True),
        CapabilityBackend("cloud", "cloud-model", "cloud", 1.0, frozenset({"reasoning"}), available=False),
    )
    route = select_capability_route(backends, capability="reasoning", classification="RESTRICTED")
    assert route.state == "READY" and route.backend.location == "local"
    assert route.grants_execution_authority is False


def test_preferred_local_model_loss_degrades_only_to_verified_capability():
    backends = (
        CapabilityBackend("local-1b", "gemma3:1b", "local", 1.885, frozenset({"reasoning"}), available=True),
        CapabilityBackend("local-4b", "gemma3:4b", "local", 6.429, frozenset({"reasoning", "tool_selection"}), available=False),
    )
    assert select_capability_route(backends, capability="reasoning", classification="LOCAL_ONLY").backend.model == "gemma3:1b"
    assert select_capability_route(backends, capability="tool_selection", classification="LOCAL_ONLY").state == "UNAVAILABLE"


def test_internet_loss_persists_work_and_reopen_does_not_lose_it(tmp_path):
    path = tmp_path / "queue.db"
    queue = OfflineSurvival(path)
    assert queue.observe(network=False, provider=False) is CapabilityState.OFFLINE
    operation = queue.enqueue(objective_id="o1", operation_type="github.push", payload_ref="artifact://candidate", idempotency_key="o1:push", authorization_ref="owner:valid", payload={"sha": "abc"})
    assert operation.state is QueueState.DEFERRED_OFFLINE
    assert OfflineSurvival(path).get(operation.id).payload_digest == operation.payload_digest


def test_restore_revalidates_then_executes_once_with_receipt(tmp_path):
    queue = OfflineSurvival(tmp_path / "queue.db")
    queue.observe(network=False, provider=False)
    operation = queue.enqueue(objective_id="o1", operation_type="github.push", payload_ref="artifact://candidate", idempotency_key="o1:push", authorization_ref="owner:valid", payload={"sha": "abc"})
    assert queue.observe(network=True, provider=True) is CapabilityState.RECONNECTING
    assert queue.confirm_online() is CapabilityState.ONLINE
    effects = []
    results = queue.reconcile(executors={"github.push": lambda item: effects.append(item.id) or {"accepted": True, "remote_sha": "abc"}}, authority_valid=lambda item: item.authorization_ref == "owner:valid", still_relevant=lambda _item: True, remote_applied=lambda _item: False)
    assert len(results) == 1 and results[0].state is QueueState.RECONCILED
    assert results[0].receipt == {"remote_sha": "abc"}
    assert effects == [operation.id]
    assert queue.reconcile(executors={}, authority_valid=lambda _item: True) == []


@pytest.mark.parametrize("mode,expected", [("authority", QueueState.SUPERSEDED), ("stale", QueueState.SUPERSEDED), ("applied", QueueState.RECONCILED), ("expired", QueueState.EXPIRED)])
def test_restore_does_not_blindly_replay_invalid_or_duplicate_work(tmp_path, mode, expected):
    now = 1000.0
    queue = OfflineSurvival(tmp_path / f"{mode}.db")
    queue.observe(network=False, provider=False)
    operation = queue.enqueue(objective_id=mode, operation_type="github.push", payload_ref="artifact://candidate", idempotency_key=f"{mode}:push", authorization_ref="owner:old", payload={"sha": "abc"}, now=now, expires_at=now - 1 if mode == "expired" else now + 100)
    queue.observe(network=True, provider=True); queue.confirm_online()
    effects = []
    results = queue.reconcile(executors={"github.push": lambda item: effects.append(item.id) or {"accepted": True}}, authority_valid=lambda _item: mode != "authority", still_relevant=lambda _item: mode != "stale", remote_applied=lambda _item: mode == "applied", now=now)
    final = queue.get(operation.id)
    assert final.state is expected
    assert effects == []
    if mode == "applied":
        assert results[0].receipt["already_applied"] is True


def test_rag_or_optional_tool_loss_is_explicit_not_fabricated(tmp_path):
    queue = OfflineSurvival(tmp_path / "queue.db")
    queue.observe(network=True, provider=False)
    for objective, operation_type in (("rag", "external.api"), ("tool", "notification.send")):
        queue.enqueue(objective_id=objective, operation_type=operation_type, payload_ref=f"deferred://{objective}", idempotency_key=f"{objective}:1", authorization_ref="member:valid", payload={"reason": "dependency unavailable"})
    calls = []
    results = queue.reconcile(executors={"external.api": lambda item: calls.append(item.id) or {"accepted": True}, "notification.send": lambda item: calls.append(item.id) or {"accepted": True}}, authority_valid=lambda _item: True, dependency_available=lambda _item: False)
    assert {item.state for item in results} == {QueueState.DEFERRED_OFFLINE}
    assert calls == []
