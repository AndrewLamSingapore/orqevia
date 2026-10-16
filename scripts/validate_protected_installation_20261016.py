"""Protected one-shot installation validation for the fresh 20261016 batch.

Independently re-verifies the candidate installation bindings (owned-domain
resolution for all 29 admitted cases), the signed-artifact provenance of run
38871679860, and emits the protected installation receipt. No L7 award, no
runtime activation, no deployment change. Fail-closed; secrets never printed.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "governance/agent-cert-reviewed-cases.json"
CANDIDATE = ROOT / "governance/agent-cert-installation-20261016.json"
OUT = ROOT / "protected-installation-output"
RUN_ID = "38871679860"
ARTIFACT_PREFIX = "prime-independent-signed-cases-8e6cea0c2ef4a1540290e6f203772274d1f352db"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def guard() -> None:
    if not (
        os.environ.get("GITHUB_REPOSITORY") == "AndrewLamSingapore/orqevia"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_REF_PROTECTED") == "true"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    ):
        raise ValueError("GUARD")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - never follow with headers
        return None


def _download(url: str, headers: dict) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
            return response.read(4_000_000)
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        location = error.headers["Location"]
        with urllib.request.urlopen(urllib.request.Request(location), timeout=60) as response:
            return response.read(4_000_000)


def fetch_artifact() -> dict:
    token = os.environ.get("GH_READ_TOKEN")
    if not token:
        raise ValueError("READ_TOKEN_REQUIRED")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    request = urllib.request.Request(
        f"https://api.github.com/repos/AndrewLamSingapore/orqevia/actions/runs/{RUN_ID}/artifacts",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        listing = json.loads(response.read(262144))
    artifact = next((a for a in listing.get("artifacts", []) if a.get("name", "").startswith(ARTIFACT_PREFIX)), None)
    if artifact is None:
        raise ValueError("SIGNED_ARTIFACT_MISSING")
    raw = _download(artifact["archive_download_url"], headers)
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        with bundle.open("signed-cases.json") as stream:
            return json.loads(stream.read(4_000_000))


def main() -> int:
    guard()
    actual = os.popen("git rev-parse HEAD").read().strip()
    expected = os.environ.get("GITHUB_SHA", "")
    if not expected or actual != expected:
        raise SystemExit("CHECKOUT_SHA_MISMATCH")

    manifest = json.loads(MANIFEST.read_bytes())
    candidate = json.loads(CANDIDATE.read_bytes())
    if candidate.get("status", "").split(" ")[0] != "CANDIDATE_INSTALLATION" or candidate.get("record_count") != 29:
        raise SystemExit("CANDIDATE_INVALID")

    from app import agent_cert_initialization as initialization
    from app import agent_registry
    registry_sha = initialization.sha(agent_registry.REGISTRY_PATH.read_bytes())
    if registry_sha != candidate.get("registry_sha256"):
        raise SystemExit("REGISTRY_REVISION_MISMATCH")

    manifest_pairs = {
        (e["record"]["agent_id"], e["record"]["capability_id"]) for e in manifest["cases"]
    }
    candidate_pairs = {(r["agent_id"], r["capability_id"]) for r in candidate["records"]}
    if manifest_pairs != candidate_pairs or len(manifest_pairs) != 29:
        raise SystemExit("CANDIDATE_BINDING_MISMATCH")

    reverified = []
    for record in candidate["records"]:
        domains = initialization._owned_domains(registry_sha, record["agent_id"], record["capability_id"])
        digest = hashlib.sha256(canonical(domains)).hexdigest()
        if digest != (record.get("owned_domain") or {}).get("definition_sha256"):
            raise SystemExit("OWNED_DOMAIN_DIGEST_MISMATCH")
        reverified.append({"agent_id": record["agent_id"], "capability_id": record["capability_id"], "definition_sha256": digest})

    signed = fetch_artifact()
    if signed.get("state") != "SIGNED_CASE_EVIDENCE" or signed.get("signed_case_count") != 29 or signed.get("l7_awarded") is not False:
        raise SystemExit("SIGNED_ARTIFACT_INVALID")
    signed_pairs = {(c.get("agent_id"), c.get("capability_id")) for c in signed["signed_cases"]}
    if signed_pairs != manifest_pairs:
        raise SystemExit("SIGNED_PAIR_MISMATCH")

    payload = {
        "schema": "orqevia.protected-installation.v1",
        "state": "PROTECTED_INSTALLATION_VERIFIED",
        "batch": "fresh29-20261016",
        "signed_run": RUN_ID,
        "signed_artifact": ARTIFACT_PREFIX,
        "protected_source_revision": actual,
        "registry_sha256": registry_sha,
        "record_count": len(reverified),
        "installation_digest": hashlib.sha256(canonical(reverified)).hexdigest(),
        "runtime_activated": False,
        "l7_awarded": False,
        "boundaries": [
            "Evidence binding only; not L7 and not capability certification",
            "No runtime activation and no deployment change",
        ],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "protected-installation.json").write_bytes(canonical(payload))
    print(json.dumps({"state": payload["state"], "records": payload["record_count"], "digest": payload["installation_digest"][:24]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
