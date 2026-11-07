from dataclasses import replace
from datetime import UTC, datetime
import json

import pytest

from healthtracker.domain.scales import NUMERIC_SCALES_V1
from healthtracker.infrastructure.sqlite.connections import connect, prepare_private_file, transaction
from healthtracker.infrastructure.sqlite.errors import ConstraintViolation, MigrationBackupRequired, SchemaError, StorageError
from healthtracker.infrastructure.sqlite.migrations import MIGRATIONS, Migration, initialize_schema, validate_schema
from healthtracker.infrastructure.sqlite.schema import TABLES


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path):
    path = tmp_path / "schema.sqlite3"
    prepare_private_file(path)
    with connect(path) as connection:
        yield connection


def test_initial_schema_seed_versions_reopen_is_idempotent(connection):
    initialize_schema(connection, now=NOW)
    assert {r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")} == TABLES
    for scale in NUMERIC_SCALES_V1:
        row = connection.execute("SELECT definition FROM scale_versions WHERE scale_code=? AND version=1", (scale.code,)).fetchone()
        assert json.loads(row[0])["labels"] == list(scale.descriptions)
    initialize_schema(connection, now=NOW)
    assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    validate_schema(connection)


def test_initial_migration_failure_rolls_back_all_ddl_and_history(connection):
    broken = replace(MIGRATIONS[0], statements=MIGRATIONS[0].statements + ("INSERT INTO missing VALUES(1)",))
    with pytest.raises(StorageError):
        initialize_schema(connection, now=NOW, migrations=(broken,))
    assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
    initialize_schema(connection, now=NOW)


def test_post_migration_check_failure_rolls_back_version_and_schema(connection, monkeypatch):
    import healthtracker.infrastructure.sqlite.migrations as module
    def fail(connection, *args):
        assert connection.in_transaction
        assert connection.execute("SELECT version FROM schema_migrations").fetchone()[0] == 1
        assert len(connection.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall()) == 16
        raise SchemaError("injected check failure")
    monkeypatch.setattr(module, "validate_schema", fail)
    with pytest.raises(SchemaError):
        initialize_schema(connection, now=NOW)
    assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []


def test_existing_upgrade_requires_backup_and_future_schema_rejected(connection):
    initialize_schema(connection, now=NOW)
    pending = Migration(2, "0002_future", ("CREATE TABLE forbidden(id INTEGER)",))
    with pytest.raises(MigrationBackupRequired):
        initialize_schema(connection, now=NOW, migrations=(*MIGRATIONS, pending))
    assert connection.execute("SELECT name FROM sqlite_schema WHERE name='forbidden'").fetchone() is None
    with transaction(connection, write=True):
        connection.execute("UPDATE schema_migrations SET version=2")
    with pytest.raises(SchemaError):
        initialize_schema(connection, now=NOW)


def test_definitions_cannot_be_rewritten_or_deleted(connection):
    initialize_schema(connection, now=NOW)
    for statement in ("UPDATE scale_versions SET definition='{}'", "DELETE FROM scale_versions",
                      "UPDATE formula_versions SET version=2", "DELETE FROM formula_versions"):
        with pytest.raises(ConstraintViolation):
            with transaction(connection, write=True):
                connection.execute(statement)


def test_migration_sequences_and_transaction_breaking_commands_rejected(connection):
    for plan in ((Migration(2, "bad", ("SELECT 1",)),),
                 (replace(MIGRATIONS[0], statements=("COMMIT",)),)):
        with pytest.raises(SchemaError):
            initialize_schema(connection, now=NOW, migrations=plan)
    assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
