import pytest

from app.agent_conditioning import BehaviorProfile, BehaviorProfileStore, condition_prompt
from app.agent_notebooks import (
    AgentNotebookStore,
    NotebookPermissionDenied,
    NotebookPrincipal,
)


def embedder(text):
    value = sum(ord(char) for char in text)
    return [float(len(text) % 31 + 1), float(value % 43 + 1), 1.0]


def test_all_registered_agents_receive_durable_private_notebooks(tmp_path):
    store = AgentNotebookStore(tmp_path / "memory.db", embedder=embedder)
    health = store.health(NotebookPrincipal("owner", "OWNER"))
    assert health["agents_discovered"] == 21
    assert health["agents_provisioned"] == 21
    assert health["records"] >= 21


def test_private_memory_isolation_versions_search_and_deletion(tmp_path):
    store = AgentNotebookStore(tmp_path / "memory.db", embedder=embedder)
    owner = NotebookPrincipal("owner", "OWNER")
    a01 = NotebookPrincipal("a01", "AGENT", "a01")
    a02 = NotebookPrincipal("a02", "AGENT", "a02")
    record = store.add_record(
        a01,
        agent_id="a01",
        section="lessons_learned",
        content={"lesson": "Verify evidence identifiers before release."},
        source="test",
        verification_status="verified_execution",
        confidence=1.0,
    )
    assert store.search(a01, "evidence identifiers")["results"][0]["memory_id"] == record["memory_id"]
    with pytest.raises(NotebookPermissionDenied):
        store.get_record(a02, record["memory_id"])
    updated = store.update_record(
        a01,
        record["memory_id"],
        content={"lesson": "Verify evidence identifiers and hashes before release."},
        source="test",
        expected_version=1,
        change_reason="clarified",
    )
    assert updated["version"] == 2
    history = store.version_history(a01, record["memory_id"])
    assert [item["version"] for item in history["versions"]] == [1, 2]
    corrected = store.correct_record(
        a01,
        record["memory_id"],
        content={"lesson": "Corrected lesson."},
        source="correction",
        change_reason="superseded",
    )
    assert corrected["supersedes_id"] == record["memory_id"]
    deleted = store.delete_record(a01, corrected["memory_id"], reason="disposable test")
    assert deleted["deleted_reason"] == "disposable test"
    own_audit = store.health(owner)
    assert own_audit["audit_events"] > 0


def test_conditioning_is_optional_and_cannot_override_task(tmp_path):
    store = AgentNotebookStore(tmp_path / "memory.db", embedder=embedder)
    profiles = BehaviorProfileStore(store)
    base = "ROLE AND SAFETY REQUIREMENTS\nReturn exact evidence."
    assert condition_prompt(base, "a02", profiles) == base
    profiles.set(
        "a02",
        BehaviorProfile(enabled=True, decision_style="analytical", mbti_tag="INTJ"),
        updated_by="owner",
    )
    prompt = condition_prompt(base, "a02", profiles)
    assert prompt.startswith("OPTIONAL BEHAVIORAL CONDITIONING")
    assert "SUBORDINATE TO SYSTEM, SECURITY, PERMISSIONS, EVIDENCE AND TASK" in prompt
    assert "Upstream MBTI-in-Thoughts priming" in prompt
    assert "strategic mindset and high intellectual capacity" in prompt
    assert "Upstream profile excerpt bounded for context budget." in prompt
    assert "End upstream priming" in prompt
    assert prompt.endswith(base)
    profiles.set(
        "a02",
        BehaviorProfile(enabled=False, decision_style="analytical", mbti_tag="INTJ"),
        updated_by="owner",
    )
    assert condition_prompt(base, "a02", profiles) == base


def test_project_and_organization_scopes_are_owner_governed_and_isolated(tmp_path):
    store = AgentNotebookStore(tmp_path / "memory.db", embedder=embedder)
    owner = NotebookPrincipal("owner", "OWNER")
    a01 = NotebookPrincipal("a01", "AGENT", "a01")
    a02 = NotebookPrincipal("a02", "AGENT", "a02")
    a04 = NotebookPrincipal("a04", "AGENT", "a04")
    store.project_create(owner, "PROJECT-ORQ-1", "Shared ORQ project")
    store.project_grant(owner, "PROJECT-ORQ-1", "a01", "write")
    store.project_grant(owner, "PROJECT-ORQ-1", "a02", "read")
    store.project_grant(owner, "PROJECT-ORQ-1", "a04", "read")
    record = store.add_record(
        a01,
        agent_id="a01",
        section="lessons_learned",
        content={"lesson": "Shared project evidence is available to approved readers."},
        source="project-test",
        scope="project",
        project_id="PROJECT-ORQ-1",
        verification_status="verified_execution",
    )
    assert store.get_record(a02, record["memory_id"])["project_id"] == "PROJECT-ORQ-1"
    assert store.get_record(a04, record["memory_id"])["project_id"] == "PROJECT-ORQ-1"
    with pytest.raises(NotebookPermissionDenied):
        store.add_record(
            a02,
            agent_id="a02",
            section="lessons_learned",
            content={"lesson": "Read-only members cannot write."},
            source="project-test",
            scope="project",
            project_id="PROJECT-ORQ-1",
        )
    projects = store.project_list(owner)
    assert projects["projects"][0]["member_count"] == 3
    organization = store.add_record(
        owner,
        agent_id="a01",
        section="lessons_learned",
        content={"lesson": "Approved organization knowledge is shared."},
        source="owner-test",
        scope="organization",
        verification_status="verified_execution",
    )
    assert store.get_record(a02, organization["memory_id"])["scope"] == "organization"
    with pytest.raises(ValueError):
        store.add_record(
            owner,
            agent_id="a01",
            section="lessons_learned",
            content={"lesson": "Unverified organization knowledge is rejected."},
            source="owner-test",
            scope="organization",
            verification_status="unverified",
        )
