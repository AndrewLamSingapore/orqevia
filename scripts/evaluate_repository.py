"""Run existing checks in one explicitly authorized owning repository."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.repository_evaluation import evaluate, profile_checks, verify_receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--profile", choices=("python", "node", "static-web"))
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--verify", type=Path, help="independently rescan a saved execution directory")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify_receipt(args.verify)
    else:
        if not all((args.repository, args.profile, args.evidence_root)):
            parser.error("select --repository, --profile and --evidence-root")
        root = args.repository.resolve(strict=True)
        result = evaluate(root, args.evidence_root, profile_checks(root, args.profile))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
