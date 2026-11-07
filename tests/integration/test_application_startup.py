from datetime import UTC, datetime

import pytest

from healthtracker.application.session import ApplicationSession
from healthtracker.domain.records import MoodRecord
from healthtracker.infrastructure.sqlite.connections import connect, transaction
from healthtracker.infrastructure.sqlite.database import Database, default_database_path


def test_application_creates_xdg_database_and_reopens_without_losing_records(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    path = default_database_path()
    assert not path.exists()
    db = Database(path)
    application = ApplicationSession(db)
    assert application.open()
    now = datetime.now(UTC)
    with db.write() as session:
        record_id = session.mood.create(MoodRecord(observed_at=now, score=0, created_at=now, updated_at=now))
    assert application.close()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    reopened = Database(path)
    application = ApplicationSession(reopened)
    assert application.open()
    with reopened.read_snapshot() as session:
        assert session.mood.get(record_id).value.score == 0
    application.close()


@pytest.mark.parametrize("damage", ["future", "corrupted"])
def test_incompatible_or_corrupted_file_stays_intact_and_no_fallback_created(tmp_path, damage):
    path = tmp_path / "database.sqlite3"
    with Database(path):
        pass
    if damage == "future":
        with connect(path) as connection:
            with transaction(connection, write=True):
                connection.execute("UPDATE schema_migrations SET version=2")
    else:
        with path.open("r+b") as file:
            file.write(b"NOT A SQLITE DB!")
    before = path.read_bytes()
    application = ApplicationSession(Database(path))
    assert not application.open()
    assert application.error_message
    assert not application.storage_available
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.sqlite3")) == [path]
    application.close()


def test_busy_existing_database_is_not_replaced(tmp_path):
    path = tmp_path / "database.sqlite3"
    with Database(path):
        application = ApplicationSession(Database(path))
        assert not application.open()
        assert "другим экземпляром" in application.error_message
        application.close()
