from pathlib import Path

from app.path_migration import migrate_legacy_database


def test_legacy_database_is_copied_without_removing_rollback_bytes(tmp_path):
    legacy = tmp_path / "prime-spine.db"
    legacy.write_bytes(b"legacy")
    Path(str(legacy) + "-wal").write_bytes(b"wal")

    destination = migrate_legacy_database(tmp_path / "orqevia-spine.db", "prime-spine.db")

    assert destination.read_bytes() == b"legacy"
    assert Path(str(destination) + "-wal").read_bytes() == b"wal"
    assert legacy.read_bytes() == b"legacy"


def test_existing_current_database_is_never_overwritten(tmp_path):
    (tmp_path / "prime-spine.db").write_bytes(b"legacy")
    current = tmp_path / "orqevia-spine.db"
    current.write_bytes(b"current")

    result = migrate_legacy_database(current, "prime-spine.db")

    assert result == current
    assert current.read_bytes() == b"current"
