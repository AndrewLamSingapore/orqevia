from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SHA1 = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_NAME = re.compile(
    r"(^|[._-])(\.env|credentials?|secrets?|tokens?|private[-_]?keys?|wifi[-_]?config)([._-]|$)",
    re.IGNORECASE,
)
SENSITIVE_CONTENT = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    rb"(?i:(?:password|passwd|api[_-]?key|client[_-]?secret|wifi[_-]?pass)\s*[:=]\s*['\"]?[^\s'\"]{8,})"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_event(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _normal_remote(value: str) -> str:
    result = value.strip().lower().replace("\\", "/")
    if result.startswith("git@github.com:"):
        result = "https://github.com/" + result.split(":", 1)[1]
    return result.removesuffix(".git").rstrip("/")


def _git(repo: Path, *args: str, timeout: int = 120) -> tuple[int, str, str]:
    command = ["git", "-c", f"safe.directory={repo.resolve()}", "-C", str(repo), *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _must_git(repo: Path, *args: str, timeout: int = 120) -> str:
    code, stdout, stderr = _git(repo, *args, timeout=timeout)
    if code:
        raise RuntimeError(stderr or stdout or f"git {' '.join(args)} failed")
    return stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SyncLockError(RuntimeError):
    pass


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as exc:
            try:
                record = _read_json(path)
                pid = int(record.get("pid", 0))
                if pid <= 0:
                    raise ProcessLookupError
                os.kill(pid, 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                if attempt == 0:
                    continue
            raise SyncLockError("another synchronization run is active") from exc
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid(), "created_at": _now()}).encode())
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)


class NodeSynchronizer:
    """Synchronize only explicit managed repositories without becoming an SSOT."""

    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.config = _read_json(self.config_path)
        self.base = self.config_path.parent
        raw_state = os.path.expandvars(str(self.config.get("state_dir", "state/dell-node-sync")))
        state = Path(raw_state)
        self.state_dir = state if state.is_absolute() else (self.base / state).resolve()
        self.node = self.config.get("node", {})
        self.node_id = str(self.node.get("node_id", ""))
        self.expected_hostname = str(self.node.get("expected_hostname", ""))
        self.events_path = self.state_dir / "events.jsonl"
        self.pending_path = self.state_dir / "pending.json"
        self.status_path = self.state_dir / "status.json"
        self.lock_path = self.state_dir / "sync.lock"

    def _validate_identity(self) -> None:
        if not self.node_id.startswith("dell:"):
            raise ValueError("Dell node_id is missing or invalid")
        if not self.expected_hostname:
            raise ValueError("expected_hostname is required")
        if socket.gethostname().upper() != self.expected_hostname.upper():
            raise RuntimeError("Dell node hostname mismatch")

    def _repo_path(self, item: dict[str, Any]) -> Path:
        raw = os.path.expandvars(str(item.get("canonical_local_path", "")))
        value = Path(raw)
        return value.resolve() if value.is_absolute() else (self.base / value).resolve()

    def _load_pending(self) -> dict[str, Any]:
        try:
            value = _read_json(self.pending_path)
        except (OSError, ValueError, json.JSONDecodeError):
            value = {"schema_version": "1.0.0", "operations": []}
        value.setdefault("operations", [])
        return value

    def _save_pending(self, value: dict[str, Any]) -> None:
        value["updated_at"] = _now()
        _atomic_json(self.pending_path, value)

    def _queue(self, pending: dict[str, Any], repository_id: str, operation: str, reason: str) -> None:
        existing = next(
            (entry for entry in pending["operations"] if entry["repository_id"] == repository_id and entry["operation"] == operation),
            None,
        )
        if existing:
            existing.update({"reason": reason, "last_seen_at": _now()})
            return
        pending["operations"].append(
            {"repository_id": repository_id, "operation": operation, "reason": reason, "created_at": _now(), "last_seen_at": _now()}
        )

    @staticmethod
    def _clear(pending: dict[str, Any], repository_id: str, *operations: str) -> None:
        wanted = set(operations)
        pending["operations"] = [
            entry for entry in pending["operations"]
            if not (entry["repository_id"] == repository_id and entry["operation"] in wanted)
        ]

    def _inspect(self, item: dict[str, Any], *, fetch: bool, pending: dict[str, Any]) -> dict[str, Any]:
        repository_id = str(item["repository_id"])
        repo = self._repo_path(item)
        result: dict[str, Any] = {"repository_id": repository_id, "path": str(repo), "actions": []}
        if not (repo / ".git").exists():
            result.update({"state": "FAILED", "error": "repository_missing"})
            return result
        branch = str(item.get("default_branch", "main"))
        origin = _must_git(repo, "remote", "get-url", "origin")
        if _normal_remote(origin) != _normal_remote(str(item.get("canonical_github_remote", ""))):
            result.update({"state": "FAILED", "error": "wrong_remote"})
            return result
        current = _must_git(repo, "branch", "--show-current")
        if current != branch:
            result.update({"state": "FAILED", "error": "wrong_branch", "branch": current})
            return result
        porcelain = _must_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        result["dirty"] = bool(porcelain)
        if porcelain:
            self._queue(pending, repository_id, "dirty_review", "working tree contains uncommitted changes")
            result.update({"state": "PENDING", "error": "dirty_working_tree"})
            return result
        self._clear(pending, repository_id, "dirty_review")

        fetch_ok = True
        if fetch:
            args = ["fetch", "--prune", "origin"]
            if item.get("git_http_ssl_backend"):
                args = ["-c", f"http.sslBackend={item['git_http_ssl_backend']}", *args]
            if item.get("use_askpass_only"):
                args = ["-c", "credential.helper=", *args]
            code, _, error = _git(repo, *args)
            fetch_ok = code == 0
            if not fetch_ok:
                self._queue(pending, repository_id, "fetch", "remote temporarily unavailable")
                result.update({"state": "PENDING", "error": "fetch_failed"})
                return result
            self._clear(pending, repository_id, "fetch")
            result["actions"].append("fetched")

        remote_ref = f"origin/{branch}"
        code, counts, _ = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}")
        if code or not re.fullmatch(r"\d+\s+\d+", counts):
            result.update({"state": "FAILED", "error": "comparison_failed"})
            return result
        ahead, behind = (int(part) for part in counts.split())
        result.update({"ahead": ahead, "behind": behind, "head_before": _must_git(repo, "rev-parse", "HEAD")})

        if behind and not ahead and item.get("allow_auto_ff", True):
            _must_git(repo, "merge", "--ff-only", remote_ref)
            result["actions"].append("fast_forwarded")
            behind = 0
        elif ahead and behind:
            code, _, error = _git(repo, "rebase", remote_ref)
            if code:
                _git(repo, "rebase", "--abort")
                self._queue(pending, repository_id, "semantic_conflict", "automatic rebase conflicted; both histories preserved")
                result.update({"state": "PENDING", "error": "semantic_conflict", "conflict_detail": error.splitlines()[-1:]})
                return result
            result["actions"].append("rebased_non_conflicting")
            ahead, behind = (int(part) for part in _must_git(repo, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}").split())
            self._clear(pending, repository_id, "semantic_conflict")

        if ahead:
            messages = _must_git(repo, "log", "--format=%B%x00", f"{remote_ref}..HEAD")
            validated = all(
                f"JARVIS-Origin-Node: {self.node_id}" in message and "JARVIS-Validation: PASS" in message
                for message in messages.split("\x00") if message.strip()
            )
            if not validated:
                self._queue(pending, repository_id, "push_review", "ahead commits lack Dell validation provenance")
                result.update({"state": "PENDING", "error": "unvalidated_ahead_commits"})
                return result
            if not item.get("allow_auto_push", False):
                self._queue(pending, repository_id, "push", "automatic push disabled for repository")
                result.update({"state": "PENDING", "error": "push_disabled"})
                return result
            args = ["push", "origin", f"HEAD:{branch}"]
            if item.get("git_http_ssl_backend"):
                args = ["-c", f"http.sslBackend={item['git_http_ssl_backend']}", *args]
            if item.get("use_askpass_only"):
                args = ["-c", "credential.helper=", *args]
            code, _, error = _git(repo, *args)
            if code:
                self._queue(pending, repository_id, "push", "push failed; local commit preserved")
                result.update({"state": "PENDING", "error": "push_failed", "push_detail": error.splitlines()[-1:]})
                return result
            result["actions"].append("pushed")
            self._clear(pending, repository_id, "push", "push_review")

        head = _must_git(repo, "rev-parse", "HEAD")
        remote_sha = _must_git(repo, "rev-parse", remote_ref)
        result.update({"head_after": head, "remote_sha": remote_sha, "remote_verified": head == remote_sha})
        result["state"] = "PASS" if head == remote_sha else "PENDING"
        return result

    def run(self, *, fetch: bool = True) -> dict[str, Any]:
        self._validate_identity()
        with _lock(self.lock_path):
            pending = self._load_pending()
            repositories = [self._inspect(item, fetch=fetch, pending=pending) for item in self.config.get("repositories", [])]
            self._save_pending(pending)
            overall = "FAIL" if any(item["state"] == "FAILED" for item in repositories) else (
                "PENDING" if any(item["state"] == "PENDING" for item in repositories) or pending["operations"] else "PASS"
            )
            result = {
                "schema_version": "1.0.0",
                "node_id": self.node_id,
                "hostname": socket.gethostname(),
                "timestamp": _now(),
                "authority": "PRIME_CANONICAL_SSOT",
                "role": "DELL_EXECUTION_NODE",
                "repositories": repositories,
                "pending_operations": pending["operations"],
                "overall": overall,
            }
            _atomic_json(self.status_path, result)
            _append_event(self.events_path, {"timestamp": result["timestamp"], "event": "synchronization_completed", "overall": overall})
            return result

    def commit_work_unit(self, work_unit_path: Path) -> dict[str, Any]:
        self._validate_identity()
        unit = _read_json(work_unit_path.resolve())
        repository_id = str(unit.get("repository_id", ""))
        item = next((entry for entry in self.config.get("repositories", []) if entry.get("repository_id") == repository_id), None)
        if item is None:
            raise ValueError("work unit repository is not managed")
        repo = self._repo_path(item)
        base = _must_git(repo, "rev-parse", "HEAD")
        if unit.get("base_revision") != base:
            raise RuntimeError("work unit base revision does not match current HEAD")
        paths = unit.get("paths") or []
        if not paths:
            raise ValueError("work unit must explicitly list changed paths")
        resolved: list[tuple[str, Path]] = []
        for raw in paths:
            relative = Path(str(raw))
            candidate = (repo / relative).resolve()
            try:
                candidate.relative_to(repo)
            except ValueError as exc:
                raise ValueError("work unit path escapes repository") from exc
            if SENSITIVE_NAME.search(relative.as_posix()):
                raise ValueError(f"sensitive path rejected: {relative.as_posix()}")
            if candidate.is_file() and candidate.stat().st_size <= 2 * 1024 * 1024 and SENSITIVE_CONTENT.search(candidate.read_bytes()):
                raise ValueError(f"secret-like content rejected: {relative.as_posix()}")
            resolved.append((relative.as_posix(), candidate))

        fetch_args = ["fetch", "--prune", "origin"]
        if item.get("git_http_ssl_backend"):
            fetch_args = ["-c", f"http.sslBackend={item['git_http_ssl_backend']}", *fetch_args]
        if item.get("use_askpass_only"):
            fetch_args = ["-c", "credential.helper=", *fetch_args]
        _must_git(repo, *fetch_args)
        branch = str(item.get("default_branch", "main"))
        counts = _must_git(repo, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
        if counts != "0\t0" and counts != "0  0" and [int(part) for part in counts.split()] != [0, 0]:
            raise RuntimeError("work unit base is not synchronized with canonical remote")
        # A work unit is the only operation allowed to consume a dirty tree, and
        # only its explicit paths may be dirty.
        dirty = _must_git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
        dirty_paths = {line[3:].replace("\\", "/") for line in dirty}
        allowed = {path for path, _ in resolved}
        if not dirty_paths or not dirty_paths.issubset(allowed):
            raise RuntimeError("dirty tree contains changes outside the explicit work unit")

        tests: list[dict[str, Any]] = []
        for command in unit.get("validation_commands", []):
            if not isinstance(command, list) or not command:
                raise ValueError("validation command must be a non-empty argument array")
            completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=900, check=False)
            tests.append({"command": command, "exit_code": completed.returncode})
            if completed.returncode:
                raise RuntimeError(f"validation failed: {command[0]}")

        _must_git(repo, "add", "--", *sorted(allowed))
        staged = _must_git(repo, "diff", "--cached", "--name-only").splitlines()
        if not staged or not set(staged).issubset(allowed):
            _git(repo, "reset", "--", *sorted(allowed))
            raise RuntimeError("staged content does not match the explicit work unit")
        work_id = str(unit.get("work_unit_id") or uuid.uuid4())
        message = str(unit.get("commit_message") or f"Complete Dell work unit {work_id}")
        full_message = (
            f"{message}\n\n"
            f"JARVIS-Origin-Node: {self.node_id}\n"
            f"JARVIS-Work-Unit: {work_id}\n"
            f"JARVIS-Base-Revision: {base}\n"
            "JARVIS-Validation: PASS"
        )
        _must_git(repo, "commit", "-m", full_message)
        result_sha = _must_git(repo, "rev-parse", "HEAD")
        sync_result = self.run(fetch=True)
        repository_result = next(entry for entry in sync_result["repositories"] if entry["repository_id"] == repository_id)
        proposal = {
            "schema_version": "1.0.0",
            "proposal_id": str(uuid.uuid4()),
            "created_at": _now(),
            "origin_node": self.node_id,
            "repository_id": repository_id,
            "work_unit_id": work_id,
            "base_revision": base,
            "result_revision": result_sha,
            "remote_revision": repository_result.get("remote_sha"),
            "validation": tests,
            "authority": "PROPOSAL_FOR_PRIME_RECONCILIATION",
        }
        proposal_path = self.state_dir / "ssot-proposals" / f"{proposal['proposal_id']}.json"
        _atomic_json(proposal_path, proposal)
        return {"overall": repository_result["state"], "work_unit": proposal, "proposal_path": str(proposal_path), "sync": sync_result}


def synchronize(config_path: Path, *, fetch: bool = True) -> dict[str, Any]:
    return NodeSynchronizer(config_path).run(fetch=fetch)


def commit_work_unit(config_path: Path, work_unit_path: Path) -> dict[str, Any]:
    return NodeSynchronizer(config_path).commit_work_unit(work_unit_path)
