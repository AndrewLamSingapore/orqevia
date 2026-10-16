import json
import subprocess
import sys

import pytest

from app.scaffolding import (
    SCAFFOLD_VERSION,
    ScaffoldError,
    ScaffoldResult,
    ScaffoldingEngine,
    generate_agent,
    generate_geospatial_app,
    generate_gods_eye_adapter,
    generate_infrastructure,
    generate_knowledge_app,
    generate_project,
    generate_skill,
    generate_verification,
    materialize,
    plan_repair,
    scan_secrets,
    validate_spec,
)


def test_project_generation_and_materialization(tmp_path):
    result = generate_project({"name": "Demo App", "port": 8080})
    assert result.kind == "project"
    assert "backend/app.py" in result.files
    assert "frontend/index.html" in result.files
    assert "backend/db/migrations/0001_init.sql" in result.files
    assert "deploy/Dockerfile" in result.files

    written = materialize(result, str(tmp_path / "demo"))
    assert len(written) == len(result.files)
    app_cfg = json.loads((tmp_path / "demo" / "config" / "app.json").read_text())
    assert app_cfg["port"] == 8080
    assert app_cfg["scaffold"]["engine"] == "orqevia.scaffolding"


def test_agent_defaults_are_fail_closed(tmp_path):
    result = generate_agent(
        {
            "agent_id": "a99",
            "name": "Builder",
            "role": "implementation",
            "capabilities": ["implement"],
            "tools": ["editor"],
        }
    )
    spec = json.loads(result.files["agents/a99/agent.json"])
    assert spec["execution_authority"] == "none"
    assert spec["advisory_only"] is True
    assert spec["human_approval"] == "required_for_execution"
    assert spec["delegation_rules"]["allow_delegation"] is False
    # A generated agent must never grant itself execution authority.
    materialize(result, str(tmp_path / "agent"))


def test_agent_id_and_spec_validation():
    with pytest.raises(ScaffoldError):
        generate_agent({"agent_id": "BAD ID!", "name": "x", "role": "y", "capabilities": ["z"]})
    with pytest.raises(ScaffoldError):
        validate_spec({}, {"name": {"type": "str", "required": True}})
    with pytest.raises(ScaffoldError):
        validate_spec({"name": 3}, {"name": {"type": "str", "required": True}})


def test_skill_generation(tmp_path):
    result = generate_skill(
        {"skill_id": "research.internet", "name": "Internet research", "description": "Fetch pages"}
    )
    spec = json.loads(result.files["skills/research.internet/skill.json"])
    assert spec["authority"] == "advisory_only"
    assert spec["required_tools"] == []
    materialize(result, str(tmp_path / "skill"))


def test_knowledge_geospatial_and_gods_eye_factories(tmp_path):
    rag = generate_knowledge_app({"app_name": "Docs QA"})
    assert "docs-qa/access_control.py" in rag.files

    geo = generate_geospatial_app({"app_name": "Map Service"})
    assert "map-service/spatial_schema.sql" in geo.files
    assert "map-service/crs.py" in geo.files

    eye = generate_gods_eye_adapter({"app_name": "Situational"})
    adapter = json.loads(eye.files["situational/adapter.json"])
    assert adapter["mode"] == "read_only"
    assert adapter["fail_closed"] is True
    materialize(rag, str(tmp_path / "rag"))
    materialize(geo, str(tmp_path / "geo"))
    materialize(eye, str(tmp_path / "eye"))


def test_infrastructure_and_verification_factories():
    infra = generate_infrastructure({"service_name": "core", "port": 8443})
    assert "core/docker-compose.yml" in infra.files
    assert "core/rollback.md" in infra.files

    verify = generate_verification({"target_name": "orqevia"})
    assert "orqevia/tests/test_security.py" in verify.files
    assert "orqevia/tests/test_recovery.py" in verify.files


def test_materialize_refuses_overwrite_and_traversal(tmp_path):
    result = generate_project({"name": "A"})
    materialize(result, str(tmp_path / "out"))
    with pytest.raises(ScaffoldError):
        materialize(result, str(tmp_path / "out"))

    result.files["../escape.txt"] = "x"  # type: ignore[misc]
    with pytest.raises(ScaffoldError):
        materialize(result, str(tmp_path / "out2"))


def test_secret_scan_rejects_credentials():
    assert scan_secrets("aws_key = AKIAIOSFODNN7EXAMPLE") == ["aws_access_key"]
    assert scan_secrets("password = 'correct horse battery staple'") == []
    with pytest.raises(ScaffoldError):
        generate_project({"name": "Leak", "description": "api_key = 'AKIAIOSFODNN7EXAMPLE'"})


def test_repair_plan_is_read_only(tmp_path):
    (tmp_path / "src.py").write_text("x = 1\n")
    plan = plan_repair(str(tmp_path))
    assert "src.py" in plan
    assert (tmp_path / "src.py").read_text() == "x = 1\n"
    with pytest.raises(ScaffoldError):
        plan_repair(str(tmp_path / "missing"))


def test_fingerprint_is_deterministic():
    a = generate_project({"name": "A"})
    b = generate_project({"name": "A"})
    assert a.fingerprint() == b.fingerprint()


def test_engine_facade_and_version():
    engine = ScaffoldingEngine()
    assert engine.name == "orqevia.scaffolding"
    assert engine.version == SCAFFOLD_VERSION
    result = engine.project({"name": "Via Facade"})
    assert result.template_version == SCAFFOLD_VERSION


def test_generated_at_is_per_instance():
    from dataclasses import MISSING
    from datetime import datetime

    field_info = ScaffoldResult.__dataclass_fields__["generated_at"]
    # Regression: the timestamp must be produced per instance by a
    # default_factory, not frozen once at class-definition time (which shared
    # a single import-time timestamp across every generated artifact).
    assert field_info.default_factory is not MISSING
    assert field_info.default is MISSING

    first = ScaffoldResult(kind="probe", artifact_id="a", files={})
    second = ScaffoldResult(kind="probe", artifact_id="b", files={})
    datetime.fromisoformat(first.generated_at)
    datetime.fromisoformat(second.generated_at)


def test_generated_project_self_test_imports_handler():
    result = generate_project({"name": "Self Test"})
    test_module = result.files["tests/test_app.py"]
    assert "from backend.app import PORT, Handler" in test_module
    assert "callable(Handler)" in test_module
    assert "import urllib.request" not in test_module


def test_scaffolded_acceptance_application_end_to_end(tmp_path):
    project = generate_project({"name": "Acceptance App", "port": 8099})
    agent = generate_agent(
        {
            "agent_id": "acceptance-reviewer",
            "name": "Acceptance Reviewer",
            "role": "review",
            "capabilities": ["review"],
            "tools": ["editor"],
        }
    )
    skill = generate_skill(
        {"skill_id": "review.acceptance", "name": "Acceptance review", "description": "Review candidate artifacts"}
    )

    project_dir = tmp_path / "project"
    agent_dir = tmp_path / "agent"
    skill_dir = tmp_path / "skill"
    materialize(project, str(project_dir))
    materialize(agent, str(agent_dir))
    materialize(skill, str(skill_dir))

    # The scaffolded applications' own test suites must pass.
    for label, cwd in (("project", project_dir), ("agent", agent_dir), ("skill", skill_dir)):
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert run.returncode == 0, f"{label} generated tests failed:\n{run.stdout}\n{run.stderr}"

    # Fail-closed safety properties hold across generated artifacts.
    agent_spec = json.loads((agent_dir / "agents" / "acceptance-reviewer" / "agent.json").read_text(encoding="utf-8"))
    assert agent_spec["execution_authority"] == "none"
    assert agent_spec["advisory_only"] is True
    assert agent_spec["human_approval"] == "required_for_execution"
    assert agent_spec["tools"] == ["editor"]
    assert agent_spec["permissions"] == []

    skill_spec = json.loads((skill_dir / "skills" / "review.acceptance" / "skill.json").read_text(encoding="utf-8"))
    assert skill_spec["authority"] == "advisory_only"
    assert skill_spec["required_tools"] == []

    # No generated file may embed credential-like content.
    for result in (project, agent, skill):
        for name, content in result.files.items():
            assert scan_secrets(content) == [], f"secret-like content in {name}"

