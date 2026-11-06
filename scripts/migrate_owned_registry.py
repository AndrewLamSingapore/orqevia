"""Explicit release-only migration of existing collective source mirrors.

No HTTP endpoint, new tenant, tool authority, user claim or financial setting is
created. Without --apply, only the existing database's scope count is inspected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from app.collective_intelligence import CollectivePrincipal, CollectiveStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        scopes = db.execute(
            "SELECT tenant_id,owner_id FROM registry_records WHERE id='canonical-registry' ORDER BY tenant_id,owner_id"
        ).fetchall()
    if not args.apply:
        print(json.dumps({"status": "READ_ONLY_PLAN", "existing_scopes": len(scopes)}))
        return 0
    store = CollectiveStore(path)
    results = []
    for tenant, owner in scopes:
        principal = CollectivePrincipal(tenant, owner, "owner-release-registry-migration", roles=frozenset({"SYSTEM"}))
        if not store.integrity(principal)["pass"]:
            raise RuntimeError("Existing scoped integrity does not pass; original records preserved")
        result = store.migrate_canonical_registry(principal, expected_source_sha256=args.expected_source_sha256)
        if not store.integrity(principal)["pass"]:
            raise RuntimeError("Post-migration integrity does not pass; retain all release evidence")
        results.append(result)
    print(json.dumps({"status": "PASS", "existing_scopes": len(scopes), "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
