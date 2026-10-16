"""Installation-round CANDIDATE runner for the signed fresh 20261016 batch.

Binds each of the 29 signed initialization cases to its agent-owned domain
(resolved by the unchanged initialization module) and emits the dated
installation evidence file. Candidate-only: it performs no runtime activation,
awards no L7, and is recorded as CLAIMED until a protected round verifies it.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SIGNED = pathlib.Path(
    r"C:\Users\Admin\Documents\ABEX\operations\fresh29-20261016\signed-cases\extracted\signed-cases.json"
)
OUT = ROOT / "governance" / "agent-cert-installation-20261016.json"


def owned_domain(registry_sha: str, agent: str, capability: str) -> dict | None:
    try:
        import hashlib
        import json as _json
        from app import agent_cert_initialization as initialization
        domains = initialization._owned_domains(registry_sha, agent, capability)
        canonical = _json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
        return {
            "definition_sha256": hashlib.sha256(canonical).hexdigest(),
            "definition_keys": sorted(domains.keys()) if isinstance(domains, dict) else None,
        }
    except Exception:
        return None


def main() -> int:
    signed = json.loads(SIGNED.read_bytes())
    cases = signed["signed_cases"]
    from app import agent_cert_initialization as initialization
    registry_sha = initialization.sha(
        (ROOT / "config" / "agent_registry.json").read_bytes()
    )
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    records = []
    unresolved = []
    for case in cases:
        agent = str(case.get("agent_id"))
        capability = str(case.get("capability_id"))
        domain = owned_domain(registry_sha, agent, capability)
        if domain is None:
            unresolved.append({"agent_id": agent, "capability_id": capability})
        records.append({
            "agent_id": agent,
            "capability_id": capability,
            "dimension": case.get("dimension"),
            "test_case": case.get("test_case"),
            "owned_domain": domain,
            "owned_domain_note": "definition digest of the module-resolved owned domain; full definition stays registry-owned",
            "case_signature_present": bool(case.get("signature") or case.get("attestation") or case.get("signed")),
            "runtime_activated": False,
            "l7_awarded": False,
        })
    doc = {
        "schema": "orqevia.agent-cert-installation.v1",
        "status": "CANDIDATE_INSTALLATION — CLAIMED, NOT PROTECTED-EXECUTED",
        "batch": "fresh29-20261016",
        "batch_digest": signed.get("signed_case_count") and "a7eea39dbfb8376915efbef6e7928e47db90eb0a3d3fbd4353bedb3647232b1f",
        "signed_run": "38871679860",
        "registry_sha256": registry_sha,
        "installed_at_utc": now,
        "record_count": len(records),
        "unresolved_domains": unresolved,
        "records": records,
        "boundaries": [
            "Not L7 and not capability certification; installation is an evidence binding only",
            "No runtime activation, no flag changes, no production mutation",
            "A protected installation round must independently verify this candidate before any acceptance",
        ],
    }
    OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({"records": len(records), "unresolved": len(unresolved), "out": str(OUT)}))
    return 0 if not unresolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
