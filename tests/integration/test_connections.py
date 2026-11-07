from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from healthtracker.infrastructure.sqlite.connections import connect, prepare_private_file, transaction
from healthtracker.infrastructure.sqlite.errors import ConstraintViolation, StorageError


@pytest.fixture
def path(tmp_path):
    file = tmp_path / "private" / "test.sqlite3"
    assert prepare_private_file(file)
    return file


def test_foreign_keys_commit_close_and_reopen(path):
    with connect(path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with transaction(connection, write=True):
            connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            connection.execute("CREATE TABLE child(id INTEGER REFERENCES parent(id))")
            connection.execute("INSERT INTO parent VALUES(1)")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with connect(path) as reopened:
        assert reopened.execute("SELECT id FROM parent").fetchone()[0] == 1
        with pytest.raises(ConstraintViolation):
            with transaction(reopened, write=True):
                reopened.execute("INSERT INTO child VALUES(2)")


def test_failure_rolls_back_schema_and_data(path):
    with connect(path) as connection:
        with pytest.raises(RuntimeError):
            with transaction(connection, write=True):
                connection.execute("CREATE TABLE scratch(value TEXT)")
                connection.execute("INSERT INTO scratch VALUES('private text')")
                raise RuntimeError("injected")
        assert connection.execute("SELECT name FROM sqlite_schema WHERE name='scratch'").fetchone() is None
        assert not connection.in_transaction


def test_readonly_cannot_write_and_does_not_create_missing_file(path):
    with pytest.raises(StorageError):
        with connect(path, readonly=True) as connection:
            connection.execute("CREATE TABLE forbidden(id INTEGER)")
    with pytest.raises(StorageError):
        with connect(path.parent / "missing.sqlite3"):
            pass
    assert not (path.parent / "missing.sqlite3").exists()


def test_connection_is_not_transferable_between_threads(path):
    with connect(path) as connection, ThreadPoolExecutor() as pool:
        with pytest.raises(sqlite3.ProgrammingError):
            pool.submit(connection.execute, "SELECT 1").result()


def test_files_private_and_existing_file_not_overwritten(path):
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert not prepare_private_file(path)
    path.chmod(0o644)
    with pytest.raises(StorageError):
        prepare_private_file(path)


def test_no_silent_nested_commit(path):
    with connect(path) as connection:
        with pytest.raises(StorageError):
            with transaction(connection, write=True):
                connection.execute("CREATE TABLE scratch(id INTEGER)")
                with transaction(connection, write=True):
                    pass
        assert connection.execute("SELECT name FROM sqlite_schema WHERE name='scratch'").fetchone() is None
