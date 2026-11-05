"""Verify product source integrity without historical organization or runtime claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def component_hash_matches(path: Path, expected: str) -> bool:
    """Treat checkout newline conversion separately from changed file content."""
    raw = path.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return any(hashlib.sha256(value).hexdigest() == expected for value in (raw, lf, crlf))


def validate_state(product: dict, registry: dict) -> bool:
    assert product["product"] == "ORQEVIA"
    assert product["execution_model"] == "DIRECT_TASK_DISPATCH"
    assert product["verification_scope"] == "SOURCE_INTEGRITY_ONLY"
    components = product["components"]
    assert {"registry", "interface", "task", "artifact"} <= components.keys()
    assert components["registry"]["path"] == "config/agent_registry.json"
    for item in components.values():
        assert isinstance(item, dict) and isinstance(item.get("path"), str)
        assert re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))
    agents = registry["agents"]
    assert isinstance(agents, list) and agents, "Capability inventory must not be empty"
    identities = [agent["agent_id"] for agent in agents]
    assert all(isinstance(value, str) and value for value in identities)
    assert len(identities) == len(set(identities)), "Capability identities must be unique"
    capabilities = []
    for agent in agents:
        owned = agent["capability_requirements"]
        assert isinstance(owned, list) and owned
        assert all(isinstance(value, str) and value for value in owned)
        capabilities.extend(owned)
    assert len(capabilities) == len(set(capabilities)), "Capability ownership must be unambiguous"
    return True


def validate_source(root: Path = ROOT) -> dict:
    root = root.resolve()
    product = json.loads((root / "system.manifest.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "config/agent_registry.json").read_text(encoding="utf-8"))
    validate_state(product, registry)
    for item in product["components"].values():
        target = (root / item["path"]).resolve()
        assert target.is_relative_to(root), "Component path must stay within this source tree"
        assert target.is_file(), "Required source component is missing"
        assert component_hash_matches(target, item["sha256"]), "Source component integrity mismatch"
    return {
        "status": "PASS",
        "scope": "SOURCE_INTEGRITY_NOT_DEPLOYMENT",
        "registry_agents": len(registry["agents"]),
        "components_checked": len(product["components"]),
    }


def main():
    result = validate_source()
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
