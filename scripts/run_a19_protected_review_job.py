"""Protected-main, non-signing A19/A26 review-artifact job.

Only this job retrieves GitHub provenance using its ephemeral read-only token.
Inputs name exact existing run/artifact IDs; they are never trusted as proof.
There is no Key Vault, OIDC, credential provisioning, or L7 mutation here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib import error, request

from app.agent_cert_a19_a26_review import build_a19_a26_review_artifact


REPOSITORY = "AndrewLamSingapore/prime"
REPOSITORY_ID = 1345668764
REVIEW_WORKFLOW = f"{REPOSITORY}/.github/workflows/a19-protected-review.yml@refs/heads/main"
_SOURCE = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = request.build_opener(_NoRedirect())


def _ids() -> tuple[str, str, str, str]:
    values = tuple(os.getenv(name, "") for name in (
        "PRIME_A19_RUN_ID", "PRIME_A19_ARTIFACT_ID",
        "PRIME_A26_RUN_ID", "PRIME_A26_ARTIFACT_ID"))
    if any(not value.isdecimal() or len(value) > 20 for value in values):
        raise ValueError("four exact decimal run/artifact IDs required")
    if values[0] == values[2] or values[1] == values[3]:
        raise ValueError("A19 and A26 runs/artifacts must be distinct")
    return values


def preflight() -> tuple[str, str, tuple[str, str, str, str]]:
    source, review_run = os.getenv("GITHUB_SHA", ""), os.getenv("GITHUB_RUN_ID", "")
    if (os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("GITHUB_REPOSITORY") != REPOSITORY
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_REF_PROTECTED") != "true"
            or os.getenv("PRIME_REVIEW_WORKFLOW_REF") != REVIEW_WORKFLOW
            or not _SOURCE.fullmatch(source)
            or not review_run.isdecimal()):
        raise ValueError("protected canonical main review job required")
    ids = _ids()
    if review_run in {ids[0], ids[2]}:
        raise ValueError("review job must be a third independent run")
    return source, review_run, ids


def _api_json(path: str, token: str) -> dict:
    if not token or "\n" in token or "\r" in token:
        raise ValueError("ephemeral Actions read token required")
    operation = request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with _OPENER.open(operation, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
    except (error.HTTPError, error.URLError, TimeoutError):
        raise ValueError("authenticated GitHub metadata unavailable") from None
    if len(raw) > 1024 * 1024:
        raise ValueError("GitHub metadata exceeds bound")
    try:
        parsed = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid GitHub metadata") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid GitHub metadata")
    return parsed


def _trusted_run(run_id: str, artifact_id: str, *, workflow: str,
                 artifact_name: str, raw: bytes, source: str,
                 protected: bool, token: str) -> dict[str, object]:
    run = _api_json(f"actions/runs/{run_id}", token)
    artifact = _api_json(f"actions/artifacts/{artifact_id}", token)
    repository = run.get("repository") or {}
    head_repository = run.get("head_repository") or {}
    artifact_run = artifact.get("workflow_run") or {}
    path = f".github/workflows/{workflow}.yml"
    if (repository.get("full_name") != REPOSITORY
            or repository.get("id") != REPOSITORY_ID
            or head_repository.get("id") != REPOSITORY_ID
            or run.get("id") != int(run_id)
            or run.get("head_branch") != "main"
            or run.get("head_sha") != source
            or run.get("event") != "workflow_dispatch"
            or run.get("conclusion") != "success"
            or run.get("path") not in {path, path + "@refs/heads/main"}
            or type(run.get("run_attempt")) is not int
            or run["run_attempt"] < 1
            or artifact.get("id") != int(artifact_id)
            or artifact.get("name") != artifact_name
            or artifact.get("expired") is not False
            or type(artifact.get("size_in_bytes")) is not int
            or not 0 < artifact["size_in_bytes"] <= 16 * 1024 * 1024
            or artifact_run.get("id") != int(run_id)
            or not isinstance(artifact.get("digest"), str)
            or not _DIGEST.fullmatch(artifact["digest"])
            or protected is not True):
        raise ValueError("GitHub run/artifact provenance mismatch")
    return {
        "repository": REPOSITORY, "repository_id": str(REPOSITORY_ID),
        "workflow_ref": f"{REPOSITORY}/{path}@refs/heads/main",
        "ref": "refs/heads/main", "ref_protected": True,
        "event_name": run["event"], "head_sha": source,
        "run_id": run_id, "run_attempt": str(run["run_attempt"]),
        "conclusion": run["conclusion"],
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _file(root: Path, name: str) -> bytes:
    path = root / name
    if (root.is_symlink() or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
            or not 0 < path.stat().st_size <= 1024 * 1024):
        raise ValueError("bounded downloaded review artifact file required")
    return path.read_bytes()


def build() -> str:
    source, review_run, ids = preflight()
    token = os.getenv("GH_TOKEN", "")
    branch = _api_json("branches/main", token)
    if branch.get("protected") is not True:
        raise ValueError("GitHub main protection is not active")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    execution_root = runner_temp / "a19-execution"
    a26_root = runner_temp / "a26-observation"
    execution = _file(execution_root, "a19-observation.json")
    profile = _file(execution_root, "profile.json")
    a26 = _file(a26_root, "a26-observation.json")
    execution_run = _trusted_run(
        ids[0], ids[1], workflow="a19-offhost-role",
        artifact_name=f"a19-offhost-observation-{ids[0]}",
        raw=execution, source=source, protected=True, token=token)
    a26_run = _trusted_run(
        ids[2], ids[3], workflow="a26-a19-observation",
        artifact_name=f"a26-a19-observation-{ids[2]}",
        raw=a26, source=source, protected=True, token=token)
    review = build_a19_a26_review_artifact(
        execution, profile, a26, source_revision=source,
        review_run_id=review_run, trusted_execution_run=execution_run,
        trusted_a26_run=a26_run)
    output = runner_temp / "a19-review" / "a19-review.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(review)
    return hashlib.sha256(review).hexdigest()


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--preflight"]:
            preflight()
            print("protected review preflight: PASS")
        elif sys.argv[1:] == ["--build"]:
            digest = build()
            print("unsigned independent review artifact: " + digest)
        else:
            raise ValueError("preflight or build mode required")
    except Exception as exc:
        print("A19 protected review blocked: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
