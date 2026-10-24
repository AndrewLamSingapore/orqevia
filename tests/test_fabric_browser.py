"""Fixed browser configuration, bounded real processes and secret isolation."""

import json
import os
from pathlib import Path
import sys

import pytest

from app import fabric_browser as browser


def test_caller_cannot_select_origin_commands_or_profile():
    for payload in [{"origin": "https://example.com"}, {"node": "x"}, {"path": "/private"}, [], "", False]:
        with pytest.raises(ValueError):
            browser.inspect_browser(payload)


def test_unconfigured_runtime_and_unapproved_origin_are_explicit(monkeypatch):
    monkeypatch.delenv("ORQEVIA_BROWSER_NODE_EXECUTABLE", raising=False)
    monkeypatch.delenv("ORQEVIA_BROWSER_PLAYWRIGHT_MODULE", raising=False)
    with pytest.raises(browser.BrowserProbeError, match="RUNTIME_UNAVAILABLE"):
        browser.inspect_browser({})
    monkeypatch.setenv("ORQEVIA_BROWSER_TARGET_ORIGIN", "https://localhost:8443/private")
    with pytest.raises(browser.BrowserProbeError, match="ORIGIN_NOT_ALLOWED"):
        browser.inspect_browser({})


def configured(monkeypatch, tmp_path):
    module = tmp_path / "operator-module"
    module.mkdir()
    monkeypatch.setenv("ORQEVIA_BROWSER_NODE_EXECUTABLE", sys.executable)
    monkeypatch.setenv("ORQEVIA_BROWSER_PLAYWRIGHT_MODULE", str(module))
    monkeypatch.setenv("ORQEVIA_BROWSER_TARGET_ORIGIN", "https://localhost:8443")


def test_receipt_and_child_environment_do_not_carry_service_credentials(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "never-forward-this-service-secret")
    monkeypatch.setenv("NODE_OPTIONS", "--require=untrusted")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy-user:proxy-secret@example.test")
    observed = {}

    def run(command, raw, environment):
        observed.update(command=command, raw=json.loads(raw), environment=environment)
        return 0, json.dumps({"protocol": "orqevia.fabric.browser-probe.v1", "status": "FAIL", "pages": []}).encode()

    monkeypatch.setattr(browser, "_run_bounded", run)
    result = browser.inspect_browser({})
    assert result["status"] == "FAIL" and len(result["probe_script_sha256"]) == 64
    assert observed["raw"]["origin"] == "https://localhost:8443"
    assert observed["command"][1] == str(browser.SCRIPT)
    assert not {"ORQEVIA_SPINE_TOKEN", "NODE_OPTIONS", "HTTPS_PROXY"} & observed["environment"].keys()


@pytest.mark.parametrize(
    "returncode,receipt",
    [
        (1, {"protocol": "orqevia.fabric.browser-probe.v1", "status": "PASS", "pages": []}),
        (0, {"protocol": "orqevia.fabric.browser-probe.v1", "status": "PASS", "pages": []}),
        (0, {"protocol": "wrong", "status": "PASS", "pages": []}),
        (0, {"protocol": "orqevia.fabric.browser-probe.v1", "status": "PASS", "pages": [1] * 7}),
    ],
)
def test_invalid_receipts_do_not_pass(monkeypatch, tmp_path, returncode, receipt):
    configured(monkeypatch, tmp_path)
    monkeypatch.setattr(browser, "_run_bounded", lambda *args: (returncode, json.dumps(receipt).encode()))
    with pytest.raises(browser.BrowserProbeError, match="RECEIPT_INVALID"):
        browser.inspect_browser({})


def test_concurrency_limit_has_no_queued_unbounded_processes(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    browser._CAPACITY.acquire()
    try:
        with pytest.raises(browser.BrowserProbeError, match="CAPACITY_EXCEEDED"):
            browser.inspect_browser({})
    finally:
        browser._CAPACITY.release()


def test_real_child_process_reads_stdin_and_returns_bounded_output():
    code = "import sys; value=sys.stdin.buffer.read();sys.stdout.buffer.write(value.upper())"
    returncode, output = browser._run_bounded([sys.executable, "-c", code], b"actual-process", dict(os.environ))
    assert returncode == 0 and output == b"ACTUAL-PROCESS"


def test_actual_oversized_process_is_terminated(monkeypatch):
    monkeypatch.setattr(browser, "MAX_OUTPUT", 4096)
    with pytest.raises(browser.BrowserProbeError, match="OUTPUT_LIMIT"):
        browser._run_bounded(
            [sys.executable, "-c", "import sys,time;sys.stdout.write('x'*65536);sys.stdout.flush();time.sleep(5)"],
            b"",
            dict(os.environ),
        )


def test_actual_hung_process_timeout(monkeypatch):
    monkeypatch.setattr(browser, "PROCESS_TIMEOUT", 0.1)
    with pytest.raises(browser.BrowserProbeError, match="PROCESS_TIMEOUT"):
        browser._run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], b"", dict(os.environ))


def test_source_script_is_fixed_and_present():
    assert browser.SCRIPT.name == "fabric_browser_probe.cjs"
    assert browser.SCRIPT.is_file()
    assert browser.CONTRACT["operations"][0]["input_schema"]["additionalProperties"] is False
    assert Path(sys.executable).is_absolute()
