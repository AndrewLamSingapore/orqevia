"""Native runtime configuration has no process-wide legacy compatibility hook."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def test_application_import_leaves_standard_environment_lookup_unchanged():
    program = """
import json, os
original = os.getenv
import app
assert os.getenv is original
assert os.getenv('PRIME_DATA_DIR') is None
print(json.dumps({'current': os.getenv('ORQEVIA_DATA_DIR')}))
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PRIME_")}
    environment["ORQEVIA_DATA_DIR"] = "native-data-root"
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {"current": "native-data-root"}


def test_legacy_catalog_does_not_redirect_native_provider_configuration(monkeypatch, tmp_path):
    from app.compute_catalog import load_catalog

    monkeypatch.delenv("ORQEVIA_PROVIDER_CATALOG", raising=False)
    monkeypatch.setenv("PRIME_PROVIDER_CATALOG", str(tmp_path / "retired-catalog.json"))
    assert load_catalog() == []


def test_native_spine_does_not_implicitly_inherit_legacy_database(tmp_path):
    from app.spine import SpineStore

    legacy = tmp_path / "prime-spine.db"
    with sqlite3.connect(legacy) as database:
        database.execute("CREATE TABLE legacy_only(value TEXT)")
        database.execute("INSERT INTO legacy_only VALUES('preserve historical bytes')")
    original_digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
    current = tmp_path / "orqevia-spine.db"
    store = SpineStore(str(current))
    with store.connect() as database:
        assert database.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_only'").fetchone() is None
        assert database.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == original_digest


@pytest.mark.parametrize("consumer", ["memory", "notebooks", "survival"])
def test_native_memory_consumers_preserve_but_do_not_inherit_legacy_bytes(consumer, monkeypatch, tmp_path):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ORQEVIA_MEMORY_DB", raising=False)
    legacy = tmp_path / "jarvis-memory.db"
    with sqlite3.connect(legacy) as database:
        database.execute("CREATE TABLE legacy_only(value TEXT)")
        database.execute("INSERT INTO legacy_only VALUES('historical memory')")
    original_digest = hashlib.sha256(legacy.read_bytes()).hexdigest()

    if consumer == "memory":
        from app.memory import MemoryStore

        store = MemoryStore()
    elif consumer == "notebooks":
        from app.agent_notebooks import AgentNotebookStore

        store = AgentNotebookStore(embedder=lambda text: [1.0, 0.0])
    else:
        from app import production_survival

        monkeypatch.setattr(production_survival, "_memory", None)
        monkeypatch.setattr(production_survival, "_memory_path", None)
        store = production_survival.memory()
    with sqlite3.connect(store.path) as database:
        assert database.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_only'").fetchone() is None
    assert Path(store.path) == tmp_path / "orqevia-memory.db"
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == original_digest


def test_capability_observation_does_not_migrate_historical_memory(monkeypatch, tmp_path):
    from app import production_survival

    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ORQEVIA_MEMORY_DB", raising=False)
    monkeypatch.setattr(production_survival, "_probe", lambda url: False)
    legacy = tmp_path / "jarvis-memory.db"
    with sqlite3.connect(legacy) as database:
        database.execute("CREATE TABLE legacy_only(value TEXT)")
    original_digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
    assert production_survival.capability_status()["memory"] == "UNVERIFIED"
    assert not (tmp_path / "orqevia-memory.db").exists()
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == original_digest
