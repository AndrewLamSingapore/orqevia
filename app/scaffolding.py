"""AI Scaffolding Engine - permanent ORQEVIA subsystem.

Generates reviewable software-construction artifacts (projects, agents,
skills, knowledge/RAG applications, geospatial applications, God's Eye
adapters, infrastructure, verification suites and repair plans).

The engine is intentionally a *generator and validator only*:

* It never grants execution authority. Generated agents and skills default to
  ``advisory_only`` with no tool grants and human approval required for any
  execution, matching the ORQEVIA fail-closed posture.
* It never deploys, never talks to the network and never spawns subprocesses.
* It never overwrites existing files and refuses to write outside the target
  directory. Generated code must enter the normal reviewable change process.

This is a subsystem, not a second authority: it emits proposals that flow
through the existing skill router, Academy and agent-registry mechanisms.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


SCAFFOLD_VERSION = "1.0.0"
ENGINE_NAME = "orqevia.scaffolding"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "artifact"


class ScaffoldError(ValueError):
    """Raised when a scaffold specification is invalid or unsafe."""


@dataclass(frozen=True)
class ScaffoldResult:
    """A generated artifact set plus its provenance."""

    kind: str
    artifact_id: str
    files: Mapping[str, str]
    warnings: Tuple[str, ...] = ()
    template_version: str = SCAFFOLD_VERSION
    generated_at: str = field(default_factory=_utcnow_iso)

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for name in sorted(self.files):
            digest.update(name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(self.files[name].encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def to_json(self) -> str:
        return _json_pretty(
            {
                "engine": ENGINE_NAME,
                "template_version": self.template_version,
                "generated_at": self.generated_at,
                "kind": self.kind,
                "artifact_id": self.artifact_id,
                "fingerprint": self.fingerprint(),
                "warnings": list(self.warnings),
                "files": {name: _sha256(content) for name, content in self.files.items()},
            }
        )


# ---------------------------------------------------------------------------
# Spec validation (small, explicit schema instead of a new dependency)
# ---------------------------------------------------------------------------

_PRIMITIVES = {
    "str": str,
    "int": int,
    "bool": bool,
    "list": list,
    "dict": dict,
}


def _matches(value: Any, type_name: str) -> bool:
    if type_name in _PRIMITIVES:
        return isinstance(value, _PRIMITIVES[type_name])
    if type_name == "str_or_none":
        return value is None or isinstance(value, str)
    if type_name == "list_of_str":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if type_name == "list_of_dict":
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    raise ScaffoldError(f"unknown schema type: {type_name}")


def validate_spec(spec: Mapping[str, Any], schema: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate *spec* against a declarative field schema.

    Each schema entry maps a field name to ``{"type": ..., "required": bool}``.
    Returns a shallow copy of the spec (so callers cannot mutate the input).
    """
    if not isinstance(spec, Mapping):
        raise ScaffoldError("spec must be a mapping")
    errors: List[str] = []
    for name, rule in schema.items():
        if not isinstance(rule, Mapping) or "type" not in rule:
            raise ScaffoldError(f"bad schema rule for field {name!r}")
        if rule.get("required", False) and name not in spec:
            errors.append(f"missing required field {name!r}")
            continue
        if name in spec and not _matches(spec[name], rule["type"]):
            errors.append(f"field {name!r} must be {rule['type']}")
    if errors:
        raise ScaffoldError("; ".join(errors))
    return dict(spec)


# ---------------------------------------------------------------------------
# Secret scanning (generated artifacts must not embed credentials)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-./+]{16,}[\"']")),
)


def scan_secrets(text: str) -> List[str]:
    """Return pattern names matched in *text*; empty means no credentials found."""
    return [name for name, pattern in _SECRET_PATTERNS if pattern.search(text)]


def _assert_no_secrets(files: Mapping[str, str]) -> None:
    for name, content in files.items():
        matches = scan_secrets(content)
        if matches:
            raise ScaffoldError(f"refusing to scaffold {name!r}: credential-like content ({', '.join(matches)})")


# ---------------------------------------------------------------------------
# Materialization (writes only, with traversal + overwrite guards)
# ---------------------------------------------------------------------------

def materialize(result: ScaffoldResult, target_dir: str, overwrite: bool = False) -> List[Path]:
    """Write a ScaffoldResult to disk and return the written paths.

    Fails closed: refuses to overwrite existing files by default and refuses
    any path that escapes *target_dir*.
    """
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for rel_name, content in result.files.items():
        rel = Path(rel_name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ScaffoldError(f"unsafe artifact path: {rel_name!r}")
        dest = (target / rel).resolve()
        if not dest.is_relative_to(target):
            raise ScaffoldError(f"artifact path escapes target directory: {rel_name!r}")
        if dest.exists() and not overwrite:
            raise ScaffoldError(f"refusing to overwrite existing file: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        written.append(dest)
    return written


def _files(*pairs: Tuple[str, str]) -> Dict[str, str]:
    return dict(pairs)


# ---------------------------------------------------------------------------
# Factory 1: Project Factory
# ---------------------------------------------------------------------------

_PROJECT_SCHEMA = {
    "name": {"type": "str", "required": True},
    "description": {"type": "str_or_none", "required": False},
    "port": {"type": "int", "required": False},
    "include_db": {"type": "bool", "required": False},
}


def generate_project(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _PROJECT_SCHEMA)
    name = s["name"]
    slug = _slugify(name)
    description = s.get("description") or f"{name} - generated by ORQEVIA scaffolding"
    port = s.get("port", 8000)
    include_db = s.get("include_db", True)

    files: Dict[str, str] = {}
    files["README.md"] = (
        f"# {name}\n\n{description}\n\n"
        f"Generated by the ORQEVIA AI Scaffolding Engine (v{SCAFFOLD_VERSION}).\n"
        "This is a candidate artifact: review and test it before any deployment.\n"
    )
    files["config/app.json"] = _json_pretty(
        {
            "name": name,
            "slug": slug,
            "description": description,
            "port": port,
            "include_db": include_db,
            "scaffold": {"engine": ENGINE_NAME, "version": SCAFFOLD_VERSION, "generated_at": _utcnow_iso()},
        }
    )
    files["backend/app.py"] = (
        "import json\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n\n"
        f"PORT = {port}\n\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/health':\n"
        "            body = json.dumps({'status': 'ok'}).encode()\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type', 'application/json')\n"
        "            self.end_headers()\n"
        "            self.wfile.write(body)\n"
        "        else:\n"
        "            self.send_response(404)\n"
        "            self.end_headers()\n\n\n"
        "if __name__ == '__main__':\n"
        f"    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()\n"
    )
    files["frontend/index.html"] = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{name}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <main><h1>{name}</h1><p>{description}</p></main>\n"
        "</body>\n"
        "</html>\n"
    )
    files["frontend/app.js"] = (
        "// Frontend entry point (candidate artifact).\n"
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  console.info('ORQEVIA scaffolded frontend ready');\n"
        "});\n"
    )
    if include_db:
        files["backend/db/models.py"] = (
            '"Minimal, provider-neutral data model. Swap in your ORM of choice."\n\n'
            "TABLES = ['item']\n\n"
            "SCHEMA = {\n"
            "    'item': [\n"
            "        ('id', 'TEXT PRIMARY KEY'),\n"
            "        ('created_at', 'TEXT NOT NULL'),\n"
            "    ],\n"
            "}\n"
        )
        files["backend/db/migrations/0001_init.sql"] = (
            "-- Candidate migration; review before applying.\n"
            "CREATE TABLE IF NOT EXISTS item (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    created_at TEXT NOT NULL\n"
            ");\n"
        )
    files["tests/test_app.py"] = (
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\n"
        "from backend.app import PORT, Handler\n\n\n"
        "def test_health_endpoint_contract():\n"
        "    assert PORT > 0\n"
        "    assert callable(Handler)\n"
    )
    files["deploy/Dockerfile"] = (
        "FROM python:3.12-slim\n"
        "WORKDIR /srv/app\n"
        "COPY . .\n"
        "EXPOSE " + str(port) + "\n"
        "CMD [\"python\", \"backend/app.py\"]\n"
    )
    files["deploy/healthcheck.sh"] = (
        "#!/bin/sh\n"
        "# Candidate health check; review for your environment.\n"
        f"curl -fsS http://127.0.0.1:{port}/health || exit 1\n"
    )
    files[".env.example"] = (
        "# No real credentials belong in generated templates.\n"
        f"PORT={port}\n"
        "DATABASE_URL=\n"
    )
    files["docs/ARCHITECTURE.md"] = (
        f"# {name} architecture\n\n"
        "Generated skeleton: frontend (static), backend (HTTP), optional database.\n"
        "Review every file; nothing here is production-ready by virtue of generation.\n"
    )

    _assert_no_secrets(files)
    return ScaffoldResult(kind="project", artifact_id=slug, files=files)


# ---------------------------------------------------------------------------
# Factory 2: Agent Factory
# ---------------------------------------------------------------------------

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9.-]{1,63}$")

_AGENT_SCHEMA = {
    "agent_id": {"type": "str", "required": True},
    "name": {"type": "str", "required": True},
    "role": {"type": "str", "required": True},
    "description": {"type": "str_or_none", "required": False},
    "capabilities": {"type": "list_of_str", "required": True},
    "tools": {"type": "list_of_str", "required": False},
    "timeout_seconds": {"type": "int", "required": False},
}


def generate_agent(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _AGENT_SCHEMA)
    agent_id = s["agent_id"]
    if not _AGENT_ID_RE.match(agent_id):
        raise ScaffoldError("agent_id must be lowercase letters/digits/hyphens, 1-32 chars")

    agent_spec = {
        "identity": {"id": agent_id, "name": s["name"], "role": s["role"]},
        "description": s.get("description") or f"{s['name']} ({s['role']})",
        "capability_declaration": sorted(s["capabilities"]),
        "tools": sorted(s.get("tools", [])),
        "permissions": [],
        "resource_limits": {"timeout_seconds": s.get("timeout_seconds", 300), "max_subagents": 0},
        "execution_authority": "none",
        "advisory_only": True,
        "human_approval": "required_for_execution",
        "delegation_rules": {"allow_delegation": False},
        "success_criteria": [],
        "failure_behavior": "fail_closed",
        "status": "DRAFT_CANDIDATE",
        "scaffold": {"engine": ENGINE_NAME, "version": SCAFFOLD_VERSION, "generated_at": _utcnow_iso()},
    }
    files = _files(
        (f"agents/{agent_id}/agent.json", _json_pretty(agent_spec)),
        (
            f"agents/{agent_id}/test_agent.py",
            f"def test_{agent_id.replace('-', '_')}_is_fail_closed():\n"
            "    import json\n"
            "    from pathlib import Path\n"
            "    spec = json.loads(Path(__file__).with_name('agent.json').read_text(encoding='utf-8'))\n"
            "    assert spec['execution_authority'] == 'none'\n"
            "    assert spec['advisory_only'] is True\n"
            "    assert spec['human_approval'] == 'required_for_execution'\n",
        ),
        (
            f"agents/{agent_id}/evaluation.md",
            f"# Evaluation package - {agent_id}\n\n"
            "Candidate evaluation plan. Academy execution and promotion remain"
            " governed by the established authority mechanisms.\n",
        ),
        (
            f"agents/{agent_id}/registration-proposal.md",
            f"# Registration proposal - {agent_id}\n\n"
            "Submit through the existing agent-registry mechanism; this file is a"
            " proposal, not an authoritative registry entry.\n",
        ),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(
        kind="agent",
        artifact_id=agent_id,
        files=files,
        warnings=("generated agents are advisory-only by default; activation is a separate authority decision",),
    )


# ---------------------------------------------------------------------------
# Factory 3: Skill Factory
# ---------------------------------------------------------------------------

_SKILL_SCHEMA = {
    "skill_id": {"type": "str", "required": True},
    "name": {"type": "str", "required": True},
    "description": {"type": "str", "required": True},
    "capabilities": {"type": "list_of_str", "required": False},
}


def generate_skill(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _SKILL_SCHEMA)
    skill_id = s["skill_id"]
    if not _SKILL_ID_RE.match(skill_id):
        raise ScaffoldError("skill_id must be lowercase letters/digits/dots/hyphens, 1-64 chars")
    skill_spec = {
        "id": skill_id,
        "name": s["name"],
        "description": s["description"],
        "capability_requirements": sorted(s.get("capabilities", [])),
        "required_tools": [],
        "authority": "advisory_only",
        "status": "DRAFT_CANDIDATE",
        "version": "0.1.0",
    }
    files = _files(
        (f"skills/{skill_id}/SKILL.md", f"# {s['name']}\n\n{s['description']}\n"),
        (f"skills/{skill_id}/skill.json", _json_pretty(skill_spec)),
        (
            f"skills/{skill_id}/tests/test_skill.py",
            "def test_skill_is_advisory_only():\n"
            "    import json\n"
            "    from pathlib import Path\n"
            "    spec = json.loads((Path(__file__).resolve().parent.parent / 'skill.json').read_text(encoding='utf-8'))\n"
            "    assert spec['authority'] == 'advisory_only'\n"
            "    assert spec['required_tools'] == []\n",
        ),
        (
            f"skills/{skill_id}/evaluation/hook.py",
            "def evaluate(evidence):\n"
            "    \"\"\"Academy evaluation hook stub - replace with real criteria.\"\"\"\n"
            "    return {'qualified': False, 'reason': 'not_evaluated'}\n",
        ),
        (
            f"skills/{skill_id}/evidence/capture.md",
            "# Evidence capture\n\nRecord per-run evidence here; never fabricate receipts.\n",
        ),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(kind="skill", artifact_id=skill_id, files=files)


# ---------------------------------------------------------------------------
# Factory 4: Knowledge (RAG) Factory
# ---------------------------------------------------------------------------

_APP_SCHEMA = {
    "app_name": {"type": "str", "required": True},
    "description": {"type": "str_or_none", "required": False},
}


def generate_knowledge_app(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _APP_SCHEMA)
    name = _slugify(s["app_name"])
    files = _files(
        (f"{name}/ingestion.py", "def ingest(document):\n    return {'source': document}\n"),
        (
            f"{name}/retrieval.py",
            "def retrieve(query, allowed_sources):\n"
            "    # Permission-filtered retrieval stub; do not bypass access controls.\n"
            "    return [item for item in allowed_sources if query.lower() in item.lower()]\n",
        ),
        (
            f"{name}/provenance.py",
            "def cite(result):\n"
            "    return {'source': result.get('source'), 'passage': result.get('passage')}\n",
        ),
        (
            f"{name}/access_control.py",
            "def visible_sources(identity):\n"
            "    return identity.get('allowed_sources', [])\n",
        ),
        (
            f"{name}/tests/test_rag.py",
            "def test_retrieval_respects_allowlist():\n"
            "    from retrieval import retrieve\n"
            "    assert retrieve('a', ['a', 'b']) == ['a']\n"
            "    assert retrieve('z', ['a', 'b']) == []\n",
        ),
        (
            f"{name}/fixtures/queries.jsonl",
            '{"query": "example", "allowed_sources": ["example"]}\n',
        ),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(kind="knowledge", artifact_id=name, files=files)


# ---------------------------------------------------------------------------
# Factory 5: Geospatial Factory
# ---------------------------------------------------------------------------

def generate_geospatial_app(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _APP_SCHEMA)
    name = _slugify(s["app_name"])
    files = _files(
        (f"{name}/crs.py", "def validate_wgs84(lat, lon):\n    if not (-90 <= lat <= 90 and -180 <= lon <= 180):\n        raise ValueError('coordinate out of range')\n    return lat, lon\n"),
        (
            f"{name}/spatial_schema.sql",
            "-- Candidate spatial schema; review before applying.\n"
            "CREATE TABLE place (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    name TEXT NOT NULL,\n"
            "    geom TEXT NOT NULL\n"
            ");\n",
        ),
        (f"{name}/api.py", "def near(point, radius_km):\n    return []\n"),
        (f"{name}/map.html", "<!doctype html><title>map</title><div id=\"map\"></div>\n"),
        (
            f"{name}/tests/test_spatial.py",
            "import pytest\nfrom crs import validate_wgs84\n\ndef test_wgs84_validation():\n"
            "    assert validate_wgs84(1.35, 103.82) == (1.35, 103.82)\n"
            "    with pytest.raises(ValueError):\n        validate_wgs84(99.0, 103.0)\n",
        ),
        (f"{name}/fixtures/points.json", _json_pretty([{"name": "Singapore", "lat": 1.3521, "lon": 103.8198}])),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(kind="geospatial", artifact_id=name, files=files)


# ---------------------------------------------------------------------------
# Factory 6: God's Eye adapter Factory
# ---------------------------------------------------------------------------

def generate_gods_eye_adapter(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _APP_SCHEMA)
    name = _slugify(s["app_name"])
    adapter_spec = {
        "adapter": name,
        "target": "orqevia.gods-eye",
        "mode": "read_only",
        "fail_closed": True,
        "no_actuation": True,
    }
    files = _files(
        (f"{name}/adapter.json", _json_pretty(adapter_spec)),
        (
            f"{name}/adapter.py",
            "class GodsEyeAdapter:\n"
            "    def __init__(self):\n"
            "        self.fail_closed = True\n\n"
            "    def observe(self, query):\n"
            "        if self.fail_closed:\n"
            "            return {'status': 'unavailable'}\n"
            "        return {}\n",
        ),
        (
            f"{name}/tests/test_adapter.py",
            "def test_adapter_fails_closed():\n"
            "    from adapter import GodsEyeAdapter\n"
            "    assert GodsEyeAdapter().observe('x') == {'status': 'unavailable'}\n",
        ),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(kind="gods_eye_adapter", artifact_id=name, files=files)


# ---------------------------------------------------------------------------
# Factory 7: Infrastructure Factory
# ---------------------------------------------------------------------------

_INFRA_SCHEMA = {
    "service_name": {"type": "str", "required": True},
    "port": {"type": "int", "required": False},
}


def generate_infrastructure(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _INFRA_SCHEMA)
    name = _slugify(s["service_name"])
    port = s.get("port", 8000)
    files = _files(
        (f"{name}/Dockerfile", "FROM python:3.12-slim\nWORKDIR /srv/app\nCOPY . .\nEXPOSE " + str(port) + "\n"),
        (
            f"{name}/docker-compose.yml",
            f"services:\n  {name}:\n    build: .\n    ports:\n      - \"{port}:{port}\"\n",
        ),
        (f"{name}/.env.example", f"PORT={port}\n# Add non-secret configuration only.\n"),
        (
            f"{name}/ci.yml",
            "name: CI\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n      - run: python -m pytest -q\n",
        ),
        (
            f"{name}/observability.json",
            _json_pretty({"logging": "structured", "tracing": "correlation_id", "redaction": "enabled"}),
        ),
        (
            f"{name}/rollback.md",
            "# Rollback procedure\n\n1. Revert the release commit/tag.\n2. Restore the previous image.\n3. Re-run smoke tests.\n",
        ),
    )
    _assert_no_secrets(files)
    return ScaffoldResult(kind="infrastructure", artifact_id=name, files=files)


# ---------------------------------------------------------------------------
# Factory 8: Verification Factory
# ---------------------------------------------------------------------------

_VERIFY_TARGET_SCHEMA = {"target_name": {"type": "str", "required": True}}


def generate_verification(spec: Mapping[str, Any]) -> ScaffoldResult:
    s = validate_spec(spec, _VERIFY_TARGET_SCHEMA)
    name = _slugify(s["target_name"])
    suites = {
        "test_unit.py": "def test_unit_placeholder():\n    assert True\n",
        "test_integration.py": "def test_integration_placeholder():\n    assert True\n",
        "test_contract.py": "def test_contract_placeholder():\n    assert True\n",
        "test_regression.py": "def test_regression_placeholder():\n    assert True\n",
        "test_e2e.py": "def test_e2e_placeholder():\n    assert True\n",
        "test_security.py": "def test_security_placeholder():\n    assert True\n",
        "test_recovery.py": "def test_recovery_placeholder():\n    assert True\n",
    }
    files = {f"{name}/tests/{filename}": content for filename, content in suites.items()}
    files[f"{name}/build_verify.sh"] = "#!/bin/sh\nset -e\npython -m pytest -q\n"
    _assert_no_secrets(files)
    return ScaffoldResult(
        kind="verification",
        artifact_id=name,
        files=files,
        warnings=("placeholders are explicit; replace with real acceptance criteria before promotion",),
    )


# ---------------------------------------------------------------------------
# Factory 9: Repair and Extension Factory (read-only plan)
# ---------------------------------------------------------------------------

def plan_repair(project_dir: str) -> str:
    """Inspect *project_dir* read-only and return a Markdown impact-analysis plan.

    Never edits files. The returned plan is a starting point for a controlled,
    reviewable modification workflow.
    """
    root = Path(project_dir).resolve()
    if not root.is_dir():
        raise ScaffoldError(f"project directory not found: {root}")
    entries: List[str] = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts:
            continue
        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = -1
            entries.append(f"- `{path.relative_to(root)}` ({size} bytes)")
    listing = "\n".join(entries) or "- (no files)"
    return (
        "# Repair and extension plan\n\n"
        f"Project: `{root}`\n\n"
        "## Observed files\n\n"
        f"{listing}\n\n"
        "## Proposed changes\n\n"
        "1. (describe the defect or extension and its impact)\n"
        "2. (list affected files and interfaces)\n"
        "3. (define regression tests to run before and after)\n\n"
        "## Safety\n\n"
        "Never silently overwrite unrelated work. Run the verification suite before"
        " and after; keep the change reviewable and reversible.\n"
    )


# ---------------------------------------------------------------------------
# Engine facade
# ---------------------------------------------------------------------------

class ScaffoldingEngine:
    """Thin, side-effect-free facade over the individual factories."""

    name = ENGINE_NAME
    version = SCAFFOLD_VERSION

    def project(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_project(spec)

    def agent(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_agent(spec)

    def skill(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_skill(spec)

    def knowledge(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_knowledge_app(spec)

    def geospatial(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_geospatial_app(spec)

    def gods_eye_adapter(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_gods_eye_adapter(spec)

    def infrastructure(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_infrastructure(spec)

    def verification(self, spec: Mapping[str, Any]) -> ScaffoldResult:
        return generate_verification(spec)

    def repair_plan(self, project_dir: str) -> str:
        return plan_repair(project_dir)


engine = ScaffoldingEngine()

