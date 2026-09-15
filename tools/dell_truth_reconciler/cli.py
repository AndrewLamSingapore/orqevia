from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import reconcile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently reconcile PRIME truth on Dell")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fetch", action="store_true", help="refresh remote refs non-destructively")
    parser.add_argument("--repair", action="store_true", help="perform bounded derived-state repair")
    args = parser.parse_args(argv)
    result = reconcile(args.config, fetch=args.fetch, repair=args.repair)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if result["overall_health"] == "RED" else 0
