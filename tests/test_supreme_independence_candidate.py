"""LAB contract only: simulated dependency loss, not a physical Black Start claim."""

from app.agent_dispatch_api import user_facing_contract
from app.agent_registry import load_agent_registry, registered_agent_ids
from app.memory import MemoryStore
from app.offline_survival import CapabilityState, OfflineSurvival, QueueState
from app.routing_policy import RoutingPolicy
from app.tier_router import Backend, Tier, select_route


def test_local_control_plane_survives_simulated_external_dependency_loss(tmp_path):
    # Simulated unavailable dependencies: Internet, GitHub, OpenAI, ChatGPT and
    # Codex are represented by the absence of every cloud backend and by an
    # explicit offline observation. This test never changes host networking.
    local = Backend("ollama-fast", "fixture-local-model", Tier.NANO, "local", available=True)
    route = select_route(
        (local,),
        minimum_tier=Tier.NANO,
        classification="LOCAL_ONLY",
        text="private local objective",
        provider_authorized=False,
        disclosure_authorized=False,
        cost_authorized=False,
    )
    assert route.state == "READY"
    assert route.backend == local
    assert route.grants_execution_authority is False

    policy = RoutingPolicy().decide(
        deterministic_satisfied=False,
        local_confidence=None,
        frontier_allowed=False,
        frontier_available=False,
    )
    assert policy.selected_stage == "local_ai"
    assert policy.frontier_allowed is False

    registry = load_agent_registry()
    assert len(registry["agents"]) == 21
    assert len(registry["responsibility_coverage"]) == 29
    assert "prime" in registered_agent_ids()

    memory = MemoryStore(str(tmp_path / "memory.db"))
    memory.put_governed(
        memory_class="semantic",
        key="offline-contract",
        value={"identity": "JARVIS", "authority": "preserved"},
        authority="prime",
    )
    assert memory.search("offline JARVIS authority")[0]["value"]["record"]["identity"] == "JARVIS"

    survival = OfflineSurvival(tmp_path / "offline-queue.db")
    assert survival.observe(network=False, provider=False) is CapabilityState.OFFLINE
    operation = survival.enqueue(
        objective_id="lab-offline-objective",
        operation_type="github.push",
        payload_ref="artifact://candidate/1",
        idempotency_key="lab-offline-objective:github.push",
        authorization_ref="owner:preserved",
        payload={"candidate_sha": "fixture"},
    )
    assert operation.state is QueueState.DEFERRED_OFFLINE
    executed = []
    assert survival.reconcile(
        executors={"github.push": lambda item: executed.append(item.id) or {"accepted": True}},
        authority_valid=lambda _item: True,
    ) == []
    assert executed == []

    chinese = user_facing_contract("你叫什么名字？")
    assert "JARVIS" in chinese
    assert "Simplified Chinese" in chinese


def test_cloud_fallback_stays_fail_closed_when_local_capacity_is_busy():
    local = Backend("ollama-fast", "fixture-local-model", Tier.NANO, "local", available=True)
    route = select_route(
        (local,),
        minimum_tier=Tier.NANO,
        classification="CLOUD_PERMITTED",
        text="public but not authorized for external disclosure",
        local_saturated=True,
        provider_authorized=False,
        disclosure_authorized=False,
        cost_authorized=False,
    )
    assert route.state == "QUEUED"
    assert route.backend == local
    assert route.grants_execution_authority is False
