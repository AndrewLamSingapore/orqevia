"""Fixed29 public-only protected validation for the 20261019 dated batch.

One workflow invocation consumes this exact evidence batch, including failure.
Subsequent runs/attempts are denied. Local audit never emits protected rows.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib import request

from app.agent_registry import load_agent_registry
from scripts.audit_initialization_package import probe_case, ROOT
from scripts.sign_admitted_agent_cases import (
    parse, unchanged_reviewer_code, unchanged_runtime_reviewer_code,
)

REPOSITORY = "AndrewLamSingapore/orqevia"
WORKFLOW = "orqevia-fresh-initialization-validation-20261019.yml"
BATCH = "ce9a3f5a5d5da9180b8b7879a45de180c709a065907d1d76b577b80a153248d1"
PLAN = "governance/agent-cert-initialization-proposed-fields-20261019.json"
IMAGE = "sha256:67af1345345ab8b89b2195507c3ed8343ac1998de79ec81f8494dcaf49346f37"
SOURCE = "767f9451d42c65eb905f2c3e5f816536c4e17982"
VERIFIER = "0c10fca0938eb66280ebb6dedb9008f09f57c8e6"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def local_audit(plan, *, local_audit_at):
    if len(plan["cases"]) != 29 or plan["case_count"] != 29:
        raise ValueError("EXACT_29_CASE_PACKAGE_REQUIRED")
    unchanged_reviewer_code(ROOT, VERIFIER)
    unchanged_runtime_reviewer_code(ROOT, SOURCE)
    seen = set()
    cases_out = []
    for entry in plan["cases"]:
        row = entry["record_established_fields"]
        key = (row["agent_id"], row["capability_id"])
        if key in seen:
            raise ValueError("DUPLICATE_OWNED_PAIR")
        seen.add(key)
        path = ROOT / entry["evidence_directory"] / row["agent_id"]
        probe_case(
            entry,
            (path / "execution.json").read_bytes(),
            (path / "review.json").read_bytes(),
            local_audit_at=local_audit_at,
        )
        cases_out.append(
            {
                "agent_id": row["agent_id"],
                "capability_id": row["capability_id"],
                "original_oracle_validation": "PASS",
            }
        )
    expected = {
        (agent["id"], capability)
        for agent in load_agent_registry()["agents"]
        for capability in agent["capability_requirements"]
    }
    if seen != expected:
        raise ValueError("EXACT_OWNERSHIP_POPULATION_REQUIRED")
    return {
        "schema": "prime.initialization-local-oracle-audit.v1",
        "cases": cases_out,
        "source_closure": "CURRENT_VERIFIER_AND_SOURCE_CLOSURE_PASS",
    }


def guard(env, *, checkout_head, github_read):
    expected = REPOSITORY + "/.github/workflows/" + WORKFLOW + "@refs/heads/main"
    if (
        env.get("GITHUB_REPOSITORY") != REPOSITORY
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("GITHUB_REF_PROTECTED") != "true"
        or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or env.get("GITHUB_WORKFLOW_REF") != expected
        or env.get("GITHUB_RUN_ATTEMPT") != "1"
        or checkout_head != env.get("GITHUB_SHA")
        or env.get("GITHUB_WORKFLOW_SHA") != checkout_head
        or len(checkout_head) != 40
        or any(char not in "0123456789abcdef" for char in checkout_head)
    ):
        raise ValueError("PROTECTED_FIXED_BATCH_GUARD_DENIED")
    run_id = env.get("GITHUB_RUN_ID", "")
    if not run_id.isdecimal():
        raise ValueError("EXACT_RUN_ID_REQUIRED")
    current = github_read("/actions/runs/" + run_id)
    if (
        type(current) is not dict
        or current.get("id") != int(run_id)
        or current.get("head_sha") != checkout_head
        or current.get("head_branch") != "main"
        or current.get("event") != "workflow_dispatch"
        or current.get("run_attempt") != 1
        or current.get("status") != "in_progress"
        or current.get("conclusion") is not None
        or current.get("path") != ".github/workflows/" + WORKFLOW
        or current.get("repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("AUTHENTICATED_RUN_BINDING_DENIED")
    runs = github_read(
        "/actions/workflows/" + WORKFLOW
        + "/runs?event=workflow_dispatch&per_page=100"
    )
    if (
        type(runs) is not dict
        or type(runs.get("total_count")) is not int
        or not 1 <= runs["total_count"] <= 100
        or type(runs.get("workflow_runs")) is not list
        or len(runs["workflow_runs"]) != runs["total_count"]
    ):
        raise ValueError("COMPLETE_BOUNDED_INVOCATION_HISTORY_REQUIRED")
    if len(runs["workflow_runs"]) != 1 or runs["workflow_runs"][0].get("id") != int(run_id):
        raise ValueError("BATCH_PREVIOUS_OR_CONCURRENT_INVOCATION_DENIED")
    return {
        "run_id": int(run_id),
        "run_attempt": 1,
        "source_revision": checkout_head,
        "workflow_ref": expected,
        "batch_sha256": BATCH,
    }


def protected_validation(
    plan, *, env, checkout_head, github_read, clock=lambda: datetime.now(timezone.utc)
):
    provenance = guard(
        env, checkout_head=checkout_head, github_read=github_read
    )
    pairs = sorted(
        (
            entry["record_established_fields"]["agent_id"],
            entry["record_established_fields"]["capability_id"],
            entry["execution_sha256"],
            entry["review_sha256"],
        )
        for entry in plan["cases"]
    )
    digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode()).hexdigest()
    if digest != BATCH:
        raise ValueError("EXACT_ORIGINAL_29_DIGESTSET_REQUIRED")
    if any(
        entry["execution_source_revision"] != SOURCE
        or entry["reviewer_code_revision"] != SOURCE
        or entry["verifier_code_revision"] != VERIFIER
        or entry["runtime_image_id"] != IMAGE
        for entry in plan["cases"]
    ):
        raise ValueError("FIXED_SOURCE_IMAGE_CLOSURE_REQUIRED")
    started = clock()
    result = local_audit(plan, local_audit_at=started)
    boundary = clock()
    if (
        boundary.tzinfo is None
        or started.tzinfo is None
        or not started <= boundary
        or (boundary - started).total_seconds() > 120
    ):
        raise ValueError("PROTECTED_VALIDATION_CLOCK_BOUND_DENIED")
    boundary = boundary.astimezone(timezone.utc)
    expires = boundary + timedelta(hours=24)
    entries = []
    for entry in plan["cases"]:
        row = dict(entry["record_established_fields"])
        row.update(
            certification_test="baseline-initialization",
            test_version=row["review_test_version"],
            certified_at=boundary.isoformat(),
            last_revalidated=boundary.isoformat(),
            expires_at=expires.isoformat(),
        )
        entries.append(
            {
                key: entry[key]
                for key in (
                    "evidence_directory",
                    "execution_sha256",
                    "review_sha256",
                    "execution_source_revision",
                    "runtime_image_id",
                    "reviewer_code_revision",
                    "verifier_code_revision",
                    "cloud_policy",
                    "owner_policy_sha256",
                )
            }
            | {"record": row}
        )
    proposed = {"schema_version": "prime.protected-reviewed-cases.v1", "cases": entries}
    parse(canonical(proposed))
    return {
        "schema": "prime.protected-initialization-validation.v1",
        "provenance": provenance,
        "protected_validation_at": boundary.isoformat(),
        "fixed_expires_at": expires.isoformat(),
        "original_case_count": len(result["cases"]),
        "all_original_oracles": "PASS",
        "proposed_manifest": proposed,
        "proposed_manifest_sha256": hashlib.sha256(canonical(proposed)).hexdigest(),
        "signature": "NOT_PERFORMED",
        "l7_awarded": False,
        "installed": False,
        "rolling_renewal": False,
    }


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def github_reader(token):
    opener = request.build_opener(NoRedirect)
    calls = []

    def read(suffix):
        allowed = {
            "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
            "/actions/workflows/" + WORKFLOW
            + "/runs?event=workflow_dispatch&per_page=100",
        }
        if suffix not in allowed or suffix in calls:
            raise ValueError("FIXED_SINGLE_READ_REQUIRED")
        calls.append(suffix)
        req = request.Request(
            "https://api.github.com/repos/" + REPOSITORY + suffix,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ORQEVIA-fixed29-public-validation-20261019",
            },
        )
        with opener.open(req, timeout=10) as response:
            if response.status != 200:
                raise ValueError("READONLY_GITHUB_RESPONSE_DENIED")
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("GITHUB_RESPONSE_BOUND")
        return json.loads(raw)

    return read


def main():
    out = ROOT / "fresh-initialization-validation-output"
    out.mkdir(exist_ok=False)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            timeout=5,
        ).stdout.decode().strip()
        token = os.environ.get("GH_READ_TOKEN")
        if not isinstance(token, str) or not token:
            raise ValueError("READONLY_WORKFLOW_TOKEN_REQUIRED")
        result = protected_validation(
            json.loads((ROOT / PLAN).read_bytes()),
            env=os.environ,
            checkout_head=head,
            github_read=github_reader(token),
        )
        with (out / "protected-validation.json").open("xb") as stream:
            stream.write(canonical(result))
        print("FIXED_29_VALIDATED_PROPOSED_ROWS_ONLY_NO_SIGNATURE_NO_INSTALL")
    except Exception:
        with (out / "failure.json").open("xb") as stream:
            stream.write(
                canonical(
                    {
                        "state": "REJECTED_OR_UNCERTAIN_BATCH_CONSUMED_NO_RETRY",
                        "batch_sha256": BATCH,
                        "run_id": os.environ.get("GITHUB_RUN_ID"),
                        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                        "signature": "NOT_PERFORMED",
                        "l7_awarded": False,
                    }
                )
            )
        raise SystemExit(
            "Fixed batch validation rejected; original failure preserved, no automatic retry"
        ) from None


if __name__ == "__main__":
    main()
