import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("benchmark_local_models", ROOT / "scripts" / "benchmark_local_models.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_builtin_tasks_cover_required_supreme_dimensions_without_storing_answers():
    tasks = MODULE.validate_tasks(MODULE.DEFAULT_TASKS)
    assert {task["category"] for task in tasks} == {
        "reasoning", "coding", "structured_output", "chinese", "english", "tool_selection", "retrieval", "verification"
    }
    source = (ROOT / "scripts" / "benchmark_local_models.py").read_text(encoding="utf-8")
    assert '"response": answer' not in source


@pytest.mark.parametrize(
    ("category", "answer", "passed"),
    [
        ("structured_output", '{"decision":"BLOCKED","reason":"one check failed"}', True),
        ("structured_output", "not json", False),
        ("chinese", "我是 ORQEVIA，很高兴为你服务。", True),
        ("chinese", "I am ORQEVIA.", False),
        ("verification", "The claim is incorrect; the correct product is 102.", True),
    ],
)
def test_scoring_is_deterministic_and_language_aware(category, answer, passed):
    task = next(item for item in MODULE.DEFAULT_TASKS if item["category"] == category)
    result, failures = MODULE.score_answer(task, answer)
    assert result is passed
    assert bool(failures) is (not passed)


def test_task_validation_fails_closed_on_malformed_input():
    with pytest.raises(SystemExit):
        MODULE.validate_tasks([])
    with pytest.raises(SystemExit):
        MODULE.validate_tasks([{"category": "reasoning"}])
    with pytest.raises(SystemExit):
        MODULE.validate_tasks([{"category": "reasoning", "prompt": "vacuous"}])


def test_report_contract_names_truthful_resource_scope():
    source = (ROOT / "scripts" / "benchmark_local_models.py").read_text(encoding="utf-8")
    for value in ("host_cpu", "host_ram", "not measured by this container-local harness", "ollama_api_timing"):
        assert value in source
    assert "tokens_per_second" in source
    assert "error_type" in source
    assert '"error": str(error)' not in source


def test_active_benchmark_uses_current_product_identity():
    tasks = MODULE.validate_tasks(MODULE.DEFAULT_TASKS)
    for task in tasks:
        assert 'JARVIS' not in task['prompt']
        assert 'PRIME' not in task['prompt']
    identity_tasks = [task for task in tasks if task['category'] in {'chinese', 'english'}]
    assert len(identity_tasks) == 2
    for task in identity_tasks:
        assert 'ORQEVIA' in task['prompt']
        assert 'orqevia' in task['must_include']
        assert MODULE.score_answer(task, 'I am JARVIS. ?? JARVIS?')[0] is False
