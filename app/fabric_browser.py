"""Fixed, operator-configured real public-page Chromium probe.

The HTTP caller selects no executable, module, script, URL, arguments, profiles
or credentials. Only one probe may run at once. The browser child has a 20-second
deadline and is tree-terminated at 25 seconds or upon bounded-output overflow.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading


ORIGINS = frozenset({"https://localhost:8443", "https://192.168.1.23:9443"})
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/fabric_browser_probe.cjs"
MAX_OUTPUT = 65536
PROCESS_TIMEOUT = 25
_CAPACITY = threading.BoundedSemaphore(1)

CONTRACT = {
    "version": "0.3.0",
    "operations": [
        {
            "operation": "browser.inspect",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "output_schema": {
                "type": "object",
                "required": ["protocol", "status", "pages"],
                "properties": {
                    "protocol": {"type": "string"},
                    "status": {"type": "string", "enum": ["PASS", "FAIL"]},
                    "pages": {"type": "array", "maxItems": 6},
                },
            },
            "scope": "REAL_PUBLIC_PAGES_DESKTOP_AND_EMULATED_MOBILE_ONLY",
        }
    ],
    "limitations": [
        "Public page HTTP/render/navigation semantics, screenshots and mobile geometry only.",
        "No authenticated gameplay, axe audit, physical mobile-device or production readiness certification.",
        "One concurrent Chromium probe; 20-second browser deadline and 25-second process timeout.",
    ],
}


class BrowserProbeError(RuntimeError):
    """A sanitized configuration, capacity or child-process failure."""


def _terminate(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
        try:
            result = subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _run_bounded(command, raw, environment):
    kwargs = (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=SCRIPT.parent,
        shell=False,
        **kwargs,
    )
    output = bytearray()
    overflow = threading.Event()

    def read(stream, *, keep):
        size = 0
        try:
            while True:
                block = stream.read(4096)
                if not block:
                    return
                size += len(block)
                if size > MAX_OUTPUT:
                    overflow.set()
                    _terminate(process)
                    return
                if keep:
                    output.extend(block)
        except OSError:
            return
        finally:
            stream.close()

    readers = [
        threading.Thread(target=read, args=(process.stdout,), kwargs={"keep": True}, daemon=True),
        threading.Thread(target=read, args=(process.stderr,), kwargs={"keep": False}, daemon=True),
    ]
    for thread in readers:
        thread.start()
    try:
        process.stdin.write(raw)
        process.stdin.close()
        process.wait(timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        _terminate(process)
        process.wait(timeout=5)
        raise BrowserProbeError("BROWSER_PROCESS_TIMEOUT") from None
    finally:
        if process.poll() is None:
            _terminate(process)
        for thread in readers:
            thread.join(timeout=2)
    if overflow.is_set() or any(thread.is_alive() for thread in readers):
        raise BrowserProbeError("BROWSER_OUTPUT_LIMIT")
    return process.returncode, bytes(output)


def inspect_browser(payload=None):
    if payload is not None and (not isinstance(payload, dict) or payload):
        raise ValueError("Browser inspection accepts an empty payload only")
    origin = os.getenv("ORQEVIA_BROWSER_TARGET_ORIGIN", "https://localhost:8443")
    node = Path(os.getenv("ORQEVIA_BROWSER_NODE_EXECUTABLE", ""))
    module = Path(os.getenv("ORQEVIA_BROWSER_PLAYWRIGHT_MODULE", ""))
    if origin not in ORIGINS:
        raise BrowserProbeError("BROWSER_ORIGIN_NOT_ALLOWED")
    if (
        not node.is_absolute()
        or not node.is_file()
        or not module.is_absolute()
        or not module.is_dir()
        or not SCRIPT.is_file()
    ):
        raise BrowserProbeError("BROWSER_RUNTIME_UNAVAILABLE")
    if not _CAPACITY.acquire(blocking=False):
        raise BrowserProbeError("BROWSER_CAPACITY_EXCEEDED")
    try:
        script_sha256 = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        # Do not inherit service credentials, proxy credentials, Node flags,
        # user-supplied require hooks or unrelated provider configuration.
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "PLAYWRIGHT_BROWSERS_PATH",
            "NODE_EXTRA_CA_CERTS",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        raw = json.dumps({"origin": origin, "module_path": str(module.resolve())}).encode()
        try:
            returncode, output = _run_bounded([str(node.resolve()), str(SCRIPT)], raw, environment)
        except (OSError, subprocess.SubprocessError):
            raise BrowserProbeError("BROWSER_PROCESS_UNAVAILABLE") from None
        try:
            value = json.loads(output)
        except (ValueError, UnicodeError):
            raise BrowserProbeError("BROWSER_RECEIPT_INVALID") from None
        if (
            not isinstance(value, dict)
            or value.get("protocol") != "orqevia.fabric.browser-probe.v1"
            or value.get("status") not in {"PASS", "FAIL"}
            or not isinstance(value.get("pages"), list)
            or len(value["pages"]) > 6
            or (returncode != 0 and value["status"] == "PASS")
        ):
            raise BrowserProbeError("BROWSER_RECEIPT_INVALID")
        if value["status"] == "PASS":
            expected = {(path, view) for path in ("/", "/capabilities", "/pwa/") for view in ("desktop", "mobile")}
            if (
                value.get("origin") != origin
                or value.get("execution_status") != "COMPLETED"
                or len(value["pages"]) != 6
                or any(not isinstance(row, dict) for row in value["pages"])
                or {(row.get("path"), row.get("view")) for row in value["pages"]} != expected
                or any(
                    row.get("passed") is not True
                    or row.get("response_status") != 200
                    or row.get("same_origin") is not True
                    or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("screenshot_sha256", "")))
                    for row in value["pages"]
                )
            ):
                raise BrowserProbeError("BROWSER_RECEIPT_INVALID")
        if hashlib.sha256(SCRIPT.read_bytes()).hexdigest() != script_sha256:
            raise BrowserProbeError("BROWSER_SOURCE_CHANGED")
        value["probe_script_sha256"] = script_sha256
        return value
    finally:
        _CAPACITY.release()
