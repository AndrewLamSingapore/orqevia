"""Generate/check the ten versioned Activity Pocket JSON schemas from runtime models."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.activity_pockets.contracts import SCHEMAS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = ROOT / "contracts" / "activity-pockets-v1"
    if not args.check:
        root.mkdir(parents=True, exist_ok=True)
    for model in SCHEMAS:
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = "https://orqevia.local/contracts/activity-pockets/v1/" + model.__name__
        raw = json.dumps(value, indent=2, sort_keys=True) + "\n"
        path = root / (model.__name__ + ".schema.json")
        if args.check:
            if path.read_text(encoding="utf-8") != raw:
                raise SystemExit("Schema differs from runtime contract: " + model.__name__)
        else:
            path.write_text(raw, encoding="utf-8", newline="\n")
    print("10 shared contracts match runtime validation")


if __name__ == "__main__":
    main()
