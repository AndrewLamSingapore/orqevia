from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import commit_work_unit, synchronize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize validated Dell work with canonical GitHub refs")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-unit", type=Path, help="commit and publish one explicit validated work unit")
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args(argv)
    result = (
        commit_work_unit(args.config, args.work_unit)
        if args.work_unit
        else synchronize(args.config, fetch=not args.no_fetch)
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["overall"] in {"PASS", "PENDING"} else 2
