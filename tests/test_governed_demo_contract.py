from pathlib import Path

from app.agent_runtime import AgentAuthorityRuntime
from app.orchestration import has_consequential_intent


SCRIPT = Path("scripts/run-governed-demo.ps1").read_text(encoding="utf-8")
INTENT = "Analyze the JARVIS runtime authority architecture and identify one read-only operational integrity check for its governed agent path."
CONTEXT = "Local verification only. Reasoning and inspection only."


def test_demo_intent_is_non_consequential():
    assert has_consequential_intent(INTENT, CONTEXT) is False


def test_demo_routes_through_engineering_architecture_agent(tmp_path):
    runtime = AgentAuthorityRuntime(tmp_path / "authority.db")
    assert runtime.resolve_path("engineering", INTENT) == ["a15", "a16"]


def test_demo_operator_enforces_safe_contract():
    assert 'department = "engineering"' in SCRIPT
    assert 'allow_frontier = $false' in SCRIPT
    assert 'deep = $false' in SCRIPT
    assert 'executed_external_action -ne $false' in SCRIPT
    assert 'approval_required -ne $false' in SCRIPT
    assert '/api/cognitive/reason' in SCRIPT
    assert 'https://authority-engine-app.vercel.app/api/jarvis-agent-trace' in SCRIPT
    assert '$response.evaluation.released' in SCRIPT
    assert '$terminal.gate.decision' in SCRIPT
    assert 'release-gate metadata' in SCRIPT
    assert 'No evaluator rationale, prompt, model answer, claim text or evidence text was published.' in SCRIPT
