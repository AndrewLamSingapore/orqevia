"""Verified SQLite backup, integrity verification and restore testing.

Non-destructive by construction: backups use SQLite's online backup API with a
read-only source connection, verification opens databases read-only, and
restore testing writes into a scratch file so no live database is mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def discover_databases(data_dir: str | Path) -> list[Path]:
    root = Path(data_dir)
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.glob("*.db")
        if not path.name.endswith(("-wal", "-shm", "-journal"))
    )


def integrity_report(db_path: str | Path) -> dict:
    path = Path(db_path)
    with closing(sqlite3.connect(_read_only_uri(path), uri=True, timeout=5)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        tables = sorted(
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        row_counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    return {
        "db": str(path),
        "integrity": str(integrity),
        "foreign_key_violations": len(violations),
        "tables": tables,
        "row_counts": row_counts,
    }


def backup_one(src: str | Path, backup_dir: str | Path) -> dict:
    source = Path(src)
    dest_dir = Path(backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{source.name}.{_utc_stamp()}.bak"
    with closing(sqlite3.connect(_read_only_uri(source), uri=True, timeout=20)) as live:
        with closing(sqlite3.connect(dest)) as target:
            live.backup(target)
    return {
        "source": str(source),
        "backup": str(dest),
        "sha256": _sha256(dest),
        "integrity": integrity_report(dest)["integrity"],
    }


def restore_test(backup_path: str | Path, expected_row_counts: dict | None = None) -> dict:
    backup = Path(backup_path)
    if not backup.is_file():
        return {"backup": str(backup), "status": "MISSING"}
    with tempfile.TemporaryDirectory(prefix="orqevia-restore-test-") as tmp:
        restored = Path(tmp) / "restored.db"
        with closing(sqlite3.connect(_read_only_uri(backup), uri=True, timeout=20)) as source:
            with closing(sqlite3.connect(restored)) as target:
                source.backup(target)
        report = integrity_report(restored)
        report["status"] = "PASS" if report["integrity"] == "ok" else "FAIL"
        if expected_row_counts is not None:
            report["row_counts_match"] = report["row_counts"] == expected_row_counts
        return report


def run_backup(data_dir: str | Path, backup_dir: str | Path) -> dict:
    databases = [backup_one(path, backup_dir) for path in discover_databases(data_dir)]
    manifest = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "source_data_dir": str(Path(data_dir).resolve()),
        "backup_dir": str(Path(backup_dir).resolve()),
        "database_count": len(databases),
        "databases": databases,
    }
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="back up every *.db under a data directory")
    backup.add_argument("data_dir")
    backup.add_argument("--backup-dir", required=True)

    verify = sub.add_parser("verify", help="read-only integrity/foreign-key check")
    verify.add_argument("db_path")

    restore = sub.add_parser("restore-test", help="restore a backup to a scratch file and verify")
    restore.add_argument("backup_path")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "backup":
        print(json.dumps(run_backup(args.data_dir, args.backup_dir), indent=2, sort_keys=True))
    elif args.command == "verify":
        print(json.dumps(integrity_report(args.db_path), indent=2, sort_keys=True))
    elif args.command == "restore-test":
        print(json.dumps(restore_test(args.backup_path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
