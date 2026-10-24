"""Exercise real processes, failure oracles, cancellation and evidence tampering."""

import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from app.repository_evaluation import Check, evaluate, inspect_repository, run_check, verify_receipt


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "product"
    root.mkdir()
    (root / "app.py").write_text("value = 42\n", encoding="utf-8")
    for argv in (("init",), ("add", "app.py"),
                 ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, timeout=15)
    return root


def command(name, code, timeout=5, **kwargs):
    return Check(name, (sys.executable, "-c", code), timeout, **kwargs)


def test_real_check_and_separate_evidence_verification(repository, tmp_path):
    result = evaluate(repository, tmp_path / "evidence", (command("numeric-oracle", "assert 6*7 == 42; print('PASS')"),))
    assert result["status"] == "PASS"
    directory = Path(result["directory"])
    assert verify_receipt(directory)["status"] == "PASS"
    (directory / "numeric-oracle.log").write_text("altered evidence\n")
    assert "evidence_mismatch:numeric-oracle:log" in verify_receipt(directory)["errors"]


def test_nonzero_exit_cannot_be_overridden_by_printed_pass(repository, tmp_path):
    result = evaluate(repository, tmp_path / "evidence", (command("failed-test", "print('PASS'); raise SystemExit(2)"),))
    assert result["status"] == "FAIL"
    receipt = json.loads(Path(result["directory"], "execution.json").read_text())
    assert receipt["checks"][0]["exit_code"] == 2


def test_junit_cases_overrule_successful_process_exit(repository, tmp_path):
    output = tmp_path / "check"
    output.mkdir()
    xml = output / "tests.xml"
    code = f"from pathlib import Path; Path({str(xml)!r}).write_text('<testsuite tests=\"99\" failures=\"0\"><testcase name=\"broken\"><failure>wrong answer</failure></testcase></testsuite>')"
    check = run_check(repository, output, command("dishonest-counter", code, junit=xml.name))
    assert check["exit_code"] == 0 and check["status"] == "FAIL"
    assert check["test_counts"] == {"tests": 1, "failed": 1, "skipped": 0}


def test_timeout_terminates_real_process(repository, tmp_path):
    check = run_check(repository, tmp_path, command("slow-tool", "import time; time.sleep(60)", timeout=0.2))
    assert check["status"] == "TIMED_OUT" and check["exit_code"] != 0
    assert check["seconds"] < 10


def test_cancellation_stops_real_running_tool(repository, tmp_path):
    cancellation = threading.Event()
    timer = threading.Timer(0.2, cancellation.set)
    timer.start()
    try:
        result = run_check(repository, tmp_path, command("cancelled-tool", "import time; time.sleep(60)"), cancel=cancellation)
    finally:
        timer.cancel()
    assert result["status"] == "CANCELLED" and result["seconds"] < 10


def test_pre_cancelled_check_does_not_execute(repository, tmp_path):
    cancellation = threading.Event()
    cancellation.set()
    target = tmp_path / "must-not-exist"
    result = run_check(repository, tmp_path, command("cancelled-before-start", f"from pathlib import Path; Path({str(target)!r}).touch()"), cancel=cancellation)
    assert result["status"] == "CANCELLED" and not target.exists()


def test_inherited_credentials_are_absent(repository, tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_TEST_PRIVATE_CREDENTIAL", "fixture-only")
    check = command("credential-isolation", "import os; assert 'ORQEVIA_TEST_PRIVATE_CREDENTIAL' not in os.environ")
    assert run_check(repository, tmp_path, check)["status"] == "PASS"


def test_tracked_mutation_invalidates_release_evidence(repository, tmp_path):
    check = command("mutating-check", "from pathlib import Path; Path('app.py').write_text('value = 0\\n')")
    result = evaluate(repository, tmp_path / "evidence", (check,))
    assert result["status"] == "FAIL"
    assert "repository_changed_during_checks" in verify_receipt(Path(result["directory"]))["errors"]


def test_missing_tool_is_unavailable(repository, tmp_path):
    result = run_check(repository, tmp_path, Check("missing-tool", (str(tmp_path / "no-such-program"),)))
    assert result["status"] == "UNAVAILABLE" and result["exit_code"] is None


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, 1801])
def test_unbounded_timeout_is_rejected(timeout):
    with pytest.raises(ValueError):
        Check("test", (sys.executable,), timeout)


def test_only_selected_owning_root_is_accepted(repository):
    child = repository / "subdirectory"
    child.mkdir()
    with pytest.raises(ValueError, match="owning repository root"):
        inspect_repository(child)


def test_distinct_runs_preserve_original_receipts(repository, tmp_path):
    check = command("oracle", "print(42)")
    a = evaluate(repository, tmp_path / "evidence", (check,))
    original = Path(a["directory"], "execution.json").read_bytes()
    b = evaluate(repository, tmp_path / "evidence", (check,))
    assert a["execution_id"] != b["execution_id"]
    assert Path(a["directory"], "execution.json").read_bytes() == original


def test_passing_receipt_does_not_claim_deployment_or_ai_review(repository, tmp_path):
    result = evaluate(repository, tmp_path / "evidence", (command("oracle", "pass"),))
    receipt = json.loads(Path(result["directory"], "execution.json").read_text())
    verification = verify_receipt(Path(result["directory"]))
    assert receipt["production_deployed"] is False
    assert verification["publication_authorized"] is False
    assert "not independent AI review" in verification["scope"]
