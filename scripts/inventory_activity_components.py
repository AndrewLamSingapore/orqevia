"""Index baseline tracked source references without treating presence as operation."""

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "20bdad87a97e649eb751dd6c7add53d3fb9d65fe"
TERMS = {
    "academy": r"academy|training.room",
    "library": r"agent.library|agent.registry|skill.library",
    "tools": r"tool.discovery|tool.eligibility|ConnectorRegistry|register_tool",
    "pockets": r"activity.pocket|pocket.factory",
    "workspaces": r"workspace",
    "coaching": r"coaching|coach",
    "memory": r"memory",
    "evaluation": r"evaluation|assessment|certification",
    "dispatch": r"dispatch|delegation",
    "governance": r"governance|permission|authorization",
    "execution": r"execution|scheduler|worker|queue",
    "retired_references": r"(^|[^A-Za-z0-9_])(PRIME|JARVIS|SSOT|REA|MiroFish)([^A-Za-z0-9_]|$)",
}


def main():
    inventory = {}
    for component, pattern in TERMS.items():
        result = subprocess.run(
            ["git", "grep", "-n", "-I", "-i", "-E", pattern, BASELINE, "--", "."],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        files = {}
        for line in result.stdout.splitlines():
            match = re.match(re.escape(BASELINE) + r":(.+?):(\d+):", line)
            if match:
                files.setdefault(match[1], []).append(int(match[2]))
        inventory[component] = {"file_count": len(files), "references": files}
    value = {
        "baseline_source_revision": BASELINE,
        "classification": "SOURCE_REFERENCE_INDEX_NOT_OPERATIONAL_EVIDENCE",
        "components": inventory,
    }
    destination = ROOT / "docs" / "evidence" / "activity-pocket-source-inventory.json"
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value["file_count"] for key, value in inventory.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
