from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TruthState(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    DISPUTED = "DISPUTED"
    STALE = "STALE"
    DIVERGED = "DIVERGED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _run_git(path: Path, *args: str, timeout: int = 30) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _normalize_remote(value: str) -> str:
    normalized = value.strip().lower().replace("\\", "/")
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized.split(":", 1)[1]
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Finding:
    code: str
    state: TruthState
    detail: str
    repository_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"code": self.code, "state": self.state.value, "detail": self.detail}
        if self.repository_id:
            value["repository_id"] = self.repository_id
        return value


class Reconciler:
    """Compares local Git, remote refs, SSOT claims, and durable evidence.

    The class never changes Git history or source files. With ``repair=True`` it
    may refresh refs and replace only its own derived cache/status documents.
    """

    def __init__(self, config_path: Path, *, fetch: bool = False, repair: bool = False):
        self.config_path = config_path.resolve()
        self.config = _read_json(self.config_path)
        self.fetch = fetch
        self.repair = repair
        self.findings: list[Finding] = []
        self.repairs: list[dict[str, str]] = []
        self.base = self.config_path.parent

    def _path(self, raw: str | None) -> Path | None:
        if not raw:
            return None
        expanded = os.path.expandvars(raw)
        path = Path(expanded)
        return path if path.is_absolute() else (self.base / path).resolve()

    def _find(self, code: str, state: TruthState, detail: str, repository_id: str | None = None) -> None:
        self.findings.append(Finding(code, state, detail, repository_id))

    def _repository(self, item: dict[str, Any], ssot: dict[str, Any]) -> dict[str, Any]:
        repository_id = str(item["repository_id"])
        path = self._path(item.get("canonical_local_path"))
        result: dict[str, Any] = {
            "repository_id": repository_id,
            "component_name": item.get("component_name"),
            "canonical_local_path": str(path) if path else None,
            "expected_remote": item.get("canonical_github_remote"),
            "default_branch": item.get("default_branch", "main"),
            "classification": item.get("classification", "UNKNOWN"),
        }
        if path is None:
            result["state"] = TruthState.UNKNOWN.value
            self._find("canonical_local_path_unresolved", TruthState.UNKNOWN, "No canonical local path is selected", repository_id)
            return result
        if not (path / ".git").exists():
            result["state"] = TruthState.FAILED.value
            self._find("repository_missing", TruthState.FAILED, f"Git working tree not found: {path}", repository_id)
            return result

        if self.fetch:
            fetch_args = ["fetch", "--prune", "origin"]
            ssl_backend = item.get("git_http_ssl_backend")
            if ssl_backend:
                fetch_args = ["-c", f"http.sslBackend={ssl_backend}", *fetch_args]
            if item.get("use_askpass_only"):
                fetch_args = ["-c", "credential.helper=", *fetch_args]
            code, _, error = _run_git(path, *fetch_args)
            if code:
                self._find("github_fetch_failed", TruthState.UNKNOWN, error or "fetch failed", repository_id)
            else:
                self.repairs.append({"kind": "remote_refs_refreshed", "repository_id": repository_id})

        commands = {
            "head_sha": ("rev-parse", "HEAD"),
            "current_branch": ("branch", "--show-current"),
            "upstream_branch": ("rev-parse", "--abbrev-ref", "@{upstream}"),
            "upstream_sha": ("rev-parse", "@{upstream}"),
            "origin_url": ("remote", "get-url", "origin"),
            "porcelain": ("status", "--porcelain=v1", "--untracked-files=all"),
        }
        for key, command in commands.items():
            code, output, error = _run_git(path, *command)
            result[key] = output if code == 0 else None
            if key not in {"upstream_branch", "upstream_sha"} and code:
                self._find(f"git_{key}_failed", TruthState.FAILED, error or f"git {key} failed", repository_id)

        expected_remote = str(item.get("canonical_github_remote", ""))
        if _normalize_remote(str(result.get("origin_url") or "")) != _normalize_remote(expected_remote):
            self._find("wrong_remote", TruthState.DIVERGED, "origin does not match the canonical GitHub remote", repository_id)

        porcelain = str(result.get("porcelain") or "")
        lines = porcelain.splitlines() if porcelain else []
        result["dirty"] = bool(lines)
        result["untracked"] = [line[3:] for line in lines if line.startswith("?? ")]
        if lines:
            self._find("dirty_working_tree", TruthState.UNVERIFIED, f"{len(lines)} working-tree entries", repository_id)
        if result["untracked"]:
            self._find("untracked_files", TruthState.UNVERIFIED, f"{len(result['untracked'])} untracked entries", repository_id)
        if not result.get("current_branch"):
            self._find("detached_head", TruthState.DIVERGED, "HEAD is detached", repository_id)
        if not result.get("upstream_sha"):
            self._find("missing_upstream", TruthState.UNVERIFIED, "Current branch has no upstream", repository_id)
        else:
            code, counts, error = _run_git(path, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
            if code == 0 and re.fullmatch(r"\d+\s+\d+", counts):
                ahead, behind = (int(value) for value in counts.split())
                result.update({"ahead": ahead, "behind": behind})
                if ahead and behind:
                    self._find("branch_diverged", TruthState.DIVERGED, f"ahead={ahead}, behind={behind}", repository_id)
                elif ahead:
                    self._find("local_ahead", TruthState.UNVERIFIED, f"{ahead} commit(s) not upstream", repository_id)
                elif behind:
                    self._find("remote_ahead", TruthState.STALE, f"local is behind by {behind} commit(s)", repository_id)
            else:
                self._find("ahead_behind_unknown", TruthState.UNKNOWN, error or "could not compare upstream", repository_id)

        system_id = item.get("ssot_system_id")
        system = ssot.get("systems", {}).get(system_id, {}) if system_id else {}
        ssot_sha = system.get("source_head_sha")
        result["ssot_sha"] = ssot_sha
        if ssot_sha and result.get("head_sha") != ssot_sha:
            code, _, _ = _run_git(path, "merge-base", "--is-ancestor", str(ssot_sha), str(result.get("head_sha")))
            if code == 0:
                self._find("ssot_behind", TruthState.STALE, f"SSOT={ssot_sha}, local={result.get('head_sha')}", repository_id)
            else:
                self._find("ssot_result_sha_mismatch", TruthState.DISPUTED, f"SSOT={ssot_sha}, local={result.get('head_sha')}", repository_id)

        red_codes = {"wrong_remote", "branch_diverged", "ssot_result_sha_mismatch"}
        repo_findings = [finding for finding in self.findings if finding.repository_id == repository_id]
        if any(finding.code in red_codes or finding.state in {TruthState.DIVERGED, TruthState.DISPUTED, TruthState.FAILED} for finding in repo_findings):
            result["state"] = TruthState.DIVERGED.value
        elif repo_findings:
            result["state"] = TruthState.UNVERIFIED.value
        else:
            result["state"] = TruthState.VERIFIED.value
        return result

    def _evidence(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in self.config.get("evidence", []):
            path = self._path(item.get("path"))
            expected = str(item.get("sha256", "")).lower()
            record = {"evidence_id": item.get("evidence_id"), "path": str(path) if path else None, "expected_sha256": expected or None}
            if path is None or not path.is_file():
                record["state"] = TruthState.UNVERIFIED.value
                self._find("missing_evidence", TruthState.UNVERIFIED, f"Missing evidence: {record['path']}")
            else:
                observed = _sha256(path)
                record["observed_sha256"] = observed
                if not SHA256.fullmatch(expected) or observed != expected:
                    record["state"] = TruthState.DISPUTED.value
                    self._find("evidence_hash_mismatch", TruthState.DISPUTED, f"Evidence hash mismatch: {path}")
                else:
                    record["state"] = TruthState.VERIFIED.value
            results.append(record)
        return results

    def _claims(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        verified_ids = {item["evidence_id"] for item in evidence if item.get("state") == TruthState.VERIFIED.value}
        results: list[dict[str, Any]] = []
        for claim in self.config.get("claims", []):
            result = dict(claim)
            references = set(claim.get("evidence_ids", []))
            declared = str(claim.get("verification_state", TruthState.UNKNOWN.value))
            if declared == TruthState.VERIFIED.value and (not references or not references.issubset(verified_ids)):
                result["effective_state"] = TruthState.DISPUTED.value
                self._find("unsupported_pass_claim", TruthState.DISPUTED, f"Claim {claim.get('claim_id')} lacks verified evidence")
            else:
                result["effective_state"] = declared
            results.append(result)
        return results

    def _abex(self) -> dict[str, Any]:
        config = self.config.get("abex", {})
        observation = self._path(config.get("observation_path"))
        if observation:
            if not observation.is_file():
                self._find("abex_unavailable", TruthState.UNKNOWN, f"ABEX observation is unavailable: {observation}")
                return {"reachable": False, "method": "preserved_observation"}
            observed = _read_json(observation)
            return {
                "reachable": True,
                "method": "preserved_observation",
                "observation_sha256": _sha256(observation),
                "identity": observed.get("identity") or observed.get("abex_host"),
                "prime_authority": observed.get("prime_authority"),
            }
        endpoint = config.get("health_endpoint")
        if not endpoint:
            self._find("abex_unconfigured", TruthState.UNKNOWN, "No ABEX observer is configured")
            return {"reachable": None, "method": None}
        parsed = urlsplit(endpoint)
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=float(config.get("timeout_seconds", 3))):
                pass
            return {"reachable": True, "method": "tcp_visibility_only", "endpoint": endpoint}
        except OSError as exc:
            self._find("abex_unavailable", TruthState.UNKNOWN, f"ABEX is unreachable: {type(exc).__name__}")
            return {"reachable": False, "method": "tcp_visibility_only", "endpoint": endpoint}

    def run(self) -> dict[str, Any]:
        timestamp = _utc_now()
        ssot_path = self._path(self.config.get("ssot_path"))
        try:
            ssot = _read_json(ssot_path) if ssot_path else {}
            ssot_reachable = bool(ssot_path)
            if ssot.get("status") == "STALE":
                reasons = ssot.get("verification", {}).get("stale_reasons", [])
                detail = f"SSOT declares STALE with {len(reasons)} recorded reason(s)"
                self._find("ssot_declared_stale", TruthState.STALE, detail)
            as_of = ssot.get("as_of_utc")
            if as_of:
                observed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
                max_age = timedelta(hours=float(self.config.get("ssot_max_age_hours", 24)))
                if datetime.now(timezone.utc) - observed > max_age:
                    self._find("stale_ssot", TruthState.STALE, f"SSOT is older than {max_age.total_seconds() / 3600:g} hours")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            ssot = {}
            ssot_reachable = False
            self._find("ssot_unavailable", TruthState.FAILED, f"SSOT could not be read: {type(exc).__name__}")

        repositories = [self._repository(item, ssot) for item in self.config.get("repositories", [])]
        remote_groups: dict[str, list[str]] = {}
        path_groups: dict[str, list[str]] = {}
        for repository in repositories:
            remote = _normalize_remote(str(repository.get("expected_remote") or ""))
            path = str(repository.get("canonical_local_path") or "").lower()
            if remote:
                remote_groups.setdefault(remote, []).append(repository["repository_id"])
            if path:
                path_groups.setdefault(path, []).append(repository["repository_id"])
        for kind, groups in (("remote", remote_groups), ("path", path_groups)):
            for identity, repository_ids in groups.items():
                if len(repository_ids) > 1:
                    self._find("duplicate_repository", TruthState.UNVERIFIED, f"Duplicate {kind} {identity}: {', '.join(repository_ids)}")
        evidence = self._evidence()
        claims = self._claims(evidence)
        abex = self._abex()
        contradictions = [finding.as_dict() for finding in self.findings if finding.state in {TruthState.DISPUTED, TruthState.DIVERGED, TruthState.FAILED}]
        unresolved = [finding.as_dict() for finding in self.findings if finding.state in {TruthState.UNKNOWN, TruthState.UNVERIFIED, TruthState.STALE}]
        overall = "RED" if contradictions else ("AMBER" if unresolved else "GREEN")
        result: dict[str, Any] = {
            "schema_version": "1.0.0",
            "reconciler_version": "1.0.0",
            "reconciliation_id": str(uuid.uuid4()),
            "timestamp": timestamp,
            "host": socket.gethostname(),
            "repositories_checked": repositories,
            "abex": abex,
            "github_reachability": not any(finding.code == "github_fetch_failed" for finding in self.findings),
            "ssot_reachability": ssot_reachable,
            "evidence_store_reachability": all(item.get("state") != TruthState.UNVERIFIED.value for item in evidence),
            "evidence_findings": evidence,
            "claims": claims,
            "contradictions": contradictions,
            "automatic_repairs_performed": self.repairs,
            "unresolved_findings": unresolved,
            "overall_health": overall,
        }
        cache_path = self._path(self.config.get("derived_status_path"))
        if self.repair and cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result["automatic_repairs_performed"].append({"kind": "derived_status_rebuilt", "path": str(cache_path)})
        return result


def reconcile(config_path: Path, *, fetch: bool = False, repair: bool = False) -> dict[str, Any]:
    return Reconciler(config_path, fetch=fetch, repair=repair).run()
