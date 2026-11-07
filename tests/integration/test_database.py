from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest

from healthtracker.infrastructure.sqlite.database import Database, default_database_path
from healthtracker.infrastructure.sqlite.errors import StorageBusy, StorageError


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_manager_reopens_private_database_and_invalidates_old_session(tmp_path):
    path = tmp_path / "db.sqlite3"
    with Database(path, clock=lambda: NOW) as db:
        with db.read_snapshot() as reader:
            token = reader.token
        assert db.is_current(token)
        with pytest.raises(StorageError):
            reader.ensure_active()
    with Database(path, clock=lambda: NOW) as db:
        assert not db.is_current(token)


def test_only_one_manager_writes_a_file(tmp_path):
    path = tmp_path / "db.sqlite3"
    with Database(path) as first:
        with pytest.raises(StorageBusy):
            Database(path).initialize()
        with first.read_snapshot() as reader:
            assert reader.connection.execute("SELECT count(*) FROM scale_versions").fetchone()[0] == 9


def test_consistent_read_while_writer_waits_for_reader_then_generation_changes(tmp_path):
    with Database(tmp_path / "db.sqlite3", clock=lambda: NOW) as db:
        inserted = Event()
        def writer():
            with db.write() as session:
                session.connection.execute("INSERT INTO application_settings VALUES('test','1','2026-11-04T12:00:00.000000Z')")
                inserted.set()
        with ThreadPoolExecutor() as pool:
            with db.read_snapshot() as reader:
                token = reader.token
                assert reader.connection.execute("SELECT count(*) FROM application_settings").fetchone()[0] == 0
                future = pool.submit(writer)
                assert inserted.wait(1)
                # Ещё один запрос той же транзакции не видит незавершённую запись.
                assert reader.connection.execute("SELECT count(*) FROM application_settings").fetchone()[0] == 0
            future.result(timeout=3)
        assert not db.is_current(token)
        with db.read_snapshot() as reader:
            assert reader.connection.execute("SELECT count(*) FROM application_settings").fetchone()[0] == 1


def test_failed_transaction_does_not_advance_generation(tmp_path):
    with Database(tmp_path / "db.sqlite3") as db:
        with db.read_snapshot() as reader:
            token = reader.token
        with pytest.raises(RuntimeError):
            with db.write():
                raise RuntimeError("injected")
        assert db.is_current(token)


def test_nested_session_and_close_with_active_reader_rejected(tmp_path):
    with Database(tmp_path / "db.sqlite3") as db:
        with db.read_snapshot():
            with pytest.raises(StorageError):
                with db.write():
                    pass
            with pytest.raises(StorageBusy):
                db.close()


def test_default_path_only_calculated_not_created(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert default_database_path() == tmp_path / "data/healthtracker/healthtracker.sqlite3"
    assert not (tmp_path / "data").exists()
