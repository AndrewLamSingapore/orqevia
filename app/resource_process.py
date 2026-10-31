"""Opt-in execution adapter for owned build/test processes, using existing state.

No scheduler, daemon, deployment hold, cloud submission or unregistered-process
control. Callers retain their workflow/checkpoint/artifact authority.
"""

from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from .resource_guardian import Workload


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    try:
        with db:
            yield db
    finally:
        db.close()


def _alive(row):
    if row["pid"] is None:
        # A crash between spawn and PID persistence cannot prove that no child
        # exists. Keep this reservation visible for checkpoint reconciliation.
        return True
    import psutil

    try:
        process = psutil.Process(row["pid"])
        return process.is_running() and abs(process.create_time() - row["process_started"]) < 0.01
    except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
        # AccessDenied cannot prove a process has exited and must not release
        # capacity for an overlapping replacement.
        return True if isinstance(row["process_started"], (int, float)) and psutil.pid_exists(row["pid"]) else False


def _stop_owned(process):
    """Cancel only this process and its descendants, retaining exit evidence."""
    import psutil

    try:
        parent = psutil.Process(process.pid)
        owned = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for child in reversed(owned):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, pending = psutil.wait_procs(owned, timeout=2)
    for child in pending:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    process.wait(timeout=3)


def run_guarded(
    guardian,
    database,
    command,
    *,
    workload: Workload,
    work_key,
    timeout_seconds,
    cwd=None,
    cancel_event=None,
    output=None,
    environment=None,
):
    import psutil  # Existing project dependency; verify before starting a child.

    if workload.inference or workload.lane not in {"tools", "build"}:
        raise ValueError("This adapter runs registered tool/build processes only")
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(a, str) for a in command):
        raise ValueError("Explicit argv required; shell execution is not accepted")
    if not isinstance(work_key, str) or not 1 <= len(work_key) <= 256:
        raise ValueError("Explicit logical workflow identity required")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 86400:
        raise ValueError("Finite execution deadline required")
    request = {
        "argv": list(command),
        "workload": asdict(workload),
        "timeout": timeout_seconds,
        "cwd": str(Path(cwd or os.getcwd()).resolve()),
        "environment": environment or {},
    }
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()
    key = hashlib.sha256(work_key.encode()).hexdigest()
    permit = uuid.uuid4().hex
    with connect(database) as db:
        guardian.install(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT * FROM compute_resource_process_keys WHERE key_hash=?", (key,)).fetchone()
        if prior:
            if prior["request_hash"] != digest:
                raise ValueError("Logical workflow identity conflicts with the original request")
            permit_row = db.execute(
                "SELECT * FROM compute_resource_permits WHERE id=?", (prior["permit_id"],)
            ).fetchone()
            if prior["receipt_json"] is None and permit_row is not None and not _alive(permit_row):
                db.execute(
                    "UPDATE compute_resource_permits SET state='ORPHAN_EXITED' WHERE id=?", (prior["permit_id"],)
                )
                receipt = {
                    "status": "RECOVERY_REQUIRED",
                    "permit_id": prior["permit_id"],
                    "reason": "Owner wrapper exited; reconcile existing artifacts before a distinct retry",
                }
            else:
                receipt = (
                    json.loads(prior["receipt_json"])
                    if prior["receipt_json"]
                    else {"status": "IN_PROGRESS", "permit_id": prior["permit_id"]}
                )
            return {**receipt, "replayed": True, "stdout_retained": False}
        # Reconcile only owned permits. A deadline alone cannot prove that a
        # live orphan stopped. Never kill it or start an overlapping duplicate.
        rows = db.execute("SELECT * FROM compute_resource_permits WHERE state IN ('RESERVED','RUNNING')").fetchall()
        for row in rows:
            if not _alive(row):
                db.execute("UPDATE compute_resource_permits SET state='ORPHAN_EXITED' WHERE id=?", (row["id"],))
        rows = db.execute("SELECT * FROM compute_resource_permits WHERE state IN ('RESERVED','RUNNING')").fetchall()
        state = db.execute("SELECT mode,recovering FROM compute_resource_policy WHERE id=1").fetchone()
        active = sum(row["lane"] == workload.lane for row in rows)
        reserved = sum(row["memory_bytes"] for row in rows)
        # Existing inference ownership is shared with this adapter's memory
        # accounting. It is never enrolled as another tool worker.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_jobs'").fetchone():
            reserved += db.execute(
                "SELECT coalesce(sum(ram_mb),0)*1048576 FROM compute_jobs WHERE status='running' OR local_inflight=1"
            ).fetchone()[0]
        decision = guardian.profile.decide(
            guardian.observe(),
            workload,
            mode=state["mode"],
            active=active,
            reserved_bytes=reserved,
            recovering=bool(state["recovering"]),
            now=guardian.clock(),
        )
        db.execute("UPDATE compute_resource_policy SET recovering=? WHERE id=1", (int(decision.recovering),))
        if not decision.admitted:
            return {"status": "DEFERRED", "decision": asdict(decision), "replayed": False}
        now = time.time()
        db.execute(
            "INSERT INTO compute_resource_permits VALUES(?,?,?,?,NULL,NULL,?,?,?)",
            (
                permit,
                workload.lane,
                workload.peak_memory_bytes,
                workload.cpu_threads,
                "RESERVED",
                now + timeout_seconds + 10,
                now,
            ),
        )
        db.execute("INSERT INTO compute_resource_process_keys VALUES(?,?,?,NULL)", (key, digest, permit))
    started = time.perf_counter()
    process = None
    peak_rss = 0
    cpu_seconds = 0.0
    affinity_applied = False
    observed_samples = 0
    receipt = {"permit_id": permit, "status": "FAILED_TO_START", "replayed": False, "command_sha256": digest}
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdout=output,
            stderr=output,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        try:
            owned = psutil.Process(process.pid)
            process_started = owned.create_time()
        except psutil.NoSuchProcess:
            owned, process_started = None, None
        try:
            eligible = owned.cpu_affinity() if owned is not None else []
            owned.cpu_affinity(eligible[: workload.cpu_threads])
            affinity_applied = len(owned.cpu_affinity()) <= workload.cpu_threads
            if workload.priority < 100:
                owned.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
        except (AttributeError, OSError, psutil.Error):
            pass
        with connect(database) as db:
            db.execute(
                "UPDATE compute_resource_permits SET pid=?,process_started=?,state='RUNNING' WHERE id=?",
                (process.pid, process_started, permit),
            )
        reason = None
        while process.poll() is None:
            rss, cpu = 0, 0.0
            try:
                for child in [owned, *owned.children(recursive=True)] if owned is not None else []:
                    try:
                        rss += child.memory_info().rss
                        observed_samples += 1
                        times = child.cpu_times()
                        cpu += times.user + times.system
                    except psutil.Error:
                        pass
            except psutil.Error:
                pass
            peak_rss, cpu_seconds = max(peak_rss, rss), max(cpu_seconds, cpu)
            if cancel_event is not None and cancel_event.is_set():
                reason = "CANCELLED"
            elif time.perf_counter() - started >= timeout_seconds:
                reason = "EXECUTION_TIMEOUT"
            elif workload.peak_memory_bytes and peak_rss > workload.peak_memory_bytes:
                reason = "DECLARED_MEMORY_BUDGET_EXCEEDED"
            if reason:
                _stop_owned(process)
                break
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        code = process.wait(timeout=3)
        receipt.update(status=reason or ("COMPLETED" if code == 0 else "FAILED"), exit_code=code)
    except Exception as error:
        receipt["failure_type"] = type(error).__name__
        if process is not None and process.poll() is None:
            try:
                _stop_owned(process)
            except (OSError, psutil.Error, subprocess.TimeoutExpired) as cleanup_error:
                receipt["cancellation_failure_type"] = type(cleanup_error).__name__
    finally:
        settled = process is None or process.poll() is not None
        if not settled:
            receipt["status"] = "CANCELLATION_PENDING"
        receipt.update(
            elapsed_seconds=time.perf_counter() - started,
            peak_process_tree_rss_bytes=peak_rss if observed_samples else None,
            sampled_process_tree_cpu_seconds=cpu_seconds if observed_samples else None,
            cpu_affinity_applied=affinity_applied,
            observed_process_samples=observed_samples,
            metrics_scope="SAMPLED_PROCESS_TREE_RSS_NOT_UNIQUE_PHYSICAL_MEMORY",
            cloud_submission=False,
            owner_pause_changed=False,
        )
        with connect(database) as db:
            db.execute(
                "UPDATE compute_resource_permits SET state=? WHERE id=?",
                (receipt["status"] if settled else "RUNNING", permit),
            )
            db.execute(
                "UPDATE compute_resource_process_keys SET receipt_json=? WHERE key_hash=?",
                (json.dumps(receipt, separators=(",", ":")), key),
            )
    return receipt
