import hashlib
import sqlite3
from pathlib import Path

from scripts.sqlite_backup import (
    backup_one,
    discover_databases,
    integrity_report,
    restore_test,
    run_backup,
)


def _make_db(path, rows=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        db.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        for i in range(rows):
            db.execute("INSERT INTO parent (name) VALUES (?)", (f"row-{i}",))
            db.execute("INSERT INTO child (parent_id) VALUES (?)", (i + 1,))
    return path


def test_integrity_report_reads_tables_and_foreign_keys(tmp_path):
    path = _make_db(tmp_path / "data" / "objectives.db")
    report = integrity_report(path)
    assert report["integrity"] == "ok"
    assert report["foreign_key_violations"] == 0
    assert set(report["tables"]) == {"parent", "child"}
    assert report["row_counts"] == {"parent": 3, "child": 3}


def test_backup_preserves_rows_and_hashes(tmp_path):
    source = _make_db(tmp_path / "data" / "objectives.db")
    result = backup_one(source, tmp_path / "backups")
    backup = Path(result["backup"])
    assert backup.is_file()
    assert result["integrity"] == "ok"
    digest = hashlib.sha256()
    with backup.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    assert result["sha256"] == digest.hexdigest()
    with sqlite3.connect(backup) as db:
        count = db.execute("SELECT COUNT(*) FROM parent").fetchone()[0]
    assert count == 3


def test_restore_test_round_trips_row_counts(tmp_path):
    source = _make_db(tmp_path / "data" / "objectives.db", rows=5)
    result = backup_one(source, tmp_path / "backups")
    restored = restore_test(result["backup"], expected_row_counts={"parent": 5, "child": 5})
    assert restored["status"] == "PASS"
    assert restored["row_counts_match"] is True


def test_discover_databases_skips_wal_sidecars(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "a.db").write_bytes(b"")
    (root / "a.db-wal").write_bytes(b"")
    (root / "a.db-shm").write_bytes(b"")
    (root / "b.db").write_bytes(b"")
    assert [p.name for p in discover_databases(root)] == ["a.db", "b.db"]


def test_run_backup_produces_manifest(tmp_path):
    _make_db(tmp_path / "data" / "objectives.db")
    _make_db(tmp_path / "data" / "compute-queue.db")
    manifest = run_backup(tmp_path / "data", tmp_path / "backups")
    assert manifest["database_count"] == 2
    assert all(item["integrity"] == "ok" for item in manifest["databases"])
