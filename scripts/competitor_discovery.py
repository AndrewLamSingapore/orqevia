"""Bounded competitor discovery report using the credential-free search adapter.

Output is source data only: titles, URLs and snippets. No verified claims,
no financial or product decisions. Usage:
  python scripts/competitor_discovery.py --topic "autonomous ai workspace" --out report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.web_search import search


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--max-results", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    queries = [
        f"{args.topic} competitors 2026",
        f"{args.topic} market leaders features",
        f"open-source alternative {args.topic}",
    ]
    entries = []
    seen = set()
    for query in queries:
        try:
            result = search(query, args.max_results)
        except RuntimeError as exc:
            print("search unavailable:", exc, file=sys.stderr)
            continue
        for item in result["results"]:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            entries.append({**item, "query": query})
    report = {
        "schema": "orqevia.competitor-discovery.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": args.topic,
        "queries": queries,
        "entries": entries,
        "disclosure": "Retrieved source data only; no verified claims or product decisions.",
    }
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(entries), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
