"""Safe public dispatch failure classification regression tests."""

from app.public_task_errors import public_task


def test_known_dispatch_code_is_visible():
    original = {"steps": [{"reason": "PROVIDER_UNAVAILABLE"}]}
    assert public_task(original)["steps"][0]["reason"] == "PROVIDER_UNAVAILABLE"
    assert original["steps"][0]["reason"] == "PROVIDER_UNAVAILABLE"


def test_exception_details_are_not_leaked():
    result = public_task(
        {
            "steps": [
                {"reason": "token=supersecret"},
                {"reason": "RuntimeError"},
                {"job": {"error": "https://provider.example/private?key=secret"}},
            ]
        }
    )
    assert result["steps"][0]["reason"] == "STEP_DISPATCH_FAILED"
    assert result["steps"][1]["reason"] == "STEP_DISPATCH_FAILED"
    assert result["steps"][2]["job"]["error"] == "EXECUTION_FAILED"


def test_known_job_code_is_visible():
    result = public_task({"steps": [{"job": {"error": "PROVIDER_TIMEOUT"}}]})
    assert result["steps"][0]["job"]["error"] == "PROVIDER_TIMEOUT"
