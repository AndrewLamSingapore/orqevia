"""Curated public-safe external platform registry (observed, not endorsed)."""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "config" / "platform-registry.json"


def load_platforms() -> list:
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    platforms = data.get("platforms", [])
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("platform registry unavailable")
    for entry in platforms:
        if not all(key in entry for key in ("id", "name", "category", "source_url")):
            raise ValueError("platform entry missing required fields")
        if not str(entry["source_url"]).startswith("https://"):
            raise ValueError("platform source_url must be https")
    return platforms


def public_platforms() -> list:
    """Sanitized public projection: identity and category only."""
    return [
        {"id": entry["id"], "name": entry["name"], "category": entry["category"],
         "source_url": entry["source_url"], "notes": entry.get("notes", "")[:200]}
        for entry in load_platforms()
    ]
