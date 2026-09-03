"""Export the deny-by-default public projection for publication consumers."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# A script launched as `python scripts/export_agent_registry.py` gets `scripts/`
# on sys.path rather than the repository root. Add the root explicitly so the
# canonical `app` package resolves identically in local shells and GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_registry import public_agent_registry

p = argparse.ArgumentParser()
p.add_argument("output", nargs="?", default="public-agent-registry.json")
args = p.parse_args()
payload = public_agent_registry()
body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
Path(args.output).write_text(body, encoding="utf-8")
print(json.dumps({
    "output": args.output,
    "sha256": hashlib.sha256(body.encode()).hexdigest(),
    "agents": len(payload["agents"]),
    "relationships": len(payload.get("relationships", [])),
}))
