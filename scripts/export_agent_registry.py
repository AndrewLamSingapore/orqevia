"""Export the deny-by-default public projection for publication consumers."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from app.agent_registry import public_agent_registry

p = argparse.ArgumentParser()
p.add_argument("output", nargs="?", default="public-agent-registry.json")
args = p.parse_args()
payload = public_agent_registry()
body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
Path(args.output).write_text(body, encoding="utf-8")
print(json.dumps({"output": args.output, "sha256": hashlib.sha256(body.encode()).hexdigest(), "agents": len(payload["agents"])}))
