from decimal import Decimal

from app import project_workflows
from app.project_workflows import (
    FinancialInputs,
    ProjectWorkflowRequest,
    ProjectWorkflowService,
    ProjectWorkflowStore,
    ScenarioParameters,
    calculate_financials,
    load_template,
    _prior_context,
)


INPUTS = FinancialInputs(
    revenue=50000,
    rent=8000,
    salaries=18000,
    inventory=12000,
    utilities=2000,
    marketing=3000,
    other_expenses=2000,
)


class CompletedQueue:
    def __init__(self):
        self.jobs = {}

    def submit(self, **kwargs):
        import uuid

        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "agent": kwargs["agent"],
            "status": "completed",
            "result": f"completed contribution from {kwargs['agent']}",
            "provider": "test-local",
            "model": kwargs.get("model") or "test-model",
            "started_at": "2026-10-20T00:00:00+00:00",
            "completed_at": "2026-10-20T00:00:01+00:00",
            "input_tokens": 10,
            "output_tokens": 5,
            "error": "",
        }
        self.jobs[job_id] = job
        return job

    def get(self, job_id):
        return self.jobs[job_id]

    def cancel(self, job_id):
        self.jobs[job_id]["status"] = "cancelled"
        return self.jobs[job_id]


def test_template_has_exactly_one_task_per_registered_agent():
    template = load_template()
    assert len(template["tasks"]) == 21
    assert len({item["agent_id"] for item in template["tasks"]}) == 21


def test_financial_calculation_is_reproducible():
    result = calculate_financials(INPUTS, ScenarioParameters())
    assert Decimal(str(result["baseline"]["total_expenses"])) == Decimal("45000")
    assert Decimal(str(result["baseline"]["monthly_profit"])) == Decimal("5000")
    assert Decimal(str(result["baseline"]["net_margin_percent"])) == Decimal("10")
    assert result["ranking"] == ["S3", "S2", "S1"]
    scenarios = {item["scenario_id"]: item for item in result["scenarios"]}
    assert scenarios["S1"]["monthly_profit"] == 6200
    assert scenarios["S2"]["monthly_profit"] == 7440
    assert scenarios["S3"]["monthly_profit"] == 8736


def test_review_context_is_compressed_and_release_gate_is_fast():
    template = load_template()
    roles = {item["agent_id"]: item["model_role"] for item in template["tasks"]}
    assert roles["a26"] == "deep"
    assert roles["a29"] == "fast"
    tasks = [
        {
            "agent_id": f"a{index:02d}",
            "phase": 1,
            "status": "completed",
            "result_sha256": f"hash-{index}",
            "result": "# " + ("long analysis " * 200),
        }
        for index in range(1, 20)
    ] + [
        {
            "agent_id": "a26",
            "phase": 2,
            "status": "completed",
            "result_sha256": "review-hash",
            "result": "PASS with one caveat " * 100,
        }
    ]
    context = _prior_context(tasks, 3)
    assert len(context) <= 6500
    assert "review-hash" in context
    assert "hash-1" not in context


def test_workflow_store_is_idempotent(tmp_path):
    store = ProjectWorkflowStore(tmp_path / "workflow.db")
    request = ProjectWorkflowRequest(
        project_key="ORQ-T1",
        title="Test business analysis",
        idempotency_key="test-run-0001",
        inputs=INPUTS,
    )
    template = load_template()
    financials = calculate_financials(INPUTS, ScenarioParameters())
    first = store.create(request, actor="owner", template=template, financials=financials)
    second = store.create(request, actor="owner", template=template, financials=financials)
    assert first["run_id"] == second["run_id"]
    assert len(store.tasks(first["run_id"])) == 21


def test_worker_executes_all_agents_and_marks_restart_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_MEMORY_DB", str(tmp_path / "agent-memory.db"))
    fake = CompletedQueue()
    monkeypatch.setattr(project_workflows, "_live_queue", lambda: fake)
    store = ProjectWorkflowStore(tmp_path / "workflow.db")
    service = ProjectWorkflowService(store=store)
    request = ProjectWorkflowRequest(
        project_key="ORQ-T2",
        title="Executable workflow test",
        idempotency_key="test-run-0002",
        inputs=INPUTS,
    )
    run = store.create(
        request,
        actor="owner",
        template=service.template,
        financials=calculate_financials(INPUTS, ScenarioParameters()),
    )
    service._advance(run["run_id"])
    status = service.status(run["run_id"])
    assert status["state"] == "AWAITING_RESTART_VERIFICATION"
    assert status["summary"]["completed"] == 21
    assert status["summary"]["handoffs"] == 21
    assert len(status["artifacts"]) == 6
    verified = service.verify_restart(
        run["run_id"],
        before="2026-10-20T00:00:00+00:00",
        after="2026-10-20T00:01:00+00:00",
    )
    assert verified["state"] == "COMPLETED"
    verification = next(item for item in verified["artifacts"] if item["name"].endswith("verification.md"))
    path = service.artifact_path(run["run_id"], verification["name"])
    assert "**Verdict:** **PASS**" in path.read_text(encoding="utf-8")


def test_workflow_rejects_unknown_template():
    try:
        ProjectWorkflowRequest(
            template_id="arbitrary.prompt.v1",
            project_key="ORQ-T3",
            title="Invalid template",
            idempotency_key="test-run-0003",
            inputs=INPUTS,
        )
    except ValueError:
        return
    raise AssertionError("unknown workflow template must be rejected")
