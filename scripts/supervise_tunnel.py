"""Windows transport-only supervisor for an existing approved tunnel profile.

No alias creation, credential provisioning, authority API or work replay.
Run under the same Windows owner as the existing profile; see TUNNEL_RECOVERY.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone


class Recovery:
    """Five failures per recovery episode; five stable minutes reset the budget."""
    def __init__(self, failures=0):
        if type(failures) is not int or not 0 <= failures <= 5:
            raise ValueError("invalid recovery evidence")
        self.failures = failures
        self.next_start = 0.0
        self.started = None
        self.stable_since = None
        self.missed = 0

    def tick(self, now, running, ready):
        if self.failures >= 5:
            return "EXHAUSTED"
        if not running:
            if self.started is not None:
                self.failed(now)
                return "PROCESS_EXITED"
            if now < self.next_start:
                return "WAIT"
            self.started = now
            return "START"
        if ready:
            self.missed = 0
            if self.stable_since is None:
                self.stable_since = now
            if now - self.stable_since >= 300:
                self.failures = 0
            return "HEALTHY"
        self.stable_since = None
        if self.started is not None and now - self.started < 30:
            return "STARTING"
        self.missed += 1
        if self.missed < 3:
            return "DEGRADED"
        self.failed(now)
        return "RESTART"

    def failed(self, now):
        self.failures = min(5, self.failures + 1)
        self.next_start = now + min(60, 2 ** self.failures)
        self.started = self.stable_since = None
        self.missed = 0


class Evidence:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "status.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        allowed = {"state", "consecutive_failures", "observed_at", "process_running", "authority_changed",
                   "readiness_scope", "last_successful_connection", "last_failure", "failure_reason", "reconnect_count"}
        self.state = {key: value for key, value in self.state.items() if key in allowed}
        self.previous = None

    def record(self, event, failures, running):
        now = datetime.now(timezone.utc).isoformat()
        state = dict(self.state)
        state.update(state=event, consecutive_failures=failures, observed_at=now,
                     process_running=running, authority_changed=False,
                     readiness_scope="client_health_requires_prior_control_plane_poll")
        if event == "HEALTHY":
            state["last_successful_connection"] = now
            if self.previous != "HEALTHY" and state.get("last_failure"):
                state["reconnect_count"] = state.get("reconnect_count", 0) + 1
        elif event in {"PROCESS_EXITED", "RESTART", "DEGRADED", "EXHAUSTED", "START_FAILED", "SUPERVISOR_FAILED"}:
            state.update(last_failure=now, failure_reason=event)
        state.setdefault("reconnect_count", 0)
        # Store enum-only transitions, never subprocess output or profile content.
        # The JSONL is retained across supervisor restarts, including exhaustion.
        if event != self.previous:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(state, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        self.state, self.previous = state, event


def launch(binary, profile, health_file):
    return subprocess.Popen([str(binary), "run", "--profile-file", str(profile),
        "--health.listen-addr", "127.0.0.1:0", "--health.url-file", str(health_file),
        "--allow-remote-ui=false", "--open-web-ui=false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)


def ready(binary, health_file, pid):
    try:
        return subprocess.run([str(binary), "health", "--url-file", str(health_file),
            "--pid", str(pid), "--require-control-plane-poll"], timeout=8,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def stop_owned(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)


def prime_ready():
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        body = response.read(4097)
        return response.status == 200 and len(body) <= 4096 and json.loads(body).get("ok") is True
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def supervise(binary, profile, directory, expected_hash):
    if os.name != "nt":
        raise RuntimeError("Windows owner-context operator required")
    import msvcrt
    binary, profile = Path(binary).resolve(strict=True), Path(profile).resolve(strict=True)
    if binary.name.lower() != "tunnel-client.exe":
        raise ValueError("expected the inspected tunnel-client executable")
    if hashlib.sha256(profile.read_bytes()).hexdigest() != expected_hash.lower():
        raise ValueError("approved profile changed")
    evidence = Evidence(directory)
    recovery = Recovery(evidence.state.get("consecutive_failures", 0))
    # One owner-context supervisor, regardless of profile. Never adopt/kill an
    # unrelated existing client. Incomplete process visibility is a deployment gate.
    lock_directory = Path(os.environ["LOCALAPPDATA"]) / "JARVIS" / "tunnel-supervision"
    lock_directory.mkdir(parents=True, exist_ok=True)
    with (lock_directory / "supervisor.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq tunnel-client.exe"],
                                 capture_output=True, text=True, check=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        if any(row and row[0].lower() == "tunnel-client.exe" for row in csv.reader(listing.stdout.splitlines())):
            raise RuntimeError("existing tunnel client requires owner-context review")
        child = None
        health_file = evidence.directory / "health.url"
        try:
            deadline = time.monotonic() + 240
            while recovery.failures < 5 and not prime_ready():
                if time.monotonic() >= deadline:
                    evidence.record("EXHAUSTED", 5, False)
                    return 1
                evidence.record("WAITING_DEPENDENCY", recovery.failures, False)
                time.sleep(10)
            while True:
                running = child is not None and child.poll() is None
                event = recovery.tick(time.monotonic(), running,
                                      running and ready(binary, health_file, child.pid))
                if event == "START":
                    # Revalidate immutable selected profile before every restart.
                    if hashlib.sha256(profile.read_bytes()).hexdigest() != expected_hash.lower():
                        raise ValueError("approved profile changed")
                    health_file.unlink(missing_ok=True)
                    try:
                        child = launch(binary, profile, health_file)
                    except OSError:
                        recovery.failed(time.monotonic())
                        event = "START_FAILED"
                elif event in {"RESTART", "EXHAUSTED"}:
                    stop_owned(child)
                evidence.record(event, recovery.failures, child is not None and child.poll() is None)
                if event == "EXHAUSTED":
                    return 1
                time.sleep(10)
        except Exception:
            stop_owned(child)
            evidence.record("SUPERVISOR_FAILED", 5, False)
            raise
        finally:
            stop_owned(child)
            # No queue, envelope, ledger, policy, alias or authority reset.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    try:
        return supervise(args.binary, args.profile, args.evidence_dir, args.profile_sha256)
    except Exception as exc:
        print("Tunnel supervision stopped: " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
