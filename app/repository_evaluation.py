"""Local, bounded repository checks with independently readable execution evidence.

This runs approved check commands in an explicitly selected owning repository.
It does not patch, publish, deploy, fetch credentials or install dependencies.
The caller authorizes execution of the selected repository's test code. Process
limits and a small inherited environment provide bounds, not a sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET

VERSION = "1.0.0"
MAX_LOG_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,}|"
    r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})"
)
_ENV = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "LANG",
    "LC_ALL",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "UV_PYTHON_INSTALL_DIR",
    "PLAYWRIGHT_BROWSERS_PATH",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path, value: dict) -> None:
    # Exclusive creation makes receipts append-only; a repeated run gets a new ID.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        timeout=15,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return process.stdout.strip()


def inspect_repository(root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    top = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if root != top:
        raise ValueError("Select the owning repository root")
    tracked = git(root, "ls-files", "-z").split("\0")
    manifests = {}
    for name in ("package.json", "package-lock.json", "pyproject.toml", "uv.lock", "requirements.txt"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            manifests[name] = digest(path)
    findings = []
    skipped = []
    tree = hashlib.sha256()
    for name in sorted(filter(None, tracked)):
        path = root / name
        # Do not follow a tracked symlink or junction outside the owning repository.
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            skipped.append(name)
            continue
        raw_hash = digest(path)
        tree.update(name.encode("utf-8") + b"\0" + raw_hash.encode() + b"\n")
        if path.stat().st_size > 2 * 1024 * 1024 or path.suffix.lower() not in {
            ".py",
            ".js",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".json",
            ".yml",
            ".yaml",
            ".env",
        }:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _SECRET.search(line):
                # Never include the matching value or source text in a receipt.
                findings.append({"path": name, "line": number, "kind": "credential_pattern_review_required"})
    return {
        "revision": git(root, "rev-parse", "HEAD"),
        "branch": git(root, "branch", "--show-current"),
        "dirty": bool(git(root, "status", "--porcelain")),
        "tracked_content_sha256": tree.hexdigest(),
        "tracked_files": len(list(filter(None, tracked))),
        "manifest_sha256": manifests,
        "secret_findings": findings,
        "unreadable_or_linked": skipped,
        "security_scope": "credential patterns in tracked text; not a vulnerability or authorization audit",
    }


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 300
    junit: str | None = None

    def __post_init__(self):
        if (
            not isinstance(self.name, str)
            or not _NAME.fullmatch(self.name)
            or not isinstance(self.argv, tuple)
            or not self.argv
            or not all(isinstance(x, str) and x and "\0" not in x for x in self.argv)
        ):
            raise ValueError("Invalid check identity or argv")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 1800
        ):
            raise ValueError("Check timeout must be finite and between zero and 1800 seconds")
        if self.junit is not None and (Path(self.junit).name != self.junit or not self.junit.endswith(".xml")):
            raise ValueError("JUnit must name a receipt-local XML file")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # PID is generated by the OS, never supplied by a tool caller.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def _junit(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError("Missing or oversized JUnit evidence")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("DTD is not accepted in test evidence")
    root = ET.fromstring(raw)
    cases = list(root.iter("testcase"))
    # Read executed cases rather than trusting caller-supplied suite counters.
    return {
        "tests": len(cases),
        "failed": sum(case.find("failure") is not None or case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }


def run_check(root: Path, directory: Path, check: Check, *, cancel: threading.Event | None = None) -> dict:
    started = time.monotonic()
    log = directory / (check.name + ".log")
    result = {
        "name": check.name,
        "started_at": utcnow(),
        "execution_mode": "DETERMINISTIC",
        "argv": list(check.argv),
        "timeout_seconds": check.timeout_seconds,
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in _ENV}
    environment.update(
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        CI="1",
        NO_COLOR="1",
        ORQEVIA_DATA_DIR=str(directory / "runtime-data"),
        ORQEVIA_COMPUTE_QUEUE_DB=str(directory / "runtime-data" / "queue.db"),
    )
    if cancel is not None and cancel.is_set():
        result.update(status="CANCELLED", exit_code=None)
    else:
        try:
            with log.open("xb") as output:
                process = subprocess.Popen(
                    check.argv,
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                status = None
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        status = "CANCELLED"
                    elif time.monotonic() - started >= check.timeout_seconds:
                        status = "TIMED_OUT"
                    elif log.stat().st_size > MAX_LOG_BYTES:
                        status = "OUTPUT_LIMIT"
                    if status:
                        _stop(process)
                        break
                    time.sleep(0.025)
                result.update(
                    status=status or ("PASS" if process.returncode == 0 else "FAIL"), exit_code=process.returncode
                )
        except OSError as error:
            result.update(status="UNAVAILABLE", exit_code=None, error_type=type(error).__name__)
    if log.exists():
        # A fast command can exceed the limit and exit between polling ticks.
        if log.stat().st_size > MAX_LOG_BYTES and result["status"] == "PASS":
            result["status"] = "OUTPUT_LIMIT"
        with log.open("rb") as stream:
            raw = stream.read(MAX_LOG_BYTES)
        safe = _SECRET.sub("[REDACTED_CREDENTIAL]", raw.decode("utf-8", errors="replace"))
        log.write_text(safe, encoding="utf-8", newline="\n")
        result.update(log=log.name, log_sha256=digest(log))
    if check.junit:
        try:
            path = directory / check.junit
            result.update(junit=check.junit, junit_sha256=digest(path), test_counts=_junit(path))
            if result["test_counts"]["tests"] == 0 or result["test_counts"]["failed"]:
                if result["status"] == "PASS":
                    result["status"] = "FAIL"
        except (OSError, ValueError, ET.ParseError):
            if result["status"] == "PASS":
                result["status"] = "INVALID_EVIDENCE"
    result["seconds"] = round(time.monotonic() - started, 4)
    result["completed_at"] = utcnow()
    return result


def verify_receipt(directory: Path) -> dict:
    """Rescan preserved bytes and executed test cases without trusting PASS flags."""
    directory = Path(directory).resolve()
    receipt = json.loads((directory / "execution.json").read_text(encoding="utf-8"))
    errors = []
    checks = receipt.get("checks", [])
    if not checks or receipt.get("status") != "PASS":
        errors.append("execution_not_passed")
    if receipt.get("source_before") != receipt.get("source_after"):
        errors.append("repository_changed_during_checks")
    for check in checks:
        if check.get("status") != "PASS" or check.get("exit_code") != 0:
            errors.append("check_not_passed:" + check["name"])
        for field in ("log", "junit"):
            if field not in check:
                continue
            path = directory / check[field]
            if (
                path.is_symlink()
                or path.parent != directory
                or not path.is_file()
                or digest(path) != check.get(field + "_sha256")
            ):
                errors.append("evidence_mismatch:" + check["name"] + ":" + field)
            elif field == "junit":
                try:
                    counts = _junit(path)
                    if counts != check.get("test_counts") or not counts["tests"] or counts["failed"]:
                        errors.append("test_oracle_failed:" + check["name"])
                except (ValueError, ET.ParseError):
                    errors.append("invalid_test_evidence:" + check["name"])
    return {
        "execution_id": receipt["execution_id"],
        "status": "PASS" if not errors else "FAIL",
        "execution_sha256": digest(directory / "execution.json"),
        "errors": errors,
        "execution_mode": "DETERMINISTIC",
        "scope": "separate evidence rescan; not independent AI review",
        "verified_at": utcnow(),
        "publication_authorized": False,
    }


def evaluate(root: Path, evidence_root: Path, checks: tuple[Check, ...], *, cancel=None) -> dict:
    if not checks or len(checks) > 16 or len({check.name for check in checks}) != len(checks):
        raise ValueError("Select one to sixteen uniquely named checks")
    root = Path(root).resolve(strict=True)
    before = inspect_repository(root)
    directory = Path(evidence_root).resolve() / str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    _json(
        directory / "intent.json",
        {
            "execution_id": directory.name,
            "repository": str(root),
            "source": before,
            "started_at": utcnow(),
            "status": "RUNNING",
            "scope": "authorized local repository checks",
            "paid_provider_budget_usd": 0,
        },
    )
    results = [run_check(root, directory, check, cancel=cancel) for check in checks]
    after = inspect_repository(root)
    result = {
        "version": VERSION,
        "execution_id": directory.name,
        "repository": str(root),
        "source_before": before,
        "source_after": after,
        "checks": results,
        "status": "PASS" if all(item["status"] == "PASS" for item in results) and before == after else "FAIL",
        "completed_at": utcnow(),
        "production_deployed": False,
        "external_cost_usd": None,
        "cost_scope": "no provider invoked by runner; child check costs not inferred",
    }
    result["release_eligible"] = result["status"] == "PASS" and not before["dirty"] and not after["dirty"]
    result["runner"] = {
        "module": "app.repository_evaluation",
        "version": VERSION,
        "source_sha256": digest(Path(__file__)),
        "execution_mode": "DETERMINISTIC",
    }
    _json(directory / "execution.json", result)
    verification = verify_receipt(directory)
    _json(directory / "verification.json", verification)
    return {
        "execution_id": directory.name,
        "status": verification["status"],
        "directory": str(directory),
        "checks": len(results),
        "receipt_sha256": digest(directory / "execution.json"),
    }


def profile_checks(root: Path, profile: str) -> tuple[Check, ...]:
    """Small fixed recipes; the API never accepts arbitrary shell commands."""
    if profile == "python":
        python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return (
            Check("python-tests", (str(python) if python.is_file() else sys.executable, "-m", "pytest", "-q"), 600),
        )
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise ValueError("npm is unavailable")
    if profile == "node":
        return (Check("node-tests", (npm, "test"), 600),)
    if profile == "static-web":
        return (Check("node-check", (npm, "run", "check"), 600),)
    raise ValueError("Unknown repository check profile")
