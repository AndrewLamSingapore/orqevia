"""Audit installed package versions against OSV; no source or secrets are sent."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def audit(packages):
    queries = [{"package": {"name": name, "ecosystem": "PyPI"}, "version": version} for name, version in packages]
    error_type = None
    for attempt in range(3):
        try:
            response = httpx.post("https://api.osv.dev/v1/querybatch", json={"queries": queries}, timeout=30)
            response.raise_for_status()
            results = response.json()["results"]
            if not isinstance(results, list) or len(results) != len(packages):
                raise ValueError("incomplete advisory response")
            if any(not isinstance(r, dict) or r.get("next_page_token") for r in results):
                raise ValueError("incomplete advisory page")
            findings = [{"name": p[0], "version": p[1], "advisories": r["vulns"]}
                        for p, r in zip(packages, results) if r.get("vulns")]
            return {"status": "FINDINGS" if findings else "NO_KNOWN_FINDINGS",
                    "packages_checked": len(packages), "findings": findings}
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            error_type = type(exc).__name__
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {"status": "UNVERIFIED", "packages_checked": 0, "reason": error_type}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packages = sorted({(d.metadata["Name"], d.version) for d in importlib.metadata.distributions()})
    result = {**audit(packages), "source": "https://api.osv.dev/v1/querybatch",
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "scope": "installed environment only; not production qualification"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "findings"}))
    return 0 if result["status"] == "NO_KNOWN_FINDINGS" else 1 if result["status"] == "FINDINGS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
